最终输出是数组，数组中的每个元素都符合下面这个公用 schema：

```json
[
  {
    "id": 1,
    "type": 1,
    "show_at": 0,
    "duration_ms": 5000,
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

5. `side_comment`：

    ```json
    {
      "text": "这也太敢说了吧！",
      "mood": "mood"(未来加入)
    }
    ```
