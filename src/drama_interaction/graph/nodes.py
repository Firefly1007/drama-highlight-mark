"""单集 V2 工作流节点。"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from drama_interaction.context import DramaContext
from drama_interaction.evidence.adapter import adapt_file, parse_time_str_to_ms
from drama_interaction.evidence.render import render_evidence_timeline
from drama_interaction.evidence.service import EvidenceService
from drama_interaction.llm import LLMGatewayError, LLMNetworkExhaustedError
from drama_interaction.scheduling.constraints import (
    analyze_constraints,
    assert_final_interactions,
    render_candidate,
)
from drama_interaction.schemas.candidate import Candidate, SpecialistResult
from drama_interaction.schemas.evidence import EvidenceDocument
from drama_interaction.schemas.interaction import FinalInteraction
from drama_interaction.specialists import (
    DeferredVoteSpecialist,
    EmotionButtonSpecialist,
    InstantVoteSpecialist,
    RepeatKeylineSpecialist,
    SideCommentSpecialist,
)
from drama_interaction.validation.repair import repair_candidate
from drama_interaction.validation.rules import validate_candidate

from .state import (
    SPECIALIST_TYPES,
    SpecialistBranchInput,
    SpecialistBranchOutput,
    SpecialistBranchState,
    WorkflowState,
    state_to_jsonable,
)


def _now() -> str:
    """返回 UTC 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _document(state: Mapping[str, Any]) -> EvidenceDocument:
    """读取已适配的共享证据。"""
    value = state.get("evidence")
    if not isinstance(value, EvidenceDocument):
        raise ValueError("工作流缺少 EvidenceDocument")
    return value


def _drama_context(state: Mapping[str, Any]) -> DramaContext:
    """读取已加载的剧集上下文。"""
    value = state.get("drama_context")
    if not isinstance(value, DramaContext):
        raise ValueError("工作流缺少 DramaContext")
    return value


def _input_path(state: Mapping[str, Any]) -> Path:
    """读取已校验的 V1 输入文件。"""
    value = state.get("input_path")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("工作流缺少 input_path")
    return Path(value)


