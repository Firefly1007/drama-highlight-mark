# src/drama_interaction/cli.py 内容规划

- 状态：规划中（未实现）
- 上游依据：README_v2.md「使用」节（唯一权威）、ADR-016、PRD §13 / §17 / §20.2

## 职责与边界

- 三个命令的用户入口：运行(run) / 恢复(resume) / 导出(export)；负责参数解析、execution-id 生成、图调用、人工介入(HITL)的 命令行(CLI)交互、结果落盘与展示。
- 明确不做：
  - 业务逻辑与图结构（图(graph)层）
  - 产物格式定义（模式(schemas)）
  - 检查点(checkpoint)介质实现（builder/config）

## 依赖关系

- 依赖：
  - graph/builder.py（编译图与 恢复(resume)通道）
  - config.py（路径与参数）
  - schemas/interaction.py（导出(export)格式）
- 被 pyproject 的 console entry（`python -m drama_interaction`）指向。

## 主要组成

- 运行(run)命令：
  - 参数：输入路径（V1 片段(segments) JSON 文件或整剧目录 `data/text/<剧名>/`）、可选覆盖参数（预算(budget)等，基准评测(benchmark)用）。
  - 目录输入 = 遍历该剧全部 片段(segments) JSON。
  - 建议每集独立 执行(execution)：
    - 独立 execution-id、独立 检查点(checkpoint)、独立产物文件。
    - 单集失败 / 待人工不阻塞其他集，与分支隔离理念一致。
  - 启动时生成 execution-id，即 LangGraph 检查点(checkpoint)线程(thread)标识(ID)：
    - 建议：可读前缀 + 短随机码。
    - 运行开始即打印，并落盘于 `data/interaction_v2/runs/<execution-id>/`。
  - 最终互动 JSON 写 `data/interaction_v2/<剧名>/<集名>.json`；适配器(Adapter)中间产物写 `data/evidence/`（由 适配器(Adapter)节点完成）。
- 恢复(resume)命令：
  - 参数：`--thread <execution-id>`（必填）。
  - 流程：
    - 列出该 执行(execution)的待人工项：候选(candidate)级 / 分支级 / 调度级。
    - 逐项呈现上下文：候选内容、错误历史、局部证据。
    - 接受 accept / edit / drop。
    - edit 采用最朴素形态：把候选导出为临时 JSON 文件让用户手工编辑后回填。
    - 人工结果写入 工作流状态(Workflow State)后从 检查点(checkpoint)恢复执行（恢复点=触发 人工介入(HITL)的节点，PRD §13）。
- 导出(export)命令：
  - 参数：`--thread <execution-id>`（必填）、可选输出路径。
  - 从已持久化的执行状态读取最终互动数组导出，不重新执行任何节点。
  - 状态未到可导出阶段（未完成 / 仍待人工）时明确报告当前状态与待办项。
  - 导出数组的排序与 标识(ID)规则（定稿，ADR-023）：按 (`show_at`, `duration_ms`)排序、标识(ID)为 1-based 自增。
- 输出与退出码约定：
  - 正常完成（0）。
  - 存在待人工项：非零专码，提示 resume 命令与 execution-id。
  - 失败：非零，附错误摘要。
  - 运行过程打印节点进度与 指标(metrics)摘要（调用次数、重试、人工介入(HITL)次数——PRD §20.2）。

## 关键设计点

- execution-id 的三重身份：检查点(checkpoint)线程(thread)标识(ID)、runs 目录名、恢复(resume)/导出(export)的引用键——生成规则集中在一处。
- 人工介入(HITL)是 命令行(CLI)流程的一等公民但保持朴素：第一版交互 = 文本列表 + 序号选择 + JSON 文件编辑，不做 界面(UI)（人工介入(HITL)界面(UI)属 Deferred，PRD §22 第 8 项）。
- 运行(run)的批处理不牺牲隔离：集与集之间互不影响，符合「异常只影响自身、其余照常」的全局设计理念。
- 导出(export)严格只读：保证「最终发布暂停」期间（PRD §13）状态可查而不被改动。

## 待定项

- 运行(run)是否需要 --episode 过滤（目录输入下只跑指定集）。
- 恢复(resume)的非交互模式（人工结果从文件批量导入，供自动化测试与批量处理）：第一版可只做交互式，标注待定。
- execution-id 具体格式（可读性与碰撞率的平衡）。

## 测试要点

- 三命令的参数校验与错误提示（缺参、路径不存在、execution-id 无效）。
- 目录批处理：多集独立 执行(execution)、单集失败不影响他集。
- 恢复(resume)交互流程用脚本化标准输入模拟：accept/drop/edit 三动作各一条路径。
- 退出码约定的稳定性测试。
