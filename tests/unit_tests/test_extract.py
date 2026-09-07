"""人声分离、Qwen ASR、OCR、VLM 与音频观察提取单元测试。"""

from __future__ import annotations

import json
from contextlib import contextmanager
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIStatusError

from drama_interaction.config import (
    ASR_TRANSCRIPTION_DOWNLOAD_TIMEOUT_SECONDS,
    ASR_VOCABULARY_WEIGHT,
    ASR_WAIT_TIMEOUT_SECONDS,
    EVIDENCE_AUDIO_OBSERVER_SYSTEM_PROMPT,
    EVIDENCE_AUDIO_OBSERVER_USER_PROMPT,
    EVIDENCE_OCR_SYSTEM_PROMPT,
    EVIDENCE_OCR_USER_PROMPT,
    EVIDENCE_VLM_SYSTEM_PROMPT,
    EVIDENCE_VLM_USER_PROMPT,
    Settings,
)
from drama_interaction.evidence.extract import (
    ExtractionError,
    run_qwen_asr,
    run_qwen_audio_observer,
    run_qwen_ocr,
    run_qwen_vlm,
    separate_episode_audio,
    transcribe_episode_dialogue,
)
from drama_interaction.prompt_models import (
    AudioObserverResponse,
    OCRResponse,
    VLMResponse,
)
from drama_interaction.schemas.evidence import TranscriptSegment

DIALOGUE_URL = "https://cdn.example/dialogue.wav"
TRANSCRIPTION_URL = "https://asr.example/result.json"


@pytest.mark.parametrize(
    ("prompt", "response_model"),
    [
        (EVIDENCE_OCR_USER_PROMPT, OCRResponse),
        (EVIDENCE_VLM_USER_PROMPT, VLMResponse),
        (EVIDENCE_AUDIO_OBSERVER_USER_PROMPT, AudioObserverResponse),
    ],
)
def test_evidence_prompts_embed_pydantic_json_schema(prompt, response_model):
    schema = json.dumps(
        response_model.model_json_schema(), ensure_ascii=False, separators=(",", ":")
    )
    assert "JSON 数据对象" in prompt
    assert "不要输出 JSON Schema 本身" in prompt
    assert "JSON Schema" in prompt
    assert schema in prompt


def _mock_settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_model_id="test-model",
        llm_api_key="test-key",
        llm_base_url="https://llm.example/v1",
        checkpoint_database_url="postgresql://user:pass@localhost/db",
        audio_separator_access_key_id="separator-id",
        audio_separator_access_key_secret="separator-secret",
        audio_separator_bucket="separator-bucket",
        audio_separator_region="ap-guangzhou",
        asr_model_id="qwen-audio-3.0-asr-flash-filetrans",
        asr_api_key="asr-key",
        asr_base_url="https://dashscope.aliyuncs.com/api/v1",
        audio_observer_model_id="qwen3-omni-flash",
        audio_observer_api_key="audio-key",
        audio_observer_base_url="https://audio.example/compatible-mode/v1",
        ocr_model_id="qwen-ocr-model",
        ocr_api_key="ocr-key",
        ocr_base_url="https://ocr.example/v1",
        vlm_model_id="qwen-vlm-model",
        vlm_api_key="vlm-key",
        vlm_base_url="https://vlm.example/v1",
        evidence_dir=tmp_path / "evidence",
        interaction_v2_dir=tmp_path / "interaction_v2",
        runs_dir=tmp_path / "runs",
    )


def _completion(content: str) -> MagicMock:
    """构造与 OpenAI SDK 取值链一致的响应：choices[0].message.content 是 JSON 字符串。"""
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


def _stream_completion(*contents: str) -> list[MagicMock]:
    return [
        MagicMock(choices=[MagicMock(delta=MagicMock(content=content))])
        for content in contents
    ]


