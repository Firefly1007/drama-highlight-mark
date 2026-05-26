import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipline.common.runtime import parse_highlights_document, parse_highlights_list
from pipline.common.schemas import Segment


class HighlightRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.segments = [
            Segment(
                id=1,
                start="00:00:01.000",
                end="00:00:02.000",
                text="第一句",
                speech="normal",
                emotion="calm",
                voice="female",
                music="none",
                audio_cues=[],
                uncertainty="",
            ),
            Segment(
                id=2,
                start="00:00:03.000",
                end="00:00:05.000",
                text="第二句",
                speech="fast",
                emotion="tense",
                voice="male",
                music="rise",
                audio_cues=["bang"],
                uncertainty="",
            ),
            Segment(
                id=3,
                start="00:00:06.000",
                end="00:00:08.000",
                text="第三句",
                speech="shout",
                emotion="angry",
                voice="male",
                music="hit",
                audio_cues=["shock"],
                uncertainty="",
            ),
        ]

    def test_parse_highlights_document_builds_final_items(self) -> None:
        raw = """
        {
          "highlights": [
            {
              "id": 1,
              "summary": "两句对话形成冲突",
              "level": 2,
              "reason": "态度对撞明显",
              "segment_ids": [2, 3],
              "trigger_segment_id": 2
            }
          ]
        }
        """

        parsed = parse_highlights_document(raw, self.segments)

        self.assertEqual(len(parsed), 1)
        item = parsed[0]
        self.assertEqual(item.id, 1)
        self.assertEqual(item.start, "00:00:03.000")
        self.assertEqual(item.end, "00:00:08.000")
        self.assertEqual(item.trigger_time, "00:00:03.000")
        self.assertEqual(item.segment_ids, [2, 3])
        self.assertEqual(item.trigger_segment_id, 2)
        self.assertEqual([segment.id for segment in item.evidence_segments], [2, 3])

    def test_parse_highlights_document_rejects_extra_root_field(self) -> None:
        raw = """
        {
          "highlights": [],
          "extra": true
        }
        """

        with self.assertRaisesRegex(ValueError, "highlights.json 校验失败"):
            parse_highlights_document(raw, self.segments)

    def test_parse_highlights_document_rejects_unsorted_segment_ids(self) -> None:
        raw = """
        {
          "highlights": [
            {
              "id": 1,
              "summary": "顺序错误",
              "level": 1,
              "reason": "测试",
              "segment_ids": [3, 2],
              "trigger_segment_id": 2
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "segment_ids 必须按升序排列"):
            parse_highlights_document(raw, self.segments)

    def test_parse_highlights_document_rejects_trigger_outside_segment_ids(self) -> None:
        raw = """
        {
          "highlights": [
            {
              "id": 1,
              "summary": "触发点错误",
              "level": 1,
              "reason": "测试",
              "segment_ids": [2, 3],
              "trigger_segment_id": 1
            }
          ]
        }
        """

        with self.assertRaisesRegex(ValueError, "trigger_segment_id"):
            parse_highlights_document(raw, self.segments)

    def test_parse_highlights_list_validates_final_array(self) -> None:
        raw = """
        [
          {
            "id": 1,
            "summary": "最终结果",
            "level": 2,
            "reason": "测试",
            "segment_ids": [1],
            "trigger_segment_id": 1,
            "start": "00:00:01.000",
            "end": "00:00:02.000",
            "trigger_time": "00:00:01.000",
            "evidence_segments": [
              {
                "id": 1,
                "start": "00:00:01.000",
                "end": "00:00:02.000",
                "text": "第一句",
                "speech": "normal",
                "emotion": "calm",
                "voice": "female",
                "music": "none",
                "audio_cues": [],
                "uncertainty": ""
              }
            ]
          }
        ]
        """

        parsed = parse_highlights_list(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].trigger_time, "00:00:01.000")


if __name__ == "__main__":
    unittest.main()
