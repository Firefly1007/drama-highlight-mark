"""确定性媒体层（切片、采样、探测与抽取）单元测试。"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from drama_interaction.config import (
    EVIDENCE_FRAME_JPEG_QUALITY,
    EVIDENCE_SAMPLE_BUCKET_MS,
    EVIDENCE_SAMPLE_FPS,
    EVIDENCE_SLICE_DURATION_MS,
)
from drama_interaction.media import (
    MediaError,
    calculate_sample_timestamps_ms,
    calculate_slices,
    cut_audio_hard,
    extract_audio_flac,
    extract_frames,
    probe_video_duration_ms,
    slice_audio,
)


def test_calculate_slices_boundaries():
    """测试固定 3000ms 切片及尾片切分。"""
    # 3000ms: 恰好一片
    assert calculate_slices(3000) == [(0, 3000)]

    # 3001ms: 两片，尾片 1ms
    assert calculate_slices(3001) == [(0, 3000), (3000, 3001)]

    # 3125ms: 两片，尾片 125ms
    assert calculate_slices(3125) == [(0, 3000), (3000, 3125)]

    # 3250ms: 两片，尾片 250ms
    assert calculate_slices(3250) == [(0, 3000), (3000, 3250)]

    # 3251ms: 两片，尾片 251ms
    assert calculate_slices(3251) == [(0, 3000), (3000, 3251)]

    # 0 或负数时长返回空
    assert calculate_slices(0) == []
    assert calculate_slices(-100) == []


def test_calculate_sample_timestamps_boundaries():
    """测试 3000/3001/3125/3250/3251ms 的分桶中点采样点。"""
    # 完整 3000ms 切片：12 个目标中点 125, 375, ..., 2875ms
    pts_3000 = calculate_sample_timestamps_ms(0, 3000)
    assert len(pts_3000) == 12
    expected_12 = [125, 375, 625, 875, 1125, 1375, 1625, 1875, 2125, 2375, 2625, 2875]
    assert pts_3000 == expected_12

    # 3001ms 尾片 [3000, 3001): 1 个采样点 (3000ms)
    pts_3001_tail = calculate_sample_timestamps_ms(3000, 3001)
    assert pts_3001_tail == [3000]

    # 3125ms 尾片 [3000, 3125): 1 个采样点 (3000 + 125 // 2 = 3062ms)
    pts_3125_tail = calculate_sample_timestamps_ms(3000, 3125)
    assert pts_3125_tail == [3062]

    # 3250ms 尾片 [3000, 3250): 1 个采样点 (3000 + 250 // 2 = 3125ms)
    pts_3250_tail = calculate_sample_timestamps_ms(3000, 3250)
    assert pts_3250_tail == [3125]

    # 3251ms 尾片 [3000, 3251): 2 个采样点 (3125ms, 3250ms)
    pts_3251_tail = calculate_sample_timestamps_ms(3000, 3251)
    assert pts_3251_tail == [3125, 3250]


def test_probe_video_duration_ms_success(tmp_path):
    """测试通过 ffprobe 成功解析主视频轨时长并转为毫秒。"""
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"dummy")

    fake_output = json.dumps({"streams": [{"duration": "12.345678"}]})

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
        duration = probe_video_duration_ms(video_path)

    assert duration == 12346

    # 只读主视频轨：命令行必须带 -select_streams v:0，且统一按 UTF-8 解码输出
    command, kwargs = mock_run.call_args.args[0], mock_run.call_args.kwargs
    assert command == [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=duration",
        "-of",
        "json",
        str(video_path),
    ]
    assert kwargs == {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "check": False,
    }


def test_probe_video_duration_ms_missing_stream(tmp_path):
    """测试缺少主视频轨时报错。"""
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"dummy")

    fake_output = json.dumps({"streams": []})

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_output, stderr="")
        with pytest.raises(MediaError, match="缺少主视频轨"):
            probe_video_duration_ms(video_path)


def test_probe_video_duration_ms_missing_or_invalid_duration(tmp_path):
    """测试 duration 字段缺失或小于等于 0 时报错。"""
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"dummy")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"streams": [{"duration": "0.0"}]}),
            stderr="",
        )
        with pytest.raises(MediaError, match="主视频轨时长必须大于 0"):
            probe_video_duration_ms(video_path)

        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"streams": [{}]}), stderr=""
        )
        with pytest.raises(MediaError, match="缺少 duration 字段"):
            probe_video_duration_ms(video_path)


def _fake_ffmpeg_writer(
    commands: list[list[str]],
    frames_per_batch: list[int] | None = None,
    returncode: int = 0,
):
    """顶替 ffmpeg：按命令里的 -start_number/-frames:v 落盘 JPEG。"""

    def run(command, **_kwargs):
        cmd = [str(item) for item in command]
        commands.append(cmd)
        batch = len(commands) - 1
        count = int(cmd[cmd.index("-frames:v") + 1])
        start = int(cmd[cmd.index("-start_number") + 1])
        pattern = Path(cmd[-1])
        written = count if frames_per_batch is None else frames_per_batch[batch]
        for offset in range(written):
            path = pattern.parent / pattern.name.replace(
                "%03d", f"{start + offset:03d}"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"jpeg")
        return subprocess.CompletedProcess(cmd, returncode, "", "no decodable frame")

    return run


@pytest.mark.parametrize(
    ("end_ms", "batch_sizes"),
    [
        (3000, [12]),  # 完整三秒片：连续中点只起一个 ffmpeg
        (6000, [24]),  # 两整片中点仍然连续（2875 → 3125 差 250ms）
        (3250, [13]),  # 尾桶中点 3125 仍落在网格上，并入同一批
        (3125, [12, 1]),  # 孤立尾桶中点 3062 单独成批
    ],
)
def test_extract_frames_batches_contiguous_midpoints(tmp_path, end_ms, batch_sizes):
    """测试连续中点合成一批、孤立尾桶另起一批，帧数与目标时刻一一对应。"""
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"dummy")
    out_dir = tmp_path / "frames"
    timestamps = calculate_sample_timestamps_ms(0, end_ms)

    commands: list[list[str]] = []
    with patch("subprocess.run", side_effect=_fake_ffmpeg_writer(commands)):
        frames = extract_frames(video_path, timestamps, out_dir)

    assert [item[item.index("-frames:v") + 1] for item in commands] == [
        str(size) for size in batch_sizes
    ]
    expected_starts = [sum(batch_sizes[:index]) for index in range(len(batch_sizes))]
    assert [item[item.index("-start_number") + 1] for item in commands] == [
        str(start) for start in expected_starts
    ]
    assert [item.name for item in frames] == [
        f"frame_{index:03d}.jpg" for index in range(len(timestamps))
    ]
    assert all(item.is_file() for item in frames)


def test_extract_frames_ffmpeg_command_targets_first_midpoint(tmp_path):
    """测试抽帧命令从首个中点起按 4 FPS 定量取帧并沿用全局编号。"""
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"dummy")
    out_dir = tmp_path / "frames"

    commands: list[list[str]] = []
    with patch("subprocess.run", side_effect=_fake_ffmpeg_writer(commands)):
        extract_frames(video_path, calculate_sample_timestamps_ms(0, 3000), out_dir)

    assert len(commands) == 1
    command = commands[0]
    assert (
        EVIDENCE_SLICE_DURATION_MS,
        EVIDENCE_SAMPLE_BUCKET_MS,
        EVIDENCE_SAMPLE_FPS,
    ) == (3000, 250, 4)
    assert command[0] == "ffmpeg"
    assert command[command.index("-ss") + 1] == "0.125000"
    assert command[command.index("-i") + 1] == str(video_path)
    assert command[command.index("-vf") + 1] == f"fps={EVIDENCE_SAMPLE_FPS}"
    assert command[command.index("-frames:v") + 1] == "12"
    assert command[command.index("-q:v") + 1] == str(EVIDENCE_FRAME_JPEG_QUALITY)
    assert command[command.index("-start_number") + 1] == "0"
    assert command[-1] == str(out_dir / "frame_%03d.jpg")


def test_extract_frames_keeps_written_frames_on_nonzero_exit(tmp_path):
    """测试源末尾 ffmpeg 非零退出时保留已写出的帧，不判死整集。"""
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"dummy")
    out_dir = tmp_path / "frames"

    commands: list[list[str]] = []
    with patch(
        "subprocess.run",
        side_effect=_fake_ffmpeg_writer(
            commands, frames_per_batch=[1, 0], returncode=1
        ),
    ):
        frames = extract_frames(
            video_path, calculate_sample_timestamps_ms(0, 3125), out_dir
        )

    assert [item.name for item in frames] == ["frame_000.jpg"]
    assert len(commands) == 1


def test_extract_frames_partial_batch_is_not_padded(tmp_path):
    """测试 ffmpeg 成功但少出一帧时只保留取到的帧，不补帧也不再跑后续批次。"""
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"dummy")
    out_dir = tmp_path / "frames"

    commands: list[list[str]] = []
    with patch(
        "subprocess.run",
        side_effect=_fake_ffmpeg_writer(commands, frames_per_batch=[11, 1]),
    ):
        frames = extract_frames(
            video_path, calculate_sample_timestamps_ms(0, 3125), out_dir
        )

    assert [item.name for item in frames] == [
        f"frame_{index:03d}.jpg" for index in range(11)
    ]
    assert len(commands) == 1
    assert not (out_dir / "frame_011.jpg").exists()


def test_extract_frames_without_any_frame_raises(tmp_path):
    """测试一批里一张都取不到仍报媒体失败（该切片三路全无输入）。"""
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"dummy")
    out_dir = tmp_path / "frames"

    commands: list[list[str]] = []
    with patch(
        "subprocess.run",
        side_effect=_fake_ffmpeg_writer(commands, frames_per_batch=[0], returncode=1),
    ):
        with pytest.raises(MediaError, match="没有可解码帧"):
            extract_frames(video_path, [125, 375], out_dir)


def test_extract_audio_flac_and_cut(tmp_path):
    """测试音频抽取与硬切调用命令。"""
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"dummy")
    flac_path = tmp_path / "mix.flac"

    def fake_run_flac(cmd, **kw):
        flac_path.write_bytes(b"flac-data")
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=fake_run_flac):
        out = extract_audio_flac(video_path, flac_path)
        assert out == flac_path
        assert out.is_file()

    cut_wav_path = tmp_path / "background.wav"

    def fake_run_cut(cmd, **kw):
        cut_wav_path.write_bytes(b"wav-data")
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=fake_run_cut):
        out = cut_audio_hard(flac_path, cut_wav_path, duration_ms=5000)
        assert out == cut_wav_path
        assert out.is_file()

    slice_wav_path = tmp_path / "slice_0_3000.wav"

    def fake_run_slice(cmd, **kw):
        slice_wav_path.write_bytes(b"slice-data")
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=fake_run_slice):
        out_slice = slice_audio(cut_wav_path, 0, 3000, slice_wav_path)
        assert out_slice == slice_wav_path
        assert out_slice.is_file()
