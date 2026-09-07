"""确定性媒体层：ffprobe/ffmpeg 媒体探测、音频抽取、固定切片与采帧。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from drama_interaction.config import (
    EVIDENCE_FRAME_JPEG_QUALITY,
    EVIDENCE_SAMPLE_BUCKET_MS,
    EVIDENCE_SAMPLE_FPS,
    EVIDENCE_SLICE_DURATION_MS,
)


class MediaError(RuntimeError):
    """媒体探测、抽取或采样失败。"""


def _run(
    command: list[str], failure: str, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """执行 ffmpeg/ffprobe；所有子进程统一按 UTF-8 读取输出。

    ``check=False`` 用于源末尾已无帧、ffmpeg 会以非零码退出的采样批次。
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        raise MediaError(f"执行 {command[0]} 失败: {exc}") from exc
    if check and result.returncode != 0:
        raise MediaError(
            f"{failure} (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result


def probe_video_duration_ms(video_path: str | Path) -> int:
    """通过 ffprobe 读取主视频轨 v:0 的时长并转换为最近整数毫秒。

    Args:
        video_path: 视频文件路径。

    Returns:
        主视频轨时长（整数毫秒）。

    Raises:
        MediaError: 文件不存在、无法读取或缺少有效主视频轨时长。
    """
    path = Path(video_path)
    if not path.is_file():
        raise MediaError(f"视频文件不存在: {path}")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=duration",
        "-of",
        "json",
        str(path),
    ]

    result = _run(command, "ffprobe 探测失败")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(f"ffprobe 返回的 JSON 无法解析: {exc}") from exc

    streams = data.get("streams", [])
    if not streams:
        raise MediaError(f"视频缺少主视频轨 (v:0): {path}")

    duration_str = streams[0].get("duration")
    if duration_str is None:
        raise MediaError(f"主视频轨缺少 duration 字段: {path}")

    try:
        duration_sec = float(duration_str)
    except (TypeError, ValueError) as exc:
        raise MediaError(f"主视频轨 duration 无效: {duration_str!r}") from exc

    if duration_sec <= 0:
        raise MediaError(f"主视频轨时长必须大于 0，实际为: {duration_sec}")

    return round(duration_sec * 1000)


def extract_audio_flac(video_path: str | Path, output_flac_path: str | Path) -> Path:
    """使用 ffmpeg 提取整集 mix.flac。

    Args:
        video_path: 输入视频路径。
        output_flac_path: 输出 flac 音频路径。

    Returns:
        输出 flac 路径。

    Raises:
        MediaError: 音频抽取失败。
    """
    video = Path(video_path)
    output = Path(output_flac_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vn",
        "-acodec",
        "flac",
        str(output),
    ]

    _run(command, "ffmpeg 抽取 mix.flac 失败")

    if not output.is_file() or output.stat().st_size == 0:
        raise MediaError(f"抽取得到的 mix.flac 为空或不存在: {output}")

    return output


def cut_audio_hard(
    input_audio_path: str | Path,
    output_audio_path: str | Path,
    duration_ms: int,
) -> Path:
    """使用 ffmpeg 将背景音硬切为权威集长。

    Args:
        input_audio_path: 输入音频路径。
        output_audio_path: 输出音频路径。
        duration_ms: 目标时长（毫秒）。

    Returns:
        输出音频路径。

    Raises:
        MediaError: 硬切失败。
    """
    input_path = Path(input_audio_path)
    output = Path(output_audio_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-t",
        f"{duration_ms / 1000.0:.6f}",
        str(output),
    ]

    _run(command, "ffmpeg 硬切音频失败")

    if not output.is_file() or output.stat().st_size == 0:
        raise MediaError(f"硬切后的 background.wav 为空或不存在: {output}")

    return output


def calculate_slices(duration_ms: int) -> list[tuple[int, int]]:
    """按配置跨度生成非重叠切片列表，保留不足周期的尾片。

    start_ms = EVIDENCE_SLICE_DURATION_MS * k
    end_ms   = min(start_ms + EVIDENCE_SLICE_DURATION_MS, duration_ms)

    Args:
        duration_ms: 总时长（毫秒）。

    Returns:
        切片起止时间元组列表 [(start_ms, end_ms), ...]。
    """
    return [
        (start, min(start + EVIDENCE_SLICE_DURATION_MS, duration_ms))
        for start in range(0, duration_ms, EVIDENCE_SLICE_DURATION_MS)
    ]


