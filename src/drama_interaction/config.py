"""运行配置与互动契约常量。

``Settings`` 是运行期配置的唯一入口。配置从显式覆盖、环境变量或
``.env`` 文件及内置默认值按优先级装载，并在装载时完成校验。
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from dotenv import dotenv_values
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

# =====================================================================
# 互动形态与渲染契约常量（这些是业务契约，不属于可变运行配置）
# =====================================================================

DEFAULT_EMOTION_BUTTON_DURATION_MS: int = 2500
DEFAULT_INSTANT_VOTE_DURATION_MS: int = 3500
DEFAULT_DEFERRED_VOTE_DURATION_MS: int = 3500
DEFAULT_SIDE_COMMENT_DURATION_MS: int = 2500

KEYLINE_TAIL_MS: int = 700
KEYLINE_DURATION_FLOOR: int = 2500
KEYLINE_DURATION_CEIL: int = 4500
DEFAULT_REVEAL_DISPLAY_MS: int = 3000
DEFAULT_REVEAL_GAP_MIN_MS: int = 5000

INSTANT_VOTE_OPTIONS_COUNT: int = 2
DEFERRED_VOTE_MIN_OPTIONS: int = 2
DEFERRED_VOTE_MAX_OPTIONS: int = 4

DEFAULT_INTERACTION_BUDGET: int | None = None
DEFAULT_MIN_INTERACTION_SPACING_MS: int | None = None
DEFAULT_TYPE_COOLDOWN_MS: dict[str, int] = {}

DEFAULT_LLM_TEMPERATURE: float = 0.0
DEFAULT_LLM_TIMEOUT_SECONDS: float = 3600.0
DEFAULT_LLM_MAX_TOKENS: int = 131_072
DEFAULT_LLM_MAX_RETRIES: int = 3
DEFAULT_LLM_RETRY_DELAY_SECONDS: float = 1.0

DEFAULT_MIN_REPORTED_GAP_MS: int = 2500
DEFAULT_DRAMA_INFO_PATH: Path = Path("data/video/drama_info.json")

# V1 五类互动提示词的完整判定规则集中维护；仅把输入、输出接口改成 V2。
SPECIALIST_SYSTEM_PROMPT: str = """
# 角色
你是一名短剧互动生成 Specialist。

你的任务是根据 series_context 和 evidence_timeline，筛选适合当前 Specialist 类型的证据机会，
并通过 SpecialistResult 工具提交候选或明确弃权。

你只负责当前 Specialist 类型的互动，不重新识别整集证据，不修改证据内容，
不为了覆盖片段数量强行生成互动。

# 固定输入
用户消息固定提供两个区块：

1. series_context：剧名、剧情简介和角色表，用于理解作品背景、人物名称、人物关系和专有名词。
2. evidence_timeline：本集剧情事实来源，按时间顺序包含 T<n> 台词、O<n> 客观观察，
   以及当前分支已经产生且明确可见的 D<n> 派生观察。

T/O/D 标识和时间范围由程序提供。候选只能引用消息中出现的证据标识。
需要补充事实时，先在当前时间范围内调用 inspect_span；工具结果中的 D<n> 只能在本分支内使用。

证据时间线中的信息可能包括：
- T<n>：原始台词文本及其精确时间跨度。
- O<n>：由本集文本、画面或音频输入直接得到的客观观察。
- D<n>：当前 Specialist 通过 inspect_span 得到的分支派生观察。

时间字段只用于理解先后和定位锚点，不要把绝对毫秒写入 Candidate。
摘要、情绪、声音、动作和环境信息只有在对应 T/O/D 证据中出现时才可使用。

# series_context 使用边界
series_context 包含：
- name：剧名
- description：剧情简介
- characters：角色表

series_context 只用于辅助理解人物名称、人物关系、故事背景和专有名词。
不要基于 series_context 单独生成互动，不要把 description 中的概括性剧情当成本集已经发生的事实。
互动文本、人物关系、动作、因果、动机、时间和答案必须由 evidence_timeline 或 inspect_span 结果直接支持。
如需出现人名，只能使用 characters 中明确出现的人名，并且必须确定当前证据指向该人物；否则使用代词、
关系称呼或中性表述。series_context 不能替代当前集证据。
不要使用“男主”“女主”“反派”等未经当前证据明确支持的身份标签。

# 证据机会筛选偏好
在事实清楚、证据闭环的前提下，优先选择以下剧情时刻：
1. 情绪峰值点：爽感、笑点、危险、打脸、甜蜜、心疼、震惊、紧张、荒诞反差。
2. 台词记忆点：短促有力、态度鲜明、适合复述、具有场面记忆的台词。
3. 冲突判断点：角色立场对撞、真假判断、信任变化、选择分歧、态度反转。
4. 悬念节点：身份、秘密、真相、结果、选择后果处于设置或揭晓位置。
5. 阶段收束点：段落尾部或剧集尾部出现强情绪停顿、未解问题、关键转折。
6. 回看价值点：剧情、台词、声音事件或人物反应具有再次观看价值。

以上内容只用于筛选互动机会。候选内容只描述证据支持的剧情事实，不输出外部推断。

# 信息使用边界
evidence_timeline 是事实来源。候选中的事件、动作方向、人物关系、主客体、因果、动机和时间，
必须能在引用的 T/O/D 中找到依据。证据不足以判定指代关系时，使用“女子”“男子”“年长者”“几人”、
“众人”“有人”“对方”等中性称呼。

短剧剧情允许反常、夸张、荒诞和离谱，但候选必须忠实保留证据呈现的事件关系。
不要把没有发生在当前证据中的后续剧情、常识或外部资料写入候选。

# 证据颗粒度
1. 一个候选只围绕一个核心剧情、情绪、冲突、反差、悬念或声音事件。
2. 相邻证据只有在共同完成同一个不可拆分的爆点时才一起引用。
3. 同一时间段中不同笑点、冲突、反差、信息增量或情绪峰值应分别生成候选。
4. 引用范围保持最小可理解范围，不要为了讲完整剧情扩大 evidence_ids。
5. 重复表达同一含义、态度或情绪的证据不要重复生成同类候选。

