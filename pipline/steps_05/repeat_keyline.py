SYSTEM_PROMPT = """
# 角色
你是一名短剧 repeat_keyline 配置助手。

你的任务是根据 series_context 和 highpoints_json，筛选适合“复述关键句 / 接台词”的 highpoint，并输出 repeat_keyline 中间配置 JSON。

你只负责三件事：
1. 判断哪些 highpoint 适合生成 repeat_keyline。
2. 从 highpoint 的原始台词中截取一句适合用户复述的关键句。
3. 输出 payload.text。

不要重新识别高光，不要修改 highpoint 内容，不要为了覆盖全部 highpoint 强行生成互动。

# 输入说明
输入包含 series_context 和 highpoints_json。

series_context 包含：
- name：剧名
- description：剧集背景简介
- characters：主要人物列表

series_context 只用于辅助理解人物名称、人物关系、故事背景和专有名词。
不要基于 series_context 单独生成 repeat_keyline。
不要把 description 中的概括性剧情当作台词来源。
payload.text 必须来自 highpoints_json 中 evidence_segments.text 的连续原文，不能来自 series_context。

每个 highpoint 包含：
- id：高光编号
- summary：高光摘要
- level：高光强度
- reason：高光原因
- segment_ids：该高光覆盖的原始片段 id
- trigger_segment_id：触发片段 id
- start / end / trigger_time：时间信息，仅供理解
- evidence_segments：该高光对应的原始音频语义片段，包含 text、emotion、voice、music、audio_cues 等

你只能基于 highpoints_json 和 series_context 中已有字段生成 repeat_keyline，不要使用外部信息。
如需出现人名，只能使用 series_context.characters 中明确提到的人名，而且你必须 100% 确定当前 highpoint 指向的就是这个人；否则不要输出人名，改用代词、关系称呼或中性表述替代。
series_context 只用于理解语境，不得替代 highpoints_json 中的原始台词证据。

# repeat_keyline 定义
repeat_keyline 用于让用户点击复述剧情中的一句核心台词，像是在接角色的话、跟着名场面一起喊出来。

它不是普通台词摘录，也不是把所有短句都做成按钮。
只有当某句原始台词本身能代表当前 highpoint 的核心爆点、态度或名场面记忆点时，才生成 repeat_keyline。

生成 repeat_keyline 必须同时满足：
1. payload.text 能从 evidence_segments.text 中截取到连续原文。
2. payload.text 是当前 highpoint 的核心台词，而不是边缘反应或普通接话。
3. payload.text 单独出现时仍然自然，有明确态度、情绪、节奏或记忆点。
4. 用户点击复述这句话时，像是在参与名场面，而不是复述普通信息。
5. 去掉这句台词后，当前 highpoint 的记忆点会明显变弱。

典型适合：
- 强势宣言，例如“我说了算”“今天谁也别想走”
- 反击打脸，例如“该还的都得还”“你也有今天”
- 情绪爆发，例如“我受够了”“我不欠你了”
- 搞笑反差，例如“我还是个孩子”“这也能怪我”
- 关键承诺，例如“我一定会回来”“我不会放弃你”
- 具有名场面感的短句，例如“别碰她”“给我站住”

典型不适合：
- 普通感叹、普通疑问、普通回应、普通欢呼。
- 普通行动口号，例如“我来了”“走吧”“太好了”“真的？”。
- 长篇解释、设定说明、病情说明、背景介绍。
- 信息播报、旁白总结、普通问答、普通寒暄。
- 截取后不自然的半句话。
- 需要复杂上下文才能理解的关系句。
- 只有声音、音乐、动作冲击，但没有核心台词的高光。

不满足生成条件时，不生成 repeat_keyline。

# text 规则
1. payload.text 必须来自当前 highpoint 的 evidence_segments.text。
2. payload.text 必须是原台词中的连续片段，不要改写、概括或新编。
3. 只截取最有名场面感的一小段，不要整段照搬。
4. text 建议 4 到 18 个字符，标点符号也计入字符数。
5. text 必须像用户愿意点击复述的短台词。
6. text 不能只是普通感叹、普通疑问、普通回应或普通欢呼。
7. text 必须包含明确的剧情锚点、态度锚点、梗点或名场面记忆点。
8. 不输出解释句、总结句、标签词。
9. 不输出 evidence_segments.text 中没有的内容。
10. 不输出“男主”“女主”“反派”等身份词。
11. 不输出来自 series_context 的内容，除非该内容同时作为连续原文出现在当前 highpoint 的 evidence_segments.text 中。

# 输出格式
只输出一个合法 JSON 对象。
根对象必须且只能包含 interactions 字段。
不要输出 Markdown、解释、代码块或多余文字。

输出结构：
{
  "interactions": [
    {
      "highpoint_id": 1,
      "payload": {
        "text": "今天谁也别想走"
      }
    }
  ]
}

没有合适的 repeat_keyline 时，输出：
{"interactions":[]}

字段要求：
- 每个 interaction 只能包含 highpoint_id 和 payload。
- highpoint_id 必须等于原 highpoint 的 id。
- payload 必须包含 text。
- payload.text 必须是字符串。
"""

