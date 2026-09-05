"""把 V1 片段确定性转换为 V2 共享证据。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from drama_interaction.schemas.evidence import (
    EvidenceDocument,
    Observation,
    TranscriptSegment,
)

TIME_PATTERN = re.compile(r"^(\d{2,}):([0-5]\d):([0-5]\d)\.(\d{3})$")


class _V1Segment(BaseModel):
    """适配器接收的 V1 片段结构。"""

    model_config = ConfigDict(extra="forbid")

    id: StrictInt = Field(gt=0)
    start: str
    end: str
    text: str = ""
    speech: str = ""
    emotion: str = ""
    voice: str = ""
    music: str = ""
    audio_cues: list[str] | str = Field(default_factory=list)
    uncertainty: list[str] | str = ""


def parse_time_str_to_ms(value: str) -> int:
    """将严格的 ``HH:MM:SS.mmm`` 时间码转换为毫秒。

    Args:
        value: V1 片段中的时间码。

    Returns:
        对应的毫秒数。

    Raises:
        ValueError: 当时间码格式或取值非法时抛出。
    """
    if not isinstance(value, str) or (match := TIME_PATTERN.fullmatch(value)) is None:
        raise ValueError("时间码必须符合 HH:MM:SS.mmm")
    hours, minutes, seconds, milliseconds = map(int, match.groups())
    return hours * 3_600_000 + minutes * 60_000 + seconds * 1_000 + milliseconds


def _nonblank_items(value: str | list[str]) -> list[str]:
    """提取并清理非空的 V1 文本项。

    Args:
        value: 单个文本或文本列表。

    Returns:
        去除首尾空白后的非空文本列表。
    """
    values = [value] if isinstance(value, str) else value
    return [item.strip() for item in values if item.strip()]


def convert_v1_segments_to_evidence(
    segments: list[dict[str, Any]],
    episode_duration_ms: int,
) -> EvidenceDocument:
    """将 V1 片段和预处理阶段给出的集长转换为证据文档。

    Args:
        segments: V1 片段 JSON 数组。
        episode_duration_ms: 媒体预处理阶段确认的单集时长。

    Returns:
        转换后的共享基线证据文档。

    Raises:
        ValueError: 当输入结构、片段顺序或时间范围非法时抛出。
    """
    if type(episode_duration_ms) is not int or episode_duration_ms <= 0:
        raise ValueError("episode_duration_ms 必须为正整数")
    if not isinstance(segments, list):
        raise ValueError("V1 片段 JSON 顶层必须是数组")

    transcripts: list[TranscriptSegment] = []
    observations: list[Observation] = []
    previous_start = -1

    for expected_id, raw_segment in enumerate(segments, start=1):
        segment = _V1Segment.model_validate(raw_segment)
        # 保持 V1 编号连续，避免证据标识错配。
        if segment.id != expected_id:
            raise ValueError(f"V1 片段 id 必须从 1 连续递增，期望 {expected_id}")

        start_ms = parse_time_str_to_ms(segment.start)
        end_ms = parse_time_str_to_ms(segment.end)
        if start_ms > end_ms:
            raise ValueError(f"V1 片段 {segment.id} 的开始时间晚于结束时间")
        if start_ms < previous_start:
            raise ValueError("V1 片段必须按 start 时间升序传入")
        if end_ms > episode_duration_ms:
            raise ValueError(f"V1 片段 {segment.id} 超出 episode_duration_ms")
        previous_start = start_ms

        text = segment.text.strip()
        if text:
            transcripts.append(
                TranscriptSegment(
                    id=f"T{segment.id}",
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                )
            )

        # 只有存在客观音频信息或不确定性时才生成观察。
        audio = [
            *(f"说话方式：{value}" for value in _nonblank_items(segment.speech)),
            *(f"嗓音：{value}" for value in _nonblank_items(segment.voice)),
            *(f"背景音乐：{value}" for value in _nonblank_items(segment.music)),
            *(f"环境音效：{value}" for value in _nonblank_items(segment.audio_cues)),
        ]
        uncertainty = _nonblank_items(segment.uncertainty)
        if audio or uncertainty:
            observations.append(
                Observation(
                    id=f"O{segment.id}",
                    start_ms=start_ms,
                    end_ms=end_ms,
                    audio_observations=list(dict.fromkeys(audio)),
                    uncertainty=list(dict.fromkeys(uncertainty)),
                )
            )

    return EvidenceDocument(
        episode_duration_ms=episode_duration_ms,
        transcript_segments=transcripts,
        observations=observations,
    )


def save_evidence_document(
    document: EvidenceDocument,
    output_path: str | Path,
) -> Path:
    """将已校验证据文档原子写入 JSON 文件。

    Args:
        document: 已通过模型校验的证据文档。
        output_path: 目标 JSON 文件路径。

    Returns:
        实际写入的目标路径。

    Raises:
        OSError: 当临时文件或目标文件写入失败时抛出。
    """
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(
                document.model_dump(mode="json"),
                temp_file,
                ensure_ascii=False,
                indent=2,
            )
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        # 同目录原子替换，避免留下半写文件。
        os.replace(temp_path, target)
    except OSError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    return target


def adapt_file(
    input_path: str | Path,
    episode_duration_ms: int,
    output_dir: str | Path | None = None,
) -> tuple[EvidenceDocument, Path | None]:
    """读取一集 V1 JSON，使用预处理集长适配并按需落盘。

    Args:
        input_path: V1 片段 JSON 文件路径。
        episode_duration_ms: 媒体预处理阶段确认的单集时长。
        output_dir: 可选的证据输出根目录。

    Returns:
        证据文档及可选的落盘路径。

    Raises:
        FileNotFoundError: 当输入文件不存在时抛出。
        ValueError: 当输入 JSON 或片段内容非法时抛出。
    """
    source = Path(input_path)
    if not source.is_file():
        raise FileNotFoundError(f"输入文件不存在: {source}")
    with source.open(encoding="utf-8") as file:
        document = convert_v1_segments_to_evidence(
            json.load(file), episode_duration_ms
        )

    if output_dir is None:
        return document, None

    target = Path(output_dir) / source.parent.name / f"{source.stem}.json"
    return document, save_evidence_document(document, target)
