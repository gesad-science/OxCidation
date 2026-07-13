import asyncio
import json
import unittest
from types import SimpleNamespace

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

    def test_visible_failure_uses_validator_repair_guidance(self):
        state = {
            "test_metrics": {"status": "failed", "details": "Output differs."},
            "repair_count": 0,
            "validator_report": {
                "diagnosis": "The row width differs.",
                "repair_guidance": "Preserve the C printf width of five characters.",
            },
        }

        decision = CodeValidator(max_repairs=5).from_tests(state)

        self.assertEqual(decision["validation_decision"]["next_action"], "repair_translation")
        self.assertIn("Semantic diagnosis", decision["errors"])
        self.assertIn("printf width", decision["errors"])

    def test_validator_analyzes_differential_failure(self):
        session = _FakeSession(
            {
                "diagnosis": "The Rust program omits the final newline.",
                "repair_guidance": "Print a newline after the result.",
                "semantic_discrepancies": ["Output formatting differs."],
            }
        )
        state = {
            "file_name": "sample.c",
            "c_code": "int main(void) { return 0; }",
            "rust_code": "fn main() {}",
            "test_metrics": {
                "status": "failed",
                "failed_rust_where_c_passed": 1,
                "details": "Test input_01.in failed.",
            },
        }

        result = asyncio.run(CodeValidator(max_repairs=5).analyze_test_report(state, session))

        self.assertEqual(result["validator_report"]["status"], "completed")
        self.assertEqual(
            session.tool_name,
            "analyze_translation_discrepancy",
        )
        self.assertEqual(session.arguments["c_code"], state["c_code"])
        self.assertEqual(result["validator_report"]["repair_guidance"], "Print a newline after the result.")

    def test_validator_skips_analysis_without_differential_failure(self):
        session = _FakeSession({})
        state = {
            "file_name": "sample.c",
            "c_code": "int main(void) { return 0; }",
            "rust_code": "fn main() {}",
            "test_metrics": {"status": "success", "total_tests": 3},
        }

        result = asyncio.run(CodeValidator(max_repairs=5).analyze_test_report(state, session))

        self.assertEqual(result["validator_report"]["status"], "not_required")
        self.assertIsNone(session.tool_name)

    def test_validator_skips_analysis_without_differential_failure_or_rust_code(self):
        session = _FakeSession({})
        result = asyncio.run(
            CodeValidator(max_repairs=5).analyze_test_report(
                {"file_name": "sample.c", "test_metrics": {"status": "skipped"}},
                session,
            )
        )

        self.assertEqual(result["validator_report"]["status"], "not_required")
        self.assertIsNone(session.tool_name)


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.tool_name = None
        self.arguments = None

    async def call_tool(self, tool_name, arguments):
        self.tool_name = tool_name
        self.arguments = arguments
        return SimpleNamespace(
            content=[SimpleNamespace(text=json.dumps(self.payload))],
            isError=False,
        )
