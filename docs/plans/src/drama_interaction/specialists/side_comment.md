# specialists/side_comment.py 内容计划

本模块实现边看边聊（side_comment）专家，公共执行逻辑复用 [base](base.md)。

## 职责与边界

- 为适合旁白吐槽、赞叹、共情或质疑的时刻生成简短评论。
- 保持评论有趣但可由当前集证据验证，不把模型推测写成事实。
- 不负责情绪按钮、投票、金句、时间计算或跨类型排序。

## 输入、输出与接口

- 接收 base 提供的专家输入和本分支证据时间线。
- 输出 specialist_type 为 side_comment 的 SpecialistResult。
- payload 包含 text 和必填 mood；mood 只能是 roast、shock、laugh、praise、sympathy、doubt。

## 依赖与消费者

- 依赖 specialists/base、schemas/candidate、schemas/interaction。
- validation/rules 验证 payload 与证据链；graph/nodes 负责分支运行和入池。

## 目标实现要求

- 评论应贴合可见反差、离谱行为、感人时刻、惊讶点或值得质疑的情节。
- mood 与文本语气和证据情境一致，且作为最终契约必填字段输出。
- 不剧透、不代替角色说出未证实心理，也不以静态上下文充当本集事实。
- 取证后仍无法安全支撑评论时弃权。

## 失败与边界情形

- 缺少 mood、mood 不在六个合法值内、文本无证据或内容剧透时必须拒绝。
- 不得跨分支借用 D<n> 或用空泛占位评论填充产量。
- 文案长度和风格细则只维护在 [PROGRESS](../../../../PROGRESS.md)。

## 验证

- 覆盖六种合法 mood、非法 mood、缺失 mood 和文本为空。
- 验证评论能追溯到当前专家分支可见的证据。
- 验证无可靠评论时返回弃权而不是生成泛化文本。
