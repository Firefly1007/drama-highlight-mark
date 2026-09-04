# schemas/evidence.py 内容计划

本模块定义共享证据（Evidence）的结构契约。架构原因见 [ADR](../../../../drama-interaction-v2-ADR.md)。

## 职责与边界

- 定义单集证据文档 EvidenceDocument、台词片段 TranscriptSegment、观察 Observation 和派生观察 DerivedObservation。
- 在构造期保证证据的时间、标识、顺序和集长边界合法。
- 不做文件读写、媒体解析、模型调用、剧情推理或工作流状态管理。

## 输入、输出与接口

- EvidenceDocument 是单个根对象，包含 episode_duration_ms、transcript_segments 和 observations。
- TranscriptSegment 使用从 T1 开始、无前导零的 T<n> 标识，包含 start_ms、end_ms、text 与可选 speaker_label。
- Observation 使用从 O1 开始、无前导零的 O<n> 标识，包含 start_ms、end_ms、visual_observations、onscreen_texts、audio_observations、uncertainty。
- DerivedObservation 使用每个 Specialist 内从 D1 开始、无前导零的 D<n> 标识，与 Observation 同构，并增加 refines 和 provenance；它只属于产生它的 Specialist。

## 依赖与消费者

- 只依赖 Pydantic 等结构校验能力。
- evidence/adapter 构造并落盘基线证据；evidence/service 产生派生证据；evidence/render、validation、scheduling 和 graph/state 消费这些结构。

## 目标实现要求

- episode_duration_ms 必须为正数；所有条目的 0 <= start_ms <= end_ms <= episode_duration_ms。
- 两个基线列表按 start_ms 升序传入；模型校验不自动排序，标识不能为空且在各自作用域内不重复。
- 基线证据只由适配器写入，后续工作流不得改写；分支视图始终是基线加该分支的 DerivedObservation。
- DerivedObservation 的 refines 只能指向基线 O<n> 或同一 Specialist 早已存在的 D<n>，不得形成环；provenance 固定为 `{specialist, query_span: {start_ms, end_ms}, query}`。
- 结构不提供情绪、分数、置信度或剧情解释字段；证据内容保持客观文本。

## 失败与边界情形

- 时间逆序、越出集长、重复或空白标识、无序列表和无效 refines 必须在构造期报错。
- 不能用截断或自动排序掩盖上游数据问题。
- D<n> 不是跨 Specialist 全局标识；消费者必须同时使用 Specialist 定位它。
- 新证据字段或派生数据的持久化细节只维护在 [PROGRESS](../../../../PROGRESS.md)。

## 验证

- 覆盖合法文档和所有时间、顺序、标识、集长反例。
- 覆盖分支内派生标识、外部引用和成环反例。
- 验证模型序列化再读回后不改变根对象、条目顺序或标识。
- 验证基线对象与派生对象在类型上互不混淆。
