# 短剧即时互动生成工作流 V2 — 架构决策记录（ADR）

本文只保留当前有效的 V2 决策；产品规则见 [PRD](drama-interaction-v2-PRD.md)，最终 JSON 见 [输出契约](schema.md)。

## 当前可执行图

```text
START
 ├─ media_prepare ─┐
 └─ extract_mix ───┴→ separate_audio
                         ├─ transcribe_audio ─┐
                         └─ prepare_background ┴→ dispatch_slice_batch
                                                       └→ slice × 最多 4
                                                          ├─ prepare_frames ─────┬→ observe_ocr
                                                          │                       └→ observe_vlm
                                                          └─ prepare_slice_audio ───→ observe_audio
                                                        → merge_slice_result
                                                    → merge_slice_batch ↻
                                                    → assemble_evidence → persist_evidence → render_evidence
                                                    → 五个 Specialist 节点并行 → pool
                                                    → render → constraints → semantic
                                                    → human_gate（必要时）→ final_check → END
```

切片子图是唯一的业务子图；五个 Specialist 是父图中直接扇出的节点，不再额外包一层只含 `run` 的 Specialist 子图。

## ADR-001：以整集证据直接发现互动，不设高光中间层

**决策**：V2 从整集证据直接寻找五类互动机会。高情绪片段可以入选，但并非所有互动都必须先被定义为高光。

**原因与影响**：关键台词、真实分歧、身份悬念、画面反差与声音事件都能被各自类型的 Specialist 使用；跨类型取舍留给下游调度，而非让单一“高光”定义限制发现范围。

## ADR-002：证据是单一、可锚定的完整视频基线

**决策**：一集只形成一个 `EvidenceDocument`：

```text
EvidenceDocument
  episode_duration_ms
  transcript_segments[]   # T<n>
  observations[]          # O<n>
```

- 每条 `T<n>`、`O<n>` 都带自身的整数 `start_ms`、`end_ms`，以真实媒体时长为边界。
- 台词、屏幕文字、视觉和背景音观察均只存一份；`D<n>` 是 Specialist 分支私有的派生观察，不回写基线。
- 上下文只用于理解名称与关系；当前集事件、因果、答案和揭晓必须由 `T/O/D` 支撑。

**原因与影响**：证据可以由所有 Specialist 复用、人工核查和候选锚点共同引用，不需要复制窗口或预先共享模型解释。

## ADR-003：原始视频是唯一生产入口，媒体边界由确定性工具测得

**决策**：生产 `run` 只接受原始 `.mp4` 或包含 `.mp4` 的目录。`ffprobe` 读取主视频轨时长；`ffmpeg` 提取整集混音音轨。视频父目录名用于加载同名 `DramaContext`。

- `media_prepare` 与 `extract_mix` 并行开始，之后才执行人声分离。
- 托管分离服务产出 `dialogue.mp3` 和 `background.mp3`，并保存在 `data/evidence/<剧名>/<集名>.audio/`。
- `dialogue.mp3` 的短时签名 URL 交给 ASR；`background.mp3` 是背景音观察的唯一音频来源。

**原因与影响**：集长、台词、画面和背景音都来自同一真实视频。缺少可用主视频轨或时长时当前集立即失败，不从容器、音轨或旧产物回退推测。

## ADR-004：ASR 时间直接采用句段结果；视觉与背景音使用固定切片

**决策**：

- ASR 直接映射 provider 返回的句段 `text/start/end`；不重切、不修正、不补偿时间，也不要求逐词时间戳或真实角色说话人标注。角色表作为即时词汇表传入，权重为 5。
- 非台词观察以固定、非重叠的 3 秒切片建立。每片以 4 FPS 采样：250ms 桶的中点帧，共最多 12 帧。
- OCR 和 VLM 接收同一有序帧序列；VLM 不接收台词、OCR、音频或剧集上下文。背景音观察只接收该片背景音频。
- OCR、VLM、音频观察的非空结果按同一跨度合并为一个 `O<n>`；不新增独立音频证据类型，也不做跨切片去重。

**原因与影响**：时间精度的来源清晰，模型不制造伪精确毫秒；OCR、视觉与音频职责互不挤占，切片策略也可复现。

## ADR-005：空观察不是失败，也不是可引用事实

**决策**：三路提取器都成功、但一个固定切片没有任何内容或不确定性时，不创建空 `O<n>`。时间线从切片网格推导并显示：

```text
[已覆盖、无可记录观察 start_ms=<开始> end_ms=<结束>]
```

相邻状态行合并。该行不是证据，不能引用，也不表示该时间范围内“什么都没发生”。真正无法判断的内容只写在实际 `O<n>` 的 `uncertainty` 中；必需提取器没有完成时，当前集失败，不产生 `[未覆盖]` 或半成品时间线。

**原因与影响**：正常空结果、观察不确定和提取失败三种情况可区分，不需要为覆盖状态新建数据结构。

## ADR-006：托管 API、能力通用配置与 Pydantic 结构化输出

**决策**：音轨分离使用腾讯云 CI 官方 SDK；ASR 使用 DashScope 官方 SDK；OCR、VLM、背景音观察与 Specialist/调度 LLM 使用相应的 OpenAI-compatible SDK。项目不部署本地模型，也不手写供应商签名或请求头。

