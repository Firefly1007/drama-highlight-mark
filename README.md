# Drama Highlight Mark V2

短剧即时互动点标注/生成引擎（V2）。它以单集原始视频和必要上下文为输入，生成供后端消费的互动配置 JSON。

> 开发中：本文描述目标形态；如需维护进度快照，见 [PROGRESS 使用指南](docs/PROGRESS.md)。

## 项目边界

- 处理单位是一集短剧，产物是该集的一组即时互动配置。
- V2 从原始视频提取整集台词、屏幕文字、客观画面和非台词音频观察，组成共享的基线证据。
- V2 直接从本集内容中发现互动机会，不再以 V1 的“高光”作为必经入口。
- V2 只负责离线生成和标注，不包含前端播放器、业务服务、业务数据库、用户评论区或剧情分支内容生成；运行检查点属于工作流基础设施。
- 输出互动类型固定为五种：
  `emotion_button`、`repeat_keyline`、`instant_vote`、`deferred_vote`、`side_comment`。
- `episode_comment`、`scene_bookmark` 和 `heatmap_bar` 不属于 V2 工作流。

## 五类互动

| 类型 | 用户看到的互动 | 适用内容 |
| --- | --- | --- |
| `emotion_button` | 点击情绪按钮或预设短句 | 爽点、笑点、打脸、危险、甜宠等即时情绪场景 |
| `repeat_keyline` | 复述或接住一句关键台词 | 名台词、放话、反转前后 |
| `instant_vote` | 即时二选一投票 | 真实分歧、站队、真假判断 |
| `deferred_vote` | 先投票、后随剧情揭晓结果 | 身份悬念、预测、真假判断 |
| `side_comment` | 一句短吐槽、短评或提醒 | 有明显情绪或讨论价值的剧情节点 |

完整的产品规则与验收标准见 [产品需求文档（PRD）](docs/drama-interaction-v2-PRD.md)。

## 目标流程

```text
单集原始 .mp4
        ↓
媒体探测、音轨分离与固定 3 秒切片
        ↓
ASR 台词 + OCR 屏幕文字 + VLM 画面观察 + 背景音观察
        ↓
EvidenceDocument 与必要上下文
        ↓
五类互动专家
        ↓
局部校验与定向修复
        ↓
候选池
        ↓
全局调度与最终渲染
        ↓
后端消费的互动 JSON
```

必要上下文来自 `data/video/drama_info.json` 中按剧名匹配的剧情简介和角色表；它只辅助理解名称与关系，互动事实仍必须引用本集证据。

该流程的技术取舍、证据锚定和调度原则见 [架构决策记录（ADR）](docs/drama-interaction-v2-ADR.md)。最终 JSON 字段以 [输出契约](docs/schema.md) 为准。

## 目标使用方式

完成后的命令行入口如下；`run` 处理单集或目录，`resume` 恢复待人工处理的执行，`export` 只导出已持久化结果：

```bash
pip install -e .

python -m drama_interaction run data/video/某短剧/第1集.mp4
python -m drama_interaction run data/video/某短剧
python -m drama_interaction run data/video
python -m drama_interaction resume --execution-id <execution-id>
python -m drama_interaction export --execution-id <execution-id>
```

`run` 的最终产物是符合 `docs/schema.md` 的 JSON。目录输入递归发现 `.mp4`，按相对路径自然排序后逐集处理；单集失败不中断整个批次。V1 片段 JSON 只作为回归 fixture，不进入生产链路。提示词、配置和更细的执行细节以代码和提交记录为准，不在 README 重复定义。

## 文档地图

| 文档 | 回答的问题 |
| --- | --- |
| [产品需求文档（PRD）](docs/drama-interaction-v2-PRD.md) | 要生成什么互动、什么算合格、哪些不做？ |
| [架构决策记录（ADR）](docs/drama-interaction-v2-ADR.md) | 为什么采用当前证据、生成、校验和调度方案？ |
| [输出契约](docs/schema.md) | 后端收到的 JSON 长什么样？ |
| [PROGRESS 使用指南](docs/PROGRESS.md) | 现在要怎么维护进度快照？ |

推荐阅读顺序：README → PRD / ADR → 输出契约 → PROGRESS 使用指南。

V1 的比赛版本保留在 [v1/](v1/README.md)，用于对照与历史参考。
