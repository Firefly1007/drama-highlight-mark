import argparse
import asyncio
import json
import re
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio

from pipline.common.config import get_async_openai_client, get_settings
from pipline.common.paths import DATA_DIR, map_output_dir, map_output_file
from pipline.common.runtime import (
    DRAMA_INFO_PATH,
    EpisodeStatus,
    load_drama_info,
    get_drama_name_from_path,
    parse_highlights_document,
    parse_segments_list,
    print_episode_status,
    with_retry,
    write_json_document,
)

SETTINGS = get_settings()

SYSTEM_PROMPT = """
你是一名短剧剧情高光打标助手。

你的任务是根据用户提供的音频语义片段 JSON，标出短剧中适合后续互动处理的“剧情刺激点”。

剧情刺激点指：观众在观看过程中可能产生即时反应的内容节点，例如惊讶、爽感、吐槽、紧张、好笑、疑惑、感动、期待反转等。

你只做内容层面的高光打标：
- 判断哪里值得标记
- 说明为什么值得标记
- 给出依据来自哪些原始片段

不要生成前端互动组件、按钮文案、投票选项、展示时长或用户互动方案。

剧集参考信息使用规则：

1. 每次任务会提供当前短剧的 drama_context，包括剧名、简介和角色名。
2. drama_context 只用于辅助理解剧情背景、人物称呼、专有名词和核心设定，不作为直接高光证据。
3. 高光判断必须以 segments 中实际出现的台词、人声状态、情绪、语气、音乐、音效和声音线索为依据。
4. 如果 drama_context 中提到某个设定、人物或事件，但当前 segments 没有体现，不要据此生成 highlight。
5. summary 和 reason 必须围绕 segments 中实际出现的信息展开，不要把简介内容当作当前片段内容复述。
6. evidence.dialogues 和 evidence.signals 只能来自 segments，不能来自 drama_context。

判断原则：

1. 以 segments 为唯一打标证据，不补写 segments 中没有的剧情、台词、人物关系或声音事件。
2. 一个 highlight 应围绕一个可以独立触发观众反应的核心刺激点。
3. 不要把一整段剧情总结成一个 highlight；如果一段剧情里有多个独立刺激点，应拆成多个 highlight。
4. 普通寒暄、过渡、背景交代、无明显情绪或信息变化的片段，不应标为高光。
5. 介绍性片段只有在包含强身份信息、强反差、悬念、情绪刺激或戏剧张力时，才可以标为高光。
6. 每个 highlight 的 evidence 只放支撑当前刺激点的片段，不要把前后相邻但不直接支撑本高光的台词或声音信号带入。
7. highlights 按时间顺序输出。

称呼与人物关系原则：

1. 优先使用 segments 中明确出现的称呼，例如“太奶奶”“妈妈”“爷爷”“老三”。
2. 如果人物关系或身份能被 segments 中的台词、上下文和语义标注明确支持，可以使用，例如“季家少爷”“晚辈”“爷爷”。
3. drama_context 可以帮助理解称呼和专名，但不能单独作为人物关系判断依据。
4. 不要使用缺乏 segments 支撑的人物身份判断，例如“男主”“女主”“反派”等。
5. 如果只是根据剧情常识、简介或想象推测出来的身份，不要写入 label、summary、reason 或 evidence.signals。
6. label 应尽量围绕事件本身表达；当人物关系本身就是高光刺激点时，可以保留人物关系。
7. 如果人物关系表达会让 label 变得冗长，优先改写成事件化表达，例如“太奶奶身份反差”“我在哪季家就在哪宣言”“穿越身份揭露”“装病不想上学笑点”。

level 表示高光强度与后续处理优先级，不是概率，也不是模型置信度：

1 = 轻微高光：有一定趣味、信息或情绪，但剧情张力较弱。
2 = 明显高光：有明确冲突、笑点、身份信息、情绪变化、剧情推进或反差。
3 = 强高光：重大反转、核心身份揭露、强势反击、危险事故、强情绪爆发、强反差笑点或名场面。

level 使用原则：

- 普通信息介绍即使有信息量，通常最多为 level 2。
- 单句强台词、重大身份揭露、危险事件、强反差笑点，可以为 level 3。
- 如果一个片段只是补充解释前面的高光，而没有新的刺激点，通常为 level 1 或 level 2。
- 不要输出小数分数，不要输出 score。

片段选择原则：

1. evidence.segment_ids 只包含直接支撑当前高光的原始片段。
2. segment_ids 可以不连续，不要为了连续性强行加入无关片段。
3. 一个 highlight 通常覆盖 1 到 5 个 segments。
4. 如果一个高光需要很多 segments 才能说明，优先检查是否包含多个刺激点，并拆分。
5. 不要为了让剧情更完整而扩大 evidence.segment_ids；只保留理解当前刺激点必要的片段。

输出必须是合法 JSON 对象，根对象只能包含 highlights 字段。

如果没有合适高光，输出：

{"highlights":[]}

输出结构如下：

{
  "highlights": [
    {
      "id": 1,
      "label": "",
      "level": 1,
      "summary": "",
      "reason": "",
      "evidence": {
        "segment_ids": [],
        "dialogues": [],
        "signals": []
      }
    }
  ]
}

字段说明：

- id：高光编号，从 1 开始，按时间顺序递增。
- label：简短自然语言标签，概括当前高光的核心刺激点。优先使用事件、关键台词、反差信息，或 segments 中有明确依据的人物称呼。建议控制在 8 到 18 个中文字符。
- level：只能是 1、2、3。
- summary：简短说明这段发生了什么，不要写成长篇剧情复述。
- reason：简短说明为什么这段值得作为高光，重点说明戏剧张力、信息冲击、情绪变化或反差点。
- evidence.segment_ids：支撑该高光的原始 segment id，按升序排列。
- evidence.dialogues：只摘录支撑当前高光的关键台词；每一句必须来自 evidence.segment_ids 对应的原始 segments；如果高光主要由音乐、音效或沉默构成，可以为空数组。
- evidence.signals：只写支撑当前高光的短证据点，例如“强势宣言”“身份揭露”“嘲讽挑衅”“多人惊呼”“音乐突然增强”“语气急促”“强身份反差”等。

一致性要求：

- evidence.dialogues 必须来自 evidence.segment_ids 对应的原始 segments。
- evidence.signals 必须能从对应 segments 的 text、speech、emotion、voice、music 或 audio_cues 中找到依据。
- evidence.signals 可以包含由原始台词、segments 上下文和输入语义标注明确支持的短证据点，例如“太奶奶称呼”“季家少爷身份”“晚辈解释”“强身份反差”。
- 不要在 evidence.signals 中新增 segments 里没有依据的音效、情绪、人物关系或剧情信息。
- 每个 highlight 只能包含 schema 中列出的字段，不要新增任何字段。
- 不要输出 Markdown、解释、代码块或多余文字。
"""