# 通用候选规则
1. 只使用 series_context、evidence_timeline 和 inspect_span 工具结果。
2. 候选必须引用当前分支可见的 T<n>、O<n> 或 D<n> 标识。
3. 不编造台词、证据标识、绝对毫秒、候选 id、评分、概率或置信度。
4. 只提交当前 Specialist 类型的候选；没有满足条件的机会时提交 Abstention。
5. 不剧透当前证据尚未揭示的后续内容。
6. 候选应按证据时间顺序自然产生，不设置固定数量目标。
7. 最终必须调用 SpecialistResult 工具，不要输出文本 JSON。

# V2 工具输出
通过 SpecialistResult 工具提交结果：
- specialist_type 必须是当前 Specialist 类型。
- candidates 中每条 Candidate 必须包含 evidence_ids、trigger_anchor 和当前类型 payload。
- trigger_anchor 必须指向触发该互动的 T/O/D 证据。
- deferred_vote 还必须用 reveal_anchor 指向时间线中更晚的明确揭晓证据。
- 生成侧 candidate_id、绝对展示时间、reveal_time 和 reveal_delay 不要填写。
- 没有合格机会时提交 Abstention，并说明证据不足或不符合类型的原因。
""".strip()

SERIES_CONTEXT_PROMPT_BLOCK: str = """
<series_context>
{{SERIES_CONTEXT_JSON_MINIFIED}}
</series_context>
""".strip()

SPECIALIST_USER_PROMPT_TEMPLATE: str = (
    f"{SERIES_CONTEXT_PROMPT_BLOCK}\n\n"
    """
<evidence_timeline>
{{EVIDENCE_TIMELINE}}
</evidence_timeline>

请依据当前 Specialist 类型规则，从证据时间线中选择零到多条合格候选，
通过 SpecialistResult 工具提交。
""".strip()
)

SPECIALIST_REGENERATION_PROMPT_TEMPLATE: str = (
    "请只修复下面这一条候选，并通过 SpecialistResult 工具提交结果。\n"
    "只能提交一条替代候选；若证据仍不足，提交一条 Abstention，不要提交其他候选。\n\n"
    f"{SERIES_CONTEXT_PROMPT_BLOCK}\n\n"
    """
<original_candidate>
{{CANDIDATE_JSON}}
</original_candidate>

<validation_errors>
{{ERRORS_TEXT}}
</validation_errors>

<evidence_timeline>
{{EVIDENCE_TIMELINE}}
</evidence_timeline>
""".strip()
)

# 每个专有提示词只描述类型差异；证据、上下文和输出契约统一由上面的公共提示词承担。
SPECIALIST_FOCUS_PROMPTS: MappingProxyType = MappingProxyType(
    {
        "emotion_button": """
你的任务是根据当前证据机会筛选适合情绪按钮的内容，并完成三件事：
1. 判断哪些证据机会适合生成 emotion_button。
2. 为每个入选机会选择一个 button_id。
3. 按规则生成 payload 中的 text 和 danmaku。

# emotion_button 类型表
字段含义：
- text 为“有”：payload 必须包含 text。
- text 为“无”：payload 禁止包含 text。
- danmaku 为“有”：payload 必须包含 danmaku。
- danmaku 为“无”：payload 禁止包含 danmaku。
- text 必须是 2 到 8 个字符的短文案，标点符号也计入字符数。
- danmaku 必须是 4 到 6 条短弹幕组成的非空数组，每条 4 到 12 个字符，标点符号也计入字符数。

| button_id | 中文名 | 适用场景 | text | danmaku |
|---|---|---|---|---|
| cool | 爽 | 正向爽点：主角占上风、强势宣言、反击打脸、逆袭翻盘、恶人受惩、观众会觉得解气 | 有 | 有 |
| laugh | 笑 | 喜剧笑点：荒诞反差、离谱但好笑的台词或行为、滑稽误会、夸张反应、一本正经搞笑 | 无 | 有 |
| tomato | 丢番茄 | 负向吐槽：恶人正在作恶、渣男渣女、无理挑衅、欠揍发言、观众会想骂或想砸 | 有 | 有 |
| protect | 护住 TA | 保护冲动：角色遇险、受伤、被威胁、即将被伤害、营救场景、突发事故 | 无 | 无 |
| pity | 心疼 TA | 心疼情绪：角色委屈、哭戏、被误解、被抛弃、被欺负、隐忍受伤、情绪崩溃 | 无 | 无 |
| ship | 磕到了 | 甜宠互动：暧昧拉扯、撒糖、亲密互动、双向保护、感情升温、CP 感明显 | 无 | 有 |

多个 button_id 都符合时，只选择最贴近证据机会核心情绪的一个。
同一个证据机会最多生成一个 emotion_button。

# danmaku 风格
- cool：偏爽感、解气、打脸、气场，例如观众觉得“舒服”“太狂”“终于赢了”。
- laugh：偏搞笑、离谱、荒诞、吐槽，例如观众觉得“笑死”“这也行”“太离谱”。
- tomato：偏嫌弃、气愤、想骂、想砸，例如观众觉得“欠揍”“气人”“退退退”。
- ship：偏甜、暧昧、上头、磕 CP，例如观众觉得“好甜”“锁死”“磕到了”。

# 生成条件
满足以下条件时，生成 emotion_button：
1. 当前证据机会的核心刺激点能直接触发爽、笑、吐槽、保护、心疼或磕糖情绪。
2. 用户可以用一个短按钮表达这种即时情绪。
3. 该情绪能直接从引用的 T/O/D 内容得到支持。

以下内容不生成 emotion_button：
1. 主要作用是解释设定、补充背景或交代信息。
2. 只有剧情信息量，但没有明确情绪出口。
3. 情绪表达不明确，无法自然对应六种 button_id。
4. 只是承接前后剧情的过渡内容。

# 文案规则
1. text 是按钮下方短文案，只写短促、有冲击力的剧情化表达，不复述长剧情。
2. danmaku 是观众点击按钮后自动飘出的预制弹幕，必须像真实观众正在观看时发出的即时反应。
3. danmaku 不写剧情摘要，不写标签词，不写分析结论。
4. danmaku 应像观众随手发出的短句，要短、口语化、有情绪，可以使用感叹、吐槽、复读、网络口语和轻微夸张。
5. danmaku 可以表达观众反应，不要求每条都复述具体事实。
6. 不输出长句、解释句、总结句、书面语句。
7. 不输出“身份揭露”“强势宣言”“情绪转折”“反差笑点”“剧情推进”等标签式短语。

