"""单集 LangGraph 工作流状态与并行汇聚 reducer。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, TypedDict

from drama_interaction.context import DramaContext
from drama_interaction.schemas.candidate import Candidate, SpecialistResult
from drama_interaction.schemas.evidence import DerivedObservation, EvidenceDocument
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
    evidence: EvidenceDocument
    specialist_timelines: Annotated[dict[str, str], merge_dicts]
    derived_evidence: Annotated[
        dict[str, list[DerivedObservation]], merge_derived_evidence
    ]
    specialist_results: Annotated[
        dict[str, SpecialistResult], merge_dicts
    ]
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


class SpecialistBranchInput(TypedDict, total=False):
    """Specialist 子图从父图接收的只读上下文。"""

    drama_context: DramaContext
    evidence: EvidenceDocument
    specialist_timelines: dict[str, str]
    derived_evidence: dict[str, list[DerivedObservation]]


class SpecialistBranchState(SpecialistBranchInput, total=False):
    """单个 Specialist 子图的内部状态。"""

    specialist_results: dict[str, SpecialistResult]
    branch_results: dict[str, dict[str, Any]]
    repair_log: list[dict[str, Any]]
    hitl_queue: list[dict[str, Any]]


class SpecialistBranchOutput(TypedDict, total=False):
    """Specialist 子图回写父图的分支结果。"""

    specialist_results: dict[str, SpecialistResult]
    branch_results: dict[str, dict[str, Any]]
    repair_log: list[dict[str, Any]]
    hitl_queue: list[dict[str, Any]]


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


__all__ = [
    "SPECIALIST_TYPES",
    "RunStatus",
    "SpecialistBranchInput",
    "SpecialistBranchOutput",
    "SpecialistBranchState",
    "WorkflowState",
    "append_items",
    "merge_derived_evidence",
    "merge_dicts",
    "state_to_jsonable",
]