@contextmanager
def _asr_env(
    transcription_json: dict,
    *,
    submit_status: int = HTTPStatus.OK,
    wait_output: dict | None = None,
):
    """按真实 dashscope 1.27.4 的形状装好 async_call、wait 与转写 JSON 下载。"""
    with (
        patch("dashscope.audio.asr.Transcription.async_call") as mock_call,
        patch("dashscope.audio.asr.Transcription.wait") as mock_wait,
        patch("httpx.Client") as mock_httpx,
    ):
        mock_call.return_value = MagicMock(
            status_code=submit_status,
            message="",
            output={"task_id": "task_asr_1"},
        )
        mock_wait.return_value = MagicMock(
            status_code=HTTPStatus.OK,
            message="",
            output=wait_output
            if wait_output is not None
            else {
                "results": [
                    {
                        "subtask_status": "SUCCEEDED",
                        "transcription_url": TRANSCRIPTION_URL,
                    }
                ]
            },
        )
        mock_httpx.return_value.__enter__.return_value.get.return_value = MagicMock(
            json=lambda: transcription_json,
            raise_for_status=lambda: None,
        )
        yield mock_call, mock_wait, mock_httpx


def test_run_qwen_asr_success(tmp_path):
    """测试 ASR 成功转写：整数毫秒直接映射、说话人为空、按顺序编号 T<n>。"""
    settings = _mock_settings(tmp_path)
    fake_transcription_json = {
        "transcripts": [
            {
                "sentences": [
                    {"text": "你到底是谁？", "begin_time": 100, "end_time": 1200},
                    {"text": "我是来找你的。", "begin_time": 1500, "end_time": 2800},
                ]
            }
        ]
    }

    with _asr_env(fake_transcription_json) as (mock_call, mock_wait, mock_httpx):
        segments = run_qwen_asr(
            DIALOGUE_URL,
            settings,
            episode_duration_ms=5000,
            characters=("容遇", "纪舜英", "容遇"),
        )

    assert [(item.id, item.start_ms, item.end_ms) for item in segments] == [
        ("T1", 100, 1200),
        ("T2", 1500, 2800),
    ]
    assert segments[0].text == "你到底是谁？"
    assert all(item.speaker_label is None for item in segments)

    # 协议契约：模型、单条 dialogue URL、固定声道、独立的 ASR 凭据
    assert mock_call.call_count == 1
    call_kwargs = mock_call.call_args.kwargs
    assert call_kwargs["model"] == "qwen-audio-3.0-asr-flash-filetrans"
    assert call_kwargs["file_urls"] == [DIALOGUE_URL]
    assert call_kwargs["channel_id"] == [0]
    assert call_kwargs["api_key"] == "asr-key"
    assert call_kwargs["vocabulary"] == {
        "容遇": ASR_VOCABULARY_WEIGHT,
        "纪舜英": ASR_VOCABULARY_WEIGHT,
    }
    assert mock_wait.call_args.kwargs["task"] == "task_asr_1"
    assert mock_wait.call_args.kwargs["api_key"] == "asr-key"
    assert (
        mock_wait.call_args.kwargs["wait_timeout"] == ASR_WAIT_TIMEOUT_SECONDS == 3600
    )
    assert (
        mock_httpx.call_args.kwargs["timeout"]
        == ASR_TRANSCRIPTION_DOWNLOAD_TIMEOUT_SECONDS
    )
    assert mock_httpx.call_args.kwargs["follow_redirects"] is True
    get_call = mock_httpx.return_value.__enter__.return_value.get
    assert get_call.call_args[0][0] == TRANSCRIPTION_URL


def test_run_qwen_asr_maps_transcripts_in_provider_order(tmp_path):
    """测试多个 transcript 的句段按 provider 顺序压平后连续编号，不排序也不重切。"""
    settings = _mock_settings(tmp_path)
    fake_json = {
        "transcripts": [
            {
                "sentences": [
                    {"text": "靠后的一句", "begin_time": 3000, "end_time": 3500},
                    {"text": "再后一句", "begin_time": 4000, "end_time": 4500},
                ]
            },
            {
                "sentences": [
                    {"text": "补回的一句", "begin_time": 5000, "end_time": 5200}
                ]
            },
        ]
    }

    with _asr_env(fake_json) as (mock_call, _mock_wait, _mock_httpx):
        segments = run_qwen_asr(DIALOGUE_URL, settings, episode_duration_ms=6000)

    assert [item.id for item in segments] == ["T1", "T2", "T3"]
    assert [item.text for item in segments] == ["靠后的一句", "再后一句", "补回的一句"]
    assert [item.start_ms for item in segments] == [3000, 4000, 5000]
    assert "vocabulary" not in mock_call.call_args.kwargs


