# 当前进度（PROGRESS）

本文件是 V2 唯一的**现状、缺口、未决项与下一步**来源；它不替代目标形态的 [README](../README.md)、产品要求的 [PRD](drama-interaction-v2-PRD.md)、技术决策的 [ADR](drama-interaction-v2-ADR.md)、外部输出契约的 [schema](schema.md) 或模块实现计划的 [plans](plans/README.md)。

最后核对：2026-09-05

## 当前判断

V2 的基础主链已建立：它可在离线测试中从单集 V1 片段 JSON 生成后端互动 JSON，并覆盖证据、校验、调度、终端 HITL、LangGraph 恢复和 CLI。本机 PostgreSQL checkpoint 的中断—恢复已实机验证；五类 Specialist 已作为可嵌入父图的已编译 LangGraph 子图运行。每个子图中的 ReAct Agent 按需调用分支私有 `inspect_span` 工具，并通过 LangChain `ToolStrategy(SpecialistResult)` 提交结构化结果；语义调度也使用工具调用，不保留文本 JSON 解析路径。V1 五类互动提示词的完整判定规则已集中迁移到 `config.py`，并将按剧名加载的剧情简介、角色表注入 Specialist 与语义调度器；当前版本已完成一次真实端到端试跑，结果仍需人工验收和 benchmark。

项目范围仍是单集离线互动点标注/生成，并向后端输出 JSON；不包含播放器、前端页面或后端业务服务。

## 当前快照

| 层级 | 状态 | 当前事实 |
| --- | --- | --- |
| 文档体系 | 已完成 | README、PRD、ADR、schema、plans 与本文件各自承担唯一职责。 |
| 配置与运行时 | 已完成 | `Settings` 统一加载配置；LLM 使用 LangChain `ChatOpenAI` 的单一路径，并显式使用 Chat Completions API。 |
| 外部输出模型 | 已完成 | `type` 只输出五个字符串；`side_comment.payload.mood` 必填且受六值枚举约束；导出使用 `exclude_none=True`。 |
| 基线证据与 Adapter | 已完成 | 使用 `EvidenceDocument`、精确跨度与 `T/O/D` 标识；当前起始节点以 V1 片段合法 `end` 的最大值作为临时集长。 |
| 按需取证 | 接口完成 | `inspect_span` 具备校验与审计；未接媒体提取器时明确返回不可用，不生成派生证据。 |
| 证据时间线 | 已完成 | 每个 Specialist 获得隔离的基线加本分支 `D<n>` 时间线，并标出足够长的未覆盖区间。 |
| 五类 Specialist 与修复 | 已完成 | 五个编译 Specialist 子图已嵌入父图；子图内实际 ReAct 图包含 `model → tools → model` 循环，可调用分支私有 `inspect_span`，并通过 ToolStrategy 输出 SpecialistResult。局部校验失败可安全修复或定向重生，网络耗尽进入 HITL。 |
| V1 提示词与剧集上下文 | 已完成 | V1 五类互动提示词的完整筛选、生成、数量和文案规则集中在 `config.py`；V1 的统一 highpoint 识别提示词不单独执行（V2 按 ADR-001 直接从证据找互动机会），其通用筛选边界已并入共用 Specialist 提示词；`data/video/drama_info.json` 的 `name`、`description`、`characters` 作为辅助上下文传入五个 Specialist 和语义调度器，当前集事实仍必须引用 T/O/D。 |
| 渲染与调度 | 已完成 | 锚点确定性换算毫秒；半开区间有任意交集即冲突；UUIDv5 稳定洗牌延时投票选项；仅真实冲突才调用语义调度。 |
| LangGraph、HITL、CLI | 已完成 | 父图使用当前 `StateGraph`、`interrupt` 与 `Command(resume=…)`；五个 Specialist 子图已接入并可由 xray 展开；CLI 提供 `run`、`resume`、`export`；正式 checkpoint 仅允许 PostgreSQL，测试可显式注入内存 saver。 |
| PostgreSQL 实机验证 | 已完成 | 本机服务端口可达；已创建约定的目标数据库，并以 `postgres` 连接完成真实 checkpoint 的网络耗尽中断、终端 `drop` 与恢复。未添加 SQLite 或内存回退。 |
| V2 代码收敛审查 | 已完成 | 已删除重复 Pydantic 预解析/校验、旧文本 JSON 网关路径和未文档化格式或状态容忍分支；保留外部 JSON 契约与清晰主流程。 |
| 真实模型与 Golden benchmark | 进行中 | 已用当前提示词与 ToolStrategy 重跑《十八岁太奶奶驾到，重整家族荣耀第三部》第 1 集，生成 14 条最终互动；仍需人工校正 golden fixtures 与 V1/V2 对照。 |
| 最终 V2 产物 | 运行时生成 | 成功执行后写入 `data/interaction_v2/<剧集目录>/<集名>.json`，仓库不提交运行产物。 |

