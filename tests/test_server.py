import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server


class ServerUsageTests(unittest.TestCase):
    def test_reads_langchain_usage_metadata(self):
        response = SimpleNamespace(
            usage_metadata={"input_tokens": 12, "output_tokens": 7},
            response_metadata={},
        )

        self.assertEqual(
            server.token_usage(response),
            {"input_tokens": 12, "output_tokens": 7},
        )

    def test_reads_openai_compatible_response_metadata(self):
        response = SimpleNamespace(
            usage_metadata={},
            response_metadata={
                "token_usage": {"prompt_tokens": 15, "completion_tokens": 9}
            },
        )

        self.assertEqual(
            server.token_usage(response),
            {"input_tokens": 15, "output_tokens": 9},
        )

    def test_structured_invocation_preserves_raw_message_usage(self):
        parsed = SimpleNamespace(model_dump=lambda: {"value": "ok"})
        raw = SimpleNamespace(
            usage_metadata={"input_tokens": 20, "output_tokens": 4},
            response_metadata={},
        )
        structured = SimpleNamespace()
        structured.with_structured_output = lambda *args, **kwargs: "structured"

        with patch(
            "server.invoke_llm",
            return_value={"parsed": parsed, "raw": raw, "parsing_error": None},
        ):
            payload, usage = server.invoke_structured(
                structured,
                object,
                "prompt",
                "operation",
            )

        self.assertEqual(payload, {"value": "ok"})
        self.assertEqual(usage, {"input_tokens": 20, "output_tokens": 4})


if __name__ == "__main__":
    unittest.main()
