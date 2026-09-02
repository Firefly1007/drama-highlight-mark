# 短剧即时互动生成工作流 V2 — 架构决策记录(ADR)

- 文档类型：架构决策记录集(ADR)
- 版本：v0.6
- 日期：2026-09-02
- 状态：核心架构决策 已接受(Accepted)；少量实现参数 延后(Deferred)

## 变更记录（v0.5 → v0.6）

ADR-023 原地修订，内容已同步至 docs/plans/ 各规划文件。落实 2026-09-02 七条决策：

- 金句台词(keyline)不强制 `segment_id`；
- `resolve_anchor` 二分支定稿，唯一实现落 scheduling/constraints.py；
- 时间字段全程序生成，大语言模型(LLM)侧零毫秒；
- 延时投票(deferred_vote)时间校验前移至冲突组之前；
- inspect_window 不在 提示词(Prompt)预告不可用；
- 渲染提前到候选池(Candidate Pool)之后；
- 不设全局时长护栏。

其余修订点：

- 渲染位置从「调度器(Scheduler)之后、落盘之前」提前到「候选池(Candidate Pool)之后、确定性约束处理之前」；
- 删除全局 `DURATION_FLOOR` / `DURATION_CEIL` 护栏，`repeat_keyline` 改用专属上下限代码常量（`KEYLINE_DURATION_FLOOR` / `KEYLINE_DURATION_CEIL`），其余四类直接取 `type_base`；
- 补入延时投票(deferred_vote)时间检查调用时机（候选池(Candidate Pool)之后、冲突组之前）与 `spacing` 派生校验（配置(config)装载期 快速失败(fail fast)）。

---

## ADR-001：删除 高光(Highlight)作为统一中间瓶颈

状态：已接受(Accepted)

### 背景(Context)

V1 使用：

```text
Evidence → Highlight Detection → 5 Interaction Modules
```

高光价值与互动价值并不等价，一些普通冲突、未揭晓问题、可接话台词或反差动作仍可能是优质互动点。

### 决策(Decision)

V2 删除 高光(Highlight)作为五类互动的强制前置层。

五类生成专家(Specialist)直接从共享证据(Evidence)中寻找各自类型的互动机会。

### 影响(Consequences)

- 提高非高光互动机会的召回空间；
- 不同互动类型可以使用不同标准；
- 类型冲突由下游调度器(Scheduler)统一处理。

---

## ADR-002：共享证据(Evidence)，不共享任务特定剧情解释

状态：已接受(Accepted)

### 背景(Context)

共享层过重会演化成新的通用剧情理解瓶颈，并把错误传播给所有生成专家(Specialist)。

### 决策(Decision)

共享层只保留文本模型可消费的证据：

- 台词文本(transcript)；
- 屏上文本(on-screen text)；
- 客观视觉(visual)观测(observations)；
- 客观音频(audio)观测(observations)；
- 不确定性(uncertainty)。

不共享：

- 情绪标签；
- 悬念判断；
- 人物目标；
- 关系变化；
- 互动价值；
- 模型置信度(confidence) / 评分(score)。

### 影响(Consequences)

- 证据(Evidence)更客观、可复用；
- 生成专家(Specialist)保留任务特定推理自由；
- 五类生成专家(Specialist)仍会存在合理的上下文重复推理。

---

## ADR-003：共享(Shared)证据(Evidence)采用 3 秒固定非重叠窗口

状态：已接受(Accepted)

### 背景(Context)

V1 由模型自行决定片段(segment)边界并输出精确时间，实际时间线(Timeline)不够可靠。后续又需要稳定检索、验证、人工校正和基准评测(benchmark)单位。

### 决策(Decision)

共享(Shared)证据(Evidence)的组织单位为固定 3 秒窗口(window)：

```text
list[EvidenceWindow]
```

窗口：

- 固定 3 秒；
- 默认不重叠；
- 是组织 / 检索 / 验证单位；
- 不被视为精确事件时间。

集(episode)级元数据不为此额外包一层对象，而放在工作流状态(Workflow State)。

