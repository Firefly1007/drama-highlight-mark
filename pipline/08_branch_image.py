SYSTEM_PROMPT = ""  # 本脚本不调用 LLM，保留字段仅为结构一致

import argparse
import asyncio
import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path
import sys
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipline.common.config import get_settings, get_video_client
from pipline.common.paths import DATA_DIR
from pipline.common.runtime import EpisodeStatus


MAX_ATTEMPTS = 3
STEP_NAME = "branch_image"
EPISODE_PATTERN = re.compile(r"第(\d+)集$")


class PromptItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_index: int = Field(ge=0)
    option_index: int = Field(ge=0)
    prompt: str

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("prompt 不能为空字符串")
        return text


class BranchEndpointInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode: int
    segment_id: int = Field(ge=1)
    time: str


class BranchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    trigger: BranchEndpointInput
    question: str
    options: list[Any]
    resume: BranchEndpointInput


def parse_prompt_items(raw_text: str) -> list[PromptItem]:
    """解析 prompt JSON 根数组。"""
    try:
        payload = json.loads(raw_text)
        if not isinstance(payload, list):
            raise ValueError("prompt JSON 必须是根数组格式")
        return [PromptItem.model_validate(item) for item in payload]
    except json.JSONDecodeError as exc:
        raise ValueError(f"prompt JSON 不是合法 JSON: {exc}") from exc
    except ValidationError as exc:
        raise ValueError(f"prompt JSON 校验失败: {exc}") from exc


def parse_branch_items(raw_text: str) -> list[BranchInput]:
    """解析 branch JSON 根数组。"""
    try:
        payload = json.loads(raw_text)
        if not isinstance(payload, list):
            raise ValueError("branch JSON 必须是根数组格式")
        return [BranchInput.model_validate(item) for item in payload]
    except json.JSONDecodeError as exc:
        raise ValueError(f"branch JSON 不是合法 JSON: {exc}") from exc
    except ValidationError as exc:
        raise ValueError(f"branch JSON 校验失败: {exc}") from exc


def get_branch_path_from_prompt_path(prompt_path: Path) -> Path:
    """根据 prompt 路径推导对应的 branch JSON 路径。"""
    parts = list(prompt_path.parts)
    try:
        idx = parts.index("prompt")
    except ValueError:
        raise ValueError(f"路径 {prompt_path} 不包含 prompt 目录")
    parts[idx] = "json"
    return Path(*parts)


def get_image_dir_from_prompt_path(prompt_path: Path) -> Path:
    """根据 prompt 路径推导图片输出目录。"""
    parts = list(prompt_path.parts)
    try:
        idx = parts.index("prompt")
    except ValueError:
        raise ValueError(f"路径 {prompt_path} 不包含 prompt 目录")
    parts[idx] = "image"
    return Path(*parts).with_suffix("")


def get_video_path(episode: int, drama_name: str) -> Path:
    """根据集数和剧名定位视频文件。"""
    return DATA_DIR / "video" / drama_name / f"第{episode}集.mp4"


def extract_drama_name_from_path(path: Path) -> str:
    """从路径中提取剧名（prompt/json 目录下的第一级子目录名）。"""
    parts = list(path.parts)
    try:
        idx = parts.index("prompt")
    except ValueError:
        try:
            idx = parts.index("json")
        except ValueError:
            raise ValueError(f"路径 {path} 不包含 prompt 或 json 目录")
    return parts[idx + 1]


def extract_episode_number(path: Path) -> int:
    """从“第N集.json”文件名中提取集数。"""
    match = EPISODE_PATTERN.fullmatch(path.stem)
    if match is None:
        raise ValueError(f"无法从文件名提取集数: {path}")
    return int(match.group(1))


def sort_prompt_files_by_episode(prompt_files: list[Path]) -> list[Path]:
    """按集数对 prompt 文件做自然排序。"""
    return sorted(
        prompt_files,
        key=lambda path: (extract_episode_number(path), path.name),
    )


def get_expected_image_paths(prompt_path: Path) -> list[Path]:
    """根据 prompt 文件计算期望输出的图片路径列表。"""
    prompt_items = parse_prompt_items(prompt_path.read_text(encoding="utf-8"))
    image_dir = get_image_dir_from_prompt_path(prompt_path)
    return [
        image_dir / f"{item.branch_index}_{item.option_index}.jpeg"
        for item in prompt_items
    ]


def is_prompt_file_complete(prompt_path: Path) -> bool:
    """判断某个 prompt 文件对应的图片是否已经全部生成完成。"""
    try:
        expected_image_paths = get_expected_image_paths(prompt_path)
    except Exception:
        return False

    return all(path.is_file() for path in expected_image_paths)


