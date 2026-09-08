"""V2 数据契约的最小回归测试。"""

import pytest
from pydantic import ValidationError

from drama_interaction.schemas.candidate import Candidate, RevealAnchor, TriggerAnchor
from drama_interaction.schemas.evidence import (
    DerivedObservation,
    EvidenceDocument,
    EvidenceProvenance,
    Observation,
    TranscriptSegment,
    validate_derived_observations,
)
from drama_interaction.schemas.interaction import (
    DeferredVotePayload,
    EmotionButtonPayload,
    FinalInteraction,
    InstantVotePayload,
    RepeatKeylinePayload,
    SideCommentPayload,
)


@pytest.mark.parametrize(
    ("interaction_type", "payload", "payload_model"),
    [
        (
            "emotion_button",
            {"button_id": "cool", "text": "太解气了"},
            EmotionButtonPayload,
        ),
        ("repeat_keyline", {"text": "我会回来。"}, RepeatKeylinePayload),
        (
            "instant_vote",
            {"question": "你站谁？", "options": ["她", "他"]},
            InstantVotePayload,
        ),
        (
            "deferred_vote",
            {
                "question": "她说的是真的吗？",
                "options": ["是真的", "有问题"],
                "answer_id": 1,
                "reveal_time": 5000,
                "reveal_delay": 1000,
            },
            DeferredVotePayload,
        ),
        (
            "side_comment",
            {"text": "这也太敢说了吧！", "mood": "shock"},
            SideCommentPayload,
        ),
    ],
)
def test_final_interaction_parses_payload_union(
    interaction_type, payload, payload_model
):
    interaction = FinalInteraction(
        id=1,
        type=interaction_type,
        show_at=1000,
        duration_ms=1000,
        payload=payload,
    )

    assert interaction.model_dump(mode="json")["type"] == interaction_type
    assert isinstance(interaction.payload, payload_model)


def test_final_interaction_rejects_mismatched_payload_type():
    with pytest.raises(ValidationError):
        FinalInteraction(
            id=1,
            type="emotion_button",
            show_at=0,
            duration_ms=1000,
            payload={"text": "这其实是跟读金句"},
        )


@pytest.mark.parametrize("mood", ["ROAST", " roast", "roast ", None])
def test_side_comment_mood_must_be_present_and_lowercase(mood):
    with pytest.raises(ValidationError):
        SideCommentPayload(text="不对劲", mood=mood)


def test_final_interaction_rejects_numeric_type_and_invalid_deferred_fields():
    with pytest.raises(ValidationError):
        FinalInteraction(
            id=1,
            type=1,
            show_at=0,
            duration_ms=1000,
            payload={"button_id": "cool"},
        )

    with pytest.raises(ValidationError):
        FinalInteraction(
            id=1,
            type="side_comment",
            show_at=0,
            duration_ms=1000,
            payload={"text": "缺少 mood"},
        )

    deferred = {"question": "真相是什么？", "options": ["A", "B"], "answer_id": 0}
    with pytest.raises(ValidationError):
        FinalInteraction(
            id=1,
            type="deferred_vote",
            show_at=1000,
            duration_ms=1000,
            payload=deferred,
        )
    with pytest.raises(ValidationError):
        FinalInteraction(
            id=1,
            type="deferred_vote",
            show_at=1000,
            duration_ms=1000,
            payload={**deferred, "reveal_time": 1999, "reveal_delay": 1},
        )


@pytest.mark.parametrize("value", [True, "1", 1.0])
def test_external_integer_fields_do_not_coerce(value):
    with pytest.raises(ValidationError):
        FinalInteraction(
            id=value,
            type="emotion_button",
            show_at=0,
            duration_ms=1000,
            payload={"button_id": "cool"},
        )


def test_candidate_uses_evidence_ids_and_generation_only_deferred_payload():
    candidate = Candidate(
        specialist_type="deferred_vote",
        evidence_ids=["T1", "O1", "D1"],
        trigger_anchor=TriggerAnchor(transcript_segment_id="T1"),
        reveal_anchor=RevealAnchor(observation_id="O1"),
        payload=DeferredVotePayload(
            question="她会承认吗？", options=["会", "不会"], answer_id=0
        ),
    )

    assert candidate.reveal_anchor is not None

    for invalid_id in ("T0", "T00", "O0", "D0", "D00", "X1"):
        with pytest.raises(ValidationError):
            Candidate(
                specialist_type="instant_vote",
                evidence_ids=[invalid_id],
                trigger_anchor=TriggerAnchor(transcript_segment_id="T1"),
                payload={"question": "选谁？", "options": ["A", "B"]},
            )

    with pytest.raises(ValidationError):
        TriggerAnchor(observation_id="T1")
    with pytest.raises(ValidationError):
        Candidate(
            specialist_type="instant_vote",
            evidence_ids=["T1"],
            trigger_anchor=TriggerAnchor(transcript_segment_id="T1"),
            reveal_anchor=RevealAnchor(observation_id="O1"),
            payload={"question": "选谁？", "options": ["A", "B"]},
        )


def test_evidence_document_requires_one_based_ids_and_exact_bounds():
    document = EvidenceDocument(
        episode_duration_ms=1000,
        transcript_segments=[
            TranscriptSegment(id="T1", start_ms=0, end_ms=200, text="第一句")
        ],
        observations=[
            Observation(
                id="O1", start_ms=200, end_ms=300, audio_observations=["脚步声"]
            )
        ],
    )
    assert document.model_dump(mode="json")["transcript_segments"][0]["id"] == "T1"

    with pytest.raises(ValidationError):
        TranscriptSegment(id="T0", start_ms=0, end_ms=1, text="无效")
    with pytest.raises(ValidationError):
        EvidenceDocument(
            episode_duration_ms=100,
            transcript_segments=[
                TranscriptSegment(id="T1", start_ms=50, end_ms=80, text="后"),
                TranscriptSegment(id="T2", start_ms=0, end_ms=20, text="前"),
            ],
        )
    with pytest.raises(ValidationError):
        EvidenceDocument(
            episode_duration_ms=100,
            observations=[Observation(id="O1", start_ms=0, end_ms=101)],
        )


def test_derived_observations_are_specialist_private_and_acyclic():
    document = EvidenceDocument(
        episode_duration_ms=1000,
        observations=[Observation(id="O1", start_ms=0, end_ms=100)],
    )
    provenance = EvidenceProvenance(
        specialist="instant_vote",
        query_span={"start_ms": 100, "end_ms": 200},
        query="这里出现了什么？",
    )
    first = DerivedObservation(id="D1", start_ms=100, end_ms=200, provenance=provenance)
    second = DerivedObservation(id="D2", start_ms=200, end_ms=300, provenance=provenance)
    validate_derived_observations(document, "instant_vote", [first, second])

    with pytest.raises(ValueError):
        validate_derived_observations(document, "side_comment", [first])
    with pytest.raises(ValueError):
        validate_derived_observations(
            document,
            "instant_vote",
            [
                first,
                DerivedObservation(
                    id="D1", start_ms=200, end_ms=300, provenance=provenance
                ),
            ],
        )
