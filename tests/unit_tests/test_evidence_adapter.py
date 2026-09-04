"""V1 片段到 V2 EvidenceDocument 的适配测试。"""

import json

import pytest
from pydantic import ValidationError

from drama_interaction.evidence.adapter import (
    adapt_file,
    convert_v1_segments_to_evidence,
    parse_time_str_to_ms,
    save_evidence_document,
)
from drama_interaction.schemas.evidence import EvidenceDocument


def test_parse_time_str_to_ms_is_strict():
    assert parse_time_str_to_ms("00:01:02.003") == 62_003

    for value in ("0:01:02.003", "00:60:00.000", "00:00:00", 1):
        with pytest.raises(ValueError):
            parse_time_str_to_ms(value)  # type: ignore[arg-type]


def test_convert_v1_segments_preserves_exact_spans_and_ignores_emotion():
    document = convert_v1_segments_to_evidence(
        [
            {
                "id": 1,
                "start": "00:00:00.100",
                "end": "00:00:01.500",
                "text": "第一句",
                "speech": "单人发言",
                "voice": "急促",
                "music": "紧张配乐",
                "audio_cues": "脚步声",
                "uncertainty": ["背景嘈杂"],
                "emotion": "愤怒",
            },
            {
                "id": 2,
                "start": "00:00:02.000",
                "end": "00:00:03.000",
                "text": "",
                "music": "",
            },
        ],
        episode_duration_ms=3_000,
    )

    assert document.episode_duration_ms == 3_000
    assert [(item.id, item.start_ms, item.end_ms) for item in document.transcript_segments] == [
        ("T1", 100, 1500)
    ]
    assert document.observations[0].id == "O1"
    assert document.observations[0].audio_observations == [
        "说话方式：单人发言",
        "嗓音：急促",
        "背景音乐：紧张配乐",
        "环境音效：脚步声",
    ]
    assert "愤怒" not in document.model_dump_json()


def test_convert_rejects_bad_input_and_never_clamps_time():
    valid_segment = {
        "id": 1,
        "start": "00:00:00.000",
        "end": "00:00:01.000",
        "text": "第一句",
    }
    with pytest.raises(ValueError):
        convert_v1_segments_to_evidence([valid_segment], episode_duration_ms=0)
    with pytest.raises(ValueError):
        convert_v1_segments_to_evidence(
            [{**valid_segment, "end": "00:00:02.000"}], episode_duration_ms=1_000
        )
    with pytest.raises(ValueError):
        convert_v1_segments_to_evidence(
            [{**valid_segment, "id": 2}], episode_duration_ms=1_000
        )
    with pytest.raises(ValidationError):
        convert_v1_segments_to_evidence(
            [{**valid_segment, "unexpected": "field"}], episode_duration_ms=1_000
        )


def test_empty_document_is_valid_and_file_adapter_uses_preprocessed_duration(tmp_path):
    source = tmp_path / "剧名" / "第1集.json"
    source.parent.mkdir()
    source.write_text("[]", encoding="utf-8")

    document, saved_path = adapt_file(source, episode_duration_ms=1_000, output_dir=tmp_path / "evidence")

    assert document == EvidenceDocument(episode_duration_ms=1_000)
    assert saved_path == tmp_path / "evidence" / "剧名" / "第1集.json"
    assert EvidenceDocument.model_validate_json(saved_path.read_text(encoding="utf-8")) == document


def test_save_evidence_document_writes_one_root_object(tmp_path):
    output = tmp_path / "evidence.json"
    document = EvidenceDocument(episode_duration_ms=1_000)

    assert save_evidence_document(document, output) == output
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "episode_duration_ms": 1_000,
        "transcript_segments": [],
        "observations": [],
    }
