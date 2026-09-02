# 短剧即时互动生成工作流 V2 — 产品需求文档(PRD)

- 文档类型：产品需求文档(PRD)
- 版本：v0.5
- 日期：2026-09-02
- 状态：核心产品与工作流架构已确认；工作流框架已确定 LangGraph；少量参数待定

## 1. 背景

现有 V1 工作流以“剧情高光(Highlight)”作为五类互动生成的统一入口：先从内容中识别高光，再把高光结果交给不同互动生成模块。

该设计符合原始课题中“高光剧情互动”的思路，但存在一个关键建模问题：**高光价值不等于互动价值**。

一些适合互动的时刻未必是强高光，例如：

- 一个尚未揭晓、但适合用户预测的问题；
- 一个适合立刻站队的普通冲突；
- 一句很适合用户接话或复述、但并非剧情爆点的台词；
- 一个适合吐槽的反差动作或表情。

因此 V2 不再把高光(Highlight)作为统一中间瓶颈，而是让五类互动生成专家(Specialist)直接面向共享证据，各自寻找并生成最适合自身类型的互动候选。

## 2. 产品目标

V2 的目标是构建一个**可解释、可恢复、可评测、低重复推理**的短剧即时互动生成工作流。

优先级：

1. 简历与工程技术价值；
2. 业务逻辑合理性与互动质量；
3. 功能数量。

本版本强调：

- 删除高光(Highlight)强制瓶颈；
- 五类互动独立专家化处理；
- 不使用统一机会检测器(Opportunity Detector) / 路由(Router)重复判断同一问题；
- 不要求模型输出伪概率或伪置信度；
- 运行时以确定性约束校验为主；
- 必要时支持局部重试、分支故障隔离与人工介入(HITL)；
- 用离线基准评测(benchmark)改进语义质量，而不是为每个候选增加在线大语言模型(LLM)评审器(Critic)；
- 证据(Evidence)层与互动生成层通过稳定契约解耦。

## 3. 本版本范围

### 3.1 固定支持的五类互动

1. `emotion_button`
2. `repeat_keyline`
3. `instant_vote`
4. `deferred_vote`
5. `side_comment`

互动类型固定，不增不减。

### 3.2 本版本不包含

- 剧情分支与人工智能生成内容(AIGC)分支内容生成（原 06 → 08 链路）；
- 前端播放器与后台业务服务；
- 跨集剧情摘要自动生成；
- 完整人物世界状态 / 剧情世界模型；
- 每个候选固定追加的在线大语言模型(LLM)评判器(Judge) / 评审器(Critic)；
- 大语言模型(LLM)自报概率(probability) / 置信度(confidence)；
- 为展示智能体(Agent)概念而人为增加规划器(Planner) / 评审器(Critic) / 反思(Reflect)循环；
- **新的自动语音识别(ASR) / 光学字符识别(OCR) / 多模态证据(Evidence)提取(Extraction)实现。**

### 3.3 本轮对上游的处理

本轮实现暂时继续使用 V1 已有的内容提取结果。

V2 只增加一个很薄的 `Legacy Evidence Adapter`，把 V1 片段(segments)转换为 V2 的 `EvidenceWindow[]`。新的证据(Evidence)提取(Extraction)方案只保留接口，不在本轮实现。

## 4. 核心用户故事

作为内容生产方，我希望输入一集短剧及其已有内容证据，系统能够自动生成少量、位置合适、类型多样、不过度打断观看的即时互动配置；当局部结果无法自动处理时，系统应保留已完成结果并只把异常部分交给人工处理，而不是整集重跑。

## 5. 静态上下文(Static Context)

生成专家(Specialist)可获得：

- 剧名；
- 角色表；
- 剧集 / 剧目简介。

静态上下文(Static Context)只用于辅助身份、背景和专名理解。

**约束：当前集互动中出现的具体剧情事实必须能够由当前集证据(Evidence)支撑。静态上下文(Static Context)不能替代当前集事实证据。**