def test_run_qwen_asr_submit_failure(tmp_path):
    """测试 async_call 返回非 200 时整集失败。"""
    settings = _mock_settings(tmp_path)

    with _asr_env({"transcripts": []}, submit_status=HTTPStatus.BAD_REQUEST):
        with pytest.raises(ExtractionError, match="提交失败"):
            run_qwen_asr(DIALOGUE_URL, settings, episode_duration_ms=3000)


def test_run_qwen_asr_missing_task_id_fails(tmp_path):
    """测试响应 output 里没有 task_id 时整集失败（真实 output 是 dict）。"""
    settings = _mock_settings(tmp_path)

    with _asr_env({"transcripts": []}) as (mock_call, _wait, _httpx):
        mock_call.return_value.output = {}
        with pytest.raises(ExtractionError, match="缺少 task_id"):
            run_qwen_asr(DIALOGUE_URL, settings, episode_duration_ms=3000)


def test_run_qwen_asr_subtask_failure(tmp_path):
    """测试子任务未 SUCCEEDED 时整集失败。"""
    settings = _mock_settings(tmp_path)
    failed_output = {
        "results": [{"subtask_status": "FAILED", "message": "audio decode failed"}]
    }

    with _asr_env({"transcripts": []}, wait_output=failed_output):
        with pytest.raises(ExtractionError, match="子任务状态失败"):
            run_qwen_asr(DIALOGUE_URL, settings, episode_duration_ms=3000)


@pytest.mark.parametrize(
    ("wait_output", "message"),
    [
        ({}, "结果结构非法"),
        ({"results": []}, "结果结构非法"),
        ({"results": [{"subtask_status": "SUCCEEDED"}]}, "缺少 transcription_url"),
    ],
)
def test_run_qwen_asr_rejects_illegal_result_shape(tmp_path, wait_output, message):
    """测试任务结果结构非法（无 results 或无转写 URL）时整集失败。"""
    settings = _mock_settings(tmp_path)

    with _asr_env({"transcripts": []}, wait_output=wait_output):
        with pytest.raises(ExtractionError, match=message):
            run_qwen_asr(DIALOGUE_URL, settings, episode_duration_ms=3000)


def test_run_qwen_asr_zero_sentences_fails(tmp_path):
    """测试 ASR 返回零句段时整集失败。"""
    settings = _mock_settings(tmp_path)

    with _asr_env({"transcripts": [{"sentences": []}]}):
        with pytest.raises(ExtractionError, match="零句段"):
            run_qwen_asr(DIALOGUE_URL, settings, episode_duration_ms=5000)


@pytest.mark.parametrize(
    ("sentences", "message"),
    [
        (
            [
                {"text": "句1", "begin_time": 1500, "end_time": 2000},
                {"text": "句2", "begin_time": 1000, "end_time": 1800},
            ],
            "逆序",
        ),
        ([{"text": "句1", "begin_time": 500, "end_time": 3500}], "超过集长"),
        ([{"text": "句1", "begin_time": -5, "end_time": 100}], "时间跨度非法"),
        ([{"text": "句1", "begin_time": "500", "end_time": 1000}], "整数毫秒"),
        ([{"text": "句1", "begin_time": 1000, "end_time": 500}], "时间跨度非法"),
        ([{"text": "   ", "begin_time": 0, "end_time": 100}], "文本为空"),
        ([{"begin_time": 0, "end_time": 100}], "文本为空"),
    ],
)
def test_run_qwen_asr_rejects_illegal_sentences(tmp_path, sentences, message):
    """测试句段时间戳逆序、越界、非整数毫秒或空文本都让整集失败。"""
    settings = _mock_settings(tmp_path)

    with _asr_env({"transcripts": [{"sentences": sentences}]}):
        with pytest.raises(ExtractionError, match=message):
            run_qwen_asr(DIALOGUE_URL, settings, episode_duration_ms=3000)