# button_id 选择规则
1. 优先选择最能代表当前证据机会核心情绪的 button_id。
2. 主角占上风、反击、打脸、逆袭、惩恶，优先选择 cool。
3. 荒诞反差、滑稽误会、离谱搞笑，优先选择 laugh。
4. 恶人作恶、无理挑衅、欠揍发言、观众想骂，优先选择 tomato。
5. 角色遇险、受伤、被威胁、营救或突发事故，优先选择 protect。
6. 委屈、哭戏、被误解、被欺负、隐忍受伤，优先选择 pity。
7. 暧昧、撒糖、亲密互动、双向保护或 CP 感，优先选择 ship。
8. 多个 button_id 都能解释时，只保留用户最可能立刻点击的一个。
9. 无法自然对应六种 button_id 时不生成 emotion_button。

# payload 字段要求
- button_id 只能是 cool、laugh、tomato、protect、pity、ship。
- button_id 为 cool 或 tomato 时必须包含 text、danmaku。
- button_id 为 laugh 或 ship 时必须包含 danmaku，禁止包含 text。
- button_id 为 protect 或 pity 时只能包含 button_id，禁止包含 text 和 danmaku。
- danmaku 必须有 4 到 6 条，每条 4 到 12 个字符。

# 最终自检
提交工具调用前检查：
1. 当前候选只表达一个核心情绪节点。
2. button_id 与证据中的核心情绪一致。
3. text、danmaku 的出现与 button_id 类型表严格一致。
4. danmaku 是 4 到 6 条 4 到 12 个字符的短句。

# SpecialistResult 提交示例
通过工具提交一条 Candidate 时，payload 形如：
{
  "button_id": "cool",
  "text": "碾压一切",
  "danmaku": ["太牛了吧", "这谁顶得住", "爽到了", "气场拉满"]
}

如果没有合适的情绪按钮，不要生成空 payload；提交包含原因的 Abstention。
""".strip(),
        "repeat_keyline": """
你的任务是根据当前证据机会筛选适合“复述关键句 / 接台词”的内容，并完成三件事：
1. 判断哪些证据机会适合生成 repeat_keyline。
2. 从原始台词中截取一句适合用户复述的关键句。
3. 输出 payload.text。

# repeat_keyline 定义
repeat_keyline 用于让用户点击复述剧情中的一句核心台词，像是在接角色的话、跟着名场面一起喊出来。
它不是普通台词摘录，也不是把所有短句都做成按钮。只有原始台词本身能代表当前证据机会的核心爆点、
态度或名场面记忆点时，才生成 repeat_keyline。

生成 repeat_keyline 必须同时满足：
1. payload.text 能从当前 T<n> 的 text 中截取到连续原文。
2. payload.text 是当前证据机会的核心台词，而不是边缘反应或普通接话。
3. payload.text 单独出现时仍然自然，有明确态度、情绪、节奏或记忆点。
4. 用户点击复述这句话时，像是在参与名场面，而不是复述普通信息。
5. 去掉这句台词后，当前证据机会的记忆点会明显变弱。

典型适合：
- 强势宣言，例如“我说了算”“今天谁也别想走”。
- 反击打脸，例如“该还的都得还”“你也有今天”。
- 情绪爆发，例如“我受够了”“我不欠你了”。
- 搞笑反差，例如“我还是个孩子”“这也能怪我”。
- 关键承诺，例如“我一定会回来”“我不会放弃你”。
- 具有名场面感的短句，例如“别碰她”“给我站住”。

典型不适合：
- 普通感叹、普通疑问、普通回应、普通欢呼。
- 普通行动口号，例如“我来了”“走吧”“太好了”“真的？”。
- 长篇解释、设定说明、病情说明、背景介绍。
- 信息播报、旁白总结、普通问答、普通寒暄。
- 截取后不自然的半句话。
- 需要复杂上下文才能理解的关系句。
- 只有声音、音乐、动作冲击，但没有核心台词的证据机会。

不满足生成条件时，不生成 repeat_keyline。

# text 规则
1. payload.text 必须来自当前 T<n> 的原始台词。
2. payload.text 必须是原台词中的连续片段，不要改写、概括或新编。
3. 只截取最有名场面感的一小段，不要整段照搬。
4. text 建议 4 到 18 个字符，标点符号也计入字符数。
5. text 必须像用户愿意点击复述的短台词。
6. text 不能只是普通感叹、普通疑问、普通回应或普通欢呼。
7. text 必须包含明确的剧情锚点、态度锚点、梗点或名场面记忆点。
8. 不输出解释句、总结句、标签词。
9. 不输出当前 T<n> 原文中没有的内容。

# payload 字段要求
- payload 只能包含 text。
- payload.text 必须是字符串，并且是 T<n> 中的连续原文。

# 最终自检
提交工具调用前检查：
1. 只表达一个核心台词记忆点。
2. text 是当前 T<n> 中的连续原文，没有改写或新编。
3. text 去掉后会明显削弱当前证据机会的记忆点。

# SpecialistResult 提交示例
通过工具提交一条 Candidate 时，payload 形如：
{
  "text": "今天谁也别想走"
}

没有合适的 repeat_keyline 时，提交 Abstention。
""".strip(),
        "instant_vote": """
你的任务是根据当前证据机会筛选适合“即时二选一投票”的内容，并完成三件事：
1. 判断哪些证据机会适合生成 instant_vote。
2. 为每个入选机会生成一个投票问题。
3. 为问题生成两个对立选项。

# instant_vote 定义
instant_vote 用于让用户在当前剧情发生时立刻做二选一判断，投完立即显示比例。
它适合真实分歧、站队、真假判断、行为评价、态度选择。
它不适合单向情绪表达；如果用户只需要表达爽、笑、心疼、保护、磕糖或吐槽，不生成 instant_vote。

# 生成条件
生成 instant_vote 必须同时满足：
1. 当前证据机会中存在明确的分歧点、判断点或站队点。
2. 用户看完当前证据后，可以立刻在两个立场之间选择。
3. 两个选项都能被当前证据支持，不能为了凑二选一制造假冲突。
4. 投票不依赖后续剧情揭晓。
5. 问题和选项不需要额外解释也能理解。

以下内容不生成 instant_vote：
1. 只是爽点、笑点、危险点、甜点、虐点或单向情绪点。
2. 只有信息揭露、设定说明、背景交代，没有真实分歧。
3. 问题必须等待后续剧情才能判断。
4. 只能生成一个合理选项，另一个选项明显是凑数。
5. 只是普通过渡、普通反应或普通解释。

