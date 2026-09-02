# Drama Highlight Mark V2

短剧即时互动生成工作流 V2。输入一集短剧的内容证据，输出位置合适、类型多样、不过度打断观看的即时互动配置。

V2 是对 V1「高光 → 互动」链路的架构级重构。

- 设计决策见 [架构决策记录(ADR)](docs/drama-interaction-v2-ADR.md)
- 产品需求见 [产品需求文档(PRD)](docs/drama-interaction-v2-PRD.md)
- 最终输出格式见 [契约(schema)](docs/schema.md)

> 状态：开发中。V1 链路（[v1/README.md](v1/README.md)）仍可运行，用于 基准评测(benchmark)对照。

## 与 V1 的区别

V1 以「剧情高光」作为五类互动的统一入口。V2 的核心变化：

1. **删除高光(Highlight)瓶颈**。高光价值不等于互动价值——未揭晓的悬念、可接话台词、反差动作都可能是优质互动点。
   五类生成专家(Specialist)直接面向共享证据(Evidence)各自找点并生成，其成立前提是证据(Evidence)只共享客观、可引用的证据：
   - 证据内容：台词、画面文字、客观的视觉 / 音频观察
   - 不含：情绪标签、悬念判断、互动价值等任务特定剧情解释（ADR-002）
2. **证据锚点替代模型自报时间**。共享证据(Evidence)以固定 3 秒窗口组织，触发位置使用 `window_id + transcript_segment_id?` 引用，可程序验证，不要求模型输出毫秒级精确时间（ADR-011）。
3. **局部校验与故障隔离**。确定性校验在各生成专家(Specialist)分支内完成；候选失败只做定向修复。
   单分支失败不影响其他分支，异常进入 `WAITING_FOR_HUMAN` 并支持从检查点(checkpoint)恢复，而非整集重跑（ADR-013 ~ 016）。
4. **模型语义输出只用离散状态**。全程不要求模型自报置信度(confidence) / 概率(probability) / 评分(score)。
   证据不足以安全生成时生成专家(Specialist)显式 `abstain`；语义调度只返回离散候选(candidate)标识(IDs)（ADR-012）。

工作流框架为 LangGraph。

- 通过旧版证据适配器(Legacy Evidence Adapter)复用 V1 片段(segments)作为证据来源；该适配器(Adapter)是临时兼容层。
- 未来真正的多模态证据抽取(Evidence Extraction)只需输出同一 `EvidenceWindow[]` 契约即可替换（ADR-007）。

## 范围

- 固定支持五类互动，不增不减：`emotion_button` / `repeat_keyline` / `instant_vote` / `deferred_vote` / `side_comment`。
- 集尾 `episode_comment` 不在本工作流范围内。
- 本版本不包含：
  - 剧情分支与人工智能生成内容(AIGC)分支内容生成
  - 前端播放器与业务服务
  - 跨集剧情摘要、新的自动语音识别(ASR) / 光学字符识别(OCR) / 多模态证据抽取(Evidence Extraction)实现
  - 每个候选固定追加的在线大语言模型(LLM)评审器(Critic)（PRD §3.2）
- 静态上下文(Static Context)（剧名、角色表、简介）只作身份与专名理解的背景。
- 当前集互动涉及的具体剧情事实必须由当前集证据(Evidence)支撑，不能由简介替代（ADR-010）。
- 同一局部时刻可保留多个候选进入候选池(Candidate Pool)，但最终展示最多 1 个互动（ADR-017）。

## 架构

```text
V1 segments + Static Context
          ↓
  Legacy Evidence Adapter
          ↓
  EvidenceWindow[]
          ↓
 ┌────────────────────────────────────────────────┐
 │      五类 Specialist 并行（五路彼此隔离）          │
 │  Emotion / Repeat / Instant / Deferred /       │
 │  Comment —— 分支内部校验与修复结构见下图            │
 └────────┬──────────────────────────┬────────────┘
    通过 ↓                           ↓ 自动修复与局部重试耗尽 /
  Candidate Pool                     分支持续失败 / abstain 需人工
         ↓                           ↓
  Deterministic Render（锚点 → 毫秒，确定性打乱，ADR-023）  HITL
         ↓
  Deterministic Constraints（含 deferred_vote 时间校验）
 （去重 / 冲突组 / 间隔 / cooldown / budget）
         ↓
  Semantic Scheduler ── 无法返回合法选择 ──→ HITL
         ↓
  Final Deterministic Check
         ↓
  Selected Interactions
```

每个生成专家(Specialist)分支内部（×5 同构）：

```text
EvidenceWindow[]
      ↓
Specialist（找点 + 绑证据 + 生成 payload） ←──── 定向退回，只修这一条
      ↓                                           │
Local Constraint Validation（分支内）               │
 通过 ↓              ↓ fail                        │
      │        安全程序修复（确定性，若可行）          │
      │            ↓ 修复无效                       │
      │        局部 Retry ─────────────────────────┘
      │            ↓ 仍失败
      ↓            ↓
Candidate Pool   HITL
```

