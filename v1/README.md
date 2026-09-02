# Drama Highlight Mark

一个面向短剧内容理解与互动素材生产的 LLM 流水线项目。

这个仓库从原始剧集视频出发，生成两类结构化产物：

- 主链路产物：`语义转写 -> 高光识别 -> 互动配置 JSON`
- 扩展链路产物：`剧情分支 JSON -> 分支提示词 -> 分支图片素材`

如果你只需要“短剧高光 + 播放器互动层配置”，跑到 `05_highlight2interaction.py` 即可。
如果你还需要“可回流主线的剧情分支素材”，再继续执行 `06~08`。

> 注意：仓库中工作流脚本实际位于 `pipline/`

## 项目定位

这个项目解决的不是通用字幕提取，而是更偏内容生产侧的结构化理解：

- 把短剧音频转成带时间戳、情绪、语气、音乐、音效线索的语义片段
- 从片段中识别具有互动价值的剧情高光点
- 为高光点生成播放器可直接消费的互动层 JSON
- 基于相邻剧集文本生成“可回流主线”的剧情分支配置
- 为分支内容生成后续素材生产所需的提示词和参考图片

## 当前能力概览

### 主链路

1. `01_video2audio.py`
   批量把 `data/video/` 下的视频转成 `data/audio/` 下的 mp3。

2. `02_extract_desc_char.py`
   从外部页面抓取短剧简介和角色信息，生成 `data/video/drama_info.json`。

3. `03_audio2text.py`
   调用多模态 LLM，把音频转成结构化 `segments` JSON。

4. `04_text2highlight.py`
   基于 `segments` 识别剧情高光点，输出 `highlights` JSON。

5. `05_highlight2interaction.py`
   基于高光点生成 5 类互动配置，输出最终 `interaction` JSON。

### 扩展链路

6. `06_plot_branch.py`
   结合当前集文本、当前集高光和下一集文本，生成“可回流主线”的分支配置。

7. `07_branch_video.py`
   为每个非原剧情分支生成视频级提示词，输出到 `data/branch/prompt/`。

8. `08_branch_image.py`
   从原视频截取触发帧与回流帧，结合步骤 7 的提示词生成分支图片，输出到 `data/branch/image/`。

## 为什么当前是“分支图片”而不是“分支视频”

分支视频原本是这条链路的目标形态，但实际落地时，视频生成成本过高，当前版本只能先退一步，使用“分支提示词 + 参考截帧 + 分支图片”的方案完成验证。

这意味着：

- `06` 和 `07` 仍然保留了面向分支视频的结构设计
- `08` 当前承担的是一个成本可控的替代实现
- 如果后续视频生成成本下降，这条链路有机会从“分支图片”再升级回“分支视频”

## 流程总览

```text
主链路
data/video/*.mp4
  -> 01_video2audio
data/audio/*.mp3
  -> 03_audio2text
data/text/*.json
  -> 04_text2highlight
data/highlight/*.json
  -> 05_highlight2interaction
data/interaction/*.json

扩展链路
data/text/*.json + data/highlight/*.json + 下一集 text
  -> 06_plot_branch
data/branch/json/*.json
  -> 07_branch_video
data/branch/prompt/*.json
  -> 08_branch_image
data/branch/image/*/*.jpeg
```

## 输出物一览

| 步骤 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `01_video2audio.py` | `data/video/<剧名>/第N集.*` | `data/audio/<剧名>/第N集.mp3` | ffmpeg 异步抽音 |
| `02_extract_desc_char.py` | `data/video/name2id.json` | `data/video/drama_info.json` | 聚合剧名、简介、角色信息 |
| `03_audio2text.py` | `data/audio/<剧名>/第N集.mp3` | `data/text/<剧名>/第N集.json` | 结构化 `segments` |
| `04_text2highlight.py` | `data/text/<剧名>/第N集.json` | `data/highlight/<剧名>/第N集.json` | 高光点识别结果 |
| `05_highlight2interaction.py` | `data/highlight/<剧名>/第N集.json` | `data/interaction/<剧名>/第N集.json` | 最终互动层 JSON |
| `06_plot_branch.py` | 当前集 `text` + 当前集 `highlight` + 下一集 `text` | `data/branch/json/<剧名>/第N集.json` | 可回流分支配置 |
| `07_branch_video.py` | `data/branch/json/<剧名>/第N集.json` | `data/branch/prompt/<剧名>/第N集.json` | 非原剧情分支提示词 |
| `08_branch_image.py` | `data/branch/prompt/<剧名>/第N集.json` + 原视频截帧 | `data/branch/image/<剧名>/第N集/*.jpeg` | 当前分支素材产物 |

