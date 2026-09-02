# V2 各文件内容规划索引

每份规划对应一个目标源文件，目录结构镜像 `src/drama_interaction/` 的实际布局；规划文件与源文件同名（`.md` 后缀），实现时直接在规划旁建文件。

- 规划内容为「大致内容规划」：职责与边界、依赖关系、主要组成、关键设计点、待定项、测试要点，对应 `README.md` 项目结构树中的目标形态。
- 规划阶段产物，不含代码；实现时以对应规划为蓝本，与 架构决策记录(ADR) / 产品需求文档(PRD)冲突时以上游文档为准。

## 目录

```text
docs/plans/
├── README.md                        # 本索引
├── project-config.md                # pyproject.toml / .env.example / langgraph.json 三件套
└── src/drama_interaction/           # 镜像 src/ 源码结构
    ├── cli.md                       # → cli.py
    ├── config.md                    # → config.py
    ├── llm.md                       # → llm.py
    ├── schemas/
    │   ├── evidence.md              # → schemas/evidence.py
    │   ├── candidate.md             # → schemas/candidate.py
    │   └── interaction.md           # → schemas/interaction.py
    ├── evidence/
    │   ├── adapter.md               # → evidence/adapter.py
    │   └── service.md               # → evidence/service.py
    ├── specialists/
    │   ├── base.md                  # → specialists/base.py
    │   └── emotion-button.md        # → specialists/ 五个类型模块（含五类型对照）
    ├── validation/
    │   ├── rules.md                 # → validation/rules.py
    │   └── repair.md                # → validation/repair.py
    ├── scheduling/
    │   ├── constraints.md           # → scheduling/constraints.py
    │   └── semantic.md              # → scheduling/semantic.py
    └── graph/
        ├── state.md                 # → graph/state.py
        ├── nodes.md                 # → graph/nodes.py
        └── builder.md               # → graph/builder.py
```

## 阅读顺序建议

1. 契约层先行：模式(schemas)三份 → 全项目的类型地基。
2. 数据入口：evidence/adapter.md（V1 → 证据窗口(EvidenceWindow)[]）。
3. 业务主干：specialists/base.md → specialists/emotion-button.md（含五类型对照）→ 校验(validation)两份 → scheduling 两份。
4. 编排与入口：图(graph)三份 → cli.md → llm.md / config.md / project-config.md。

## 逐文件索引

| 规划文件 | 对应源文件 | 一句话定位 |
|----------|-----------|------------|
| [project-config.md](project-config.md) | pyproject.toml / .env.example / langgraph.json | 工程壳三件套内容清单 |
| [cli.md](src/drama_interaction/cli.md) | cli.py | 运行(run) / 恢复(resume) / 导出(export)三命令语义与 人工介入(HITL)交互 |
| [config.md](src/drama_interaction/config.md) | config.py | 全项目唯一配置入口：运行参数 / 大语言模型(LLM)连接 / 路径 / 检查点(checkpoint)开关 |
| [llm.md](src/drama_interaction/llm.md) | llm.py | 唯一 大语言模型(LLM)网络出口：装配、瞬时重试、JSON 解析容错、调用审计 |
| [evidence.md](src/drama_interaction/schemas/evidence.md) | schemas/evidence.py | 证据窗口(EvidenceWindow)数据契约与窗口纪律校验（地基，零依赖） |
| [candidate.md](src/drama_interaction/schemas/candidate.md) | schemas/candidate.py | 触发锚点(TriggerAnchor) / 候选(Candidate) / 专家结果(SpecialistResult)与 candidate_id 后赋值约定 |
| [interaction.md](src/drama_interaction/schemas/interaction.md) | schemas/interaction.py | 最终五类互动输出契约（载荷(payload)字段单一来源） |
| [adapter.md](src/drama_interaction/evidence/adapter.md) | evidence/adapter.py | 旧版适配器(Legacy Adapter)：V1 片段(segments) → 证据窗口(EvidenceWindow)[]（临时层，确定性幂等） |
| [service.md](src/drama_interaction/evidence/service.md) | evidence/service.py | inspect_window 契约与本轮 桩实现(stub)行为 |
| [base.md](src/drama_interaction/specialists/base.md) | specialists/base.py | 五类 生成专家(Specialist)公共骨架：输入组装 / 提示词(Prompt) / 解析 / 弃权(abstain) / 单条修复入口 |
| [emotion-button.md](src/drama_interaction/specialists/emotion-button.md) | specialists/ 五个类型模块 | 单类型模块结构 + 五类型对照（载荷(payload) / 校验 / 弃权(abstain)倾向 / 误用风险） |
| [rules.md](src/drama_interaction/validation/rules.md) | validation/rules.py | 确定性校验规则清单（四组规则 + 结构化错误描述） |
| [repair.md](src/drama_interaction/validation/repair.md) | validation/repair.py | 两阶段修复：安全程序修复白名单 → 定向退回 → 人工介入(HITL) |
| [constraints.md](src/drama_interaction/scheduling/constraints.md) | scheduling/constraints.py | 确定性全局约束 + 候选代表时间点解析（resolve_anchor 唯一实现）+ 终检复用 |
| [semantic.md](src/drama_interaction/scheduling/semantic.md) | scheduling/semantic.py | 语义调度：触发条件 / 五要素输入 / 离散 标识(ID)输出协议 |
| [state.md](src/drama_interaction/graph/state.md) | graph/state.py | 工作流状态(Workflow State)字段组与并行汇聚 归并器(reducer) |
| [nodes.md](src/drama_interaction/graph/nodes.md) | graph/nodes.py | 节点清单（编排层）+ render_node 渲染与 人工介入(HITL)中断(interrupt)挂点 |
| [builder.md](src/drama_interaction/graph/builder.md) | graph/builder.py | 状态图(StateGraph)装配：边结构 / 重试策略(RetryPolicy) / 检查点存储(checkpointer) / 恢复(resume) |