def _write_json_atomic(value: Any, output_path: str | Path) -> Path:
    """原子写入 JSON 运行产物。"""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(state_to_jsonable(value), file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return target


def derive_episode_duration_ms(input_path: str | Path) -> int:
    """从 V1 输入的合法 end 取得临时集长。"""
    source = Path(input_path)
    if not source.is_file():
        raise FileNotFoundError(f"输入文件不存在: {source}")
    try:
        segments = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"输入 JSON 无法解析: {source}: {error.msg}") from error
    if not isinstance(segments, list):
        raise ValueError("V1 片段 JSON 顶层必须是数组")

    ends: list[int] = []
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, Mapping):
            raise ValueError(f"V1 片段 {index} 必须是对象")
        try:
            ends.append(parse_time_str_to_ms(segment["end"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"V1 片段 {index} 的 end 时间码无效") from error
    if not ends or max(ends) <= 0:
        raise ValueError("V1 片段缺少大于 0 的 end 时间码")
    return max(ends)


def media_prepare_node(state: WorkflowState) -> dict[str, Any]:
    """写入本轮 V1 临时集长。"""
    context = _drama_context(state)
    duration = derive_episode_duration_ms(_input_path(state))
    timestamp = _now()
    return {
        "drama_context": context,
        "episode_duration_ms": duration,
        "status": "running",
        "updated_at": timestamp,
        "execution": {"updated_at": timestamp},
        "metrics": {"episode_duration_ms": duration},
    }


def adapter_node(state: WorkflowState) -> dict[str, Any]:
    """把 V1 输入适配为共享 EvidenceDocument。"""
    context = _drama_context(state)
    duration = state.get("episode_duration_ms")
    if type(duration) is not int or duration <= 0:
        raise ValueError("adapter_node 需要有效的 episode_duration_ms")
    document, evidence_path = adapt_file(
        _input_path(state),
        duration,
        state.get("evidence_dir"),
    )
    timestamp = _now()
    return {
        "drama_context": context,
        "evidence": document,
        "evidence_path": str(evidence_path) if evidence_path else None,
        "status": "running",
        "updated_at": timestamp,
        "execution": {"updated_at": timestamp},
        "metrics": {
            "transcript_segment_count": len(document.transcript_segments),
            "observation_count": len(document.observations),
        },
    }


def has_evidence(state: WorkflowState) -> str:
    """空证据直接输出空数组，避免无意义模型调用。"""
    document = _document(state)
    return "render_evidence" if (
        document.transcript_segments or document.observations
    ) else "final_check"


def render_evidence_node(state: WorkflowState, *, settings: Any) -> dict[str, Any]:
    """为五个 Specialist 构造相互隔离的时间线。"""
    document = _document(state)
    timelines = {
        specialist: render_evidence_timeline(
            document,
            specialist,
            state.get("derived_evidence", {}).get(specialist, ()),
            settings.min_reported_gap_ms,
        )
        for specialist in SPECIALIST_TYPES
    }
    return {"specialist_timelines": timelines}


def _specialist(
    specialist_type: str,
    gateway: Any,
    *,
    drama_context: DramaContext,
    evidence_service: EvidenceService,
    existing_derived: Sequence[Any] = (),
) -> Any:
    """创建绑定当前分支证据的 Specialist。"""
    classes = {
        "emotion_button": EmotionButtonSpecialist,
        "repeat_keyline": RepeatKeylineSpecialist,
        "instant_vote": InstantVoteSpecialist,
        "deferred_vote": DeferredVoteSpecialist,
        "side_comment": SideCommentSpecialist,
    }
    return classes[specialist_type](
        gateway,
        drama_context=drama_context,
        evidence_service=evidence_service,
        existing_derived=existing_derived,
    )


def _event(event_id: str, event_type: str, reason: str, **details: Any) -> dict[str, Any]:
    """构造终端 HITL 可显示的最小事件。"""
    actions = {
        "branch_failure": ["drop"],
        "network_exhausted": ["drop"],
        "candidate_review": ["accept", "edit", "drop"],
        "semantic_selection": ["edit", "drop"],
        "constraint_review": ["drop"],
    }
    return {
        "event_id": event_id,
        "event_type": event_type,
        "reason": reason,
        "actions": actions[event_type],
        **details,
    }


def specialist_node(
    state: SpecialistBranchState,
    *,
    specialist_type: str,
    gateway: Any,
) -> dict[str, Any]:
    """运行一个 Specialist 子图分支，并隔离其校验与修复失败。"""
    document = _document(state)
    drama_context = _drama_context(state)
    timeline = state.get("specialist_timelines", {}).get(specialist_type, "")
    branch_derived = state.get("derived_evidence", {}).get(specialist_type, ())
    try:
        specialist = _specialist(
            specialist_type,
            gateway,
            drama_context=drama_context,
            evidence_service=EvidenceService(document),
            existing_derived=branch_derived,
        )
        result = specialist.run(timeline)
    except LLMNetworkExhaustedError as error:
        return {
            "branch_results": {
                specialist_type: {"status": "network_exhausted", "error": str(error)}
            },
            "hitl_queue": [
                _event(
                    f"network:{specialist_type}",
                    "network_exhausted",
                    "LLM 网络重试已耗尽，分支等待人工处理",
                    specialist_type=specialist_type,
                    error=str(error),
                )
            ],
        }
    except (LLMGatewayError, TypeError, ValueError) as error:
        return {
            "branch_results": {
                specialist_type: {"status": "failed", "error": str(error)}
            },
            "hitl_queue": [
                _event(
                    f"branch:{specialist_type}",
                    "branch_failure",
                    "Specialist 分支失败，已保留其他分支结果",
                    specialist_type=specialist_type,
                    error=str(error),
                )
            ],
        }

    accepted: list[Candidate] = []
    repairs: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for index, candidate in enumerate(result.candidates, start=1):
        errors = validate_candidate(
            candidate,
            document,
            branch_derived,
            specialist_type=specialist_type,
            existing_candidates=accepted,
        )
        if not errors:
            accepted.append(candidate)
            continue
        try:
            outcome = repair_candidate(
                candidate,
                errors,
                specialist=specialist,
                evidence_timeline=timeline,
                evidence_document=document,
                derived_observations=branch_derived,
            )
        except LLMNetworkExhaustedError as error:
            events.append(
                _event(
                    f"network:{specialist_type}:{index}",
                    "network_exhausted",
                    "定向重生的 LLM 网络重试已耗尽",
                    specialist_type=specialist_type,
                    candidate=state_to_jsonable(candidate),
                    error=str(error),
                )
            )
            continue
        except (LLMGatewayError, TypeError, ValueError) as error:
            events.append(
                _event(
                    f"candidate:{specialist_type}:{index}",
                    "candidate_review",
                    f"定向重生失败: {error}",
                    specialist_type=specialist_type,
                    candidate=state_to_jsonable(candidate),
                    errors=state_to_jsonable(errors),
                )
            )
            continue
        repairs.append(state_to_jsonable(outcome))
        if outcome.candidate is not None:
            accepted.append(outcome.candidate)
        elif outcome.hitl_event is not None:
            events.append(
                _event(
                    f"candidate:{specialist_type}:{index}",
                    "candidate_review",
                    outcome.hitl_event.reason,
                    specialist_type=specialist_type,
                    candidate=outcome.hitl_event.candidate,
                    errors=state_to_jsonable(outcome.hitl_event.errors),
                    attempts=state_to_jsonable(outcome.hitl_event.attempts),
                )
            )

    resolved = SpecialistResult(
        specialist_type=specialist_type,
        candidates=accepted,
        abstentions=result.abstentions,
    )
    return {
        "specialist_results": {specialist_type: resolved},
        "branch_results": {
            specialist_type: {
                "status": "completed",
                "candidate_count": len(accepted),
                "abstention_count": len(result.abstentions),
            }
        },
        "repair_log": repairs,
        "hitl_queue": events,
    }


def build_specialist_subgraph(
    specialist_type: str,
    gateway: Any,
) -> Any:
    """构造一个可嵌入父图的 Specialist 编译子图。"""

    graph = StateGraph(
        SpecialistBranchState,
        input_schema=SpecialistBranchInput,
        output_schema=SpecialistBranchOutput,
    )

    def run_branch(state: SpecialistBranchState) -> dict[str, Any]:
        """运行当前类型的分支节点。"""

        return specialist_node(
            state,
            specialist_type=specialist_type,
            gateway=gateway,
        )

    graph.add_node("run", run_branch)
    graph.add_edge(START, "run")
    graph.add_edge("run", END)
    return graph.compile(name=f"specialist_{specialist_type}")


def pool_node(state: WorkflowState) -> dict[str, Any]:
    """按稳定顺序为局部合法候选分配 ID。"""
    pending: list[Candidate] = []
    for specialist_type in SPECIALIST_TYPES:
        result = state.get("specialist_results", {}).get(specialist_type)
        if result is None:
            continue
        pending.extend(result.candidates)
    pending.extend(state.get("manual_candidates", ()))
    if any(candidate.candidate_id is not None for candidate in pending):
        raise ValueError("入池 Candidate 不能预先携带 candidate_id")
    assigned = [
        candidate.model_copy(update={"candidate_id": f"candidate-{index:04d}"})
        for index, candidate in enumerate(pending, start=1)
    ]
    return {
        "candidate_pool": assigned,
        "metrics": {"candidate_pool_count": len(assigned)},
    }


def render_node(state: WorkflowState, *, settings: Any) -> dict[str, Any]:
    """把候选锚点转换为最终毫秒字段。"""
    document = _document(state)
    rendered: dict[str, FinalInteraction] = {}
    failures: list[dict[str, Any]] = []
    for candidate in state.get("candidate_pool", ()):
        if candidate.candidate_id is None:
            raise ValueError("候选池中的 Candidate 必须已有 candidate_id")
        try:
            rendered[candidate.candidate_id] = render_candidate(
                candidate,
                document,
                state.get("derived_evidence", {}).get(candidate.specialist_type, ()),
                execution_id=state["execution_id"],
                config=settings,
            )
        except ValueError as error:
            failures.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "code": "render_invalid",
                    "message": str(error),
                }
            )
    ordered = sorted(
        rendered.items(),
        key=lambda item: (item[1].show_at, item[1].duration_ms, item[0]),
    )
    rendered = {
        candidate_id: interaction.model_copy(update={"id": index})
        for index, (candidate_id, interaction) in enumerate(ordered, start=1)
    }
    return {
        "rendered_candidates": rendered,
        "constraints_report": {"render_failures": failures},
    }


