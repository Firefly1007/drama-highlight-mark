# 原始视频到 V2 基线证据实现计划

状态：`in_progress`

## 1. 目标与成功标准

把现有 V2 生产入口从 V1 片段 JSON 替换为原始 `.mp4`，生成覆盖整集的文本化 `EvidenceDocument`，再交给五个 Specialist。该阶段只做客观取证，不筛选高光、不判断互动点。

完成标准：

- 单集能够生成时间合法、至少含一条台词的完整基线证据。
- 任一必需阶段失败时整集失败，不向 Specialist 提供半成品。
- 目录任务中，失败集被记录后继续下一集。
- 生产链路不调用 V1 adapter。
- 内部及 Specialist 时间线只使用整数毫秒。
- `EvidenceDocument` 保持现有结构，不新增 coverage、帧或音频证据类型。

## 2. 范围与非目标

包含：

- `.mp4` 发现、自然排序、主视频轨时长探测。
- 托管音轨分离、ASR、OCR、VLM、背景音观察。
- 固定三秒切片、4 FPS 中点采帧；四个切片子图并行、每片三路观察合并。
- Evidence 原子落盘、LangGraph 切片级 checkpoint、工作流接入、时间线覆盖状态更新。
- 配置、单元测试及一次真实 API 验证。

本轮不做：

- V1 生产兼容或修改 `v1/`。
- 缓存、半成品 Evidence。
- `inspect_span` 的真实媒体补证，保留现有桩。
- 跨集并发。
- Specialist 长上下文分块。
- 镜头检测、自适应采样、直接上传三秒视频的备用路径。
- 2/4/8 FPS benchmark 框架；4 FPS 暂作 MVP 默认。
- OCR/ASR 去重、文字纠错、跨切片语义去重。
- 本地推理模型或 provider factory/registry。

## 3. 固定实现方案

### 3.1 生产数据流

```text
.mp4
  → ffprobe 主视频轨时长
  → FFmpeg 提取整集 mix.flac
  → 腾讯云数据万象 CI VoiceSeparate 分离 dialogue / background
  → 两个输出下载为 dialogue.mp3 / background.mp3
  → dialogue 输出 URL → Qwen 整集异步 ASR
  → background.mp3 按集长硬切
  → 固定 3 秒切片，四片一批并发
      → 每片子图：4 FPS 有序帧 → OCR / VLM，background.wav 对应切片 → 音频观察
  → 同跨度结果合并为 Observation
  → 完整 EvidenceDocument 校验并原子保存
  → Specialist 时间线
```

图结构调整为：

```text
START → media_prepare / extract_mix（并行）→ separate_audio → transcribe_audio / prepare_background（并行）
      → dispatch_slice_batch → slice 子图 ×4（并行）→ merge_slice_batch ↻
      → assemble_evidence → persist_evidence → render_evidence → Specialists
```

节点边界以能否独立测试、缓存、重试或替换为准：`extract_mix` 只抽取音轨，`separate_audio` 只做 CI 分离，`transcribe_audio` 只做 ASR。父图的 `dispatch_slice_batch` 只选择最多四个跨度，`merge_slice_batch` 只按切片序号写 Observation 并推进索引。每个切片子图只处理一个跨度：`prepare_frames` 和 `prepare_slice_audio` 各自产生一种输入，OCR、VLM、音频观察各自只调用一种模型，最后合并为该片的普通结果。父图使用 LangGraph `Send` 派发子图，并以 `max_concurrency=4` 限制同批切片；子图内原有的三路节点继续由图并行执行。`assemble_evidence` 只构造并校验文档，`persist_evidence` 只原子写正式文件。其条件边决定继续下一批或进入 Evidence 汇聚。删除生产图中的 `adapter` 节点和恒为真的 `has_evidence` 分支；现有下游候选、校验、调度和 HITL 不改。

### 3.2 媒体规则

只新增两个职责明确的模块：

- `media.py`：`ffprobe`、FFmpeg、切片和采帧。
- `evidence/extract.py`：五项 API 调用、结果校验和 Evidence 汇聚。

