"""多模态托管 API 与端到端真实验证集成测试。

默认 `uv run pytest -q` 只收集 tests/unit_tests，本目录不会被执行。
需要真实外部端点时用 `uv run pytest tests/integration_tests --integration`
（或 `-m integration`）显式触发；缺少 Key 或用例内检测不满足时自动 skip。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from drama_interaction.cli import run_episode
from drama_interaction.config import (
    EVIDENCE_SAMPLE_BUCKET_MS,
    EVIDENCE_SLICE_DURATION_MS,
    Settings,
    SettingsError,
    load_settings,
)
from drama_interaction.evidence.extract import (
    frame_data_urls,
    run_qwen_audio_observer,
    run_qwen_ocr,
    run_qwen_vlm,
)
from drama_interaction.media import (
    calculate_sample_timestamps_ms,
    calculate_slices,
    cut_audio_hard,
    extract_audio_flac,
    extract_frames,
    probe_video_duration_ms,
    slice_audio,
)

pytestmark = pytest.mark.integration

VIDEO_PATH = Path("data/video/云渺1：我修仙多年强亿点怎么了/第1集.mp4")


def _get_settings() -> Settings:
    """获取真实配置；如果未配置或为测试占位符则跳过。"""
    try:
        settings = load_settings()
    except SettingsError as exc:
        pytest.skip(f"跳过集成测试：缺少必填环境变量: {exc}")

    keys = [
        settings.audio_separator_access_key_id,
        settings.audio_separator_access_key_secret,
        settings.audio_separator_bucket,
        settings.audio_separator_region,
        settings.asr_api_key,
        settings.audio_observer_api_key,
        settings.ocr_api_key,
        settings.vlm_api_key,
    ]
    for key in keys:
        if not key or key.startswith("test-") or "example" in key:
            pytest.skip("跳过集成测试：检测到占位符 API Key")
    return settings


def _require_video() -> Path:
    if not VIDEO_PATH.is_file():
        pytest.skip(f"测试视频不存在: {VIDEO_PATH}")
    return VIDEO_PATH


def test_media_layer_on_local_video(tmp_path: Path) -> None:
    """验证本地真实短视频的媒体层切片、采帧与音频截取。"""
    video_path = _require_video()

    # 1. 探测集长
    duration_ms = probe_video_duration_ms(video_path)
    assert duration_ms > 0

    # 2. 提取整集 mix.flac
    flac_path = tmp_path / "mix.flac"
    extract_audio_flac(video_path, flac_path)
    assert flac_path.is_file() and flac_path.stat().st_size > 0

    # 3. 切片与 4 FPS 采帧（验证第一个三秒片）
    slices = calculate_slices(duration_ms)
    assert slices[0] == (0, EVIDENCE_SLICE_DURATION_MS)
    start_ms, end_ms = slices[0]
    timestamps = calculate_sample_timestamps_ms(start_ms, end_ms)
    assert timestamps == [
        bucket + EVIDENCE_SAMPLE_BUCKET_MS // 2
        for bucket in range(start_ms, end_ms, EVIDENCE_SAMPLE_BUCKET_MS)
    ]

    frames_dir = tmp_path / "frames"
    frames = extract_frames(video_path, timestamps, frames_dir)
    assert 0 < len(frames) <= len(timestamps)
    for index, frame in enumerate(frames):
        assert frame == frames_dir / f"frame_{index:03d}.jpg"
        assert frame.is_file() and frame.stat().st_size > 0

    # 4. 背景音硬切与三秒切片
    wav_path = tmp_path / "background.wav"
    cut_audio_hard(flac_path, wav_path, duration_ms)
    audio_slice_path = tmp_path / "slice_0_3000.wav"
    slice_audio(wav_path, 0, EVIDENCE_SLICE_DURATION_MS, audio_slice_path)
    assert audio_slice_path.is_file() and audio_slice_path.stat().st_size > 0


def test_real_qwen_vl_ocr_and_vlm(tmp_path: Path) -> None:
    """验证一次采帧同时喂给真实 OCR 与 VLM，并记录请求体大小。"""
    settings = _get_settings()
    video_path = _require_video()

    timestamps = calculate_sample_timestamps_ms(0, EVIDENCE_SLICE_DURATION_MS)
    frames = extract_frames(video_path, timestamps, tmp_path / "frames")
    data_urls = frame_data_urls(frames)
    assert len(data_urls) == len(frames)
    assert all(item.startswith("data:image/jpeg;base64,") for item in data_urls)

    onscreen_texts = run_qwen_ocr(data_urls, settings)
    assert isinstance(onscreen_texts, list)
    for text in onscreen_texts:
        assert isinstance(text, str)

    visual_obs, uncertainty = run_qwen_vlm(data_urls, settings)
    assert isinstance(visual_obs, list)
    assert isinstance(uncertainty, list)


def test_real_qwen_omni_audio_observer(tmp_path: Path) -> None:
    """验证使用真实背景音频切片调用 Qwen Omni 进行音频观察。"""
    settings = _get_settings()
    video_path = _require_video()

    flac_path = tmp_path / "mix.flac"
    extract_audio_flac(video_path, flac_path)
    wav_path = tmp_path / "background.wav"
    cut_audio_hard(flac_path, wav_path, EVIDENCE_SLICE_DURATION_MS)

    audio_slice_path = tmp_path / "slice_0_3000.wav"
    slice_audio(wav_path, 0, EVIDENCE_SLICE_DURATION_MS, audio_slice_path)

    obs, unc = run_qwen_audio_observer(audio_slice_path, settings)
    assert isinstance(obs, list)
    assert isinstance(unc, list)


def test_end_to_end_real_video() -> None:
    """验证一集真实视频端到端生成完整合法 EvidenceDocument。"""
    settings = _get_settings()
    video_path = _require_video()

    state = run_episode(video_path, settings=settings)
    doc = state["evidence"]

    assert doc.episode_duration_ms == probe_video_duration_ms(video_path)
    assert len(doc.transcript_segments) > 0
    assert Path(state["evidence_path"]).is_file()