def extract_frame_as_data_uri(video_path: Path, timestamp: str) -> str:
    """用 ffmpeg 从视频中截取指定时间戳的帧，返回 data URI。"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", timestamp,
            "-i", str(video_path),
            "-frames:v", "1",
            "-f", "image2",
            tmp_path,
        ]
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
        )
        with open(tmp_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/png;base64,{b64}"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def generate_image(prompt: str, image_data_uris: list[str]) -> bytes:
    """调用图片生成 API，返回 JPEG 二进制数据。"""
    settings = get_settings()
    client = get_video_client()

    response = client.images.generate(
        model=settings.video_model_id,
        prompt=prompt,
        size="1600x2848",
        response_format="b64_json",
        extra_body={
            "image": image_data_uris,
            "watermark": False,
            "sequential_image_generation": "disabled",
        },
    )
    response_data = response.data
    if not response_data:
        raise ValueError("图片生成响应缺少 data")

    b64_json = response_data[0].b64_json
    if not isinstance(b64_json, str) or not b64_json:
        raise ValueError("图片生成响应缺少 b64_json")

    return base64.b64decode(b64_json)


async def process_prompt_file(
    prompt_path: Path,
    *,
    emit_status_logs: bool = True,
) -> None:
    """处理单个 prompt JSON 文件：截帧、生图、保存。"""
    source_path = str(prompt_path)
    output_path = str(get_image_dir_from_prompt_path(prompt_path))
    if emit_status_logs:
        log_episode_status(
            status=EpisodeStatus.PENDING,
            source_path=source_path,
            output_path=output_path,
        )
        log_episode_status(
            status=EpisodeStatus.RUNNING,
            source_path=source_path,
            output_path=output_path,
        )

    try:
        prompt_items = parse_prompt_items(prompt_path.read_text(encoding="utf-8"))
        if not prompt_items:
            if emit_status_logs:
                log_episode_status(
                    status=EpisodeStatus.SUCCESS,
                    source_path=source_path,
                    output_path=output_path,
                )
            return

        branch_path = get_branch_path_from_prompt_path(prompt_path)
        branch_items = parse_branch_items(branch_path.read_text(encoding="utf-8"))
        drama_name = extract_drama_name_from_path(prompt_path)
        image_dir = get_image_dir_from_prompt_path(prompt_path)
        image_dir.mkdir(parents=True, exist_ok=True)

        # 按 branch_index 分组，同一 branch 只截帧一次
        grouped: dict[int, list[PromptItem]] = {}
        for item in prompt_items:
            grouped.setdefault(item.branch_index, []).append(item)

        for branch_index, items in grouped.items():
            if branch_index >= len(branch_items):
                raise ValueError(
                    f"branch_index {branch_index} 超出 branch.json 范围 "
                    f"(共 {len(branch_items)} 个分支)"
                )
            branch = branch_items[branch_index]
            video_path = get_video_path(branch.trigger.episode, drama_name)
            if not video_path.is_file():
                raise FileNotFoundError(f"视频文件不存在: {video_path}")

            start_frame, resume_frame = await asyncio.gather(
                asyncio.to_thread(
                    extract_frame_as_data_uri, video_path, branch.trigger.time
                ),
                asyncio.to_thread(
                    extract_frame_as_data_uri, video_path, branch.resume.time
                ),
            )

            for item in items:
                try:
                    jpeg_bytes = await asyncio.to_thread(
                        generate_image, item.prompt, [start_frame, resume_frame]
                    )
                    out_path = image_dir / f"{item.branch_index}_{item.option_index}.jpeg"
                    out_path.write_bytes(jpeg_bytes)
                except Exception as exc:
                    print(
                        f"[warn][{STEP_NAME}] {source_path} "
                        f"branch={item.branch_index} option={item.option_index} 跳过: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )

        if emit_status_logs:
            log_episode_status(
                status=EpisodeStatus.SUCCESS,
                source_path=source_path,
                output_path=output_path,
            )
    except Exception as exc:
        log_episode_status(
            status=EpisodeStatus.FAILED,
            source_path=source_path,
            output_path=output_path,
            error=str(exc),
        )
        raise


def log_episode_status(
    status: EpisodeStatus,
    *,
    source_path: str,
    output_path: str,
    error: str = "",
) -> None:
    """将单文件处理状态打印到 stderr。"""
    message = f"[{status.value}][{STEP_NAME}] {source_path} -> {output_path}"
    if error:
        message = f"{message} | {error}"
    print(message, file=sys.stderr, flush=True)


async def batch_process_prompt_files(prompt_files: list[Path]) -> None:
    """异步批量处理 prompt 文件。"""
    success_count = 0
    fail_count = 0
    tasks = [
        process_prompt_file(prompt_file, emit_status_logs=False)
        for prompt_file in prompt_files
    ]
    for task in tqdm_asyncio.as_completed(
        tasks,
        total=len(tasks),
        desc="prompt转分支图片",
    ):
        try:
            await task
            success_count += 1
        except Exception:
            fail_count += 1

    tqdm.write(f"完成: 成功 {success_count}，失败 {fail_count}")


def batch_process_prompt_dir(prompt_dir: Path) -> None:
    """处理目录下所有 prompt 文件。"""
    prompt_files = sort_prompt_files_by_episode(
        [
            prompt_file
            for prompt_file in prompt_dir.rglob("*.json")
            if not is_prompt_file_complete(prompt_file)
        ]
    )
    asyncio.run(batch_process_prompt_files(prompt_files))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="视频提示词转分支图片工具")
    parser.add_argument(
        "--prompt-path",
        type=str,
        dest="prompt_path",
        help="prompt JSON 文件或目录路径。传文件只处理该文件；不传则读取 data/branch/prompt",
    )
    args = parser.parse_args()

    prompt_path = (
        Path(args.prompt_path) if args.prompt_path else DATA_DIR / "branch" / "prompt"
    )
    if prompt_path.is_file():
        asyncio.run(process_prompt_file(prompt_path))
    elif prompt_path.is_dir():
        batch_process_prompt_dir(prompt_path)
    else:
        raise FileNotFoundError(f"路径不存在: {prompt_path}")
