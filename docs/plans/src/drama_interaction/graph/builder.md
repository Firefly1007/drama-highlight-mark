# src/drama_interaction/graph/builder.py 内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-015 / 016 / 022、PRD §13 / §20.1、README_v2.md（langgraph.json 定位）

## 职责与边界

- LangGraph 组装层：状态图(StateGraph)的节点注册、边结构、节点级重试与错误处理策略、检查点存储(checkpointer)装配、中断(interrupt)/恢复(resume)通道、编译产物导出(export)。
- 框架接入点集中于此：LangGraph 版本升级的破坏性变更只应波及本文件与 nodes/state 的装配细节，业务模块不感知框架（README_v2.md 分层原则）。
- 明确不做：业务逻辑（nodes.py）、工作流状态(State)定义（state.py）、命令行(cli)交互（cli.py）。

## 依赖关系

- 依赖 graph/state.py、graph/nodes.py、config.py。
  - state.py 提供 工作流状态(State)类型与 归并器(reducer)。
  - nodes.py 提供节点函数。
  - config.py 提供 检查点(checkpoint)位置与介质开关。
- 被依赖方：cli.py（run/恢复(resume)/导出(export)使用编译产物）、langgraph.json（Studio/dev 入口指向本模块导出的图）。

## 主要组成

- 图装配：注册 state.py 定义的 工作流状态(State)与 nodes.py 的全部节点；边结构——
  - START → adapter_node；
  - adapter_node → 五个 specialist_node（静态多边 扇出(fan-out)，分支数固定）；
  - 每个 specialist_node → 各自 branch_validate_repair（含条件边循环：校验失败可修复→修复回校验；耗尽→中断(interrupt)/人工介入(HITL)记录）；
  - 五路 branch 通过后 扇入(fan-in) → pool_node；
  - pool_node → render_node → constraints_node →（待取舍集合为空则跳过）semantic_node → final_check_node → END。
- 节点级重试与错误处理策略（ADR-015）：对含 大语言模型(LLM)调用的节点配置 重试策略(RetryPolicy)，重试耗尽后的 error_handler 让该分支记录失败状态并进入 人工介入(HITL)，而非整图失败；确定性节点不配 大语言模型(LLM)式重试。
  - 含 大语言模型(LLM)调用的节点：specialist、semantic、repair 退回。
  - 重试策略(RetryPolicy)为瞬时错误有限重试，与 llm.py 调用层重试分层：调用层管单请求，节点层管「整个节点步骤」。
  - 确定性节点（adapter、rules、constraints、render_node、终检）不配 大语言模型(LLM)式重试。
- 检查点存储(checkpointer)装配：开发期本地 SQLite/文件 检查点存储(checkpointer)，位置与介质来自 config（介质本身 暂缓(Deferred)，PRD §22 第 8 项）；线程(thread) id 即 execution_id（README_v2.md 使用节）。
- 中断(interrupt)/恢复(resume)通道：图编译为可恢复形态。
  - 恢复(resume)路径 = 人工结果写入 工作流状态(State)后从 中断(interrupt)挂点继续（nodes.py 定义的挂点）。
  - 已完成节点（adapter、成功 生成专家(Specialist)）天然不重跑——检查点(checkpoint)语义的直接结果，也是 ADR-016 的落实。
- 编译产物导出(export)：提供编译后的图对象（供 命令行(cli)调用）与 langgraph.json 所需的图入口引用（供 langgraph dev / Studio 可视化调试）。

## 关键设计点

- 重试策略(RetryPolicy)与分支隔离的配合：重试只发生在失败分支内部，任何配置都不产生「其他四路重跑」的路径——与 ADR-022「避免把整集重跑藏在图结构里」互为印证。
- 中断(interrupt)挂点注册集中在 builder（挂点位置由 nodes 定义），保证「成功结果已持久化 → 暂停 → 人工处理 → 恢复」的完整闭环可装配。
- 介质可替换：检查点存储(checkpointer)装配按 config 开关选择实现，业务与 命令行(cli)不感知介质差异。
- 图结构可静态审阅：全部边在装配时确定（除条件边谓词），为「图里没有整集重跑边」提供可审查性。

## 待定项

- 检查点存储(checkpointer)介质最终选型（SQLite 起步，介质待定）。
- 重试策略(RetryPolicy)各节点的次数 / 退避数值（与 llm.py 调用层参数统一调）。
- langgraph.json 的具体声明格式（随 LangGraph 1.x 版本核对，见 project-config.md）。

## 测试要点

- 图可整体编译（装配无环错误、工作流状态(State)类型一致）。
- 小 工作流状态(State)干跑：正常路径跑通、中断后 恢复(resume)路径跑通、单分支注入持续失败后其余分支不受影响。
- 检查点存储(checkpointer)落盘与恢复：同一 execution_id 二次 invoke 从 检查点(checkpoint)继续。
- 「无整集重跑边」的结构断言（遍历边集合验证）。
