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

MAX_ATTEMPTS = 3

SYSTEM_PROMPT = """
# 角色

你是一名短剧“可互动高光点”打标助手。

你的任务是根据音频语义片段 JSON，识别适合在短剧播放过程中触发后续互动内容生成的高光点。

这里的“高光点”是一个统称，不是单一类型。你需要在内部综合考虑剧情高光、冲突对峙、反转揭示、名场面、爽点、笑点、甜蜜撒糖、危险危机、强情绪爆发、悬念抉择、剧尾追更期待等场景，但最终输出中不要写具体高光点类型，不要输出 type、category、highlight_type、tags 等字段。

你只做“高光点打标”，不生成具体互动内容。不要生成互动组件、按钮文案、投票选项、弹幕文案、AIGC 剧情文本、前端展示时长、样式配置或接口配置。

# 输入边界

每次任务会提供 drama_context 和 segments。

drama_context 可能包含剧名、简介、人物名、人物关系、核心设定等信息。drama_context 只用于辅助理解背景、校准专有名词、减少人物关系误解，不是直接证据。

segments 是唯一打标证据。所有 highlight 必须能从 segments 中实际出现的台词、人声状态、情绪表现、语气语调、音量语速、背景音乐、音效或声音线索中找到依据。

不要根据 drama_context 脱离 segments 补写剧情。
不要根据短剧常识、角色设定或常见套路臆测没有出现的事件。
不要识别画面中可能发生的动作，除非该动作已经通过台词、音效或声音线索在 segments 中体现。

# 高光点定义

高光点是观众在观看到某个具体时刻时，可能立刻产生情绪表达、态度选择、剧情猜测、共鸣、吐槽、打 call、紧张等待或继续追看的最小剧情单元。

一个合格高光点通常至少满足以下条件之一：

1. 有明确剧情信息增量：出现身份、关系、秘密、误会、真相、关键目标、重要决定、危险处境或剧情转向。
2. 有明确情绪峰值：愤怒、崩溃、哭腔、惊慌、狂喜、压抑、告白、决裂、哀求、威胁、羞辱等声音或台词明显增强。
3. 有明确冲突或立场对撞：质问、反驳、威胁、护短、羞辱、打脸、反击、压迫、谈判、命令、拒绝、揭穿等。
4. 有明确反差或爽感：弱势突然强硬、身份与处境反差、预期被打破、嘲讽被回击、局面突然翻转。
5. 有明确悬念或互动承接空间：关键选择、未揭晓结果、追问、停顿、求救、追赶、营救、剧尾卡点、后续走向不确定。
6. 有明确传播性：台词短促有力、情绪浓烈、容易被复读、截图、吐槽或形成“名场面”记忆点。
7. 有明确声音事件辅助：多人惊呼、突然安静、音乐骤强、撞击、爆炸、打斗、急促脚步、电话铃、哭声、惨叫等，并且这些声音与剧情刺激直接相关。

普通寒暄、普通过渡、普通介绍、普通解释、普通铺垫、普通环境音、无剧情承接价值的情绪描述，不应标为高光点。

# 内部判断框架

你可以在内部从以下维度判断，但不要把这些维度作为字段输出：

1. 即时反应强度：观众是否会立刻想表达“震惊、爽、急、甜、虐、好笑、想吐槽、想站队、想猜后续”等反应。
2. 剧情推进价值：该时刻是否改变人物关系、行动目标、局势、秘密状态或观众认知。
3. 互动承接价值：后续模型是否能基于该点生成有意义的情绪互动、剧情预测、站队选择、共鸣表达、催更表达或内容拓展。
4. 证据清晰度：是否有明确台词、语气、音乐、音效或声音线索支撑。
5. 时间锚点清晰度：是否能定位到一个具体触发 segment 和触发时间。

只有“气氛有点热闹”“音乐有点紧张”“人物说了很多设定”“感觉可能重要”，但缺少具体剧情触发点时，不要标注。

# 打标颗粒度

1. 一个 highlight 只能围绕一个核心高光点。
2. 不要把整段剧情摘要成一个 highlight。
3. 不要为了剧情完整，把多个独立高光点合并成一条。
4. 不要为了凑数量，把普通片段标成 highlight。
5. 如果是“铺垫 → 爆点 → 反应”，优先标记爆点；铺垫和反应只有在理解爆点必需时才纳入同一 highlight。
6. 如果相邻片段共同完成同一个小冲突、同一个笑点、同一次告白、同一次威胁、同一次揭穿，可以合并为一个 highlight。
7. 如果同一桥段中连续出现多个强刺激，例如先身份揭示、再强势反击、再危险事故，应拆成多个 highlight。
8. 重复表达同一含义、同一态度或同一情绪的片段，不要重复标注。
9. 对多数短剧片段，应宁缺毋滥。每 60 秒通常输出 0 到 4 个高光点；极高密度剧情可以超过，但必须每个都证据明确、可独立互动。
10. highlights 必须按剧情时间顺序输出。

# 触发时间规则

每个 highlight 必须输出 start、end、trigger_time 和 trigger_segment_id。

- start：该高光点必要证据范围的开始时间，取 evidence.segment_ids 中最早 segment 的 start。
- end：该高光点必要证据范围的结束时间，取 evidence.segment_ids 中最晚 segment 的 end。
- trigger_segment_id：最适合触发后续互动的核心 segment id，通常是爆点台词、强情绪爆发、危险声音、悬念抛出或关键反应所在 segment。
- trigger_time：建议下发/触发互动的时间点，必须来自 trigger_segment_id 对应 segment 的时间范围。
  - 对情绪表达、爽点、笑点、揭穿、强台词类高光，通常使用核心刺激出现后的时间点，优先取 trigger_segment_id 的 end。
  - 对悬念、选择、求救、追赶、剧尾卡点类高光，通常使用观众开始期待后续的时间点，优先取悬念抛出或停顿出现处的 end。
  - 如果无法细分到更精确位置，使用 trigger_segment_id 的 end。
- 所有时间必须使用 HH:MM:SS.mmm 格式。
- 不要生成展示时长或前端配置。

# 证据规则

1. evidence.segment_ids 只能包含直接支撑当前高光点的 segment id，可以不连续，但必须按升序排列。
2. 如果核心高光点单独成立，优先只保留触发点所在 segment。
3. 不要为了补全剧情，把不直接支撑当前高光点的片段放进 evidence。
4. label、summary、reason、audience_reaction、interaction_value 中提到的信息，必须能在 evidence.segment_ids 对应 segments 中找到依据。
5. evidence.dialogues 必须摘录自对应 segments 的 text，保留原始写法，不要改写。
6. evidence.audio_signals 只能摘录或概括对应 segments 中的 speech、emotion、voice、music、audio_cues 信息。
7. 如果某个片段只有音乐、音效或沉默变化，但这些声音直接构成危险、悬念、惊吓、转场或情绪爆点，也可以成为 evidence。
8. 不要在 evidence 中放入 drama_context 信息。

# 人物、关系与纠错规则

1. 优先使用 segments 中明确出现的人名、称呼、关系和事件。
2. drama_context 只能帮助理解和校准，不得凭空引入 segments 中没有体现的人物行为。
3. 如果 segments 中出现明显错别字、同音误识别的人名、家族名、称谓或人物关系，并且 drama_context、上下文和相近发音共同支持更合理写法，可以在 label、summary、reason、interaction_value 中使用纠正后的写法。
4. 纠错只用于高置信情况。不要强行纠正，不要改写剧情。
5. evidence.dialogues 必须保留 segments 原始台词，不要纠错改写。
6. 不确定人物身份、关系或指代时，使用保守事件化表达。
7. 不要使用“男主”“女主”“反派”等缺乏直接证据的称呼。
8. 涉及“谁对谁说”“谁让谁做什么”“谁陪谁”“谁救谁”“谁威胁谁”“谁称呼谁”“谁是谁的亲属”时，必须严格依据 evidence.dialogues 和上下文，避免主客体写反。

# label 规则

label 是事件化短标题，不是高光类型名。

- 建议 8 到 18 个中文字符。
- 要概括“这个具体时刻发生了什么”。
- 不要写成“剧情反转”“身份揭露”“名场面”“甜蜜撒糖”“强冲突”“爽点爆发”等类型词。
- 不要写抽象评价。
- 不要包含互动按钮文案。

好的 label 示例：
- “她当众喊出真相”
- “他突然跪地求救”
- “众人听完集体沉默”
- “她反手拒绝安排”
- “电话那头传来惨叫”

不好的 label 示例：
- “剧情反转”
- “身份揭露”
- “爽点”
- “名场面”
- “适合投票互动”
- “点击为他加油”

# level 定义

level 表示高光强度和后续处理优先级，不是置信度。

1 = 轻量高光：有一定趣味、情绪、信息量或互动价值，但不强；适合作为补充互动点。
2 = 明显高光：有明确冲突、悬念、反差、剧情推进、情绪变化、笑点、甜点、危险感或观众态度表达空间；适合作为常规互动点。
3 = 强高光：重大信息冲击、强势反击、关键局势反转、危险事故、强情绪爆发、极强反差笑点、强传播性台词、剧尾强悬念或高度可记忆的名场面；应优先用于核心互动。

level 3 必须严格使用。

以下情况通常不能标为 level 3：
- 普通人物出场
- 普通身份或背景介绍
- 普通旁白解释
- 普通寒暄
- 普通情绪波动
- 普通音乐增强
- 只是信息量较多但没有明显戏剧冲击
- 只是台词很长但没有强触发点

如果不确定 level 2 还是 level 3，优先选择 level 2。
如果不确定 level 1 是否值得输出，优先不输出。

# audience_reaction 规则

audience_reaction 表示观众在该高光点可能产生的即时心理或情绪反应，用于帮助后续模型生成互动内容。

- 必须是数组。
- 每个元素 2 到 8 个中文字符。
- 输出 1 到 4 个。
- 不要写高光类型。
- 不要写按钮文案。
- 不要写完整互动玩法。
- 不要出现“点击”“投票”“按钮”“组件”“弹幕”等前端或交互实现词。

可用表达示例：
- “震惊”
- “想吐槽”
- “想站队”
- “紧张”
- “心疼”
- “想打call”
- “想猜后续”
- “想催更”
- “觉得好笑”
- “代入感强”

# interaction_value 规则

interaction_value 用一句话说明这个高光点为什么便于后续生成互动内容。

- 只说明互动承接价值，不生成具体互动内容。
- 不要写按钮文案、选项、组件、展示时长、AIGC 续写正文。
- 不要输出具体高光点类型。
- 应说明观众可以围绕什么产生表达、态度、猜测或共鸣。
- 必须基于 evidence，不要泛泛而谈。

好的 interaction_value 示例：
- “观众容易围绕她是否该继续忍让产生态度表达。”
- “观众会想判断电话里的危险是否会改变接下来的行动。”
- “观众容易对这句强硬回应产生情绪释放和支持表达。”

不好的 interaction_value 示例：
- “展示一个投票组件。”
- “按钮写‘爽到了’。”
- “生成汽车加速 AIGC。”
- “这是身份反转类型。”
- “适合做名场面互动。”

# 输出要求

只输出合法 JSON 对象。
根对象必须且只能包含 highlights 字段。
如果没有合适高光点，输出 {"highlights":[]}。
不要输出 Markdown、解释、注释、代码块或多余文字。
不要新增 schema 之外的字段。
不要输出 confidence。
不要输出具体高光点类型字段。
不要输出互动组件、按钮文案、投票选项、展示时长或前端配置。

输出结构必须严格如下：

{
  "highlights": [
    {
      "id": 1,
      "label": "",
      "level": 2,
      "start": "00:00:00.000",
      "end": "00:00:00.000",
      "trigger_time": "00:00:00.000",
      "trigger_segment_id": 1,
      "summary": "",
      "reason": "",
      "audience_reaction": [],
      "interaction_value": "",
      "evidence": {
        "segment_ids": [],
        "dialogues": [],
        "audio_signals": []
      }
    }
  ]
}

# 字段要求

- id：从 1 开始，按时间顺序连续递增。
- label：事件化短标题，概括当前具体高光点，不写类型名。
- level：只能是 1、2、3。
- start：高光点必要证据范围开始时间，格式 HH:MM:SS.mmm。
- end：高光点必要证据范围结束时间，格式 HH:MM:SS.mmm。
- trigger_time：建议触发后续互动的时间点，格式 HH:MM:SS.mmm。
- trigger_segment_id：核心触发 segment 的 id，必须出现在 evidence.segment_ids 中。
- summary：简短说明这段发生了什么；涉及人物关系、称谓、动作方向时必须保守准确。
- reason：简短说明为什么值得标为高光点，重点说明具体冲突、信息冲击、情绪峰值、反差、危险感、悬念、传播性或观众即时反应价值；不要只写“很刺激”“很重要”。
- audience_reaction：观众可能产生的即时反应数组，1 到 4 个短语。
- interaction_value：一句话说明后续互动生成可围绕什么展开，但不生成具体互动内容。
- evidence.segment_ids：直接支撑该高光点的原始 segment id，非空，按升序排列。
- evidence.dialogues：关键台词摘录，必须来自对应 segments 的 text，保留原始写法；没有台词但由声音构成高光时可为空数组。
- evidence.audio_signals：关键声音证据，来自 speech、emotion、voice、music、audio_cues；没有可为空数组。

# 最终自检

输出前逐条检查：

1. 是否每个 highlight 都能独立成为一个可互动高光点？
2. 是否没有把普通过渡、普通解释、普通介绍误标为高光？
3. 是否没有把多个独立高光点合并成一条？
4. 是否没有把同一个高光点重复标注？
5. 是否 label 没有写成类型名？
6. 是否没有输出 type、category、highlight_type、tags？
7. 是否没有生成按钮文案、投票选项、组件、展示时长或前端配置？
8. 是否 level 3 足够严格？
9. 是否 trigger_segment_id 位于 evidence.segment_ids 中？
10. 是否 start、end、trigger_time 都来自 evidence 对应 segments 的时间范围？
11. 是否 summary、reason、audience_reaction、interaction_value 都有 evidence 支撑？
12. 是否最终输出是可被 JSON.parse 直接解析的单个 JSON 对象？
"""

USER_PROMPT = """
<drama_context>
{{DRAMA_CONTEXT_JSON_MINIFIED}}
</drama_context>

<segments>
{{SEGMENTS_JSON_MINIFIED}}
</segments>

请根据 segments 识别可互动剧情高光点，并严格按照 system prompt 指定的 JSON 格式输出。
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
    raise ValueError(f"重试 {MAX_ATTEMPTS} 次后仍未生成有效高光点结果")


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
