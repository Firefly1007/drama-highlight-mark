# schemas/candidate.py 内容计划

本模块定义候选（Candidate）、锚点（Anchor）和专家结果（SpecialistResult）的内部契约。

## 职责与边界

- 定义触发锚点 TriggerAnchor、揭晓锚点 RevealAnchor、候选、弃权 Abstention 和专家结果。
- 让模型输出只表达可引用证据与互动内容，不表达绝对毫秒、分数或置信度。
- 不定义五类 payload 的字段细节，不解析证据文件，也不进行全局调度。

## 输入、输出与接口

- TriggerAnchor 和 RevealAnchor 都只允许 transcript_segment_id 与 observation_id；至少一个非空，同时存在时按 transcript_segment_id 解析。
- Candidate 包含可空 candidate_id、五类之一的 specialist_type、非空 evidence_ids、trigger_anchor、payload 和仅供 deferred_vote 使用的 reveal_anchor。
- evidence_ids 可引用基线 T<n>、O<n> 和同一专家分支的 D<n>。
- candidate_id 在进入候选池时由程序赋值，模型和专家不得生成它。
- SpecialistResult 由 specialist_type、candidates 和 abstentions 组成；弃权理由是离散文字说明。

## 依赖与消费者

- 依赖 schemas/interaction 的 payload 类型；运行时与 schemas/evidence 提供的分支证据视图配合。
- specialists 负责构造，validation 负责局部校验，scheduling 和 graph 负责入池、选择和追踪。

## 目标实现要求

- 锚点局部结构约束在模型层校验；证据是否存在、是否属于 evidence_ids 由 validation/rules 在分支视图内校验。
- 非 deferred_vote 不得包含 reveal_anchor；deferred_vote 必须提供它。
- 所有候选类型都与最终输出使用同一组字符串类型：emotion_button、repeat_keyline、instant_vote、deferred_vote、side_comment。
- candidate_id 赋值后应作为不可变追踪标识；最终输出 id 是另一套数组序号。
- 结构中不出现 probability、confidence、score 或等价数值评判字段。

## 失败与边界情形

- 空锚点、错误类型、缺失 evidence_ids、错误 reveal_anchor 组合必须被拒绝。
- D<n> 跨分支引用或锚点和证据链不一致必须由校验层形成结构化错误，不能猜测所属分支。
- 候选 ID、弃权词表和局部校验策略未冻结时只维护在 [PROGRESS](../../../../PROGRESS.md)。

## 验证

- 覆盖五种类型的合法候选、空锚点、非法 reveal_anchor 和空 evidence_ids。
- 验证 candidate_id 可在入池前为空，赋值后可追踪且不与最终 id 混用。
- 验证模型不能构造含数值评分或绝对时间字段的生成侧候选。
- 与 validation/rules 联测锚点和 evidence_ids 的分支视图检查。