### 影响(Consequences)

- 数据结构简单稳定；
- 方便窗口(window) based retrieval / 校验(Validation) / 基准评测(benchmark)；
- 跨窗口证据需要明确复制策略。

---

## ADR-004：台词文本(Transcript)跨窗口完整复制，不建立独立引用仓库

状态：已接受(Accepted)

### 背景(Context)

一条自动语音识别(ASR)台词文本(transcript)可能跨越两个固定窗口(window)。建立独立 transcript object store 会增加间接层，而生成专家(Specialist)最终仍需看到实际台词。

### 决策(Decision)

跨越多个窗口(window)的台词文本(transcript)：

- 完整复制到所有相交窗口(window)；
- 保留同一个 `segment_id / start_ms / end_ms / text / speaker_label`；
- 不建立单独台词文本(transcript)对象(object)仓库(store)。

### 影响(Consequences)

- 提示词(Prompt)输入直接、无解引用；
- 数据有少量重复，但重复项拥有相同标识(ID)和时间，不会失去同一性。

---

## ADR-005：匿名 `speaker_label` 可选，不要求角色身份识别

状态：已接受(Accepted)

### 背景(Context)

不同上游自动语音识别(ASR)是否支持说话人(speaker)说话人分离(diarization)不确定；强制真实角色名会把身份识别问题塞进证据(Evidence)层。

### 决策(Decision)

Transcript schema 允许：

```text
speaker_label: str | null
```

若上游能提供说话人分离(diarization)，使用匿名 `speaker_1 / speaker_2`；否则为 null。

不要求共享(Shared)证据(Evidence)将说话人(speaker)映射到真实角色名。

### 影响(Consequences)

- 兼容不同自动语音识别(ASR)能力；
- 保留可用的对话轮次信息；
- 角色身份理解留给更高层。

---

## ADR-006：不让模型制造视觉 / 音频事件的毫秒级精确时间

状态：已接受(Accepted)

### 背景(Context)

通用多模态模型可以理解时间范围内发生了什么，但不能把自行生成的毫秒时间当作可靠测量。

### 决策(Decision)

`visual_observations[]` / `audio_observations[]` 只保存文本观察，不强制精细 `start_ms/end_ms`。

它们继承所在 3 秒窗口(window)。

只有本身具有可靠时间定位来源的台词片段(transcript segment)保留精细时间。

### 影响(Consequences)

- 避免伪精确；
- 视觉 / 音频触发(trigger)只能锚到窗口(window)级别，除非未来上游提供可靠更细定位。

---

## ADR-007：本轮不重做证据(Evidence)提取(extraction)，使用 V1 旧版适配器(Legacy Adapter)

状态：已接受(Accepted)

### 背景(Context)

新的自动语音识别(ASR)、光学字符识别(OCR)、多模态证据(Evidence)提取(extraction)仍需单独设计。如果先把全部上游能力做完，会阻塞后半工作流(Workflow)开发；如果直接让下游依赖 V1 模式(schema)，又会形成强耦合。

### 决策(Decision)

本轮：

```text
V1 segments
  ↓
Legacy Evidence Adapter
  ↓
EvidenceWindow[]
  ↓
V2 downstream workflow
```

暂时映射：

- `text` → 台词文本(transcript)；
- `speech / voice / music / audio_cues` → 音频(audio)观测(observations)；
- `emotion` 不进入共享(Shared)证据(Evidence)；
- 视觉(visual) / 屏上文本(on-screen text)为空。

未来证据(Evidence)提取(extraction)只需输出同一 `EvidenceWindow[]` 契约(contract)，即可替换适配器(Adapter)。

### 影响(Consequences)

- 后半链路可立即开发；
- 下游不绑定 V1；
- 真实端到端效果仍会受到 V1 上游质量限制，因此需要黄金用例(golden fixture)隔离变量。

---

## ADR-008：保留五个 Type-Specific 生成专家(Specialist)，并一次完成"找点 + 生成"

状态：已接受(Accepted)

### 背景(Context)