## 6. 证据(Evidence)数据契约

### 6.1 设计原则

本版本先冻结数据契约，不冻结未来证据(Evidence)提取(Extraction)的具体技术实现。

证据(Evidence)的目标是：

> 把短剧内容表示成文本模型可以稳定消费、可以引用、可以验证、可以回查的共享证据。

V2 后半链路不要求使用多模态模型。

### 6.2 根节点

共享证据(Shared Evidence)的根节点直接是：

```text
list[EvidenceWindow]
```

不额外包 `EpisodeEvidence.windows`。

集(Episode)级元数据属于工作流状态(Workflow State)，不属于共享证据(Shared Evidence)模式(schema)。

### 6.3 固定窗口

每个 `EvidenceWindow`：

- 固定 3 秒；
- 默认不重叠；
- `window_id` 连续；
- `start_ms / end_ms` 由窗口边界确定。

固定窗口是**组织、检索、验证单位**，不是伪造精确事件时间的工具。

### 6.4 `EvidenceWindow` v0.1

```text
EvidenceWindow
├─ window_id
├─ start_ms
├─ end_ms
├─ transcript_segments[]
│  ├─ id
│  ├─ start_ms
│  ├─ end_ms
│  ├─ text
│  └─ speaker_label?        # 可空，匿名 speaker label
├─ onscreen_text_segments[]
│  ├─ start_ms
│  ├─ end_ms
│  └─ text
├─ visual_observations[]
│  └─ text
├─ audio_observations[]
│  └─ text
└─ uncertainty[]
```

### 6.5 台词文本(Transcript)跨窗口规则

如果一条台词文本(Transcript)跨越多个 3 秒窗口：

- 不硬切台词；
- 完整复制到所有相交窗口；
- 保留同一个 `id / start_ms / end_ms / text / speaker_label`。

重复项拥有相同标识(ID)和时间，因此仍然是同一个证据对象。

### 6.6 证据(Evidence)层不做的事

共享证据(Shared Evidence)不直接提供：

- `emotion = 愤怒`；
- `plot_role = 身份悬念`；
- `importance = 3`；
- `interaction_value = high`；
- `confidence = 0.82`；
- 完整人物目标、关系状态、悬念状态等高层剧情解释。

视觉和音频观察(observation)只保留尽量客观的文本观察，例如：

- “女子突然转头看向男子”；
- “男子后退一步”；
- “说话音量明显升高”；
- “背景音乐明显增强”。

### 6.7 不制造精确时间

`visual_observations` / `audio_observations` 不要求输出毫秒级 `start_ms / end_ms`。

它们只继承所在 3 秒窗口的时间范围。

只有本身已经具有可靠时间定位的结构，例如台词片段(transcript segment)，才保留精细时间。

## 7. V1 旧版证据适配器(Legacy Evidence Adapter)

本轮实现通过适配器(Adapter)将 V1 片段(segments)转换为 `EvidenceWindow[]`。

临时映射原则：

- V1 `text` → `transcript_segments`；
- V1 `id / start / end` → transcript `id / start_ms / end_ms`；
- `speaker_label = null`；
- V1 `speech / voice / music / audio_cues` → 暂时整理为 `audio_observations`；
- V1 `uncertainty` 非空时 → 并入窗口 `uncertainty[]`；
- V1 `emotion` 不进入共享证据(Shared Evidence)；
- `visual_observations = []`；
- `onscreen_text_segments = []`；
- V1 片段(segment)与 3 秒窗口相交时加入该窗口，跨窗口则完整复制。

该适配器(Adapter)是临时兼容层，不代表未来证据(Evidence)提取(Extraction)的最终实现。

## 8. 按需文本取证：证据服务(Evidence Service)

### 8.1 基本原则

五个业务生成专家(Specialist)可以全部使用文本模型。