def constraints_node(state: WorkflowState, *, settings: Any) -> dict[str, Any]:
    """先执行所有可确定的全局约束。"""
    rendered = state.get("rendered_candidates", {})
    report = analyze_constraints(
        rendered,
        episode_duration_ms=state["episode_duration_ms"],
        config=settings,
    )
    candidate_for_interaction = {
        str(interaction.id): candidate_id
        for candidate_id, interaction in rendered.items()
    }
    invalid_ids = {
        candidate_id
        for issue in report.invalid
        for candidate_id in issue.candidate_ids
        if candidate_id in rendered
    }
    eligible_ids = [
        candidate_for_interaction[str(interaction.id)]
        for interaction in report.eligible
        if candidate_for_interaction[str(interaction.id)] not in invalid_ids
    ]
    groups = [tuple(group) for group in report.conflict_groups]
    conflicted = {candidate_id for group in groups for candidate_id in group}
    return {
        "constraints_report": {
            "render_failures": state.get("constraints_report", {}).get("render_failures", []),
            "invalid": state_to_jsonable(report.invalid),
            "eligible_ids": eligible_ids,
            "conflict_groups": [list(group) for group in groups],
        },
        "selected_candidate_ids": [
            candidate_id for candidate_id in eligible_ids if candidate_id not in conflicted
        ],
    }


