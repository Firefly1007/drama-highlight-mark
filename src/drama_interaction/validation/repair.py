"""候选级安全修复、定向重生与人工交接。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from drama_interaction.schemas.candidate import Candidate
from drama_interaction.schemas.evidence import DerivedObservation, EvidenceDocument
from drama_interaction.validation.rules import ValidationIssue, validate_candidate


class RepairAttempt(BaseModel):
    """一次候选修复尝试及其结果。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["safe_repair", "regenerate", "hitl"]
    success: bool
    reason: str = Field(min_length=1)
    errors: list[ValidationIssue] = Field(default_factory=list)


class HITLEvent(BaseModel):
    """等待人工决定的候选事件。"""

    model_config = ConfigDict(extra="forbid")

    event_type: Literal["candidate_review"] = "candidate_review"
    reason: str = Field(min_length=1)
    candidate: dict[str, Any]
    errors: list[ValidationIssue] = Field(default_factory=list)
    attempts: list[RepairAttempt] = Field(default_factory=list)
    actions: tuple[str, ...] = ("accept", "edit", "drop")


class RepairOutcome(BaseModel):
    """修复流程的可审计结果。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["valid", "repaired", "regenerated", "hitl"]
    candidate: Candidate | None = None
    attempts: list[RepairAttempt] = Field(default_factory=list)
    errors: list[ValidationIssue] = Field(default_factory=list)
    hitl_event: HITLEvent | None = None


_SAFE_CODES = frozenset({"candidate_id_present"})


def safe_repair_candidate(candidate: Candidate) -> Candidate:
    """只清理候选 ID，不改业务内容。"""
    if candidate.candidate_id is None:
        return candidate
    return candidate.model_copy(update={"candidate_id": None})


def repair_candidate(
    candidate: Candidate,
    errors: Sequence[ValidationIssue] = (),
    *,
    specialist: Any = None,
    evidence_timeline: str = "",
    evidence_document: EvidenceDocument,
    derived_observations: Iterable[DerivedObservation] | None = None,
) -> RepairOutcome:
    """按安全修复、定向重生、HITL 顺序处理一条候选。"""
    if not isinstance(candidate, Candidate):
        raise TypeError("candidate 必须是 Candidate")
    if not isinstance(evidence_document, EvidenceDocument):
        raise TypeError("evidence_document 必须是 EvidenceDocument")
    if any(not isinstance(error, ValidationIssue) for error in errors):
        raise TypeError("errors 必须全部是 ValidationIssue")

    normalized_errors = list(errors)
    if not normalized_errors:
        current_errors = validate_candidate(
            candidate,
            evidence_document,
            derived_observations,
        )
        if not current_errors:
            return RepairOutcome(status="valid", candidate=candidate)
        normalized_errors = current_errors

    attempts: list[RepairAttempt] = []
    repaired = safe_repair_candidate(candidate)
    if all(error.code in _SAFE_CODES for error in normalized_errors):
        safe_errors = validate_candidate(
            repaired,
            evidence_document,
            derived_observations,
        )
        if not safe_errors:
            attempts.append(
                RepairAttempt(
                    action="safe_repair",
                    success=True,
                    reason="安全规范化后通过局部校验",
                )
            )
            return RepairOutcome(status="repaired", candidate=repaired, attempts=attempts)
        normalized_errors = safe_errors
        attempts.append(
            RepairAttempt(
                action="safe_repair",
                success=False,
                reason="安全规范化后仍有局部校验错误",
                errors=safe_errors,
            )
        )
    else:
        attempts.append(
            RepairAttempt(
                action="safe_repair",
                success=False,
                reason="错误不在安全修复白名单内",
                errors=normalized_errors,
            )
        )

    if specialist is not None and evidence_timeline.strip():
        # 网络耗尽异常不在这里捕获，交由图层原样转 HITL。
        replacement = specialist.regenerate_one(
            candidate,
            normalized_errors,
            evidence_timeline,
        )
        if replacement is not None:
            regenerated_errors = validate_candidate(
                replacement,
                evidence_document,
                derived_observations,
            )
            if not regenerated_errors:
                attempts.append(
                    RepairAttempt(
                        action="regenerate",
                        success=True,
                        reason="定向重生候选通过局部校验",
                    )
                )
                return RepairOutcome(
                    status="regenerated",
                    candidate=replacement,
                    attempts=attempts,
                )
            normalized_errors = regenerated_errors
            attempts.append(
                RepairAttempt(
                    action="regenerate",
                    success=False,
                    reason="定向重生候选仍未通过局部校验",
                    errors=regenerated_errors,
                )
            )
        else:
            reason = specialist.last_error or "定向重生未返回候选"
            attempts.append(
                RepairAttempt(
                    action="regenerate",
                    success=False,
                    reason=reason,
                    errors=normalized_errors,
                )
            )

    attempts.append(
        RepairAttempt(
            action="hitl",
            success=False,
            reason="候选需要人工 accept/edit/drop 决定",
            errors=normalized_errors,
        )
    )
    event = HITLEvent(
        reason="程序修复与定向重生均未形成合法候选",
        candidate=candidate.model_dump(mode="json", exclude_none=False),
        errors=normalized_errors,
        attempts=attempts,
    )
    return RepairOutcome(
        status="hitl",
        attempts=attempts,
        errors=normalized_errors,
        hitl_event=event,
    )


__all__ = [
    "HITLEvent",
    "RepairAttempt",
    "RepairOutcome",
    "repair_candidate",
    "safe_repair_candidate",
]
