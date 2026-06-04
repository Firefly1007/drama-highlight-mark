import asyncio
import base64
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

branch_image = importlib.import_module("pipline.08_branch_image")


class ParsePromptItemsTest(unittest.TestCase):
    def test_valid_root_array(self) -> None:
        raw = json.dumps(
            [
                {"branch_index": 0, "option_index": 0, "prompt": ""},
                {"branch_index": 0, "option_index": 1, "prompt": "提示词B"},
            ]
        )

        items = branch_image.parse_prompt_items(raw)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].branch_index, 0)
        self.assertEqual(items[0].option_index, 0)
        self.assertEqual(items[1].prompt, "提示词B")

    def test_empty_array(self) -> None:
        items = branch_image.parse_prompt_items("[]")

        self.assertEqual(items, [])

    def test_rejects_root_object(self) -> None:
        with self.assertRaises(ValueError):
            branch_image.parse_prompt_items('{"video_prompts": []}')

    def test_rejects_empty_non_original_prompt(self) -> None:
        raw = json.dumps([{"branch_index": 0, "option_index": 1, "prompt": ""}])

        with self.assertRaises(ValueError):
            branch_image.parse_prompt_items(raw)

    def test_rejects_invalid_json(self) -> None:
        with self.assertRaises(ValueError):
            branch_image.parse_prompt_items("[{]")


class ParseBranchItemsTest(unittest.TestCase):
    def test_valid_root_array(self) -> None:
        raw = json.dumps(
            [
                {
                    "id": 1,
                    "trigger": {"episode": 1, "segment_id": 4, "time": "00:00:44.300"},
                    "question": "问题",
                    "options": [{"text": "A", "prompt": "a"}],
                    "resume": {"episode": 1, "segment_id": 7, "time": "00:01:03.300"},
                }
            ]
        )

        items = branch_image.parse_branch_items(raw)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].trigger.time, "00:00:44.300")
        self.assertEqual(items[0].resume.time, "00:01:03.300")

    def test_rejects_root_object(self) -> None:
        with self.assertRaises(ValueError):
            branch_image.parse_branch_items('{"branches": []}')


class PathMappingTest(unittest.TestCase):
    def test_get_branch_path_from_prompt_path(self) -> None:
        prompt_path = ROOT / "data" / "branch" / "prompt" / "某剧" / "第1集.json"

        result = branch_image.get_branch_path_from_prompt_path(prompt_path)

        self.assertEqual(result, ROOT / "data" / "branch" / "json" / "某剧" / "第1集.json")

    def test_get_image_dir_from_prompt_path(self) -> None:
        prompt_path = ROOT / "data" / "branch" / "prompt" / "某剧" / "第1集.json"

        result = branch_image.get_image_dir_from_prompt_path(prompt_path)

        self.assertEqual(result, ROOT / "data" / "branch" / "image" / "某剧" / "第1集")

    def test_get_video_path(self) -> None:
        result = branch_image.get_video_path(6, "某剧")

        self.assertEqual(result, ROOT / "data" / "video" / "某剧" / "第6集.mp4")

    def test_extract_drama_name_from_prompt_path(self) -> None:
        prompt_path = ROOT / "data" / "branch" / "prompt" / "某剧名" / "第1集.json"

        result = branch_image.extract_drama_name_from_path(prompt_path)

        self.assertEqual(result, "某剧名")

    def test_extract_drama_name_from_json_path(self) -> None:
        json_path = ROOT / "data" / "branch" / "json" / "某剧名" / "第1集.json"

        result = branch_image.extract_drama_name_from_path(json_path)

        self.assertEqual(result, "某剧名")

    def test_sort_prompt_files_by_episode_orders_numerically(self) -> None:
        prompt_files = [
            ROOT / "data" / "branch" / "prompt" / "某剧" / "第10集.json",
            ROOT / "data" / "branch" / "prompt" / "某剧" / "第2集.json",
            ROOT / "data" / "branch" / "prompt" / "某剧" / "第1集.json",
        ]

        result = branch_image.sort_prompt_files_by_episode(prompt_files)

        self.assertEqual(
            [path.name for path in result],
            ["第1集.json", "第2集.json", "第10集.json"],
        )


