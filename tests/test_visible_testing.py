import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from visible_test_preparation import prepare_generated_suite
from visible_testing import (
    evaluate_visible_suite,
    find_reusable_suite,
    load_generation_prompt,
    load_review_prompt,
    materialize_generated_suite,
)


class VisibleTestGenerationTests(unittest.TestCase):
    def test_prompt_uses_only_the_c_source_and_leaves_case_count_to_the_model(self):
        prompt = load_generation_prompt()

        self.assertIn("{c_code}", prompt)
        self.assertIn("Choose the number of cases needed", prompt)
        self.assertIn("observable behavior", prompt)
        self.assertIn("make each input complete", prompt)
        self.assertNotIn("Prefer a compact suite", prompt)
        self.assertIn("Do not assume a problem statement", prompt)
        self.assertNotIn("input-dependent loops", prompt)
        self.assertNotIn("conversion counts", prompt)
        self.assertNotIn("scanf", prompt)

        review_prompt = load_review_prompt()
        self.assertIn("{c_code}", review_prompt)
        self.assertIn("{cases}", review_prompt)
        self.assertIn("{deterministic_report}", review_prompt)
        self.assertIn("complete batch", review_prompt)
        self.assertIn("Preserve as many existing cases as possible", review_prompt)
        self.assertIn("Do not require exhaustive coverage", review_prompt)
        self.assertNotIn("scanf", review_prompt)
        self.assertNotIn("sentinel", review_prompt)

    def test_materializes_c_oracles_and_reuses_the_suite(self):
        generation = {
            "strategy": "Exercise zero and a positive value.",
            "cases": [
                {"purpose": "zero", "input": "0\n"},
                {"purpose": "positive", "input": "4\n"},
            ],
        }
        c_runs = [
            {"status": "ACCEPTED", "stdout": "0\n", "stderr": ""},
            {"status": "ACCEPTED", "stdout": "8\n", "stderr": ""},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch("visible_test_preparation.run_program", side_effect=c_runs),
            ):
                suite = materialize_generated_suite(
                    "int main(void) { return 0; }",
                    generation,
                    temp_dir,
                    timeout_sec=1,
                    generation_prompt=load_generation_prompt(),
                )

            reused = find_reusable_suite(
                temp_dir,
                "int main(void) { return 0; }",
                load_generation_prompt(),
            )
            stale = find_reusable_suite(
                temp_dir,
                "int main(void) { return 0; }",
                "changed generation prompt",
            )
            suite_dir = Path(suite["suite_dir"])

            self.assertEqual(suite["status"], "ready")
            self.assertEqual(suite["case_count"], 2)
            self.assertEqual((suite_dir / "case-002.out").read_text(), "8\n")
            self.assertTrue(reused["reused"])
            self.assertEqual(reused["suite_dir"], suite["suite_dir"])
            self.assertIsNone(stale)

    def test_preparation_approves_and_reuses_one_frozen_suite(self):
        generation_calls = []
        review_calls = []

        def generate(feedback):
            generation_calls.append(feedback)
            return {
                "strategy": "Exercise one value.",
                "cases": [{"purpose": "positive", "input": "4\n"}],
            }, {"input_tokens": 10, "output_tokens": 5}

        def review(cases, _deterministic_report):
            review_calls.append(cases)
            return {
                "assessment": "approved",
                "replacements": [],
            }, {"input_tokens": 7, "output_tokens": 3}

        c_runs = [
            {"status": "ACCEPTED", "stdout": "8\n", "stderr": ""},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch("visible_test_preparation.run_program", side_effect=c_runs),
            ):
                suite = prepare_generated_suite(
                    "int main(void) { return 0; }",
                    temp_dir,
                    1,
                    load_generation_prompt(),
                    load_review_prompt(),
                    "gemini",
                    "model",
                    generate,
                    review,
                )

            reused = find_reusable_suite(
                temp_dir,
                "int main(void) { return 0; }",
                load_generation_prompt(),
                load_review_prompt(),
                "gemini",
                "model",
            )
            history = Path(suite["preparation_history_path"])
            history_entries = json.loads(history.read_text(encoding="utf-8"))

            self.assertEqual(suite["status"], "ready")
            self.assertEqual(suite["review_status"], "approved")
            self.assertEqual(suite["generation_attempt_count"], 1)
            self.assertEqual(suite["suite_sha256"], reused["suite_sha256"])
            self.assertTrue(reused["reused"])
            self.assertTrue(history.is_file())
            self.assertEqual(
                history_entries[-1]["action"],
                "preparation_completed",
            )
            self.assertEqual(
                history_entries[-1]["data"]["suite_sha256"],
                suite["suite_sha256"],
            )
            deterministic = next(
                entry
                for entry in history_entries
                if entry["action"] == "deterministic_validation"
            )
            self.assertEqual(
                deterministic["data"]["evaluations"][0]["verdict"],
                "ACCEPTED",
            )
            self.assertEqual(generation_calls, [""])
            self.assertEqual(review_calls[0][0]["id"], "case-001")

            history.unlink()
            self.assertIsNone(
                find_reusable_suite(
                    temp_dir,
                    "int main(void) { return 0; }",
                    load_generation_prompt(),
                    load_review_prompt(),
                    "gemini",
                    "model",
                )
            )

    def test_validator_revision_replaces_requested_case_then_freezes_batch(self):
        generation_feedback = []
        generations = iter(
            [
                {
                    "strategy": "initial",
                    "cases": [{"purpose": "case", "input": "1\n"}],
                },
                {
                    "strategy": "replacement",
                    "cases": [{"purpose": "replacement", "input": "2\n"}],
                },
            ]
        )
        reviews = iter(
            [
                {
                    "assessment": "revise",
                    "replacements": [
                        {
                            "case_id": "case-001",
                            "reason": "The batch needs a distinct behavior.",
                            "requirements": "Generate a different valid input.",
                        }
                    ],
                },
                {
                    "assessment": "approved",
                    "replacements": [],
                },
            ]
        )

        def generate(feedback):
            generation_feedback.append(feedback)
            return next(generations), {}

        def review(_cases, _deterministic_report):
            return next(reviews), {}

        accepted_run = {"status": "ACCEPTED", "stdout": "1\n", "stderr": ""}
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch("visible_test_preparation.run_program", return_value=accepted_run),
            ):
                suite = prepare_generated_suite(
                    "C",
                    temp_dir,
                    1,
                    "generation {c_code}",
                    "review {c_code} {cases}",
                    "provider",
                    "model",
                    generate,
                    review,
                )

            self.assertEqual(suite["status"], "ready")
            self.assertEqual(suite["generation_attempt_count"], 2)
            self.assertIn("Generate a different valid input", generation_feedback[1])
            self.assertIn("frozen", suite["suite_dir"])

    def test_repeated_validator_revision_can_leave_no_usable_cases(self):
        def generate(_feedback):
            return {
                "strategy": "case",
                "cases": [{"purpose": "case", "input": "1\n"}],
            }, {}

        def review(_cases, _deterministic_report):
            return {
                "assessment": "revise",
                "replacements": [
                    {
                        "case_id": "case-001",
                        "reason": "The case is not useful.",
                        "requirements": "Generate a distinct valid input.",
                    }
                ],
            }, {}

        accepted_run = {"status": "ACCEPTED", "stdout": "1\n", "stderr": ""}
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch("visible_test_preparation.run_program", return_value=accepted_run),
            ):
                suite = prepare_generated_suite(
                    "C",
                    temp_dir,
                    1,
                    "generation {c_code}",
                    "review {c_code} {cases}",
                    "provider",
                    "model",
                    generate,
                    review,
                )

            self.assertEqual(suite["status"], "invalid_visible_tests")
            self.assertEqual(suite["review_status"], "revision_unresolved")
            self.assertEqual(suite["generation_attempt_count"], 3)
            self.assertEqual(suite["case_count"], 0)

    def test_preserves_approved_cases_and_generates_only_replacements(self):
        generations = iter(
            [
                {
                    "strategy": "initial",
                    "cases": [
                        {"purpose": "first", "input": "1\n"},
                        {"purpose": "invalid", "input": "2\n"},
                        {"purpose": "third", "input": "3\n"},
                    ],
                },
                {
                    "strategy": "replacement",
                    "cases": [
                        {"purpose": "replacement", "input": "4\n"},
                        {"purpose": "unexpected extra", "input": "5\n"},
                    ],
                },
            ]
        )
        feedback = []
        reviews = iter(
            [
                {
                    "assessment": "revise",
                    "replacements": [
                        {
                            "case_id": "case-002",
                            "reason": "Substantially redundant.",
                            "requirements": "Generate a distinct valid behavior.",
                        },
                    ],
                },
                {
                    "assessment": "approved",
                    "replacements": [],
                },
            ]
        )

        def generate(regeneration_feedback):
            feedback.append(regeneration_feedback)
            return next(generations), {}

        def review(_cases, _deterministic_report):
            return next(reviews), {}

        accepted_run = {"status": "ACCEPTED", "stdout": "ok\n", "stderr": ""}
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch(
                    "visible_test_preparation.run_program",
                    return_value=accepted_run,
                ),
            ):
                suite = prepare_generated_suite(
                    "C",
                    temp_dir,
                    1,
                    "generation {c_code}",
                    "review {c_code} {cases} {deterministic_report}",
                    "provider",
                    "model",
                    generate,
                    review,
                )

            suite_dir = Path(suite["suite_dir"])
            inputs = [
                path.read_text(encoding="utf-8")
                for path in sorted(suite_dir.glob("case-*.in"))
            ]
            history = json.loads(
                Path(suite["preparation_history_path"]).read_text(encoding="utf-8")
            )

        self.assertEqual(suite["status"], "ready")
        self.assertEqual(suite["case_count"], 3)
        self.assertEqual(inputs, ["1\n", "4\n", "3\n"])
        self.assertNotIn("5\n", inputs)
        self.assertEqual(
            [slot["case_id"] for slot in json.loads(feedback[1])["replacement_slots"]],
            ["case-002"],
        )
        replacement = next(
            entry for entry in history if entry["action"] == "batch_review"
        )
        self.assertEqual(replacement["data"]["replacement_count"], 1)

    def test_deterministic_rejection_is_replaced_before_batch_review(self):
        generations = iter(
            [
                {
                    "strategy": "initial",
                    "cases": [
                        {"purpose": "normal", "input": "1\n"},
                        {"purpose": "requires sentinel", "input": "2\n"},
                    ],
                },
                {
                    "strategy": "replacement",
                    "cases": [
                        {"purpose": "with sentinel", "input": "2\n0\n"}
                    ],
                },
            ]
        )
        review_inputs = []

        def generate(_feedback):
            return next(generations), {}

        def review(cases, _deterministic_report):
            review_inputs.append(cases)
            return {"assessment": "approved", "replacements": []}, {}

        accepted = {"status": "ACCEPTED", "stdout": "ok\n", "stderr": ""}
        timed_out = {"status": "TIME_LIMIT_EXCEEDED", "stdout": "", "stderr": ""}
        c_runs = [accepted, timed_out, accepted]
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch(
                    "visible_test_preparation.run_program",
                    side_effect=c_runs,
                ),
            ):
                suite = prepare_generated_suite(
                    "C",
                    temp_dir,
                    1,
                    "generation {c_code}",
                    "review {c_code} {cases} {deterministic_report}",
                    "provider",
                    "model",
                    generate,
                    review,
                )

        self.assertEqual(suite["status"], "ready")
        self.assertEqual(suite["case_count"], 2)
        self.assertEqual(
            [case["id"] for case in review_inputs[0]],
            ["case-001", "case-002"],
        )
        self.assertEqual(
            [case["input"] for case in review_inputs[0]],
            ["1\n", "2\n0\n"],
        )
        self.assertEqual(len(review_inputs), 1)

    def test_repeated_batch_revision_disables_suite_when_no_cases_remain(self):
        generation_count = 0

        def generate(_feedback):
            nonlocal generation_count
            generation_count += 1
            return {
                "strategy": "case",
                "cases": [
                    {"purpose": "case", "input": f"{generation_count}\n"}
                ],
            }, {}

        def review(_cases, _deterministic_report):
            return {
                "assessment": "revise",
                "replacements": [
                    {
                        "case_id": "case-001",
                        "reason": "The batch needs another behavior.",
                        "requirements": "Generate a distinct valid input.",
                    }
                ],
            }, {}

        accepted_run = {"status": "ACCEPTED", "stdout": "1\n", "stderr": ""}
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch("visible_test_preparation.run_program", return_value=accepted_run),
            ):
                suite = prepare_generated_suite(
                    "C",
                    temp_dir,
                    1,
                    "generation {c_code}",
                    "review {c_code} {cases}",
                    "provider",
                    "model",
                    generate,
                    review,
                )

            self.assertEqual(suite["status"], "invalid_visible_tests")
            self.assertEqual(suite["review_status"], "revision_unresolved")
            self.assertEqual(suite["case_count"], 0)
            self.assertEqual(generation_count, 2)

    def test_review_failure_is_operational_and_retried_on_resume(self):
        review_calls = 0

        def generate(_feedback):
            return {
                "strategy": "case",
                "cases": [{"purpose": "case", "input": "1\n"}],
            }, {}

        def review(_cases, _deterministic_report):
            nonlocal review_calls
            review_calls += 1
            if review_calls == 1:
                raise RuntimeError("Provider unavailable.")
            return {
                "assessment": "approved",
                "replacements": [],
            }, {}

        accepted_run = {"status": "ACCEPTED", "stdout": "1\n", "stderr": ""}
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch("visible_test_preparation.run_program", return_value=accepted_run),
            ):
                suite = prepare_generated_suite(
                    "C",
                    temp_dir,
                    1,
                    "generation {c_code}",
                    "review {c_code} {cases}",
                    "provider",
                    "model",
                    generate,
                    review,
                )

            history = json.loads(
                Path(suite["preparation_history_path"]).read_text(encoding="utf-8")
            )
            reusable = find_reusable_suite(
                temp_dir,
                "C",
                "generation {c_code}",
                "review {c_code} {cases}",
                "provider",
                "model",
            )

            self.assertEqual(suite["status"], "review_failed")
            self.assertEqual(suite["review_status"], "not_completed")
            self.assertFalse(suite["frozen"])
            self.assertIn("Provider unavailable", suite["details"])
            self.assertIn("review_failed", [entry["action"] for entry in history])
            self.assertEqual(history[-1]["action"], "preparation_failed")
            self.assertIsNone(reusable)

            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch("visible_test_preparation.run_program", return_value=accepted_run),
            ):
                retried = prepare_generated_suite(
                    "C",
                    temp_dir,
                    1,
                    "generation {c_code}",
                    "review {c_code} {cases}",
                    "provider",
                    "model",
                    generate,
                    review,
                )

            self.assertEqual(retried["status"], "ready")
            self.assertTrue(retried["frozen"])

    def test_executes_each_candidate_once(self):
        accepted_run = {"status": "ACCEPTED", "stdout": "1\n", "stderr": ""}
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch(
                    "visible_test_preparation.run_program",
                    return_value=accepted_run,
                ) as run,
            ):
                suite = materialize_generated_suite(
                    "C",
                    {"strategy": "case", "cases": [{"purpose": "case", "input": "1\n"}]},
                    temp_dir,
                    1,
                    "generation {c_code}",
                )

            self.assertEqual(suite["status"], "ready")
            self.assertEqual(suite["case_count"], 1)
            self.assertEqual(run.call_count, 1)

    def test_validator_receives_a_compact_successful_execution_summary(self):
        review_reports = []

        def generate(_feedback):
            return {
                "strategy": "Exercise one input path.",
                "cases": [{"purpose": "exercise processing", "input": "1 a b"}],
            }, {}

        def review(_cases, deterministic_report):
            review_reports.append(deterministic_report)
            return {"assessment": "approved", "replacements": []}, {}

        empty_run = {"status": "ACCEPTED", "stdout": "", "stderr": ""}
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch(
                    "visible_test_preparation.run_program",
                    return_value=empty_run,
                ),
            ):
                prepare_generated_suite(
                    "C",
                    temp_dir,
                    1,
                    "generation {c_code}",
                    "review {c_code} {cases} {deterministic_report}",
                    "provider",
                    "model",
                    generate,
                    review,
                )

        self.assertEqual(review_reports[0]["case_count"], 1)
        self.assertEqual(review_reports[0]["executions_per_case"], 1)
        self.assertEqual(
            review_reports[0]["status"],
            "all_cases_accepted",
        )

    def test_approval_with_legacy_review_fields_is_rejected(self):
        def generate(_feedback):
            return {
                "strategy": "Exercise one value.",
                "cases": [{"purpose": "positive", "input": "1\n"}],
            }, {}

        def review(_cases, _deterministic_report):
            return {
                "assessment": "approved",
                "diagnosis": "The suite looks valid.",
                "verified_case_ids": [],
                "invalid_case_ids": [],
                "regeneration_guidance": "",
            }, {}

        accepted_run = {"status": "ACCEPTED", "stdout": "1\n", "stderr": ""}
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "visible_test_preparation.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch(
                    "visible_test_preparation.run_program",
                    return_value=accepted_run,
                ),
            ):
                suite = prepare_generated_suite(
                    "C",
                    temp_dir,
                    1,
                    "generation {c_code}",
                    "review {c_code} {cases} {deterministic_report}",
                    "provider",
                    "model",
                    generate,
                    review,
                )

        self.assertEqual(suite["status"], "review_failed")
        self.assertIn("must contain replacements", suite["details"])


