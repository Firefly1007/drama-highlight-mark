# src/drama_interaction/schemas/evidence.py 内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-002 / 003 / 004 / 006、PRD §6、PRD §6.2

## 职责与边界

- 定义 共享(Shared)证据(Evidence)的全部数据结构：证据窗口(EvidenceWindow)及其子结构。
- 提供结构层校验（模型 validators），保证「落盘即合法」：凡是通过本 schema 构造的 证据(Evidence)，自动满足窗口纪律。
- 明确不做：无 输入输出(IO)（落盘在 适配器(adapter)）、无 大语言模型(LLM)、无任何剧情解释字段（ADR-002）、不含 集(episode)级元数据（PRD §6.2：属于 工作流状态(Workflow State)）。

## 依赖关系

- 零内部依赖（地基模块），仅依赖 pydantic。
- 被依赖方：
  - evidence/adapter.py（构造与落盘）
  - evidence/service.py（桩实现(stub)返回证据）
  - specialists/base.py（文本化渲染输入）
  - validation/rules.py（引用校验的查询结构）
  - graph/state.py（状态(State)内嵌 证据窗口(EvidenceWindow)[]）

## 主要组成

数据结构（字段树沿用 PRD §6.4 v0.1，不增不减）：

```text
EvidenceWindow
├─ window_id
├─ start_ms
├─ end_ms
├─ transcript_segments[]
│  ├─ id
│  ├─ start_ms
│  ├─ end_ms
│  ├─ text
│  └─ speaker_label?        # str | null，匿名标签
├─ onscreen_text_segments[]
│  ├─ start_ms
│  ├─ end_ms
│  └─ text
├─ visual_observations[]    # 纯 text 条目，无时间字段
├─ audio_observations[]     # 纯 text 条目，无时间字段
└─ uncertainty[]
```

- 校验器（构造期强制）：
  - 窗口纪律：除末窗外 start_ms / end_ms 差值等于 window_size_ms；末窗 end 不超过其序号边界（允许短于 window_size_ms）、边界按窗口序号对齐、跨整集的窗口序列 window_id 连续且不重叠（序列级校验，作用于列表整体）。
  - 跨窗复制纪律：同一段 台词文本(transcript)出现在多个窗口时，id / start_ms / end_ms / text / speaker_label 必须完全一致（ADR-004 的「同一证据对象」）。
  - 客观性纪律：visual / audio 观察(observation)条目只有文本字段，结构上不存在毫秒字段（ADR-006 在类型层面的落实）；台词文本(transcript)保留精细时间。
  - speaker_label 可空，不要求映射真实角色名（ADR-005）。
- 序列化约定：落盘文件内容即 `list[EvidenceWindow]` 的 JSON（根节点直接是数组，无包裹对象，PRD §6.2）；本模块只定义结构，读写动作在 适配器(adapter)。

## 关键设计点

- 客观性是类型层面的强制而不是口头约定：观察(observation)条目想带时间戳在构造期直接报错（ADR-002/006）。
- 「同一证据对象」靠 标识(id)一致性保证，不做引用仓库、不建立解引用层（ADR-004）。
- 集(episode)元数据（剧名、集名）不进本 schema，由路径与 工作流状态(Workflow State)承载，人工校正回流 黄金(golden)时文件可直接当契约数据使用。
- 固定窗口是组织 / 检索 / 验证单位，不是精确事件时间（ADR-003）：schema 不提供任何「窗口内事件精确时刻」的表达。

## 待定项

- 不确定性(uncertainty)条目的结构：v0.1 只定为文本列表还是带来源标注的结构（V1 的 片段(segment)级 不确定性(uncertainty)如何落到窗口级，见 适配器(adapter)规划的待定项）。
- 序列级校验（连续性、跨窗一致）放在模型 validators 还是独立校验函数：倾向后者（列表级约束不适合单对象 validator），实现时定。

## 测试要点

- 全部可完全离线测试：合法样例构造通过；违规构造（窗口重叠、标识(id)不连续、跨窗复制字段不一致、observation 带时间字段）逐一报错。
- 序列化 round-trip：落盘格式与读回构造一致。
- 边界样例：断言末窗允许短于 3 秒、其余窗口必须等于 3 秒（window_size_ms）；空窗口（无任何内容的窗口是否合法存在，与 适配器(adapter)对齐）。