生成专家(Specialist) **不直接查看原视频、原音频或原始帧**。

当共享证据(Shared Evidence)不足时，生成专家(Specialist)可以调用：

```text
inspect_window(window_id, question)
```

### 8.2 `inspect_window()` 语义

- 生成专家(Specialist)只提交 `window_id + 具体问题`；
- 证据服务(Evidence Service)自行访问对应的原始媒体或未来的上游提取器；
- 返回给生成专家(Specialist)的永远是**文本化补充证据**；
- 生成专家(Specialist)继续基于这些文本证据完成自己的任务。

例如：

```text
inspect_window(
  window_id=11,
  question="这句话说出时，两人的动作和明显声音变化是什么？"
)
```

返回：

```text
visual_observations:
- 女子迅速转头看向男子
- 男子短暂停顿后退半步

audio_observations:
- 说话音量明显提高
```

### 8.3 本轮实现范围

本轮不实现新的多模态证据服务(Evidence Service)内部能力。

如果需要保留工具接口，可以先定义契约(contract) / 桩实现(stub)；真正的媒体取证实现留到后续证据(Evidence)提取(Extraction)阶段。

## 9. 五类类型专属生成专家(Type-Specific Specialist)

### 9.1 输入

统一输入：

```text
SpecialistInput
├─ static_context
├─ evidence_windows[]
└─ tool: inspect_window(window_id, question)
```

### 9.2 基本原则

五类生成专家(Specialist)并行执行。

每个生成专家(Specialist)：

- 一次扫描完整当前集证据(Evidence)；
- 只负责自己的互动类型；
- 在同一个逻辑任务中完成“找位置 + 生成互动”；
- 不依赖高光(Highlight) / 机会检测器(Opportunity Detector) / 路由(Router)；
- 可以生成 0、1 或多个候选(Candidate)；
- 证据明显不足时允许 `abstain`；
- 不输出置信度(confidence) / 概率(probability) / 自评分(self-score)。

### 9.3 五路结构

```text
EvidenceWindow[]
      │
 ┌────┼────────┬────────┬────────┬────────┐
 ↓    ↓        ↓        ↓        ↓
Emotion Repeat Instant Deferred Comment
   Specialist × 5（并行）
      │
      ↓
Local Constraint Validation（每路分支内，Candidate Pool 之前）
```

### 9.4 生成专家(Specialist)输出契约

统一外壳：

```text
SpecialistResult
├─ candidates[]
│  ├─ evidence_window_ids[]
│  ├─ trigger_anchor
│  │  ├─ window_id
│  │  └─ transcript_segment_id?   # 可选
│  ├─ payload                     # 各类型自己的业务内容
│  └─ reveal_anchor?              # 仅 deferred_vote
└─ abstentions[]
```

候选标识(ID)在汇入候选池(Candidate Pool)时由程序生成，不要求大语言模型(LLM)自己生成。

### 9.5 触发锚点(Trigger Anchor)

生成专家(Specialist)不输出伪精确绝对毫秒时间。

触发位置使用证据锚点：

```text
trigger_anchor:
  window_id: 11
  transcript_segment_id: t27   # 可选
```

含义：

- 有明确台词锚点时，引用对应台词片段(transcript segment)；
- 仅有视觉 / 音频证据时，锚到整个 3 秒窗口(window)；
- 不要求模型估计毫秒级事件发生时刻。

`deferred_vote` 的 `reveal_anchor` 使用同类引用结构。

### 9.6 `abstain`

`abstain` 是离散状态，不是低置信度(confidence)。

只用于：生成专家(Specialist)认为可能存在机会，但当前证据不足以安全地产生合法互动。

## 10. 局部约束校验(Local Constraint Validation)

### 10.1 位置

约束校验(Constraint Validation)位于每个生成专家(Specialist)分支内部，候选池(Candidate Pool)之前。

### 10.2 只验证可确定性判断的内容

典型规则：