USER_PROMPT = """
下面是当前短剧的参考信息。它只用于背景理解和专有名词参考，不是直接高光证据。

<drama_context>
{{DRAMA_CONTEXT_JSON_MINIFIED}}
</drama_context>

下面是本集音频语义片段 JSON。它是高光打标的主要依据，是只读输入，不要修改，不要补全。

<segments_json>
{{SEGMENTS_JSON_MINIFIED}}
</segments_json>

请根据 segments 识别剧情高光点，并严格按照 system prompt 指定的 JSON 格式输出。
"""


client = get_async_openai_client()


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


def parse_highlights(result: str, segments: list | None = None) -> list:
    """按提示词规定的对象结构解析高光，并返回其中的数组。"""
    s = strip_markdown_code_block(result)

    if not s:
        raise ValueError("模型输出为空，放弃全部输出")

    try:
        return parse_highlights_document(s, segments)
    except ValueError:
        raise


def build_user_prompt(segments: list, text_path: str | Path) -> str:
    """以紧凑 JSON 格式注入 user prompt，包含短剧参考信息和 segments 数据。"""
    drama_info = load_drama_info()
    drama_name = get_drama_name_from_path(text_path)
    drama = drama_info.get(drama_name)
    if drama is None:
        raise ValueError(
            f"找不到短剧 '{drama_name}' 的参考信息，请检查 {DRAMA_INFO_PATH}"
        )
    drama_json = json.dumps(
        drama.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
    segments_json_minified = json.dumps(
        [segment.model_dump(mode="json") for segment in segments],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return USER_PROMPT.replace(
        "{{DRAMA_CONTEXT_JSON_MINIFIED}}", drama_json
    ).replace(
        "{{SEGMENTS_JSON_MINIFIED}}", segments_json_minified
    )


@with_retry()
async def text_to_highlight(text_path: str, highlight_path: str):
    """将文本语义 JSON 发送给模型，获取剧情高光结果（异步）。"""
    try:
        raw_text = Path(text_path).read_text(encoding="utf-8")
        segments = parse_segments_list(raw_text)

        completion = await client.chat.completions.create(
            model=SETTINGS.llm_model_id,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": build_user_prompt(segments, text_path),
                },
            ],
            temperature=0.1
        )

        result = completion.choices[0].message.content or "[]"
        parsed = parse_highlights(result, segments)
        write_json_document(highlight_path, parsed)
    except Exception:
        raise


