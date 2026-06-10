SYSTEM_PROMPT = """
你是短剧分支视频提示词生成器。

输入包含：
- series_context：剧集背景信息，包含剧名、简介、主要人物，只用于帮助理解人物、关系、设定和整体背景
- current_episode_segments：当前集字幕
- lookahead_episode_segments：下一集字幕
- branches：已确定的剧情分支配置

使用边界：
1. series_context 只用于辅助理解人物名称、人物关系、故事背景和设定。series_context 不是当前集剧情事实来源。
2. 不要把 series_context.description 中的概括性剧情直接当作当前分支里已经发生、角色已经知道或画面里一定会直接出现的事实。
3. 不要因为 series_context.characters 或 description 提到某个角色，就默认该角色一定在当前分支视频画面里出场；人物是否出场、站位和互动关系应以 branches、字幕和参考帧语义为准。
4. trigger、resume、分支选项方向和主线约束，必须以 branches、current_episode_segments 和 lookahead_episode_segments 为准。

视频生成模型还会额外收到两张参考图：
- start_frame_image：分支开始前的尾帧图
- resume_frame_image：分支结束后要回归的原剧首帧图

任务：
为 branches 中每个非“原剧情” option 生成一条视频生成提示词。

处理方法：
1. 根据 branch.trigger 找到分支开始位置。
2. 根据 branch.resume 找到分支结束后要接回的位置。
3. branches 里的 options[0] 表示继续原剧情；它的 text 是正常按钮文案，prompt 为空字符串。不要为它生成 video_prompt。
4. 只根据非原剧情 option 的 option.text 和 option.prompt 生成一段短视频内容。
5. 视频开头必须承接 start_frame_image。
6. 视频结尾必须贴近 resume_frame_image，方便无缝接回原剧。
7. 保持原剧主线事实不变，包括人物身份、亲属关系、穿越设定、重要揭晓结果、生死状态和主线矛盾。

每条视频生成提示词必须按下面结构写：

【基础规格】
竖屏 9:16，短剧质感，真实演员实拍风格，节奏紧凑，时长建议 8-20 秒。

【首帧承接】
说明视频第一帧要延续 start_frame_image 的人物位置、镜头景别、光线、色调、场景方向和情绪状态。
不要突然换场景、换服装、换人物站位。

【人物与场景】
说明画面中有哪些人物、他们的关系、所在地点、现场氛围。
不要新增会影响主线的新角色。

【分支内容】
围绕当前 option 展开一小段剧情。
写清角色具体动作、表情、情绪变化和关键反应。
内容只能补充 trigger 到 resume 之间的过程，不能改写 resume 之后的主线。

【镜头设计】
写 3-5 个连续镜头。
每个镜头说明景别和动作，例如：
1. 中景：延续首帧站位，角色看向众人。
2. 近景：角色表情变化，做出当前选项对应的回应。
3. 反应镜头：周围人产生短暂反应。
4. 推镜或切特写：情绪达到峰值。
5. 收束镜头：人物位置和状态逐渐接近 resume_frame_image。

【台词与声音】
可以包含 1-3 句短台词。
台词要符合人物身份和短剧风格。
说明背景音乐和音效，例如悬疑鼓点、短促停顿、爆炸声、人群惊呼、卡通音效等。
不要写长对白。

【尾帧回归】
说明视频最后一帧要尽量对齐 resume_frame_image：
人物应回到相近位置，镜头景别相近，光线色调相近，情绪状态相近，动作应能自然接上 resume 对应的原剧 segment。
最后一帧不能出现与 resume_frame_image 冲突的人物状态或场景变化。

【主线约束】
用一句话说明本视频必须保持不变的剧情事实。

输出严格 JSON：

{
  "video_prompts": [
    {
      "branch_index": 0,
      "option_index": 1,
      "prompt": "视频生成提示词"
    }
  ]
}

要求：
- 每个非原剧情 option 输出一条 video_prompt。
- 不要为 options[0] 的“原剧情”项输出 video_prompt。
- branch_index 和 option_index 使用数组下标，从 0 开始。
- prompt 使用中文。
- prompt 写成可直接交给视频生成模型的画面指令。
- prompt 里保留上面的【基础规格】【首帧承接】【人物与场景】【分支内容】【镜头设计】【台词与声音】【尾帧回归】【主线约束】小标题。
- 只输出 JSON。
"""