- JSON / Pydantic 模式(schema)合法；
- `evidence_window_ids` 存在；
- `trigger_anchor.window_id` 存在；
- `transcript_segment_id` 如存在必须能在对应证据(Evidence)中找到；
- `deferred_vote.reveal_anchor` 位于触发(trigger)之后；
- 载荷(payload)类型字段合法；
- 选项数量、文本长度等业务约束合法；
- 明显重复候选(Candidate)；
- 其他可以稳定用程序判断的规则。

第一版不设置固定在线大语言模型(LLM)评审器(Critic)。

## 11. 候选(Candidate)级修复(Repair) / 重试(Retry)

候选(Candidate)违反确定性约束时，禁止重新扫描整集。

处理顺序：

```text
Candidate
  ↓
Constraint Validation
  ↓ fail
安全的程序修复（若可行）
  ↓ 仍 fail
原 candidate + 明确错误 + 必要局部 evidence
退回原 Specialist
  ↓
只修这一条 candidate
  ↓
再次 Validation
  ↓ 仍 fail
HITL
```

禁止局部重试(Retry)：

- 重新寻找新的互动点；
- 修改其他成功候选；
- 重跑整个生成专家(Specialist)；
- 重跑上游证据(Evidence)。

## 12. 五路故障隔离

五个生成专家(Specialist)彼此独立。

如果某一路出现接口(API) / 解析 / 持续约束失败：

- 只重试失败分支；
- 成功分支结果立即持久化；
- 失败分支最终进入人工介入(HITL)；
- 不因为单路失败导致其他四路重跑或丢失。

## 13. 人工介入(HITL)

人工介入(HITL)是异常兜底，不是正常审批流程。

第一版触发条件：

- 自动修复 + 局部重试仍失败；
- 生成专家(Specialist)主动 `abstain` 且需要人工决定；
- 生成专家(Specialist)分支持续失败；
- 语义调度器(Semantic Scheduler)无法返回合法选择。

人工动作：

- `accept`；
- `edit`；
- `drop`；
- 冲突场景下直接指定保留候选(Candidate)。

当存在待人工处理状态：

- 已成功结果立即持久化；
- 工作流(Workflow)状态为 `WAITING_FOR_HUMAN`，而非 `FAILED`；
- 最终发布暂停；
- 人工处理后从检查点(checkpoint)恢复；
- 已完成证据(Evidence)与成功生成专家(Specialist)不重新执行。

恢复点定义：检查点(checkpoint)恢复点即触发人工介入(HITL)的节点。

- 候选(Candidate)修复耗尽 → 对应其所在生成专家(Specialist)分支。
- 分支持续失败 → 对应该生成专家(Specialist)分支。
- 调度器(Scheduler)失败 → 对应调度器(Scheduler)节点。

人工 `accept / edit / drop` 的结果写入工作流状态(Workflow State)后从该节点继续执行。

## 14. 候选池(Candidate Pool)

所有已经通过本地校验(Validation)的候选(Candidate)汇合成候选池(Candidate Pool)。

程序在汇入时生成统一 `candidate_id`，用于：

- 冲突分组；
- 调度器(Scheduler)选择；
- 人工介入(HITL)；
- 可观测性；
- 最终输出追踪。

同一局部时刻可以保留多个候选进入池(Pool)，但最终展示最多 1 个互动。

## 15. 全局约束处理(Global Constraint Processing) + 集调度器(Episode Scheduler)

### 15.1 总原则

> 程序判断“哪些不能同时出现”；大语言模型(LLM)只在确实需要时判断“如果只能留一些，哪些更值得留”。

### 15.2 确定性预处理(Deterministic Preprocessing)

程序优先处理：

- 完全重复项；
- 局部时间冲突组；
- 最小互动间隔；
- 同类型冷却(cooldown)；
- 集(Episode)预算(budget)；
- 其他可以确定性表达的业务约束。