## 互动类型

`05_highlight2interaction.py` 当前会并行生成 5 类互动项：

| 类型 | 含义 | 典型输出 |
|------|------|----------|
| `emotion_button` | 情绪按钮 | `button_id`、短文案、预制弹幕 |
| `repeat_keyline` | 台词复述 | 一句可直接复读的名台词 |
| `instant_vote` | 即时投票 | 问题 + 2 个选项 |
| `deferred_vote` | 延迟揭晓投票 | 问题 + 选项 + 揭晓时间 + 答案 |
| `side_comment` | 侧边吐槽 | 一句短吐槽 |

调试时可以用 `--type` 单独生成某一类互动：

- `1` = `emotion_button`
- `2` = `repeat_keyline`
- `3` = `instant_vote`
- `4` = `deferred_vote`
- `5` = `side_comment`

## 环境要求

- Python 3.10+
- `ffmpeg`，并且已经加入系统 `PATH`
- 一个兼容 OpenAI API 的文本 / 多模态模型接口
- 一个兼容 OpenAI Images 接口的图片模型接口（只在 `08_branch_image.py` 需要）

## 安装

```bash
pip install -r requirements.txt
```

## 环境变量

在项目根目录创建 `.env` 文件：

```env
LLM_MODEL_ID=your-llm-model-id
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://your-llm-endpoint/v1

VIDEO_MODEL_ID=your-image-model-id
VIDEO_API_KEY=your-image-api-key
VIDEO_BASE_URL=https://your-image-endpoint/v1
```

变量用途如下：

| 变量 | 是否必需 | 用途 |
|------|----------|------|
| `LLM_MODEL_ID` | 必需 | `03/04/05/06/07` 使用的模型 ID |
| `LLM_API_KEY` | 必需 | `03/04/05/06/07` 的 API Key |
| `LLM_BASE_URL` | 必需 | `03/04/05/06/07` 的接口地址 |
| `VIDEO_MODEL_ID` | 仅步骤 `08` 必需 | 分支图片生成模型 ID |
| `VIDEO_API_KEY` | 仅步骤 `08` 必需 | 分支图片生成 API Key |
| `VIDEO_BASE_URL` | 仅步骤 `08` 必需 | 分支图片生成接口地址 |

如果你只跑到 `05` 或 `07`，可以先不配置 `VIDEO_*`。

## 数据准备

### 1. 准备视频

按下面的目录组织原始剧集视频：

```text
data/
  video/
    某短剧/
      第1集.mp4
      第2集.mp4
```

### 2. 准备短剧元数据

`03/04/06/07` 依赖 `data/video/drama_info.json`。你有两种准备方式：

- 方式 A：先准备 `data/video/name2id.json`，再执行 `02_extract_desc_char.py`（仅限红果短剧）
- 方式 B：手动维护 `data/video/drama_info.json`

`name2id.json` 的最小格式示例：

```json
[
  {
    "name": "某短剧",
    "book_id": "123456"
  }
]
```

## 快速开始

### 只跑主链路：高光与互动

```bash
python pipline/02_extract_desc_char.py
python pipline/01_video2audio.py
python pipline/03_audio2text.py
python pipline/04_text2highlight.py
python pipline/05_highlight2interaction.py
```

### 继续跑扩展链路：剧情分支与分支图片

```bash
python pipline/06_plot_branch.py
python pipline/07_branch_video.py
python pipline/08_branch_image.py
```

### 常用单文件命令

```bash
# 只处理一集视频
python pipline/01_video2audio.py --video-path data/video/某短剧/第1集.mp4

# 抓取单部短剧信息
python pipline/02_extract_desc_char.py --book-id 123456
python pipline/02_extract_desc_char.py --name 某短剧

# 只转一集音频
python pipline/03_audio2text.py --audio-path data/audio/某短剧/第1集.mp3

# 只做一集高光识别
python pipline/04_text2highlight.py --text-path data/text/某短剧/第1集.json

# 只做一集互动生成
python pipline/05_highlight2interaction.py --highlight-path data/highlight/某短剧/第1集.json

# 调试：只输出某一种互动类型到 stdout，不落盘
python pipline/05_highlight2interaction.py --highlight-path data/highlight/某短剧/第1集.json --type 1

# 只生成一集剧情分支
python pipline/06_plot_branch.py --text-path data/text/某短剧/第1集.json

# 只生成一集分支提示词
python pipline/07_branch_video.py --branch-path data/branch/json/某短剧/第1集.json

# 只生成一集分支图片
python pipline/08_branch_image.py --prompt-path data/branch/prompt/某短剧/第1集.json
```