不引入 OpenCV、Pillow、NumPy、ffmpeg-python 或异步框架。

集长只读取 `ffprobe -select_streams v:0` 返回的主视频轨 `duration`，转换为最近整数毫秒。缺少主视频轨或有效时长直接失败，不回退到容器时长、音轨时长或 V1 数据。

切片公式：

```text
start_ms = 3000 × k
end_ms   = min(start_ms + 3000, episode_duration_ms)
```

每片按 250ms 分桶：

```text
bucket_start = start_ms + 250 × j
bucket_end   = min(bucket_start + 250, end_ms)
sample_ms    = bucket_start + floor((bucket_end - bucket_start) / 2)
```

完整三秒片的目标中点为 `125, 375, …, 2875ms` 共 12 个；不足 250ms 的最终尾桶也取自身中点。FFmpeg 输出 JPEG，不预先增加尺寸配置；实际 API 探针证明超限后再固定缩放值。连续的目标中点合并为一个 4 FPS 批次（从该批首个中点起定量取帧），每个中点得到一张不早于它的帧；源视频提前结束时只保留真正写出的帧（可能少于目标数），不补帧也不回退，某批目标时刻内一张都取不到时按媒体失败处理当前集。

### 3.3 托管 API 与 SDK

环境变量名称保持能力通用化：

```dotenv
AUDIO_SEPARATOR_ACCESS_KEY_ID=
AUDIO_SEPARATOR_ACCESS_KEY_SECRET=
AUDIO_SEPARATOR_BUCKET=
AUDIO_SEPARATOR_REGION=

ASR_MODEL_ID=qwen-audio-3.0-asr-flash-filetrans
ASR_API_KEY=
ASR_BASE_URL=https://dashscope.aliyuncs.com/api/v1

AUDIO_OBSERVER_MODEL_ID=qwen3.5-omni-flash
AUDIO_OBSERVER_API_KEY=
AUDIO_OBSERVER_BASE_URL=

OCR_MODEL_ID=qwen-3.8-flash
OCR_API_KEY=
OCR_BASE_URL=

VLM_MODEL_ID=qwen-3.8-flash
VLM_API_KEY=
VLM_BASE_URL=
```

三组 Qwen 配置允许填写相同值，但代码分别读取，不做隐式回退。

媒体采样、帧 JPEG 质量、CI/ASR 等待与轮询、统一模型重试、OpenAI SDK 重试和图递归上限全部只在 `config.py` 声明默认值；调用模块只导入这些值，不再各自定义可调整常量。既有模型、凭据、目录和互动规则继续由 `Settings` 与 `.env` 提供，不为这些运行默认值新增环境变量。

依赖直接声明：

- `openai`：调用 Qwen 的 OpenAI-compatible 接口。
- `dashscope`：通过阿里云官方 Python SDK 调用 Qwen ASR。
- `cos-python-sdk-v5`：腾讯云 COS/CI 官方 Python SDK，负责上传、提交任务、轮询、签名和下载。
- `httpx`：下载 Qwen ASR 返回的转写 JSON，并提供 OpenAI 网络异常类型。

腾讯云 CI 的上传、建任务、轮询、签名和下载集中在一个具体客户端中，不抽象成通用 HTTP 网关，也不手写签名或请求头。

执行边界：以下协议字段已经按腾讯云 CI 与 DashScope 文档核对；实施时按此契约落地，不再自行猜字段名或增加新的抽象层。

具体协议：