def test_run_qwen_ocr_and_vlm_request_shapes(tmp_path):
    """测试 OCR/VLM 各发出一次有序图片块与 json_object 响应格式的请求。"""
    settings = _mock_settings(tmp_path)
    data_urls = ["data:image/jpeg;base64,QUFB", "data:image/jpeg;base64,QkJC"]

    ocr_client = MagicMock(name="ocr_client")
    ocr_client.chat.completions.create.return_value = _completion(
        '{"onscreen_texts": ["第一集", "  ", "招牌", 42]}'
    )
    assert run_qwen_ocr(data_urls, settings, ocr_client) == ["第一集", "招牌", "42"]

    vlm_client = MagicMock(name="vlm_client")
    vlm_client.chat.completions.create.return_value = _completion(
        '{"visual_observations": ["男子进入房间"], "uncertainty": ["神情紧张"]}'
    )
    assert run_qwen_vlm(data_urls, settings, vlm_client) == (
        ["男子进入房间"],
        ["神情紧张"],
    )

    for client, model in (
        (ocr_client, "qwen-ocr-model"),
        (vlm_client, "qwen-vlm-model"),
    ):
        assert client.chat.completions.create.call_count == 1
        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == model
        assert kwargs["response_format"] == {"type": "json_object"}
        assert "modalities" not in kwargs
        blocks = kwargs["messages"][1]["content"]
        assert blocks[:-1] == [
            {"type": "image_url", "image_url": {"url": data_url}}
            for data_url in data_urls
        ]  # 帧内容与顺序逐字透传
    assert (
        ocr_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        == EVIDENCE_OCR_SYSTEM_PROMPT
    )
    assert (
        ocr_client.chat.completions.create.call_args.kwargs["messages"][1]["content"][
            -1
        ]["text"]
        == EVIDENCE_OCR_USER_PROMPT
    )
    assert (
        vlm_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        == EVIDENCE_VLM_SYSTEM_PROMPT
    )
    assert (
        vlm_client.chat.completions.create.call_args.kwargs["messages"][1]["content"][
            -1
        ]["text"]
        == EVIDENCE_VLM_USER_PROMPT
    )


def test_run_qwen_audio_observer_request_shape(tmp_path):
    """测试音频观察只提交背景切片的 Base64 input_audio，并声明 modalities=[text]。"""
    settings = _mock_settings(tmp_path)
    wav_file = tmp_path / "slice.wav"
    wav_file.write_bytes(b"riff-wav-data")

    client = MagicMock(name="audio_client")
    client.chat.completions.create.return_value = _stream_completion(
        '{"audio_observations": ["脚步声', '急促"], "uncertainty": []}'
    )
    assert run_qwen_audio_observer(wav_file, settings, client) == (["脚步声急促"], [])

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "qwen3-omni-flash"
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["modalities"] == ["text"]
    assert kwargs["stream"] is True
    block = kwargs["messages"][1]["content"][0]
    assert block["type"] == "input_audio"
    assert block["input_audio"] == {
        "data": "data:audio/wav;base64,cmlmZi13YXYtZGF0YQ==",
        "format": "wav",
    }
    assert kwargs["messages"][0]["content"] == EVIDENCE_AUDIO_OBSERVER_SYSTEM_PROMPT
    assert (
        kwargs["messages"][1]["content"][1]["text"]
        == EVIDENCE_AUDIO_OBSERVER_USER_PROMPT
    )


