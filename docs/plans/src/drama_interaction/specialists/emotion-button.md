# src/drama_interaction/specialists/（五类型模块）内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-001 / 008、PRD §3.1 / §9、docs/schema.md
- 覆盖文件：情绪按钮(emotion_button).py（代表）与同构的 跟读金句(repeat_keyline).py / 即时投票(instant_vote).py / 延时投票(deferred_vote).py / 边看边聊(side_comment).py

## 职责与边界

- 每个类型模块只做本类型的事：类型职责定义（提示词(Prompt)要素方向）、载荷(payload)生成要求、类型特有的 弃权(abstain)判断倾向。
- 公共骨架（输入组装、大语言模型(LLM)调用、解析、弃权(abstain)通道、单条修复入口）全部复用 base.py，类型模块不重复实现。
- 明确不做：
  - 不做跨类型取舍（调度器(Scheduler)的事）。
  - 不做确定性校验（rules.py 的事，类型模块只声明「需要哪些校验」）。
  - 不写成文 提示词(Prompt)（Deferred，PRD §22 第 3 项）。

## 依赖关系

- 依赖：
  - specialists/base.py（骨架）
  - schemas/candidate.py（结果结构）
  - schemas/interaction.py（本类型 载荷(payload)定义）
- 被依赖方：graph/nodes.py（每类一个节点，静态并行）、validation/repair.py（定向退回调用本模块的单条修复入口）。

## 主要组成（以 emotion_button.py 为主体描述单模块结构）

- 类型职责描述：识别适合「情绪表达按钮」的时刻（打脸、强势宣言、搞笑反差、危险受伤、虐点委屈、甜宠暧昧等 button_id 适用场景），绑定证据(Evidence)锚点(Anchor)并生成 按钮(button)载荷(payload)。
- 类型 提示词(Prompt)要素方向（不写成文）：
  - 本类型适用场景与 button_id 映射表。
  - 输出契约（专家结果(SpecialistResult)结构与锚点(Anchor)纪律）。
  - 当前集事实必须由当前集 证据(Evidence)支撑（ADR-010）。
  - 何时应 弃权(abstain)。
- 载荷(payload)生成要求：button_id 从 0-5 中选择；文本(text) / 弹幕(danmaku)的可选性按 button_id 约束（schema.md）。
- 类型声明的校验需求：button_id 合法性、文本(text)/弹幕(danmaku)可选性、锚点(Anchor)合法性——由 rules.py 统一实施。

## 五类型对照

| 维度 | 情绪按钮(emotion_button) | 跟读金句(repeat_keyline) | 即时投票(instant_vote) | 延时投票(deferred_vote) | 边看边聊(side_comment) |
|------|----------------|----------------|--------------|---------------|--------------|
| 载荷(payload)核心字段 | button_id 0-5（+可选 文本(text)/弹幕(danmaku)） | 文本(text)（一句台词） | 题干(question) + 2 选项 | 题干(question) + 2-4 选项 + answer_id + reveal 毫秒字段 | 文本(text)（+mood 未来字段） |
| 适合的 证据(Evidence)特征 | 情绪浓度高的时刻（打脸/搞笑/危险/虐点/撒糖） | 值得用户跟读复述的金句台词（台词文本(transcript)级锚点(Anchor)） | 有明确对立两方的即时冲突站队 | 剧情抛出、答案未揭晓的问题（需存在后续揭晓位置） | 适合旁白吐槽的反差、离谱、敢说时刻 |
| 特有校验点 | button_id 与 文本(text)/弹幕(danmaku)可选性匹配 | 金句台词(keyline)文本必须能在 台词文本(transcript)中找到（防编造台词，V1 经验沿用） | 选项恰 2 个 | reveal_anchor 必须晚于 触发(trigger)；answer_id 为 options 合法索引；reveal_time/reveal_delay 由渲染环节生成（ADR-023），生成侧禁填（必须为 null），揭晓(reveal)位置由 reveal_anchor 承载 | 无特殊结构校验，重点在内容 实据(grounding) |
| 弃权(abstain)倾向 | 场景匹配不上任一 button_id 时 | 找不到「金句级」台词时 | 冲突对立不明确时 | 找不到可信的后续揭晓位置时（宁缺勿滥） | 证据(Evidence)不足以支撑吐槽内容时 |
| 常见误用风险 | 情绪场景泛化滥用、button_id 与场景错配 | 把普通台词当金句；金句台词(keyline)与 台词文本(transcript)不一致 | 问题引导性过强、选项不对立 | 泄露未来剧情；揭晓(reveal)位置找错 | 吐槽内容无证据(Evidence)支撑、剧透 |

## 关键设计点

- 五类完全同构于 base 骨架，类型模块是「职责 + 提示词(Prompt)要素 + 载荷(payload)」的差异化薄层（ADR-008 的物理落地）。
- 延时投票(deferred_vote)是唯一带 reveal_anchor 的类型，也是唯一与「未来位置」耦合的类型，其「找不到揭晓(reveal)位置就 弃权(abstain)」的纪律要写进 提示词(Prompt)要素。
- 延时投票(deferred_vote)生成侧 载荷(payload)只含 题干(question) / options / answer_id（ADR-011 的落实），毫秒时间字段一律由渲染环节生成、生成侧禁填（见 ADR-023），生成专家(Specialist)不输出任何毫秒值。
- 类型间不通信、不感知彼此输出——类型冲突完全交给调度层（ADR-001 的 Consequences）。
- 每类输出的 专家结果(SpecialistResult)经分支内校验后入池，candidate_id 由程序赋值，类型模块不生成 标识(ID)。

## 待定项

- 各类型 提示词(Prompt)的最终 wording（Deferred，PRD §22 第 3 项）。
- 跟读金句(repeat_keyline)的「金句」判定标准与 金句台词(keyline)匹配的严格程度（精确匹配 / 归一化匹配）：待 rules.py 冻结。
- 纯窗口锚下 金句台词(keyline)时长退化（已接受为预期行为）：
  - 无 transcript_segment_id 时 duration_ms 退化为常数 clamp(3000+700, 2500, 4500)=3700。
  - 不强制 跟读金句(repeat_keyline)带 transcript_segment_id。
  - 基准评测(benchmark)阶段统计纯窗口锚 金句台词(keyline)占比，用数据决定是否加约束，不预先加。
- 边看边聊(side_comment)的 mood 取值词表：未来字段，暂不定。

## 测试要点

- 每类型模块用假 大语言模型(LLM)响应测试：合法 候选(candidate)生成、弃权(abstain)-only 输出、载荷(payload)与类型不匹配时被拒绝。
- 延时投票(deferred_vote)的 reveal_after_trigger 场景与 金句台词(keyline)的 台词文本(transcript)匹配场景与 rules.py 联测。
- 五模块与 graph 并行节点的集成冒烟（假 大语言模型(LLM)）。
