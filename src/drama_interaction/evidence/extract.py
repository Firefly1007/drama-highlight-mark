"""托管多模态证据提取器：腾讯云 CI 人声分离、Qwen ASR、OCR、VLM 与音频观察。"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from http import HTTPStatus
from pathlib import Path
from typing import Any, TypeVar

import dashscope
import httpx
from dashscope.audio.asr import Transcription
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

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
    MODEL_SDK_MAX_RETRIES,
    VIDEO_OBSERVER_SYSTEM_PROMPT,
    VIDEO_OBSERVER_USER_PROMPT_TEMPLATE,
    Settings,
)
from drama_interaction.evidence.audio_separator import AudioSeparatorClient
from drama_interaction.prompt_models import (
    AudioObserverResponse,
    OCRResponse,
    VideoObserverResponse,
    VLMResponse,
)
from drama_interaction.retry import retry_call
from drama_interaction.schemas.evidence import TranscriptSegment


class ExtractionError(RuntimeError):
    """多模态提取或证据校验失败。"""


StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


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


def _qwen_tool_output(
    model_id: str,
    api_key: str,
    base_url: str,
    messages: list[dict[str, Any]],
    response_model: type[StructuredOutput],
    *,
    streaming: bool = False,
    modalities: list[str] | None = None,
) -> StructuredOutput:
    """通过 Pydantic 输出工具调用一个 OpenAI-compatible 模型。"""
    model = ChatOpenAI(
        model=model_id,
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        max_retries=MODEL_SDK_MAX_RETRIES,
        streaming=streaming,
        use_responses_api=False,
    ).with_structured_output(response_model, method="function_calling")
    invoke_kwargs = {"modalities": modalities} if modalities else {}
    return retry_call(
        lambda: model.invoke(messages, **invoke_kwargs),
        ExtractionError,
        f"{model_id} 调用",
    )


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
    response = _qwen_tool_output(
        settings.ocr_model_id,
        settings.ocr_api_key,
        settings.ocr_base_url,
        messages,
        OCRResponse,
    )
    return response.onscreen_texts


def run_qwen_vlm(
    data_urls: Sequence[str],
    settings: Settings,
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
    response = _qwen_tool_output(
        settings.vlm_model_id,
        settings.vlm_api_key,
        settings.vlm_base_url,
        messages,
        VLMResponse,
    )
    return response.visual_observations, response.uncertainty


def run_qwen_audio_observer(
    background_slice_path: Path,
    settings: Settings,
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
    response = _qwen_tool_output(
        settings.audio_observer_model_id,
        settings.audio_observer_api_key,
        settings.audio_observer_base_url,
        messages,
        AudioObserverResponse,
        modalities=["text"],
        streaming=True,
    )
    return response.audio_observations, response.uncertainty


def run_qwen_video_observer(
    video_path: str | Path,
    query: str,
    settings: Settings,
) -> dict[str, list[str]]:
    """将临时 MP4 作为 Base64 视频发送给专用全模态模型。"""
    video_url = "data:video/mp4;base64," + base64.b64encode(
        Path(video_path).read_bytes()
    ).decode("ascii")
    messages = [
        {"role": "system", "content": VIDEO_OBSERVER_SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "video_url", "video_url": {"url": video_url}},
            {"type": "text", "text": VIDEO_OBSERVER_USER_PROMPT_TEMPLATE.format(query=query)},
        ]},
    ]
    response = _qwen_tool_output(
        settings.omni_observer_model_id,
        settings.omni_observer_api_key,
        settings.omni_observer_base_url,
        messages,
        VideoObserverResponse,
        modalities=["text"],
        streaming=True,
    )
    return response.model_dump()


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
    "run_qwen_video_observer",
    "separate_episode_audio",
    "transcribe_episode_dialogue",
]