### 15.3 语义调度器(Semantic Scheduler)

只有出现真正的语义选择时才调用大语言模型(LLM)，例如：

- 同一局部时刻多个合法互动只能留一个；
- 合法候选(Candidate)数量超过集(Episode)预算(budget)；
- 多个候选(Candidate)都合法，但需要在互动价值、剧情覆盖、多样性之间取舍。

调度器(Scheduler)不重新寻找互动点，不重新分析完整一集。

输入只包括：

- 待选择候选(Candidate)；
- 候选(Candidate)对应的局部证据(Evidence)；
- 已选择互动的简要概况；
- 剩余预算(budget)；
- 明确硬约束。

输出采用离散选择候选标识(ID)，不输出概率(probability) / 置信度(confidence) / 评分(score)。

### 15.4 最终确定性校验(Final Deterministic Check)

调度器(Scheduler)之后再执行一次确定性终检，确保：

- `count <= budget`；
- 时间冲突满足要求；
- 最小间隔合法；
- 冷却(cooldown)合法；
- 无重复候选(Candidate)。

## 16. 配置

以下参数作为显式配置，不写死在模型提示词(Prompt)中：

```text
window_size_ms = 3000
interaction_budget
min_interaction_spacing_ms
type_cooldown_ms
```

其中 `window_size_ms = 3000` 当前已确定。

其余值在基准评测(benchmark)后调参。

## 17. 最终输出与内部状态

业务最终只消费调度器(Scheduler)选中的 `selected interactions`。

系统内部同时保留：

- 工作流状态(Workflow State)；
- 证据窗口(EvidenceWindow)[]；
- 五类生成专家(Specialist)原始结果；
- 校验(Validation) / 修复(Repair)状态；
- 人工介入(HITL)状态；
- 候选池(Candidate Pool)；
- 调度器(Scheduler)决策；
- 最终互动(Final Interactions)。

这些内部状态用于调试、评测、回溯和简历展示。

## 18. 正常路径与异常路径

### 18.1 本轮正常路径

```text
V1 segments + Static Context
        ↓
Legacy Evidence Adapter
        ↓
EvidenceWindow[]
        ↓
5 Specialists（并行，各自分支内完成 Local Constraint Validation）
        ↓
Candidate Pool
        ↓
Deterministic Render（锚点 → 毫秒，确定性打乱，ADR-023）
        ↓
Global Constraint Processing（含 deferred_vote 时间合法性校验）
        ↓
Semantic Scheduler（仅需要时）
        ↓
Final Deterministic Check
        ↓
Final Interactions
```

### 18.2 异常路径

```text
Candidate / Specialist Failure
        ↓
Local Repair / Retry
        ↓
仍失败
        ↓
WAITING_FOR_HUMAN
        ↓
Human accept / edit / drop
        ↓
Checkpoint Resume
        ↓
后续节点继续
```

## 19. 轻量基准评测(Benchmark)

### 19.1 目标

本轮基准评测(benchmark)专门验证**后半链路**，不评价新的证据(Evidence)提取(Extraction)，因为本轮不实现它。

### 19.2 开发基准

准备：

- 3–5 集人工校正的证据(Evidence)时间线(Timeline)；
- 总计约 20–50 个有代表性的互动机会 / 案例(case)。

人工校正数据作为黄金用例(golden fixture)，隔离 V1 上游时间线误差。

### 19.3 V1 / V2 对照

尽可能让 V1 与 V2 使用同一份校正证据(Evidence)输入，比较：

- V1：高光(Highlight) → 5 个互动(Interaction)提示词(prompts)；
- V2：5 个生成专家(Specialist) → 校验(Validation) → 调度器(Scheduler)。

重点验证：

> 删除高光(Highlight)强制瓶颈后，类型专属生成专家(Specialist) + 全局调度是否提升互动机会发现和最终整集质量。

### 19.4 核心评估维度

