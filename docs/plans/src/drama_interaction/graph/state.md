# src/drama_interaction/graph/state.py 内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-015 / 022、PRD §6.2 / §13 / §17 / §20.2

## 职责与边界

- 定义 工作流状态(Workflow State)：LangGraph 全图共享状态的字段结构、并行汇聚的追加式 归并器(reducer)、状态机枚举。
- 落实 证据(Evidence)契约与 工作流状态(Workflow State)的分层（ADR-022）：EvidenceWindow[] 是共享数据契约本体，集(episode)级元数据只在 工作流状态(State)（PRD §6.2）。
  - 集(episode)级元数据指：剧名、集名、执行(execution)标识。
- 明确不做：不含业务逻辑；不做节点函数；不做持久化介质选择（builder 的事）。

## 依赖关系

- 依赖 schemas 三模块（工作流状态(State)内嵌的数据类型）。
- 被依赖方：graph/nodes.py（读写 工作流状态(State)）、graph/builder.py（状态图(StateGraph)装配时引用 工作流状态(State)类型与 归并器(reducer)）、命令行(cli)（读取最终结果与状态）。

## 主要组成

工作流状态(State)字段组（覆盖 PRD §17 要求保留的全部内部状态）：

```text
WorkflowState
├─ execution                    # execution 元数据
│  ├─ execution_id              # = LangGraph checkpoint thread id
│  ├─ drama_name / episode_name
│  ├─ status                    # running / waiting_for_human / completed / failed
│  └─ created_at / updated_at
├─ evidence                     # EvidenceWindow[]（adapter 节点写入，之后只读）
├─ specialist_results           # 五类 SpecialistResult 容器（追加式 reducer）
│                               # 含解析失败的原始返回留存
├─ candidate_pool               # 通过分支校验的候选（入池时程序赋 candidate_id）
├─ hitl_queue                   # 待人工项（candidate 级 / 分支级 / 调度级）
│                               # 每项含触发原因、上下文、人工动作结果
├─ repair_log                   # 修复尝试记录（输入、动作、结果）
├─ constraints_report           # 约束阶段淘汰/合并/标记的候选清单（每项含确定性原因：
│                               # 哪条约束、与谁冲突——供 benchmark 统计与可观测性）
├─ scheduler_decision           # keep / drop 及理由（可能为空=未触发语义调度）
├─ rendered_candidates         # render_node 产出：全部候选（带真实毫秒、已打乱），调度与终检的输入
├─ selected_candidates         # 进入终检的选中集：constraints_node 先写入确定性存活集，
│                               # semantic_node 触发时以语义取舍结果覆盖（跳过 semantic 时存活集即终检输入）
├─ final_interactions           # FinalInteraction[]：终检通过后按 (show_at, duration_ms) 排序、赋 1-based id 的成品
└─ metrics                      # 调用次数、重试次数、HITL 次数、节点耗时
                              # 拆三层的附带收益：benchmark 能单独统计「渲染了但未被选中」的候选（调度质量评估素材），HITL 调度级事件可明确引用哪一层
```

- 追加式 归并器(reducer)：specialist_results / candidate_pool / hitl_queue / repair_log 等列表字段由五路并行分支或多次节点写入，必须声明追加合并语义（实现为对 list 的合并函数声明）。
  - 原因：LangGraph 静态并行多边写同一键时，无 归并器(reducer)会报并发更新错误（INVALID_CONCURRENT_GRAPH_UPDATE），有 归并器(reducer)则按追加合并。
  - 这是 ADR-015「成功结果立即持久化、互不覆盖」的状态层保障。
- 人工介入(HITL)状态语义：status=waiting_for_human 时图在 interrupt 点暂停；人工 accept / edit / drop 的结果写回 hitl_queue 对应项后 resume（恢复点=触发 人工介入(HITL)的节点，PRD §13 恢复点定义）。
- 状态机：status 的合法迁移（running→waiting_for_human→running→completed / failed）在 工作流状态(State)层定义，供 命令行(cli)与 可观测性(observability)消费。

## 关键设计点

- 证据(evidence)只写一次（adapter 节点）后全程只读：证据(Evidence)是共享契约数据，不是可变工作区——与 ADR-016「已完成 证据(Evidence)不重跑」对应。
- 五路并行只写各自的容器条目（按 specialist_type 隔离），归并器(reducer)保证合并不丢不重。
- 保留 生成专家(Specialist)原始结果与解析失败留存的字段（PRD §17：用于调试、评测、回溯），即使该分支后来失败。
- 指标(metrics)内嵌 工作流状态(State)使 可观测性(observability)数据随 检查点(checkpoint)持久化，resume 后计数连续。

## 待定项

- specialist_results 容器形态：按类型分键的 dict 还是带类型标记的扁平 list（倾向 dict，键即五类型，天然无写入冲突；list+归并器(reducer)作为备选）。
- 指标(metrics)的具体字段清单与统计口径（与 基准评测(benchmark)对接时冻结）。
- hitl_queue 条目的完整字段（与 validation/repair.py 的 人工介入(HITL)事件、命令行(cli)的交互展示三方对齐后冻结）。

## 测试要点

- 归并器(reducer)语义可完全离线测试：模拟五路并发写入同一字段，断言合并不丢不重、顺序无关。
- 状态机迁移的合法性测试。
- 工作流状态(State)序列化 round-trip（检查点(checkpoint)持久化前提）。
