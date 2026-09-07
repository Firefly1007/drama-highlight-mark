"""单集 LangGraph 工作流状态与并行汇聚 reducer。"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from drama_interaction.context import DramaContext
from drama_interaction.schemas.candidate import Candidate, SpecialistResult
from drama_interaction.schemas.evidence import (
    DerivedObservation,
    EvidenceDocument,
    Observation,
    TranscriptSegment,
)
from drama_interaction.schemas.interaction import FinalInteraction, InteractionType

SPECIALIST_TYPES = tuple(interaction_type.value for interaction_type in InteractionType)

RunStatus = Literal["running", "waiting_for_human", "completed", "failed"]


def append_items(
    current: Sequence[Any] | None,
    update: Sequence[Any] | None,
) -> list[Any]:
    """追加并行节点写入的列表值。"""

    return [*(current or ()), *(update or ())]


def merge_dicts(
    current: Mapping[str, Any] | None,
    update: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """合并并行节点写入的键值。"""

    return {**(current or {}), **(update or {})}


def merge_derived_evidence(
    current: Mapping[str, Sequence[DerivedObservation]] | None,
    update: Mapping[str, Sequence[DerivedObservation]] | None,
) -> dict[str, list[DerivedObservation]]:
    """按 Specialist 隔离并追加派生观察。"""

    merged = {key: list(value) for key, value in (current or {}).items()}
    for specialist, observations in (update or {}).items():
        merged.setdefault(specialist, []).extend(observations)
    return merged


class SliceState(TypedDict, total=False):
    """一个固定时间跨度的媒体观察子图状态。"""

    input_path: str
    run_dir: str
    background_wav_path: str
    slice_index: int
    slice_start_ms: int
    slice_end_ms: int
    slice_frame_paths: list[str]
    slice_audio_path: str
    slice_onscreen_texts: list[str]
    slice_visual_observations: list[str]
    slice_vlm_uncertainty: list[str]
    slice_audio_observations: list[str]
    slice_audio_uncertainty: list[str]
    slice_results: Annotated[dict[str, dict[str, Any]], merge_dicts]


class SliceOutput(TypedDict):
    """切片子图唯一回传给父图的结果。"""

    slice_results: Annotated[dict[str, dict[str, Any]], merge_dicts]


class WorkflowState(TypedDict, total=False):
    """一集 V2 运行的可恢复状态。"""

    execution_id: str
    input_path: str
    run_dir: str
    evidence_dir: str
    output_dir: str
    evidence_path: str | None
    output_path: str | None
    episode_duration_ms: int
    drama_context: DramaContext
    mix_audio_path: str
    background_audio_path: str
    dialogue_audio_path: str
    background_wav_path: str
    transcript_segments: list[TranscriptSegment]
    baseline_observations: Annotated[list[Observation], append_items]
    next_slice_index: int
    slice_batch_indices: list[int]
    slice_results: Annotated[dict[str, dict[str, Any]], merge_dicts]
    evidence: EvidenceDocument
    specialist_timelines: Annotated[dict[str, str], merge_dicts]
    derived_evidence: Annotated[
        dict[str, list[DerivedObservation]], merge_derived_evidence
    ]
    specialist_results: Annotated[dict[str, SpecialistResult], merge_dicts]
    branch_results: Annotated[dict[str, dict[str, Any]], merge_dicts]
    candidate_pool: list[Candidate]
    manual_candidates: Annotated[list[Candidate], append_items]
    repair_log: Annotated[list[dict[str, Any]], append_items]
    hitl_queue: Annotated[list[dict[str, Any]], append_items]
    hitl_resolutions: Annotated[list[dict[str, Any]], append_items]
    constraints_report: dict[str, Any]
    scheduler_decision: dict[str, Any] | None
    rendered_candidates: dict[str, FinalInteraction]
    selected_candidate_ids: list[str]
    repool_after_human: bool
    final_interactions: list[FinalInteraction]
    metrics: Annotated[dict[str, Any], merge_dicts]
    execution: Annotated[dict[str, Any], merge_dicts]
    status: RunStatus
    error: str | None
    created_at: str
    updated_at: str


def state_to_jsonable(value: Any) -> Any:
    """递归转换状态，供 JSON 运行产物写入。"""

    if hasattr(value, "model_dump"):
        return state_to_jsonable(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): state_to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [state_to_jsonable(item) for item in value]
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return state_to_jsonable(value.value)
    return value


def write_json_atomic(value: Any, output_path: str | Path) -> Path:
    """以同目录临时文件 + 替换的方式原子写入 JSON 产物。"""

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


__all__ = [
    "SPECIALIST_TYPES",
    "RunStatus",
    "SliceOutput",
    "SliceState",
    "WorkflowState",
    "append_items",
    "merge_derived_evidence",
    "merge_dicts",
    "state_to_jsonable",
    "write_json_atomic",
]