## 当前简历表述边界

- 可以如实表达：实现了证据驱动的五专家互动生成工作流、确定性渲染与冲突约束、可恢复 HITL/CLI，以及五类互动的后端 JSON 契约。
- 不应表述为已验证：真实媒体预处理、真实模型端点的端到端质量、benchmark 指标或任何质量/成本提升。

## 已确认的实现决策

- 当前临时 V1 输入以片段 JSON 中合法 `end` 的最大值暂代 `episode_duration_ms`；未来 FFmpeg 媒体预处理只替换这一来源，不改变 Adapter 与下游证据接口。
- PostgreSQL 是唯一正式 checkpoint；`execution_id` 同时作为 LangGraph `thread_id`、CLI 标识和运行目录名。测试中的假 checkpointer 必须显式注入。
- HITL 只通过终端处理事件允许的 `accept`、`edit` 或 `drop`；LangSmith 仅可选追踪和查看，不参与回写或恢复。
- LLM Gateway 独占网络重试；网关耗尽时形成 `network_exhausted` 事件，不额外消耗定向重生次数。
- `LLM_TIMEOUT_SECONDS` 与 `LLM_MAX_TOKENS` 字段保留并传入 ChatOpenAI；benchmark 前暂用 `3600s` 与 `131072` 的较大上限，正式值待 benchmark 决定。
- Specialist 使用共用的 LangGraph 子图骨架；子图内 ReAct Agent 通过 LangChain 工具调用 `inspect_span`，最终以 `ToolStrategy(SpecialistResult)` 提交结构化结果。类型模块不复制 Agent、工具或结果解析逻辑。
- 最终互动展示区间为半开区间，任何重叠均冲突；延时投票以固定项目命名空间的 UUIDv5 局部种子稳定洗牌并重映射 `answer_id`。
- `inspect_span` 本轮只实现接口、校验与审计；未接入提取器时明确不可用。

## 下一步

1. 人工验收本次真实输出，校正 golden fixtures，并完成 V1/V2 对照。
2. 接入 FFmpeg 集长提取，并建立离线质量评测。

## 未决项

- `inspect_span` 的每分支调用次数上限：待 benchmark 数据决定。
- 派生观察是否允许跨运行缓存：当前不缓存。
- 真实媒体时长与 V1 时间线的偏差处理：接入 FFmpeg 并完成实测后决定。
- 跟读金句文本匹配的归一化策略。
- `LLM_TIMEOUT_SECONDS` 与 `LLM_MAX_TOKENS` 的 benchmark 后正式取值。

## 本轮验证

