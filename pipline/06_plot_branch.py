SYSTEM_PROMPT = """
你是短剧剧情分支生成器。

任务：
根据当前集字幕、当前集高光点、下一集字幕，生成可直接用于互动播放的剧情分支配置。

输入：
0. series_context：剧集背景信息，包含剧名、简介、主要人物，只用于帮助理解人物、关系、设定和整体背景。
1. current_episode_segments：当前集完整字幕，含 segment_id、台词、情绪、音乐、音效等信息。
2. current_episode_highlights：当前集高光点，只用于帮助你优先寻找有互动价值的位置。
3. lookahead_episode_segments：下一集字幕，只用于判断当前集后段分支能否回流到下一集。

使用边界：
1. series_context 只用于辅助理解人物名称、人物关系、故事背景和设定，不是当前集剧情事实来源。
2. 不要把 series_context.description 中的概括性剧情直接当作当前集已经发生、角色已经知道或下一步一定会发生的事实。
3. trigger、resume、当前可选点和分支衔接，必须以 current_episode_segments 和 lookahead_episode_segments 为准。

只生成“主线可回流分支”：
用户在当前集某个 segment 做选择，播放一段短分支内容，然后回到原剧 current 或 next 的某个 segment 继续播放。

选点规则：
1. trigger 必须来自 current_episode_segments，episode 写 "current"。
2. resume 必须来自 current_episode_segments 或 lookahead_episode_segments；来自前者写 "current"，来自后者写 "next"。
3. 每个分支必须能自然回到 resume，不允许生成无法回流的分支。
4. 分支只能改变局部表达、回应方式、行动过程、视角呈现或情绪强化。
5. 分支不能改变人物身份、亲属关系、穿越设定、重要揭晓结果、生死状态、主线矛盾归属。
6. 分支选项不能把下一集新信息当成当前集角色已经知道的事实。
7. 优先选择质疑、冲突、危机、行动前、态度表达前等有选择感的位置。
8. 优先选择距离较近、衔接自然的 resume。
9. 高光点只是参考，不合适就跳过。
10. 只输出可直接制作的分支；没有合适分支时输出 {"branches": []}。

输出必须是严格 JSON，格式如下：

{
  "branches": [
    {
      "trigger": {
        "episode": "current",
        "segment_id": 1
      },
      "question": "展示给用户的选择问题",
      "options": [
        {
          "text": "选项文案",
          "prompt": "用于生成该选项分支内容的提示词"
        }
      ],
      "resume": {
        "episode": "current",
        "segment_id": 2
      }
    }
  ]
}

输出要求：
1. 只输出 JSON。
2. branches 是数组。
3. 每个 branch 只包含 trigger、question、options、resume。
4. options 生成 2-3 个。
5. options.text 要短，适合按钮展示。
6. options.prompt 要能直接交给内容生成模型使用。
7. options.prompt 必须写清人物、场景、分支方向、情绪氛围、不能改变的主线事实、如何衔接到 resume。
8. segment_id 必须来自对应输入中的真实 segment id。
9. episode 只能是 "current" 或 "next"。
"""


USER_PROMPT_TEMPLATE = """
<series_context>
{{series_context}}
</series_context>

<current_episode_segments>
{{current_episode_segments}}
</current_episode_segments>

<current_episode_highlights>
{{current_episode_highlights}}
</current_episode_highlights>

<lookahead_episode_segments>
{{lookahead_episode_segments}}
</lookahead_episode_segments>
"""

import argparse
import asyncio
import json
import re
from pathlib import Path
import sys
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio

from pipline.common.config import get_async_openai_client, get_settings
from pipline.common.paths import DATA_DIR
from pipline.common.runtime import (
    DRAMA_INFO_PATH,
    EpisodeStatus,
    get_drama_name_from_path,
    load_drama_info,
    parse_highlights_list,
    parse_segments_list,
    print_episode_status,
    write_json_document,
)
from pipline.common.schemas import Segment


MAX_ATTEMPTS = 3
STEP_NAME = "plot_branch"
EPISODE_PATTERN = re.compile(r"第(\d+)集$")


class BranchEndpointDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode: Literal["current", "next"]
    segment_id: int


class BranchOptionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    prompt: str


class BranchDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: BranchEndpointDraft
    question: str
    options: list[BranchOptionDraft]
    resume: BranchEndpointDraft

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[BranchOptionDraft]) -> list[BranchOptionDraft]:
        if not 2 <= len(value) <= 3:
            raise ValueError("options 必须包含 2 到 3 个选项")
        return value


class BranchesDraftDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branches: list[BranchDraft]


def strip_markdown_code_block(text: str) -> str:
    """去掉模型可能输出的 Markdown 代码块。"""
    s = text.strip()

    code_block = re.fullmatch(
        r"```(?:json)?\s*([\s\S]*?)\s*```",
        s,
        flags=re.IGNORECASE,
    )

    if code_block:
        return code_block.group(1).strip()

    return s


def parse_model_output(result: str) -> BranchesDraftDocument:
    """按提示词规定的对象结构解析分支草稿。"""
    s = strip_markdown_code_block(result)

    if not s:
        raise ValueError("模型输出为空，放弃全部输出")

    try:
        return BranchesDraftDocument.model_validate_json(s)
    except ValidationError as exc:
        raise ValueError(f"branch.json 校验失败: {exc}") from exc


def build_json_payload(items: list[BaseModel]) -> str:
    """将模型列表压缩为注入 prompt 的紧凑 JSON。"""
    return json.dumps(
        [item.model_dump(mode="json") for item in items],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_series_context_payload(text_path: str | Path) -> str:
    """根据当前剧集路径加载对应短剧背景信息。"""
    drama_info = load_drama_info()
    drama_name = get_drama_name_from_path(text_path)
    drama = drama_info.get(drama_name)
    if drama is None:
        raise ValueError(
            f"找不到短剧 '{drama_name}' 的参考信息，请检查 {DRAMA_INFO_PATH}"
        )

    return json.dumps(
        drama.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_user_prompt(
    current_segments: list,
    current_highlights: list,
    lookahead_segments: list,
    text_path: str | Path,
) -> str:
    """以紧凑 JSON 格式注入 prompt。"""
    return (
        USER_PROMPT_TEMPLATE.replace(
            "{{series_context}}", build_series_context_payload(text_path)
        )
        .replace(
            "{{current_episode_segments}}", build_json_payload(current_segments)
        )
        .replace(
            "{{current_episode_highlights}}", build_json_payload(current_highlights)
        )
        .replace(
            "{{lookahead_episode_segments}}", build_json_payload(lookahead_segments)
        )
    )


def replace_path_part_with_parts(
    path: str | Path, source_part: str, target_parts: tuple[str, ...]
) -> Path:
    """将路径中的指定目录名替换为一个或多个目录名。"""
    source = Path(path)
    parts = list(source.parts)

    try:
        index = parts.index(source_part)
    except ValueError as exc:
        raise ValueError(f"路径 {source} 不包含目录 {source_part}") from exc

    return Path(*parts[:index], *target_parts, *parts[index + 1 :])


def extract_episode_number(path: str | Path) -> int:
    """从“第N集.json”文件名中提取集数。"""
    stem = Path(path).stem
    match = EPISODE_PATTERN.fullmatch(stem)
    if match is None:
        raise ValueError(f"无法从文件名提取集数: {path}")
    return int(match.group(1))


def get_highlight_path(text_path: str | Path) -> Path:
    """根据当前集文本路径推导高光路径。"""
    return replace_path_part_with_parts(text_path, "text", ("highlight",)).with_suffix(
        ".json"
    )


def get_branch_output_path(text_path: str | Path) -> Path:
    """根据当前集文本路径推导分支输出路径。"""
    return replace_path_part_with_parts(
        text_path,
        "text",
        ("branch", "json"),
    ).with_suffix(".json")


def get_branch_output_dir(text_dir: str | Path) -> Path:
    """根据文本目录推导分支输出目录。"""
    return replace_path_part_with_parts(text_dir, "text", ("branch", "json"))


def find_next_episode_text_path(text_path: str | Path) -> Path | None:
    """查找当前集的下一集字幕文件。"""
    current_path = Path(text_path)
    current_episode_number = extract_episode_number(current_path)
    next_path = current_path.with_name(f"第{current_episode_number + 1}集.json")
    if next_path.exists():
        return next_path
    return None


def get_segment_start(segment_map: dict[int, Segment], segment_id: int) -> str:
    """返回 segment 对应的 start 时间。"""
    segment = segment_map.get(segment_id)
    if segment is None:
        raise ValueError(f"segment_id={segment_id} 在对应 segments 中不存在")
    return segment.start


def finalize_endpoint(
    endpoint: BranchEndpointDraft,
    *,
    current_episode_number: int,
    next_episode_number: int | None,
    current_segment_map: dict[int, Segment],
    next_segment_map: dict[int, Segment],
) -> dict[str, int | str]:
    """将 current/next 端点转换为最终输出结构。"""
    if endpoint.episode == "current":
        return {
            "episode": current_episode_number,
            "segment_id": endpoint.segment_id,
            "time": get_segment_start(current_segment_map, endpoint.segment_id),
        }

    if next_episode_number is None:
        raise ValueError("最后一集没有 next episode，不能生成 next 端点")

    return {
        "episode": next_episode_number,
        "segment_id": endpoint.segment_id,
        "time": get_segment_start(next_segment_map, endpoint.segment_id),
    }


def finalize_branches_document(
    result: str | BranchesDraftDocument,
    *,
    current_episode_number: int,
    next_episode_number: int | None,
    current_segments: list,
    next_segments: list,
) -> list[dict]:
    """补齐最终输出所需的 id、集数数字和时间字段。"""
    document = parse_model_output(result) if isinstance(result, str) else result
    current_segment_map = {segment.id: segment for segment in current_segments}
    next_segment_map = {segment.id: segment for segment in next_segments}

    final_branches: list[dict] = []
    for index, branch in enumerate(document.branches, start=1):
        final_branches.append(
            {
                "id": index,
                "trigger": finalize_endpoint(
                    branch.trigger,
                    current_episode_number=current_episode_number,
                    next_episode_number=next_episode_number,
                    current_segment_map=current_segment_map,
                    next_segment_map=next_segment_map,
                ),
                "question": branch.question,
                "options": [
                    option.model_dump(mode="json")
                    for option in branch.options
                ],
                "resume": finalize_endpoint(
                    branch.resume,
                    current_episode_number=current_episode_number,
                    next_episode_number=next_episode_number,
                    current_segment_map=current_segment_map,
                    next_segment_map=next_segment_map,
                ),
            }
        )

    return final_branches


async def text_to_branch(text_path: str, branch_path: str) -> bool:
    """将单个当前集文本、高光和下一集文本转换为最终分支文件。"""
    current_text_path = Path(text_path)
    highlight_path = get_highlight_path(current_text_path)
    if not highlight_path.is_file():
        raise FileNotFoundError(f"当前集高光文件不存在: {highlight_path}")

    next_text_path = find_next_episode_text_path(current_text_path)
    if next_text_path is None:
        return False

    current_segments = parse_segments_list(current_text_path.read_text(encoding="utf-8"))
    current_highlights = parse_highlights_list(highlight_path.read_text(encoding="utf-8"))
    next_segments = parse_segments_list(next_text_path.read_text(encoding="utf-8"))
    user_prompt = build_user_prompt(
        current_segments=current_segments,
        current_highlights=current_highlights,
        lookahead_segments=next_segments,
        text_path=current_text_path,
    )

    settings = get_settings()
    client = get_async_openai_client()

    last_exception: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            completion = await client.chat.completions.create(
                model=settings.llm_model_id,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                temperature=0.3,
            )

            result = completion.choices[0].message.content or '{"branches":[]}'
            final_document = finalize_branches_document(
                result,
                current_episode_number=extract_episode_number(current_text_path),
                next_episode_number=extract_episode_number(next_text_path),
                current_segments=current_segments,
                next_segments=next_segments,
            )
            write_json_document(branch_path, final_document)
            return True
        except Exception as exc:
            last_exception = exc
            if attempt < MAX_ATTEMPTS:
                tqdm.write(
                    f"[retrying][{STEP_NAME}] 第 {attempt} 次失败，剩余 {MAX_ATTEMPTS - attempt} 次: {exc}"
                )

    if last_exception is not None:
        raise last_exception
    raise ValueError(f"重试 {MAX_ATTEMPTS} 次后仍未生成有效分支结果")


async def batch_convert(text_files: list[str], branch_files: list[str]) -> None:
    """批量生成剧情分支。"""
    success_count = 0
    skip_count = 0
    fail_count = 0
    tasks = [
        text_to_branch(text_path, branch_path)
        for text_path, branch_path in zip(text_files, branch_files)
    ]
    for task in tqdm_asyncio.as_completed(tasks, total=len(tasks), desc="文本转分支"):
        try:
            generated = await task
            if generated:
                success_count += 1
            else:
                skip_count += 1
        except Exception:
            fail_count += 1
    tqdm.write(f"完成: 成功 {success_count}，跳过 {skip_count}，失败 {fail_count}")


def batch_convert_dir(text_dir: str | Path, branch_dir: str | Path) -> None:
    """批量转换目录下所有可生成分支的文本 JSON 文件。"""
    text_dir = Path(text_dir)
    branch_dir = Path(branch_dir)
    candidates = list(text_dir.rglob("*.json"))
    text_files: list[str] = []
    branch_files: list[str] = []

    for text_path in tqdm(candidates, desc="扫描文本文件"):
        next_text_path = find_next_episode_text_path(text_path)
        if next_text_path is None:
            tqdm.write(f"[skipped] 最后一集不生成分支: {text_path}")
            continue

        rel_path = text_path.relative_to(text_dir)
        branch_path = branch_dir / rel_path
        if branch_path.exists():
            continue

        text_files.append(str(text_path))
        branch_files.append(str(branch_path))
        branch_path.parent.mkdir(parents=True, exist_ok=True)

    asyncio.run(batch_convert(text_files, branch_files))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="文本转剧情分支工具（异步批量转换）")
    parser.add_argument(
        "--text-path",
        type=str,
        dest="text_path",
        help="当前集文本 JSON 文件或目录路径。传文件转单个，传目录递归转换，不传则转换 data/text 下所有非最后一集文件",
    )
    args = parser.parse_args()

    if args.text_path:
        text_path = Path(args.text_path)
        if text_path.is_file():
            next_text_path = find_next_episode_text_path(text_path)
            branch_path = get_branch_output_path(text_path)
            if next_text_path is None:
                tqdm.write(f"[skipped] 最后一集不生成分支: {text_path}")
            elif branch_path.exists():
                tqdm.write(f"输出文件已存在，跳过: {branch_path}")
            else:
                print_episode_status(
                    status=EpisodeStatus.PENDING,
                    source_path=str(text_path),
                    output_path=str(branch_path),
                )
                branch_path.parent.mkdir(parents=True, exist_ok=True)
                print_episode_status(
                    status=EpisodeStatus.RUNNING,
                    source_path=str(text_path),
                    output_path=str(branch_path),
                )
                try:
                    generated = asyncio.run(
                        text_to_branch(str(text_path), str(branch_path))
                    )
                    if generated:
                        print_episode_status(
                            status=EpisodeStatus.SUCCESS,
                            source_path=str(text_path),
                            output_path=str(branch_path),
                        )
                    else:
                        tqdm.write(f"[skipped] 最后一集不生成分支: {text_path}")
                except Exception as exc:
                    print_episode_status(
                        status=EpisodeStatus.FAILED,
                        source_path=str(text_path),
                        output_path=str(branch_path),
                        error=str(exc),
                    )
                    raise
        elif text_path.is_dir():
            batch_convert_dir(text_path, get_branch_output_dir(text_path))
        else:
            raise FileNotFoundError(f"路径不存在: {text_path}")
    else:
        batch_convert_dir(DATA_DIR / "text", DATA_DIR / "branch" / "json")