曾考虑 Opportunity Detector → Eligibility → Router → Generator，但这些层会反复判断"这里是否适合互动"。

### 决策(Decision)

五个生成专家(Specialist)并行，每个只负责一个固定类型(type)，并一次完成：

1. 找到适合本类型(type)的位置；
2. 绑定证据(Evidence)；
3. 给出触发锚点(Trigger Anchor)；
4. 生成载荷(payload)。

### 影响(Consequences)

- 减少重复语义判断；
- 天然支持扇出(fan-out) / 扇入(fan-in)；
- 类型冲突(conflict)交给调度器(Scheduler)。

---

## ADR-009：生成专家(Specialist)可以是纯文本模型

状态：已接受(Accepted)

### 背景(Context)

后续五个业务生成专家(Specialist)不一定使用多模态模型。如果让它们直接回看原视频，工具链就与模型模态能力强绑定。

### 决策(Decision)

生成专家(Specialist)只消费文本化证据(Evidence)。

需要补充证据时可调用：

```text
inspect_window(window_id, question)
```

该工具由证据(Evidence)服务(Service)负责访问原始媒体或未来上游能力，并向生成专家(Specialist)返回文本化补充证据(Evidence)。

生成专家(Specialist)不直接接收原始(raw) video / audio / 帧(frames)。

### 影响(Consequences)

- 业务生成专家(Specialist)可使用便宜、能力更合适的文本模型；
- 多模态能力被封装在证据(Evidence)服务(Service)；
- 本轮可以只定义 `inspect_window()` 契约(contract)，而延后真实多模态实现。

---

## ADR-010：静态上下文(Static Context)只作背景，当前集事实必须由当前集证据(Evidence)支撑

状态：已接受(Accepted)

### 决策(Decision)

所有生成专家(Specialist)可访问剧名、角色表、简介，但当前集互动中的具体事实必须绑定当前集证据(evidence)。

第一版不额外生成跨集剧情摘要。

---

## ADR-011：触发(Trigger)使用证据锚点，不输出伪精确时间

状态：已接受(Accepted)

### 背景(Context)

模型自行生成 `trigger_time=32741ms` 会制造无法验证的精度。

### 决策(Decision)

候选(Candidate)使用：

```text
trigger_anchor:
  window_id
  transcript_segment_id?  # 可选
```

- 对明确台词，可锚到台词片段(transcript segment)；
- 对视觉 / 音频事件，可锚到窗口(window)；
- 不要求大语言模型(LLM)输出绝对毫秒事件时刻。

`deferred_vote.reveal_anchor` 使用同类结构。

### 影响(Consequences)

- 触发(trigger)与证据(evidence)直接关联；
- 可程序验证引用合法性；
- 播放器最终时间转换与业务输出格式可独立处理。

---

## ADR-012：生成专家(Specialist)输出不使用置信度(confidence) / 概率(probability) / 自评分(self-score)

状态：已接受(Accepted)

### 决策(Decision)

禁止用模型自报数字作为：

- 类型路由；
- Top-K；
- 人工介入(HITL)阈值；
- 调度器(Scheduler)排序。

使用可观察离散状态，例如：

- `abstain`；
- 证据(evidence)缺失；
- 约束(constraint)失败(fail)；
- 重试(Retry)失败(fail)；
- 冲突(conflict)。

---

## ADR-013：局部约束校验(Local Constraint Validation)位于候选池(Candidate Pool)之前

状态：已接受(Accepted)

### 背景(Context)

候选(candidate)的模式(schema) / 锚点(Anchor) / 载荷(payload)错误应该在自己的生成专家(Specialist)分支内处理，不能污染全局池(Pool)。

### 决策(Decision)

每个生成专家(Specialist)输出后先执行本地确定性校验(Validation)。

只验证程序能稳定判断的约束(constraint)，例如：

- 模式(schema)；
- 证据(evidence)引用(refs)；
- 触发(trigger) / 揭晓(reveal)锚点(Anchor)合法性；
- 载荷(payload)字段数量；
- 文本长度；
- 明显重复。

