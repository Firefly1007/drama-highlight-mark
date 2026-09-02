# src/drama_interaction/validation/rules.py 内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-013、ADR-023（渲染断点：锚点→毫秒确定性规则、延时投票(deferred_vote)时间合法性）、PRD §10.2、docs/schema.md；参考（仅清单灵感，禁止照抄）：v1/pipline/common/runtime.py

## 职责与边界

- 局部约束校验(Local Constraint Validation)的规则库：每个 生成专家(Specialist)分支内、候选池(Candidate Pool)之前运行的确定性校验（ADR-013）。
- 每条规则失败产出结构化错误描述，能直接驱动下游处理链（程序修复 / 定向退回 / 人工介入(HITL)，PRD §11）。
- 明确不做：无 输入输出(IO)、无 大语言模型(LLM)、无网络；不做语义质量评价（不设在线 评审器(Critic)，PRD §10.2）；不修改 候选(candidate)（修复是 repair.py 的事）。

## 依赖关系

- 依赖 schemas 三个模块（校验对象与查询 证据窗口(EvidenceWindow)）。
- 被依赖方：validation/repair.py（按错误分类决定修复路径）、graph/nodes.py（分支校验节点调用）、scheduling/constraints.py（最终确定性校验(Final Deterministic Check)复用部分规则）。

## 主要组成（规则清单）

分组 A：结构合法性
| 规则 | 判定依据 | 失败描述内容 | 可否程序修复 |
|------|----------|--------------|--------------|
| schema 合法 | pydantic 校验通过 | 字段路径 + 期望类型 | 否（退回 大语言模型(LLM)） |
| 载荷(payload)类型匹配 | 载荷(payload)结构与 specialist_type 一致 | 实际类型 vs 期望类型 | 否 |
| 生成侧零毫秒 | 延时投票(deferred_vote)载荷(payload)的 reveal_time/reveal_delay 必须为 null；任何 生成专家(Specialist)输出结构不得携带毫秒字段（ADR-011 禁伪精确） | 违规字段名与实际值 | 是（丢弃并置空——渲染环节重算，不改变业务语义） |

分组 B：证据引用合法性
| 规则 | 判定依据 | 失败描述内容 | 可否程序修复 |
|------|----------|--------------|--------------|
| evidence_window_ids 存在 | 引用的 window 在 证据(Evidence)中存在 | 缺失的 window_id 列表 | 否 |
| trigger_anchor.window_id 存在 | 同上 | 同上 | 否 |
| transcript_segment_id 可解析 | 在该 window 的 台词文本(transcript)中存在同 标识(id)项 | 缺失的 片段(segment)标识(id) | 否 |
| reveal_anchor 晚于 trigger | 揭晓(reveal)的窗口/时间位置在 触发(trigger)之后（窗口序号或可解析时间比较） | 两者位置 | 否 |
| trigger_window 属于 evidence_window_ids | 引用一致性 | —— | 否 |
| 延时投票(deferred_vote)时间合法性 | reveal_time >= show_at + duration_ms + reveal_gap_min_ms（真实毫秒来自渲染产物，调用时机在 候选池(Candidate Pool)之后、冲突组之前——先淘汰再竞争） | 两者毫秒值与差值 | 不适用 → 由 constraints 预处理直接丢弃 |

分组 C：业务约束（schema.md）
| 规则 | 判定依据 | 失败描述内容 | 可否程序修复 |
|------|----------|--------------|--------------|
| button_id 合法且与 文本(text)/弹幕(danmaku)可选性匹配 | 五类映射表 | 实际 button_id 与冲突字段 | 否 |
| 金句台词(keyline)在 台词文本(transcript)中存在 | 文本（或归一化后）匹配 | 是否匹配 | 否 |
| 即时投票(instant_vote)选项恰 2 个 | schema.md | 实际数量 | 否 |
| 延时投票(deferred_vote)选项 2-4 个 | schema.md | 实际数量 | 否 |
| answer_id 为 options 合法索引 | 索引范围 | 实际值 | 否 |
| 文本长度 / 空白约束 | 数值阈值（待定） | 字段 + 实际长度 | 部分（空白清理可程序修复） |

分组 D：重复检测
| 规则 | 判定依据 | 失败描述内容 | 可否程序修复 |
|------|----------|--------------|--------------|
| 明显重复 候选(candidate) | 同分支内 锚点(Anchor)相同且 载荷(payload)高度近似 | 与哪条重复 | 是（保留策略明确的机械合并） |

- 错误描述统一结构：错误类别、候选(candidate)定位、期望值 / 实际值、建议处理路径（程序修复 / 退回 大语言模型(LLM) / 人工介入(HITL)），共三路径，不新增 discard。
- 延时投票(deferred_vote)时间合法性失败的落点：判定谓词由 rules.py 定义，但失败不进入上述三路径。
  - 失败发生在 候选池(Candidate Pool)之后，由 scheduling/constraints.py 的淘汰 / 合并清单直接丢弃（见分组 B 表格）。
  - 本库只提供「判什么」，「何时判、判完去哪」由 constraints 预处理流程决定。
- V1 runtime.py 校验清单的取舍：吸收 载荷(payload)数值约束、锚点(Anchor)存在性、跟读金句(repeat_keyline)真实性校验的思路；不带入任何依赖 高光(Highlight)层的前提（V2 无 高光(Highlight)）。

## 关键设计点

- 每条规则的失败描述直接决定修复路径：「可程序修复」白名单与 repair.py 的安全修复清单一一对应，避免两处口径不一。
- reveal_anchor 的「晚于」判定优先用窗口序号比较（窗口级锚点），有可解析 台词文本(transcript)时间时用时间比较——判定方式必须确定性且与调度层的代表时间点规则一致（见 scheduling/constraints.md）。
- 规则全部纯函数化：输入（候选(candidate) + 证据(Evidence) + 阈值配置）→ 输出（错误列表），便于穷尽测试与复用。
- 「明显重复」的相似度口径从简第一版（同 锚点(Anchor) + 关键字段一致即重复），复杂相似度留给 基准评测(benchmark)观察。
- 毫秒取值合法性校验（非负、落在 金句台词(keyline)上下限内、揭晓(reveal)晚于 show_at+duration）下沉到终检对 最终互动(FinalInteraction)执行：分支内校验时毫秒尚不存在，校验点在渲染之后；终检在 渲染(rendering)之后验真实毫秒，不在此规则库的「可否程序修复」口径内。

## 待定项

- 文本长度等数值阈值（V1 有惯例值，V2 未冻结）：作为配置注入，具体数值待 基准评测(benchmark)。
- 金句台词(keyline)匹配的归一化程度（全半角、标点）。
- 「明显重复」的 载荷(payload)近似判定口径。

## 测试要点

- 纯函数可穷尽离线测试：每条规则构造正 / 反样例。
- 错误描述结构完整性断言（类别、定位、期望 / 实际、建议路径四要素齐全）。
- 与 repair.py 的白名单口径联测：标记「可程序修复」的错误必须能被安全修复函数处理。
