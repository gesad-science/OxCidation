import asyncio
import json
import unittest
from types import SimpleNamespace

from agents import CodeEvaluator, CodeTranslatorAgent, CodeValidator, TesterAgent
from orchestrator import compile_node


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

    def test_visible_timeout_is_classified_from_the_test_report(self):
        state = {
            "test_metrics": {
                "status": "failed",
                "details": "Rust timed out.",
                "verdict_counts": {"TIME_LIMIT_EXCEEDED": 1},
            },
            "repair_count": 0,
        }

        decision = CodeValidator(max_repairs=5).from_tests(state)

        self.assertEqual(decision["failure_category"], "timeout")

    def test_tester_generates_then_executes_one_shared_suite(self):
        session = _TesterSession()
        state = {
            "file_name": "sample.c",
            "c_code": "int main(void) { return 0; }",
            "rust_code": "fn main() {}",
            "visible_test_root": "visible/sample",
            "execution_history": [],
        }

        result = asyncio.run(TesterAgent(session).run_suite(state))

        self.assertEqual(session.tool_names, ["generate_visible_test_suite", "evaluate_test_cases"])
        self.assertEqual(result["test_metrics"]["status"], "success")
        self.assertEqual(result["visible_test_suite"]["suite_dir"], "visible/sample/hash")

    def test_tester_reuses_a_suite_during_repair(self):
        session = _TesterSession()
        state = {
            "file_name": "sample.c",
            "c_code": "int main(void) { return 0; }",
            "rust_code": "fn main() {}",
            "visible_test_root": "visible/sample",
            "visible_test_suite": {
                "status": "ready",
                "suite_dir": "visible/sample/hash",
                "case_count": 1,
            },
            "execution_history": [],
        }

        asyncio.run(TesterAgent(session).run_suite(state))

        self.assertEqual(session.tool_names, ["evaluate_test_cases"])

    def test_skipped_tester_infrastructure_does_not_request_repair(self):
        decision = CodeValidator(max_repairs=5).from_tests(
            {
                "test_metrics": {
                    "status": "skipped",
                    "failure_category": "infrastructure",
                    "reason": "Test generation failed.",
                },
                "repair_count": 0,
            }
        )

        self.assertEqual(decision["validation_decision"]["next_action"], "run_judge")
        self.assertEqual(decision["failure_category"], "infrastructure")

    def test_validator_analyzes_differential_failure(self):
        session = _FakeSession(
            {
                "test_assessment": "translation_discrepancy",
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
                "failure_examples": [{"case": "input_01.in", "input": "1\n"}],
                "details": "Test input_01.in failed.",
                "suite_dir": "visible/sample/hash",
            },
        }

        result = asyncio.run(CodeValidator(max_repairs=5).analyze_test_report(state, session))

        self.assertEqual(result["validator_report"]["status"], "completed")
        self.assertEqual(
            result["agent_interactions"][-1]["data"]["validator_report"]["status"],
            "completed",
        )
        self.assertEqual(
            session.tool_name,
            "analyze_translation_discrepancy",
        )
        self.assertEqual(session.arguments["c_code"], state["c_code"])
        self.assertEqual(
            session.arguments["test_report"]["failure_examples"],
            state["test_metrics"]["failure_examples"],
        )
        self.assertNotIn("details", session.arguments["test_report"])
        self.assertNotIn("suite_dir", session.arguments["test_report"])
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

    def test_interaction_history_preserves_analysis_after_successful_repair(self):
        validator = CodeValidator(max_repairs=5)
        state = {
            "file_name": "sample.c",
            "c_code": "int main(void) { return 0; }",
            "rust_code": "fn main() { print!(\"wrong\"); }",
            "repair_count": 0,
            "agent_interactions": [],
            "test_metrics": {
                "status": "failed",
                "failed_rust_where_c_passed": 1,
                "details": "Rust output differs from C output.",
            },
        }
        analysis_session = _FakeSession(
            {
                "test_assessment": "translation_discrepancy",
                "diagnosis": "Rust prints output that C does not print.",
                "repair_guidance": "Remove the extra output.",
                "semantic_discrepancies": ["Observable output differs."],
            }
        )

        state.update(asyncio.run(validator.analyze_test_report(state, analysis_session)))
        state.update(validator.from_tests(state))
        repair_session = _RepairSession()
        state.update(asyncio.run(CodeTranslatorAgent(repair_session).repair(state)))
        state["test_metrics"] = {
            "status": "success",
            "total_tests": 1,
            "failed_rust_where_c_passed": 0,
        }
        state.update(asyncio.run(validator.analyze_test_report(state, _FakeSession({}))))
        state.update(validator.from_tests(state))

        semantic_reports = [
            interaction["data"]["validator_report"]
            for interaction in state["agent_interactions"]
            if interaction["action"] == "semantic_analysis"
        ]
        self.assertEqual(
            [report["status"] for report in semantic_reports],
            ["completed"],
        )
        self.assertEqual(semantic_reports[0]["repair_guidance"], "Remove the extra output.")
        self.assertEqual(repair_session.arguments["c_code"], state["c_code"])
        self.assertEqual(
            [interaction["sequence"] for interaction in state["agent_interactions"]],
            list(range(1, len(state["agent_interactions"]) + 1)),
        )
        self.assertEqual(
            [
                interaction.get("caused_by_sequence")
                for interaction in state["agent_interactions"][1:]
            ],
            [
                interaction["sequence"]
                for interaction in state["agent_interactions"][:-1]
            ],
        )
        self.assertIn(
            "repair",
            [interaction["action"] for interaction in state["agent_interactions"]],
        )
        self.assertIn(
            "semantic_analysis_skipped",
            [interaction["action"] for interaction in state["agent_interactions"]],
        )
        self.assertNotIn(
            "rust_code_before",
            next(
                interaction["data"]
                for interaction in state["agent_interactions"]
                if interaction["action"] == "repair"
            ),
        )

    def test_invalid_visible_test_does_not_trigger_translation_repair(self):
        state = {
            "test_metrics": {
                "status": "failed",
                "failed_rust_where_c_passed": 4,
                "total_tests": 4,
            },
            "validator_report": {
                "status": "completed",
                "test_assessment": "invalid_visible_test",
                "diagnosis": "The inputs omit a value required by the C input loop.",
                "repair_guidance": "",
            },
            "repair_count": 0,
        }

        result = CodeValidator(max_repairs=5).from_tests(state)

        self.assertEqual(result["validation_decision"]["next_action"], "run_judge")
        self.assertEqual(result["failure_category"], "invalid_tests")
        self.assertEqual(result["errors"], "")

    def test_compile_repair_references_compiler_event_without_copying_it(self):
        session = _RepairSession()
        state = {
            "file_name": "sample.c",
            "c_code": "int main(void) { return 0; }",
            "rust_code": "fn main( {",
            "errors": "expected parameter list",
            "failure_category": "compile",
            "repair_count": 0,
            "agent_interactions": [
                {
                    "sequence": 1,
                    "agent": "translator",
                    "action": "compilation",
                    "repair_count": 0,
                    "data": {
                        "status": "failed",
                        "compiler_output": "expected parameter list",
                    },
                }
            ],
        }

        result = asyncio.run(CodeTranslatorAgent(session).repair(state))
        repair_event = result["agent_interactions"][-1]

        self.assertEqual(repair_event["data"]["feedback_source_sequence"], 1)
        self.assertNotIn("feedback", repair_event["data"])
        self.assertEqual(session.arguments["c_code"], state["c_code"])

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

    def test_evaluator_uses_the_configured_c_rust_judge_comparison(self):
        comparison = _FakeJudgeComparison()
        state = {
            "file_name": "sample.c",
            "problem_id": "p00001",
            "c_code": "int main(void) { return 0; }",
            "rust_code": "fn main() {}",
        }

        result = asyncio.run(CodeEvaluator(comparison).evaluate(state))

        self.assertEqual(comparison.arguments[0:2], ("sample", "p00001"))
        self.assertEqual(result["judge_result"]["status"], "ACCEPTED")
        self.assertEqual(result["baseline_judge"]["baseline_status"], "valid")

    def test_evaluator_records_initial_result_without_changing_pipeline_status(self):
        comparison = _FakeJudgeComparison()
        state = {
            "file_name": "sample.c",
            "problem_id": "p00001",
            "c_code": "int main(void) { return 0; }",
            "rust_code": "fn main() {}",
            "status": "failed",
            "agent_interactions": [],
        }

        result = asyncio.run(CodeEvaluator(comparison).evaluate_initial(state))

        self.assertEqual(result["initial_rust_code"], "fn main() {}")
        self.assertEqual(
            result["initial_evaluation"]["rust"]["judge"]["status"],
            "ACCEPTED",
        )
        self.assertNotIn("status", result)
        self.assertEqual(
            result["agent_interactions"][-1]["action"],
            "initial_judge_evaluation",
        )

    def test_final_evaluation_reuses_unchanged_initial_translation(self):
        comparison = _FakeJudgeComparison()
        state = {
            "file_name": "sample.c",
            "problem_id": "p00001",
            "c_code": "int main(void) { return 0; }",
            "rust_code": "fn main() {}",
            "initial_rust_code": "fn main() {}",
            "initial_evaluation": _FakeJudgeComparison.result(),
            "agent_interactions": [],
        }

        result = asyncio.run(CodeEvaluator(comparison).evaluate(state))

        self.assertIsNone(comparison.arguments)
        self.assertTrue(
            result["agent_interactions"][-1]["data"][
                "reused_initial_evaluation"
            ]
        )

    def test_compile_node_records_initial_evaluator_event(self):
        session = _PipelineSession()
        comparison = _FakeJudgeComparison()
        state = {
            "file_name": "sample.c",
            "problem_id": "p00001",
            "c_code": "int main(void) { return 0; }",
            "rust_code": "fn main() {}",
            "status": "in_progress",
            "repair_count": 0,
            "failure_category": "none",
            "execution_history": [],
            "agent_interactions": [],
            "initial_evaluation": {},
        }

        result = asyncio.run(
            compile_node(
                state,
                {
                    "configurable": {
                        "mcp_session": session,
                        "judge_comparison": comparison,
                    }
                },
            )
        )

        actions = [
            interaction["action"]
            for interaction in result["agent_interactions"]
        ]
        self.assertEqual(actions, ["compilation", "initial_judge_evaluation"])
        self.assertEqual(comparison.call_count, 1)
        self.assertEqual(result["status"], "success")


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