不设置固定在线大语言模型(LLM)评审器(Critic)。

### 影响(Consequences)

- 故障影响范围小；
- 候选池(Candidate Pool)只接收合法候选；
- 语义质量主要通过生成专家(Specialist) + 离线基准评测(benchmark)改进。

---

## ADR-014：候选(candidate)失败采用局部定向修复(Repair) / 重试(Retry)

状态：已接受(Accepted)

### 决策(Decision)

失败处理：

1. 确定性(Deterministic)校验(Validation)；
2. 仅做安全的程序修复(Repair)；
3. 仍失败时把"原候选(candidate) + 明确错误 + 必要局部证据(evidence)"退回原生成专家(Specialist)；
4. 只允许修复(Repair)该候选(candidate)；
5. 再失败进入人工介入(HITL)。

禁止重新扫描整集或修改其他成功候选(candidate)。

---

## ADR-015：五路生成专家(Specialist)采用部分故障隔离(partial failure isolation)

状态：已接受(Accepted)

### 决策(Decision)

- 五路并行分支各自重试(Retry)；
- 成功结果立即持久化；
- 单路持续失败只让该分支进入人工介入(HITL)；
- 其他成功结果不重跑、不丢失。

---

## ADR-016：人工介入(HITL)使用 WAITING_FOR_HUMAN + 检查点(checkpoint)恢复(resume)

状态：已接受(Accepted)

### 决策(Decision)

异常需要人工处理时：

- 成功结果已持久化；
- 工作流(Workflow)状态(State)进入 `WAITING_FOR_HUMAN`，而不是 `FAILED`；
- 最终发布暂停；
- 人工支持 `accept / edit / drop`；
- 处理后从检查点(checkpoint)恢复(resume)；
- 已完成证据(Evidence)和成功生成专家(Specialist)不重跑。

人工介入(HITL)是异常路径，不是所有结果的常规审核。

---

## ADR-017：同一局部时刻最终最多展示一个互动

状态：已接受(Accepted)

### 决策(Decision)

候选池(Candidate Pool)可以保留同一局部时刻的多个不同类型候选(candidate)，但最终选中集合(selected set)中最多保留 1 个。

具体冲突(conflict)组(group)时间规则待基准评测(benchmark)后确定。

---

## ADR-018：调度器(Scheduler)采用"确定性约束优先 + 必要时语义选择"

状态：已接受(Accepted)

### 背景(Context)

纯规则无法判断"两个都合法的互动哪个更值得留"；但让大语言模型(LLM)每集重新分析完整集(episode)会重复生成专家(Specialist)的工作。

### 决策(Decision)

程序先处理：

- 重复(duplicate)；
- 局部(Local)冲突(conflict)；
- 最小(min)间隔(spacing)；
- 类型(type)冷却(cooldown)；
- 集(episode)预算(budget)。

只有出现真正语义选择时才调用大语言模型(LLM)。

大语言模型(LLM)输入只包含：

- 待选择候选(candidates)；
- 对应局部证据(evidence)；
- 已选择互动摘要；
- 剩余预算(budget)；
- 明确硬约束(constraint)。

大语言模型(LLM)返回候选(candidate)标识(ID)，不返回评分(score) / 概率(probability)。

最终再执行最终确定性校验(Final Deterministic Check)。

### 影响(Consequences)

- 调度器(Scheduler)不成为第六个完整剧情分析器；
- 保留必要语义选择能力；
- 结果仍可由程序终检。

---

## ADR-019：互动数量使用显式配置预算(budget)

状态：已接受(Accepted)

### 决策(Decision)

显式配置：

```text
window_size_ms = 3000
interaction_budget
min_interaction_spacing_ms
type_cooldown_ms
```

其中 `window_size_ms=3000` 已确定，其余参数在基准评测(benchmark)后调参。

调度器(Scheduler)可以少选，但不得超预算(budget)。

---

## ADR-020：用黄金用例(golden fixture)隔离 V1 上游误差

状态：已接受(Accepted)

### 背景(Context)

