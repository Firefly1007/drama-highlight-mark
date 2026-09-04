# validation/rules.py 内容计划

本模块提供候选入池前的局部确定性校验（Local Constraint Validation）。

## 职责与边界

- 对单个候选及其专家分支证据视图执行结构、引用、payload 和明显重复检查。
- 将失败写成可路由的结构化错误，供 repair 或人工流程消费。
- 不调用模型、不修改候选、不评价互动价值，也不执行全局调度。

## 输入、输出与接口

- 输入为 Candidate、对应 SpecialistResult、基线加当前分支派生证据和必要配置。
- 输出为零个或多个结构化错误：类别、字段定位、期望值、实际值和建议处理路径。
- 规则需要能复用锚点解析和最终互动的时间合法性检查。

## 依赖与消费者

- 依赖三个 schemas 模块；与 scheduling/constraints 共用确定性断言。
- graph/nodes 在每个专家分支调用；validation/repair 根据错误类型选择处理。

## 目标实现要求

- 校验 payload 与 specialist_type 匹配、生成侧不携带最终毫秒、五类字段满足 [输出契约](../../../../schema.md)。
- 校验 evidence_ids 非空且存在于当前分支视图，trigger_anchor 和 reveal_anchor 合法，锚点引用包含在 evidence_ids。
- deferred_vote 的 reveal_anchor 必须晚于 trigger_anchor；派生证据引用不可跨分支或成环。
- 验证 repeat_keyline 的文本可在台词中找到，并识别同锚点且关键 payload 相同的明显重复候选。
- 规则函数保持纯函数，输出稳定，不自动修正输入。

## 失败与边界情形

- 缺失证据、非法锚点、错误 payload、编造台词和重复候选都形成可追踪错误。
- 时间字段在渲染后才完整出现；渲染后的全局时间约束由 constraints 终检。
- 长度阈值、文本归一化程度和重复近似策略只维护在 [PROGRESS](../../../../PROGRESS.md)。

## 验证

- 为每类规则构造正反样例，断言错误包含完整路由信息。
- 覆盖 T<n>、O<n>、本分支 D<n> 和另一分支 D<n> 的引用。
- 与 repair 联测可修复错误白名单，与 constraints 联测渲染后时间规则。
- 断言校验不会修改 Candidate 或证据对象。
