"""按需取证桩接口测试。"""

import pytest
from pydantic import ValidationError

from drama_interaction.evidence.service import (
    EvidenceAuditRecord,
    EvidenceService,
    InspectSpanResult,
)
from drama_interaction.schemas.evidence import (
    DerivedObservation,
    EvidenceDocument,
    EvidenceProvenance,
    Observation,
)


def _document() -> EvidenceDocument:
    return EvidenceDocument(
        episode_duration_ms=1_000,
        observations=[Observation(id="O1", start_ms=0, end_ms=100)],
    )


def test_inspect_span_returns_auditable_unavailable_result_without_mutation():
    document = _document()
    service = EvidenceService(document)

    result = service.inspect_span(
        start_ms=100,
        end_ms=300,
        query="此处有什么动作？",
        specialist="emotion_button",
    )

    assert result.available is False
    assert result.observations == []
    assert result.failure_reason == "按需取证尚未接入媒体提取器"
    assert result.audit_record is not None
    assert result.audit_record.specialist.value == "emotion_button"
    assert result.audit_record.query_span.start_ms == 100
    assert result.audit_record.query == "此处有什么动作？"
    assert document.observations[0].id == "O1"


@pytest.mark.parametrize(
    ("start_ms", "end_ms", "query", "specialist"),
    [(-1, 10, "问题", "instant_vote"), (10, 1, "问题", "instant_vote"), (1, 2, " ", "instant_vote"), (1, 2, "问题", "unknown")],
)
def test_inspect_span_returns_structured_input_errors(start_ms, end_ms, query, specialist):
    result = EvidenceService(_document()).inspect_span(
        start_ms=start_ms,
        end_ms=end_ms,
        query=query,
        specialist=specialist,
    )

    assert result.available is False
    assert result.observations == []
    assert result.failure_reason is not None
    assert result.failure_reason.startswith("输入错误:")
    assert result.audit_record is None


def test_inspect_span_rejects_other_specialists_derived_evidence():
    foreign_derived = DerivedObservation(
        id="D1",
        start_ms=100,
        end_ms=200,
        provenance=EvidenceProvenance(
            specialist="side_comment",
            query_span={"start_ms": 100, "end_ms": 200},
            query="补证",
        ),
        refines="O1",
    )

    result = EvidenceService(_document()).inspect_span(
        100, 200, "此处有什么？", "instant_vote", [foreign_derived]
    )

    assert result.available is False
    assert result.audit_record is not None
    assert result.failure_reason is not None
    assert result.failure_reason.startswith("existing_derived 非法:")


def test_audit_models_are_strict():
    audit = EvidenceAuditRecord(
        specialist="instant_vote",
        query_span={"start_ms": 1, "end_ms": 2},
        query="谁在说话？",
        result_count=0,
        available=False,
        failure_reason="服务不可用",
    )
    assert audit.model_dump(mode="json")["specialist"] == "instant_vote"

    with pytest.raises(ValidationError):
        InspectSpanResult(available=False, unknown=True)