def semantic_node(state: WorkflowState, *, gateway: Any, settings: Any) -> dict[str, Any]:
    """仅在真实冲突存在时交给语义调度器。"""
    groups = state.get("constraints_report", {}).get("conflict_groups", [])
    if not groups:
        return {"scheduler_decision": {"status": "skipped"}}

    from drama_interaction.scheduling.semantic import select_candidate_ids

    timelines = {
        candidate.candidate_id: _evidence_excerpt(
            state.get("specialist_timelines", {}).get(candidate.specialist_type, ""),
            candidate.evidence_ids,
        )
        for candidate in state.get("candidate_pool", ())
        if candidate.candidate_id in state["rendered_candidates"]
    }
    result = select_candidate_ids(
        gateway,
        state["rendered_candidates"],
        groups,
        timelines,
        _drama_context(state),
        settings,
    )
    if result.requires_human:
        return {
            "scheduler_decision": state_to_jsonable(result),
            "hitl_queue": [
                _event(
                    "semantic:selection",
                    "semantic_selection",
                    result.reason,
                    candidate_ids=sorted({item for group in groups for item in group}),
                    conflict_groups=[list(group) for group in groups],
                )
            ],
        }
    selected = [
        *state.get("selected_candidate_ids", ()),
        *result.selected_candidate_ids,
    ]
    return {
        "scheduler_decision": state_to_jsonable(result),
        "selected_candidate_ids": selected,
    }


def _evidence_excerpt(timeline: str, evidence_ids: Sequence[str]) -> str:
    """只把候选引用的证据行发送给语义调度器。"""
    markers = tuple(f"[{evidence_id}]" for evidence_id in evidence_ids)
    return "\n".join(
        line for line in timeline.splitlines() if line.lstrip().startswith(markers)
    )