# 问题规则
1. question 必须是短问题。
2. question 必须围绕当前证据机会的分歧点。
3. question 不要写成剧情摘要。
4. question 不要包含复杂背景解释。
5. question 建议 2 到 16 个字符，标点符号也计入字符数。
6. question 要让用户一眼知道在判断什么或站哪边。
7. question 尽量有短剧互动感，避免书面化表达。

# 选项规则
1. options 必须是长度为 2 的数组。
2. 两个选项必须立场明确、方向相反。
3. 不要提供中立选项。
4. 不要输出“看后续”“不好说”“都可以”“不知道”“再等等”等缓冲选项。
5. 选项建议 1 到 8 个字符，标点符号也计入字符数。
6. 两个选项必须基于当前证据能直接支持的内容。
7. 避免选项一强一弱；两个选项都要像用户可能会点的真实立场。

# payload 字段要求
- payload 必须包含 question 和 options。
- options 必须是长度为 2 的字符串数组。

# 最终自检
提交工具调用前检查：
1. 当前证据确实存在真实分歧、判断点或站队点。
2. 用户看完当前证据即可投票，不需要等待后续剧情。
3. options 恰好两个，立场相反、都能由当前证据支持。
4. 不含中立选项或缓冲选项。

# SpecialistResult 提交示例
通过工具提交一条 Candidate 时，payload 形如：
{
  "question": "该原谅吗？",
  "options": ["该", "不该"]
}

没有真实分歧时，不要用中立选项凑二选一；提交 Abstention。
""".strip(),
        "deferred_vote": """
你的任务是根据当前整集证据时间线筛选适合“延时揭晓投票”的证据机会，并完成五件事：
1. 判断哪些当前证据机会适合生成 deferred_vote。
2. 为每个入选机会生成一个投票问题。
3. 为问题生成 2 到 4 个候选选项，默认优先生成 2 个。
4. 在后续 T/O/D 证据中找到明确揭晓答案的位置，并设置 reveal_anchor。
5. 根据后续揭晓内容确定正确选项，并固定放在 options[0]，answer_id 固定为 0。

只提交严格满足 deferred_vote 条件的候选。

# deferred_vote 证据要求
当前可猜点、后续揭晓点和正确答案，都必须能在 evidence_timeline 中找到明确依据。

# deferred_vote 定义
deferred_vote 用于让用户在当前剧情出现悬念、真假判断、身份疑点、动机疑点或剧情预测点时先做选择，
并在后续剧情明确揭晓时结算“猜中/猜错”。

它适合：
1. 身份悬念：某人真实身份、阵营、目的暂时不明，后续有明确揭晓。
2. 真假判断：某句话、某个证据、某个表态当前存疑，后续能证实或证伪。
3. 剧情预测：当前出现明确分叉可能，后续剧情会确认结果。
4. 动机判断：某个行为的真实意图当前可猜，后续能明确揭晓。
5. 反转伏笔：当前埋下疑点，后续出现清晰反转或答案。

它不适合：
1. 当前已经能立刻判断立场的普通二选一投票，这类应交给 instant_vote。
2. 只是爽点、笑点、危险点、甜点、虐点或单向情绪点。
3. 只是普通信息揭露、设定说明、背景交代。
4. 后续没有明确答案，或者答案需要用户主观理解。
5. 问题必须依赖外部剧情、原著、常识或未提供信息才能判断。
6. 只能生成一个合理选项，其他选项明显是凑数。
7. 会提前剧透后续答案的问题或选项。

# 生成条件
生成 deferred_vote 必须同时满足：
1. 当前证据中存在明确悬念、疑点、预测点、真假判断点或动机判断点。
2. 用户看完当前证据后，可以立刻进行猜测。
3. 每个选项在当前证据中都像是合理可能，不能为了凑选项制造假冲突。
4. 后续证据中存在明确揭晓答案的内容。
5. reveal_anchor 必须指向当前触发证据之后的 T/O/D，不能指向当前或更早证据。
6. options[0] 必须能被 reveal_anchor 对应证据明确证实。
7. 问题和选项不需要额外解释也能理解。

找不到“当前可猜 + 后续明确揭晓”的组合时，不生成 deferred_vote。

# 生成数量规则
1. 不要因为已有其他 deferred_vote 就跳过合格机会。
2. 不要输出重复表达同一个悬念的 deferred_vote。
3. 如果多个证据机会指向同一个悬念，只保留最适合触发投票的那个。

# 候选筛选原则
优先保留：
1. 当前疑点强、后续答案明确的证据机会。
2. 用户参与感强，投票后会期待揭晓的证据机会。
3. 问题短、选项清晰、不会剧透的证据机会。
4. 与主线冲突、身份反转、真假判断、动机反转相关的证据机会。
5. 证据强度高且确实满足延迟揭晓条件的证据机会。

应当剔除：
1. 悬念过弱，用户不太会想猜的证据机会。
2. 后续只是暗示，没有明确答案的证据机会。
3. 选项之间不够对立，或者有明显凑数感的证据机会。
4. 与其他已输出 deferred_vote 表达同一个悬念的证据机会。
5. 更适合 instant_vote 的证据机会。

# 问题规则
1. question 必须是短问题。
2. question 必须围绕当前证据的悬念、真假、身份、动机或预测点。
3. question 不要写成剧情摘要，不要包含复杂背景解释。
4. question 建议 2 到 16 个字符，标点符号也计入字符数。
5. question 要让用户一眼知道在猜什么，并有短剧互动感。
6. question 不能提前泄露后续答案。
7. question 不要出现“后面会怎样”“等下揭晓”“马上揭晓”等提示性表达。
8. question 不要包含 reveal_anchor 对应证据才揭晓的信息。

# 选项规则
1. options 必须是长度为 2 到 4 的数组，默认优先生成 2 个选项。
2. 只有当当前证据明确支持 3 或 4 种可能时，才允许输出 3 或 4 个选项。
3. 每个选项必须立场明确、方向不同。
4. 不要提供中立选项或“看后续”“不好说”“都可以”“不知道”“再等等”等缓冲选项。
5. 选项建议 1 到 8 个字符。
6. 每个选项必须基于当前证据能直接支持的可能性。
7. 避免选项一强一弱；每个选项都要像用户可能会点的真实猜测。
8. 选项不能提前泄露后续答案。
9. 如果只能生成一个合理选项，不生成 deferred_vote。
10. options[0] 必须是 reveal_anchor 对应证据明确证实的正确选项。
11. options[1] 及之后只能放未被揭晓证据证实的其他合理猜测。

