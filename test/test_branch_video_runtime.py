import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipline.common.schemas import Segment
from pipline.common.schemas import DramaInfo


branch_video = importlib.import_module("pipline.07_branch_video")


class BranchVideoRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_option_text = "模型给出的原剧情文案"
        self.current_segments = [
            Segment(
                id=1,
                start="00:00:01.000",
                end="00:00:02.500",
                text="先别动。",
                speech="单人发言",
                emotion="克制",
                voice="平稳",
                music="紧张",
                audio_cues=[],
                uncertainty="",
            )
        ]
        self.next_segments = [
            Segment(
                id=1,
                start="00:00:03.000",
                end="00:00:05.000",
                text="你现在说。",
                speech="单人发言",
                emotion="压迫",
                voice="强硬",
                music="推进",
                audio_cues=[],
                uncertainty="",
            )
        ]
        self.branches = [
            {
                "id": 1,
                "trigger": {
                    "episode": 1,
                    "segment_id": 1,
                    "time": "00:00:01.000",
                },
                "question": "要不要继续追问？",
                "options": [
                    {
                        "text": self.original_option_text,
                        "prompt": "",
                    },
                    {
                        "text": "继续追问",
                        "prompt": "延续压迫感，短暂偏离后回到主线。",
                    },
                    {
                        "text": "先稳住",
                        "prompt": "暂时缓和情绪，最后回到主线。",
                    },
                ],
                "resume": {
                    "episode": 2,
                    "segment_id": 1,
                    "time": "00:00:03.000",
                },
            }
        ]

    def test_get_text_path_from_branch_path_maps_branch_json_tree_to_text_tree(self) -> None:
        branch_path = ROOT / "data" / "branch" / "json" / "某短剧" / "第12集.json"

        text_path = branch_video.get_text_path_from_branch_path(branch_path)

        self.assertEqual(
            text_path,
            ROOT / "data" / "text" / "某短剧" / "第12集.json",
        )

    def test_get_prompt_output_path_maps_branch_json_tree_to_prompt_tree(self) -> None:
        branch_path = ROOT / "data" / "branch" / "json" / "某短剧" / "第12集.json"

        output_path = branch_video.get_prompt_output_path(branch_path)

        self.assertEqual(
            output_path,
            ROOT / "data" / "branch" / "prompt" / "某短剧" / "第12集.json",
        )

    def test_build_user_prompt_includes_segments_branches_and_series_context(self) -> None:
        drama = DramaInfo(
            name="某短剧",
            description="这是一个跨时代家族故事。",
            characters=["甲", "乙"],
        )
        text_path = ROOT / "data" / "text" / "某短剧" / "第1集.json"

        with patch.object(branch_video, "load_drama_info", return_value={"某短剧": drama}):
            with patch.object(
                branch_video,
                "get_drama_name_from_path",
                return_value="某短剧",
            ):
                prompt = branch_video.build_user_prompt(
                    current_segments=self.current_segments,
                    lookahead_segments=self.next_segments,
                    branches_document=self.branches,
                    text_path=text_path,
                )

        self.assertIn("<series_context>", prompt)
        self.assertIn('"name":"某短剧"', prompt)
        self.assertIn('"description":"这是一个跨时代家族故事。"', prompt)
        self.assertIn('"characters":["甲","乙"]', prompt)
        self.assertIn("<current_episode_segments>", prompt)
        self.assertIn("<lookahead_episode_segments>", prompt)
        self.assertIn("<branches>", prompt)
        self.assertIn('"text":"先别动。"', prompt)
        self.assertIn('"question":"要不要继续追问？"', prompt)
        self.assertIn(f'"text":"{self.original_option_text}"', prompt)
        self.assertIn('"text":"继续追问"', prompt)
        self.assertNotIn('"branches":[', prompt)

    def test_system_prompt_marks_series_context_as_reference_only(self) -> None:
        self.assertIn("series_context：剧集背景信息", branch_video.SYSTEM_PROMPT)
        self.assertIn("只用于帮助理解人物、关系、设定和整体背景", branch_video.SYSTEM_PROMPT)
        self.assertIn("series_context 不是当前集剧情事实来源", branch_video.SYSTEM_PROMPT)
        self.assertIn(
            "不要把 series_context.description 中的概括性剧情直接当作当前分支里已经发生",
            branch_video.SYSTEM_PROMPT,
        )
        self.assertIn(
            "不要因为 series_context.characters 或 description 提到某个角色，就默认该角色一定在当前分支视频画面里出场",
            branch_video.SYSTEM_PROMPT,
        )

    def test_parse_model_output_strips_markdown_code_block(self) -> None:
        raw = """
        ```json
        {
          "video_prompts": [
            {
              "branch_index": 0,
              "option_index": 1,
              "prompt": "保持当前镜头关系，最后贴近回归帧。"
            }
          ]
        }
        ```
        """

        document = branch_video.parse_model_output(raw)

        self.assertEqual(len(document.video_prompts), 1)
        self.assertEqual(document.video_prompts[0].branch_index, 0)
        self.assertEqual(document.video_prompts[0].option_index, 1)

    def test_parse_branches_document_supports_root_list(self) -> None:
        raw = """
        [
          {
            "id": 1,
            "trigger": {
              "episode": 1,
              "segment_id": 1,
              "time": "00:00:01.000"
            },
            "question": "要不要继续追问？",
            "options": [
              {
                "text": "__ORIGINAL_TEXT__",
                "prompt": ""
              },
              {
                "text": "继续追问",
                "prompt": "延续压迫感，短暂偏离后回到主线。"
              },
              {
                "text": "先稳住",
                "prompt": "暂时缓和情绪，最后回到主线。"
              }
            ],
            "resume": {
              "episode": 2,
              "segment_id": 1,
              "time": "00:00:03.000"
            }
          }
        ]
        """.replace("__ORIGINAL_TEXT__", self.original_option_text)

        document = branch_video.parse_branches_document(raw)

        self.assertEqual(len(document.branches), 1)
        self.assertEqual(document.branches[0].id, 1)
        self.assertEqual(document.branches[0].options[0].text, self.original_option_text)

    def test_parse_branches_document_rejects_root_object(self) -> None:
        raw = """
        {
          "branches": [
            {
              "id": 1,
              "trigger": {
                "episode": 1,
                "segment_id": 1,
                "time": "00:00:01.000"
              },
            "question": "要不要继续追问？",
            "options": [
              {
                "text": "__ORIGINAL_TEXT__",
                "prompt": ""
              },
              {
                "text": "继续追问",
                "prompt": "延续压迫感，短暂偏离后回到主线。"
              },
              {
                  "text": "先稳住",
                  "prompt": "暂时缓和情绪，最后回到主线。"
                }
              ],
              "resume": {
                "episode": 2,
                "segment_id": 1,
                "time": "00:00:03.000"
              }
            }
          ]
        }
        """.replace("__ORIGINAL_TEXT__", self.original_option_text)

        with self.assertRaises(ValueError):
            branch_video.parse_branches_document(raw)

    def test_parse_branches_document_wraps_validation_error(self) -> None:
        raw = """
        [
          {
            "id": 1,
            "trigger": {
              "episode": 1,
              "segment_id": 0,
              "time": "00:00:01.000"
            },
            "question": "要不要继续追问？",
            "options": [
              {
                "text": "__ORIGINAL_TEXT__",
                "prompt": ""
              },
              {
                "text": "继续追问",
                "prompt": "延续压迫感，短暂偏离后回到主线。"
              }
            ],
            "resume": {
              "episode": 2,
              "segment_id": 1,
              "time": "00:00:03.000"
            }
          }
        ]
        """.replace("__ORIGINAL_TEXT__", self.original_option_text)

        with self.assertRaisesRegex(ValueError, r"branch\.json 校验失败:"):
            branch_video.parse_branches_document(raw)

    def test_parse_branches_document_wraps_json_decode_error(self) -> None:
        raw = "[{]"

        with self.assertRaisesRegex(ValueError, r"branch\.json 不是合法 JSON:"):
            branch_video.parse_branches_document(raw)

    def test_branch_to_video_prompts_returns_empty_result_without_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            branch_path = (
                root / "data" / "branch" / "json" / "某短剧" / "第1集.json"
            )
            branch_path.parent.mkdir(parents=True, exist_ok=True)
            branch_path.write_text("[]", encoding="utf-8")

            with patch.object(
                branch_video,
                "get_async_openai_client",
                side_effect=AssertionError("empty branches should not call model"),
            ):
                result = asyncio.run(
                    branch_video.branch_to_video_prompts(str(branch_path))
                )

        self.assertEqual(result, [])

    def test_branch_to_video_prompts_skips_original_option_index_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            branch_path = root / "data" / "branch" / "json" / "某短剧" / "第1集.json"
            branch_path.parent.mkdir(parents=True, exist_ok=True)
            branch_path.write_text(
                """
                [
                  {
                    "id": 1,
                    "trigger": {
                      "episode": 1,
                      "segment_id": 1,
                      "time": "00:00:01.000"
                    },
                    "question": "要不要继续追问？",
                    "options": [
                      {
                        "text": "__ORIGINAL_TEXT__",
                        "prompt": ""
                      },
                      {
                        "text": "继续追问",
                        "prompt": "延续压迫感，短暂偏离后回到主线。"
                      },
                      {
                        "text": "先稳住",
                        "prompt": "暂时缓和情绪，最后回到主线。"
                      }
                    ],
                    "resume": {
                      "episode": 2,
                      "segment_id": 1,
                      "time": "00:00:03.000"
                    }
                  }
                ]
                """.replace("__ORIGINAL_TEXT__", self.original_option_text),
                encoding="utf-8",
            )
            current_text_path = root / "data" / "text" / "某短剧" / "第1集.json"
            next_text_path = root / "data" / "text" / "某短剧" / "第2集.json"
            current_text_path.parent.mkdir(parents=True, exist_ok=True)
            current_text_path.write_text("[]", encoding="utf-8")
            next_text_path.write_text("[]", encoding="utf-8")
            generated = branch_video.VideoPromptsDocument.model_validate(
                {
                    "video_prompts": [
                        {
                            "branch_index": 0,
                            "option_index": 0,
                            "prompt": "不应保留的原剧情提示词",
                        },
                        {
                            "branch_index": 0,
                            "option_index": 1,
                            "prompt": "保留的提示词1",
                        },
                        {
                            "branch_index": 0,
                            "option_index": 2,
                            "prompt": "保留的提示词2",
                        },
                    ]
                }
            )

            with patch.object(
                branch_video,
                "parse_segments_list",
                side_effect=[self.current_segments, self.next_segments],
            ), patch.object(
                branch_video,
                "build_user_prompt",
                return_value="prompt",
            ), patch.object(
                branch_video,
                "generate_video_prompts",
                new=AsyncMock(return_value=generated),
            ):
                result = asyncio.run(branch_video.branch_to_video_prompts(str(branch_path)))

        self.assertEqual(
            result,
            [
                {
                    "branch_index": 0,
                    "option_index": 1,
                    "prompt": "保留的提示词1",
                },
                {
                    "branch_index": 0,
                    "option_index": 2,
                    "prompt": "保留的提示词2",
                },
            ],
        )

    def test_run_single_branch_file_logs_status_and_writes_json(self) -> None:
        branch_path = ROOT / "data" / "branch" / "json" / "某短剧" / "第1集.json"
        output_path = ROOT / "data" / "branch" / "prompt" / "某短剧" / "第1集.json"
        result: list[dict] = []

        with patch.object(
            branch_video,
            "branch_to_video_prompts",
            new=AsyncMock(return_value=result),
        ) as convert_mock, patch.object(
            branch_video,
            "get_prompt_output_path",
            return_value=output_path,
        ), patch.object(
            branch_video,
            "log_episode_status",
        ) as log_mock, patch.object(
            branch_video,
            "write_json_document",
        ) as write_mock:
            branch_video.run_single_branch_file(branch_path)

        convert_mock.assert_awaited_once_with(str(branch_path))
        self.assertEqual(
            log_mock.call_args_list,
            [
                call(
                    status=branch_video.EpisodeStatus.PENDING,
                    source_path=str(branch_path),
                    output_path=str(output_path),
                ),
                call(
                    status=branch_video.EpisodeStatus.RUNNING,
                    source_path=str(branch_path),
                    output_path=str(output_path),
                ),
                call(
                    status=branch_video.EpisodeStatus.SUCCESS,
                    source_path=str(branch_path),
                    output_path=str(output_path),
                ),
            ],
        )
        write_mock.assert_called_once_with(str(output_path), result)

    def test_batch_convert_uses_tqdm_asyncio_progress(self) -> None:
        tqdm_asyncio_mock = SimpleNamespace()
        tqdm_asyncio_mock.as_completed = Mock(side_effect=lambda tasks, total, desc: tasks)

        with patch.object(
            branch_video,
            "branch_file_to_prompt_file",
            new=AsyncMock(return_value=None),
        ), patch.object(
            branch_video,
            "tqdm_asyncio",
            tqdm_asyncio_mock,
            create=True,
        ) as patched_tqdm_asyncio, patch.object(
            branch_video,
            "tqdm",
            create=True,
        ) as tqdm_mock:
            asyncio.run(
                branch_video.batch_convert(
                    ["a.json", "b.json"],
                    ["a.prompt.json", "b.prompt.json"],
                )
            )

        patched_tqdm_asyncio.as_completed.assert_called_once()
        _, kwargs = patched_tqdm_asyncio.as_completed.call_args
        self.assertEqual(kwargs["total"], 2)
        self.assertEqual(kwargs["desc"], "分支转视频提示词")
        tqdm_mock.write.assert_called_once_with("完成: 成功 2，失败 0")


if __name__ == "__main__":
    unittest.main()
