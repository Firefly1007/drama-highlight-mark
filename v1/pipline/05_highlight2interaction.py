import argparse
import asyncio
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio

from pipline.common.paths import DATA_DIR, map_output_dir, map_output_file
from pipline.common.runtime import (
    EpisodeStatus,
    build_interactions_document,
    parse_highlights_list,
    print_episode_status,
    write_json_document,
)
from pipline.steps_05.deferred_vote import generate_deferred_vote_interactions
from pipline.steps_05.emotion_button import generate_emotion_button_interactions
from pipline.steps_05.instant_vote import generate_instant_vote_interactions
from pipline.steps_05.repeat_keyline import generate_repeat_keyline_interactions
from pipline.steps_05.side_comment import generate_side_comment_interactions


API_SEMAPHORE = asyncio.Semaphore(20)


SUPPORTED_INTERACTION_TYPES = {
    1: "emotion_button",
    2: "repeat_keyline",
    3: "instant_vote",
    4: "deferred_vote",
    5: "side_comment",
}


async def generate_interactions_by_type(highpoints: list, highlight_path: str, interaction_type: int):
    """生成单一类型的 interaction 中间结果。"""
    if interaction_type == 1:
        return await generate_emotion_button_interactions(
            highpoints, highlight_path=highlight_path, tqdm=tqdm
        )
    if interaction_type == 2:
        return await generate_repeat_keyline_interactions(
            highpoints, highlight_path=highlight_path, tqdm=tqdm
        )
    if interaction_type == 3:
        return await generate_instant_vote_interactions(
            highpoints, highlight_path=highlight_path, tqdm=tqdm
        )
    if interaction_type == 4:
        return await generate_deferred_vote_interactions(
            highpoints, highlight_path=highlight_path, tqdm=tqdm
        )
    if interaction_type == 5:
        return await generate_side_comment_interactions(
            highpoints, highlight_path=highlight_path, tqdm=tqdm
        )
    raise ValueError(f"暂不支持的互动类型: {interaction_type}")


async def _guarded(coro):
    """用信号量限制并发 API 请求数。"""
    async with API_SEMAPHORE:
        return await coro


async def highlight_to_interaction(highlight_path: str, interaction_path: str) -> None:
    """将单个 highpoints 文件转换为最终 interaction 文件。"""
    raw_text = Path(highlight_path).read_text(encoding="utf-8")
    highpoints = parse_highlights_list(raw_text)

    prepared_groups = await asyncio.gather(
        _guarded(generate_emotion_button_interactions(
            highpoints, highlight_path=highlight_path, tqdm=tqdm
        )),
        _guarded(generate_repeat_keyline_interactions(
            highpoints, highlight_path=highlight_path, tqdm=tqdm
        )),
        _guarded(generate_instant_vote_interactions(
            highpoints, highlight_path=highlight_path, tqdm=tqdm
        )),
        _guarded(generate_deferred_vote_interactions(
            highpoints, highlight_path=highlight_path, tqdm=tqdm
        )),
        _guarded(generate_side_comment_interactions(
            highpoints, highlight_path=highlight_path, tqdm=tqdm
        )),
    )

    prepared_items = [
        item
        for prepared_group in prepared_groups
        for item in prepared_group
    ]
    final_document = build_interactions_document(prepared_items)
    write_json_document(interaction_path, final_document)


async def debug_highlight_to_interaction(highlight_path: str, interaction_type: int) -> None:
    """调试模式：只生成指定类型并输出到 stdout，不落盘。"""
    raw_text = Path(highlight_path).read_text(encoding="utf-8")
    highpoints = parse_highlights_list(raw_text)
    prepared_items = await generate_interactions_by_type(
        highpoints, highlight_path, interaction_type
    )
    final_document = build_interactions_document(prepared_items)
    print(
        json.dumps(
            final_document.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
        )
    )


