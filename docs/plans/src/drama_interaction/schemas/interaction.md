# src/drama_interaction/schemas/interaction.py 内容规划

- 状态：规划中（未实现）
- 上游依据：docs/schema.md（核心依据）、ADR-017、PRD §17、README_v2.md「使用」节

## 职责与边界

- 定义播放器最终消费的五类互动输出契约：最终互动(FinalInteraction)外壳与五类 载荷(payload)的字段及约束。
- 作为 载荷(payload)字段定义的单一来源，candidate.py 引用本文件（生成专家(Specialist)输出侧与最终输出侧不重复定义）。
- 明确不做：无 输入输出(IO)、无 大语言模型(LLM)；不做锚点→毫秒换算（ADR-023 已定稿，职责在渲染环节）；类型(type)数字映射沿用 V1 的 1–5（schemas/interaction.py 为唯一权威）。

## 依赖关系

- 零内部依赖（除被 candidate.py 引用外），仅依赖 pydantic。
- 被依赖方：
  - schemas/candidate.py（载荷(payload)校验规则的对象）
  - validation/rules.py（载荷(payload)校验规则的对象）
  - scheduling（终检对象）
  - graph（final_check / 渲染导出节点）
  - cli（导出(export)落盘格式）

## 主要组成

- 外壳结构（schema.md）：

```text
FinalInteraction
├─ id             # 最终输出内自增序号
├─ type           # 数字，五类各一个固定值
├─ show_at        # 毫秒；ADR-023：resolve_anchor(trigger).start
├─ duration_ms    # 毫秒；ADR-023：类型时长表（repeat_keyline 取锚区间+tail）
└─ payload        # 五类之一
```

- 五类 载荷(payload)结构（schema.md 定义，本文件落地约束）：
  - 情绪按钮(emotion_button)：button_id 取 0-5（爽/笑/丢番茄/护住TA/心疼TA/磕到了）；文本(text)与 弹幕(danmaku)的可选性随 button_id 不同（如笑/护住TA/心疼TA 无 文本(text)，护住TA/心疼TA 无 弹幕(danmaku)），按 button_id 条件校验。
  - 跟读金句(repeat_keyline)：文本(text)必填（被用户跟读的台词）。
  - 即时投票(instant_vote)：题干(question)必填；options 恰好 2 个元素。
  - 延时投票(deferred_vote)：题干(question)必填；options 2-4 个元素；reveal_time? / reveal_delay? 毫秒字段（可空；生成侧禁填，必须为 null，由渲染环节赋值）；answer_id 必须是 options 的合法索引。
  - 边看边聊(side_comment)：文本(text)必填；mood 为未来字段（本轮可定义但标注未启用）。
- 字符串类型 ↔ 类型(type)数字的映射表：映射结构在本文件定义（唯一权威）。
  - 数值已定：情绪按钮(emotion_button)=1 / 跟读金句(repeat_keyline)=2 / 即时投票(instant_vote)=3 / 延时投票(deferred_vote)=4 / 边看边聊(side_comment)=5。
  - 出处：v1/pipline/common/schemas.py:248-252（V1 既有约定，沿用）。

## 关键设计点

- 四个毫秒字段（show_at / duration_ms / reveal_time / reveal_delay）的产生规则已定稿，权威见 ADR-023。
  - schema 只定义字段与取值范围合法性（非负整数）。
  - 换算职责在渲染环节（resolve_anchor + 类型时长表）。
  - 渲染环节位于 候选池(Candidate Pool)之后、确定性约束处理之前。
- answer_id 与 options 的对应关系在结构层校验（索引合法）；「正确答案」的语义判定（揭晓时哪个选项为真）是 生成专家(Specialist)生成侧的责任，rules.py 只查索引合法性。
- 五类互动固定不增不减（PRD §3.1）；episode_comment 不在本契约内。
- 标识(id)为最终数组内自增序号，与 candidate_id 是两个体系（后者是内部追踪 标识(ID)，PRD §14 的输出追踪通过内部状态保留映射）。

## 待定项

- 时长表具体数值（基准评测(benchmark)调参后冻结）：
  - 情绪按钮(emotion_button) 2500–3000 / votes 3500–4000 / 边看边聊(side_comment) 2500–3000。
  - 跟读金句(repeat_keyline)专属上下限为代码常量 KEYLINE_DURATION_FLOOR=2500 / KEYLINE_DURATION_CEIL=4500（不进 config，与 keyline_tail_ms 同待遇）。
  - 其余四类直接取 type_base，无 clamp。
  - 运行期 type_base 为每类单一标量；开发期未冻结时默认取区间下限，保证渲染确定性。
- 边看边聊(side_comment)的 mood 字段本轮是否出现在 schema（倾向预留字段 + 校验跳过）。

## 测试要点

- 全部可完全离线测试：五类 载荷(payload)各自的合法样例通过；即时投票(instant_vote)选项数≠2、延时投票(deferred_vote)选项数越界、answer_id 越界、button_id 与 文本(text)/弹幕(danmaku)可选性冲突等违规逐一报错。
- 毫秒字段负数报错。
- 与 schema.md 逐字段核对的一致性用测试固化（防文档与实现漂移）。
