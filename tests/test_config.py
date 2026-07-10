import os
import tempfile
import unittest
from pathlib import Path

from config import ConfigDetails


class ConfigDetailsTests(unittest.TestCase):
    def test_reads_config_path_from_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "gemini.yaml"
            config_path.write_text(
                "provider: gemini\nmodel: gemma-4-31b-it\nrequest_rate_limit_rpm: 15\n",
                encoding="utf-8",
            )
            previous = os.environ.get("OXCIDATION_CONFIG_FILE")
            os.environ["OXCIDATION_CONFIG_FILE"] = str(config_path)
            try:
                config = ConfigDetails()
            finally:
                if previous is None:
                    os.environ.pop("OXCIDATION_CONFIG_FILE", None)
                else:
                    os.environ["OXCIDATION_CONFIG_FILE"] = previous

            self.assertEqual(config.llm_provider, "gemini")
            self.assertEqual(config.llm_model, "gemma-4-31b-it")
            self.assertEqual(config.request_rate_limit_rpm, 15)
