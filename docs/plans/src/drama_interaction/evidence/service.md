# src/drama_interaction/evidence/service.py 内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-009、PRD §8（§8.1–8.3）、README_v2.md 架构节

## 职责与边界

- 定义并承载 `inspect_window(window_id, question)` 工具契约：生成专家(Specialist)提交 window_id + 具体问题，返回文本化补充证据。
- 本轮只实现 契约(contract) / 桩实现(stub)，不实现新的多模态取证能力（PRD §8.3）；真实媒体取证留到后续 证据(Evidence)抽取(Extraction)阶段，接口不变、内部替换。
- 明确不做：
  - 不让 生成专家(Specialist)接触原视频 / 原音频 / 原始帧（ADR-009）。
  - 本轮不引入 大语言模型(LLM)调用（大语言模型(LLM)调用点仅 生成专家(Specialist) / 调度器(Scheduler) / 修复(Repair)三类）。
  - 不修改 共享(Shared)证据(Evidence)本体（返回的是补充证据，不回写窗口）。

## 依赖关系

- 依赖 schemas/evidence.py（读取窗口现有证据）与 adapter 的落盘产物（data/evidence/）。
- 被依赖方：specialists/base.py（工具注入 SpecialistInput）、graph/nodes.py（装配时传入）。
- 未来替换方：真正的 证据(Evidence)服务(Service)（访问原媒体或上游提取器），对外契约保持不变。

## 主要组成

- 工具契约定义：
  - 入参：window_id（必填）、question（必填，要求是关于该窗口的具体问题）。
  - 出参：文本化补充证据，形态与 证据窗口(EvidenceWindow)的观察字段同构——visual_observations / audio_observations 文本列表 + 明确的能力标注；window_id 无效或问题为空时报结构化错误而非空结果。
- 本轮 桩实现(stub)行为（已确定）：对任何合法调用返回显式的「本轮取证不可用」说明（含能力边界声明），不返回任何证据内容。
  - 桩实现(stub)阶段绝不产生 共享(Shared)证据(Evidence)之外的文本，杜绝虚假补充证据。
  - 调用链路（调用 → 审计 → 明确的不可用语义）仍然完整，生成专家(Specialist)收到不可用结果后应基于 共享(Shared)证据(Evidence)继续任务。
- 防呆注记：本轮刻意不在 生成专家(Specialist)的 提示词(Prompt)中声明「inspect_window 不可用」。
  - 需观测真实调用行为（触发场景 / 频次 / question 质量 / 收到不可用后的行为）。
  - 理由：提示词(Prompt)预告会使模型不再调用、观测样本归零；桩实现(stub)行为不变（任何合法调用仍返回显式不可用、不返回证据内容）。
- 调用审计：记录每次调用的 生成专家(Specialist)类型、window_id、question 全文、返回摘要——供可观测性（PRD §20.2）与后续评估「生成专家(Specialist)是否过度依赖取证」。
- 未来替换边界：接口签名与出参形态冻结；内部实现从「读 共享(Shared)证据(Evidence)」换为「访问原媒体 + 多模态提取」时，调用方零改动。

## 关键设计点

- 返回的永远是文本（ADR-009 的落实）：即使未来接入真实多模态，多模态能力也被封装在 服务(Service)内部，生成专家(Specialist)侧始终只见文本。
- 桩实现(stub)不返回任何证据内容：第一版统一返回显式不可用说明，生成专家(Specialist)的补充证据需求在第一版只能由 共享(Shared)证据(Evidence)本身满足——这是防止 桩实现(stub)阶段引入虚假 实据(grounding)的最保守选择。
- question 强制具体（要求指向该窗口的具体问题），拒绝「看看这个窗口有什么」式的泛问，控制未来真实取证的成本。
- 审计与 专家结果(SpecialistResult)关联：调用记录要能对齐到产生某 候选(candidate)的 生成专家(Specialist)执行过程。

## 待定项

- 单集调用次数上限（成本控制，PRD §20.3 延伸）：第一版即设宽松上限——每 生成专家(Specialist)每集 N 次，超限后 桩实现(stub)返回明确「已达上限」而非「不可用」，既保观测样本又给成本兜底；N 值由首轮观测数据反推。

## 测试要点

- 合法调用返回明确的不可用说明，且返回文本不包含任何 共享(Shared)证据(Evidence)之外的内容；非法 window_id / 空 question 报结构化错误。
- 审计记录完整（调用方、窗口、问题、返回）。
