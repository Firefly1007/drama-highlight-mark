"""托管多模态证据提取器：腾讯云 CI 人声分离、Qwen ASR、OCR、VLM 与音频观察。"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from http import HTTPStatus
from pathlib import Path
from typing import Any

import dashscope
import httpx
from dashscope.audio.asr import Transcription
from openai import OpenAI

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
from drama_interaction.evidence.audio_separator import AudioSeparatorClient
from drama_interaction.retry import retry_call
from drama_interaction.schemas.evidence import TranscriptSegment


class ExtractionError(RuntimeError):
    """多模态提取或证据校验失败。"""


def run_qwen_asr(
    dialogue_url: str,
    settings: Settings,
    episode_duration_ms: int,
    *,
    characters: Sequence[str] = (),
) -> list[TranscriptSegment]:
    """通过 dashscope 官方 SDK 执行 Qwen 异步 ASR 并直接映射为 TranscriptSegment。

    Args:
        dialogue_url: CI 分离出的 dialogue 临时 URL。
        settings: 全局配置。
        episode_duration_ms: 权威集长。
        characters: 当前剧集的角色名，用作即时热词。

    Returns:
        按 provider 返回顺序编号的台词句段列表。

    Raises:
        ExtractionError: 任务失败、零句段或时间戳非法。
    """
    dashscope.base_http_api_url = settings.asr_base_url.rstrip("/")
    vocabulary = {
        character: ASR_VOCABULARY_WEIGHT for character in characters if character
    }
    request = {
        "model": settings.asr_model_id,
        "file_urls": [dialogue_url],
        "channel_id": [0],
        "api_key": settings.asr_api_key,
    }
    if vocabulary:
        request["vocabulary"] = vocabulary

    try:
        response = Transcription.async_call(**request)
    except Exception as exc:
        raise ExtractionError(f"DashScope ASR async_call 失败: {exc}") from exc

    if response.status_code != HTTPStatus.OK:
        raise ExtractionError(
            f"DashScope ASR 提交失败 (status {response.status_code}): {response.message}"
        )
    task_id = (response.output or {}).get("task_id")
    if not task_id:
        raise ExtractionError(f"DashScope ASR 响应缺少 task_id: {response.output}")

    try:
        result = Transcription.wait(
            task=task_id,
            api_key=settings.asr_api_key,
            wait_timeout=ASR_WAIT_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise ExtractionError(f"DashScope ASR wait 失败: {exc}") from exc

    if result.status_code != HTTPStatus.OK:
        raise ExtractionError(
            f"DashScope ASR 任务等待失败 (status {result.status_code}): {result.message}"
        )

    results = (result.output or {}).get("results", [])
    if not results:
        raise ExtractionError(f"DashScope ASR 结果结构非法: {result.output}")
    for subtask in results:
        if subtask.get("subtask_status") != "SUCCEEDED":
            raise ExtractionError(
                f"DashScope ASR 子任务状态失败: {subtask.get('subtask_status')}"
                f", 详情: {subtask.get('message')}"
            )

    transcription_url = results[0].get("transcription_url")
    if not transcription_url:
        raise ExtractionError(
            f"DashScope ASR 子任务成功但缺少 transcription_url: {results[0]}"
        )
    try:
        with httpx.Client(
            timeout=ASR_TRANSCRIPTION_DOWNLOAD_TIMEOUT_SECONDS,
            follow_redirects=True,
        ) as client:
            transcription = client.get(transcription_url)
            transcription.raise_for_status()
            transcription_data = transcription.json()
    except Exception as exc:
        raise ExtractionError(
            f"下载 ASR 转写 JSON 失败 ({transcription_url}): {exc}"
        ) from exc

    sentences = [
        sentence
        for transcript in transcription_data["transcripts"]
        for sentence in transcript["sentences"]
    ]
    if not sentences:
        raise ExtractionError(
            "Qwen ASR 识别结果为零句段，短剧单集必须包含至少一条有效台词"
        )

    segments: list[TranscriptSegment] = []
    for idx, sentence in enumerate(sentences, start=1):
        text = str(sentence.get("text") or "").strip()
        if not text:
            raise ExtractionError(f"ASR 句段 {idx} 文本为空")

        begin_time = sentence.get("begin_time")
        end_time = sentence.get("end_time")
        if not isinstance(begin_time, int) or not isinstance(end_time, int):
            raise ExtractionError(f"ASR 句段 {idx} 时间戳必须为整数毫秒: {sentence}")
        if begin_time < 0 or begin_time > end_time:
            raise ExtractionError(
                f"ASR 句段 {idx} 时间跨度非法: [{begin_time}, {end_time}]"
            )
        if segments and begin_time < segments[-1].start_ms:
            raise ExtractionError(
                f"ASR 句段 {idx} 时间戳逆序: {begin_time} < {segments[-1].start_ms}"
            )
        if end_time > episode_duration_ms:
            raise ExtractionError(
                f"ASR 句段 {idx} 结束时间超过集长: {end_time} > {episode_duration_ms}"
            )

        segments.append(
            TranscriptSegment(
                id=f"T{idx}",
                start_ms=begin_time,
                end_ms=end_time,
                text=text,
                speaker_label=None,
            )
        )

    return segments


def _qwen_json_lists(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    fields: tuple[str, ...],
    **create_kwargs: Any,
) -> dict[str, list[str]]:
    """一次 JSON Object 调用，按字段取回非空字符串列表。

    Raises:
        ExtractionError: 调用重试耗尽，或响应不是带齐 ``fields`` 的 JSON 对象。
    """

    def _call() -> str:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            **create_kwargs,
        )
        if create_kwargs.get("stream"):
            return "".join(chunk.choices[0].delta.content or "" for chunk in completion)
        return completion.choices[0].message.content

    content = retry_call(_call, ExtractionError, f"{model} 调用")
    json_content = content.strip() if isinstance(content, str) else content
    if isinstance(json_content, str):
        json_content = json_content.removeprefix("```json").removeprefix("```")
        json_content = json_content.removesuffix("```").strip()
    try:
        data = json.loads(json_content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"{model} 响应非合法 JSON: {content}") from exc
    if not isinstance(data, dict):
        raise ExtractionError(f"{model} 响应结构非法: {content}")

    values: dict[str, list[str]] = {}
    for field in fields:
        items = data.get(field)
        if not isinstance(items, list):
            raise ExtractionError(f"{model} 响应缺少 {field} 字符串列表: {content}")
        values[field] = [str(item).strip() for item in items if str(item).strip()]
    return values


def frame_data_urls(frame_paths: Sequence[str | Path]) -> list[str]:
    """把同一片的帧一次编码为 Base64 data URL，供 OCR 与 VLM 共用。"""
    return [
        f"data:image/jpeg;base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"
        for path in frame_paths
    ]


def _image_blocks(data_urls: Sequence[str]) -> list[dict[str, Any]]:
    """按采样顺序构造 OpenAI 兼容的图片内容块。"""
    return [
        {"type": "image_url", "image_url": {"url": data_url}} for data_url in data_urls
    ]


def run_qwen_ocr(
    data_urls: Sequence[str],
    settings: Settings,
    client: OpenAI,
) -> list[str]:
    """识别当前切片采样帧上的所有屏幕文字。"""
    messages = [
        {
            "role": "system",
            "content": EVIDENCE_OCR_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": [
                *_image_blocks(data_urls),
                {
                    "type": "text",
                    "text": EVIDENCE_OCR_USER_PROMPT,
                },
            ],
        },
    ]
    values = _qwen_json_lists(
        client, settings.ocr_model_id, messages, ("onscreen_texts",)
    )
    return values["onscreen_texts"]


def run_qwen_vlm(
    data_urls: Sequence[str],
    settings: Settings,
    client: OpenAI,
) -> tuple[list[str], list[str]]:
    """对当前切片采样帧做客观画面观察，不接收任何台词或其它模态结果。"""
    messages = [
        {
            "role": "system",
            "content": EVIDENCE_VLM_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": [
                *_image_blocks(data_urls),
                {
                    "type": "text",
                    "text": EVIDENCE_VLM_USER_PROMPT,
                },
            ],
        },
    ]
    values = _qwen_json_lists(
        client,
        settings.vlm_model_id,
        messages,
        ("visual_observations", "uncertainty"),
    )
    return values["visual_observations"], values["uncertainty"]


def run_qwen_audio_observer(
    background_slice_path: Path,
    settings: Settings,
    client: OpenAI,
) -> tuple[list[str], list[str]]:
    """对当前切片的背景音做客观声音事件观察。"""
    messages = [
        {
            "role": "system",
            "content": EVIDENCE_AUDIO_OBSERVER_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": "data:audio/wav;base64,"
                        + base64.b64encode(background_slice_path.read_bytes()).decode(
                            "ascii"
                        ),
                        "format": "wav",
                    },
                },
                {
                    "type": "text",
                    "text": EVIDENCE_AUDIO_OBSERVER_USER_PROMPT,
                },
            ],
        },
    ]
    values = _qwen_json_lists(
        client,
        settings.audio_observer_model_id,
        messages,
        ("audio_observations", "uncertainty"),
        modalities=["text"],
        stream=True,
    )
    return values["audio_observations"], values["uncertainty"]


def _audio_separator(settings: Settings) -> AudioSeparatorClient:
    return AudioSeparatorClient(
        access_key_id=settings.audio_separator_access_key_id,
        access_key_secret=settings.audio_separator_access_key_secret,
        bucket=settings.audio_separator_bucket,
        region=settings.audio_separator_region,
    )


def separate_episode_audio(
    video_path: str | Path,
    mix_flac_path: str | Path,
    settings: Settings,
) -> tuple[Path, Path]:
    """仅执行 CI 分离，并保留 background/dialogue 两个 MP3。"""
    video = Path(video_path)
    drama_name = video.parent.name
    episode_name = video.stem
    audio_dir = settings.evidence_dir / drama_name / f"{episode_name}.audio"
    background_raw_path = audio_dir / "background.mp3"
    dialogue_path = audio_dir / "dialogue.mp3"

    _audio_separator(settings).separate(
        mix_flac_path,
        background_raw_path,
        dialogue_path,
        drama_name=drama_name,
        episode_name=episode_name,
    )
    return background_raw_path, dialogue_path


def transcribe_episode_dialogue(
    video_path: str | Path,
    settings: Settings,
    episode_duration_ms: int,
    *,
    characters: Sequence[str] = (),
) -> list[TranscriptSegment]:
    """为已分离的 dialogue 生成新 URL，并提交整集 ASR。"""
    video = Path(video_path)
    dialogue_url = _audio_separator(settings).dialogue_url(
        drama_name=video.parent.name,
        episode_name=video.stem,
    )
    return run_qwen_asr(
        dialogue_url, settings, episode_duration_ms, characters=characters
    )


__all__ = [
    "ExtractionError",
    "frame_data_urls",
    "run_qwen_asr",
    "run_qwen_audio_observer",
    "run_qwen_ocr",
    "run_qwen_vlm",
    "separate_episode_audio",
    "transcribe_episode_dialogue",
]