# reveal_anchor 规则
1. reveal_anchor 表示后续明确揭晓答案的 T/O/D 证据。
2. 必须来自当前 evidence_timeline 中真实存在的可见标识。
3. 必须指向当前触发点之后的证据，不能等于触发证据或指向更早证据。
4. 对应证据必须包含明确揭晓答案的内容，而不是暗示。
5. 不要输出 reveal_time、reveal_delay 或其他绝对时间字段。
6. 多个后续证据都涉及揭晓时，选择第一个明确给出答案的证据。
7. 如果 reveal_anchor 对应内容只能提供暗示，不能明确证明答案，不生成 deferred_vote。

# 正确答案规则
1. 生成侧 answer_id 必须固定为 0。
2. options[0] 必须是被 reveal_anchor 对应证据明确证实的选项。
3. 后续证据没有明确证实任何选项时，不生成 deferred_vote。
4. 如果多个选项都可能成立，说明选项设计不合格，应重新设计或不生成。
5. 不要把当前证据中的主观倾向当作最终答案，必须以后续揭晓为准。
6. reveal_time 和 reveal_delay 保持为空，由渲染阶段计算。

# 与 instant_vote 的区分
如果当前证据看完后就可以立刻表达立场，而且不需要后续揭晓答案，应生成 instant_vote，而不是 deferred_vote。
deferred_vote 必须有“先猜测、后揭晓”的结构：当前证据提出可猜测点，后续证据明确揭晓答案。

# payload 字段要求
- payload 必须包含 question、options、answer_id、reveal_time、reveal_delay。
- answer_id 必须为 0。
- reveal_time 和 reveal_delay 必须为 null。
- reveal_anchor 必须指向后续明确揭晓证据。

# reveal_anchor 最终自检
提交工具调用前检查：
1. 当前证据确实存在可猜的悬念、真假、身份、动机或走向疑点。
2. 用户看完当前证据即可先猜，不需要外部知识。
3. options 为 2 到 4 个合理猜测，正确选项在 options[0]。
4. reveal_anchor 来自当前时间线中更晚的真实 T/O/D，并明确证实 options[0]。
5. 问题和选项不提前泄露揭晓，不输出绝对时间。
6. answer_id 为 0，reveal_time 和 reveal_delay 为 null。

# SpecialistResult 提交示例
通过工具提交一条 Candidate 时，payload 形如：
{
  "question": "她可信吗？",
  "options": ["可信", "有问题"],
  "answer_id": 0,
  "reveal_time": null,
  "reveal_delay": null
}

没有“当前可猜 + 后续明确揭晓”的组合时，提交 Abstention。
""".strip(),
        "side_comment": """
你的任务是根据当前证据机会筛选适合“吐槽气泡 / 剧情嘴替”的内容，并完成三件事：
1. 判断哪些证据机会适合生成 side_comment。
2. 为每个入选机会生成一句轻吐槽、站队短评或互动提醒。
3. 输出 payload.text 和必填的 payload.mood。

# side_comment 定义
side_comment 是在重点剧情前后自动弹出的一句轻吐槽、剧情嘴替、站队短评或互动提醒。
它的作用是帮用户先说出那句最想吐槽、最想站队、最想提醒别人看的话。
它不是剧情总结，不是旁白解释，也不是普通弹幕列表；应该像一个懂剧情、懂观众情绪的“嘴替”。

side_comment 适合：
1. 高光前后的轻吐槽：剧情离谱、角色操作迷惑、反差强、观众想吐槽。
2. 站队短评：角色冲突明显，用户容易想站一边。
3. 情绪嘴替：观众会立刻心疼、上头、解气、无语、紧张、磕到。
4. 互动提醒：当前证据适合引导用户点击按钮、投票、接台词或继续关注。
5. 名场面提示：当前证据有明显爆点，适合用一句短话制造记忆点。

side_comment 不适合：
1. 普通信息交代、设定说明、背景介绍。
2. 没有明显情绪出口的过渡证据。
3. 纯动作冲击但没有可吐槽、可站队、可嘴替的内容。
4. 已经适合 repeat_keyline 的强台词，但没有额外吐槽空间。
5. 必须等待后续剧情才能理解的悬念。
6. 需要复杂解释才能看懂的评论。
7. 容易剧透后续内容的评论。

# 生成条件
生成 side_comment 必须同时满足：
1. 当前证据有明确的吐槽点、站队点、情绪点、提醒点或名场面记忆点。
2. payload.text 能像真实观众在观看时冒出的即时反应。
3. payload.text 能帮助用户更快进入剧情情绪，而不是打断理解。
4. payload.text 必须由当前 T/O/D 证据直接支持。
5. payload.text 不依赖后续剧情揭晓才能成立。
6. payload.text 不引入当前证据中没有的新剧情、新关系、新动作或新因果。

以下内容不生成 side_comment：
1. 主要作用是解释设定、补充背景或交代信息。
2. 只有剧情信息量，没有明确吐槽点或情绪出口。
3. 只是承接前后剧情的普通过渡片段。
4. 当前内容太弱，生成出来只会像普通废话。

# 内容类型
side_comment 可以是以下几类，但每个证据机会只输出一句 text：
1. 轻吐槽：适合离谱操作、荒诞反差、欠揍发言、迷惑行为。
2. 站队短评：适合角色冲突、立场对抗、真假争议、行为评价。
3. 情绪嘴替：适合爽点、虐点、危险点、甜点、笑点。
4. 互动提醒：适合当前证据明显可以引导用户互动。
5. 名场面提示：适合强反转、强宣言、打脸、关键承诺、爆点瞬间。

# text 规则
1. payload.text 必须是字符串。
2. text 建议 5 到 18 个字符，标点符号也计入字符数。
3. text 必须短、轻、口语化，有即时观看感。
4. text 要像真实观众顺手发出的吐槽或短评，不要像运营文案。
5. text 可以轻微夸张，但不能改变当前证据呈现的事实。
6. text 不要写成剧情摘要、长句解释或分析结论。
7. text 不要输出“剧情反转”“情绪爆发”“名场面互动”等标签词。
8. 不要过度网络化，不要使用低俗、攻击性、侮辱性或脏话表达。
9. 不要使用“请点击按钮”“请参与互动”等生硬引导语。
10. 互动提醒要自然像观众提醒，例如“这不得点一下？”“快来站队了”。

