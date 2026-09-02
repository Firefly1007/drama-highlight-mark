# src/drama_interaction/scheduling/constraints.py 内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-017 / 018 / 019、PRD §15.2 / §15.4 / §16

## 职责与边界

- 全局确定性约束的纯函数集合：候选池(Candidate Pool)的确定性预处理(Deterministic Preprocessing)与调度器(Scheduler)之后的最终确定性校验(Final Deterministic Check)共用本模块。
- 产出两类结果：被确定性淘汰 / 合并的候选清单，以及「存在真实语义取舍」的待取舍集合（交给 scheduling/semantic.py）。
  - **两类结果分别写入 State.constraints_report 与 State.selected_candidates**：
    - constraints_report：淘汰 / 合并 / 标记候选 + 确定性原因。
    - selected_candidates：确定性存活集（跳过 semantic 时即终检输入）。
- 明确不做：无输入输出(IO)、无大语言模型(LLM)；不做「留谁更好」的语义判断；不重新理解剧情。

## 依赖关系

- 依赖 schemas（候选(Candidate)、EvidenceWindow）、config（预算(budget) / 间隔(spacing) / 冷却(cooldown)数值，未配置时显式降级）。
- 被依赖方：scheduling/semantic.py（接收待取舍集合）、graph/nodes.py（constraints 节点与 final_check 节点调用）。

## 主要组成

- 候选代表时间点解析（resolve_anchor）：**本模块是唯一实现处**，render_node 直接 import 它（与渲染环节同一实现，ADR-023 要求；不新建 anchors 模块）。
  - 定义：`resolve_anchor(anchor) → {start_ms, end_ms}`。
    - 有 `transcript_segment_id` 取该片段(segment)的 `start_ms` / `end_ms`。
    - 无则取所在窗口(window)的 `start_ms` / `end_ms`。
  - **只有这一个判断分支**：不插值、不推断窗口内偏移（ADR-006）。
  - 下游字段据此展开，同一规则贯穿冲突组 / 间隔 / 冷却(cooldown)三类时间约束：
    - `show_at` = 触发(trigger)锚 start。
    - `duration_ms` 仅跟读金句(repeat_keyline)读**锚区间长度**（`end_ms − start_ms` + keyline_tail_ms，截断(clamp)至 `KEYLINE_DURATION_FLOOR` / `KEYLINE_DURATION_CEIL`）。
    - `reveal_time` = 揭晓(reveal)锚 start。
    - `reveal_delay` = 配置常量，与锚点无关。
- 完全重复去除：同锚点(anchor)且载荷(payload)关键字段一致的候选合并，保留策略确定性（如保留先入池者），记录被合并者与原因。
- 局部时间冲突组构建：代表时间点落在同一窗口(window)（或按待定时间规则判定为「同刻」）的候选分为一组——组内成员标记互斥，组内留谁是语义问题，本模块只分组不选择。
- 最小间隔约束：相邻（按代表时间点排序）选中集的间隔低于 min_interaction_spacing_ms 的对标记冲突；处理方式为与冲突组同样的「标记 + 交给语义取舍或确定性淘汰策略」（数值待基准评测(benchmark)）。
- 同类型冷却(cooldown)：同类型候选间隔低于 type_cooldown_ms 的对同样标记。
- 预算(budget)约束：候选数超 interaction_budget 时，超限本身交语义取舍（PRD §15.3 的第二种触发），本模块只报告超限量。
- 处理顺序建议：时间合理性校验（仅延时投票(deferred_vote)）→ 去重 → 冲突组 → 间隔 / 冷却(cooldown)标记 → 预算(budget)报告 → 输出确定性存活集 + 待取舍集合。
  - 本模块输入为已渲染候选（带真实毫秒）。
  - 延时投票(deferred_vote)的时间合理性校验失败直接丢弃候选并记录原因，复用本模块已有的淘汰 / 合并清单机制（不走 repair）。
    - 规则：`reveal_time >= show_at + duration_ms + reveal_gap_min_ms`（定义在 rules.py 分组 B）。
  - **先淘汰、再竞争**：时间不合法是「互动本身成不成立」的淘汰性判断，应在冲突组（同刻只选一个，竞争性判断）之前执行。
    - 理由：顺序颠倒会让不合法候选先挤掉同位置合法候选后再被丢弃，导致合法候选无辜落空、语义调度白做一轮。
- 最终确定性校验(Final Deterministic Check)复用：同一组函数对调度器(Scheduler)输出做终检，违规即报错（防大语言模型(LLM)输出破坏约束，PRD §15.4）；渲染提前到池(Pool)之后后，终检验的是真实毫秒，并新增三项：
  - ① 毫秒字段合法性：非负，且金句台词(keyline) `duration_ms` 在 `KEYLINE_DURATION_FLOOR` / `KEYLINE_DURATION_CEIL` 上下限内。
  - ② 揭晓(reveal)时间合法性（仅延时投票(deferred_vote)）：`reveal_time >= show_at + duration_ms + reveal_gap_min_ms`。
  - ③ `answer_id` 与已打乱选项(options)的索引一致（渲染已打乱，终检在渲染之后）。
  - 终检范围：count ≤ 预算(budget)、无时间冲突、间隔 / 冷却(cooldown)合法、无重复。

## 关键设计点

- 本模块体现 ADR-018 的总原则：程序判断「哪些不能同时出现」，大语言模型(LLM)只判断「如果只能留一些，哪些更值得留」——分组 / 标记在程序，选择在 大语言模型(LLM)，终检回到程序。
- 代表时间点解析是时间约束的基石，必须单一实现、单一口径，禁止各约束各自推时间。
- 数值参数全部来自 config 且允许「未配置」状态：未配置时对应约束显式跳过并记录（服务基准评测(benchmark)前的开发期），不默认为 0。
- 输出可解释：每个被淘汰 / 合并 / 标记的候选都带确定性原因（哪条约束、与谁冲突），供 PRD §20.2 可观测性与基准评测(benchmark)调度质量评估。

## 待定项

- 冲突组(conflict group)的具体时间规则（同刻的判定：同窗口？重叠区间？毫秒阈值？）——ADR-017 明确暂缓(Deferred)，待基准评测(benchmark)。
- min_interaction_spacing_ms / type_cooldown_ms / interaction_budget 数值（基准评测(benchmark)后定）。
- 间隔 / 冷却(cooldown)冲突是「确定性淘汰其中一方」还是「并入语义取舍」：倾向并入语义取舍（淘汰标准无语义依据），待定。
- 间隔(spacing)与时长(duration)的联动（已定）：因渲染提前到池(Pool)之后，本模块间隔 / 冷却(cooldown) / 冲突组计算可直接使用渲染产物的真实毫秒，无需再取预演值。
  - config 装载时执行派生校验 `min_interaction_spacing_ms >= max(全部 type_base, KEYLINE_DURATION_CEIL)`，违者快速失败(fail fast)。
  - 右边的 max 从 config 数据**现算**（不引入新常量），调参改时长后间隔(spacing)下界自动跟随。

## 测试要点

- 纯函数穷尽测试：构造候选集覆盖——无冲突、同窗冲突、跨窗重叠、间隔越界、同类型连发、超预算(budget)、空集。
- 代表时间点解析：台词文本(transcript)锚与纯窗口锚两种情形。
- 最终确定性校验(Final Check)的守门性：对违反约束的调度器(Scheduler)输出必须报错（用构造的违规输出测试）。
- 未配置参数时的显式跳过行为。