class CompletionDetectionTest(unittest.TestCase):
    def test_empty_prompt_file_is_incomplete_without_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "data" / "branch" / "prompt" / "某剧" / "第1集.json"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("[]", encoding="utf-8")

            result = branch_image.is_prompt_file_complete(prompt_path)

        self.assertFalse(result)

    def test_empty_prompt_file_is_complete_when_output_dir_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "data" / "branch" / "prompt" / "某剧" / "第1集.json"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("[]", encoding="utf-8")
            image_dir = root / "data" / "branch" / "image" / "某剧" / "第1集"
            image_dir.mkdir(parents=True, exist_ok=True)

            result = branch_image.is_prompt_file_complete(prompt_path)

        self.assertTrue(result)

    def test_prompt_file_is_complete_when_all_expected_images_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "data" / "branch" / "prompt" / "某剧" / "第1集.json"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(
                json.dumps(
                    [
                        {"branch_index": 0, "option_index": 0, "prompt": ""},
                        {"branch_index": 1, "option_index": 2, "prompt": "B"},
                    ]
                ),
                encoding="utf-8",
            )
            image_dir = root / "data" / "branch" / "image" / "某剧" / "第1集"
            image_dir.mkdir(parents=True, exist_ok=True)
            (image_dir / "1_2.jpeg").write_bytes(b"b")

            result = branch_image.is_prompt_file_complete(prompt_path)

        self.assertTrue(result)

    def test_prompt_file_is_incomplete_when_any_expected_image_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "data" / "branch" / "prompt" / "某剧" / "第1集.json"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(
                json.dumps(
                    [
                        {"branch_index": 0, "option_index": 0, "prompt": ""},
                        {"branch_index": 1, "option_index": 2, "prompt": "B"},
                    ]
                ),
                encoding="utf-8",
            )
            image_dir = root / "data" / "branch" / "image" / "某剧" / "第1集"
            image_dir.mkdir(parents=True, exist_ok=True)

            result = branch_image.is_prompt_file_complete(prompt_path)

        self.assertFalse(result)


class ExtractFrameTest(unittest.TestCase):
    def test_calls_ffmpeg_with_correct_args(self) -> None:
        png_bytes = b"\x89PNG\r\n\x1a\n"
        with patch.object(branch_image.subprocess, "run") as mock_run, \
             patch("builtins.open", unittest.mock.mock_open(read_data=png_bytes)), \
             patch.object(branch_image.Path, "unlink"):
            result = branch_image.extract_frame_as_data_uri(
                Path("/video/test.mp4"), "00:00:44.300"
            )

        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], "ffmpeg")
        self.assertIn("-ss", args)
        self.assertEqual(args[args.index("-ss") + 1], "00:00:44.300")
        self.assertIn("-i", args)
        self.assertEqual(args[args.index("-i") + 1], str(Path("/video/test.mp4")))
        self.assertIn("-frames:v", args)
        self.assertEqual(args[args.index("-frames:v") + 1], "1")
        self.assertTrue(result.startswith("data:image/png;base64,"))

    def test_returns_data_uri_with_valid_base64(self) -> None:
        png_bytes = b"\x89PNG test data"
        expected_b64 = base64.b64encode(png_bytes).decode("utf-8")
        with patch.object(branch_image.subprocess, "run"), \
             patch("builtins.open", unittest.mock.mock_open(read_data=png_bytes)), \
             patch.object(branch_image.Path, "unlink"):
            result = branch_image.extract_frame_as_data_uri(
                Path("/video/test.mp4"), "00:00:01.000"
            )

        self.assertEqual(result, f"data:image/png;base64,{expected_b64}")


class GenerateImageTest(unittest.TestCase):
    def test_calls_api_with_correct_params(self) -> None:
        fake_jpeg = b"\xff\xd8\xff fake jpeg"
        fake_b64 = base64.b64encode(fake_jpeg).decode("utf-8")
        fake_response = SimpleNamespace(
            data=[SimpleNamespace(b64_json=fake_b64)]
        )
        mock_client = Mock()
        mock_client.images.generate.return_value = fake_response

        with patch.object(branch_image, "get_settings") as mock_settings, \
             patch.object(branch_image, "get_video_client", return_value=mock_client):
            mock_settings.return_value = SimpleNamespace(video_model_id="test-model")
            result = branch_image.generate_image(
                "测试提示词",
                ["data:image/png;base64,abc", "data:image/png;base64,def"],
            )

        self.assertEqual(result, fake_jpeg)
        mock_client.images.generate.assert_called_once_with(
            model="test-model",
            prompt="测试提示词",
            size="1600x2848",
            response_format="b64_json",
            extra_body={
                "image": ["data:image/png;base64,abc", "data:image/png;base64,def"],
                "watermark": False,
                "sequential_image_generation": "disabled",
            },
        )

    def test_rejects_response_without_image_data(self) -> None:
        mock_client = Mock()
        mock_client.images.generate.return_value = SimpleNamespace(data=None)

        with patch.object(branch_image, "get_settings") as mock_settings, \
             patch.object(branch_image, "get_video_client", return_value=mock_client):
            mock_settings.return_value = SimpleNamespace(video_model_id="test-model")

            with self.assertRaisesRegex(ValueError, "图片生成响应缺少 data"):
                branch_image.generate_image("测试提示词", ["data:image/png;base64,abc"])

    def test_rejects_response_without_b64_payload(self) -> None:
        mock_client = Mock()
        mock_client.images.generate.return_value = SimpleNamespace(
            data=[SimpleNamespace(b64_json=None)]
        )

        with patch.object(branch_image, "get_settings") as mock_settings, \
             patch.object(branch_image, "get_video_client", return_value=mock_client):
            mock_settings.return_value = SimpleNamespace(video_model_id="test-model")

            with self.assertRaisesRegex(ValueError, "图片生成响应缺少 b64_json"):
                branch_image.generate_image("测试提示词", ["data:image/png;base64,abc"])