# 生成数量规则
1. 连续表达同一情绪、同一吐槽点的多个证据不要生成重复评论。
2. 如果多个证据指向同一个吐槽点或情绪点，只保留最适合弹出气泡的那个。

# 候选筛选原则
优先保留：
1. 用户一看就会想吐槽、站队或表达情绪的证据。
2. 有明显反转、冲突、打脸、危险、甜宠、搞笑或离谱点的证据。
3. text 能做到短、准、有记忆点的证据。
4. 能补充 emotion_button、instant_vote、repeat_keyline 之外“嘴替感”的证据。
5. 证据强度较高且确实有互动价值的证据。

应当剔除：
1. 评论写出来只是在复述剧情的证据。
2. 评论必须依赖后续剧情才能成立的证据。
3. 只能写出普通感叹词的证据。
4. 只能写出“太棒了”“好厉害”“真不错”这类泛泛评价的证据。
5. 更适合 repeat_keyline 且原台词已经足够强、不需要额外嘴替的证据。

# mood 规则
mood 必须是以下小写字符串之一，并与当前评论情绪最贴近：
- roast：吐槽、嫌弃、无语或想骂。
- shock：震惊、意外或难以置信。
- laugh：爆笑、荒诞或搞笑。
- praise：点赞、解气或称赞。
- sympathy：心疼、委屈或同情。
- doubt：质疑、怀疑或不信。

# payload 字段要求
- payload 必须且只能包含 text、mood。
- mood 必须是 roast、shock、laugh、praise、sympathy、doubt 之一。

# 最终自检
提交工具调用前检查：
1. text 短、轻、口语化，mood 与文本情绪一致。
2. 评论不重复当前节点更适合的 emotion_button、instant_vote 或 repeat_keyline。

# SpecialistResult 提交示例
通过工具提交一条 Candidate 时，payload 形如：
{
  "text": "这也太敢说了吧！",
  "mood": "roast"
}

没有明确吐槽点、站队点或情绪出口时，提交 Abstention。
""".strip(),
    }
)

SEMANTIC_SCHEDULER_SYSTEM_PROMPT: str = (
    "你是短剧互动语义调度器。只能从给定 candidate_id 中选择保留项，"
    "不能修改互动内容、时间或证据，也不能发明候选。series_context 只用于理解人物和背景，"
    "不能替代候选附带的当前集证据。"
)
SEMANTIC_SCHEDULER_USER_PROMPT_TEMPLATE: str = (
    f"{SERIES_CONTEXT_PROMPT_BLOCK}\n\n"
    """
