# evidence/adapter.py 内容计划

本模块把 V1 片段输入确定性地适配为共享证据（Evidence）文档。

## 职责与边界

- 读取一集 V1 片段 JSON 和起始媒体预处理阶段提供的真实集长，构造并落盘一个 EvidenceDocument。
- 维护 V1 片段标识到 T<n>、O<n> 证据标识的稳定映射。
- 不调用模型，不分析剧情，不创建派生证据，也不让生成专家直接访问原媒体。

## 输入、输出与接口

- 输入是一集 V1 片段文件、工作流状态中的 episode_duration_ms 和配置提供的输入输出根目录。
- 输出为已校验的 EvidenceDocument，落盘到 data/evidence/<剧名>/<集名>.json，并回写给图状态。
- 起始媒体预处理阶段负责探测并向上取整集长；适配器只校验并写入 episode_duration_ms。

## 依赖与消费者

- 依赖 schemas/evidence、config 和媒体预处理阶段写入的工作流状态。
- graph/nodes 调用适配器；evidence/render、specialists、validation 和 scheduling 消费生成的证据文档。

## 目标实现要求

- 相同 V1 JSON 和同一 episode_duration_ms 必须产生逐字稳定的证据文档，重复执行不改变结果。
- 保留 V1 中可验证的台词、视觉、屏幕文字、音频和不确定性信息；不添加模型推断。
- 适配后立即通过 EvidenceDocument 校验，再原子写入目标文件。
- 片段时间必须与真实集长一致；任何超界时间都作为上游数据错误暴露。

## 失败与边界情形

- 输入 JSON 缺失、字段非法、时间无法解析或 episode_duration_ms 缺失/非法时快速失败，不从 V1 时间线推导替代集长。
- 空证据文档是合法输出，但由图层短路后续模型调用。
- 已有输出与新输入不一致时不得静默复用旧文件。
- V1 字段映射的细节调整只维护在 [PROGRESS](../../../../PROGRESS.md)。

## 验证

- 使用固定 JSON 与 episode_duration_ms 验证稳定映射、落盘路径和重复执行一致性。
- 覆盖无台词、无观察、空证据、乱序、负时间、超集长和 malformed JSON。
- 覆盖缺失或非法 episode_duration_ms 和输出写入失败。
- 验证产物能被 EvidenceDocument 读回，且不含解释性字段。
