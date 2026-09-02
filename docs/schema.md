最终输出是数组，数组中的每个元素都符合下面这个公用 模式(schema)（`duration_ms` 按 V2 时长表取值——类型常数 + 跟读金句(repeat_keyline)内容自适应，见 ADR-023；示例值仅为格式示意）：

```json
[
  {
    "id": 1,
    "type": 1,
    "show_at": 0,
    "duration_ms": 2800,
    "payload": {}
  }
]
```

`payload`字段：

1. `emotion_button`:

    ```json
    {
      "button_id":1,
      "text":"恶有恶报",(可选字段)
      "danmaku":["弹幕1","弹幕2",...](可选字段)
    }
    ```

    `button_id`可选：
    
    |   id | name   | en_name | text | danmaku | 适用场景                   |
    | ---- | ------ | ------- | ---- | ------- | -------------------------- |
    |    0 | 爽     | cool    | 有   | 有      | 打脸、强势宣言、反击、逆袭 |
    |    1 | 笑     | laugh   | 无   | 有      | 搞笑、反差、离谱台词       |
    |    2 | 丢番茄 | tomato  | 有   | 有      | 恶人、渣男、欠揍、离谱操作 |
    |    3 | 护住TA | protect | 无   | 无      | 危险、受伤、救人、惊险场面 |
    |    4 | 心疼TA | pity    | 无   | 无      | 虐点、委屈、哭戏、被误解   |
    |    5 | 磕到了 | ship    | 无   | 有      | 甜宠、暧昧、撒糖、CP互动   |

2. `repeat_keyline`:

    ```json
    {
      "text": "因为我在哪，纪家就在哪"
    }

3. `instant_vote`:

    ```json
    {
      "question": "你站谁？",
      "options": ["站她","站他"](必须是2个元素)
    }
    ```

4. `deferred_vote`:

    ```json
    {
      "question": "她说的是真的吗？",
      "options": ["是真的", "有问题"](2-4个元素),
      "reveal_time": 1000,
      "reveal_delay":5000,
      "answer_id": 0
    }

    注：`answer_id` 指向 `options` 中正确项的索引（ 生成专家(Specialist)生成时指向原 options[0]，渲染打乱后由渲染环节重映射为新索引）。`reveal_time` / `reveal_delay` 为渲染环节的程序产物——生成侧（生成专家(Specialist) / 候选(Candidate)）中必须为 null，不输出毫秒（ADR-011 / ADR-023）。

5. `side_comment`：

    ```json
    {
      "text": "这也太敢说了吧！",
      "mood": "mood"(未来加入)
    }
    ```
