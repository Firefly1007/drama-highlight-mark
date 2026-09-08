"""按需取证桩接口测试。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import drama_interaction.evidence.service as service_module
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
    assert result.failure_reason == "视频观察不可用"
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


def test_inspect_span_creates_one_branch_private_observation_and_success_audit(
    monkeypatch, tmp_path
):
    calls = {}
    monkeypatch.setattr(
        service_module,
        "slice_video",
        lambda video, start, end, output: calls.update(
            video=video, start=start, end=end, output=output
        ) or output,
    )
    monkeypatch.setattr(
        service_module,
        "run_qwen_video_observer",
        lambda clip, query, settings: {
            "visual_observations": ["男子举手"],
            "onscreen_texts": ["警告"],
            "audio_observations": ["关门声"],
            "uncertainty": ["身份不确定"],
        },
    )
    settings = SimpleNamespace(
        inspection_max_span_ms=6000,
        omni_observer_api_key="key",
        omni_observer_base_url="https://example.invalid/v1",
    )

    result = EvidenceService(
        _document(), "episode.mp4", str(tmp_path), settings
    ).inspect_span(100, 300, "画面和声音发生了什么？", "instant_vote")

    assert result.available is True
    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.id == "D1"
    assert (observation.start_ms, observation.end_ms) == (100, 300)
    assert observation.provenance.specialist.value == "instant_vote"
    assert observation.provenance.query_span.start_ms == 100
    assert result.audit_record is not None
    assert result.audit_record.available is True
    assert result.audit_record.result_count == 1
    assert calls["start"] == 100 and calls["end"] == 300
    assert "instant_vote-1.mp4" in str(calls["output"])


def test_inspect_span_keeps_successful_empty_observation_available_without_d(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(service_module, "slice_video", lambda *args: args[-1])
    monkeypatch.setattr(
        service_module,
        "run_qwen_video_observer",
        lambda *args: {
            "visual_observations": [],
            "onscreen_texts": [],
            "audio_observations": [],
            "uncertainty": [],
        },
    )
    settings = SimpleNamespace(
        inspection_max_span_ms=6000,
        omni_observer_api_key="key",
        omni_observer_base_url="https://example.invalid/v1",
    )

    result = EvidenceService(
        _document(), "episode.mp4", str(tmp_path), settings
    ).inspect_span(100, 300, "有什么？", "instant_vote")

    assert result.available is True
    assert result.observations == []
    assert result.audit_record is not None
    assert result.audit_record.available is True
    assert result.audit_record.result_count == 0


def test_inspect_span_serializes_parallel_calls_for_one_specialist(
    monkeypatch, tmp_path
):
    """同一 Specialist 的并行调用不能复用临时文件或 D 编号。"""

    output_paths: list[str] = []
    second_slice_started = Event()

    def fake_slice(_video, _start, _end, output):
        output_paths.append(str(output))
        if len(output_paths) == 1:
            second_slice_started.wait(timeout=0.1)
        else:
            second_slice_started.set()
        return output

    monkeypatch.setattr(service_module, "slice_video", fake_slice)
    monkeypatch.setattr(
        service_module,
        "run_qwen_video_observer",
        lambda *_args: {
            "visual_observations": ["有人出现"],
            "onscreen_texts": [],
            "audio_observations": [],
            "uncertainty": [],
        },
    )
    settings = SimpleNamespace(
        inspection_max_span_ms=6000,
        omni_observer_api_key="key",
        omni_observer_base_url="https://example.invalid/v1",
    )
    service = EvidenceService(_document(), "episode.mp4", str(tmp_path), settings)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda query: service.inspect_span(
                    100, 300, query, "instant_vote"
                ),
                ["第一个事实", "第二个事实"],
            )
        )

    assert len(set(output_paths)) == 2
    assert [item.observations[0].id for item in results] == ["D1", "D2"]
    assert len(service.audit_records) == 2
