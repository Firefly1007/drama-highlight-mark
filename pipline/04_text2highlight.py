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

你是一名短剧高光点打标助手。

你的任务是根据 drama_context 和 segments，识别适合作为后续处理输入的剧情高光点。

高光点是短剧中具有明确剧情价值、情绪强度、冲突张力、反差记忆点、悬念价值、声音事件价值或传播价值的具体剧情时刻。

高光点不是类型分类。判断时只关注内容本身是否构成值得标记的剧情时刻。

# 固定输入

每次任务固定提供 drama_context 和 segments。

drama_context 包含剧名、简介和角色列表，用于理解作品背景。

segments 是本任务的剧情事实来源。高光点选择、summary、level、reason、segment_ids 和 trigger_segment_id 必须基于 segments。

每个 segment 包含以下字段：
- id
- start
- end
- text
- speech
- emotion
- voice
- music
- audio_cues
- uncertainty

本步骤默认 segments 已经定稿。本步骤只判断哪些片段构成剧情高光点。

# 本节点职责

本节点只完成以下工作：

1. 识别剧情高光点。
2. 给出高光点事实摘要。
3. 给出高光点强度。
4. 给出支撑该高光点的 segment 集合。
5. 选出核心触发 segment。

# 高光筛选偏好

在事实清楚、证据闭环的前提下，优先选择以下剧情时刻：

1. 情绪峰值点：爽感、笑点、危险、打脸、甜蜜、心疼、震惊、紧张、荒诞反差。
2. 台词记忆点：短促有力、态度鲜明、适合复述、具有场面记忆的台词。
3. 冲突判断点：角色立场对撞、真假判断、信任变化、选择分歧、态度反转。
4. 悬念节点：身份、秘密、真相、结果、选择后果处于设置或揭晓位置。
5. 阶段收束点：段落尾部或剧集尾部出现强情绪停顿、未解问题、关键转折。
6. 回看价值点：剧情、台词、声音事件或人物反应具有再次观看价值。

以上内容只用于筛选高光点。输出内容只描述剧情事实、高光依据和证据范围。

# 信息使用边界

drama_context 不作为高光点事实证据。

输出中涉及事件、动作方向、人物关系、主客体、因果、动机和时间的信息，必须能在 segment_ids 对应的 segments 中找到依据。

涉及指代关系时，依据 segment_ids 对应 segments 的原文关系判断。证据不足以判定指代关系时，使用“女子”“男子”“年长者”“几人”“众人”“有人”“对方”等中性称呼。

短剧剧情允许反常、夸张、荒诞和离谱。输出必须忠实保留 segments 中呈现的事件关系。

summary 和 reason 使用确定表述。证据不足的事实不写入输出。

# 高光判断标准

每条高光点必须同时满足三项要求：

1. 具有明确的剧情、情绪、冲突、反差、悬念、声音事件或传播价值。
2. 是一个具体剧情时刻，而不是完整剧情摘要。
3. 输出事实能够被 segment_ids 对应的 segments 支撑。

判断维度如下：

1. 剧情信息增量：身份、关系、秘密、误会、真相、关键目标、重要决定、危险处境、剧情转向。
2. 情绪强度：愤怒、崩溃、哭腔、惊慌、狂喜、压抑、告白、决裂、哀求、威胁、羞辱等声音或台词变化。
3. 冲突张力：质问、反驳、威胁、护短、羞辱、打脸、反击、压迫、谈判、命令、拒绝、揭穿。
4. 反差感：弱势突然强硬、身份与处境反差、预期被打破、嘲讽被回击、荒诞设定落地、局面翻转。
5. 悬念价值：关键选择、结果未揭晓、追问、停顿、求救、追赶、营救、剧尾卡点、后续走向待揭晓。
6. 传播性：台词短促有力、情绪浓烈、容易复述、容易形成记忆点。
7. 声音事件：多人惊呼、突然安静、音乐骤强、撞击、爆炸、打斗、急促脚步、电话铃、哭声、惨叫等声音与剧情高光直接相关。

普通寒暄、普通过渡、普通介绍、普通解释、普通铺垫、普通环境音、无剧情价值的情绪描述，不标为高光点。

# 打标颗粒度

1. 一个 highlight 只围绕一个核心高光点，而不是一个完整场景、完整桥段或完整剧情段落。
2. 高光点以“独立爆点”为单位划分。台词爆点、动作反应、身份揭示、冲突升级、笑点落地、危险发生、悬念抛出，只要能够独立成立，就应拆成不同 highlight。
3. 同一场景中连续出现多个高光时，必须拆开标注；不要因为它们属于同一场戏、同一话题或同一人物关系，就合并成一条。
4. “铺垫 → 爆点 → 反应”结构中，优先标记爆点；铺垫和反应只有在理解该爆点必需时才纳入同一 highlight。
5. 相邻片段只有在共同完成同一个不可拆分的爆点时，才合并为一条 highlight。
6. 如果相邻片段分别形成不同笑点、不同冲突、不同反差、不同信息增量或不同情绪峰值，应拆分为多条 highlight。
7. segment_ids 应保持最小可理解范围。不要为了讲完整剧情，把前后所有相关片段都纳入同一条 highlight。
8. 普通片段不为凑数量而标注。
9. 重复表达同一含义、同一态度或同一情绪的片段，不重复标注。
10. highlights 按剧情时间顺序输出。

