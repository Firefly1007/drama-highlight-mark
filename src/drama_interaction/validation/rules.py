"""候选入池前的局部确定性校验。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from drama_interaction.schemas.candidate import (
    Candidate,
    RevealAnchor,
    TriggerAnchor,
)
from drama_interaction.schemas.evidence import (
    DerivedObservation,
    EvidenceDocument,
    EvidenceEntry,
    validate_derived_observations,
    visible_evidence_entries,
)
from drama_interaction.schemas.interaction import (
    RepeatKeylinePayload,
)


class ValidationIssue(BaseModel):
    """一条可路由的候选校验错误。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    field: str = Field(min_length=1)
    message: str = Field(min_length=1)
    expected: Any = None
    actual: Any = None
    route: str = "repair"


def _issue(
    code: str,
    field: str,
    message: str,
    *,
    expected: Any = None,
    actual: Any = None,
    route: str = "repair",
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        field=field,
        message=message,
        expected=expected,
        actual=actual,
        route=route,
    )


def _anchor_ids(anchor: TriggerAnchor | RevealAnchor | None) -> list[str]:
    if anchor is None:
        return []
    return [
        value
        for value in (
            anchor.transcript_segment_id,
            anchor.observation_id,
        )
        if value is not None
    ]


def _anchor_entry(
    anchor: TriggerAnchor | RevealAnchor | None,
    entries: dict[str, EvidenceEntry],
) -> tuple[str | None, EvidenceEntry | None]:
    """按 transcript 优先规则取得锚点证据。"""
    ids = _anchor_ids(anchor)
    if not ids:
        return None, None
    selected = ids[0]
    return selected, entries.get(selected)


def _payload_signature(candidate: Candidate) -> tuple[str, dict[str, Any]]:
    return candidate.specialist_type, candidate.payload.model_dump(mode="json")


def _normalise_derived(
    derived_observations: Iterable[DerivedObservation] | None,
) -> tuple[list[DerivedObservation], ValidationIssue | None]:
    """将当前分支派生证据物化一次，拒绝非 DerivedObservation 项。"""
    if derived_observations is None:
        return [], None
    try:
        values = list(derived_observations)
    except TypeError as exc:
        return [], _issue(
            "derived_evidence_invalid",
            "derived_observations",
            f"派生证据必须是可迭代的 DerivedObservation 列表: {exc}",
            route="regenerate",
        )
    if not all(isinstance(value, DerivedObservation) for value in values):
        return [], _issue(
            "derived_evidence_invalid",
            "derived_observations",
            "派生证据必须全部是 DerivedObservation",
            route="regenerate",
        )
    return values, None