V1 时间线(Timeline)本身存在时间与内容误差。如果直接用真实 V1 输出调下游，很难区分是证据(Evidence)错还是生成专家(Specialist) / 调度器(Scheduler)错。

### 决策(Decision)

准备 3–5 集人工校正证据(Evidence)时间线(Timeline)，形成黄金用例(golden fixture)，并整理约 20–50 个代表性互动机会。

后半链路优先在黄金用例(golden fixture)上开发与基准评测(benchmark)；V1 适配器(Adapter)的真实输出用于端到端冒烟测试(smoke test)。

### 影响(Consequences)

- 可以独立评价下游(downstream)工作流(Workflow)；
- 后续替换证据(Evidence)提取(extraction)时仍可复用基准评测(benchmark)；
- 需要少量人工校正成本。

---

## ADR-021：语义质量采用离线基准评测(benchmark)，不做在线评审(Judge)闭环

状态：已接受(Accepted)

### 决策(Decision)

离线评估覆盖：

- 互动(Interaction)发现(discovery)；
- 触发(trigger)正确性(correctness)；
- 内容(content)质量(quality) / 实据(grounding) / 剧透(spoiler)；
- 最终调度(scheduling)质量(quality)；
- 工作流(Workflow)鲁棒性(robustness)；
- 调用次数、重试(Retry)、人工介入(HITL)、耗时等可观测性(observability)。

大语言模型(LLM)-as-a-Judge 只能作为离线辅助，不作为生产链路必经节点。

---

## ADR-022：工作流框架选用 LangGraph

状态：已接受(Accepted)

### 背景(Context)

V2 后半链路包含五路并行生成专家(Specialist)、局部修复(Repair) / 重试(Retry)、分支故障隔离、`WAITING_FOR_HUMAN` 状态(State)与检查点(checkpoint)恢复(resume)。

这些需求需要统一的状态管理与可编排的执行图，而不是继续堆叠脚本式流水线。候选包括自研状态机、Temporal 等重型编排框架与 LangGraph。

### 决策(Decision)

V2 后半链路（从旧版适配器(Legacy Adapter)到最终互动(FinalInteraction)）使用 LangGraph 实现：

- 用 `StateGraph` 表达生成专家(Specialist)扇出(fan-out) / 扇入(fan-in)、校验(Validation)、调度器(Scheduler)等节点；
- 用 LangGraph 检查点(checkpoint)持久化支撑 `WAITING_FOR_HUMAN` 与恢复(resume)；
- 证据(Evidence)契约(contract)（`EvidenceWindow[]`）与 LangGraph 状态(State)分层：证据(Evidence)是共享数据契约(contract)，工作流(Workflow)状态(State)承载集(episode)级元数据与节点进度。

### 影响(Consequences)

- 复用 LangGraph 的持久化、恢复(resume)与中断原语，不自研检查点(checkpoint)；
- 五路生成专家(Specialist)天然映射为并行分支，与ADR-015 的故障隔离语义一致；
- 引入 LangGraph 依赖与框架学习成本；
- 节点边界需与ADR-013 / ADR-014 的局部校验与定向修复(Repair)语义对齐，避免把整集重跑隐藏在图(Graph)结构里。

---

## ADR-023：锚点 → 最终输出的确定性渲染规则

状态：已接受(Accepted)

### 背景(Context)

V2 全链路候选只携带证据锚点（`window_id + transcript_segment_id?`，ADR-011），而播放器最终消费 `show_at` / `duration_ms` / `reveal_time` / `reveal_delay` 绝对毫秒字段。

- 最终输出字段定义见 docs/schema.md。

锚点在哪一步、按什么规则变成毫秒，此前未定义，是输入→输出链路上唯一缺失的环节（渲染断点）。

V1 的换算经验已被数据证伪（对 V1 全部 2103 条互动产物的统计）：

