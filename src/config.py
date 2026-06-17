import yaml

class ConfigDetails:
    def __init__(self, config_file: str = 'config/config.yaml'):
        self.config_file = config_file

        with open(self.config_file, 'r', encoding='utf-8') as f:
            self.config_data = yaml.safe_load(f)

        self.llm_provider = self.config_data.get("provider", "openai")
        self.llm_model = self.config_data.get("model", "gpt-4o")
        self.max_repair_attempts = self.config_data.get("max_repair_attempts", 3)
        self.ollama_base_url = self.config_data.get("base_url", "http://localhost:11434")
        self.think = self.config_data.get("think", True)