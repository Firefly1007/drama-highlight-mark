# graph/builder.py 内容计划

本模块装配 LangGraph 状态图、检查点和暂停恢复通道。

## 职责与边界

- 注册状态、节点、静态分支、条件边和 PostgreSQL 检查点。
- 编译可被 CLI 与 langgraph 开发工具调用的单集图。
- 不实现节点业务逻辑、状态字段定义或终端交互。

## 输入、输出与接口

- 输入为 config、graph/state 的状态类型和 graph/nodes 的节点函数。
- 输出为已编译父图，以及供 langgraph.json 引用的稳定入口；父图中嵌入五个已编译 Specialist 子图。
- execution_id 作为 PostgreSQL checkpoint 线程标识，resume 从相应 interrupt 继续。

## 依赖与消费者

- 依赖 graph/state、graph/nodes、specialists/base 和 config。
- CLI 用它启动和恢复运行；langgraph.json 用它进行开发调试。

## 目标实现要求

- 图只接受单集状态；批量执行由 CLI 重复调用图。
- 注册五个使用同一公共骨架的 Specialist 子图，分别注入类型 focus 和分支证据；子图内部由 ReAct Agent 与 `inspect_span` 工具循环，最终通过 ToolStrategy 返回 SpecialistResult。
- 子图内在 Agent 结果之后完成分支校验—修复，成功结果回写父图并汇聚到 pool。
- 网络重试仅在 LLM Gateway 内执行；适配、渲染、约束和终检等图节点不重复网络重试。
- 中断点支持候选/分支级和调度级人工介入；恢复时已完成节点不得重跑。
- 所有边在装配时静态可审阅，图中不得存在回到媒体预处理、适配器或整集专家重跑的边。

## 失败与边界情形

- 图无法编译、PostgreSQL checkpoint 不可用或 execution_id 无效时给出明确异常。
- Specialist 子图无法形成结构化结果时只失败当前分支，不使用文本 JSON 解析或整集重跑。
- 单一专家分支持续失败时隔离该分支，保留其他完成结果并进入人工流程。
- 重试数值由 LLM Gateway 和配置对象统一承载；运行状态见 [PROGRESS](../../../../PROGRESS.md)。

## 验证

- 验证图可编译、节点和状态键匹配。
- 验证父图实际嵌入五个 Specialist 子图，`xray` 图视图能展开各子图的运行节点；Specialist 专项测试验证 Agent 与 `inspect_span` 工具调用。
- 使用小状态覆盖正常、人工中断后恢复和单分支失败隔离路径。
- 验证 SpecialistResult 由 ToolStrategy 结构化工具调用提交。
- 验证同一 execution_id 从检查点继续，成功节点不重复执行。
- 审阅边集合，断言不存在整集重跑路径。