class VisibleTestExecutionTests(unittest.TestCase):
    def test_reports_a_language_agnostic_differential_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            suite_dir = Path(temp_dir)
            (suite_dir / "case-001.in").write_text("2\n", encoding="utf-8")
            (suite_dir / "case-001.out").write_text("4\n", encoding="utf-8")
            runs = [
                {"status": "ACCEPTED", "stdout": "4\n", "stderr": ""},
                {"status": "ACCEPTED", "stdout": "5\n", "stderr": ""},
            ]

            with (
                patch(
                    "visible_testing.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch(
                    "visible_testing.compile_rust",
                    return_value=(SimpleNamespace(returncode=0), "rust"),
                ),
                patch("visible_testing.run_program", side_effect=runs),
            ):
                report = evaluate_visible_suite("C", "Rust", suite_dir, timeout_sec=1)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failed_rust_where_c_passed"], 1)
        self.assertEqual(report["verdict_counts"]["WRONG_ANSWER"], 1)
        self.assertEqual(report["failure_examples"][0]["input"], "2\n")
        self.assertNotIn("Failure examples", report["details"])

    def test_baseline_failure_does_not_become_a_rust_repair_signal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            suite_dir = Path(temp_dir)
            (suite_dir / "case-001.in").write_text("2\n", encoding="utf-8")
            (suite_dir / "case-001.out").write_text("4\n", encoding="utf-8")
            runs = [
                {"status": "RUNTIME_ERROR", "stdout": "", "stderr": "error"},
                {"status": "ACCEPTED", "stdout": "4\n", "stderr": ""},
            ]

            with (
                patch(
                    "visible_testing.compile_c",
                    return_value=(SimpleNamespace(returncode=0), "c"),
                ),
                patch(
                    "visible_testing.compile_rust",
                    return_value=(SimpleNamespace(returncode=0), "rust"),
                ),
                patch("visible_testing.run_program", side_effect=runs),
            ):
                report = evaluate_visible_suite("C", "Rust", suite_dir, timeout_sec=1)

        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["failed_rust_where_c_passed"], 0)
        self.assertEqual(report["baseline_failures"][0]["verdict"], "RUNTIME_ERROR")