def validate_candidate(
    candidate: Candidate,
    evidence_document: EvidenceDocument | None = None,
    derived_observations: Iterable[DerivedObservation] | None = None,
    *,
    specialist_type: str | None = None,
    existing_candidates: Sequence[Candidate] = (),
) -> list[ValidationIssue]:
    """校验一条 Candidate 并返回稳定顺序的结构化错误。"""
    if not isinstance(candidate, Candidate):
        return [
            _issue(
                "schema_invalid",
                "candidate",
                "候选必须是 Candidate",
                actual=type(candidate).__name__,
                route="regenerate",
            )
        ]

    errors: list[ValidationIssue] = []
    if specialist_type is not None and candidate.specialist_type != specialist_type:
        errors.append(
            _issue(
                "specialist_type_mismatch",
                "specialist_type",
                "候选类型与当前 Specialist 不一致",
                expected=specialist_type,
                actual=candidate.specialist_type,
            )
        )
    if candidate.candidate_id is not None:
        errors.append(
            _issue(
                "candidate_id_present",
                "candidate_id",
                "生成侧 Candidate 的 candidate_id 必须为空",
                expected=None,
                actual=candidate.candidate_id,
            )
        )

    if evidence_document is None:
        errors.append(
            _issue(
                "evidence_document_missing",
                "evidence_document",
                "缺少共享证据文档，无法验证引用",
                route="regenerate",
            )
        )
        return errors
    if not isinstance(evidence_document, EvidenceDocument):
        errors.append(
            _issue(
                "evidence_document_invalid",
                "evidence_document",
                "evidence_document 必须是 EvidenceDocument",
                actual=type(evidence_document).__name__,
                route="regenerate",
            )
        )
        return errors

    branch_derived, derived_error = _normalise_derived(derived_observations)
    if derived_error is not None:
        errors.append(derived_error)
        branch_derived = []
    try:
        validate_derived_observations(
            evidence_document,
            candidate.specialist_type,
            branch_derived,
        )
    except ValueError as exc:
        errors.append(
            _issue(
                "derived_evidence_invalid",
                "derived_observations",
                str(exc),
                route="regenerate",
            )
        )

    entries = visible_evidence_entries(
        evidence_document, candidate.specialist_type, branch_derived
    )
    visible_ids = set(entries)
    for evidence_id in candidate.evidence_ids:
        if evidence_id not in visible_ids:
            errors.append(
                _issue(
                    "evidence_not_visible",
                    "evidence_ids",
                    f"证据 {evidence_id} 不在当前 Specialist 分支可见视图中",
                    expected=sorted(visible_ids),
                    actual=evidence_id,
                    route="regenerate",
                )
            )

    trigger_ids = _anchor_ids(candidate.trigger_anchor)
    for anchor_id in trigger_ids:
        if anchor_id not in visible_ids:
            errors.append(
                _issue(
                    "trigger_anchor_not_visible",
                    "trigger_anchor",
                    f"触发锚点 {anchor_id} 不在当前分支证据中",
                    actual=anchor_id,
                    route="regenerate",
                )
            )
        if anchor_id not in candidate.evidence_ids:
            errors.append(
                _issue(
                    "trigger_anchor_not_supported",
                    "evidence_ids",
                    f"evidence_ids 必须包含触发锚点 {anchor_id}",
                    expected=anchor_id,
                    actual=candidate.evidence_ids,
                    route="regenerate",
                )
            )

    reveal_ids = _anchor_ids(candidate.reveal_anchor)
    for anchor_id in reveal_ids:
        if anchor_id not in visible_ids:
            errors.append(
                _issue(
                    "reveal_anchor_not_visible",
                    "reveal_anchor",
                    f"揭晓锚点 {anchor_id} 不在当前分支证据中",
                    actual=anchor_id,
                    route="regenerate",
                )
            )
        if anchor_id not in candidate.evidence_ids:
            errors.append(
                _issue(
                    "reveal_anchor_not_supported",
                    "evidence_ids",
                    f"evidence_ids 必须包含揭晓锚点 {anchor_id}",
                    expected=anchor_id,
                    actual=candidate.evidence_ids,
                    route="regenerate",
                )
            )

    trigger_id, trigger_entry = _anchor_entry(candidate.trigger_anchor, entries)
    reveal_id, reveal_entry = _anchor_entry(candidate.reveal_anchor, entries)
    if candidate.specialist_type == "deferred_vote":
        if reveal_entry is None:
            errors.append(
                _issue(
                    "reveal_anchor_missing",
                    "reveal_anchor",
                    "deferred_vote 必须引用当前分支中的揭晓证据",
                    route="regenerate",
                )
            )
        elif trigger_entry is not None and reveal_entry.start_ms <= trigger_entry.start_ms:
            errors.append(
                _issue(
                    "reveal_anchor_not_later",
                    "reveal_anchor",
                    "揭晓锚点必须晚于触发锚点",
                    expected=f"> {trigger_id}",
                    actual=reveal_id,
                    route="regenerate",
                )
            )

    if candidate.specialist_type == "repeat_keyline":
        text = (
            candidate.payload.text.strip()
            if isinstance(candidate.payload, RepeatKeylinePayload)
            else ""
        )
        if not any(text in segment.text for segment in evidence_document.transcript_segments):
            errors.append(
                _issue(
                    "keyline_not_in_transcript",
                    "payload.text",
                    "repeat_keyline 文本必须能在本集台词中找到",
                    actual=text,
                    route="regenerate",
                )
            )

    current_signature = _payload_signature(candidate)
    current_trigger = tuple(trigger_ids)
    for index, other in enumerate(existing_candidates):
        if not isinstance(other, Candidate):
            continue
        if (
            other.specialist_type == candidate.specialist_type
            and tuple(_anchor_ids(other.trigger_anchor)) == current_trigger
            and _payload_signature(other) == current_signature
        ):
            errors.append(
                _issue(
                    "duplicate_candidate",
                    "candidate",
                    f"候选与已有候选 {index} 在同一锚点上的关键内容重复",
                    actual=index,
                    route="drop",
                )
            )
            break
    return errors


__all__ = ["ValidationIssue", "validate_candidate"]
