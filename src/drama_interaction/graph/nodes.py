"""单集 V2 工作流节点。"""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from langgraph.types import Send, interrupt
from openai import OpenAI

from drama_interaction.config import EVIDENCE_SLICE_CONCURRENCY, MODEL_SDK_MAX_RETRIES
from drama_interaction.context import DramaContext
from drama_interaction.evidence.extract import (
    frame_data_urls,
    run_qwen_audio_observer,
    run_qwen_ocr,
    run_qwen_vlm,
    separate_episode_audio,
    transcribe_episode_dialogue,
)
from drama_interaction.evidence.render import render_evidence_timeline
from drama_interaction.evidence.service import EvidenceService
from drama_interaction.llm import LLMGatewayError, LLMNetworkExhaustedError
from drama_interaction.media import (
    calculate_sample_timestamps_ms,
    calculate_slices,
    cut_audio_hard,
    extract_audio_flac,
    extract_frames,
    probe_video_duration_ms,
    slice_audio,
)
from drama_interaction.scheduling.constraints import (
    analyze_constraints,
    assert_final_interactions,
    render_candidate,
)
from drama_interaction.schemas.candidate import Candidate, SpecialistResult
from drama_interaction.schemas.evidence import EvidenceDocument, Observation
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
    SliceState,
    WorkflowState,
    state_to_jsonable,
    write_json_atomic,
)