USER_PROMPT_TEMPLATE = """
<series_context>
{{series_context}}
</series_context>

<current_episode_segments>
{{current_episode_segments}}
</current_episode_segments>

<lookahead_episode_segments>
{{lookahead_episode_segments}}
</lookahead_episode_segments>

<branches>
{{branches}}
</branches>
"""

import argparse
import asyncio
import json
import re
from pathlib import Path
import sys
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipline.common.config import get_async_openai_client, get_settings
from pipline.common.paths import DATA_DIR
from pipline.common.runtime import (
    DRAMA_INFO_PATH,
    EpisodeStatus,
    get_drama_name_from_path,
    load_drama_info,
    parse_segments_list,
    write_json_document,
)


MAX_ATTEMPTS = 3
STEP_NAME = "branch_video"
API_SEMAPHORE = asyncio.Semaphore(20)
EPISODE_PATTERN = re.compile(r"第(\d+)集$")


class BranchEndpointInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode: int
    segment_id: int = Field(ge=1)
    time: str


class BranchOptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    prompt: str

    @field_validator("text")
    @classmethod
    def validate_text_fields(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("branch option text 不能为空字符串")
        return text


class BranchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    trigger: BranchEndpointInput
    question: str
    options: list[BranchOptionInput]
    resume: BranchEndpointInput

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("branch question 不能为空字符串")
        return text

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[BranchOptionInput]) -> list[BranchOptionInput]:
        if not 2 <= len(value) <= 3:
            raise ValueError("branch options 必须包含 2 到 3 个选项")

        if not is_original_branch_option(value[0]):
            raise ValueError("branch options[0] 必须是非空 text + 空 prompt 的原剧情项")

        for option in value[1:]:
            if not option.prompt.strip():
                raise ValueError("非原剧情 branch option 的 prompt 不能为空字符串")

        return value


class BranchesInputDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branches: list[BranchInput]


class VideoPromptItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_index: int = Field(ge=0)
    option_index: int = Field(ge=0)
    prompt: str

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("video prompt 不能为空字符串")
        return text


class VideoPromptsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_prompts: list[VideoPromptItem]


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


def parse_model_output(result: str) -> VideoPromptsDocument:
    """按提示词规定的对象结构解析视频提示词结果。"""
    s = strip_markdown_code_block(result)
    if not s:
        raise ValueError("模型输出为空，无法解析 video_prompts")

    try:
        return VideoPromptsDocument.model_validate_json(s)
    except ValidationError as exc:
        raise ValueError(f"branch_video.json 校验失败: {exc}") from exc


def parse_branches_document(raw_text: str) -> BranchesInputDocument:
    """校验并解析根数组格式的 branch.json。"""
    try:
        payload = json.loads(raw_text)
        if not isinstance(payload, list):
            raise ValueError("branch.json 必须是根数组格式")
        return BranchesInputDocument.model_validate({"branches": payload})
    except json.JSONDecodeError as exc:
        raise ValueError(f"branch.json 不是合法 JSON: {exc}") from exc
    except ValidationError as exc:
        raise ValueError(f"branch.json 校验失败: {exc}") from exc
    except ValueError:
        raise


def normalize_json_value(value: Any) -> Any:
    """将 BaseModel、列表和字典递归转换为可序列化对象。"""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_json_value(item) for key, item in value.items()}
    return value


