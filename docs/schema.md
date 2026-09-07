# V2 最终互动 JSON 契约

本文是 V2 交给后端的最终输出契约。它只定义可消费的互动 JSON，不定义生成过程、中间状态或内部数据结构。

V2 的 `type` 使用字符串；接入方应按本文契约解析。

## 输出外壳

最终输出是一个 JSON 数组。数组中的对象只允许下列公共字段，且按 `show_at` 升序排列；`id` 是数组内从 1 开始的唯一序号。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `id` | integer | 是 | 大于等于 1，数组内唯一。 |
| `type` | string | 是 | 只能是 `emotion_button`、`repeat_keyline`、`instant_vote`、`deferred_vote`、`side_comment` 之一。 |
| `show_at` | integer | 是 | 展示开始时间，单位毫秒，大于等于 0。 |
| `duration_ms` | integer | 是 | 展示时长，单位毫秒，大于 0。 |
| `payload` | object | 是 | 与 `type` 严格对应的载荷，见下文。 |

所有对象均为严格对象：未在对应表中声明的字段不可出现。所有文本字段不得为空或仅含空白字符；可选字段不需要时应省略，不使用 `null` 占位。

## 类型与载荷

### `emotion_button`

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `button_id` | string | 是 | 只能是 `cool`、`laugh`、`tomato`、`protect`、`pity`、`ship`。 |
| `text` | string | 否 | 仅 `button_id` 为 `cool` 或 `tomato` 时允许出现。 |
| `danmaku` | array of string | 否 | 非空数组；仅 `button_id` 为 `cool`、`laugh`、`tomato` 或 `ship` 时允许出现。 |

`button_id` 直接使用英文业务名称：`cool`（爽）、`laugh`（笑）、`tomato`（丢番茄）、`protect`（护住 TA）、`pity`（心疼 TA）、`ship`（磕到了）。V2 不接受数字按钮编号。

### `repeat_keyline`

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `text` | string | 是 | 用户要复述的关键台词。 |

### `instant_vote`

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `question` | string | 是 | 投票题干。 |
| `options` | array of string | 是 | 恰好两个非空且互不重复的选项。 |

### `deferred_vote`

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `question` | string | 是 | 竞猜或预测题干。 |
| `options` | array of string | 是 | 两至四个非空且互不重复的选项。 |
| `answer_id` | integer | 是 | 正确选项在最终 `options` 数组中的从 0 开始索引。 |
| `reveal_time` | integer | 是 | 揭晓开始时间，单位毫秒，且不得早于该互动展示结束。 |
| `reveal_delay` | integer | 是 | 揭晓展示时长，单位毫秒，大于 0。 |

`answer_id` 必须落在 `options` 的有效索引范围内。最终 JSON 中的选项顺序与 `answer_id` 必须一致。

### `side_comment`

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `text` | string | 是 | 展示的短吐槽、短评或提醒。 |
| `mood` | string | 是 | 必须是全小写的 `roast`、`shock`、`laugh`、`praise`、`sympathy`、`doubt` 之一。 |

## 完整示例

```json
[
  {
    "id": 1,
    "type": "emotion_button",
    "show_at": 12000,
    "duration_ms": 2800,
    "payload": {
      "button_id": "cool",
      "text": "太解气了",
      "danmaku": [
        "爽到了"
      ]
    }
  },
  {
    "id": 2,
    "type": "repeat_keyline",
    "show_at": 26300,
    "duration_ms": 3400,
    "payload": {
      "text": "因为我在哪，纪家就在哪。"
    }
  },
  {
    "id": 3,
    "type": "instant_vote",
    "show_at": 38900,
    "duration_ms": 3600,
    "payload": {
      "question": "你站谁？",
      "options": [
        "站她",
        "站他"
      ]
    }
  },
  {
    "id": 4,
    "type": "deferred_vote",
    "show_at": 50800,
    "duration_ms": 3600,
    "payload": {
      "question": "她说的是真的吗？",
      "options": [
        "是真的",
        "有问题"
      ],
      "answer_id": 1,
      "reveal_time": 67000,
      "reveal_delay": 3000
    }
  },
  {
    "id": 5,
    "type": "side_comment",
    "show_at": 82400,
    "duration_ms": 2600,
    "payload": {
      "text": "这也太敢说了吧！",
      "mood": "shock"
    }
  }
]
```

接入方应先按 `type` 选择对应的 `payload` 规则，再渲染互动；不得根据数字类型、缺省 `mood` 或未声明字段推断行为。
