import unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipline.common.runtime import (
    build_interactions_document,
    parse_deferred_vote_candidates_document,
    parse_emotion_button_candidates_document,
    parse_instant_vote_candidates_document,
    parse_interactions_document,
    parse_repeat_keyline_candidates_document,
    parse_side_comment_candidates_document,
)
from pipline.common.schemas import FinalHighlightItem, Segment


class InteractionRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.highpoints = [
            FinalHighlightItem(
                id=1,
                summary="女子强势回击对方，现场气氛陡然反转。",
                level=3,
                reason="反击打脸非常明确，爽点强。",
                segment_ids=[7, 8],
                trigger_segment_id=8,
                start="00:01:20.100",
                end="00:01:25.000",
                trigger_time="00:01:23.500",
                evidence_segments=[
                    Segment(
                        id=7,
                        start="00:01:20.100",
                        end="00:01:23.400",
                        text="你刚才不是很会说吗？",
                        speech="单人发言",
                        emotion="压制",
                        voice="语气强硬",
                        music="紧张",
                        audio_cues=[],
                        uncertainty="",
                    ),
                    Segment(
                        id=8,
                        start="00:01:23.500",
                        end="00:01:25.000",
                        text="现在轮到我了。",
                        speech="单人发言",
                        emotion="强势",
                        voice="气场拉满",
                        music="推进",
                        audio_cues=[],
                        uncertainty="",
                    ),
                ],
            ),
            FinalHighlightItem(
                id=2,
                summary="现场突发危险，众人惊呼提醒。",
                level=3,
                reason="危险点明确，保护冲动强。",
                segment_ids=[13],
                trigger_segment_id=13,
                start="00:02:08.400",
                end="00:02:13.200",
                trigger_time="00:02:08.400",
                evidence_segments=[
                    Segment(
                        id=13,
                        start="00:02:08.400",
                        end="00:02:13.200",
                        text="小心！",
                        speech="多人轮流发言",
                        emotion="惊慌",
                        voice="急促尖锐",
                        music="危机音效",
                        audio_cues=["爆炸声"],
                        uncertainty="",
                    )
                ],
            ),
            FinalHighlightItem(
                id=3,
                summary="对方翻出证据，证实她刚才没有虚张声势。",
                level=3,
                reason="前面留下的真假悬念在这里被明确揭晓。",
                segment_ids=[18, 19],
                trigger_segment_id=19,
                start="00:02:18.000",
                end="00:02:22.000",
                trigger_time="00:02:20.000",
                evidence_segments=[
                    Segment(
                        id=18,
                        start="00:02:18.000",
                        end="00:02:19.900",
                        text="你以为我是在吓唬你？",
                        speech="单人发言",
                        emotion="压迫",
                        voice="冷静施压",
                        music="推进",
                        audio_cues=[],
                        uncertainty="",
                    ),
                    Segment(
                        id=19,
                        start="00:02:20.000",
                        end="00:02:22.000",
                        text="证据就在这里，你自己看。",
                        speech="单人发言",
                        emotion="笃定",
                        voice="落锤",
                        music="反转强调",
                        audio_cues=[],
                        uncertainty="",
                    ),
                ],
            ),
        ]

    def test_parse_emotion_button_candidates_document_builds_prepared_items(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "button_type": "cool",
                "text": "终于反击",
                "danmaku": ["这波舒服", "气场拉满", "就该这样", "真的爽到"]
              }
            },
            {
              "highpoint_id": 2,
              "payload": {
                "button_type": "protect"
              }
            }
          ]
        }
        """

        parsed = parse_emotion_button_candidates_document(raw, self.highpoints)

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].show_at, 83500)
        self.assertEqual(parsed[0].duration_ms, 2200)
        self.assertEqual(parsed[0].payload.button_id, 0)
        self.assertEqual(parsed[1].show_at, 128400)
        self.assertEqual(parsed[1].duration_ms, 5000)
        self.assertEqual(parsed[1].payload.button_id, 3)
        self.assertIsNone(parsed[1].payload.text)
        self.assertIsNone(parsed[1].payload.danmaku)

    def test_parse_emotion_button_candidates_document_rejects_unknown_highpoint(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 99,
              "payload": {
                "button_type": "protect"
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "highpoint_id=99"):
            parse_emotion_button_candidates_document(raw, self.highpoints)

    def test_parse_emotion_button_candidates_document_rejects_invalid_payload_combo(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 2,
              "payload": {
                "button_type": "protect",
                "danmaku": ["快点护住她", "现在先别动", "千万别受伤", "快去救她啊"]
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "payload.danmaku 不允许出现"):
            parse_emotion_button_candidates_document(raw, self.highpoints)

    def test_parse_emotion_button_candidates_document_rejects_short_text(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "button_type": "cool",
                "text": "爽",
                "danmaku": ["这波舒服", "气场拉满", "就该这样", "真的爽到"]
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "payload.text 需包含 2 到 8 个字符（含标点符号）"):
            parse_emotion_button_candidates_document(raw, self.highpoints)

    def test_parse_emotion_button_candidates_document_counts_punctuation_in_text_length(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "button_type": "cool",
                "text": "爽！！！！！",
                "danmaku": ["这波舒服", "气场拉满", "就该这样", "真的爽到"]
              }
            }
          ]
        }
        """

        parsed = parse_emotion_button_candidates_document(raw, self.highpoints)
        self.assertEqual(parsed[0].payload.text, "爽！！！！！")

    def test_parse_emotion_button_candidates_document_rejects_invalid_danmaku_count(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "button_type": "cool",
                "text": "终于反击",
                "danmaku": ["这波舒服", "气场拉满", "就该这样"]
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "payload.danmaku 条数需为 4 到 6 条"):
            parse_emotion_button_candidates_document(raw, self.highpoints)

    def test_parse_emotion_button_candidates_document_rejects_forbidden_term(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "button_type": "cool",
                "text": "男主赢了",
                "danmaku": ["这波舒服", "气场拉满", "就该这样", "真的爽到"]
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "payload.text 不允许包含禁用词"):
            parse_emotion_button_candidates_document(raw, self.highpoints)

    def test_build_interactions_document_matches_final_schema(self) -> None:
        prepared_items = parse_emotion_button_candidates_document(
            """
            {
              "interactions": [
                {
                  "highpoint_id": 1,
                  "payload": {
                    "button_type": "cool",
                    "text": "终于反击",
                    "danmaku": ["这波舒服", "气场拉满", "就该这样", "真的爽到"]
                  }
                }
              ]
            }
            """,
            self.highpoints,
        )

        document = build_interactions_document(prepared_items)
        payload = document.model_dump(mode="json", exclude_none=True)

        self.assertEqual(payload[0]["id"], 1)
        self.assertEqual(payload[0]["type"], 1)
        self.assertEqual(payload[0]["show_at"], 83500)
        self.assertEqual(payload[0]["duration_ms"], 2200)
        self.assertEqual(payload[0]["payload"]["button_id"], 0)

    def test_parse_repeat_keyline_candidates_document_builds_prepared_items(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "text": "现在，轮到我了。"
              }
            }
          ]
        }
        """

        parsed = parse_repeat_keyline_candidates_document(raw, self.highpoints)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].type, 2)
        self.assertEqual(parsed[0].show_at, 83500)
        self.assertEqual(parsed[0].duration_ms, 2200)
        self.assertEqual(parsed[0].payload.text, "现在，轮到我了。")

    def test_parse_repeat_keyline_candidates_document_rejects_unknown_highpoint(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 99,
              "payload": {
                "text": "现在轮到我了"
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "highpoint_id=99"):
            parse_repeat_keyline_candidates_document(raw, self.highpoints)

    def test_parse_repeat_keyline_candidates_document_rejects_text_not_in_evidence(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "text": "现在该我反击了"
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "payload.text 在对应 evidence_segments 中不存在"):
            parse_repeat_keyline_candidates_document(raw, self.highpoints)

    def test_build_interactions_document_supports_repeat_keyline(self) -> None:
        prepared_items = parse_repeat_keyline_candidates_document(
            """
            {
              "interactions": [
                {
                  "highpoint_id": 1,
                  "payload": {
                    "text": "现在，轮到我了。"
                  }
                }
              ]
            }
            """,
            self.highpoints,
        )

        document = build_interactions_document(prepared_items)
        payload = document.model_dump(mode="json", exclude_none=True)

        self.assertEqual(payload[0]["id"], 1)
        self.assertEqual(payload[0]["type"], 2)
        self.assertEqual(payload[0]["show_at"], 83500)
        self.assertEqual(payload[0]["duration_ms"], 2200)
        self.assertEqual(payload[0]["payload"]["text"], "现在，轮到我了。")

    def test_duration_ms_uses_trigger_segment_end_instead_of_highpoint_end(self) -> None:
        highpoints = [
            FinalHighlightItem(
                id=1,
                summary="角色先放狠话，后面还有承接台词。",
                level=3,
                reason="触发点在前一个 segment，但高光仍延续到了后一个 segment。",
                segment_ids=[21, 22],
                trigger_segment_id=21,
                start="00:03:00.000",
                end="00:03:08.000",
                trigger_time="00:03:00.000",
                evidence_segments=[
                    Segment(
                        id=21,
                        start="00:03:00.000",
                        end="00:03:02.500",
                        text="今天谁也别想走！",
                        speech="单人发言",
                        emotion="强势",
                        voice="高压",
                        music="推进",
                        audio_cues=[],
                        uncertainty="",
                    ),
                    Segment(
                        id=22,
                        start="00:03:02.500",
                        end="00:03:08.000",
                        text="你们一个都跑不掉。",
                        speech="单人发言",
                        emotion="压迫",
                        voice="持续施压",
                        music="推进",
                        audio_cues=[],
                        uncertainty="",
                    ),
                ],
            )
        ]

        emotion_items = parse_emotion_button_candidates_document(
            """
            {
              "interactions": [
                {
                  "highpoint_id": 1,
                  "payload": {
                    "button_type": "cool",
                    "text": "统统别走",
                    "danmaku": ["压迫感拉满", "气场太强了", "这波真霸气", "根本跑不掉"]
                  }
                }
              ]
            }
            """,
            highpoints,
        )
        repeat_items = parse_repeat_keyline_candidates_document(
            """
            {
              "interactions": [
                {
                  "highpoint_id": 1,
                  "payload": {
                    "text": "今天谁也别想走！"
                  }
                }
              ]
            }
            """,
            highpoints,
        )

        self.assertEqual(emotion_items[0].show_at, 180000)
        self.assertEqual(emotion_items[0].duration_ms, 3200)
        self.assertEqual(repeat_items[0].show_at, 180000)
        self.assertEqual(repeat_items[0].duration_ms, 3200)

    def test_parse_instant_vote_candidates_document_builds_prepared_items(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "question": "该怼回去吗？",
                "options": ["该", "不该"]
              }
            }
          ]
        }
        """

        parsed = parse_instant_vote_candidates_document(raw, self.highpoints)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].type, 3)
        self.assertEqual(parsed[0].show_at, 83500)
        self.assertEqual(parsed[0].duration_ms, 2200)
        self.assertEqual(parsed[0].payload.question, "该怼回去吗？")
        self.assertEqual(parsed[0].payload.options, ["该", "不该"])

    def test_parse_instant_vote_candidates_document_rejects_unknown_highpoint(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 99,
              "payload": {
                "question": "该怼回去吗？",
                "options": ["该", "不该"]
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "highpoint_id=99"):
            parse_instant_vote_candidates_document(raw, self.highpoints)

    def test_parse_instant_vote_candidates_document_rejects_invalid_options_count(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "question": "该怼回去吗？",
                "options": ["该", "不该", "看情况"]
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "payload.options 必须恰好包含 2 个元素"):
            parse_instant_vote_candidates_document(raw, self.highpoints)

    def test_build_interactions_document_supports_instant_vote(self) -> None:
        prepared_items = parse_instant_vote_candidates_document(
            """
            {
              "interactions": [
                {
                  "highpoint_id": 1,
                  "payload": {
                    "question": "该怼回去吗？",
                    "options": ["该", "不该"]
                  }
                }
              ]
            }
            """,
            self.highpoints,
        )

        document = build_interactions_document(prepared_items)
        payload = document.model_dump(mode="json", exclude_none=True)

        self.assertEqual(payload[0]["id"], 1)
        self.assertEqual(payload[0]["type"], 3)
        self.assertEqual(payload[0]["show_at"], 83500)
        self.assertEqual(payload[0]["duration_ms"], 2200)
        self.assertEqual(payload[0]["payload"]["question"], "该怼回去吗？")
        self.assertEqual(payload[0]["payload"]["options"], ["该", "不该"])

    def test_parse_deferred_vote_candidates_document_builds_prepared_items(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "question": "她在虚张声势吗？",
                "options": ["是", "不是"],
                "reveal_id": 3
              }
            }
          ]
        }
        """

        with patch("pipline.common.runtime.random.shuffle", side_effect=lambda items: items.reverse()):
            parsed = parse_deferred_vote_candidates_document(raw, self.highpoints)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].type, 4)
        self.assertEqual(parsed[0].show_at, 83500)
        self.assertEqual(parsed[0].duration_ms, 2200)
        self.assertEqual(parsed[0].payload.question, "她在虚张声势吗？")
        self.assertEqual(parsed[0].payload.options, ["不是", "是"])
        self.assertEqual(parsed[0].payload.reveal_time, 140000)
        self.assertEqual(parsed[0].payload.reveal_delay, 2700)
        self.assertEqual(parsed[0].payload.answer_id, 1)

    def test_parse_deferred_vote_candidates_document_rejects_unknown_reveal_id(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "question": "她在虚张声势吗？",
                "options": ["是", "不是"],
                "reveal_id": 99
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "reveal_id=99"):
            parse_deferred_vote_candidates_document(raw, self.highpoints)

    def test_parse_deferred_vote_candidates_document_rejects_non_future_reveal_id(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 3,
              "payload": {
                "question": "她在虚张声势吗？",
                "options": ["是", "不是"],
                "reveal_id": 1
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "必须晚于 highpoint_id=3"):
            parse_deferred_vote_candidates_document(raw, self.highpoints)

    def test_parse_deferred_vote_candidates_document_rejects_invalid_options_count(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "question": "她在虚张声势吗？",
                "options": ["是"],
                "reveal_id": 3
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "payload.options 必须是 2 到 4 个元素的字符串数组"):
            parse_deferred_vote_candidates_document(raw, self.highpoints)

    def test_parse_deferred_vote_candidates_document_randomizes_options_and_sets_answer_id(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "question": "她在虚张声势吗？",
                "options": ["是", "不是", "一半一半"],
                "reveal_id": 3
              }
            }
          ]
        }
        """

        with patch("pipline.common.runtime.random.shuffle", side_effect=lambda items: items.reverse()):
            parsed = parse_deferred_vote_candidates_document(raw, self.highpoints)

        self.assertEqual(parsed[0].payload.options, ["一半一半", "不是", "是"])
        self.assertEqual(parsed[0].payload.answer_id, 2)

    def test_build_interactions_document_supports_deferred_vote(self) -> None:
        with patch("pipline.common.runtime.random.shuffle", side_effect=lambda items: items.reverse()):
            prepared_items = parse_deferred_vote_candidates_document(
                """
                {
                  "interactions": [
                    {
                      "highpoint_id": 1,
                      "payload": {
                        "question": "她在虚张声势吗？",
                        "options": ["是", "不是"],
                        "reveal_id": 3
                      }
                    }
                  ]
                }
                """,
                self.highpoints,
            )

        document = build_interactions_document(prepared_items)
        payload = document.model_dump(mode="json", exclude_none=True)

        self.assertEqual(payload[0]["id"], 1)
        self.assertEqual(payload[0]["type"], 4)
        self.assertEqual(payload[0]["show_at"], 83500)
        self.assertEqual(payload[0]["duration_ms"], 2200)
        self.assertEqual(payload[0]["payload"]["reveal_time"], 140000)
        self.assertEqual(payload[0]["payload"]["reveal_delay"], 2700)
        self.assertEqual(payload[0]["payload"]["options"], ["不是", "是"])
        self.assertEqual(payload[0]["payload"]["answer_id"], 1)

    def test_parse_side_comment_candidates_document_builds_prepared_items(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 1,
              "payload": {
                "text": "这话真够硬啊"
              }
            }
          ]
        }
        """

        parsed = parse_side_comment_candidates_document(raw, self.highpoints)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].type, 5)
        self.assertEqual(parsed[0].show_at, 83500)
        self.assertEqual(parsed[0].duration_ms, 2200)
        self.assertEqual(parsed[0].payload.text, "这话真够硬啊")

    def test_parse_side_comment_candidates_document_rejects_unknown_highpoint(self) -> None:
        raw = """
        {
          "interactions": [
            {
              "highpoint_id": 99,
              "payload": {
                "text": "这话真够硬啊"
              }
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "highpoint_id=99"):
            parse_side_comment_candidates_document(raw, self.highpoints)

    def test_build_interactions_document_supports_side_comment(self) -> None:
        prepared_items = parse_side_comment_candidates_document(
            """
            {
              "interactions": [
                {
                  "highpoint_id": 1,
                  "payload": {
                    "text": "这话真够硬啊"
                  }
                }
              ]
            }
            """,
            self.highpoints,
        )

        document = build_interactions_document(prepared_items)
        payload = document.model_dump(mode="json", exclude_none=True)

        self.assertEqual(payload[0]["id"], 1)
        self.assertEqual(payload[0]["type"], 5)
        self.assertEqual(payload[0]["show_at"], 83500)
        self.assertEqual(payload[0]["duration_ms"], 2200)
        self.assertEqual(payload[0]["payload"]["text"], "这话真够硬啊")

    def test_build_interactions_document_sorts_by_show_at_then_duration_and_assigns_ids(self) -> None:
        prepared_items = (
            parse_side_comment_candidates_document(
                """
                {
                  "interactions": [
                    {
                      "highpoint_id": 2,
                      "payload": {
                        "text": "先到的更长"
                      }
                    }
                  ]
                }
                """,
                self.highpoints,
            )
            + parse_emotion_button_candidates_document(
                """
                {
                  "interactions": [
                    {
                      "highpoint_id": 1,
                      "payload": {
                        "button_type": "cool",
                        "text": "终于反击",
                        "danmaku": ["这波舒服", "气场拉满", "就该这样", "真的爽到"]
                      }
                    }
                  ]
                }
                """,
                self.highpoints,
            )
            + parse_repeat_keyline_candidates_document(
                """
                {
                  "interactions": [
                    {
                      "highpoint_id": 2,
                      "payload": {
                        "text": "小心！"
                      }
                    }
                  ]
                }
                """,
                self.highpoints,
            )
        )

        document = build_interactions_document(prepared_items)
        payload = document.model_dump(mode="json", exclude_none=True)

        self.assertEqual(
            [(item["id"], item["show_at"], item["duration_ms"]) for item in payload],
            [(1, 83500, 2200), (2, 128400, 3000), (3, 128400, 5000)],
        )

    def test_parse_interactions_document_rejects_extra_field(self) -> None:
        raw = """
        [
          {
            "id": 1,
            "type": 1,
            "show_at": 128400,
            "duration_ms": 5000,
            "payload": {
              "button_id": 3
            },
            "extra": true
          }
        ]
        """

        with self.assertRaisesRegex(ValueError, "interactions.json 校验失败"):
            parse_interactions_document(raw)

    def test_parse_interactions_document_accepts_repeat_keyline_item(self) -> None:
        raw = """
        [
          {
            "id": 1,
            "type": 2,
            "show_at": 83500,
            "duration_ms": 5000,
            "payload": {
              "text": "现在，轮到我了。"
            }
          }
        ]
        """

        document = parse_interactions_document(raw)
        payload = document.model_dump(mode="json", exclude_none=True)

        self.assertEqual(payload[0]["type"], 2)
        self.assertEqual(payload[0]["payload"]["text"], "现在，轮到我了。")

    def test_parse_interactions_document_accepts_instant_vote_item(self) -> None:
        raw = """
        [
          {
            "id": 1,
            "type": 3,
            "show_at": 83500,
            "duration_ms": 2200,
            "payload": {
              "question": "该怼回去吗？",
              "options": ["该", "不该"]
            }
          }
        ]
        """

        document = parse_interactions_document(raw)
        payload = document.model_dump(mode="json", exclude_none=True)

        self.assertEqual(payload[0]["type"], 3)
        self.assertEqual(payload[0]["payload"]["question"], "该怼回去吗？")
        self.assertEqual(payload[0]["payload"]["options"], ["该", "不该"])

    def test_parse_interactions_document_accepts_deferred_vote_item(self) -> None:
        raw = """
        [
          {
            "id": 1,
            "type": 4,
            "show_at": 83500,
            "duration_ms": 2200,
            "payload": {
              "question": "她在虚张声势吗？",
              "options": ["是", "不是"],
              "reveal_time": 140000,
              "reveal_delay": 2700,
              "answer_id": 1
            }
          }
        ]
        """

        document = parse_interactions_document(raw)
        payload = document.model_dump(mode="json", exclude_none=True)

        self.assertEqual(payload[0]["type"], 4)
        self.assertEqual(payload[0]["payload"]["question"], "她在虚张声势吗？")
        self.assertEqual(payload[0]["payload"]["reveal_time"], 140000)
        self.assertEqual(payload[0]["payload"]["reveal_delay"], 2700)
        self.assertEqual(payload[0]["payload"]["answer_id"], 1)

    def test_parse_interactions_document_accepts_side_comment_item(self) -> None:
        raw = """
        [
          {
            "id": 1,
            "type": 5,
            "show_at": 83500,
            "duration_ms": 2200,
            "payload": {
              "text": "这话真够硬啊"
            }
          }
        ]
        """

        document = parse_interactions_document(raw)
        payload = document.model_dump(mode="json", exclude_none=True)

        self.assertEqual(payload[0]["type"], 5)
        self.assertEqual(payload[0]["payload"]["text"], "这话真够硬啊")


if __name__ == "__main__":
    unittest.main()
