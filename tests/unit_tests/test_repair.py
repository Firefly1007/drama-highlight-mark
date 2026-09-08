"""候选修复的证据边界测试。"""

import pytest

from drama_interaction.schemas.candidate import Candidate, TriggerAnchor
from drama_interaction.schemas.evidence import EvidenceDocument, TranscriptSegment
from drama_interaction.validation.repair import repair_candidate
from drama_interaction.validation.rules import ValidationIssue


def _document() -> EvidenceDocument:
    return EvidenceDocument(
        episode_duration_ms=2_000,
        transcript_segments=[
            TranscriptSegment(id="T1", start_ms=0, end_ms=1_000, text="开始"),
        ],
    )


def _invalid_candidate() -> Candidate:
    return Candidate(
        candidate_id="old",
        specialist_type="emotion_button",
        evidence_ids=["T2"],
        trigger_anchor=TriggerAnchor(transcript_segment_id="T2"),
        payload={"button_id": "cool", "text": "太解气了"},
    )


class _FakeSpecialist:
    def __init__(self, replacement: Candidate | None) -> None:
        self.replacement = replacement
        self.calls = 0
        self.last_error = "测试中的定向重生失败"

    def regenerate_one(
        self,
        candidate: Candidate,
        errors: list[ValidationIssue],
        evidence_timeline: str,
    ) -> Candidate | None:
        self.calls += 1
        return self.replacement


def test_repair_requires_evidence_document():
    """修复不能绕过候选的证据引用校验。"""

    candidate = Candidate(
        specialist_type="emotion_button",
        evidence_ids=["T1"],
        trigger_anchor=TriggerAnchor(transcript_segment_id="T1"),
        payload={"button_id": "cool", "text": "太解气了"},
    )

    with pytest.raises(TypeError, match="evidence_document"):
        repair_candidate(candidate, evidence_document=None)  # type: ignore[arg-type]


def test_repair_regenerates_once_and_accepts_valid_replacement():
    """定向重生固定只调用一次。"""

    replacement = Candidate(
        specialist_type="emotion_button",
        evidence_ids=["T1"],
        trigger_anchor=TriggerAnchor(transcript_segment_id="T1"),
        payload={"button_id": "cool", "text": "太解气了"},
    )
    specialist = _FakeSpecialist(replacement)

    outcome = repair_candidate(
        _invalid_candidate(),
        specialist=specialist,
        evidence_timeline="[T1] 开始",
        evidence_document=_document(),
    )

    assert outcome.status == "regenerated"
    assert outcome.candidate == replacement
    assert specialist.calls == 1
    assert [attempt.action for attempt in outcome.attempts] == [
        "safe_repair",
        "regenerate",
    ]


def test_repair_enters_hitl_after_single_failed_regeneration():
    """定向重生失败后保留完整尝试记录并进入 HITL。"""

    specialist = _FakeSpecialist(None)

    outcome = repair_candidate(
        _invalid_candidate(),
        specialist=specialist,
        evidence_timeline="[T1] 开始",
        evidence_document=_document(),
    )

    assert outcome.status == "hitl"
    assert specialist.calls == 1
    assert outcome.hitl_event is not None
    assert outcome.hitl_event.attempts == outcome.attempts
    assert [attempt.action for attempt in outcome.attempts] == [
        "safe_repair",
        "regenerate",
        "hitl",
    ]


def test_repair_rejects_regenerated_duplicate_of_existing_candidate():
    """定向重生不能重复本批已接纳候选。"""

    replacement = Candidate(
        specialist_type="emotion_button",
        evidence_ids=["T1"],
        trigger_anchor=TriggerAnchor(transcript_segment_id="T1"),
        payload={"button_id": "cool", "text": "太解气了"},
    )
    specialist = _FakeSpecialist(replacement)

    outcome = repair_candidate(
        _invalid_candidate(),
        specialist=specialist,
        evidence_timeline="[T1] 开始",
        evidence_document=_document(),
        existing_candidates=[replacement],
    )

    assert outcome.status == "hitl"
    assert any(error.code == "duplicate_candidate" for error in outcome.errors)
