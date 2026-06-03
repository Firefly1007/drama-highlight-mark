import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipline.common.schemas import DramaInfo
from pipline.common.schemas import Segment


plot_branch = importlib.import_module("pipline.06_plot_branch")


class PlotBranchRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.current_segments = [
            Segment(
                id=1,
                start="00:00:01.000",
                end="00:00:02.000",
                text="先别急。",
                speech="单人发言",
                emotion="克制",
                voice="平稳",
                music="紧张",
                audio_cues=[],
                uncertainty="",
            ),
            Segment(
                id=2,
                start="00:00:03.500",
                end="00:00:05.000",
                text="你现在就说清楚。",
                speech="单人发言",
                emotion="压迫",
                voice="强硬",
                music="推进",
                audio_cues=[],
                uncertainty="",
            ),
        ]
        self.next_segments = [
            Segment(
                id=1,
                start="00:00:00.800",
                end="00:00:02.500",
                text="我会给你一个交代。",
                speech="单人发言",
                emotion="笃定",
                voice="沉稳",
                music="收束",
                audio_cues=[],
                uncertainty="",
            )
        ]

    def test_finalize_branches_document_adds_ids_episode_numbers_and_time(self) -> None:
        raw = """
        {
          "branches": [
            {
              "trigger": {
                "episode": "current",
                "segment_id": 2
              },
              "question": "要不要逼问？",
              "options": [
                {
                  "text": "继续追问",
                  "prompt": "保持压迫感，局部强化冲突，最终回到 resume。"
                },
                {
                  "text": "先稳住",
                  "prompt": "暂时缓和情绪，最终回到 resume。"
                }
              ],
              "resume": {
                "episode": "next",
                "segment_id": 1
              }
            }
          ]
        }
        """

        final_document = plot_branch.finalize_branches_document(
            raw,
            current_episode_number=12,
            next_episode_number=13,
            current_segments=self.current_segments,
            next_segments=self.next_segments,
        )

        self.assertEqual(
            final_document,
            [
                {
                    "id": 1,
                    "trigger": {
                        "episode": 12,
                        "segment_id": 2,
                        "time": "00:00:03.500",
                    },
                    "question": "要不要逼问？",
                    "options": [
                        {
                            "text": "继续追问",
                            "prompt": "保持压迫感，局部强化冲突，最终回到 resume。",
                        },
                        {
                            "text": "先稳住",
                            "prompt": "暂时缓和情绪，最终回到 resume。",
                        },
                    ],
                    "resume": {
                        "episode": 13,
                        "segment_id": 1,
                        "time": "00:00:00.800",
                    },
                }
            ],
        )

    def test_finalize_branches_document_supports_current_resume(self) -> None:
        raw = """
        {
          "branches": [
            {
              "trigger": {
                "episode": "current",
                "segment_id": 1
              },
              "question": "先忍还是回怼？",
              "options": [
                {
                  "text": "先忍住",
                  "prompt": "压住情绪，短暂偏离后回到 resume。"
                },
                {
                  "text": "直接回怼",
                  "prompt": "立刻顶回去，短暂偏离后回到 resume。"
                }
              ],
              "resume": {
                "episode": "current",
                "segment_id": 2
              }
            }
          ]
        }
        """

        final_document = plot_branch.finalize_branches_document(
            raw,
            current_episode_number=7,
            next_episode_number=8,
            current_segments=self.current_segments,
            next_segments=self.next_segments,
        )

        branch = final_document[0]
        self.assertEqual(branch["trigger"]["episode"], 7)
        self.assertEqual(branch["trigger"]["time"], "00:00:01.000")
        self.assertEqual(branch["resume"]["episode"], 7)
        self.assertEqual(branch["resume"]["time"], "00:00:03.500")

    def test_get_branch_output_path_maps_text_file_to_branch_json_tree(self) -> None:
        text_path = ROOT / "data" / "text" / "某短剧" / "第12集.json"

        output_path = plot_branch.get_branch_output_path(text_path)

        self.assertEqual(
            output_path,
            ROOT / "data" / "branch" / "json" / "某短剧" / "第12集.json",
        )

    def test_find_next_episode_text_path_returns_none_for_last_episode(self) -> None:
        drama_dir = ROOT / "tmp_plot_branch_test"
        drama_dir.mkdir(exist_ok=True)
        try:
            first_path = drama_dir / "第1集.json"
            second_path = drama_dir / "第2集.json"
            first_path.write_text("[]", encoding="utf-8")
            second_path.write_text("[]", encoding="utf-8")

            self.assertEqual(
                plot_branch.find_next_episode_text_path(first_path),
                second_path,
            )
            self.assertIsNone(plot_branch.find_next_episode_text_path(second_path))
        finally:
            if first_path.exists():
                first_path.unlink()
            if second_path.exists():
                second_path.unlink()
            drama_dir.rmdir()

    def test_build_user_prompt_includes_series_context(self) -> None:
        drama = DramaInfo(
            name="某短剧",
            description="这是一个跨时代家族故事。",
            characters=["甲", "乙"],
        )
        text_path = ROOT / "data" / "text" / "某短剧" / "第1集.json"

        with patch.object(plot_branch, "load_drama_info", return_value={"某短剧": drama}):
            with patch.object(
                plot_branch,
                "get_drama_name_from_path",
                return_value="某短剧",
            ):
                prompt = plot_branch.build_user_prompt(
                    current_segments=self.current_segments,
                    current_highlights=[],
                    lookahead_segments=self.next_segments,
                    text_path=text_path,
                )

        self.assertIn("<series_context>", prompt)
        self.assertIn('"name":"某短剧"', prompt)
        self.assertIn('"description":"这是一个跨时代家族故事。"', prompt)
        self.assertIn('"characters":["甲","乙"]', prompt)
        self.assertIn("<current_episode_segments>", prompt)
        self.assertIn("<lookahead_episode_segments>", prompt)


if __name__ == "__main__":
    unittest.main()