class _FakeJudgeComparison:
    def __init__(self):
        self.arguments = None
        self.call_count = 0

    def evaluate(self, *arguments):
        self.arguments = arguments
        self.call_count += 1
        return self.result()

    @staticmethod
    def result():
        return {
            "baseline_status": "valid",
            "c": {"judge": {"status": "ACCEPTED"}},
            "rust": {
                "judge": {
                    "status": "ACCEPTED",
                    "details": "C and Rust passed.",
                    "verdict_counts": {"ACCEPTED": 1},
                }
            },
        }


class _RepairSession:
    def __init__(self):
        self.arguments = None

    async def call_tool(self, tool_name, arguments):
        self.arguments = arguments
        return SimpleNamespace(
            content=[SimpleNamespace(text="fn main() {}")],
            isError=False,
        )


class _PipelineSession:
    async def call_tool(self, tool_name, arguments):
        await asyncio.sleep(0)
        if tool_name == "translate_c_to_rust":
            text = json.dumps(
                {
                    "rust_code": "fn main() {}",
                    "raw_model_output": "fn main() {}",
                }
            )
        elif tool_name == "compile_rust_code":
            text = "Success: compilation completed"
        elif tool_name == "evaluate_test_cases":
            text = json.dumps(
                {
                    "status": "success",
                    "total_tests": 1,
                    "c_passed": 1,
                    "rust_passed": 1,
                    "rust_failed": 0,
                }
            )
        else:
            raise AssertionError(f"Unexpected tool call: {tool_name}")
        return SimpleNamespace(
            content=[SimpleNamespace(text=text)],
            isError=False,
        )


class _TesterSession:
    def __init__(self):
        self.tool_names = []

    async def call_tool(self, tool_name, arguments):
        self.tool_names.append(tool_name)
        if tool_name == "generate_visible_test_suite":
            payload = {
                "status": "ready",
                "suite_dir": "visible/sample/hash",
                "case_count": 1,
                "prompt_tokens": 10,
                "completion_tokens": 5,
            }
        else:
            payload = {
                "status": "success",
                "total_tests": 1,
                "c_passed": 1,
                "rust_passed": 1,
            }
        return SimpleNamespace(
            content=[SimpleNamespace(text=json.dumps(payload))],
            isError=False,
        )