class ProcessPromptFileTest(unittest.TestCase):
    def test_skips_empty_prompt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "data" / "branch" / "prompt" / "某剧" / "第1集.json"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("[]", encoding="utf-8")

            with patch.object(
                branch_image, "generate_image",
                side_effect=AssertionError("empty prompts should not call API"),
            ), patch.object(branch_image, "log_episode_status") as log_mock:
                asyncio.run(branch_image.process_prompt_file(prompt_path))

            image_dir = root / "data" / "branch" / "image" / "某剧" / "第1集"
            output_path = str(root / "data" / "branch" / "image" / "某剧" / "第1集")
            self.assertTrue(image_dir.is_dir())
            self.assertEqual(
                log_mock.call_args_list,
                [
                    unittest.mock.call(
                        status=branch_image.EpisodeStatus.PENDING,
                        source_path=str(prompt_path),
                        output_path=output_path,
                    ),
                    unittest.mock.call(
                        status=branch_image.EpisodeStatus.RUNNING,
                        source_path=str(prompt_path),
                        output_path=output_path,
                    ),
                    unittest.mock.call(
                        status=branch_image.EpisodeStatus.SUCCESS,
                        source_path=str(prompt_path),
                        output_path=output_path,
                    ),
                ],
            )

    def test_raises_when_branch_index_out_of_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "data" / "branch" / "prompt" / "某剧" / "第1集.json"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(
                json.dumps([{"branch_index": 5, "option_index": 0, "prompt": "提示词"}]),
                encoding="utf-8",
            )
            branch_path = root / "data" / "branch" / "json" / "某剧" / "第1集.json"
            branch_path.parent.mkdir(parents=True, exist_ok=True)
            branch_path.write_text("[]", encoding="utf-8")

            with self.assertRaises(ValueError):
                asyncio.run(branch_image.process_prompt_file(prompt_path))

    def test_generates_and_saves_images(self) -> None:
        fake_jpeg = b"\xff\xd8\xff fake jpeg data"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "data" / "branch" / "prompt" / "某剧" / "第1集.json"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(
                json.dumps(
                    [
                        {"branch_index": 0, "option_index": 0, "prompt": ""},
                        {"branch_index": 0, "option_index": 1, "prompt": "提示词B"},
                    ]
                ),
                encoding="utf-8",
            )
            branch_path = root / "data" / "branch" / "json" / "某剧" / "第1集.json"
            branch_path.parent.mkdir(parents=True, exist_ok=True)
            branch_path.write_text(
                json.dumps(
                    [
                        {
                            "id": 1,
                            "trigger": {"episode": 1, "segment_id": 1, "time": "00:00:10.000"},
                            "question": "问题",
                            "options": [],
                            "resume": {"episode": 1, "segment_id": 2, "time": "00:00:20.000"},
                        }
                    ]
                ),
                encoding="utf-8",
            )
            image_dir = root / "data" / "branch" / "image" / "某剧" / "第1集"
            fake_video = root / "video.mp4"
            fake_video.touch()

            with patch.object(
                branch_image, "get_video_path",
                return_value=fake_video,
            ), patch.object(
                branch_image, "extract_frame_as_data_uri",
                return_value="data:image/png;base64,fake",
            ), patch.object(
                branch_image, "generate_image",
                return_value=fake_jpeg,
            ) as gen_mock:
                asyncio.run(branch_image.process_prompt_file(prompt_path))

            self.assertEqual(gen_mock.call_count, 1)
            img_a = image_dir / "0_0.jpeg"
            img_b = image_dir / "0_1.jpeg"
            self.assertFalse(img_a.exists())
            self.assertTrue(img_b.exists())
            self.assertEqual(img_b.read_bytes(), fake_jpeg)

    def test_same_branch_index_shares_frame_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "data" / "branch" / "prompt" / "某剧" / "第1集.json"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(
                json.dumps(
                    [
                        {"branch_index": 0, "option_index": 0, "prompt": ""},
                        {"branch_index": 0, "option_index": 1, "prompt": "B"},
                    ]
                ),
                encoding="utf-8",
            )
            branch_path = root / "data" / "branch" / "json" / "某剧" / "第1集.json"
            branch_path.parent.mkdir(parents=True, exist_ok=True)
            branch_path.write_text(
                json.dumps(
                    [
                        {
                            "id": 1,
                            "trigger": {"episode": 1, "segment_id": 1, "time": "00:00:10.000"},
                            "question": "问题",
                            "options": [],
                            "resume": {"episode": 1, "segment_id": 2, "time": "00:00:20.000"},
                        }
                    ]
                ),
                encoding="utf-8",
            )
            fake_video = root / "video.mp4"
            fake_video.touch()

            with patch.object(
                branch_image, "get_video_path",
                return_value=fake_video,
            ), patch.object(
                branch_image, "extract_frame_as_data_uri",
                return_value="data:image/png;base64,fake",
            ) as frame_mock, patch.object(
                branch_image, "generate_image",
                return_value=b"\xff\xd8\xff",
            ):
                asyncio.run(branch_image.process_prompt_file(prompt_path))

            # 同一 branch_index 只截帧一次（调用两次：start + resume）
            self.assertEqual(frame_mock.call_count, 2)


