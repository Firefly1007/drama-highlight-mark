# src/drama_interaction/evidence/adapter.py 内容规划

- 状态：规划中（未实现）
- 上游依据：ADR-007、PRD §7、PRD §20.3、README.md「使用」节

## 职责与边界

- 旧版证据适配器(Legacy Evidence Adapter)：把 V1 片段(segments) JSON 确定性地转换为 `EvidenceWindow[]` 并落盘 `data/evidence/<剧名>/<集名>.json`。
- 是临时兼容层：未来真正的 证据(Evidence)抽取(Extraction)只需输出同一 `EvidenceWindow[]` 契约即可整体替换本模块（ADR-007），因此内部不做任何 V2 下游才知道的假设。
- 明确不做：不调用 大语言模型(LLM)、不增加任何新的内容理解（PRD §20.3）；不做剧情解释；不补 visual / onscreen text（PRD §7 明确为空）；不修改 V1 数据。

## 依赖关系

- 依赖 schemas/evidence.py（构造目标结构）、config.py（window_size_ms 与落盘路径）。
- 被依赖方：
  - graph/nodes.py（适配器(Adapter)节点调用）
  - 命令行(cli)（运行(run)命令入口侧）
  - 基准评测(benchmark)（人工校正流程读它落盘的文件回流 黄金用例(golden)）
- 输入为 V1 数据产物（data/text/<剧名>/<集名>.json），不 import V1 代码。

## 主要组成

- V1 输入读取与结构假设（基于真实样例核实）：
  - 顶层数组，每段字段：id、start、end、text、speech、emotion、voice、music、audio_cues、uncertainty。
    - id：整数
    - start / end：`HH:MM:SS.mmm` 字符串，需解析为毫秒
    - audio_cues：字符串数组
  - 退化文件真实存在：部分集只有一个空 text 的大段或近乎空文件（已核实第10集样例），必须显式处理而非崩溃。
- 时间解析：`HH:MM:SS.mmm` 字符串 → 毫秒整数（纯确定性函数，独立可测）。
- 窗口切分：从 0 开始按 window_size_ms（3000）切分；窗口数量由最后内容时间决定。
  - 末窗的 start/end 仍由窗口序号推导（保持「窗口边界由序号确定」不变量）。
  - 末窗口径已定：除末窗外相邻窗口差值等于 window_size_ms，末窗 end 由序号边界确定、允许短于 window_size_ms（与 schemas/evidence.md 一致）。
  - V1 片段(segment)与窗口相交即纳入，跨窗完整复制并保留同一 标识(ID) / 时间 / 文本。
- 字段映射（PRD §7）：
  - text → transcript_segments.text；id / start / end → transcript id / start_ms / end_ms；speaker_label = null。
  - speech / voice / music / audio_cues → 整理为 audio_observations 的文本条目（按来源前缀逐条转写，如「说话方式：单人发言」「嗓音：语速较快，音量明显提高」「背景音乐：……」「音效：……」，保持客观转写、不加解释）。
  - emotion → 显式丢弃，绝不进入任何字段（ADR-007 / PRD §7）。
  - visual_observations 与 onscreen_text_segments → 恒为空数组。
  - V1 不确定性(uncertainty)非空时 → 并入相关窗口的 不确定性(uncertainty)条目（已确定；客观保留上游标注，符合 ADR-002。实测全部 3512 个 片段(segment)中仅约 0.7% 非空，影响面小；此映射超出 PRD §7 字面清单，已同步回填 产品需求文档(PRD)）。
- 空集处理：全空 / 无有效台词的集产出空窗口数组并显式返回「空证据」状态标记，供下游与人工检查，不伪造窗口。下游（图(graph)层）遇空证据直接短路：产出空互动数组并标记，不进入五路 生成专家(Specialist)（避免空跑 5 次 大语言模型(LLM)）。
- 落盘：写 `data/evidence/<剧名>/<集名>.json`，内容为纯 EvidenceWindow[] 数组（与契约根节点一致）；目录不存在则创建；重复运行覆盖（adapter 是确定性纯函数，重跑幂等）。

## 关键设计点

- 幂等与确定性：同输入必得同输出，重跑不产生差异——这是它作为 基准评测(benchmark)临时上游的前提。
- 时间字符串解析是本模块唯一的「格式风险点」，独立成可单测的纯函数，异常时间格式显式报错而非静默夹紧。
- emotion 丢弃要留痕：转换日志/报告中说明丢弃字段清单，避免「为什么 证据(Evidence)没有情绪」被误判为 bug。
- 落盘文件保持纯契约数组（不包裹 集(episode)元数据），人工校正后可直接回流 benchmark/golden/evidence/。

## 待定项

- 说话人信息：V1 speech 只描述说话方式（单人发言等），不映射 speaker_label（保持 null），未来真实上游提供 说话人分离(diarization)才启用。

## 测试要点

- 时间解析函数：正常值、零点、边界进位、非法格式显式报错。
- 端到端（纯离线）：用真实 V1 样例（含正常集与空集）作 fixture，断言窗口切分、跨窗复制同 标识(ID)、字段映射、emotion 不出现于任何输出。
- 幂等测试：同输入两次运行落盘结果逐字节一致。