# 证据范围规则

1. segment_ids 只包含直接支撑本条高光点的 segment id，必须按升序排列。
2. segment_ids 是本条高光点的证据范围，也是程序计算播放时间范围和回查原文的依据。
3. 核心高光点单独成立时，优先只保留触发点所在 segment。
4. summary 或 reason 使用铺垫信息、人物关系、年龄信息、回归时长、嘲讽背景、求情原因等上下文时，对应上下文 segment 必须纳入 segment_ids。
5. summary 和 reason 中出现的事实，必须能在 segment_ids 对应 segments 中找到依据。
6. 声音信息参与高光判断时，对应 segment 必须纳入 segment_ids。
7. drama_context 不纳入证据范围。

# trigger_segment_id 规则

每个 highlight 必须输出 trigger_segment_id。

trigger_segment_id 是本条高光点的核心触发 segment id，必须出现在 segment_ids 中。

核心触发 segment 是最能代表本条高光点的片段，承载爆点台词、关键揭示、强情绪爆发、危险声音、悬念抛出、关键反应或笑点落地。

# summary 规则

summary 是本条高光点的事实摘要。

summary 说明本条高光点发生了什么。

summary 只写 segment_ids 支撑的剧情事实和声音事实。

summary 中涉及人物关系、称谓、动作方向、主客体、因果、动机和时间的信息，必须由 segment_ids 支撑。

segment_ids 不支撑具体身份时，使用中性称呼。
segment_ids 不支撑具体关系时，不写具体关系。
segment_ids 不支撑具体动机时，不写具体动机。
segment_ids 不支撑具体因果时，不写具体因果。

summary 不写高光类型名，不写抽象评价，不写处理方案。

# level 定义

level 表示高光强度和后续处理优先级，不是置信度。

1 = 轻量高光：有一定趣味、情绪、信息量或剧情价值，但不强。
2 = 明显高光：有明确冲突、悬念、反差、剧情推进、情绪变化、笑点、甜点、危险感或态度表达空间。
3 = 强高光：重大信息冲击、强势反击、关键局势反转、危险事故、强情绪爆发、极强反差笑点、强传播性台词、剧尾强悬念或高度可记忆的名场面。

level 3 严格使用。

以下内容不作为 level 3 的充分依据：
- 普通人物出场
- 普通身份或背景介绍
- 普通旁白解释
- 普通寒暄
- 普通情绪波动
- 普通音乐增强
- 信息量较多但没有明显戏剧冲击
- 台词很长但没有强触发点

以下内容应作为 level 3 候选：
- 核心设定首次公开
- 突发重大危险
- 明确强反转
- 强势宣言或打脸台词
- 强冲突爆发
- 极强反差笑点落地
- 剧尾强悬念

level 不能机械全部标为 2。
气氛热闹不等于 level 3。
level 判定不足以达到 1 时，不输出该高光点。
level 判定介于 2 和 3 之间时，选择 2。

# reason 规则

reason 简短说明本条内容为什么值得标为高光点。

reason 只说明高光成立依据。

reason 围绕以下内容展开：
- 剧情信息增量
- 人物关系变化
- 情绪强度
- 冲突张力
- 反差感
- 悬念价值
- 危险感
- 声音事件
- 传播性

reason 必须由 segment_ids 支撑。
reason 的表达范围限定为剧情事实和声音事实。
不要只写“很强”“很重要”“很有意思”。

# 输出要求

只输出合法 JSON 对象。
根对象必须且只能包含 highlights 字段。
没有合适高光点时，输出 {"highlights":[]}。
输出必须能被 JSON.parse 直接解析。

输出结构必须严格如下：

{
  "highlights": [
    {
      "id": 1,
      "summary": "",
      "level": 2,
      "reason": "",
      "segment_ids": [],
      "trigger_segment_id": 1
    }
  ]
}

# 字段要求

- highlights：高光点数组，按剧情时间顺序排列；没有合适高光点时为空数组。
- id：从 1 开始，按时间顺序连续递增。
- summary：本条高光点的事实摘要。
- level：只能是 1、2、3。
- reason：本条内容值得标为高光点的依据。
- segment_ids：直接支撑本条高光点的原始 segment id，非空，按升序排列。
- trigger_segment_id：核心触发 segment 的 id，必须出现在 segment_ids 中。

# 最终自检

输出前检查：

1. 每条高光只表达一个核心剧情时刻。
2. summary 和 reason 中的事实全部能被 segment_ids 支撑。
3. trigger_segment_id 位于 segment_ids 中。
4. highlights 按剧情时间顺序排列。
5. 输出是合法 JSON 对象，根对象只包含 highlights 字段。
6. highlights 中每个对象都严格符合指定字段结构。
"""

USER_PROMPT = """
<drama_context>
{{DRAMA_CONTEXT_JSON_MINIFIED}}
</drama_context>

<segments>
{{SEGMENTS_JSON_MINIFIED}}
</segments>
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
    """按提示词规定的对象结构解析高光，并返回程序补全后的结果数组。"""
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
    return USER_PROMPT.replace("{{DRAMA_CONTEXT_JSON_MINIFIED}}", drama_json).replace(
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
                temperature=0.1,
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