class BatchProcessPromptFilesTest(unittest.TestCase):
    def test_batch_process_prompt_files_uses_tqdm_asyncio_progress(self) -> None:
        tqdm_asyncio_mock = SimpleNamespace()
        tqdm_asyncio_mock.as_completed = Mock(side_effect=lambda tasks, total, desc: tasks)
        process_mock = AsyncMock(return_value=None)

        with patch.object(
            branch_image,
            "process_prompt_file",
            new=process_mock,
        ), patch.object(
            branch_image,
            "tqdm_asyncio",
            tqdm_asyncio_mock,
            create=True,
        ) as patched_tqdm_asyncio, patch.object(
            branch_image,
            "tqdm",
            create=True,
        ) as tqdm_mock:
            asyncio.run(
                branch_image.batch_process_prompt_files(
                    [Path("第1集.json"), Path("第2集.json")]
                )
            )

        patched_tqdm_asyncio.as_completed.assert_called_once()
        _, kwargs = patched_tqdm_asyncio.as_completed.call_args
        self.assertEqual(kwargs["total"], 2)
        self.assertEqual(kwargs["desc"], "prompt转分支图片")
        tqdm_mock.write.assert_called_once_with("完成: 成功 2，失败 0")
        self.assertEqual(
            process_mock.call_args_list,
            [
                unittest.mock.call(Path("第1集.json"), emit_status_logs=False),
                unittest.mock.call(Path("第2集.json"), emit_status_logs=False),
            ],
        )

    def test_batch_process_prompt_dir_skips_prompt_files_already_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_dir = root / "data" / "branch" / "prompt" / "某剧"
            prompt_dir.mkdir(parents=True, exist_ok=True)

            prompt_complete = prompt_dir / "第1集.json"
            prompt_complete.write_text(
                json.dumps(
                    [
                        {"branch_index": 0, "option_index": 0, "prompt": ""},
                        {"branch_index": 0, "option_index": 1, "prompt": "A"},
                    ]
                ),
                encoding="utf-8",
            )
            complete_image_dir = root / "data" / "branch" / "image" / "某剧" / "第1集"
            complete_image_dir.mkdir(parents=True, exist_ok=True)
            (complete_image_dir / "0_1.jpeg").write_bytes(b"a")

            prompt_incomplete = prompt_dir / "第2集.json"
            prompt_incomplete.write_text(
                json.dumps(
                    [
                        {"branch_index": 0, "option_index": 0, "prompt": ""},
                        {"branch_index": 0, "option_index": 1, "prompt": "B"},
                    ]
                ),
                encoding="utf-8",
            )

            batch_mock = AsyncMock(return_value=None)
            with patch.object(branch_image, "batch_process_prompt_files", new=batch_mock):
                branch_image.batch_process_prompt_dir(prompt_dir)

        batch_mock.assert_awaited_once_with([prompt_incomplete])


if __name__ == "__main__":
    unittest.main()
