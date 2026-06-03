# Drama Highlight Mark

基于 LLM 的短剧高光点识别与互动方案自动生成流水线。

从原始短剧视频出发，自动完成 **音频提取 → 语义转写 → 高光识别 → 互动方案生成** 的端到端处理，输出可直接用于播放器互动层的结构化 JSON 数据。

## 核心能力

- **音频语义转写**：基于多模态 LLM，将音频转为带时间戳、情绪、语气、音效等多维标注的结构化片段（Segment）
- **高光点识别**：基于 LLM 提示工程，从语义片段中识别剧情高光时刻，输出摘要、强度等级、触发片段和证据链
- **互动方案生成**：针对每个高光点，自动生成 5 种互动类型的配置数据（情绪按钮、台词复述、即时投票、延迟揭晓投票、侧边吐槽）
- **全链路 Pydantic 校验**：每个步骤的输入输出均有严格的数据模型定义，支持自动修复、交叉校验和重试机制

## 技术架构

```
video/
  ├── 01_video2audio.py        # ffmpeg 异步批量提取音频
  ├── 02_extract_desc_char.py  # 爬取短剧简介与角色信息
  ├── 03_audio2text.py         # 多模态 LLM 音频语义转写
  ├── 04_text2highlight.py     # LLM 高光点识别与打标
  └── 05_highlight2interaction.py  # LLM 互动方案生成（5 种类型并行）
      └── steps_05/
          ├── emotion_button.py    # 情绪按钮
          ├── repeat_keyline.py    # 台词复述
          ├── instant_vote.py      # 即时投票
          ├── deferred_vote.py     # 延迟揭晓投票
          └── side_comment.py      # 侧边吐槽
```

### 数据流

```
视频文件 ──ffmpeg──→ 音频文件 ──LLM──→ 语义片段(Segments) ──LLLM──→ 高光点(Highlights) ──LLM──→ 互动方案(Interactions)
```

每一步的输出均为结构化 JSON，存储在 `data/` 目录下对应的子文件夹中。

## 技术栈

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| LLM 调用 | OpenAI API (AsyncOpenAI) | 兼容任意 OpenAI 兼容接口 |
| 数据校验 | Pydantic v2 | 全链路模型定义，含字段校验、交叉校验、自动修复 |
| 音频提取 | ffmpeg + asyncio | 异步子进程批量转换 |
| 信息爬取 | aiohttp + BeautifulSoup | 异步批量抓取短剧元数据 |
| 进度展示 | tqdm | 同步/异步进度条 |
| 配置管理 | dotenv | 环境变量隔离 |

## 工程设计亮点

### 1. 提示工程驱动的结构化输出

每个 LLM 步骤都通过精心设计的 System Prompt 约束模型输出格式，配合 Pydantic 模型做严格校验：

- 高光识别提示词包含 **判断标准、筛选偏好、输出结构、自检规则** 等多层约束
- 音频转写提示词定义了 **切分规则、字段语义、不确定性标注** 等规范
- 互动方案每种类型都有独立的 **生成条件、文案规则、类型匹配策略**

### 2. 多层数据校验与容错

```
模型输出 → Markdown 去除 → JSON 解析 → Pydantic 模型校验 → 交叉校验 → 重试
```

- 时间戳格式自动补全（`MM:SS.mmm` → `00:MM:SS.mmm`）
- segment id 连续性自动修正
- highlight 与 segment 交叉校验证据链完整性
- 互动方案中台词复述校验原文存在性
- 延迟投票选项随机打乱并重算答案下标
- 全链路最多 3~5 次自动重试

### 3. 异步并发处理

所有 I/O 密集型操作均采用 `asyncio` 实现：

- 音频提取：`asyncio.create_subprocess_exec` 并行调用 ffmpeg
- 信息爬取：`aiohttp` 共享 Session 并发请求
- LLM 调用：`tqdm_asyncio.as_completed` 并发处理多文件
- 互动方案：5 种类型通过 `asyncio.gather` 并行生成

### 4. 严格的数据模型设计

使用 Pydantic v2 定义了完整的类型体系：

- `Segment` / `SegmentsDocument`：音频语义片段
- `SemanticHighlightItem` / `FinalHighlightItem` / `HighlightsDocument`：高光点（模型输出 → 最终落盘）
- 5 种互动类型的 Model 输出 / Prepared 中间态 / Final 最终态三层模型
- `Discriminated Union` 实现多态互动项的类型安全分发

### 5. 模块化 Pipeline 设计

每个步骤独立可运行（CLI 单文件执行），支持：

- 单文件处理（传入具体路径）
- 目录批量处理（递归扫描，跳过已完成文件）
- 默认处理 `data/` 下全部文件
- 路径自动推导（`video → audio → text → highlight → interaction`）

## 互动方案类型

| 类型 | 说明 | 输出内容 |
|------|------|---------|
| 情绪按钮 (emotion_button) | 爽/笑/丢番茄/护住TA/心疼TA/磕到了 | 按钮类型 + 短文案 + 预制弹幕 |
| 台词复述 (repeat_keyline) | 高光时刻的名台词复述 | 复述文案 |
| 即时投票 (instant_vote) | 二选一即时站队 | 问题 + 两个选项 |
| 延迟揭晓投票 (deferred_vote) | 先投票，后续剧情揭晓时结算 | 问题 + 选项 + 揭晓时间 + 答案 |
| 侧边吐槽 (side_comment) | 旁白式吐槽短句 | 吐槽文案 |

## 快速开始

### 环境要求

- Python 3.10+
- ffmpeg（需在 PATH 中）

### 安装

```bash
pip install -r requirements.txt
```

### 配置

在项目根目录创建 `.env` 文件：

```env
LLM_MODEL_ID=your-model-id
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-api-endpoint/v1
```

### 运行

```bash
# 完整流水线（每步独立运行）
python pipline/01_video2audio.py
python pipline/02_extract_desc_char.py
python pipline/03_audio2text.py
python pipline/04_text2highlight.py
python pipline/05_highlight2interaction.py

# 单文件处理
python pipline/04_text2highlight.py --text-path data/text/某剧/第1集.json

# 调试模式：只生成指定互动类型
python pipline/05_highlight2interaction.py --highlight-path data/highlight/某剧/第1集.json --type 1
```

## 项目结构

```
drama-highlight-mark/
├── pipline/                    # 流水线核心代码
│   ├── 01_video2audio.py       # 视频转音频
│   ├── 02_extract_desc_char.py # 爬取短剧简介与角色
│   ├── 03_audio2text.py        # 音频语义转写
│   ├── 04_text2highlight.py    # 高光点识别
│   ├── 05_highlight2interaction.py  # 互动方案生成
│   ├── steps_05/               # 5 种互动类型实现
│   └── common/                 # 共享模块
│       ├── config.py           # 环境配置与客户端
│       ├── paths.py            # 路径工具
│       ├── schemas.py          # Pydantic 数据模型
│       └── runtime.py          # 运行时工具（解析、校验、重试）
├── data/                       # 数据目录
│   ├── video/                  # 原始视频 + 元数据
│   ├── audio/                  # 提取的音频
│   ├── text/                   # 语义转写结果
│   ├── highlight/              # 高光点识别结果
│   └── interaction/            # 互动方案最终输出
├── test/                       # 测试
├── docs/codex/plans/           # 设计文档与方案记录
└── requirements.txt
```

## License

MIT
