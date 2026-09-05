# specialists/base.py 内容计划

本模块提供五类生成专家（Specialist）共用的 LangGraph 子图执行骨架。

## 职责与边界

- 组装专家输入、提示词要素、ReAct Agent、结构化结果和单条定向重生入口。
- 负责把本分支证据时间线与分支私有的 `inspect_span` 工具交给 Agent。
- 不实现类型专属的内容判断，不渲染证据，不做确定性校验、调度或图编排。

## 输入、输出与接口

- 输入包含 specialist_type、`DramaContext`、evidence_timeline、模型客户端和当前分支取证上下文。
- 正常输出为通过 LangChain `ToolStrategy(SpecialistResult)` 提交的 SpecialistResult；单条重生输入为原 Candidate、结构化错误和局部证据，输出只是一条替代候选。
- 提示词要求输出候选、锚点、evidence_ids 和弃权，不要求或接受绝对毫秒、候选 id、评分或置信度。

## 依赖与消费者

- 依赖 schemas/candidate、schemas/evidence、evidence/render、evidence/service、llm 和 config。
- 五个类型专家复用本模块；类型差异和完整 V1 互动判定规则从 config 读取；graph/nodes 负责嵌入五个编译子图；validation/repair 调用单条重生入口。

## 目标实现要求

- 使用一套可编译的 Specialist 子图骨架；类型模块只声明 specialist_type，类型专属提示词和共用规则由 config 组装。
- Agent 先读取当前分支时间线，需要补证时通过 LangChain `inspect_span` 工具调用继续推理。
- 最终 SpecialistResult 必须通过 `ToolStrategy(SpecialistResult)` 的结构化工具调用提交；不保留手写 JSON 协议、文本 JSON 解析或 `call_json` 路径。
- 提示词同时注入 `DramaContext` 的剧名、简介和角色表；它只辅助理解名称、关系和背景，当前集事实仍只能由当前集证据支撑。
- 锚点只能复制时间线可见的 T<n>、O<n>、D<n>；不得自行发明毫秒或引用其他分支的 D<n>。
- 当前专家只引用分支时间线内已有的证据标识；派生证据只能由独立取证调用写入其所属分支。
- 结构化输出失败保存错误和原因，交给校验、修复或人工流程；不得悄悄重跑整集。
- 弃权表示在允许取证后仍缺乏安全依据，不是低置信度的数值替代。

## 失败与边界情形

- Agent 网络调用耗尽时形成结构化网络错误并交给图层进入 HITL。
- `inspect_span` 不可用或失败时保留审计，Agent 只能继续使用已有证据或弃权，不补造事实。
- ToolStrategy 无法形成 SpecialistResult 时形成结构化失败，不使用备用解析器。
- 单条重生只能接收该候选及其局部上下文，不得重扫整集或触碰其他候选。
- 提示词模板由 `config.py` 集中维护，网络重试由 LLM Gateway 处理；运行状态见 [PROGRESS](../../../../PROGRESS.md)。

## 验证

- 使用假模型覆盖 `inspect_span` 工具调用、合法 SpecialistResult 和仅弃权结果。
- 断言 Agent 只看到当前分支证据，且最终结果来自 ToolStrategy 结构化工具调用。
- 断言单条重生只返回一条候选并只使用局部证据。
- 断言网络耗尽进入 HITL，且不会触发整集重跑。