- `.env` 只存凭据、端点和模型标识，变量以 `ASR_*`、`OCR_*`、`VLM_*`、`AUDIO_OBSERVER_*`、`AUDIO_SEPARATOR_*` 等能力命名。
- 所有可调运行参数与所有模型提示词集中在 `src/drama_interaction/config.py`；不加 provider factory、注册表或为尚未存在的第二供应商做兼容层。
- Agent 通过 `ToolStrategy` 提交 Pydantic 结构化结果；非 Agent 的 OCR、VLM、背景音与按需视频观察通过 LangChain function calling 提交各自的 Pydantic 输出工具。提示词只要求调用该工具，不嵌入 JSON Schema 或要求 JSON 文本。

**原因与影响**：部署边界小、供应商名称不污染配置接口，Pydantic 模型是唯一可执行的输出来源，模型不会把 Schema 当作观察结果返回。

## ADR-007：切片并发、PostgreSQL checkpoint 与恢复产物

**决策**：目录任务逐集运行；单集的固定切片由 `dispatch_slice_batch` 分批派发，`EVIDENCE_SLICE_CONCURRENCY=4` 同时限制为最多四个切片子图。

- `transcribe_audio` 与 `prepare_background` 并行。
- 每个切片中，采帧和背景音硬切并行；随后 OCR、VLM、背景音观察并行；`merge_slice_result` 只汇总本片，父图按切片顺序分配 `O<n>` 并继续下一批。
- PostgreSQL 是唯一正式 checkpoint；同一 `execution_id` 作为 LangGraph `thread_id` 恢复。项目不写 `.progress.json`，也不自行实现切片进度存储。
- 分离出的两个 MP3 与最终 Evidence 落盘以提高恢复能力；运行中的 `mix.flac`、`background.wav`、帧与片段音频在不再需要后清理。

**原因与影响**：独立节点可单独测试、重试和替换；中断后不会重新执行已 checkpoint 的分离、ASR 或已完成切片，同时不增加自建缓存层。

## ADR-008：五个 Specialist 直接并行，证据视图彼此隔离

**决策**：父图从 `render_evidence` 直接扇出五个 `specialist_<type>` 节点。每个节点绑定当前类型的 `BaseSpecialist`、当前分支时间线和 `inspect_span` 工具，并通过 `create_agent(..., response_format=ToolStrategy(SpecialistResult))` 返回结构化候选或明确弃权。

- 五路只共享只读基线证据和静态上下文，不共享情绪、剧情解释或候选。
- `inspect_span(start_ms, end_ms, query)` 只在发起分支可见；其 `D<n>` 派生观察不进入其他 Specialist。
- 局部模式、锚点、证据引用和 payload 校验在各自节点内完成；失败候选只定向重生，不重跑整集。

**原因与影响**：每一类互动按自己的规则判断机会，错误不会把任务特定解释扩散到其他分支；同时避免为单一调用节点维持多余图包装。

## ADR-009：候选只引用证据锚点，最终时间由程序确定

**决策**：模型生成候选时不输出绝对展示时间。`trigger_anchor` 和（如需）`reveal_anchor` 指向可见的 `T/O/D`；渲染节点从对应条目的 `start_ms` 计算最终字段。

- `repeat_keyline` 的展示时长由锚点跨度与配置尾部时长确定；其余类型采用配置的类型时长。
- `deferred_vote` 必须有更晚的揭晓锚点，揭晓不早于投票展示结束加最小间隔。
- 选项顺序使用同一执行和候选标识的确定性种子打乱，并同步更新 `answer_id`。
- 最终对外 `type` 只可能是五个规定字符串，且最终数组按展示位置排序、`id` 连续编号。

**原因与影响**：模型负责内容判断，程序负责可测量时间和稳定输出；后端不需要再推导位置或修复投票答案。

## ADR-010：局部校验优先，全局调度只处理必要取舍

**决策**：候选先经过分支内确定性校验与安全修复，再进入候选池。下游按以下顺序运行：确定性渲染 → 冲突、间隔、冷却、预算约束 → 必要时的语义调度 → 最终确定性校验。

模型自评分不参与路由或排序。无法自动解决的候选、网络耗尽、语义选择或最终约束会进入 `human_gate`，人工可 `accept`、`edit` 或 `drop`，然后从同一 checkpoint 继续。

**原因与影响**：大多数重复和冲突不需要 LLM 重读整集；HITL 仅处理真正无法自动确认的少数问题。

## ADR-011：失败边界按“上游证据”与“下游候选”区分

**决策**：视频不可读、时长探测失败、音轨分离失败、ASR 无合法句段、OCR/VLM/背景音观察任一必需调用失败或超时，都会使当前集失败，不发布半成品 `EvidenceDocument`。目录批处理记录该集错误后继续下一集。

Specialist 或调度阶段的局部问题不重跑已完成证据；按 ADR-010 进入定向修复、分支隔离或人工门控。

**原因与影响**：不会把不完整媒体观察伪装成可用事实，同时最大化保留已完成的同批其他集和本集下游工作。

## 明确不做

- 不复用或兼容旧处理链路。
- 不增加自建缓存、进度 JSON、provider 抽象、镜头检测、自适应采样、跨集并发或本地模型。
- 不让模型补写未被采样、未被 ASR 返回或未被证据支持的内容。
