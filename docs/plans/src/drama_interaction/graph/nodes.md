# src/drama_interaction/graph/nodes.py 内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-013 / 014 / 015 / 016 / 022、PRD §11 / §18.1 / §18.2

## 职责与边界

- 定义全部节点函数：每个节点只做编排（接收 工作流状态(State)、调用业务模块、写回 工作流状态(State)），业务实现分布在 schemas / evidence / specialists / validation / scheduling 各模块。
- 节点边界与 ADR-013/014 的局部校验、定向 修复(Repair)语义对齐：校验与修复循环发生在 生成专家(Specialist)分支内部，禁止把整集重跑藏进图结构（ADR-022 Consequences）。
- 明确不做：不实现 提示词(prompt)、不实现规则、不做图装配（builder.py）。

## 依赖关系

- 依赖全部业务模块（adapter、base、五类型、rules、repair、constraints、semantic）与 schemas。
- 被依赖方：graph/builder.py（节点注册）、tests（节点级单测）。

## 主要组成（节点清单）

- adapter_node：调用 evidence/adapter.py 将 V1 片段(segments)转 EvidenceWindow[]，落盘 data/evidence/，写入 State.evidence 与 执行(execution)元数据；空证据集在此显式标记。
  - **空证据时下游短路**：直接产出空互动数组并标记，不进入五路 生成专家(Specialist)（避免空跑 5 次 大语言模型(LLM)，PRD §20.3 成本控制）。
- specialist_node（类型参数化工厂，注册五个实例）：调用对应类型模块产出 专家结果(SpecialistResult)，写 specialist_results 对应条目。
  - 类型模块 = base 骨架 + 类型 提示词(prompt)要素。
  - 五个节点以静态多边并行方式从 adapter 扇出（分支数固定为 5，不需要 运行时(Runtime) Send 动态分发）。
- branch_validate_repair（分支内）：对每类 专家结果(SpecialistResult)跑 rules.py。
  - 循环结构建议用「校验节点 + 条件边回环」表达：validate → repair → validate，直到通过 / 耗尽。
  - 失败候选走 repair.py 两阶段：安全程序修复 → 定向退回，循环次数受 repair 重试上限约束。
  - 通过 → 候选进入入池队列；耗尽 → 产出 人工介入(HITL)事件（候选(candidate)级），分支状态记录。
- pool_node（扇入(fan-in)汇聚）：收集五路通过校验的候选，程序生成 candidate_id，写 candidate_pool。
  - 此节点是五路并行分支的汇聚点（candidate_id 在此唯一生成，渲染打乱 种子(seed) hash(execution_id + candidate_id)依赖它，故渲染不能早于 池(Pool)）。
- render_node（ADR-023）：pool_node 之后、约束处理之前的**唯一渲染点**，调用 resolve_anchor 将锚解析为毫秒，组装带真实毫秒、已打乱的渲染候选集，写入 State.rendered_candidates。
  - 调用 scheduling/constraints.py 的 resolve_anchor（本模块是唯一实现处，render_node 直接 import 它）解析 触发(trigger)/揭晓(reveal)锚。
  - 时间字段：show_at = 锚 start；reveal_time = reveal 锚 start；reveal_delay = 配置常量（与锚点无关）。
  - duration_ms 按类型时长表展开；repeat_keyline 取锚区间 + tail，clamp 至 KEYLINE_DURATION_FLOOR / KEYLINE_DURATION_CEIL。
  - deferred_vote 选项以 hash(execution_id + candidate_id)为种子确定性打乱；**打乱时同步将 answer_id 重映射为正确项在打乱后数组中的新索引**（保留「options[0] 为正确答案」约定，重映射由 render_node 负责）。
- constraints_node：调用 scheduling/constraints.py 做 确定性(Deterministic)预处理(Preprocessing)，输出确定性存活集与待取舍集合；待取舍集为空则跳过 semantic（条件边）。
  - 时间合理性校验（含 deferred_vote）在冲突组之前执行：规则定义在 rules.py 分组 B；不合法候选直接丢弃，复用本模块淘汰清单机制，不走 repair。
  - **确定性存活集写入 State.selected_candidates**：跳过 semantic 时它就是终检输入，保证字段在任何路径下都有值。
  - 淘汰 / 合并 / 标记的候选连同确定性原因写入 State.constraints_report（供 基准评测(benchmark)统计与 可观测性(observability)）。
- semantic_node：调用 scheduling/semantic.py；keep/drop 写 scheduler_decision，**语义取舍结果覆盖 State.selected_candidates**。
  - 无法返回合法选择 → 产出调度级 人工介入(HITL)事件。
- final_check_node：复用 constraints 的终检函数验收选中集，**违规即报错（不静默修正）**。
  - 通过终检后产出 final_interactions（按 show_at、duration_ms 排序，赋 1-based 标识(id)）。
  - 终检在渲染之后验真实毫秒，并承担新增三项校验：毫秒字段合法性、reveal 时间合法性、answer_id 与已打乱 选项(options)的索引一致。
    - 毫秒字段合法性：非负，且 keyline 的 duration_ms 在 KEYLINE_DURATION_FLOOR / KEYLINE_DURATION_CEIL 上下限内。
    - reveal 时间合法性：reveal_time >= show_at + duration_ms + reveal_gap_min_ms。
    - answer_id 与已打乱 选项(options)的索引一致（渲染已打乱，终检在渲染之后）。
- 人工介入(HITL) interrupt 挂点：两处，interrupt 后 status=waiting_for_human，人工结果经 resume 写回后从挂点继续（PRD §13 恢复点定义）。
  - 分支修复耗尽处（branch_validate_repair 尾部，候选(candidate)级 / 分支级）。
  - semantic 失败处（调度级）。

## 关键设计点

- 分支隔离的节点表达：五路 生成专家(Specialist) + 各自分支内校验修复互不依赖，单分支异常（大语言模型(LLM)持续失败等）只该分支进 人工介入(HITL)，其余四路照常汇入 池(Pool)（ADR-015）——分支节点的异常处理路径必须保证不向其他分支传播。
- 校验-修复循环在分支内、用条件边表达，循环上界由 repair 重试上限决定——图里不存在任何「回到 adapter / 回到 生成专家(Specialist)整体重扫」的边。
- pool_node 是唯一 candidate_id 生成点，保证 标识(ID)全局唯一且可追溯（候选(candidate) → specialist_type → evidence_window_ids）。
- 大语言模型(LLM)调用只出现在 specialist_node 与 semantic_node（以及 repair 循环内的定向退回）——与「大语言模型(LLM)调用点仅三类」的全局约束一致。

## 待定项

- branch_validate_repair 的循环表达细节（条件边 vs 子图）：倾向条件边，装配时与 builder 对齐。
- 分支级持续失败（大语言模型(LLM)全挂）与 候选(candidate)级失败在 人工介入(HITL)事件中的区分字段。

## 测试要点

- 每个节点用假业务模块 / 假 大语言模型(LLM)单测：输入 工作流状态(State) → 输出 工作流状态(State)的字段断言。
- 分支隔离注入测试：单分支抛持续异常，其余分支结果完整、状态进入 waiting_for_human。
- 条件边行为：待取舍集合为空时 semantic 不执行；终检违规时报错路径。
- 全图干跑（小 工作流状态(State) + 假 大语言模型(LLM)）：正常路径与异常路径各一条。
