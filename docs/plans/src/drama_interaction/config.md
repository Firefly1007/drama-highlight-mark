# config.py 内容计划

本模块是项目唯一的配置入口；运行状态见 [PROGRESS](../../../PROGRESS.md)。

## 职责与边界

- 集中装载运行参数、模型连接、路径、渲染参数和检查点设置。
- 对外提供只读配置对象，业务模块只能读取，不能在运行中修改。
- 不包含数据模式、图节点或路径拼接逻辑；五类 Specialist 和语义调度器的可调提示词模板集中维护在本模块。

## 输入、输出与接口

- 输入优先级为：命令行显式覆盖、环境变量或 .env、内置默认值。
- 模型连接变量为 LLM_MODEL_ID、LLM_API_KEY、LLM_BASE_URL；检查点连接变量为 CHECKPOINT_DATABASE_URL。
- 路径组包含证据产物、V2 产物和运行目录；V1 片段输入由 CLI 指定，当前集长由起始节点从其最大 `end` 计算，未来可替换为 FFmpeg 结果。
- `DEFAULT_DRAMA_INFO_PATH` 指向剧集级 `DramaContext` 来源；提示词模板包含 V1 五类互动的完整判定规则，输入/输出部分按 V2 的 `EvidenceDocument` 和 ToolStrategy 契约适配；`series_context` 区块由 Specialist 与语义调度器共用。
- 调度与渲染参数包括 interaction_budget、min_interaction_spacing_ms、type_cooldown_ms、各类型时长、keyline_tail_ms、reveal_display_ms、reveal_gap_min_ms 和 min_reported_gap_ms。

## 依赖与消费者

- llm 使用连接参数；adapter 使用输入和证据路径；graph/builder 使用 PostgreSQL checkpoint 设置；cli 使用输入输出路径。
- evidence/render、scheduling/constraints 和 scheduling/semantic 读取相应阈值或预算。
- `context`、`specialists/base` 和 `scheduling/semantic` 读取剧集上下文和提示词模板。

## 目标实现要求

- 所有产物路径由本模块生成，其他模块不得自行约定相对路径。
- min_reported_gap_ms 固定默认 2500；尚未配置的预算、间隔和冷却保持显式未配置，不得静默变为魔法数。
- 固定类型时长仅适用于其余四类；repeat_keyline 由其专属上下限和 tail 推导。
- 装载时校验必填连接信息、正整数参数、路径可用性和参数间不变量；间隔配置须不小于所用互动时长的最大值。LangSmith 标准环境变量只控制可选追踪，不影响本地运行。

## 失败与边界情形

- 缺失 LLM 或 CHECKPOINT_DATABASE_URL 等必填配置时一次性列出全部缺失项并快速失败。
- 非法整数、负数、相互冲突的时长与间隔配置必须在启动时失败。
- 未配置的可选调度限制要被消费者显式跳过并留下可观测记录。
- 新配置项和参数数值由配置对象统一声明；运行状态见 [PROGRESS](../../../PROGRESS.md)。

## 验证

- 验证三层优先级和只读性。
- 验证缺失项、非法数值、时长与间隔冲突都会产生明确错误。
- 验证未配置的限制不会被隐式替换为 0。
- 验证所有消费者从同一个配置对象读到一致的路径和参数。
