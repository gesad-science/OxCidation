import os

import yaml


class ConfigDetails:
    def __init__(self, config_file: str | None = None):
        config_file = config_file or os.getenv("OXCIDATION_CONFIG_FILE", "config/config.yaml")
        self.config_file = config_file

        with open(self.config_file, 'r', encoding='utf-8') as f:
            self.config_data = yaml.safe_load(f)

        self.llm_provider = self.config_data.get("provider", "openai")
        self.llm_model = self.config_data.get("model", "gpt-4o")
        self.max_repair_attempts = self.config_data.get("max_repair_attempts", 3)
        self.ollama_base_url = self.config_data.get("base_url", "http://localhost:11434")
        self.think = self.config_data.get("think", True)
        self.request_rate_limit_rpm = self.config_data.get("request_rate_limit_rpm", 0)
        self.judge_backend = self.config_data.get("judge_backend", "auto")
        self.judge_time_limit_sec = self.config_data.get("judge_time_limit_sec", 5)
        self.judge_compare_mode = self.config_data.get(
            "judge_compare_mode",
            "ignore-spaces-and-newlines",
        )