## 设计特点

### 1. 严格的结构化输出

每个 LLM 步骤都不是自由文本，而是被提示词约束到明确 JSON 结构，再通过 Pydantic 做二次校验。

### 2. 真实面向落盘产物的校验

仓库不是只验证“模型有没有返回 JSON”，还会验证：

- 时间戳格式是否合法
- segment / highlight / interaction 的引用关系是否闭环
- 台词复述是否真的存在于证据片段中
- 延迟投票是否能正确回算揭晓时间和答案下标
- 分支配置是否真的能回流到当前集或下一集

### 3. 异步批处理

`ffmpeg`、网页抓取和多文件 LLM 调用都按批处理方式组织，默认支持目录级递归扫描与跳过已有产物。

### 4. 为未来视频分支预留结构

虽然当前最终产物是分支图片，但 `07` 和 `08` 的数据结构仍然围绕“可回流的分支视频内容”设计，这让后续升级路径比较清晰。

## 接口有效性验证

`test/` 目录：

- `test/test-audio.py`
- `test/test-text.py`

这两个脚本都依赖有效的 `.env` 和可用的模型接口，可以测试模型文本和音频模态有效性

## 当前问题

当前链路已经能跑通从视频到高光、互动和分支素材的核心流程，但还没有达到稳定的全自动生产状态，主要问题包括：

- 音频转写、高光识别和剧情分支理解仍然依赖 LLM 判断，存在识别不准、结果波动和局部字段偏差的问题。
- 实际使用中通常还需要人工检查中间产物，决定是否补跑、跳过或手动修正异常结果。
- 现阶段的流程更接近“可串联的脚本流水线”，还不是一个真正具备统一状态管理、失败恢复和任务调度能力的自动化系统。

因此，这个仓库当前更适合做原型验证、流程打磨和数据结构迭代，而不是直接作为完全无人值守的生产方案。

## 后续规划

后续计划逐步将现有脚本式流水线迁移到基于 LangGraph 的工作流架构。

目标不是单纯更换框架，而是把转写、高光识别、互动生成、剧情分支和分支素材生成统一到一个可编排、可追踪、可恢复的执行图中，逐步实现：

- 更少的手动操作
- 节点级重试与失败恢复
- 关键步骤的人工审核插点
- 更完整的批量任务调度和全流程自动化能力

## 项目结构

```text
drama-highlight-mark/
├── pipline/
│   ├── 01_video2audio.py
│   ├── 02_extract_desc_char.py
│   ├── 03_audio2text.py
│   ├── 04_text2highlight.py
│   ├── 05_highlight2interaction.py
│   ├── 06_plot_branch.py
│   ├── 07_branch_video.py
│   ├── 08_branch_image.py
│   ├── common/
│   │   ├── config.py
│   │   ├── paths.py
│   │   ├── runtime.py
│   │   └── schemas.py
│   └── steps_05/
│       ├── deferred_vote.py
│       ├── emotion_button.py
│       ├── instant_vote.py
│       ├── repeat_keyline.py
│       └── side_comment.py
├── data/
│   ├── video/
│   ├── audio/
│   ├── text/
│   ├── highlight/
│   ├── interaction/
│   └── branch/
│       ├── json/
│       ├── prompt/
│       └── image/
├── test/                       # 当前仅保留手工联调脚本
├── docs/codex/plans/
├── schema.md
└── requirements.txt
```

## 已知限制

- `02_extract_desc_char.py` 依赖目标站点页面结构和 `data/video/name2id.json`。
- `03/04/06/07` 依赖 `data/video/drama_info.json`；缺失时会直接报错。
- `06_plot_branch.py` 需要“当前集 + 下一集”的文本，最后一集会被跳过。
- `08_branch_image.py` 当前输出的是分支图片，而不是分支视频；这是基于生成成本做出的现实折中。
- `test/` 目录当前不是完整自动化测试套件，更多是接口联调用脚本。
- LLM 输出已经做了 schema 校验，但如果要直接投入生产，仍建议保留人工抽检。