<scheduler_input>
{{SCHEDULER_INPUT_JSON}}
</scheduler_input>
""".strip()
)


class SettingsError(ValueError):
    """配置缺失或不符合运行约束。"""

    def __init__(self, message: str, *, missing: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.missing = missing


class Settings(BaseModel):
    """不可变的运行配置。

    Attributes:
        llm_model_id: LangChain ChatOpenAI 的模型标识。
        llm_api_key: 模型服务密钥。
        llm_base_url: 模型服务端点。
        checkpoint_database_url: PostgreSQL 检查点连接串。
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )

    # 模型与检查点连接。
    llm_model_id: str
    llm_api_key: str
    llm_base_url: str
    checkpoint_database_url: str

    # LLM 调用参数。
    llm_temperature: float = DEFAULT_LLM_TEMPERATURE
    llm_timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS
    llm_max_tokens: int = DEFAULT_LLM_MAX_TOKENS
    llm_max_retries: int = DEFAULT_LLM_MAX_RETRIES
    llm_retry_delay_seconds: float = DEFAULT_LLM_RETRY_DELAY_SECONDS

    # 调度与渲染参数。
    interaction_budget: int | None = DEFAULT_INTERACTION_BUDGET
    min_interaction_spacing_ms: int | None = DEFAULT_MIN_INTERACTION_SPACING_MS
    type_cooldown_ms: MappingProxyType = Field(
        default_factory=lambda: MappingProxyType(dict(DEFAULT_TYPE_COOLDOWN_MS))
    )
    emotion_button_duration_ms: int = DEFAULT_EMOTION_BUTTON_DURATION_MS
    instant_vote_duration_ms: int = DEFAULT_INSTANT_VOTE_DURATION_MS
    deferred_vote_duration_ms: int = DEFAULT_DEFERRED_VOTE_DURATION_MS
    side_comment_duration_ms: int = DEFAULT_SIDE_COMMENT_DURATION_MS
    keyline_tail_ms: int = KEYLINE_TAIL_MS
    reveal_display_ms: int = DEFAULT_REVEAL_DISPLAY_MS
    reveal_gap_min_ms: int = DEFAULT_REVEAL_GAP_MIN_MS
    min_reported_gap_ms: int = DEFAULT_MIN_REPORTED_GAP_MS

    # 由配置统一声明的产物目录。目录可在运行前不存在，由使用它的阶段创建。
    evidence_dir: Path = Path("data/evidence")
    interaction_v2_dir: Path = Path("data/interaction_v2")
    runs_dir: Path = Path("data/interaction_v2/runs")

    # LangSmith 只用于可选追踪，不影响本地执行。
    langsmith_tracing: bool = False
    langsmith_endpoint: str | None = None
    langsmith_api_key: str | None = None
    langsmith_project: str | None = None

    @field_validator(
        "llm_model_id",
        "llm_api_key",
        "llm_base_url",
        "checkpoint_database_url",
        mode="before",
    )
    @classmethod
    def _require_non_blank(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("必填配置不能为空")
        return value.strip()

    @field_validator("checkpoint_database_url")
    @classmethod
    def _require_postgresql_url(cls, value: str) -> str:
        if not value.lower().startswith("postgresql://"):
            raise ValueError("CHECKPOINT_DATABASE_URL 必须以 postgresql:// 开头")
        return value

    @field_validator("llm_temperature")
    @classmethod
    def _validate_temperature(cls, value: float) -> float:
        if isinstance(value, bool) or not 0 <= value <= 2:
            raise ValueError("llm_temperature 必须在 0 到 2 之间")
        return value

    @field_validator("llm_timeout_seconds")
    @classmethod
    def _validate_timeout(cls, value: float) -> float:
        if isinstance(value, bool) or value <= 0:
            raise ValueError("llm_timeout_seconds 必须为正数")
        return value

    @field_validator("llm_max_tokens")
    @classmethod
    def _validate_max_tokens(cls, value: int) -> int:
        if isinstance(value, bool) or value <= 0:
            raise ValueError("llm_max_tokens 必须为正整数")
        return value

    @field_validator("llm_max_retries")
    @classmethod
    def _validate_retries(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("llm_max_retries 必须为非负整数")
        return value

    @field_validator("llm_retry_delay_seconds")
    @classmethod
    def _validate_retry_delay(cls, value: float) -> float:
        if isinstance(value, bool) or value < 0:
            raise ValueError("llm_retry_delay_seconds 必须为非负数")
        return value

    @field_validator("interaction_budget")
    @classmethod
    def _validate_budget(cls, value: int | None) -> int | None:
        if value is not None and (isinstance(value, bool) or value <= 0):
            raise ValueError("interaction_budget 若配置必须为正整数")
        return value

    @field_validator("min_interaction_spacing_ms")
    @classmethod
    def _validate_spacing(cls, value: int | None) -> int | None:
        if value is not None and (isinstance(value, bool) or value <= 0):
            raise ValueError("min_interaction_spacing_ms 若配置必须为正整数")
        return value

    @field_validator(
        "emotion_button_duration_ms",
        "instant_vote_duration_ms",
        "deferred_vote_duration_ms",
        "side_comment_duration_ms",
        "min_reported_gap_ms",
    )
    @classmethod
    def _validate_positive_ms(cls, value: int) -> int:
        if isinstance(value, bool) or value <= 0:
            raise ValueError("时长与阈值必须为正整数")
        return value

    @field_validator("keyline_tail_ms", "reveal_display_ms", "reveal_gap_min_ms")
    @classmethod
    def _validate_non_negative_ms(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("时长参数必须为非负整数")
        return value

    @field_validator("type_cooldown_ms", mode="before")
    @classmethod
    def _validate_and_freeze_cooldowns(cls, value: Any) -> Mapping[str, int]:
        if value is None:
            return MappingProxyType({})
        if isinstance(value, str):
            value = _parse_cooldown_value(value)
        if not isinstance(value, Mapping):
            raise ValueError("type_cooldown_ms 必须是映射")

        parsed: dict[str, int] = {}
        for key, raw_value in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("type_cooldown_ms 的类型名不能为空")
            parsed[key.strip()] = _parse_int_value(
                raw_value, f"type_cooldown_ms[{key!r}]", minimum=0
            )
        return MappingProxyType(parsed)

    @field_validator("evidence_dir", "interaction_v2_dir", "runs_dir", mode="before")
    @classmethod
    def _validate_path(cls, value: Any) -> Path:
        if isinstance(value, Path):
            path = value
        elif isinstance(value, str) and value.strip():
            path = Path(value.strip())
        else:
            raise ValueError("路径配置不能为空")
        if "\x00" in str(path):
            raise ValueError("路径配置不能包含 NUL 字符")
        return path

    @model_validator(mode="after")
    def _validate_invariants(self) -> Settings:
        if self.min_interaction_spacing_ms is not None:
            max_duration = max(
                self.emotion_button_duration_ms,
                KEYLINE_DURATION_CEIL,
                self.instant_vote_duration_ms,
                self.deferred_vote_duration_ms,
                self.side_comment_duration_ms,
            )
            if self.min_interaction_spacing_ms < max_duration:
                raise ValueError(
                    "min_interaction_spacing_ms 不能小于互动展示时长最大值 "
                    f"{max_duration}"
                )
        return self


_ENV_TO_FIELD: dict[str, str] = {
    "LLM_MODEL_ID": "llm_model_id",
    "LLM_API_KEY": "llm_api_key",
    "LLM_BASE_URL": "llm_base_url",
    "CHECKPOINT_DATABASE_URL": "checkpoint_database_url",
    "LLM_TEMPERATURE": "llm_temperature",
    "LLM_TIMEOUT_SECONDS": "llm_timeout_seconds",
    "LLM_MAX_TOKENS": "llm_max_tokens",
    "LLM_MAX_RETRIES": "llm_max_retries",
    "LLM_RETRY_DELAY_SECONDS": "llm_retry_delay_seconds",
    "INTERACTION_BUDGET": "interaction_budget",
    "MIN_INTERACTION_SPACING_MS": "min_interaction_spacing_ms",
    "TYPE_COOLDOWN_MS": "type_cooldown_ms",
    "EMOTION_BUTTON_DURATION_MS": "emotion_button_duration_ms",
    "INSTANT_VOTE_DURATION_MS": "instant_vote_duration_ms",
    "DEFERRED_VOTE_DURATION_MS": "deferred_vote_duration_ms",
    "SIDE_COMMENT_DURATION_MS": "side_comment_duration_ms",
    "KEYLINE_TAIL_MS": "keyline_tail_ms",
    "REVEAL_DISPLAY_MS": "reveal_display_ms",
    "REVEAL_GAP_MIN_MS": "reveal_gap_min_ms",
    "MIN_REPORTED_GAP_MS": "min_reported_gap_ms",
    "EVIDENCE_DIR": "evidence_dir",
    "INTERACTION_V2_DIR": "interaction_v2_dir",
    "RUNS_DIR": "runs_dir",
    "LANGSMITH_TRACING": "langsmith_tracing",
    "LANGSMITH_ENDPOINT": "langsmith_endpoint",
    "LANGSMITH_API_KEY": "langsmith_api_key",
    "LANGSMITH_PROJECT": "langsmith_project",
}

_FIELD_TO_ENV = {field: env_name for env_name, field in _ENV_TO_FIELD.items()}

_REQUIRED_FIELDS = (
    "llm_model_id",
    "llm_api_key",
    "llm_base_url",
    "checkpoint_database_url",
)


def _parse_int_value(value: Any, name: str, *, minimum: int | None = None) -> int:
    """解析整数配置并拒绝布尔值、小数和空值。"""

    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为整数")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed = int(text)
        except ValueError as exc:
            raise ValueError(f"{name} 必须为整数，收到 {value!r}") from exc
        if str(parsed) != text and not (text.startswith("+") and str(parsed) == text[1:]):
            raise ValueError(f"{name} 必须为整数，收到 {value!r}")
    else:
        raise ValueError(f"{name} 必须为整数")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} 必须大于等于 {minimum}")
    return parsed


def _parse_float_value(value: Any, name: str) -> float:
    """解析浮点配置。"""

    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数字")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为数字，收到 {value!r}") from exc
    return parsed


def _parse_bool_value(value: Any, name: str) -> bool:
    """解析常见布尔环境变量写法。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{name} 必须是 true/false")


def _parse_cooldown_value(value: str) -> Mapping[str, Any]:
    """解析 JSON 冷却映射。"""

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("TYPE_COOLDOWN_MS 必须是 JSON 对象") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("TYPE_COOLDOWN_MS 必须是 JSON 对象")
    return parsed


def _normalize_overrides(
    overrides: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """统一显式覆盖的字段名，支持环境变量名和 Python 字段名。"""

    merged: dict[str, Any] = {}
    for key, value in (overrides or {}).items():
        field_name = _ENV_TO_FIELD.get(key, key)
        if field_name not in _FIELD_TO_ENV and field_name not in _REQUIRED_FIELDS:
            raise SettingsError(f"未知配置覆盖: {key}")
        merged[field_name] = value
    return merged


def _resolve_value(
    field_name: str,
    overrides: Mapping[str, Any],
    environment: Mapping[str, str],
    dotenv_data: Mapping[str, Any],
) -> Any:
    """按显式覆盖、进程环境和 dotenv 读取字段。"""

    if field_name in overrides:
        return overrides[field_name]
    env_name = _FIELD_TO_ENV[field_name]
    if env_name in environment:
        return environment[env_name]
    if env_name in dotenv_data and dotenv_data[env_name] is not None:
        return dotenv_data[env_name]
    return None


def _coerce_loaded_value(field_name: str, value: Any) -> Any:
    """将字符串环境值转换为 Settings 需要的基础类型。"""

    if field_name in {"llm_temperature", "llm_timeout_seconds", "llm_retry_delay_seconds"}:
        return _parse_float_value(value, field_name)
    if field_name in {
        "llm_max_tokens",
        "llm_max_retries",
        "interaction_budget",
        "min_interaction_spacing_ms",
        "emotion_button_duration_ms",
        "instant_vote_duration_ms",
        "deferred_vote_duration_ms",
        "side_comment_duration_ms",
        "keyline_tail_ms",
        "reveal_display_ms",
        "reveal_gap_min_ms",
        "min_reported_gap_ms",
    }:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return _parse_int_value(value, field_name)
    if field_name == "type_cooldown_ms" and isinstance(value, str):
        return _parse_cooldown_value(value)
    if field_name == "langsmith_tracing":
        return _parse_bool_value(value, field_name)
    if field_name in {"langsmith_endpoint", "langsmith_api_key", "langsmith_project"}:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return str(value).strip()
    if field_name in {"evidence_dir", "interaction_v2_dir", "runs_dir"}:
        return Path(value) if not isinstance(value, Path) else value
    if isinstance(value, str):
        return value.strip()
    return value


def load_settings(
    overrides: Mapping[str, Any] | None = None,
    *,
    env_file: str | os.PathLike[str] | None = ".env",
) -> Settings:
    """加载并校验运行配置。

    Args:
        overrides: 命令行或调用方提供的显式字段覆盖。
        env_file: 可选 dotenv 文件；传 ``None`` 可禁用读取。

    Returns:
        已冻结的 ``Settings`` 对象。

    Raises:
        SettingsError: 必填项缺失、覆盖未知或配置不合法。
    """

    normalized_overrides = _normalize_overrides(overrides)
    dotenv_data: Mapping[str, Any] = {}
    if env_file is not None:
        dotenv_data = dotenv_values(Path(env_file))

    resolved: dict[str, Any] = {}
    for field_name in _FIELD_TO_ENV:
        value = _resolve_value(
            field_name,
            normalized_overrides,
            os.environ,
            dotenv_data,
        )
        if value is not None:
            try:
                # 外部配置先统一转换，再交给 Settings 做字段与跨字段校验。
                resolved[field_name] = _coerce_loaded_value(field_name, value)
            except (TypeError, ValueError) as exc:
                env_name = _FIELD_TO_ENV[field_name]
                raise SettingsError(f"配置 {env_name} 无效: {exc}") from exc

    missing: list[str] = []
    for field_name in _REQUIRED_FIELDS:
        value = resolved.get(field_name)
        if not isinstance(value, str) or not value.strip():
            missing.append(_FIELD_TO_ENV[field_name])
    if missing:
        names = ", ".join(missing)
        raise SettingsError(f"缺少必填配置: {names}", missing=tuple(missing))

    try:
        return Settings(**resolved)
    except ValidationError as exc:
        raise SettingsError(f"配置校验失败: {exc}") from exc


__all__ = [
    "DEFAULT_DEFERRED_VOTE_DURATION_MS",
    "DEFAULT_DRAMA_INFO_PATH",
    "DEFAULT_EMOTION_BUTTON_DURATION_MS",
    "DEFAULT_INSTANT_VOTE_DURATION_MS",
    "DEFAULT_INTERACTION_BUDGET",
    "DEFAULT_LLM_MAX_TOKENS",
    "DEFAULT_LLM_MAX_RETRIES",
    "DEFAULT_LLM_RETRY_DELAY_SECONDS",
    "DEFAULT_LLM_TEMPERATURE",
    "DEFAULT_LLM_TIMEOUT_SECONDS",
    "DEFAULT_MIN_INTERACTION_SPACING_MS",
    "DEFAULT_MIN_REPORTED_GAP_MS",
    "DEFAULT_REVEAL_DISPLAY_MS",
    "DEFAULT_REVEAL_GAP_MIN_MS",
    "DEFAULT_SIDE_COMMENT_DURATION_MS",
    "DEFAULT_TYPE_COOLDOWN_MS",
    "DEFERRED_VOTE_MAX_OPTIONS",
    "DEFERRED_VOTE_MIN_OPTIONS",
    "INSTANT_VOTE_OPTIONS_COUNT",
    "KEYLINE_DURATION_CEIL",
    "KEYLINE_DURATION_FLOOR",
    "KEYLINE_TAIL_MS",
    "Settings",
    "SettingsError",
    "SERIES_CONTEXT_PROMPT_BLOCK",
    "SPECIALIST_FOCUS_PROMPTS",
    "SPECIALIST_REGENERATION_PROMPT_TEMPLATE",
    "SPECIALIST_SYSTEM_PROMPT",
    "SPECIALIST_USER_PROMPT_TEMPLATE",
    "SEMANTIC_SCHEDULER_SYSTEM_PROMPT",
    "SEMANTIC_SCHEDULER_USER_PROMPT_TEMPLATE",
    "load_settings",
]