def build_json_payload(value: Any) -> str:
    """将输入压缩为注入 prompt 的紧凑 JSON。"""
    return json.dumps(
        normalize_json_value(value),
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
    lookahead_segments: list,
    branches_document: BranchesInputDocument | list[dict[str, Any]],
    text_path: str | Path,
) -> str:
    """以紧凑 JSON 格式注入 prompt。"""
    branches_payload = (
        branches_document.branches
        if isinstance(branches_document, BranchesInputDocument)
        else branches_document
    )
    return (
        USER_PROMPT_TEMPLATE.replace(
            "{{series_context}}", build_series_context_payload(text_path)
        )
        .replace(
            "{{current_episode_segments}}", build_json_payload(current_segments)
        )
        .replace(
            "{{lookahead_episode_segments}}", build_json_payload(lookahead_segments)
        )
        .replace("{{branches}}", build_json_payload(branches_payload))
    )


def is_original_branch_option(option: BranchOptionInput) -> bool:
    """判断是否为“继续原剧情”的空 prompt 选项。"""
    return bool(option.text.strip()) and not option.prompt.strip()


def collect_prompt_target_pairs(
    branches_document: BranchesInputDocument,
) -> set[tuple[int, int]]:
    """收集实际需要生成视频提示词的分支选项下标。"""
    targets: set[tuple[int, int]] = set()
    for branch_index, branch in enumerate(branches_document.branches):
        for option_index, option in enumerate(branch.options):
            if is_original_branch_option(option):
                continue
            targets.add((branch_index, option_index))
    return targets


def replace_path_part_sequence(
    path: str | Path, source_parts: tuple[str, ...], target_parts: tuple[str, ...]
) -> Path:
    """将路径中的一段连续目录名替换为新的目录名序列。"""
    source = Path(path)
    parts = list(source.parts)
    source_length = len(source_parts)

    for index in range(len(parts) - source_length + 1):
        if tuple(parts[index : index + source_length]) == source_parts:
            return Path(*parts[:index], *target_parts, *parts[index + source_length :])

    joined = "/".join(source_parts)
    raise ValueError(f"路径 {source} 不包含目录序列 {joined}")


def get_text_path_from_branch_path(branch_path: str | Path) -> Path:
    """根据 branch/json 路径推导当前集 text 路径。"""
    return replace_path_part_sequence(
        branch_path,
        ("branch", "json"),
        ("text",),
    ).with_suffix(".json")


def get_prompt_output_path(branch_path: str | Path) -> Path:
    """根据 branch/json 路径推导 prompt 输出路径。"""
    return replace_path_part_sequence(
        branch_path,
        ("branch", "json"),
        ("branch", "prompt"),
    ).with_suffix(".json")


def get_prompt_output_dir(branch_dir: str | Path) -> Path:
    """根据 branch/json 目录推导 prompt 输出目录。"""
    return replace_path_part_sequence(
        branch_dir,
        ("branch", "json"),
        ("branch", "prompt"),
    )


def extract_episode_number(path: str | Path) -> int:
    """从“第N集.json”文件名中提取集数。"""
    stem = Path(path).stem
    match = EPISODE_PATTERN.fullmatch(stem)
    if match is None:
        raise ValueError(f"无法从文件名提取集数: {path}")
    return int(match.group(1))


def find_next_episode_text_path(text_path: str | Path) -> Path | None:
    """查找当前集的下一集字幕文件。"""
    current_path = Path(text_path)
    next_path = current_path.with_name(
        f"第{extract_episode_number(current_path) + 1}集.json"
    )
    if next_path.exists():
        return next_path
    return None


async def generate_video_prompts(user_prompt: str) -> VideoPromptsDocument:
    """调用模型生成视频提示词，并对输出做结构校验。"""
    settings = get_settings()
    client = get_async_openai_client()

    last_exception: Exception | None = None
    for _ in range(MAX_ATTEMPTS):
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
            result = completion.choices[0].message.content or '{"video_prompts":[]}'
            return parse_model_output(result)
        except Exception as exc:
            last_exception = exc

    if last_exception is not None:
        raise last_exception
    raise ValueError(f"重试 {MAX_ATTEMPTS} 次后仍未生成有效视频提示词")