- `duration_ms = trigger_segment.end + 700ms`（截断至 5000）在 50.3% 的条目被上限截断成常数 5000，同时 9.8% 短于 3 秒（最短 1210ms）——一半时间公式失效为常数，另一半时间制造不可用的互动；
- 互动总占用画面时长过高：实测 93% 的集短于 4 分钟（中位 2.2 分钟），按 V1 中位 5 秒 × 单集多条互动，悬浮组件可占全集画面时间近 20%；
- V1 选项打乱使用无种子 `random.shuffle`（约定 `options[0]` 为正确答案），破坏确定性。

### 决策(Decision)

渲染为确定性纯函数，位于候选池(Candidate Pool)之后、确定性约束处理（确定性(Deterministic)全局(Global)约束(constraint)）之前，即图(Graph)中的 `render_node`。理由：

- 全链路只算一次真实毫秒，消除「分支内预演值」与「渲染落盘值」两个口径不一致的缝隙；
- 终检位于渲染之后，直接验证最终互动(FinalInteraction)的真实毫秒，不再「验中间态、输出另一份值」；
- 硬约束(constraint)：确定性打乱种子 `hash(execution_id + candidate_id)` 依赖池(Pool)生成的 `candidate_id`，渲染不能早于池(Pool)。

核心是一个共用解析函数 `resolve_anchor`，**唯一实现位于 `scheduling/constraints.py`**，渲染与约束处理共用同一份代码（`render_node` import 它）。本函数只有这一个判断分支，不插值、不推断窗口内偏移：

```text
resolve_anchor(anchor) → {start_ms, end_ms}
  有 transcript_segment_id → 该 segment 的 start_ms / end_ms
  无 transcript_segment_id → 所在 window 的 start_ms / end_ms
```

四个字段的规则：

```text
show_at      = resolve_anchor(trigger_anchor).start_ms
duration_ms  = repeat_keyline：clamp(锚区间 + keyline_tail_ms,
                                     KEYLINE_DURATION_FLOOR, KEYLINE_DURATION_CEIL)
                有 transcript_segment_id → 锚区间 = segment 的 (end_ms - start_ms)
                无 transcript_segment_id → 锚区间 = window_size_ms（3000，恒为 3700）
              其余四类 → 直接取 type_base，无 clamp
                （type_base 运行期为每类单一标量——benchmark 冻结前开发期默认取
                 区间下限：2500 / 3500 / 2500，保证渲染确定性不变量不被区间破坏）
reveal_time  = resolve_anchor(reveal_anchor).start_ms      # 仅 deferred_vote
reveal_delay = reveal_display_ms                            # 配置常量，与锚点无关
```

**纯窗口锚退化（预期行为）**：无 `transcript_segment_id` 时锚区间长恒为 `window_size_ms`（3000），`repeat_keyline` 时长退化为 `clamp(3700, …) = 3700` 常数。

这是诚实行为而非缺陷：视觉 / 音频锚点本就没有比 3 秒窗口更细的定位来源（ADR-006），此时自适应无信息可依。代价仅为这类金句台词(keyline)时长不再随台词长短变化；基准评测(benchmark)阶段统计纯窗口锚占比，用数据决定是否值得引入更细定位来源。

**金句台词(keyline)上下限为代码常量**：`KEYLINE_DURATION_FLOOR = 2500` / `KEYLINE_DURATION_CEIL = 4500` 是代码常量（不进配置(config)），与 `keyline_tail_ms = 700` 同待遇。

理由：跟读金句的生理时间范围不是调参对象。

不设全局 `DURATION_FLOOR` / `DURATION_CEIL` 护栏；其余四类配置若越界，其防重叠后果由下方 `spacing` 派生校验兜住，单类时长本身的合理性由基准评测(benchmark)观测发现。

时长基准（按 2.2 分钟中位集长重新标定，数值进入配置(config)，基准评测(benchmark)调参）：

| type | type_base | 说明 |
|------|-----------|------|
| emotion_button | 2500–3000 | 单击动作，无需阅读 |
| repeat_keyline | 2500（实际取 锚区间+尾部(tail)，见上方公式） | 唯一内容自适应类型：用户需跟读完整台词 |
| instant_vote | 3500–4000 | 读题 + 选项 + 点击的最短必要时间 |
| deferred_vote | 3500–4000 | 同上 |
| side_comment | 2500–3000 | 纯阅读，不承载操作 |