全链路的大语言模型(LLM)调用只出现在两类节点：五类生成专家(Specialist)与语义调度器(Semantic Scheduler)。

- 分支内的失败处理优先使用确定性程序修复，仅当需退回生成专家(Specialist)重生成时才再次调用大语言模型(LLM)。
- 其余校验、汇聚与约束处理均为确定性程序逻辑。

生成专家(Specialist)为纯文本模型，不直接接触原视频 / 原音频。

- 需补充证据时调用 `inspect_window(window_id, question)`，由证据(Evidence)服务(Service)返回文本化补充证据（本轮仅冻结契约，不实现新的多模态提取）。

人工介入(HITL)是异常兜底而非常规审批；人工 `accept / edit / drop` 处理后从检查点(checkpoint)恢复，继续后续节点，已完成证据(Evidence)与成功生成专家(Specialist)不重跑。

## 项目结构（目标形态）

V2 代码按以下组织，尚未全部实现：

```text
drama-highlight-mark/
├── README.md                     # 本文档（V2 说明）
├── v1/                           # V1 收拢代码（说明见 v1/README.md）
├── pyproject.toml                # 依赖与工具链（uv + ruff + pytest）
├── .env.example
├── langgraph.json                # LangGraph Studio / langgraph dev 可视化调试入口
├── docs/                         # 设计文档与业务契约
├── src/drama_interaction/        # V2 主包
│   ├── config.py                 # 显式配置：窗口 / budget / 间隔 / cooldown
│   ├── llm.py                    # OpenAI 兼容 client 封装
│   ├── schemas/                  # 数据契约层（纯 pydantic，无 IO / 无 LLM）
│   │   ├── evidence.py           #   EvidenceWindow / TranscriptSegment
│   │   ├── candidate.py          #   TriggerAnchor / Candidate / SpecialistResult
│   │   └── interaction.py        #   最终 5 类互动输出契约
│   ├── evidence/
│   │   ├── adapter.py            #   Legacy Adapter：V1 segments → EvidenceWindow[]（临时）
│   │   └── service.py            #   inspect_window() contract/stub，文本化补充证据
│   ├── specialists/              # 五类 Specialist，一类一个模块（prompt + 节点逻辑）
│   │   ├── base.py               #   公共骨架：输入、LLM 调用、解析、abstain
│   │   └── emotion_button.py     #   repeat_keyline / instant_vote /
│   │                             #   deferred_vote / side_comment 同构
│   ├── validation/
│   │   ├── rules.py              #   确定性校验规则（schema / 锚点 / payload 约束 / 重复）
│   │   └── repair.py             #   安全程序修复（确定性）→ 定向退回原 Specialist（LLM）
│   ├── scheduling/
│   │   ├── constraints.py        #   确定性全局约束；代表时间点解析与 resolve_anchor（渲染共用）
│   │   └── semantic.py           #   语义调度（LLM 只返回 candidate IDs）
│   ├── graph/                    # LangGraph 组装层（框架接入点集中于此）
│   │   ├── state.py              #   Workflow State 与并行汇聚 reducer
│   │   ├── nodes.py              #   节点函数，只编排上述模块；含 render_node（渲染）
│   │   └── builder.py            #   StateGraph / RetryPolicy / checkpointer / interrupt
│   └── cli.py                    # run / resume / export 命令
├── tests/                        # unit_tests / integration_tests / fixtures
├── benchmark/                    # 离线评测：golden 数据资产 + 对照脚本
│   ├── golden/evidence/          #   3–5 集人工校正 EvidenceWindow[]
│   └── golden/cases/             #   20–50 个标注互动机会
└── data/
    ├── video/ audio/ text/ highlight/ interaction/ branch/   # V1 输入与产物（对照与 smoke test）
    ├── evidence/                 # V2 Legacy Adapter 输出（临时，供人工校正回流 golden）
    └── interaction_v2/           # V2 产物：最终互动 JSON 与执行状态（runs/<execution-id>/）
```

分层原则：

- `schemas/` 是纯契约层；`validation/rules.py` 与 `scheduling/constraints.py` 是纯确定性逻辑，均可在无网络、无模型环境下完整测试。
- 所有非确定性（大语言模型(LLM)调用）集中在 `specialists/`、`scheduling/semantic.py`、`validation/repair.py` 三处。
- LangGraph 框架接入集中在 `graph/`，框架版本升级的破坏性变更不外溢。

## 安装

```bash
pip install -e .
```

环境要求：Python 3.10+、一个兼容 OpenAI 接口(API)的文本模型接口。V2 链路不需要 `ffmpeg`（仅 V1 链路需要）。

在项目根目录创建 `.env`：

```env
LLM_MODEL_ID=your-llm-model-id
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://your-llm-endpoint/v1
```

