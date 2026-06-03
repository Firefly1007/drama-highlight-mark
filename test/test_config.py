import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipline.common.config as config_module


class ConfigTest(unittest.TestCase):
    def tearDown(self) -> None:
        config_module.get_settings.cache_clear()

    def test_get_settings_prefers_env_file_values_over_existing_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "LLM_MODEL_ID=file-model",
                        "LLM_API_KEY=file-key",
                        "LLM_BASE_URL=https://file.example/v1",
                    ]
                ),
                encoding="utf-8",
            )

            config_module.get_settings.cache_clear()
            with patch.dict(
                os.environ,
                {
                    "LLM_MODEL_ID": "process-model",
                    "LLM_API_KEY": "process-key",
                    "LLM_BASE_URL": "https://process.example/v1",
                },
                clear=False,
            ):
                with patch.object(config_module, "ENV_FILE", env_path):
                    settings = config_module.get_settings()

            self.assertEqual(settings.llm_model_id, "file-model")
            self.assertEqual(settings.llm_api_key, "file-key")
            self.assertEqual(settings.llm_base_url, "https://file.example/v1")


if __name__ == "__main__":
    unittest.main()
