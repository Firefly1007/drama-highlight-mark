# V2 实现计划索引

本目录描述 V2 的目标实现，不记录完成状态、迭代过程或未决项。项目现状与未决项只看 [PROGRESS](../PROGRESS.md)。

## 文档职责

| 文档 | 负责回答的问题 |
| --- | --- |
| [README](../../README.md) | 项目是什么，如何进入文档体系 |
| [PRD](../drama-interaction-v2-PRD.md) | 要做哪些互动，以及产品验收标准 |
| [ADR](../drama-interaction-v2-ADR.md) | 为什么采用当前技术与流程决策 |
| [输出契约](../schema.md) | 后端会收到什么 JSON |
| [PROGRESS](../PROGRESS.md) | 实际做到哪里、阻塞项和下一步 |
| 本目录 | 每个模块要实现什么、与谁交互、如何验收 |

## 阅读顺序

1. 先读 [PRD](../drama-interaction-v2-PRD.md)、[ADR](../drama-interaction-v2-ADR.md) 与 [输出契约](../schema.md)。
2. 再读三个基础数据计划：schemas/evidence、schemas/candidate、schemas/interaction。
3. 接着读 evidence、specialists、validation、scheduling，了解单集互动点生成链路。
4. 最后读 graph、cli、config、llm 与 [project-config](project-config.md)，了解运行和交付方式；剧集 `DramaContext` 的加载与提示词注入由 config/cli 计划共同约束。

## 模块计划

| 计划 | 对应源码 | 目标职责 |
| --- | --- | --- |
| [cli](src/drama_interaction/cli.md) | cli.py | 运行、恢复、导出入口 |
| [config](src/drama_interaction/config.md) | config.py | 唯一配置入口 |
| [llm](src/drama_interaction/llm.md) | llm.py | 唯一模型网络出口 |
| [schemas/evidence](src/drama_interaction/schemas/evidence.md) | schemas/evidence.py | 证据文档与派生证据契约 |
| [schemas/candidate](src/drama_interaction/schemas/candidate.md) | schemas/candidate.py | 候选、锚点和专家结果契约 |
| [schemas/interaction](src/drama_interaction/schemas/interaction.md) | schemas/interaction.py | 最终互动及五类 payload 契约 |
| [evidence/adapter](src/drama_interaction/evidence/adapter.md) | evidence/adapter.py | V1 片段到证据文档的确定性适配 |
| [evidence/render](src/drama_interaction/evidence/render.md) | evidence/render.py | 可引用的证据时间线渲染 |
| [evidence/service](src/drama_interaction/evidence/service.md) | evidence/service.py | 按需取证接口与审计 |
| [specialists/base](src/drama_interaction/specialists/base.md) | specialists/base.py | 五类专家的公共执行骨架 |
| [specialists/emotion_button](src/drama_interaction/specialists/emotion_button.md) | specialists/emotion_button.py | 情绪按钮专家 |
| [specialists/repeat_keyline](src/drama_interaction/specialists/repeat_keyline.md) | specialists/repeat_keyline.py | 跟读金句专家 |
| [specialists/instant_vote](src/drama_interaction/specialists/instant_vote.md) | specialists/instant_vote.py | 即时投票专家 |
| [specialists/deferred_vote](src/drama_interaction/specialists/deferred_vote.md) | specialists/deferred_vote.py | 延时投票专家 |
| [specialists/side_comment](src/drama_interaction/specialists/side_comment.md) | specialists/side_comment.py | 边看边聊专家 |
| [validation/rules](src/drama_interaction/validation/rules.md) | validation/rules.py | 候选局部确定性校验 |
| [validation/repair](src/drama_interaction/validation/repair.md) | validation/repair.py | 安全修复、定向重生与人工交接 |
| [scheduling/constraints](src/drama_interaction/scheduling/constraints.md) | scheduling/constraints.py | 全局确定性约束和终检 |
| [scheduling/semantic](src/drama_interaction/scheduling/semantic.md) | scheduling/semantic.py | 只处理语义取舍的调度器 |
| [graph/state](src/drama_interaction/graph/state.md) | graph/state.py | 单集工作流状态和归并规则 |
| [graph/nodes](src/drama_interaction/graph/nodes.md) | graph/nodes.py | 工作流节点编排 |
| [graph/builder](src/drama_interaction/graph/builder.md) | graph/builder.py | LangGraph 图装配、暂停和恢复 |

共有 22 份源码模块计划；[project-config](project-config.md) 说明根配置文件，不对应单个 Python 模块。

## 维护规则

- 每份模块计划固定写明：职责与边界、输入输出与接口、依赖与消费者、目标实现要求、失败与边界情形、验证。
- 产品规则改 [PRD](../drama-interaction-v2-PRD.md)，技术取舍改 [ADR](../drama-interaction-v2-ADR.md)，后端 JSON 改 [输出契约](../schema.md)；模块计划只保留实现所需的引用和局部要求。
- Specialist 的共用提示词、五类完整 V1 规则和调度器提示词只维护在 `src/drama_interaction/config.py`，模块计划不复制全文。
- 实施状态、暂缓内容、阻塞项和待确认参数统一更新到 [PROGRESS](../PROGRESS.md)，不要复制到模块计划。