`keyline_tail_ms` 沿用 V1 的 700。

**延时投票(deferred_vote)的时间合法性检查**：规则定义在 `rules.py` 分组 B；调用时机在候选池(Candidate Pool)之后、冲突组之前（先淘汰、再竞争）。

若顺序颠倒，一个时间不合法的延时投票(deferred_vote)会先参与「同刻只选一个」竞争、挤掉同位置合法候选，随后自己被丢弃使该位置空出——语义调度白做一轮，合法候选被无辜淘汰。规则：

```text
reveal_time >= show_at + duration_ms + reveal_gap_min_ms   # 晚于且晚够展示期
```

失败处理：直接放弃该候选（丢弃并记录原因，供基准评测(benchmark)统计），不进入定向修复(Repair) ——延时投票(deferred_vote)不是必须存在的类型，揭晓位置不合适时正确动作是不要这个互动，而不是逼生成专家(Specialist)重找一个合格的揭晓位置。

丢弃动作复用确定性约束已有的淘汰 / 合并候选清单机制（含原因），不另走修复(Repair)修复(Repair)链；渲染提前后，此校验消费的是渲染产出的真实毫秒。

不设揭晓距离上界（V1 存在揭晓距提问超 60 秒的案例，中位 33.5 秒；是否收紧待基准评测(benchmark)观测数据说话）。

**生成专家(Specialist)侧零毫秒**：全部时间字段（`show_at` / `duration_ms` / `reveal_time` / `reveal_delay`）一律由渲染环节程序生成，大语言模型(LLM) / 生成专家(Specialist)侧一律不输出毫秒。

`reveal_time` / `reveal_delay` 位于延时投票(deferred_vote)载荷(payload)内、生成侧必须为 null，揭晓位置由 `Candidate.reveal_anchor` 承载。

大语言模型(LLM)若输出毫秒属结构性违规（ADR-011），分支内校验（生成侧零毫秒禁令）检测后直接置空——可安全程序修复(Repair)，不改变业务语义，渲染会重算。

**确定性选项打乱**：V1 的「`options[0]` 为正确答案」约定保留，但打乱改为确定性种子：

```text
shuffle_seed = hash(execution_id + candidate_id)
```

同输入同输出（保住适配器(Adapter)幂等与基准评测(benchmark)对照的可复现性），同时消除模型的位置偏差（正确答案永远在第一位的偏置不进入产品）。渲染提前到池(Pool)之后后，打乱必然发生在终检之前，自动满足。

**未被调度选中的候选同样被打乱**——确定性种子保证无副作用。

打乱选项的同时，`render_node` 必须将 `answer_id` 重映射为正确项在打乱后数组中的新索引——打乱后原索引必然失效。

该重映射由渲染负责（V1 `shuffle_deferred_vote_options` 即此语义），终检据此校验「`answer_id` 与打乱后选项索引一致」。

**类型(type)数字映射与输出排序**：

- 类型(type) 1–5：`1=emotion_button` / `2=repeat_keyline` / `3=instant_vote` / `4=deferred_vote` / `5=side_comment`；
- 具体数值见 `v1/pipline/common/schemas.py:248-252`（数值明确可查，非待定）；
- 最终数组按 `(show_at, duration_ms)` 排序，`id` 为 1-based 自增。

### 影响(Consequences)

- 互动时长不再携带内容信息；若播放器侧存在依赖 `duration_ms` 推断内容长度的逻辑会失效（需与播放器确认一次）。
- 间隔按开始点差值度量，互动实际占画面到 `show_at + duration`；配置(config)装载时执行派生校验 `min_interaction_spacing_ms >= max(全部 type_base, KEYLINE_DURATION_CEIL)`，违者快速失败(fail fast)。
  - 右边从配置(config)数据现算，不引入新常量。
