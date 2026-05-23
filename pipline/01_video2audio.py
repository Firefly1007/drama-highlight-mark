import argparse
import asyncio
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio

from pipline.common.paths import DATA_DIR, map_output_dir, map_output_file
from pipline.common.runtime import EpisodeStatus, print_episode_status


async def video_to_audio(video_path: str, audio_path: str):
    """将视频文件转换为音频（异步）"""
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-acodec', 'libmp3lame', '-q:a', '0',
        audio_path
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError:
        raise FileNotFoundError("ffmpeg 未安装或不在 PATH 中")

    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed with code {proc.returncode}")



async def batch_convert(video_files: list[str], audio_files: list[str]):
    """批量转换"""
    success_count = 0
    fail_count = 0
    tasks = [video_to_audio(v, a) for v, a in zip(video_files, audio_files)]
    for task in tqdm_asyncio.as_completed(tasks, total=len(tasks), desc="视频转音频"):
        try:
            await task
            success_count += 1
        except Exception:
            fail_count += 1
    tqdm.write(f"完成: 成功 {success_count}，失败 {fail_count}")


def batch_convert_dir(video_dir: str | Path, audio_dir: str | Path):
    """批量转换目录下所有视频文件"""
    video_dir = Path(video_dir)
    audio_dir = Path(audio_dir)
    video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv'}
    candidates = [
        p for p in video_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in video_exts
    ]
    video_files = []
    audio_files = []
    for video_path in tqdm(candidates, desc="扫描视频文件"):
        rel_path = video_path.relative_to(video_dir)
        audio_path = audio_dir / rel_path.with_suffix(".mp3")
        if audio_path.exists():
            continue
        video_files.append(str(video_path))
        audio_files.append(str(audio_path))
        audio_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(batch_convert(video_files, audio_files))


def get_audio_path(video_path: str | Path) -> Path:
    """根据视频路径推导音频路径（video -> audio，后缀改 .mp3）"""
    return map_output_file(
        video_path,
        source_dir_name="video",
        target_dir_name="audio",
        target_suffix=".mp3",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="视频转音频工具（异步批量转换）")
    parser.add_argument("--video-path", type=str, dest="video_path",
                        help="视频文件或目录路径。传文件转单个，传目录递归转换，不传则转换 data/video 下所有视频")
    args = parser.parse_args()

    if args.video_path:
        video_path = Path(args.video_path)
        if video_path.is_file():
            audio_path = get_audio_path(video_path)
            if audio_path.exists():
                tqdm.write(f"输出文件已存在，跳过: {audio_path}")
            else:
                print_episode_status(
                    status=EpisodeStatus.PENDING,
                    source_path=str(video_path),
                    output_path=str(audio_path),
                )
                audio_path.parent.mkdir(parents=True, exist_ok=True)
                asyncio.run(video_to_audio(str(video_path), str(audio_path)))
        elif video_path.is_dir():
            audio_dir = map_output_dir(
                video_path,
                source_dir_name="video",
                target_dir_name="audio",
            )
            batch_convert_dir(video_path, audio_dir)
        else:
            raise FileNotFoundError(f"路径不存在: {video_path}")
    else:
        batch_convert_dir(DATA_DIR / "video", DATA_DIR / "audio")
