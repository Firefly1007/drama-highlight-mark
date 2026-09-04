# specialists/repeat_keyline.py 内容计划

本模块实现跟读金句（repeat_keyline）专家，公共执行逻辑复用 [base](base.md)。

## 职责与边界

- 找出值得用户跟读的单句台词，并生成 repeat_keyline 候选。
- 不把普通对白、改写台词或独立旁白当作金句。
- 不计算最终时长、跨类型调度或处理其他互动类型。

## 输入、输出与接口

- 接收 base 提供的专家输入和可引用证据时间线。
- 输出 specialist_type 为 repeat_keyline 的 SpecialistResult，payload 只含需要跟读的 text。
- 锚点可引用 transcript_segment_id 或 observation_id；payload 文本仍须能在本集台词中验证。

## 依赖与消费者

- 依赖 specialists/base、schemas/candidate、schemas/interaction。
- validation/rules 验证台词真实性；render 节点依据锚点计算跟读时长。

## 目标实现要求

- 选择具有可复述性、剧情辨识度或情绪张力的原始台词，不改写字面内容。
- 候选的 evidence_ids 至少覆盖文本出处与触发锚点。
- 允许使用观察锚点定位合适时刻，但不能因此失去对台词原文的验证。
- 没有足够突出的原始台词时弃权。

## 失败与边界情形

- 找不到原文、文本与本集台词不一致、锚点不存在时必须拒绝或定向重生。
- 不能因为没有台词锚点而使用固定时长；时长始终由实际锚点跨度和渲染规则决定。
- 金句判定和文本归一化细则只维护在 [PROGRESS](../../../../PROGRESS.md)。

## 验证

- 覆盖台词锚和观察锚两种成功路径。
- 验证 payload 文本与台词列表匹配，改写或编造文本被拒绝。
- 验证无金句时产生弃权，最终时长来自锚点而非默认常数。