def _now() -> str:
    """返回 UTC 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _document(state: Mapping[str, Any]) -> EvidenceDocument:
    """读取已提取的共享基线证据。"""
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
    """读取已校验的输入视频文件。"""
    value = state.get("input_path")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("工作流缺少 input_path")
    return Path(value)


def media_prepare_node(state: WorkflowState) -> dict[str, Any]:
    """探测主视频轨集长并写入工作流状态。"""
    context = _drama_context(state)
    path = _input_path(state)
    duration = probe_video_duration_ms(path)
    timestamp = _now()
    return {
        "drama_context": context,
        "episode_duration_ms": duration,
        "status": "running",
        "updated_at": timestamp,
        "execution": {"updated_at": timestamp},
        "metrics": {"episode_duration_ms": duration},
    }


def extract_mix_node(state: WorkflowState) -> dict[str, Any]:
    """从原始视频抽取本次分离需要的混音 FLAC。"""
    mix_path = extract_audio_flac(
        _input_path(state), Path(state["run_dir"]) / "mix.flac"
    )
    return {"mix_audio_path": str(mix_path)}


def separate_audio_node(state: WorkflowState, *, settings: Any) -> dict[str, Any]:
    """仅调用 CI 分离并保存 dialogue/background MP3。"""
    background_path, dialogue_path = separate_episode_audio(
        _input_path(state), state["mix_audio_path"], settings
    )
    return {
        "background_audio_path": str(background_path),
        "dialogue_audio_path": str(dialogue_path),
    }


def transcribe_audio_node(state: WorkflowState, *, settings: Any) -> dict[str, Any]:
    """对已分离的 dialogue 执行整集 ASR。"""
    return {
        "transcript_segments": transcribe_episode_dialogue(
            _input_path(state),
            settings,
            state["episode_duration_ms"],
            characters=_drama_context(state).characters,
        )
    }


def prepare_background_node(state: WorkflowState) -> dict[str, Any]:
    """硬切背景音，得到本次运行使用的临时 WAV。"""
    wav_path = Path(state["run_dir"]) / "background.wav"
    cut_audio_hard(
        state["background_audio_path"], wav_path, state["episode_duration_ms"]
    )
    return {"background_wav_path": str(wav_path), "next_slice_index": 0}


def dispatch_slice_batch_node(state: WorkflowState) -> dict[str, Any]:
    """选择下一批最多四个固定时间跨度。"""
    start = state["next_slice_index"]
    stop = min(
        start + EVIDENCE_SLICE_CONCURRENCY,
        len(calculate_slices(state["episode_duration_ms"])),
    )
    return {"slice_batch_indices": list(range(start, stop))}


def dispatch_slice_subgraphs(state: WorkflowState) -> list[Send]:
    """把当前批次交给互不共享临时状态的切片子图。"""
    slices = calculate_slices(state["episode_duration_ms"])
    return [
        Send(
            "slice",
            {
                "input_path": state["input_path"],
                "run_dir": state["run_dir"],
                "background_wav_path": state["background_wav_path"],
                "slice_index": index,
                "slice_start_ms": slices[index][0],
                "slice_end_ms": slices[index][1],
            },
        )
        for index in state["slice_batch_indices"]
    ]


def _slice_workspace(state: Mapping[str, Any]) -> Path:
    """返回当前切片唯一的临时目录。"""
    return Path(str(state["run_dir"])) / "slices" / str(state["slice_start_ms"])


def prepare_frames_node(state: SliceState) -> dict[str, Any]:
    """只提取当前切片的固定采样帧。"""
    frame_paths = extract_frames(
        _input_path(state),
        calculate_sample_timestamps_ms(state["slice_start_ms"], state["slice_end_ms"]),
        _slice_workspace(state) / "frames",
    )
    return {"slice_frame_paths": [str(path) for path in frame_paths]}


def prepare_slice_audio_node(state: SliceState) -> dict[str, Any]:
    """只截取当前切片对应的背景音。"""
    audio_path = slice_audio(
        state["background_wav_path"],
        state["slice_start_ms"],
        state["slice_end_ms"],
        _slice_workspace(state) / "background.wav",
    )
    return {"slice_audio_path": str(audio_path)}


def observe_ocr_node(state: SliceState, *, settings: Any) -> dict[str, Any]:
    """只识别当前采样帧的屏幕文字。"""
    client = OpenAI(
        api_key=settings.ocr_api_key,
        base_url=settings.ocr_base_url.rstrip("/"),
        max_retries=MODEL_SDK_MAX_RETRIES,
    )
    return {
        "slice_onscreen_texts": run_qwen_ocr(
            frame_data_urls(state["slice_frame_paths"]), settings, client
        )
    }


def observe_vlm_node(state: SliceState, *, settings: Any) -> dict[str, Any]:
    """只生成当前采样帧的客观视觉观察。"""
    client = OpenAI(
        api_key=settings.vlm_api_key,
        base_url=settings.vlm_base_url.rstrip("/"),
        max_retries=MODEL_SDK_MAX_RETRIES,
    )
    observations, uncertainty = run_qwen_vlm(
        frame_data_urls(state["slice_frame_paths"]), settings, client
    )
    return {
        "slice_visual_observations": observations,
        "slice_vlm_uncertainty": uncertainty,
    }


def observe_audio_node(state: SliceState, *, settings: Any) -> dict[str, Any]:
    """只生成当前背景音切片的客观声音观察。"""
    client = OpenAI(
        api_key=settings.audio_observer_api_key,
        base_url=settings.audio_observer_base_url.rstrip("/"),
        max_retries=MODEL_SDK_MAX_RETRIES,
    )
    observations, uncertainty = run_qwen_audio_observer(
        Path(state["slice_audio_path"]), settings, client
    )
    return {
        "slice_audio_observations": observations,
        "slice_audio_uncertainty": uncertainty,
    }


def merge_slice_result_node(state: SliceState) -> dict[str, Any]:
    """合并一个子图的三路结果，不在子图内分配 Observation ID。"""
    shutil.rmtree(_slice_workspace(state), ignore_errors=True)
    return {
        "slice_results": {
            str(state["slice_index"]): {
                "start_ms": state["slice_start_ms"],
                "end_ms": state["slice_end_ms"],
                "visual_observations": state["slice_visual_observations"],
                "onscreen_texts": state["slice_onscreen_texts"],
                "audio_observations": state["slice_audio_observations"],
                "uncertainty": state["slice_vlm_uncertainty"]
                + state["slice_audio_uncertainty"],
            }
        }
    }


def merge_slice_batch_node(state: WorkflowState) -> dict[str, Any]:
    """按切片顺序写入当前批次的非空 Observation。"""
    observations: list[Observation] = []
    for index in state["slice_batch_indices"]:
        result = state["slice_results"][str(index)]
        if any(
            result[field]
            for field in (
                "visual_observations",
                "onscreen_texts",
                "audio_observations",
                "uncertainty",
            )
        ):
            observations.append(
                Observation(
                    id=f"O{len(state.get('baseline_observations', [])) + len(observations) + 1}",
                    start_ms=result["start_ms"],
                    end_ms=result["end_ms"],
                    visual_observations=result["visual_observations"],
                    onscreen_texts=result["onscreen_texts"],
                    audio_observations=result["audio_observations"],
                    uncertainty=result["uncertainty"],
                )
            )
    return {
        "baseline_observations": observations,
        "next_slice_index": state["next_slice_index"]
        + len(state["slice_batch_indices"]),
    }


def route_after_merge_slice_batch(
    state: WorkflowState,
) -> Literal["dispatch_slice_batch", "assemble_evidence"]:
    """在最后一批后汇总 Evidence，否则继续下一批。"""
    if state["next_slice_index"] < len(calculate_slices(state["episode_duration_ms"])):
        return "dispatch_slice_batch"
    return "assemble_evidence"


def assemble_evidence_node(state: WorkflowState) -> dict[str, Any]:
    """只汇总已 checkpoint 的提取状态为 EvidenceDocument。"""
    document = EvidenceDocument(
        episode_duration_ms=state["episode_duration_ms"],
        transcript_segments=state["transcript_segments"],
        observations=state.get("baseline_observations", []),
    )
    return {
        "evidence": document,
        "metrics": {
            "transcript_segment_count": len(document.transcript_segments),
            "observation_count": len(document.observations),
        },
    }


def persist_evidence_node(state: WorkflowState) -> dict[str, Any]:
    """只原子写正式 Evidence，并清理已不再需要的临时媒体。"""
    video = _input_path(state)
    evidence_path = (
        Path(state["evidence_dir"]) / video.parent.name / f"{video.stem}.json"
    )
    write_json_atomic(_document(state), evidence_path)
    Path(state["background_wav_path"]).unlink(missing_ok=True)
    Path(state["mix_audio_path"]).unlink(missing_ok=True)
    return {"evidence_path": str(evidence_path)}


def render_evidence_node(state: WorkflowState) -> dict[str, Any]:
    """为五个 Specialist 构造相互隔离的时间线。"""
    document = _document(state)
    timelines = {
        specialist: render_evidence_timeline(
            document,
            specialist,
            state.get("derived_evidence", {}).get(specialist, ()),
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


def _event(
    event_id: str, event_type: str, reason: str, **details: Any
) -> dict[str, Any]:
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
    state: WorkflowState,
    *,
    specialist_type: str,
    gateway: Any,
) -> dict[str, Any]:
    """运行一个 Specialist 分支，并隔离其校验与修复失败。"""
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
            "render_failures": state.get("constraints_report", {}).get(
                "render_failures", []
            ),
            "invalid": state_to_jsonable(report.invalid),
            "eligible_ids": eligible_ids,
            "conflict_groups": [list(group) for group in groups],
        },
        "selected_candidate_ids": [
            candidate_id
            for candidate_id in eligible_ids
            if candidate_id not in conflicted
        ],
    }


def semantic_node(
    state: WorkflowState, *, gateway: Any, settings: Any
) -> dict[str, Any]:
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
    wanted = set(evidence_ids)
    return "\n".join(
        line
        for line in timeline.splitlines()
        if line.lstrip().startswith("[")
        and line.lstrip()[1:].split("]")[0].split(" ")[0] in wanted
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
    source = (
        decision.get("replacement")
        if decision.get("action") == "edit"
        else event.get("candidate")
    )
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
                    state.get("derived_evidence", {}).get(
                        candidate.specialist_type, ()
                    ),
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
                    or any(
                        not isinstance(candidate_id, str) for candidate_id in keep_ids
                    )
                    or len(keep_ids) != len(set(keep_ids))
                    or set(keep_ids) - contested
                    or not isinstance(groups, list)
                    or not all(isinstance(group, list) for group in groups)
                    or any(
                        len(set(keep_ids).intersection(group)) > 1 for group in groups
                    )
                ):
                    raise ValueError(
                        "语义调度 edit 必须提交合法 selected_candidate_ids"
                    )
                selected.extend(keep_ids)
            # drop 不保留未被语义确认的冲突候选。
        elif event["event_type"] == "constraint_review":
            contested = set(event.get("candidate_ids", ()))
            selected = [
                candidate_id
                for candidate_id in selected
                if candidate_id not in contested
            ]

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
    interactions = [
        rendered[candidate_id]
        for candidate_id in selected_ids
        if candidate_id in rendered
    ]
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
        write_json_atomic(
            [item.model_dump(mode="json", exclude_none=True) for item in final],
            output_path,
        )
    run_dir = state.get("run_dir")
    if isinstance(run_dir, str) and state.get("derived_evidence"):
        write_json_atomic(
            state["derived_evidence"], Path(run_dir) / "evidence-derived.json"
        )
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
    "assemble_evidence_node",
    "constraints_node",
    "dispatch_slice_batch_node",
    "dispatch_slice_subgraphs",
    "extract_mix_node",
    "final_check_node",
    "human_gate_node",
    "media_prepare_node",
    "merge_slice_batch_node",
    "merge_slice_result_node",
    "needs_human",
    "observe_audio_node",
    "observe_ocr_node",
    "observe_vlm_node",
    "pool_node",
    "prepare_background_node",
    "prepare_frames_node",
    "prepare_slice_audio_node",
    "persist_evidence_node",
    "render_evidence_node",
    "render_node",
    "route_after_final",
    "route_after_human",
    "route_after_merge_slice_batch",
    "route_after_pool",
    "separate_audio_node",
    "semantic_node",
    "specialist_node",
    "transcribe_audio_node",
]
