"""五类 Specialist 的公共 Agent 执行骨架。"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import tool
from pydantic import BaseModel, ValidationError

from drama_interaction.config import (
    SPECIALIST_FOCUS_PROMPTS,
    SPECIALIST_REGENERATION_PROMPT_TEMPLATE,
    SPECIALIST_SYSTEM_PROMPT,
    SPECIALIST_USER_PROMPT_TEMPLATE,
)
from drama_interaction.context import DramaContext
from drama_interaction.evidence.service import EvidenceService
from drama_interaction.llm import LLMGateway, LLMGatewayError, LLMNetworkExhaustedError
from drama_interaction.schemas.candidate import (
    Abstention,
    Candidate,
    SpecialistResult,
)
from drama_interaction.schemas.evidence import DerivedObservation

_VISIBLE_EVIDENCE_ID = re.compile(r"(?<![A-Za-z0-9_])[TOD][1-9]\d*(?![A-Za-z0-9_])")


class BaseSpecialist:
    """封装固定类型 Specialist 的 Agent、取证工具和候选校验。"""

    specialist_type = ""

    def __init__(
        self,
        gateway: LLMGateway,
        *,
        drama_context: DramaContext,
        evidence_service: EvidenceService,
        existing_derived: Sequence[DerivedObservation] = (),
    ) -> None:
        """创建绑定当前分支证据的 Specialist Agent。"""
        if not self.specialist_type:
            raise ValueError("BaseSpecialist 必须声明 specialist_type")

        self.gateway = gateway
        self.drama_context = drama_context
        self.evidence_service = evidence_service
        self.existing_derived = tuple(existing_derived)
        self.inspect_span_tool = self._build_inspect_span_tool()
        self.agent = create_agent(
            model=gateway.model,
            tools=[self.inspect_span_tool],
            system_prompt=self._system_prompt(),
            response_format=ToolStrategy(SpecialistResult),
            name=f"specialist_{self.specialist_type}",
        )
        self.last_raw_response: Any = None
        self.last_error: str | None = None

    def run(self, evidence_timeline: str) -> SpecialistResult:
        """运行 Agent，返回当前 Specialist 的结构化结果。"""
        self.last_raw_response = None
        self.last_error = None
        if not evidence_timeline.strip():
            return self._abstain("当前分支证据时间线为空")

        try:
            result = self._invoke_result(
                self._generation_prompt(evidence_timeline),
                call_label=f"specialist:{self.specialist_type}",
            )
            return self._validate_result(result, evidence_timeline)
        except LLMNetworkExhaustedError:
            # 网络重试耗尽交给图层进入 HITL。
            raise
        except (LLMGatewayError, TypeError, ValueError, ValidationError) as exc:
            return self._abstain(self._failure_reason("Agent 结构化输出无效", exc))

    def regenerate_one(
        self,
        candidate: Candidate,
        errors: Sequence[BaseModel],
        evidence_timeline: str,
    ) -> Candidate | None:
        """用同一 Agent 根据局部证据重生一条候选。"""
        self.last_raw_response = None
        self.last_error = None
        if not evidence_timeline.strip():
            self.last_error = "局部证据时间线为空"
            return None
        if candidate.specialist_type != self.specialist_type:
            self.last_error = "候选类型与当前 Specialist 不一致"
            return None

        try:
            result = self._invoke_result(
                self._regeneration_prompt(candidate, errors, evidence_timeline),
                call_label=f"specialist:{self.specialist_type}:regenerate",
            )
            if result.abstentions or len(result.candidates) != 1:
                raise ValueError("定向重生必须只返回一条候选且不得弃权")
            return self._validate_candidate(result.candidates[0], evidence_timeline)
        except LLMNetworkExhaustedError:
            # 网络重试耗尽交给图层进入 HITL。
            raise
        except (LLMGatewayError, TypeError, ValueError, ValidationError) as exc:
            self.last_error = self._failure_reason("单条 Agent 重生输出无效", exc)
            return None

    def _build_inspect_span_tool(self):
        """构造只绑定当前 Specialist 分支的取证工具。"""
        service = self.evidence_service
        specialist_type = self.specialist_type
        existing_derived = self.existing_derived

        @tool("inspect_span")
        def inspect_span(start_ms: int, end_ms: int, query: str) -> str:
            """查询当前 Specialist 分支指定时间范围内的补充证据。"""
            result = service.inspect_span(
                start_ms,
                end_ms,
                query,
                specialist=specialist_type,
                existing_derived=existing_derived,
            )
            return result.model_dump_json()

        return inspect_span

    def _system_prompt(self) -> str:
        """构造固定类型与证据边界提示。"""
        return (
            f"{SPECIALIST_SYSTEM_PROMPT}\n\n"
            f"当前 Specialist 类型固定为：{self.specialist_type}\n"
            f"类型专属规则：\n{SPECIALIST_FOCUS_PROMPTS[self.specialist_type]}"
        )

    def _generation_prompt(self, evidence_timeline: str) -> str:
        """构造整集生成输入，不规定文本 JSON 格式。"""
        context_json = json.dumps(
            self.drama_context.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            SPECIALIST_USER_PROMPT_TEMPLATE.replace(
                "{{SERIES_CONTEXT_JSON_MINIFIED}}", context_json
            ).replace("{{EVIDENCE_TIMELINE}}", evidence_timeline)
        )

    def _regeneration_prompt(
        self,
        candidate: Candidate,
        errors: Sequence[BaseModel],
        evidence_timeline: str,
    ) -> str:
        """构造只携带一条候选和局部证据的重生输入。"""
        errors_text = "\n".join(
            f"- {error.model_dump_json()}" for error in errors
        ) or "无结构化错误详情"
        context_json = json.dumps(
            self.drama_context.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            SPECIALIST_REGENERATION_PROMPT_TEMPLATE.replace(
                "{{SERIES_CONTEXT_JSON_MINIFIED}}", context_json
            )
            .replace("{{CANDIDATE_JSON}}", candidate.model_dump_json())
            .replace("{{ERRORS_TEXT}}", errors_text)
            .replace("{{EVIDENCE_TIMELINE}}", evidence_timeline)
        )

    def _invoke_result(self, prompt: str, *, call_label: str) -> SpecialistResult:
        """调用编译 Agent 并读取 ToolStrategy 结构化结果。"""
        response = self.gateway.invoke_agent(
            self.agent,
            {"messages": [{"role": "user", "content": prompt}]},
            call_label=call_label,
        )
        self.last_raw_response = response
        result = response.get("structured_response")
        if not isinstance(result, SpecialistResult):
            raise TypeError("Agent 未通过 SpecialistResult 工具提交结构化结果")
        if result.specialist_type != self.specialist_type:
            raise ValueError("SpecialistResult 类型与当前 Specialist 不一致")
        return result

    def _validate_result(
        self,
        result: SpecialistResult,
        evidence_timeline: str,
    ) -> SpecialistResult:
        """校验结构化结果中的当前分支证据引用。"""
        if not result.candidates and not result.abstentions:
            raise ValueError("Agent 未返回候选或明确弃权")
        candidates = [
            self._validate_candidate(candidate, evidence_timeline)
            for candidate in result.candidates
        ]
        return SpecialistResult(
            specialist_type=self.specialist_type,
            candidates=candidates,
            abstentions=result.abstentions,
        )

    def _validate_candidate(
        self,
        candidate: Candidate,
        evidence_timeline: str,
    ) -> Candidate:
        """验证候选类型、生成侧字段和当前分支证据可见性。"""
        if candidate.specialist_type != self.specialist_type:
            raise ValueError("候选类型与当前 Specialist 不一致")
        if candidate.candidate_id is not None:
            raise ValueError("生成侧 Candidate 的 candidate_id 必须为空")

        visible_ids = set(_VISIBLE_EVIDENCE_ID.findall(evidence_timeline))
        references = set(candidate.evidence_ids)
        for anchor in (candidate.trigger_anchor, candidate.reveal_anchor):
            if anchor is not None:
                if anchor.transcript_segment_id is not None:
                    references.add(anchor.transcript_segment_id)
                if anchor.observation_id is not None:
                    references.add(anchor.observation_id)
        missing = sorted(references - visible_ids)
        if missing:
            raise ValueError(f"候选引用了当前分支时间线不可见的证据: {missing}")
        return candidate

    def _abstain(self, reason: str) -> SpecialistResult:
        """构造显式弃权结果并保留失败原因。"""
        self.last_error = reason
        return SpecialistResult(
            specialist_type=self.specialist_type,
            abstentions=[Abstention(specialist_type=self.specialist_type, reason=reason)],
        )

    def _failure_reason(self, prefix: str, exc: Exception) -> str:
        """将 Agent 错误写成可审计原因。"""
        detail = str(exc).strip() or exc.__class__.__name__
        return f"{prefix}: {detail}；原始 Agent 返回已保留在 last_raw_response"


__all__ = ["BaseSpecialist"]