## 使用

输入为 V1 `03_audio2text` 产出的片段(segments) JSON（旧版适配器(Legacy Adapter)的输入契约，PRD §3.3 / ADR-007）：

```bash
# 生成一集互动配置
python -m drama_interaction run data/text/某短剧/第1集.json

# 批量处理整部剧
python -m drama_interaction run data/text/某短剧/

# 存在待人工处理项时，处理后从 checkpoint 恢复
python -m drama_interaction resume --thread <execution-id>

# 从已持久化的执行状态导出最终互动 JSON，不重新执行任何节点
python -m drama_interaction export --thread <execution-id>
```

`run` 启动时生成 `execution-id`（作为 LangGraph 检查点(checkpoint)的线程标识(thread id)）并随运行输出。

- 最终互动 JSON 写入 `data/interaction_v2/<剧名>/<集名>.json`。
  - 格式与 V1 一致（`id / type / show_at / duration_ms / payload`），播放器可直接消费。
  - 字段定义见 [docs/schema.md](docs/schema.md)。
- 从锚点到最终毫秒字段的确定性渲染规则见 [ADR-023](docs/drama-interaction-v2-ADR.md)。
- 执行状态（检查点(checkpoint)与人工介入(HITL)待处理项）持久化在 `data/interaction_v2/runs/<execution-id>/`。
- 旧版适配器(Legacy Adapter)输出的 `EvidenceWindow[]` 落盘至 `data/evidence/`，供人工校正后回流黄金用例(golden fixture)（适配器(Adapter)本身是临时层）。

## 配置

以下参数均为显式配置，不写死在提示词(Prompt)中：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `window_size_ms` | 3000 | 证据(Evidence)窗口长度（已确定） |
| `interaction_budget` | 基准评测(benchmark)后定 | 单集互动数量上限 |
| `min_interaction_spacing_ms` | 基准评测(benchmark)后定 | 相邻互动最小间隔 |
| `type_cooldown_ms` | 基准评测(benchmark)后定 | 同类型互动冷却时间 |

渲染参数组（锚点 → 毫秒的确定性渲染，规则见 ADR-023）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 五类 `type_base`（时长表） | 基准评测(benchmark)后定 | `emotion_button` 2500–3000 / `instant_vote` 3500–4000 / `deferred_vote` 3500–4000 / `side_comment` 2500–3000，直接取 `type_base`、无截断(clamp)；运行期为单一标量，开发期默认区间下限；`repeat_keyline` 除外——见下行，为唯一截断(clamp)类型 |
| `keyline_tail_ms` | 700 | `repeat_keyline` 锚区间 + 此尾量，截断(clamp)至专属上下限（已定，沿用 V1） |
| `KEYLINE_DURATION_FLOOR` / `KEYLINE_DURATION_CEIL` | 2500 / 4500 | `repeat_keyline` 专属截断(clamp)上下限，**代码常量不入 config**（跟读台词的生理时间范围，非调参对象） |
| `reveal_display_ms` | 待定 | `deferred_vote` 揭晓展示时长 |
| `reveal_gap_min_ms` | 待定 | `deferred_vote` 揭晓距提问的最小间隔 |

> `repeat_keyline` 上下限 `KEYLINE_DURATION_FLOOR = 2500` / `KEYLINE_DURATION_CEIL = 4500` 为代码常量（见上行，不进 config）。
>
> 配置(config)装载期执行派生校验 `min_interaction_spacing_ms >= max(全部 type_base, KEYLINE_DURATION_CEIL)`，违者快速失败(fail fast)；右边从配置(config)数据现算。

## 基准评测(Benchmark)

`benchmark/golden/` 存放人工校正的证据时间线与标注互动机会，用于隔离上游误差、独立评价后半链路。

- 黄金用例(golden fixture)优先于后半链路开发（黄金用例优先(fixture-first)，ADR-020）；V1 / V2 对照使用同一份校正证据(Evidence)输入。
- 评估维度：互动发现、触发正确性、内容质量、调度质量、工作流鲁棒性、可观测性（模型调用 / 重试(Retry) / 人工介入(HITL)次数与耗时）。
- 大语言模型裁判(LLM-as-a-Judge)仅作离线辅助。

## 路线图

- [ ] 数据契约层（证据窗口(EvidenceWindow) / 候选(candidate) / 互动(Interaction)契约(schema)）与旧版适配器(Legacy Adapter)
- [ ] 黄金用例(golden fixture)人工校正（3–5 集证据 + 20–50 个标注互动机会，黄金用例优先(fixture-first)）
- [ ] LangGraph 图骨架：五路并行、状态汇聚、检查点(checkpoint)
- [ ] 五类生成专家(Specialist)实现
- [ ] 校验与调度层
- [ ] 人工介入(HITL)与命令行(CLI)
- [ ] V1 / V2 对照基准评测(benchmark)