async def branch_to_video_prompts(branch_path: str) -> list[dict[str, Any]]:
    """将单个 branch.json 转成最终落盘用的视频提示词数组。"""
    branch_file = Path(branch_path)
    branches_document = parse_branches_document(branch_file.read_text(encoding="utf-8"))
    if not branches_document.branches:
        return []

    prompt_target_pairs = collect_prompt_target_pairs(branches_document)
    if not prompt_target_pairs:
        return []

    current_text_path = get_text_path_from_branch_path(branch_file)
    if not current_text_path.is_file():
        raise FileNotFoundError(f"当前集字幕文件不存在: {current_text_path}")

    next_text_path = find_next_episode_text_path(current_text_path)
    if next_text_path is None:
        raise FileNotFoundError(f"下一集字幕文件不存在: {current_text_path}")

    current_segments = parse_segments_list(current_text_path.read_text(encoding="utf-8"))
    next_segments = parse_segments_list(next_text_path.read_text(encoding="utf-8"))
    user_prompt = build_user_prompt(
        current_segments=current_segments,
        lookahead_segments=next_segments,
        branches_document=branches_document,
        text_path=current_text_path,
    )
    final_document = await generate_video_prompts(user_prompt)
    return [
        item.model_dump(mode="json")
        for item in final_document.video_prompts
        if (item.branch_index, item.option_index) in prompt_target_pairs
    ]


async def branch_file_to_prompt_file(branch_path: str, prompt_path: str) -> None:
    """将单个 branch.json 转成视频提示词并写入 prompt 文件。"""
    result = await branch_to_video_prompts(branch_path)
    write_json_document(prompt_path, result)


async def batch_convert(branch_files: list[str], prompt_files: list[str]) -> None:
    """批量生成分支视频提示词文件。"""
    success_count = 0
    fail_count = 0

    async def _run(branch_path, prompt_path):
        async with API_SEMAPHORE:
            return await branch_file_to_prompt_file(branch_path, prompt_path)

    tasks = [
        _run(branch_path, prompt_path)
        for branch_path, prompt_path in zip(branch_files, prompt_files)
    ]
    for task in tqdm_asyncio.as_completed(
        tasks,
        total=len(tasks),
        desc="分支转视频提示词",
    ):
        try:
            await task
            success_count += 1
        except Exception:
            fail_count += 1

    tqdm.write(f"完成: 成功 {success_count}，失败 {fail_count}")


def batch_convert_dir(branch_dir: str | Path, prompt_dir: str | Path) -> None:
    """批量转换目录下所有 branch JSON 文件。"""
    branch_dir = Path(branch_dir)
    prompt_dir = Path(prompt_dir)
    candidates = sorted(branch_dir.rglob("*.json"))
    branch_files: list[str] = []
    prompt_files: list[str] = []

    for branch_path in tqdm(candidates, desc="扫描分支文件"):
        rel_path = branch_path.relative_to(branch_dir)
        prompt_path = prompt_dir / rel_path
        if prompt_path.exists():
            continue
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        branch_files.append(str(branch_path))
        prompt_files.append(str(prompt_path))

    asyncio.run(batch_convert(branch_files, prompt_files))


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


def run_single_branch_file(branch_path: str | Path) -> None:
    """执行单个 branch 文件的转换并写入 prompt 文件。"""
    source_path = str(branch_path)
    output_path = str(get_prompt_output_path(branch_path))
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
        result = asyncio.run(branch_to_video_prompts(source_path))
        write_json_document(output_path, result)
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="剧情分支转视频提示词工具")
    parser.add_argument(
        "--branch-path",
        type=str,
        dest="branch_path",
        help="branch JSON 文件或目录路径。传文件输出单个结果，传目录递归聚合输出，不传则读取 data/branch/json",
    )
    args = parser.parse_args()

    branch_path = (
        Path(args.branch_path) if args.branch_path else DATA_DIR / "branch" / "json"
    )
    if branch_path.is_file():
        run_single_branch_file(branch_path)
    elif branch_path.is_dir():
        batch_convert_dir(branch_path, get_prompt_output_dir(branch_path))
    else:
        raise FileNotFoundError(f"路径不存在: {branch_path}")
