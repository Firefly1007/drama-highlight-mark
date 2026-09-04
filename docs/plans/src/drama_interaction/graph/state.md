# graph/state.py 内容计划

本模块定义单集工作流状态（Workflow State）和并行归并规则。

## 职责与边界

- 表达一集从证据适配到最终互动的全部可恢复状态。
- 为五条专家分支的并行写入提供追加式 reducer。
- 不做节点业务逻辑、检查点介质选择或命令行交互。

## 输入、输出与接口

- execution 保存 execution_id、剧名、集名、状态和时间戳；episode_duration_ms 保存起始媒体预处理阶段得到的真实集长。
- evidence 保存只读的 EvidenceDocument；derived_evidence 按 specialist_type 分组保存派生观察。
- specialist_results、candidate_pool、repair_log、hitl_queue、constraints_report、scheduler_decision、rendered_candidates、selected_candidates、final_interactions 和 metrics 保存各阶段产物。
- 状态机至少支持 running、waiting_for_human、completed、failed。

## 依赖与消费者

- 依赖三个 schemas 模块。
- graph/nodes 读写状态，graph/builder 装配 reducer，CLI 读取最终结果和恢复信息。

## 目标实现要求

- 一个状态实例只处理一集；整剧批处理由 CLI 创建多个独立执行。
- 基线 evidence 由 adapter 写入后只读；adapter 只消费状态中已验证的 episode_duration_ms；每个分支只能追加自己的 derived_evidence。
- 所有并行多写字段声明稳定 reducer，保证结果不丢失、不覆盖。
- 状态、修复记录和指标可被检查点序列化，恢复后保留完整上下文。

## 失败与边界情形

- 不允许不同集、不同 execution_id 或不同分支的状态数据混写。
- 基线证据不得被服务、专家或修复流程改写。
- 具体容器形态、指标和 HITL 字段未冻结时只维护在 [PROGRESS](../../../../PROGRESS.md)。

## 验证

- 模拟五路并行写入，验证 reducer 无丢失、无覆盖且顺序无关。
- 覆盖合法和非法状态迁移。
- 验证状态序列化—恢复保持证据、候选、派生分组和人工队列。
- 验证分支 D<n> 不会在另一分支视图中变得可见。
