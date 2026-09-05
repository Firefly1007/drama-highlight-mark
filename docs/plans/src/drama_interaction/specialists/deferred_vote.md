# specialists/deferred_vote.py 内容计划

本模块实现延时投票（deferred_vote）专家的类型规则，执行逻辑复用 [base](base.md) 的 Specialist 子图。

## 职责与边界

- 在剧情抛出问题后生成需要后续揭晓的投票，并给出触发和揭晓锚点。
- 只处理有可信后续答案位置的悬念，不把一般冲突改造成延时投票。
- 不生成绝对毫秒、reveal_time、reveal_delay，也不负责最终选项顺序。

## 输入、输出与接口

- 接收 base 子图提供的专家输入、本分支证据时间线和 `inspect_span` 工具。
- 通过 ToolStrategy 输出 specialist_type 为 deferred_vote 的 SpecialistResult。
- payload 包含 question、二到四个 options 与合法 answer_id；Candidate 必须有 reveal_anchor。

## 依赖与消费者

- 依赖 specialists/base、schemas/candidate、schemas/interaction。
- validation/rules 校验锚点顺序和 payload；graph 的 render 节点生成最终揭晓时间并确定性打乱选项。

## 目标实现要求

- 触发锚点定位在问题已经被提出且仍有悬念的位置；reveal_anchor 必须指向之后真正揭示答案的证据。
- 只提供 deferred_vote 的 focus 和类型约束，不复制 ReAct Agent 或结构化输出骨架。
- question、选项和 answer_id 只能使用本集可验证的事实，不能把未来细节提前写入题干。
- 生成阶段的 reveal_time 和 reveal_delay 保持为空，模型不得输出任何毫秒。
- 找不到可靠揭晓位置时弃权，宁缺勿滥。

## 失败与边界情形

- reveal_anchor 不晚于触发锚点、答案索引越界、选项数不符或时间字段被生成时必须拒绝。
- 渲染后揭晓间隔不合法的候选由全局约束直接淘汰，不进入语义竞争。
- 完整 V1 延时投票判定、揭晓和选项规则只维护在 `config.py` 的 Specialist 提示词中；揭晓间隔仍由调度配置决定。

## 验证

- 覆盖有效的触发—揭晓对、倒序揭晓、缺失揭晓锚和答案索引越界。
- 验证生成侧不含最终毫秒，渲染后能得到合法 reveal_time 与 reveal_delay。
- 验证确定性打乱选项后 answer_id 仍指向正确项。
