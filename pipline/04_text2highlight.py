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
    write_json_document,
)

SETTINGS = get_settings()

MAX_ATTEMPTS = 5

SYSTEM_PROMPT = """
# 角色
你是一名短剧剧情刺激点打标助手。你的任务是根据音频语义片段 JSON，识别适合后续互动处理的剧情刺激点。

剧情刺激点指观众看到后可能立刻产生反应的最小剧情单元，例如惊讶、爽感、吐槽、紧张、好笑、疑惑、感动、期待反转等。

你只做内容层面的刺激点打标：判断哪里值得标记、为什么值得标记、依据来自哪些原始 segment。不要生成互动组件、按钮文案、投票选项、展示时长或前端配置。

# 输入边界
每次任务会提供 drama_context 和 segments。

drama_context 包含剧名、简介和角色名，只用于辅助理解背景、专有名词、人物称呼和核心设定，不是直接刺激点证据。

segments 是唯一打标证据。所有 highlight 必须由 segments 中实际出现的台词、人声状态、情绪、语气、音乐、音效或声音线索支撑。不要根据 drama_context 生成 segments 中没有体现的刺激点。

# 打标原则
1. 刺激点是可独立互动的剧情刺激单元，不是完整剧情摘要。
2. 一个 highlight 应围绕一个核心刺激点；多个强刺激点必须拆开。
3. 普通寒暄、普通过渡、普通背景交代、普通解释说明，不标为刺激点。
4. 介绍人物、身份、背景或设定的片段，只有在本身包含强信息、强反差、悬念、冲突或戏剧张力时，才标为刺激点。
5. 如果内容是“铺垫 → 爆点 → 后续反应”，优先标记爆点；铺垫和后续反应只有在理解爆点必需时才放入同一个 highlight。
6. 如果多个相邻片段只是共同完成一个轻量冲突、轻量笑点或同一情绪反应，可以合并为一个 highlight，不要拆得过碎。
7. 如果一个桥段同时包含多个强笑点、反转、危险事件、身份揭露、情绪爆发或重要决定，应拆成多个 highlight。
8. 重复表达同一刺激点的片段，不要重复标注。
9. highlights 按剧情时间顺序输出。

# 颗粒度把握
1. 强台词、核心身份揭露、危险事件、强反差笑点、强势反击，通常可以单独成为 highlight。
2. 铺垫、解释、补充说明、路人反应，只有在它本身有明显互动价值时才单独成为 highlight。
3. 解释性旁白通常不单独标为刺激点；除非它直接揭示核心身份、重大真相或强反转。
4. 相邻弱刺激点如果都服务于同一个小冲突或同一个笑点，可以合并。
5. 不要为了凑数量标注普通片段；也不要为了剧情完整把多个独立刺激点合成一条。

# 证据规则
1. evidence.segment_ids 只放直接支撑当前刺激点的 segment，可以不连续，但必须按升序排列。
2. 如果核心刺激点单独成立，优先只保留触发点所在 segment。
3. 不要为了剧情完整，把不直接支撑当前刺激点的 segment 放进 evidence。
4. label、summary、reason、signals 中提到的信息，必须能在 evidence.segment_ids 对应的 segments 中找到依据。
5. evidence.dialogues 必须摘录自对应 segments，保留原始写法。

# 错词与关系规则
如果 segments 中出现明显错误的人名、家族名、称谓或人物关系，而 drama_context、segments 上下文和相近发音共同支持更合理写法，可以在 label、summary、reason、signals 中使用纠正后的写法。

纠错只用于高置信情况。不要强行纠正，不要改写剧情，不要引入 segments 中没有出现的事件或人物关系。evidence.dialogues 必须保留 segments 原始台词。

优先使用 segments 中明确出现的称呼、关系或专名。人物关系只有在 segments 上下文和 drama_context 共同强支持时才使用；不确定时优先使用事件化 label。不要使用“男主”“女主”“反派”等缺乏证据的身份判断。

涉及“谁陪谁”“谁送谁”“谁称呼谁”“谁是谁的亲属”“谁让谁做什么”时，必须严格依据 evidence.dialogues。关系复杂或指代不确定时，使用保守概括，避免把主客体写反。

# level 定义
level 表示刺激点强度和后续处理优先级，不是概率，不是置信度。

1 = 轻微刺激点：有一定趣味、信息或情绪，但刺激较弱。
2 = 明显刺激点：有明确冲突、笑点、身份信息、情绪变化、剧情推进、悬念或反差。
3 = 强刺激点：重大反转、核心身份揭露、强势反击、危险事故、强情绪爆发、强反差笑点或名场面。

level 3 要严格使用。不能因为有信息量、身份介绍、气氛热闹、人物出场、荣誉介绍或普通解释就标为 3。

普通信息介绍通常最多 level 2。解释性旁白通常最多 level 1 或 level 2。单句强台词、重大身份揭露、危险事件、强反差笑点可以 level 3。如果不确定 level 2 还是 level 3，优先选择 level 2。

# 输出要求
只输出合法 JSON 对象。根对象必须且只能包含 highlights 字段。如果没有合适刺激点，输出 {"highlights":[]}。不要新增 schema 之外的字段。不要输出 Markdown、解释、代码块或多余文字。

输出结构：
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

# 字段要求
- id：从 1 开始，按时间顺序递增。
- label：简短概括当前刺激点的核心刺激点，建议 8 到 18 个中文字符。
- level：只能是 1、2、3。
- summary：简短说明这段发生了什么；涉及人物关系、称谓和动作方向时，必须严格依据 evidence.dialogues。
- reason：简短说明为什么值得作为刺激点，重点说明冲突、反差、信息冲击、情绪变化、危险感或笑点。
- evidence.segment_ids：支撑该刺激点的原始 segment id，必须非空，按升序排列。
- evidence.dialogues：摘录关键台词，必须来自对应 segments，保留原始写法。
- evidence.signals：短证据点，例如“强势宣言”“身份揭露”“嘲讽挑衅”“多人惊呼”“音乐突然增强”“强身份反差”“爆炸声”。
"""