async def batch_convert(highlight_files: list[str], interaction_files: list[str]) -> None:
    """批量生成 interaction。"""
    success_count = 0
    fail_count = 0
    tasks = [
        highlight_to_interaction(highlight_path, interaction_path)
        for highlight_path, interaction_path in zip(highlight_files, interaction_files)
    ]
    for task in tqdm_asyncio.as_completed(tasks, total=len(tasks), desc="高光转互动"):
        try:
            await task
            success_count += 1
        except Exception:
            fail_count += 1
    tqdm.write(f"完成: 成功 {success_count}，失败 {fail_count}")


def batch_convert_dir(highlight_dir: str | Path, interaction_dir: str | Path) -> None:
    """批量转换目录下所有高光 JSON 文件。"""
    highlight_dir = Path(highlight_dir)
    interaction_dir = Path(interaction_dir)
    candidates = list(highlight_dir.rglob("*.json"))
    highlight_files: list[str] = []
    interaction_files: list[str] = []

    for highlight_path in tqdm(candidates, desc="扫描高光文件"):
        rel_path = highlight_path.relative_to(highlight_dir)
        interaction_path = interaction_dir / rel_path
        if interaction_path.exists():
            continue
        highlight_files.append(str(highlight_path))
        interaction_files.append(str(interaction_path))
        interaction_path.parent.mkdir(parents=True, exist_ok=True)

    asyncio.run(batch_convert(highlight_files, interaction_files))


def get_interaction_path(highlight_path: str | Path) -> Path:
    """根据高光路径推导 interaction 路径（highlight -> interaction）。"""
    return map_output_file(
        highlight_path,
        source_dir_name="highlight",
        target_dir_name="interaction",
        target_suffix=".json",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="高光点转 interaction 工具（异步批量转换）"
    )
    parser.add_argument(
        "--highlight-path",
        type=str,
        dest="highlight_path",
        help="highpoints JSON 文件或目录路径。传文件转单个，传目录递归转换，不传则转换 data/highlight 下所有文件",
    )
    parser.add_argument(
        "--type",
        type=int,
        choices=tuple(SUPPORTED_INTERACTION_TYPES.keys()),
        dest="interaction_type",
        help="调试模式：只生成指定互动类型并输出到 stdout，不写 data/interaction；仅支持单文件输入",
    )
    args = parser.parse_args()

    if args.interaction_type is not None:
        if not args.highlight_path:
            raise ValueError("--type 调试模式必须同时传入 --highlight-path，且路径必须是单个文件")
        highlight_path = Path(args.highlight_path)
        if not highlight_path.is_file():
            raise ValueError("--type 调试模式仅支持单个 highpoints JSON 文件")
        asyncio.run(
            debug_highlight_to_interaction(
                str(highlight_path), args.interaction_type
            )
        )
        raise SystemExit(0)

    if args.highlight_path:
        highlight_path = Path(args.highlight_path)
        if highlight_path.is_file():
            interaction_path = get_interaction_path(highlight_path)
            if interaction_path.exists():
                tqdm.write(f"输出文件已存在，跳过: {interaction_path}")
            else:
                print_episode_status(
                    status=EpisodeStatus.PENDING,
                    source_path=str(highlight_path),
                    output_path=str(interaction_path),
                )
                interaction_path.parent.mkdir(parents=True, exist_ok=True)
                print_episode_status(
                    status=EpisodeStatus.RUNNING,
                    source_path=str(highlight_path),
                    output_path=str(interaction_path),
                )
                try:
                    asyncio.run(
                        highlight_to_interaction(
                            str(highlight_path), str(interaction_path)
                        )
                    )
                    print_episode_status(
                        status=EpisodeStatus.SUCCESS,
                        source_path=str(highlight_path),
                        output_path=str(interaction_path),
                    )
                except Exception as exc:
                    print_episode_status(
                        status=EpisodeStatus.FAILED,
                        source_path=str(highlight_path),
                        output_path=str(interaction_path),
                        error=str(exc),
                    )
                    raise
        elif highlight_path.is_dir():
            interaction_dir = map_output_dir(
                highlight_path,
                source_dir_name="highlight",
                target_dir_name="interaction",
            )
            batch_convert_dir(highlight_path, interaction_dir)
        else:
            raise FileNotFoundError(f"路径不存在: {highlight_path}")
    else:
        batch_convert_dir(DATA_DIR / "highlight", DATA_DIR / "interaction")