- 2026-09-04：README 与 `docs/` 的 100 个相对 Markdown 链接均可达；`schema.md` 的 1 个 JSON 示例通过标准库解析。
- 2026-09-05：`uv run pytest -q` 通过，86 项单元测试全部成功；覆盖证据、剧集上下文、完整 Specialist 提示词、LLM Gateway、工具调用语义调度、父图子图、CLI 和修复层证据边界。
- 2026-09-05：`uv run ruff check .`、`uv lock --check`、`uv run python -m drama_interaction --help` 与 `git diff --check` 均通过；Ruff 显式排除不在 V2 范围内的 `v1/` 历史目录。
- 2026-09-04：对 `data/text/` 的 238 个现有 V1 片段 JSON 做只读 Adapter 与 LangGraph 冒烟，235 集经五路显式弃权后完成并导出空数组；3 集因上游时间戳倒置或片段未按开始时间排序而按契约快速失败，未静默修正原始数据。
- 2026-09-04：已按约定写入本地 PostgreSQL 配置、创建目标数据库，并以真实 `PostgresSaver` 完成一次 `network_exhausted` 中断、终端 `drop` 与 `Command(resume=…)` 恢复；未引入 SQLite 或内存运行时回退。
- 2026-09-04：完成 V2 源码、入口、依赖和离线测试的 Ponytail 审查，并按最小差异删除可确认冗余；未发现 V1/旧接口兼容层。
- 2026-09-04：以真实模型试跑《十八岁太奶奶驾到，重整家族荣耀第三部》第 1 集；工作流完成并仅写入 `data/interaction_v2/`，V1 输入与历史互动文件哈希未变。五类原始候选均因不符合 Candidate 契约转为弃权，最终 V2 JSON 为 `[]`。
- 2026-09-05：五个 Specialist 已作为已编译子图嵌入父图；`xray` 展开显示五个子图运行节点，专项测试覆盖分支私有证据服务、实际 Agent 的 `model → tools → model` 循环、ToolStrategy 结构化结果和网络耗尽 HITL。
- 2026-09-05：真实执行 `2ed68b6731794ff6a1e50bf7a1ffd87b` 处理同一集，V1 集长临时取 `245100ms`，适配出 31 个片段和 31 个观察；五个 Specialist 均因模型端点并发上限返回 429，按设计进入 `waiting_for_human`，未覆盖既有 V1 或 V2 最终 JSON。CLI 同步修正为按当前 LangGraph 的 `list[Interrupt]` 读取中断。
- 2026-09-05：更换端点后真实执行 `d7c76e7e3af74f7488e5e76891b68e61`；`repeat_keyline` 产出 3 条、`side_comment` 产出 15 条，共 18 条候选进入候选池。`emotion_button`、`instant_vote`、`deferred_vote` 各重试 4 次仍超时，流程按设计停在 `waiting_for_human`，尚未写出新的最终互动 JSON。
- 2026-09-05：使用 `config.py` 临时大 timeout/max_tokens 重新执行 `2ffda01a0eaa4b53ae9427392f46c7d8`；五个 Specialist 全部完成，候选池 28 条，最终输出 16 条（emotion_button 4、side_comment 7、instant_vote 2、repeat_keyline 2、deferred_vote 1），写入 `data/interaction_v2/`，未修改 V1 互动结果。
- 2026-09-05：使用当前公共/专有提示词与 ToolStrategy 真实执行 `487c2bf0d2a0427abdcb70c6f4697ffe`；五个 Specialist 完成，候选池 19 条，最终输出 11 条，集长临时取 `245100ms`，写入 `data/interaction_v2/十八岁太奶奶驾到，重整家族荣耀第三部/第1集.json`，未修改 V1 结果。
- 2026-09-05：将 `emotion_button.payload.button_id` 改为英文名称 `cool`、`laugh`、`tomato`、`protect`、`pity`、`ship`，拒绝数字编号；重新执行 `095e178babaf4aeb8d129ef844d163c8` 并丢弃唯一不满足揭晓间隔的候选后完成，最终输出 14 条，其中 6 条情绪按钮均使用英文名称，未修改 V1 结果。
