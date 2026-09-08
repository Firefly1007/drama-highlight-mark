"""只处理真实展示冲突的语义调度。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, ConfigDict, Field

from drama_interaction.config import (
    SEMANTIC_SCHEDULER_SYSTEM_PROMPT,
    SEMANTIC_SCHEDULER_USER_PROMPT_TEMPLATE,
    Settings,
)
from drama_interaction.context import DramaContext
from drama_interaction.llm import LLMGateway, LLMGatewayError, LLMNetworkExhaustedError
from drama_interaction.schemas.interaction import FinalInteraction

from .constraints import intervals_conflict


class SemanticSelection(BaseModel):
    """语义调度结果；失败时明确标记为等待人工。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["deterministic", "selected", "waiting_for_human"]
    selected_candidate_ids: list[str] = Field(default_factory=list)
    reason: str | None = None
    raw_response: Any = None

    @property
    def requires_human(self) -> bool:
        """返回是否需要上层进入 HITL。"""

        return self.status == "waiting_for_human"


class SemanticDecision(BaseModel):
    """语义调度 Agent 通过工具提交的选择。"""

    model_config = ConfigDict(extra="forbid")

    selected_candidate_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


def _real_conflict_groups(
    candidates_by_id: Mapping[str, FinalInteraction],
    conflict_groups: Sequence[tuple[str, ...]],
) -> tuple[list[tuple[str, ...]], str | None]:
    """仅保留确实存在区间交集的冲突组，并检查候选标识。"""

    groups: list[tuple[str, ...]] = []
    for group in conflict_groups:
        if len(group) < 2:
            continue
        if any(candidate_id not in candidates_by_id for candidate_id in group):
            return [], f"冲突组包含不存在的 candidate_id: {group}"
        if any(
            intervals_conflict(
                candidates_by_id[group[left]], candidates_by_id[group[right]]
            )
            for left in range(len(group))
            for right in range(left + 1, len(group))
        ):
            groups.append(tuple(dict.fromkeys(group)))
    return groups, None


def _prompt(
    candidates_by_id: Mapping[str, FinalInteraction],
    conflict_groups: Sequence[tuple[str, ...]],
    evidence_timelines: Mapping[str, str],
    drama_context: DramaContext,
    config: Settings | None,
) -> tuple[str, str]:
    """构造只含冲突候选及其局部证据的提示词。"""

    ids = list(dict.fromkeys(candidate_id for group in conflict_groups for candidate_id in group))
    candidates = [
        {
            "candidate_id": candidate_id,
            "interaction": candidates_by_id[candidate_id].model_dump(mode="json"),
            "evidence_timeline": evidence_timelines.get(candidate_id, ""),
        }
        for candidate_id in ids
    ]
    scheduler_input = json.dumps(
        {
            "candidates": candidates,
            "conflict_groups": [list(group) for group in conflict_groups],
            "interaction_budget": (
                config.interaction_budget if config is not None else None
            ),
            "rule": "每个 conflict_group 至多选择一个 candidate_id；可全部舍弃。",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    context_json = json.dumps(
        drama_context.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    user_prompt = (
        SEMANTIC_SCHEDULER_USER_PROMPT_TEMPLATE.replace(
            "{{SERIES_CONTEXT_JSON_MINIFIED}}", context_json
        ).replace("{{SCHEDULER_INPUT_JSON}}", scheduler_input)
    )
    return SEMANTIC_SCHEDULER_SYSTEM_PROMPT, user_prompt


def _invalid_selection(
    response: SemanticDecision,
    allowed_ids: set[str],
    conflict_groups: Sequence[tuple[str, ...]],
    config: Settings | None,
) -> str | None:
    """验证模型返回的候选选择，不做静默裁剪。"""

    selected = response.selected_candidate_ids
    if len(selected) != len(set(selected)):
        return "selected_candidate_ids 不得包含重复 candidate_id"
    unknown = sorted(set(selected) - allowed_ids)
    if unknown:
        return f"模型选择了不存在或不在冲突集合中的 candidate_id: {unknown}"
    for group in conflict_groups:
        selected_in_group = set(selected).intersection(group)
        if len(selected_in_group) > 1:
            return f"冲突组不能同时保留多个候选: {sorted(selected_in_group)}"
    budget = config.interaction_budget if config is not None else None
    if budget is not None and len(selected) > int(budget):
        return f"模型选择数量 {len(selected)} 超过预算 {budget}"
    return None


def _build_agent(gateway: LLMGateway, system_prompt: str) -> Any:
    """创建一次语义选择 Agent。"""

    return create_agent(
        model=gateway.model,
        tools=[],
        system_prompt=system_prompt,
        response_format=ToolStrategy(SemanticDecision),
        name="semantic_scheduler",
    )


def select_candidate_ids(
    gateway: LLMGateway,
    candidates_by_id: Mapping[str, FinalInteraction],
    conflict_groups: Sequence[tuple[str, ...]],
    evidence_timelines: Mapping[str, str],
    drama_context: DramaContext,
    config: Settings | None = None,
) -> SemanticSelection:
    """在真实展示冲突时调用 LLM，返回合法候选 ID 或 HITL 结果。"""

    groups, group_error = _real_conflict_groups(candidates_by_id, conflict_groups)
    if group_error is not None:
        return SemanticSelection(status="waiting_for_human", reason=group_error)
    if not groups:
        # 没有真实冲突时完全跳过网络调用，确定性保留全部输入候选。
        return SemanticSelection(
            status="deterministic",
            selected_candidate_ids=list(candidates_by_id),
            reason="不存在需要语义取舍的展示区间冲突",
        )

    system_prompt, user_prompt = _prompt(
        candidates_by_id,
        groups,
        evidence_timelines,
        drama_context,
        config,
    )
    agent = _build_agent(gateway, system_prompt)
    try:
        result = gateway.invoke_agent(
            agent,
            {"messages": [{"role": "user", "content": user_prompt}]},
            call_label="scheduling.semantic",
        )
    except LLMNetworkExhaustedError as exc:
        return SemanticSelection(
            status="waiting_for_human",
            reason=f"LLM 网络重试耗尽: {exc}",
        )
    except (LLMGatewayError, ValueError, TypeError) as exc:
        return SemanticSelection(
            status="waiting_for_human",
            reason=f"LLM 语义调度失败: {exc}",
        )

    response = result.get("structured_response")
    if not isinstance(response, SemanticDecision):
        return SemanticSelection(
            status="waiting_for_human",
            reason="语义调度 Agent 未通过 SemanticDecision 工具提交结果",
            raw_response=result,
        )

    allowed_ids = {candidate_id for group in groups for candidate_id in group}
    error = _invalid_selection(response, allowed_ids, groups, config)
    if error is not None:
        return SemanticSelection(
            status="waiting_for_human",
            reason=error,
            raw_response=result,
        )
    selected = response.selected_candidate_ids
    return SemanticSelection(
        status="selected",
        selected_candidate_ids=list(selected),
        reason=response.reason,
        raw_response=result,
    )


__all__ = ["SemanticDecision", "SemanticSelection", "select_candidate_ids"]
