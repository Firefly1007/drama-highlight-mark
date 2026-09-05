# specialists/emotion_button.py 内容计划

本模块实现情绪按钮（emotion_button）专家的类型规则，执行逻辑复用 [base](base.md) 的 Specialist 子图。

## 职责与边界

- 识别适合即时表达情绪的剧情时刻，并生成与证据相符的按钮 payload。
- 只处理 emotion_button，不和其他四类专家比较价值或争夺位置。
- 不实现模型调用骨架、证据校验、时间计算或最终 JSON 导出。

## 输入、输出与接口

- 接收 base 子图提供的专家输入、本分支证据时间线和 `inspect_span` 工具。
- 通过 ToolStrategy 输出 specialist_type 为 emotion_button 的 SpecialistResult，其中候选 payload 使用 EmotionButtonPayload。
- button_id 为 `cool`、`laugh`、`tomato`、`protect`、`pity`、`ship` 之一，text 和 danmaku 的组合遵循 [输出契约](../../../../schema.md)。

## 依赖与消费者

- 依赖 specialists/base、schemas/candidate、schemas/interaction。
- graph/nodes 作为固定专家分支调用；validation/rules 校验候选。

## 目标实现要求

- 提示词聚焦打脸、搞笑、危险、心疼、甜蜜等可由本集证据直接支撑的情绪节点。
- 只提供 emotion_button 的 focus 和类型约束，不复制 ReAct Agent 或结构化输出骨架。
- 每个候选必须用锚点和 evidence_ids 说明依据，避免仅凭静态简介生成。
- 选择与场景含义相符的 button_id，不把 payload 文本当作自由创作。
- 没有可靠按钮场景时输出弃权而不是泛化凑数。

## 失败与边界情形

- 按钮类型无法与证据或 button_id 对齐时弃权或交给校验修复，不猜测。
- 不得把跨集事实、未来剧情或其他专家的候选作为依据。
- 完整 V1 判定、文案和数量规则只维护在 `config.py` 的 Specialist 提示词中。

## 验证

- 构造每个 button_id 的合规 payload 与不合规 text/danmaku 组合。
- 验证候选引用的证据存在且场景与按钮类型相符。
- 验证无合适场景时返回弃权，不产生通用占位按钮。