- 腾讯云数据万象 CI：通过官方 `cos-python-sdk-v5` 将 `mix.flac` 上传到配置的 COS Bucket，然后调用 `ci_create_media_jobs` 提交 `VoiceSeparate`。输入对象为 `Input.Object`，`Operation.VoiceSeparate.AudioMode=AudioAndBackground`，输出对象使用 `Object`（background）和 `AuObject`（dialogue），编码为 `mp3`。[提交任务文档](https://cloud.tencent.com/document/product/460/84794)

  ```json
  {
    "Tag": "VoiceSeparate",
    "Input": {"Object": "v2/<剧名>/<集名>/mix.flac"},
    "Operation": {
      "VoiceSeparate": {
        "AudioMode": "AudioAndBackground",
        "AudioConfig": {"Codec": "mp3"}
      },
      "Output": {
        "Region": "<AUDIO_SEPARATOR_REGION>",
        "Bucket": "<AUDIO_SEPARATOR_BUCKET>",
        "Object": "v2/<剧名>/<集名>/background.mp3",
        "AuObject": "v2/<剧名>/<集名>/dialogue.mp3"
      }
    }
  }
  ```

  用 `ci_get_media_jobs` 轮询 `JobsDetail[0].State`；`Submitted`/`Running` 继续等待，`Success` 才继续，`Failed`/`Cancel` 或异常状态使当前集失败。成功后把 `Object` 和 `AuObject` 分别下载为本地 `background.mp3`、`dialogue.mp3`；再为 `AuObject` 生成 1 小时 COS 签名 URL 交给 Qwen ASR，`background.mp3` 按权威集长硬切。

- ASR：通过阿里云官方 `dashscope` Python SDK 发起异步任务，不手写请求头。`ASR_BASE_URL` 使用包含 `/api/v1` 的地址，并映射到 SDK 的 `base_http_api_url`；`ASR_API_KEY` 传给 SDK。模型固定为 `qwen-audio-3.0-asr-flash-filetrans`，输入是 CI 签名后的完整 `dialogue` URL，声道固定为 `channel_id=[0]`。提交时将 `DramaContext.characters` 作为即时 `vocabulary` 传入，全部角色名权重为 `5`。[Qwen 非实时语音识别](https://help.aliyun.com/en/model-studio/non-realtime-speech-recognition-user-guide)

  ```http
  POST /api/v1/services/audio/asr/transcription
  Authorization: Bearer $ASR_API_KEY
  Content-Type: application/json
  X-DashScope-Async: enable
  ```

  ```json
  {
    "model": "qwen-audio-3.0-asr-flash-filetrans",
    "input": {"file_urls": ["<dialogue_signed_url>"]},
    "parameters": {"channel_id": [0]}
  }
  ```

  调用顺序固定为 `Transcription.async_call` → `Transcription.wait`，等待上限与 CI 一致为 3600 秒，超时按整集失败处理。等待完成后检查 `result.output["results"]`，每个子任务的 `subtask_status` 必须为 `SUCCEEDED`；再下载每个 `transcription_url` 指向的 JSON，读取其中的 `transcripts[].sentences[]`。`text`、`begin_time`、`end_time` 直接映射为台词文本、音频内开始毫秒和结束毫秒；任务层 `end_time` 不作句段时间，不消费词级结果，说话人字段留空。转写 URL 约 24 小时有效，下载后立即解析；当前只传一个 `dialogue` URL。`context` 不接入：官方标记当前 SDK 不支持该参数。
- OCR/VLM：使用 OpenAI Python SDK 访问各自配置的兼容 base URL。同一切片的 Base64 JPEG 按采样顺序展开为 `image_url` 内容块；4 FPS 已由本地采样列表体现，OCR、VLM 各调用一次。
- 音频观察：使用 OpenAI Python SDK，把当前背景音切片作为 Base64 `input_audio` 提交给 Qwen Omni。
- 三个 Qwen 调用启用 JSON Object 输出，分别解析 `onscreen_texts`、`visual_observations`/`uncertainty`、`audio_observations`/`uncertainty`。[Qwen 结构化输出](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen-structured-output)
- 所有要求模型输出 JSON 的提示词只注入对应 Pydantic 模型的 `model_json_schema()`，不再手写 JSON 示例；注入内容使用紧凑序列化以节省 token。

ASR 直接返回整数毫秒时间戳；不排序、不重切、不补偿、不截断越界值。零个合法句段或任一句段无时间戳、逆序、越界时整集失败。`T<n>` 按 provider 顺序连续编号。

### 3.4 观察语义与合并

`config.py` 的 `EVIDENCE_SLICE_CONCURRENCY = 4` 是父图每批的固定上限。父图一次派发四个切片子图；每个子图中，采帧和背景音切片并行，随后 OCR、VLM、音频观察三路并行，三路结束后仅合并该片结果。父图收到整批结果后，按切片序号稳定写入 Observation，再进入下一批；不为并发结果提前分配 O 编号。

- OCR：保留所有非空屏幕文字及硬字幕；不分类、不纠错、不与 ASR 去重。
- VLM：只接收当前帧序列和通用观察指令；不接收 DramaContext、台词、OCR 或音频。只描述可见人物、动作、物体、状态和变化；未知人物使用中性外观，不补写采样帧未显示的中间动作。
- 音频观察：只接收当前背景音切片；描述可听声源、事件和变化，不写情绪、心理、剧情暗示或互动价值。无可记录声音返回空数组，不输出“安静”；明确进入或退出静音可以记录。
- 相邻切片重复内容允许保留，不去重。

三路结果按固定字段合并为同一个切片 `Observation`。至少一个内容或不确定性列表非空才创建 `O<n>`；`O<n>` 按实际生成的非空观察连续编号。三路全空不创建空 Observation。

### 3.5 覆盖状态与时间线

`EvidenceDocument` 不增加 coverage 字段。切片网格常量只在 `config.py` 定义，`media.calculate_slices` 读取它们；Renderer 复用该函数得到的固定 3000ms 网格和是否存在完全同跨度的基线 `O<n>` 推导 `covered_empty`：

```text
[已覆盖、无可记录观察 start_ms=3000 end_ms=6500]
```

相邻空切片先合并。台词 `T<n>` 和派生证据 `D<n>` 都不能替代基线 Observation 的覆盖状态。

所有证据行改成：

```text
[T1 start_ms=100 end_ms=1200] ...
[O1 start_ms=0 end_ms=3000] ...
[D1 start_ms=...] ...
```

删除 `_timecode`、旧 gap 并集算法、`min_reported_gap_ms` 配置以及所有 `[未覆盖]` 输出。状态行无 ID、不可引用，仅表示既定采样流程成功处理，不代表逐帧检查或该区间没有事件。

### 3.6 失败、重试与落盘

- COS SDK 自带有限重试；OpenAI-compatible Qwen 调用使用统一重试函数：连接失败、超时、429 和 5xx 最多再重试三次，每次等待一秒；鉴权、请求参数、provider 任务错误及响应 schema 非法不重试。
- DashScope ASR 使用官方 SDK 自带的有限网络重试，外层不叠加公共重试；SDK 重试耗尽、子任务进入 `FAILED`/`CANCELED`/`UNKNOWN` 或结果结构非法时当前集失败。
- CI 处理中状态每五秒轮询，最长一小时；处理中不计为请求失败。
- 任一必需阶段失败立即结束本集，不继续该集后续切片。
- 人声分离完成后，把 `dialogue.mp3`、`background.mp3` 保存在 `data/evidence/<剧名>/<集名>.audio/`；它们是恢复产物，不作为已完成 Evidence 缓存读取。硬切后的 `background.wav` 只在运行目录中暂存，正式 Evidence 写入后删除。
- 依赖 LangGraph 的 PostgreSQL checkpoint，而不写 `.progress.json`：`extract_mix`、`separate_audio`、`transcribe_audio`、`prepare_background`、父图的切片派发/整批合并，以及子图的采帧、音频切片、三路观察和单片合并均在返回后提交状态。父图保存音轨路径、ASR 结果、已完成批次索引和非空 Observation；空观察切片同样由 `merge_slice_batch` 推进索引。
- 外部中断后以同一 `execution_id` 调用 `graph.invoke(None, config)` 恢复；不重复已 checkpoint 的分离、ASR 或切片。所有切片完成后才由 `persist_evidence` 写正式 `data/evidence/<剧名>/<集名>.json`；音频分离产物保留。
- 失败运行不写入或覆盖正式 Evidence；已有旧 Evidence 不作为缓存读取，也不因本次失败被删除。帧、切片音频和 `mix.flac` 仍位于单集临时目录，成功或失败后清理。

## 4. 实施阶段

1. 配置与依赖  
   增加十五个必填能力字段、更新 `.env.example`、删除 `min_reported_gap_ms`，声明三个 SDK/客户端直接依赖。  
   → 验证：配置能从显式覆盖、环境变量和 `.env` 读取；缺失任一必填值时给出明确错误。

2. 确定性媒体层  
   实现主视频轨探测、整集音频提取、三秒 span、4 FPS 中点计算、帧提取和背景音硬切。  
   → 验证：3000/3001/3125/3250/3251ms 边界均得到预期 span、帧数和采样点；实际帧数不符时失败而不补帧。

3. 托管提取与 Evidence 汇聚  
   接入 CI、Qwen ASR 和其余 Qwen SDK 调用，完成 ASR 映射、同片三路并发和 Observation 合并。  
   → 验证：分离与 ASR 每集各调用一次；OCR/VLM/音频每片各调用一次；OCR 与 VLM 收到完全相同的帧内容和顺序。

4. 工作流与 CLI  
   替换旧媒体时长和 adapter 节点；单文件仅接受 `.mp4`，目录递归发现 `.mp4`，按相对路径进行数字感知自然排序。  
   → 验证：`第2集` 先于 `第10集`；一集失败后下一集仍运行；生产图中无 V1 adapter 调用。

5. Renderer 与提示词  
   切换 raw-ms 格式和 `covered_empty`，更新 Specialist 对状态行的解释。  
   → 验证：不存在 `HH:MM:SS.mmm`、`[未覆盖]` 或可引用的空状态 ID。

6. 真实验证与收尾  
   先验证单个真实切片的三项 Qwen 请求大小和结果，再验证四片并发的图级行为，最后运行一集完整视频和一个含损坏视频的两集目录。当前单集若需从旧串行进程转入新图，只做一次性 checkpoint 续接：保留同一 `execution_id` 的已完成 ASR、音轨和 Observation，将 `next_slice_index` 接到新图批次入口，不加入持久化兼容层或新执行任务。  
   → 验证：完整集产生 Evidence 并进入 Specialist；损坏集记录失败，后续集成功；测试和静态检查全部通过。

## 5. 测试清单

默认单元测试不访问真实 API：

- ffprobe 只读取主视频轨且拒绝无时长视频。
- 固定切片、尾片和所有中点采样边界。
- OCR/VLM 同帧、同顺序、各一次调用。
- 单片子图的三路观察确实并发；父图每批最多四个切片子图并发，整批合并仍按切片序号稳定排序。
- Qwen ASR 句段毫秒时间戳直接映射、说话人为空、零句段失败。
- 中断后从 PostgreSQL checkpoint 恢复时不重复已保存的分离产物、ASR 或切片；空观察切片也不会被重复调用。
- 任一路非空生成一个 O；三路全空不生成 O。
- 重试类别、次数及不可重试错误。
- 任一必需阶段失败时不落 Evidence。
- raw-ms 渲染、相邻空切片合并、T/D 不消除空状态。
- CLI 递归发现、自然排序和失败后继续。
- 伪 `.mp4` 的图级 smoke test；V1 fixture 只保留在 adapter 专属测试中。

真实验证不加入默认 `pytest`：

- 带时间码的合成视频：实际选帧与目标时刻偏差不超过一个源视频帧间隔。
- 12 张真实分辨率图片能够一次提交；记录请求体大小和视觉 token。
- 一集真实视频端到端生成合法 Evidence。
- 运行 `pytest` 与 `ruff check` 全部通过。

## 6. 假设与交接约束

- Qwen ASR 不增加语言配置，直接使用模型的多语言识别能力。
- 4 FPS 是待 benchmark 验证的工程默认，不宣称充分。
- 人声分离必须使用官方 COS/CI SDK；其余模型能力使用各自官方 SDK 或 OpenAI SDK，不能手写供应商请求头。
- `WorkflowState`、`EvidenceDocument` 和五类 Specialist 公共接口不新增字段。
- 实施时保留工作区现有用户修改，只改与本计划直接相关的行。
- README、PRD、ADR 已描述目标形态，不做无关重写；本计划在实现完成并通过验收后将状态更新为 `done`。