def calculate_sample_timestamps_ms(start_ms: int, end_ms: int) -> list[int]:
    """计算切片内按配置分桶的中点采样时刻（毫秒）。

    bucket_start = start_ms + EVIDENCE_SAMPLE_BUCKET_MS * j
    bucket_end   = min(bucket_start + EVIDENCE_SAMPLE_BUCKET_MS, end_ms)
    sample_ms    = bucket_start + floor((bucket_end - bucket_start) / 2)

    Args:
        start_ms: 切片开始毫秒。
        end_ms: 切片结束毫秒。

    Returns:
        采样点毫秒列表。
    """
    return [
        bucket_start
        + (min(bucket_start + EVIDENCE_SAMPLE_BUCKET_MS, end_ms) - bucket_start) // 2
        for bucket_start in range(start_ms, end_ms, EVIDENCE_SAMPLE_BUCKET_MS)
    ]


def extract_frames(
    video_path: str | Path,
    timestamps_ms: list[int],
    output_dir: str | Path,
) -> list[Path]:
    """根据目标时刻列表抽取采样 JPEG 帧。

    连续的中点用一次 ffmpeg 的 4 FPS 输出取回，只落在非完整尾桶上的孤立
    采样点单独成批。源视频提前结束时该批就少给几帧：只保留真正写出的帧，
    不补帧也不回退，之后的桶一律放弃；一张都取不到才算媒体失败。

    Args:
        video_path: 视频文件路径。
        timestamps_ms: 采样时刻列表（毫秒）。
        output_dir: 帧图片保存目录。

    Returns:
        抽取出的 JPEG 文件路径列表（按 timestamps_ms 升序，可能短于它）。

    Raises:
        MediaError: 抽帧失败或该批目标时刻内完全没有可解码帧。
    """
    video = Path(video_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    extracted_frames: list[Path] = []
    index = 0
    while index < len(timestamps_ms):
        count = 1
        while (
            index + count < len(timestamps_ms)
            and timestamps_ms[index + count] - timestamps_ms[index + count - 1]
            == EVIDENCE_SAMPLE_BUCKET_MS
        ):
            count += 1

        command = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{timestamps_ms[index] / 1000.0:.6f}",
            "-i",
            str(video),
            "-vf",
            f"fps={EVIDENCE_SAMPLE_FPS}",
            "-frames:v",
            str(count),
            "-q:v",
            str(EVIDENCE_FRAME_JPEG_QUALITY),
            "-start_number",
            str(index),
            str(out_dir / "frame_%03d.jpg"),
        ]
        result = _run(
            command, f"抽帧失败（起始 {timestamps_ms[index]}ms）", check=False
        )

        batch: list[Path] = []
        for offset in range(count):
            frame_path = out_dir / f"frame_{index + offset:03d}.jpg"
            if not frame_path.is_file() or frame_path.stat().st_size == 0:
                break
            batch.append(frame_path)
        extracted_frames.extend(batch)
        if len(batch) < count:
            break

        index += count

    if not extracted_frames:
        raise MediaError(
            f"目标时刻内没有可解码帧（起始 {timestamps_ms[0]}ms）：{(result.stderr or '').strip()[-200:]}"
        )
    return extracted_frames


def slice_audio(
    input_wav_path: str | Path,
    start_ms: int,
    end_ms: int,
    output_wav_path: str | Path,
) -> Path:
    """使用 ffmpeg 截取指定起止毫秒的音频切片。

    Args:
        input_wav_path: 输入背景音路径。
        start_ms: 切片开始时间（毫秒）。
        end_ms: 切片结束时间（毫秒）。
        output_wav_path: 输出音频切片路径。

    Returns:
        输出切片路径。

    Raises:
        MediaError: 切割失败。
    """
    input_path = Path(input_wav_path)
    output = Path(output_wav_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_ms / 1000.0:.6f}",
        "-t",
        f"{(end_ms - start_ms) / 1000.0:.6f}",
        "-i",
        str(input_path),
        str(output),
    ]

    _run(command, f"音频切片提取失败 [{start_ms}, {end_ms})")

    if not output.is_file() or output.stat().st_size == 0:
        raise MediaError(f"音频切片为空或不存在: {output}")

    return output


__all__ = [
    "MediaError",
    "calculate_sample_timestamps_ms",
    "calculate_slices",
    "cut_audio_hard",
    "extract_audio_flac",
    "extract_frames",
    "probe_video_duration_ms",
    "slice_audio",
]
