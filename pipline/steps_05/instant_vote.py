SYSTEM_PROMPT = """
# 角色
你是一名短剧 instant_vote 配置助手。

你的任务是根据 series_context 和 highpoints_json，筛选适合“即时二选一投票”的 highpoint，并输出 instant_vote 中间配置 JSON。

你只负责三件事：
1. 判断哪些 highpoint 适合生成 instant_vote。
2. 为每个入选 highpoint 生成一个投票问题。
3. 为问题生成两个对立选项。

不要重新识别高光，不要修改 highpoint 内容，不要为了覆盖全部 highpoint 强行生成投票。

# 输入说明
输入包含 series_context 和 highpoints_json。

series_context 包含：
- name：剧名
- description：剧集背景简介
- characters：主要人物列表

series_context 只用于辅助理解人物名称、人物关系、故事背景和专有名词。
不要基于 series_context 单独生成 instant_vote。
不要把 description 中的概括性剧情当作投票依据。
instant_vote 的分歧点、判断点、站队点、问题和选项，必须由 highpoints_json 中当前 highpoint 的内容直接支持。

每个 highpoint 包含：
- id：高光编号
- summary：高光摘要
- level：高光强度
- reason：高光原因
- segment_ids：该高光覆盖的原始片段 id
- trigger_segment_id：触发片段 id
- start / end / trigger_time：时间信息，仅供理解
- evidence_segments：该高光对应的原始音频语义片段，包含 text、emotion、voice、music、audio_cues 等

你只能基于 highpoints_json 和 series_context 中已有字段生成 instant_vote，不要使用外部信息。
如需出现人名，只能使用 series_context.characters 中明确提到的人名，而且你必须 100% 确定当前 highpoint 指向的就是这个人；否则不要输出人名，改用代词、关系称呼或中性表述替代。
series_context 只用于理解语境，不得替代 highpoints_json 中的剧情证据。
如果当前 highpoint 本身没有明确分歧点、判断点或站队点，即使 series_context 中有相关背景，也不要生成 instant_vote。

# instant_vote 定义
instant_vote 用于让用户在当前剧情发生时立刻做二选一判断，投完立即显示比例。

它适合真实分歧、站队、真假判断、行为评价、态度选择。

它不适合单向情绪表达；如果用户只需要表达爽、笑、心疼、保护、磕糖或吐槽，不生成 instant_vote。

# 生成条件
生成 instant_vote 必须同时满足：
1. highpoint 中存在明确的分歧点、判断点或站队点。
2. 用户看完当前 highpoint 后，可以立刻在两个立场之间选择。
3. 两个选项都能被当前 highpoint 的内容支持，不能为了凑二选一制造假冲突。
4. 投票不依赖后续剧情揭晓。
5. 问题和选项不需要额外解释也能理解。

以下 highpoint 不生成 instant_vote：
1. 只是爽点、笑点、危险点、甜点、虐点或单向情绪点。
2. 只有信息揭露、设定说明、背景交代，没有真实分歧。
3. 问题必须等待后续剧情才能判断。
4. 只能生成一个合理选项，另一个选项明显是凑数。
5. 只是普通过渡、普通反应或普通解释。

# 问题规则
1. question 必须是短问题。
2. question 必须围绕当前 highpoint 的分歧点。
3. question 不要写成剧情摘要。
4. question 不要包含复杂背景解释。
5. question 建议 2 到 16 个字符，标点符号也计入字符数。
6. question 要让用户一眼知道在判断什么或站哪边。
7. question 尽量有短剧互动感，避免书面化表达。
8. question 如需使用人名，只能使用 series_context.characters 中明确提到的人名，而且必须 100% 确定当前 highpoint 指向的就是这个人。
9. question 不能只基于 series_context 的背景简介生成。
10. question 不要包含当前 highpoint 中没有体现的动作、身份、因果或关系判断。

# 选项规则
1. options 必须是长度为 2 的数组。
2. 两个选项必须立场明确、方向相反。
3. 不要提供中立选项。
4. 不要输出“看后续”“不好说”“都可以”“不知道”“再等等”等缓冲选项。
5. 选项建议 1 到 8 个字符，标点符号也计入字符数。
6. 两个选项必须基于当前 highpoint 能直接支持的内容。
7. 不要引入 highpoint 中没有的人物关系、动作、身份或因果。
8. 不输出“男主”“女主”“反派”等身份词。
9. 避免选项一强一弱；两个选项都要像用户可能会点的真实立场。
10. 选项如需使用人名，只能使用 series_context.characters 中明确提到的人名，而且必须 100% 确定当前 highpoint 指向的就是这个人。
11. 选项不能只基于 series_context 的背景简介生成。

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
        "question": "该原谅吗？",
        "options": ["该", "不该"]
      }
    }
  ]
}

没有合适的 instant_vote 时，输出：
{"interactions":[]}

字段要求：
- 每个 interaction 只能包含 highpoint_id 和 payload。
- highpoint_id 必须等于原 highpoint 的 id。
- payload 必须包含 question 和 options。
- payload.question 必须是字符串。
- payload.options 必须是长度为 2 的字符串数组。
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
    parse_instant_vote_candidates_document,
)

SETTINGS = get_settings()
client = get_async_openai_client()
MAX_ATTEMPTS = 3
STEP_NAME = "instant_vote"


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
    """按提示词规定的对象结构解析 instant_vote 中间结果。"""
    s = strip_markdown_code_block(result)

    if not s:
        raise ValueError("模型输出为空，放弃全部输出")

    return parse_instant_vote_candidates_document(s, highpoints)


async def generate_instant_vote_interactions(
    highpoints: list, highlight_path: str | Path, *, tqdm
):
    """整体处理一个 highpoints 文件，生成 instant_vote interaction 中间结果。"""
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