- 时长成为类型常数后，`spacing` 的调参语义变干净（间隔不再与随机时长叠加），防重叠由此派生校验保证，不再依赖单类时长护栏。
- 渲染提前后，时间合法性校验 / 冲突组 / 调度 / 终检消费同一份真实毫秒。
- 终检（位于渲染之后）直接验最终互动(FinalInteraction)取值合法性：
  - 毫秒字段非负；
  - 金句台词(keyline)时长在 `[KEYLINE_DURATION_FLOOR, KEYLINE_DURATION_CEIL]` 内；
  - `reveal_time` 晚于 `show_at + duration_ms`；
  - `answer_id` 与打乱后选项索引一致。
- 渲染节点为 `render_node`（原 `render_export`）；图(Graph)-状态(State)区分 `rendered_candidates` / `selected_candidates` / `final_interactions` 三层。
- 渲染断点消解：`graph/nodes.py` 的 `render_node` 节点、`schemas/interaction.md` 的毫秒字段来源、`cli.md` 的导出行为全部落地。

---

## 延后(Deferred)决策(Decisions)

以下决策当前有意延后：

1. 真正自动语音识别(ASR) / 光学字符识别(OCR) / 多模态证据(Evidence)提取(extraction)的实现；
2. `inspect_window()` 的真实多模态内部实现；
3. 五个生成专家(Specialist)的最终提示词(Prompt)；
4. 五类载荷(payload)的详细模式(schema)；
5. 冲突(conflict)组时间规则；
6. `interaction_budget / min_interaction_spacing_ms / type_cooldown_ms` 数值；
7. 调度器(Scheduler)提示词(Prompt)；
8. 人工介入(HITL)界面(UI)与最终持久化介质（检查点(checkpoint)已由ADR-022 确定使用 LangGraph 持久化，具体后端存储仍待定）；
9. 基准评测(benchmark)标注细则与指标(metrics)阈值；
10. ~~工作流框架选型~~（已由ADR-022 确定：LangGraph）。

---

## 当前(Current)架构(Architecture)快照(Snapshot)

```text
V1 segments + Static Context
          ↓
Legacy Evidence Adapter
          ↓
EvidenceWindow[]
          ↓
 ┌────────────────────────────────────────────────┐
 │      五类 Specialist 并行（五路彼此隔离）       │
 │  Emotion / Repeat / Instant / Deferred /       │
 │  Comment —— 分支内部结构见下图                 │
 └────────┬──────────────────────────┬────────────┘
    通过 ↓                           ↓ 自动修复与局部重试耗尽 /
  Candidate Pool                     分支持续失败 / abstain 需人工
         ↓                           ↓
Deterministic Render（锚点 → 毫秒，确定性打乱，ADR-023）  HITL
         ↓
Deterministic Global Constraints（含 deferred_vote 时间校验）
（去重 / 冲突 / 间隔 / cooldown / budget）
         ↓
Semantic Scheduler ── 无法返回合法选择 ──→ HITL
         ↓
Final Deterministic Check
          ↓
Selected Interactions
```

每个生成专家(Specialist)分支内部（×5 同构）。局部约束校验(Local Constraint Validation)位于分支内、候选池(Candidate Pool)之前，对应ADR-013；修复(Repair)的定向退回回到本分支生成专家(Specialist)，只修该条候选(candidate)，对应ADR-014：

```text
EvidenceWindow[]
      ↓
Specialist（找点 + 绑证据 + 生成 payload） ←──── 定向退回，只修这一条
      ↓                                          │
Local Constraint Validation                      │
 通过 ↓              ↓ fail                       │
      │        安全程序修复（确定性，若可行）      │
      │            ↓ 修复无效                     │
      │        局部 Retry ─────────────────────────┘
      │            ↓ 仍失败
      ↓            ↓
Candidate Pool   HITL
```

生成专家(Specialist)需要补充证据时：

```text
Text Specialist
      ↓
inspect_window(window_id, question)
      ↓
Evidence Service
      ↓
文本化补充证据
      ↓
Same Specialist Continues
```

本轮证据(Evidence)服务(Service)可以只冻结接口，不实现新的多模态提取能力。