## 已定决策

- 2026-09-02：evidence-service 桩实现(stub)对任何合法调用返回「本轮取证不可用」，不返回证据内容（见 evidence/service.md）。
- 2026-09-02：V1 `uncertainty` 非空时并入窗口 `uncertainty[]`（已回填 PRD §7，见 evidence/adapter.md）。
- 2026-09-02：渲染断点定稿为 ADR-023（Accepted），要点：
  - `resolve_anchor` 共用解析；`show_at` = 锚 start；`reveal_time` = 揭晓(reveal)锚 start；`reveal_delay` = 配置常量。
  - `duration_ms` 按类型时长表（数值按 2.2 分钟中位集长整体下调，区间见 架构决策记录(ADR)，待 基准评测(benchmark)调参）。
  - `deferred_vote` 时间不合法时直接放弃候选（不修复）。
  - 不设揭晓距离上界（待 基准评测(benchmark)观测）。
  - 选项以 `hash(execution_id + candidate_id)` 为种子确定性打乱；`type` 1–5 与排序/标识(ID)规则沿用 V1。
- 2026-09-02：渲染断点后续 7 条决策：
  1. `repeat_keyline` 不强制 `segment_id`（接受退化常数）。
  2. `resolve_anchor` 单条件二分支定稿，唯一实现落 `scheduling/constraints.py`（不新建模块，`render_node` import 它）。
  3. 时间字段全部在渲染环节由程序生成，大语言模型(LLM) / 生成专家(Specialist)侧零毫秒。
  4. `deferred_vote` 时间校验前移至冲突组之前（先淘汰再竞争，复用 constraints 淘汰清单，不走 修复(repair)）。
  5. `inspect_window` 不在 提示词(Prompt)预告不可用（保留观测窗口）。
  6. 渲染提前到 池(Pool)之后，节点改名 `render_node`；边结构 `pool → render → constraints → semantic → final_check`。
  7. 不设全局时长护栏：`keyline` 专属上下限为代码常量 2500 / 4500，其余四类无 截断(clamp)，防重叠由派生校验承接。

## 跨文件全局待定项（汇总）

1. 基准评测(benchmark)后定数值：
  - 约束类：`interaction_budget` / `min_interaction_spacing_ms` / `type_cooldown_ms`
  - 时长类：四类 `type_base` 与 `reveal` 两常量（`reveal_display_ms`、`reveal_gap_min_ms`）
  - `keyline` 上下限为代码常量 `KEYLINE_DURATION_FLOOR=2500` / `KEYLINE_DURATION_CEIL=4500`（写死渲染模块，不进 config）
  - 注：全局 `DURATION_FLOOR` / `DURATION_CEIL` 已删除，不列入。
2. 冲突(conflict) group 的时间规则（ADR-017 明确 Deferred）。
3. 金句台词(keyline)与 台词文本(transcript)匹配的归一化口径、「明显重复」的近似判定口径（rules / 修复(repair)白名单联动）。
4. 定向退回重试次数上限（建议 1）、调度器(Scheduler)非法输出重试上限（建议 1）。
5. 选型类：pydantic-settings、OpenAI 开发工具包(SDK)具体包、检查点(checkpoint)介质、specialist_results 容器形态（dict vs list）。
6. 外部确认：播放器是否依赖 `duration_ms` 推断内容长度（ADR-023 第 629 行外部依赖，阻塞后果评估）。
7. 观测项：调度器(Scheduler)输入带真实毫秒后，观测 大语言模型(LLM)是否试图输出时刻或做时间算术（时刻是输入不是输出，理论上不违反本层约束，需 基准评测(benchmark)确认）。
8. `inspect_window` 观测要点（本轮刻意不预告 桩实现(stub)不可用）：
  - 调用触发场景（何种证据缺口想到取证）
  - 调用频次与分布（单集调用次数）
  - `question` 质量（是否具体、是否真指向该窗口）
  - 收到不可用后的行为（继续 / 重试 / 弃权(abstain)比例）
  - 护栏：第一版本即设单集调用次数宽松上限 N（具体值由首轮观测反推）