@pytest.mark.parametrize(
    ("content", "runner", "message"),
    [
        ('{"visual_observations": ["动作"]}', run_qwen_vlm, "uncertainty"),
        ('{"onscreen_texts": null}', run_qwen_ocr, "onscreen_texts"),
        ('```json\n{"onscreen_texts": ["字幕"]}\n```', run_qwen_ocr, None),
        ("[]", run_qwen_ocr, "响应结构非法"),
        ("不是 JSON", run_qwen_ocr, "非合法 JSON"),
    ],
)
def test_qwen_json_response_schema_failures(tmp_path, content, runner, message):
    """测试必需字段缺失或结构非法时抛 ExtractionError，绝不降级为空列表。"""
    settings = _mock_settings(tmp_path)
    client = MagicMock(name="client")
    client.chat.completions.create.return_value = _completion(content)

    if message is None:
        assert runner(["data:image/jpeg;base64,QUFB"], settings, client) == ["字幕"]
    else:
        with pytest.raises(ExtractionError, match=message):
            runner(["data:image/jpeg;base64,QUFB"], settings, client)


def test_run_qwen_ocr_retries_429_until_exhausted(tmp_path):
    """测试 OCR 走统一重试：429 共四次调用后转换为 ExtractionError。"""
    settings = _mock_settings(tmp_path)
    request = httpx.Request("POST", "https://ocr.example/v1/chat/completions")
    response = httpx.Response(429, request=request)
    client = MagicMock(name="client")
    client.chat.completions.create.side_effect = APIStatusError(
        "slow down", response=response, body=None
    )

    with patch("drama_interaction.retry.time.sleep") as mock_sleep:
        with pytest.raises(ExtractionError, match="重试耗尽"):
            run_qwen_ocr(["data:image/jpeg;base64,QUFB"], settings, client)

    assert client.chat.completions.create.call_count == 4
    assert mock_sleep.call_args_list == [((1.0,), {})] * 3


def test_separate_episode_audio_preserves_both_stems(tmp_path):
    settings = _mock_settings(tmp_path)
    video = tmp_path / "测试剧" / "第1集.mp4"
    video.parent.mkdir()
    video.write_bytes(b"video")
    separator = MagicMock()

    def fake_separate(_mix, background_path, dialogue_path, **_kwargs):
        Path(background_path).parent.mkdir(parents=True, exist_ok=True)
        Path(background_path).write_bytes(b"background")
        Path(dialogue_path).write_bytes(b"dialogue")

    separator.separate.side_effect = fake_separate
    mix = tmp_path / "run" / "mix.flac"
    mix.parent.mkdir()
    mix.write_bytes(b"mix")
    with patch(
        "drama_interaction.evidence.extract.AudioSeparatorClient",
        return_value=separator,
    ):
        background, dialogue = separate_episode_audio(video, mix, settings)

    audio_dir = settings.evidence_dir / "测试剧" / "第1集.audio"
    assert background == audio_dir / "background.mp3"
    assert background.read_bytes() == b"background"
    assert dialogue == audio_dir / "dialogue.mp3"
    assert dialogue.read_bytes() == b"dialogue"


def test_transcribe_episode_dialogue_uses_fresh_dialogue_url(tmp_path):
    settings = _mock_settings(tmp_path)
    video = tmp_path / "测试剧" / "第1集.mp4"
    video.parent.mkdir()
    video.write_bytes(b"video")
    separator = MagicMock()
    separator.dialogue_url.return_value = DIALOGUE_URL
    expected = [TranscriptSegment(id="T1", start_ms=0, end_ms=100, text="台词")]

    with (
        patch(
            "drama_interaction.evidence.extract.AudioSeparatorClient",
            return_value=separator,
        ),
        patch(
            "drama_interaction.evidence.extract.run_qwen_asr", return_value=expected
        ) as asr,
    ):
        assert (
            transcribe_episode_dialogue(
                video, settings, 3000, characters=("容遇", "纪舜英")
            )
            == expected
        )

    separator.dialogue_url.assert_called_once_with(
        drama_name="测试剧", episode_name="第1集"
    )
    asr.assert_called_once_with(
        DIALOGUE_URL,
        settings,
        3000,
        characters=("容遇", "纪舜英"),
    )
