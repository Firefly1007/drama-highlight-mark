# src/drama_interaction/schemas/candidate.py 内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-011 / 012 / 013、PRD §9.4 / §9.5 / §9.6

## 职责与边界

- 定义 生成专家(Specialist)输出侧的全部数据结构：触发锚点(TriggerAnchor)、揭晓锚点(RevealAnchor)、候选(Candidate)、弃权(Abstention)、专家结果(SpecialistResult)。
- 定义 candidate_id 的「程序后赋值」约定在 schema 上的表达。
- 明确不做：
  - 无 输入输出(IO)、无 大语言模型(LLM)。
  - 不定义五类 载荷(payload)的内部字段（单一来源在 schemas/interaction.py，本文件引用）。
  - 不做任何时间换算（锚点→毫秒由渲染环节负责，ADR-023 已定稿）。

## 依赖关系

- 依赖：
  - schemas/interaction.py（载荷(payload)结构定义）
  - schemas/evidence.py（校验时需对照 证据窗口(EvidenceWindow)，但仅运行期传入，不做类型耦合）
- 被依赖方：
  - specialists/base.py（大语言模型(LLM)输出解析为 专家结果(SpecialistResult)）
  - specialists 五类型模块（载荷(payload)构造）
  - validation/rules.py（校验对象）
  - validation/repair.py（修复与退回对象）
  - scheduling 两模块（选择对象）
  - graph/state.py（池(Pool)与结果容器）

## 主要组成

```text
TriggerAnchor
├─ window_id                # 必填
└─ transcript_segment_id?   # 可选；有明确台词时引用，纯视觉/音频锚整个窗口

RevealAnchor                # 仅 deferred_vote；结构与 TriggerAnchor 同类
├─ window_id
└─ transcript_segment_id?

Candidate
├─ candidate_id?            # LLM 输出时为空；程序入 Candidate Pool 时赋值
├─ specialist_type          # 五类之一，来源标记
├─ evidence_window_ids[]    # 该候选依据的全部窗口
├─ trigger_anchor
├─ payload                  # 引用 schemas/interaction.py 的五类结构
│                           # deferred_vote 的 reveal_time / reveal_delay 生成侧必须为 null（渲染赋值）
│                           # 揭晓位置由 reveal_anchor 承载——LLM / Specialist 侧零毫秒
└─ reveal_anchor?           # 仅 deferred_vote

Abstention
├─ specialist_type
└─ reason                   # 离散化描述：可能有机会但证据不足以安全生成

SpecialistResult
├─ specialist_type
├─ candidates[]
└─ abstentions[]
```

- 约束表达：trigger_anchor.window_id 必填；reveal_anchor 与类型绑定（只有 延时投票(deferred_vote)允许且要求存在——类型级条件校验）。
- 全结构无 置信度(confidence) / 概率(probability) / 评分(score)字段（ADR-012 在类型层面的落实）；弃权(abstain)是离散状态而非数值（PRD §9.6）。

## 关键设计点

- candidate_id 的生命周期：大语言模型(LLM)永不生成 标识(ID)（PRD §9.4），schema 上为可空字段 + 约定「入 池(Pool)时由程序赋值」，此后全链路（调度、人工介入(HITL)、输出追踪、可观测性）以该 标识(ID)为准（PRD §14）。
- 载荷(payload)单一来源：五类 载荷(payload)的字段定义只在 schemas/interaction.py，candidate.py 引用之——避免 生成专家(Specialist)输出侧与最终输出侧两处定义漂移。
- 延时投票(deferred_vote)的 reveal_time / reveal_delay 在生成侧必为 null（渲染环节赋值）。
  - 揭晓位置由 候选(Candidate).reveal_anchor（window_id + 可选 transcript_segment_id）承载。
  - 大语言模型(LLM) / 生成专家(Specialist)侧一律不输出毫秒。
- 锚点只有「窗口级」与「台词片段(transcript segment)级」两种合法引用，不存在第三种时间表达（ADR-011）。
- 专家结果(SpecialistResult)是分支间数据交换的完整单元，分支失败时不产生该结构（由 状态(State)层记录失败状态），保证 池(Pool)只接收完整合法结果。

## 待定项

- 弃权(abstention).reason 是否需要受控词表（供 基准评测(benchmark)分型统计）：倾向受控枚举 + 自由文本补充，数值待 生成专家(Specialist)提示词(Prompt)冻结时定。
- evidence_window_ids 与 trigger_anchor.window_id 的关系是否要求后者必在前者中（倾向要求，交 rules.py 强制，schema 上不重复约束）。

## 测试要点

- 全部可完全离线测试：合法 候选(candidate)构造通过；window_id 缺失、载荷(payload)类型与 specialist_type 不匹配、非 延时投票(deferred_vote)带 reveal_anchor 等违规逐一报错。
- candidate_id 为空合法、赋值后不可再改的约定可测。
- 反向验证：任何构造路径都产不出带 置信度(confidence)类字段的结构。
