# schemas/interaction.py 内容计划

本模块实现最终互动（FinalInteraction）和五类 payload 的 Python 契约；后端 JSON 的唯一权威是 [schema](../../../../schema.md)。

## 职责与边界

- 定义最终输出外壳、五个字符串类型和对应 payload 的字段校验。
- 作为候选与最终输出共用的 payload 结构来源。
- 不做证据锚点解析、时间计算、候选选择、文件导出或 V1 数字类型兼容映射。

## 输入、输出与接口

- FinalInteraction 包含最终 id、type、show_at、duration_ms 和 payload。
- type 只能是 emotion_button、repeat_keyline、instant_vote、deferred_vote、side_comment，不公开数字类型。
- emotion_button 的 button_id 仍是 0 到 5 的业务字段，text 与 danmaku 的组合遵循 schema。
- repeat_keyline 要求 text；instant_vote 要求 question 和恰好两个 options。
- deferred_vote 要求 question、二到四个 options、合法 answer_id、reveal_time 和 reveal_delay。
- side_comment 要求 text，mood 必填，且只能为 roast、shock、laugh、praise、sympathy、doubt。

## 依赖与消费者

- 仅依赖结构校验库。
- schemas/candidate、validation、scheduling、graph 和 cli 共同消费该契约。
- docs/schema.md 是字段和示例的外部权威，任何变更必须同步两处。

## 目标实现要求

- 使用字符串枚举或等价约束表达 type，不保留对外数字映射。
- 最终 id 为排序后的 1 起始序号；show_at、duration_ms 和揭晓时间字段为非负整数。
- deferred_vote 的生成阶段不填毫秒字段，渲染阶段产生最终值；本模块接受并校验最终输出值。
- answer_id 必须在最终 options 数组中有效，且在选项确定性打乱后已完成重映射。
- 对 payload 使用可判别的联合类型或等价机制，保证 type 与 payload 一一对应。

## 失败与边界情形

- 未知 type、数字 type、缺少 mood、非法 mood、无效选项数、越界 answer_id 或负时间必须拒绝。
- button_id 的数字语义仅限 emotion_button payload，不能被误用为顶层 type。
- 字段增减和未冻结的长度阈值只维护在 [PROGRESS](../../../../PROGRESS.md)。

## 验证

- 为五类输出各构造一个合法样例，并与 docs/schema.md 样例逐字段比对。
- 覆盖数字 type、非法字符串 type、六种外 mood、空 mood、选项数错误和 answer_id 越界。
- 覆盖 deferred_vote 的最终时间字段和选项打乱后的 answer_id。
- 验证序列化结果可直接作为后端 JSON 使用。
