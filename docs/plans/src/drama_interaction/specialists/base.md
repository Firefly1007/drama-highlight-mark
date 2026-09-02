# src/drama_interaction/specialists/base.py 内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-008 / 009 / 010 / 012、PRD §5 / §9（§9.1–9.6）

## 职责与边界

- 五类 生成专家(Specialist)的公共骨架：输入组装、提示词(Prompt)组装、大语言模型(LLM)调用、输出解析、弃权(abstain)通道。
- 明确不做：不做类型特有逻辑（五类型模块各自实现）；不做节点编排（graph/nodes.py）；不做确定性校验与修复（validation/）；不做任何 置信度(confidence) / 评分(score)表达（ADR-012）。

## 依赖关系

- 依赖：
  - schemas/candidate.py（专家结果(SpecialistResult)）
  - schemas/evidence.py（渲染输入）
  - llm.py（调用）
  - evidence/service.py（inspect_window 工具注入）
  - config.py（static_context 与参数）
- 被依赖方：
  - 五个类型模块（继承/复用骨架）
  - graph/nodes.py（节点调用入口）
  - validation/repair.py（定向退回时复用「单条修复」入口）

## 主要组成

- SpecialistInput 组装：
  - static_context：剧名、角色表、简介（PRD §5），来自 config / 输入元数据；定位为身份与专名理解背景，并在 提示词(Prompt)中声明「当前集事实必须由当前集 证据(Evidence)支撑」（ADR-010）。
  - evidence_windows：整集 证据窗口(EvidenceWindow)[] 的文本化渲染——按窗口顺序渲染，显式保留 window_id 与 台词片段(transcript segment)标识(id)，使模型输出的 锚点(Anchor)可回指；台词文本(transcript)跨窗复制项按同 标识(id)去重展示（展示层去重，不改动数据）。
- 公共执行流程：组 提示词(Prompt)（system：类型职责 + 输出契约；user：静态上下文(Static Context) + 证据(Evidence)渲染）→ llm.py 调用 → JSON 解析 → 构造 专家结果(SpecialistResult)。
- 输出解析与失败分类：解析失败 / 结构不合法时产出结构化错误（含原始返回），上抛给分支校验/修复层处理——本层不悄悄整集重试。
- 弃权(abstain)通道：专家结果(SpecialistResult).abstentions[] 的构造支持；语义为「可能存在机会但证据(Evidence)不足以安全生成」（PRD §9.6），不与 置信度(confidence)混淆。
- inspect_window 注入：工具以受控接口传入（本轮为 evidence/service.py 的 桩实现(stub)），生成专家(Specialist)的中间取证请求经 base 记录审计。
- 防呆注记：本轮刻意**不在** 提示词(Prompt)要素中声明「inspect_window 本轮不可用」。
  - 需观测模型真实调用行为（触发场景 / 频次 / 题干(question)质量 / 收到不可用后继续 / 重试 / 弃权(abstain)的比例）。
  - 理由：提示词(Prompt)预告会使模型不再调用、观测样本归零；后续维护者不得「顺手补上」该声明，以免摧毁唯一观测样本。
- 单条修复入口（供 修复(Repair)定向退回）：接收「原 候选(candidate) + 结构化错误 + 必要局部 证据(Evidence)」，只重新生成这一条 候选(candidate)，不重新扫描整集（ADR-014）。

## 关键设计点

- 「找点 + 生成」一次完成（ADR-008）：提示词(Prompt)要素上要求模型同时给出位置（锚点(Anchor)）与 载荷(payload)，不设独立的找点层。
- 证据(Evidence)渲染的可引用性是硬要求：window_id / segment_id 必须在文本中原样可见，否则 锚点(Anchor)无法程序验证。
- 锚点(Anchor)纪律写入输出契约要求：台词锚 台词片段(transcript segment)、纯视觉/音频锚窗口、禁止输出绝对毫秒（ADR-011）。
- 静态上下文(Static Context)与当前集 证据(Evidence)的边界（ADR-010）在 system 提示词(Prompt)要素中显式声明，防泄漏未来剧情与跨集事实。
- 失败透明：解析失败的原始返回必须原样留存（状态(State)层持久化），供 修复(Repair)与 人工介入(HITL)使用。

## 待定项

- 证据(Evidence)渲染的具体文本格式（窗口头格式、观察字段排版）：实现时定，原则为「可引用、紧凑、稳定」。
- 单集 证据(Evidence)超长时的分段策略（当前短剧集不需要，属规模防御）：暂列为待定。
- 提示词(Prompt)具体 wording 属 Deferred（PRD §22 第 3 项），本层只冻结要素清单。

## 测试要点

- 用假 大语言模型(LLM)响应（注入）覆盖：合法输出解析、围栏包裹解析、非法 JSON 的失败分类、弃权(abstain)-only 输出。
- 证据(Evidence)渲染的可引用性：给样例 证据(Evidence)，断言渲染文本包含全部 window_id / segment id。
- 单条修复入口：只接收单条上下文、返回单条 候选(candidate)，可离线验证。