USER_PROMPT = """
<drama_context>
{{DRAMA_CONTEXT_JSON_MINIFIED}}
</drama_context>

<segments>
{{SEGMENTS_JSON_MINIFIED}}
</segments>

请根据 segments 识别剧情刺激点点，并严格按照 system prompt 指定的 JSON 格式输出。
"""

TOOLONG_REMINDER_PROMPT = "\n上一次输出存在跨度过长片段，请把长片段拆成更小的最小可互动剧情刺激单元。"
LEVEL3_REMINDER_PROMPT = "\n上一次输出 level 3 占比过高，请严格按标准区分 level，只有重大反转、核心身份揭露、强情绪爆发等才标 level 3。"

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
    """按提示词规定的对象结构解析刺激点，并返回其中的数组。"""
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


async def text_to_highlight(text_path: str, highlight_path: str):

    def parse_ts(ts: str) -> float:
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    def has_overspan_highlight(parsed: list) -> bool:
        for item in parsed:
            duration = parse_ts(item.end) - parse_ts(item.start)
            if duration > 15:
                return True
        return False

    def has_too_many_level3(parsed: list) -> bool:
        if len(parsed) < 6:
            return False
        level3_count = sum(1 for item in parsed if item.level == 3)
        return level3_count / len(parsed) > 0.5

    raw_text = Path(text_path).read_text(encoding="utf-8")
    segments = parse_segments_list(raw_text)
    user_prompt = build_user_prompt(segments, text_path)

    last_exception: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            completion = await client.chat.completions.create(
                model=SETTINGS.llm_model_id,
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
                temperature=0.1
            )

            result = completion.choices[0].message.content or "[]"
            parsed = parse_highlights(result, segments)

            reason = None
            if has_overspan_highlight(parsed):
                reason = "跨度过长"
                if TOOLONG_REMINDER_PROMPT not in user_prompt:
                    user_prompt += TOOLONG_REMINDER_PROMPT
            if has_too_many_level3(parsed):
                reason = "level 3 占比过高" if reason is None else f"{reason}、level 3 占比过高"
                if LEVEL3_REMINDER_PROMPT not in user_prompt:
                    user_prompt += LEVEL3_REMINDER_PROMPT

            if reason and attempt < MAX_ATTEMPTS:
                tqdm.write(
                    f"[retrying] 第 {attempt} 次输出存在{reason}，"
                    f"剩余 {MAX_ATTEMPTS - attempt} 次"
                )
                continue

            write_json_document(highlight_path, parsed)
            return
        except Exception as exc:
            last_exception = exc
            if attempt < MAX_ATTEMPTS:
                tqdm.write(
                    f"[retrying] 第 {attempt} 次失败，"
                    f"剩余 {MAX_ATTEMPTS - attempt} 次: {str(exc).splitlines()[0]}"
                )

    if last_exception is not None:
        raise last_exception
    raise ValueError(f"重试 {MAX_ATTEMPTS} 次后仍存在跨度过长的刺激点")


async def batch_convert(text_files: list[str], highlight_files: list[str]):
    """批量生成刺激点。"""
    success_count = 0
    fail_count = 0
    tasks = [text_to_highlight(t, h) for t, h in zip(text_files, highlight_files)]
    for task in tqdm_asyncio.as_completed(tasks, total=len(tasks), desc="文本转刺激点"):
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
    """根据文本路径推导刺激点路径（text -> highlight，后缀仍为 .json）。"""
    return map_output_file(
        text_path,
        source_dir_name="text",
        target_dir_name="highlight",
        target_suffix=".json",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="文本转剧情刺激点工具（异步批量转换）")
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
