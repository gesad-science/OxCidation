import unittest

from agents import CodeValidator


class TranslationValidationTests(unittest.TestCase):
    def test_translation_failure_stops_without_repair(self):
        decision = CodeValidator(max_repairs=5).from_translation(
            {"status": "failed", "rust_code": "", "errors": "Provider request failed."}
        )

        self.assertEqual(decision["validation_decision"]["next_action"], "stop_failed")
        self.assertEqual(decision["failure_category"], "infrastructure")

    def test_translation_with_code_continues_to_compilation(self):
        decision = CodeValidator(max_repairs=5).from_translation(
            {"status": "in_progress", "rust_code": "fn main() {}"}
        )

        self.assertEqual(
            decision["validation_decision"]["next_action"],
            "compile_translation",
        )