async def batch_convert(text_files: list[str], highlight_files: list[str]):
    """批量生成高光。"""
    success_count = 0
    fail_count = 0
    tasks = [text_to_highlight(t, h) for t, h in zip(text_files, highlight_files)]
    for task in tqdm_asyncio.as_completed(tasks, total=len(tasks), desc="文本转高光"):
        try:
            await task
            success_count += 1
        except Exception:
            fail_count += 1
    tqdm.write(f"完成: 成功 {success_count}，失败 {fail_count}")


def batch_convert_dir(text_dir: str | Path, highlight_dir: str | Path):
    """批量转换目录下所有文本 JSON 文件。"""
    text_dir = Path(text_dir)
    highlight_dir = Path(highlight_dir)
    candidates = list(text_dir.rglob("*.json"))
    text_files = []
    highlight_files = []
    for text_path in tqdm(candidates, desc="扫描文本文件"):
        rel_path = text_path.relative_to(text_dir)
        highlight_path = highlight_dir / rel_path
        if highlight_path.exists():
            continue
        text_files.append(str(text_path))
        highlight_files.append(str(highlight_path))
        highlight_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(batch_convert(text_files, highlight_files))


def get_highlight_path(text_path: str | Path) -> Path:
    """根据文本路径推导高光路径（text -> highlight，后缀仍为 .json）。"""
    return map_output_file(
        text_path,
        source_dir_name="text",
        target_dir_name="highlight",
        target_suffix=".json",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="文本转剧情高光工具（异步批量转换）")
    parser.add_argument(
        "--text-path",
        type=str,
        dest="text_path",
        help="文本 JSON 文件或目录路径。传文件转单个，传目录递归转换，不传则转换 data/text 下所有文件",
    )
    args = parser.parse_args()

    if args.text_path:
        text_path = Path(args.text_path)
        if text_path.is_file():
            highlight_path = get_highlight_path(text_path)
            if highlight_path.exists():
                tqdm.write(f"输出文件已存在，跳过: {highlight_path}")
            else:
                print_episode_status(
                    status=EpisodeStatus.PENDING,
                    source_path=str(text_path),
                    output_path=str(highlight_path),
                )
                highlight_path.parent.mkdir(parents=True, exist_ok=True)
                print_episode_status(
                    status=EpisodeStatus.RUNNING,
                    source_path=str(text_path),
                    output_path=str(highlight_path),
                )
                try:
                    asyncio.run(text_to_highlight(str(text_path), str(highlight_path)))
                    print_episode_status(
                        status=EpisodeStatus.SUCCESS,
                        source_path=str(text_path),
                        output_path=str(highlight_path),
                    )
                except Exception as exc:
                    print_episode_status(
                        status=EpisodeStatus.FAILED,
                        source_path=str(text_path),
                        output_path=str(highlight_path),
                        error=str(exc),
                    )
                    raise
        elif text_path.is_dir():
            highlight_dir = map_output_dir(
                text_path,
                source_dir_name="text",
                target_dir_name="highlight",
            )
            batch_convert_dir(text_path, highlight_dir)
        else:
            raise FileNotFoundError(f"路径不存在: {text_path}")
    else:
        batch_convert_dir(DATA_DIR / "text", DATA_DIR / "highlight")
