# specialists/instant_vote.py 内容计划

本模块实现即时投票（instant_vote）专家的类型规则，执行逻辑复用 [base](base.md) 的 Specialist 子图。

## 职责与边界

- 将当前时刻已明确的对立、选择或立场转换为即时投票。
- 只生成现在即可回答的问题，不生成需要后续揭晓的悬念投票。
- 不负责选项打乱、全局冲突处理、时间计算或最终导出。

## 输入、输出与接口

- 接收 base 子图提供的专家输入、本分支证据时间线和 `inspect_span` 工具。
- 通过 ToolStrategy 输出 specialist_type 为 instant_vote 的 SpecialistResult。
- payload 包含 question 和恰好两个 options；不包含 reveal_anchor 或揭晓时间。

## 依赖与消费者

- 依赖 specialists/base、schemas/candidate、schemas/interaction。
- validation/rules 校验两选项约束；graph/nodes 将通过校验的候选送入候选池。

## 目标实现要求

- 问题和两个选项都必须由当前证据直接支撑，且形成真实、清晰的二选一。
- 只提供 instant_vote 的 focus 和类型约束，不复制 ReAct Agent 或结构化输出骨架。
- 选项保持中立且可读，不泄露后续剧情或诱导用户选择。
- 触发锚点定位在冲突或选择已经发生的时刻。
- 对立不明确、证据不足或只能依赖未来信息时弃权。

## 失败与边界情形

- 选项不是两个、语义重复、无法由证据验证或需要答案揭晓时必须拒绝。
- 不得把 deferred_vote 的字段或未来事实塞入即时投票。
- 完整 V1 投票判定、问题和选项规则只维护在 `config.py` 的 Specialist 提示词中。

## 验证

- 覆盖标准二选一、选项数错误、选项同义和证据不足的案例。
- 验证结果不含 reveal_anchor、reveal_time 或 reveal_delay。
- 验证选项和题干引用当前集可见证据。