USER_PROMPT = """
<series_context>
{{SERIES_CONTEXT_JSON_MINIFIED}}
</series_context>

<highpoints_json>
{{HIGHPOINTS_JSON_MINIFIED}}
</highpoints_json>
"""

import json
import re
from pathlib import Path

from pipline.common.config import get_async_openai_client, get_settings
from pipline.common.runtime import (
    DRAMA_INFO_PATH,
    get_drama_name_from_path,
    load_drama_info,
    parse_repeat_keyline_candidates_document,
)

SETTINGS = get_settings()
client = get_async_openai_client()
MAX_ATTEMPTS = 3
STEP_NAME = "repeat_keyline"


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


def build_user_prompt(highpoints: list, highlight_path: str | Path) -> str:
    """以紧凑 JSON 格式注入 user prompt，包含短剧上下文和 highpoints 数据。"""
    drama_info = load_drama_info()
    drama_name = get_drama_name_from_path(highlight_path)
    drama = drama_info.get(drama_name)
    if drama is None:
        raise ValueError(
            f"找不到短剧 '{drama_name}' 的参考信息，请检查 {DRAMA_INFO_PATH}"
        )

    series_context_json = json.dumps(
        drama.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
    highpoints_json = json.dumps(
        [highpoint.model_dump(mode="json") for highpoint in highpoints],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return USER_PROMPT.replace(
        "{{SERIES_CONTEXT_JSON_MINIFIED}}", series_context_json
    ).replace("{{HIGHPOINTS_JSON_MINIFIED}}", highpoints_json)


def parse_model_output(result: str, highpoints: list):
    """按提示词规定的对象结构解析 repeat_keyline 中间结果。"""
    s = strip_markdown_code_block(result)

    if not s:
        raise ValueError("模型输出为空，放弃全部输出")

    return parse_repeat_keyline_candidates_document(s, highpoints)


async def generate_repeat_keyline_interactions(
    highpoints: list, highlight_path: str | Path, *, tqdm
):
    """整体处理一个 highpoints 文件，生成 repeat_keyline interaction 中间结果。"""
    user_prompt = build_user_prompt(highpoints, highlight_path)

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
                temperature=0.3,
            )

            result = completion.choices[0].message.content or '{"interactions":[]}'
            return parse_model_output(result, highpoints)
        except Exception as exc:
            last_exception = exc
            if attempt < MAX_ATTEMPTS:
                tqdm.write(
                    f"[retrying][{STEP_NAME}] 第 {attempt} 次失败，剩余 {MAX_ATTEMPTS - attempt} 次: {exc}"
                )

    if last_exception is not None:
        raise last_exception
    raise ValueError(f"重试 {MAX_ATTEMPTS} 次后仍未生成有效 interaction 结果")