- 互动(Interaction)发现(discovery)：人工认可机会是否被找到，分类型统计；
- 触发(Trigger)正确性(correctness)：证据锚点是否落在人工认可位置；
- 内容(Content)质量(quality)：类型是否合适、内容是否有证据支撑、是否泄露未来；
- 最终调度(scheduling)质量(quality)：是否同一时刻多互动、过密、超预算(budget)、明显重复；
- 工作流(Workflow)鲁棒性(robustness)：注入非法候选(Candidate) / 单分支失败，验证重试(Retry)、隔离、人工介入(HITL)、恢复(resume)；
- 可观测性(Observability)：记录调用次数、重试(Retry)次数、人工介入(HITL)次数、耗时等运行数据。

大语言模型(LLM)-as-a-评判器(Judge)只能作为离线辅助，不作为真值。

## 20. 非功能需求

### 20.1 可恢复性

- 任一生专家(Specialist)失败不得导致其他分支重跑；
- 候选(Candidate)失败优先局部修复；
- 人工介入(HITL)后必须能够从检查点(checkpoint)恢复。

### 20.2 可观测性

每个阶段至少记录：

- 执行(execution) / 集(Episode)标识；
- 节点状态；
- 失败原因；
- 重试次数；
- 人工介入(HITL)原因；
- 候选(Candidate) → 证据(Evidence)追踪关系；
- 调度器(Scheduler) keep / drop 结果；
- 模型调用次数与耗时。

### 20.3 成本控制

正常路径避免重复语义判断：

- V1 证据(Evidence)适配器(Adapter)不增加新的内容理解调用；
- 五个生成专家(Specialist)并行执行；
- 调度器(Scheduler)大语言模型(LLM)只在真实语义选择时调用；
- 只有失败候选(Candidate)才进行局部重试(Retry)；
- 不为每个候选(Candidate)固定追加大语言模型(LLM)评审器(Critic)。

## 21. 第一阶段成功标准

V2 第一阶段完成后，应能够证明：

1. 高光(Highlight)已不再是五类互动的强制前置条件；
2. V1 片段(segments)能通过旧版适配器(Legacy Adapter)转成稳定的 `EvidenceWindow[]`；
3. 五类生成专家(Specialist)可以直接从共享证据(Shared Evidence)独立发现并生成互动；
4. 生成专家(Specialist)不依赖多模态输入；
5. 触发(trigger)使用证据(Evidence)锚点(anchor)，不制造伪精确毫秒时间；
6. 候选(Candidate)可以进行确定性校验(Validation)与局部修复(Repair)；
7. 单生成专家(Specialist)失败不会导致其他分支结果丢失；
8. 人工介入(HITL)后能够从持久化状态恢复；
9. 调度器(Scheduler)能在预算(budget) / 间隔(spacing) / 冷却(cooldown) / 冲突(conflict)约束下输出最终互动集合；
10. 有轻量基准评测(benchmark)能比较 V1 / V2，并区分上游证据(Evidence)问题与下游工作流(Workflow)问题。

## 22. 延后决策(Deferred Decisions)

当前仍有意延后的内容：

1. 未来真正的自动语音识别(ASR) / 光学字符识别(OCR) / 多模态证据(Evidence)提取(Extraction)方案；
2. `inspect_window()` 的真实多模态实现；
3. 五类生成专家(Specialist)的具体提示词(Prompt)；
4. 五类载荷(payload)的最终详细字段；
5. 冲突(conflict)组(group)的具体时间规则；
6. `interaction_budget / min_interaction_spacing_ms / type_cooldown_ms` 参数值；
7. 调度器(Scheduler)提示词(Prompt)；
8. 人工介入(HITL)界面(UI)与最终持久化介质（检查点(checkpoint)使用 LangGraph 持久化，具体后端存储待定）；
9. 基准评测(benchmark)标注细则与通过阈值；
10. ~~工作流框架选型~~（已确定：LangGraph）。
