# graph/nodes.py 内容计划

本模块把业务模块编排为单集工作流节点。

## 职责与边界

- 节点只读取状态、调用一个或多个业务模块并写回状态。
- 串联媒体预处理、适配、五路专家、分支校验修复、候选池、渲染、约束、语义调度和终检。
- 不把提示词、校验规则、证据结构或图装配细节复制到节点中。

## 输入、输出与接口

- media_prepare_node 在最开始运行媒体预处理并写入 episode_duration_ms；adapter_node 消费该值并写入 EvidenceDocument，空证据直接产出空最终数组。
- 五个 specialist_node 分别调用 emotion_button、repeat_keyline、instant_vote、deferred_vote、side_comment。
- branch_validate_repair 输出可入池候选或 HITL 事件；pool_node 分配 candidate_id 并汇聚派生证据记录。
- render_node 计算最终时间与确定性选项顺序；constraints_node、semantic_node、final_check_node 依次写入后续状态。

## 依赖与消费者

- 依赖 evidence、specialists、validation、scheduling、schemas 和 graph/state。
- graph/builder 注册节点和条件边；CLI 触发图的运行和恢复。

## 目标实现要求

- 主链固定为：media_prepare → adapter → 五路专家 → 分支校验/修复 → pool → render → constraints → semantic（可跳过）→ final_check。
- 五路专家静态并行，单分支失败只进入自身 HITL 路径，其他分支照常汇聚。
- pool_node 是唯一 candidate_id 赋值点，并按分支写出全部派生证据审计；服务本身不写运行目录。
- render_node 使用 constraints.resolve_anchor，生成 show_at、duration_ms、deferred_vote 的揭晓字段，并在打乱 options 后重映射 answer_id。
- final_check 通过后按 show_at、duration_ms 排序并分配最终 id。

## 失败与边界情形

- 空证据不调用五个专家；无语义取舍集合不调用 semantic。
- 分支修复耗尽和语义调度无法合法返回时暂停为 waiting_for_human，不让整图丢失成功分支。
- 终检失败不能静默改写结果。
- 条件边、错误事件字段和图接口细节未冻结时只维护在 [PROGRESS](../../../../PROGRESS.md)。

## 验证

- 为每个节点使用假业务模块断言输入状态与输出状态。
- 验证空证据短路、五路隔离、candidate_id 唯一性和派生证据分组落盘。
- 验证 semantic 跳过条件、HITL 暂停和终检错误路径。
- 用小状态和假模型运行一条正常图路径和一条单分支失败路径。