def _pending_hitl(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """筛除已由终端处理的 HITL 事件。"""
    resolved = {
        item.get("event_id")
        for item in state.get("hitl_resolutions", ())
        if isinstance(item, Mapping)
    }
    return [
        item
        for item in state.get("hitl_queue", ())
        if item.get("event_id") not in resolved
    ]


def needs_human(state: WorkflowState) -> str:
    """有未处理事件时暂停，否则继续终检。"""
    return "human_gate" if _pending_hitl(state) else "final_check"


def route_after_pool(state: WorkflowState) -> str:
    """分支事件在候选渲染前统一暂停。"""
    return "human_gate" if _pending_hitl(state) else "render"


def route_after_final(state: WorkflowState) -> str:
    """终检失败时转人工，否则结束图。"""
    return "human_gate" if _pending_hitl(state) else "end"


def _candidate_from_decision(
    decision: Mapping[str, Any],
    event: Mapping[str, Any],
) -> Candidate | None:
    """提取人工确认或编辑后的候选。"""
    if decision.get("action") == "drop":
        return None
    source = decision.get("replacement") if decision.get("action") == "edit" else event.get("candidate")
    if not isinstance(source, Mapping):
        return None
    return Candidate.model_validate(source)


def human_gate_node(state: WorkflowState) -> dict[str, Any]:
    """暂停并应用终端提交的 accept、edit 或 drop。"""
    events = _pending_hitl(state)
    if not events:
        return {}
    payload = interrupt({"events": events})
    decisions = payload.get("decisions") if isinstance(payload, Mapping) else None
    if not isinstance(decisions, list):
        raise ValueError("HITL 恢复载荷必须包含 decisions 数组")

    by_event = {
        item.get("event_id"): item
        for item in events
        if isinstance(item.get("event_id"), str)
    }
    accepted: list[Candidate] = []
    selected = list(state.get("selected_candidate_ids", ()))
    resolutions: list[dict[str, Any]] = []
    new_events: list[dict[str, Any]] = []
    decided_ids: set[str] = set()
    document = _document(state)
    for decision in decisions:
        if not isinstance(decision, Mapping):
            raise ValueError("HITL decision 必须是对象")
        item = decision.get("item")
        event_id = item.get("event_id") if isinstance(item, Mapping) else None
        event = by_event.get(event_id)
        action = decision.get("action")
        if event is None or action not in event["actions"]:
            raise ValueError("HITL decision 不对应当前待处理事件")
        if event_id in decided_ids:
            raise ValueError("HITL decision 不得重复处理同一事件")
        decided_ids.add(event_id)
        resolutions.append({"event_id": event_id, "action": action})

        if event["event_type"] == "candidate_review":
            try:
                candidate = _candidate_from_decision(decision, event)
                if candidate is None:
                    continue
                if candidate.candidate_id is not None:
                    raise ValueError("人工候选不能携带 candidate_id")
                errors = validate_candidate(
                    candidate,
                    document,
                    state.get("derived_evidence", {}).get(candidate.specialist_type, ()),
                    specialist_type=candidate.specialist_type,
                    existing_candidates=[*state.get("candidate_pool", ()), *accepted],
                )
                if errors:
                    raise ValueError("；".join(error.message for error in errors))
                accepted.append(candidate)
            except (TypeError, ValueError) as error:
                new_events.append(
                    _event(
                        f"{event_id}:edit",
                        "candidate_review",
                        f"人工候选仍不合法: {error}",
                        specialist_type=event.get("specialist_type"),
                        candidate=decision.get("replacement") or event.get("candidate"),
                    )
                )
        elif event["event_type"] == "semantic_selection":
            contested = set(event.get("candidate_ids", ()))
            if action == "edit":
                replacement = decision.get("replacement")
                keep_ids = (
                    replacement.get("selected_candidate_ids")
                    if isinstance(replacement, Mapping)
                    else None
                )
                groups = event.get("conflict_groups")
                if (
                    not isinstance(keep_ids, list)
                    or any(not isinstance(candidate_id, str) for candidate_id in keep_ids)
                    or len(keep_ids) != len(set(keep_ids))
                    or set(keep_ids) - contested
                    or not isinstance(groups, list)
                    or not all(isinstance(group, list) for group in groups)
                    or any(
                        len(set(keep_ids).intersection(group)) > 1
                        for group in groups
                    )
                ):
                    raise ValueError(
                        "语义调度 edit 必须提交合法 selected_candidate_ids"
                    )
                selected.extend(keep_ids)
            # drop 不保留未被语义确认的冲突候选。
        elif event["event_type"] == "constraint_review":
            contested = set(event.get("candidate_ids", ()))
            selected = [candidate_id for candidate_id in selected if candidate_id not in contested]

    update: dict[str, Any] = {
        "hitl_resolutions": resolutions,
        "status": "running",
        "updated_at": _now(),
        "repool_after_human": bool(accepted),
    }
    if new_events:
        update["hitl_queue"] = new_events
    if accepted:
        update["manual_candidates"] = accepted
    if selected != state.get("selected_candidate_ids", []):
        update["selected_candidate_ids"] = selected
    return update


def route_after_human(state: WorkflowState) -> str:
    """人工新增候选后重跑纯确定性下游节点。"""
    if _pending_hitl(state):
        return "human_gate"
    if not state.get("rendered_candidates"):
        return "pool"
    return "render" if state.get("repool_after_human") else "final_check"


def final_check_node(state: WorkflowState, *, settings: Any) -> dict[str, Any]:
    """终检、排序并写出后端消费 JSON。"""
    render_failures = state.get("constraints_report", {}).get("render_failures", [])
    render_event_id = "render:failures"
    if render_failures and render_event_id not in {
        item.get("event_id")
        for item in state.get("hitl_resolutions", ())
        if isinstance(item, Mapping)
    }:
        return {
            "hitl_queue": [
                _event(
                    render_event_id,
                    "constraint_review",
                    "；".join(
                        str(failure.get("message", "候选渲染失败"))
                        for failure in render_failures
                        if isinstance(failure, Mapping)
                    ),
                    candidate_ids=[
                        failure["candidate_id"]
                        for failure in render_failures
                        if isinstance(failure, Mapping)
                        and isinstance(failure.get("candidate_id"), str)
                    ],
                )
            ]
        }
    selected_ids = state.get("selected_candidate_ids")
    rendered = state.get("rendered_candidates", {})
    if selected_ids is None:
        selected_ids = list(rendered)
    interactions = [rendered[candidate_id] for candidate_id in selected_ids if candidate_id in rendered]
    interactions.sort(key=lambda item: (item.show_at, item.duration_ms, item.id))
    interactions = [
        interaction.model_copy(update={"id": index})
        for index, interaction in enumerate(interactions, start=1)
    ]
    try:
        assert_final_interactions(
            interactions,
            episode_duration_ms=state["episode_duration_ms"],
            config=settings,
        )
    except ValueError as error:
        return {
            "hitl_queue": [
                _event(
                    f"final:constraints:{len(state.get('hitl_queue', ())) + 1}",
                    "constraint_review",
                    f"最终确定性校验失败: {error}",
                    candidate_ids=selected_ids,
                )
            ]
        }
    final = interactions
    output_dir = state.get("output_dir")
    output_path: Path | None = None
    if isinstance(output_dir, str) and output_dir:
        source = _input_path(state)
        output_path = Path(output_dir) / source.parent.name / f"{source.stem}.json"
        _write_json_atomic(
            [item.model_dump(mode="json", exclude_none=True) for item in final],
            output_path,
        )
    run_dir = state.get("run_dir")
    if isinstance(run_dir, str) and state.get("derived_evidence"):
        _write_json_atomic(state["derived_evidence"], Path(run_dir) / "evidence-derived.json")
    timestamp = _now()
    result: dict[str, Any] = {
        "final_interactions": final,
        "status": "completed",
        "updated_at": timestamp,
        "execution": {"updated_at": timestamp, "status": "completed"},
        "metrics": {"final_interaction_count": len(final)},
    }
    if output_path is not None:
        result["output_path"] = str(output_path)
    return result


__all__ = [
    "adapter_node",
    "build_specialist_subgraph",
    "constraints_node",
    "derive_episode_duration_ms",
    "final_check_node",
    "has_evidence",
    "human_gate_node",
    "media_prepare_node",
    "needs_human",
    "pool_node",
    "render_evidence_node",
    "render_node",
    "route_after_final",
    "route_after_human",
    "route_after_pool",
    "semantic_node",
    "specialist_node",
]
