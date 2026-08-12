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
        self.assertIn("Choose how many cases are necessary", prompt)
        self.assertIn("Do not reduce the number of cases", prompt)
        self.assertNotIn("Prefer a compact suite", prompt)
        self.assertIn("Do not use or assume a problem statement", prompt)
        self.assertIn("input-dependent loops", prompt)
        self.assertIn("conversion counts", prompt)
        self.assertIn("main processing logic", prompt)

        review_prompt = load_review_prompt()
        self.assertIn("{c_code}", review_prompt)
        self.assertIn("{cases}", review_prompt)
        self.assertIn("{deterministic_report}", review_prompt)
        self.assertIn("inconclusive", review_prompt)
        self.assertIn("Review input validity only", review_prompt)
        self.assertIn("Limited coverage is not a reason", review_prompt)
        self.assertIn("conversion counts in scanf-family calls", review_prompt)
        self.assertIn("assess each case independently", review_prompt)
        self.assertIn("output was empty", review_prompt)
        self.assertIn("Do not use or assume a problem statement", review_prompt)

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
            {"status": "ACCEPTED", "stdout": "0\n", "stderr": ""},
            {"status": "ACCEPTED", "stdout": "8\n", "stderr": ""},
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
                "diagnosis": "The input is complete.",
                "verified_case_ids": ["case-001"],
                "invalid_case_ids": [],
                "regeneration_guidance": "",
            }, {"input_tokens": 7, "output_tokens": 3}

        c_runs = [
            {"status": "ACCEPTED", "stdout": "8\n", "stderr": ""},
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
                "ACCEPTED_STABLE",
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

    def test_invalid_suite_is_regenerated_once_then_frozen(self):
        generation_feedback = []
        reviews = iter(
            [
                {
                    "assessment": "invalid",
                    "diagnosis": "A required value is missing.",
                    "verified_case_ids": [],
                    "invalid_case_ids": ["case-001"],
                    "regeneration_guidance": "Supply the declared number of values.",
                },
                {
                    "assessment": "approved",
                    "diagnosis": "The replacement input is complete.",
                    "verified_case_ids": ["case-001"],
                    "invalid_case_ids": [],
                    "regeneration_guidance": "",
                },
            ]
        )

        def generate(feedback):
            generation_feedback.append(feedback)
            return {
                "strategy": "replacement",
                "cases": [{"purpose": "case", "input": "1\n"}],
            }, {}

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
            self.assertIn("Supply the declared number", generation_feedback[1])
            self.assertIn("frozen", suite["suite_dir"])

    def test_second_invalid_suite_becomes_unavailable(self):
        def generate(_feedback):
            return {
                "strategy": "case",
                "cases": [{"purpose": "case", "input": "1\n"}],
            }, {}

        def review(_cases, _deterministic_report):
            return {
                "assessment": "invalid",
                "diagnosis": "The case is incomplete.",
                "verified_case_ids": [],
                "invalid_case_ids": ["case-001"],
                "regeneration_guidance": "Provide all required values.",
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
            self.assertEqual(suite["review_status"], "invalid")
            self.assertEqual(suite["generation_attempt_count"], 2)
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
                    "case_reviews": [
                        {
                            "case_id": "case-001",
                            "assessment": "approved",
                            "diagnosis": "Complete.",
                            "regeneration_guidance": "",
                        },
                        {
                            "case_id": "case-002",
                            "assessment": "invalid",
                            "diagnosis": "Missing a sentinel.",
                            "regeneration_guidance": "Append the required sentinel.",
                        },
                        {
                            "case_id": "case-003",
                            "assessment": "approved",
                            "diagnosis": "Complete.",
                            "regeneration_guidance": "",
                        },
                    ]
                },
                {
                    "case_reviews": [
                        {
                            "case_id": "case-001",
                            "assessment": "approved",
                            "diagnosis": "Complete replacement.",
                            "regeneration_guidance": "",
                        }
                    ]
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
        self.assertEqual(inputs, ["1\n", "3\n", "4\n"])
        self.assertNotIn("5\n", inputs)
        self.assertEqual(json.loads(feedback[1])["replacement_count"], 1)
        replacement = next(
            entry for entry in history if entry["action"] == "replacement_requested"
        )
        self.assertEqual(replacement["data"]["replacement_count"], 1)

    def test_deterministic_rejection_is_reviewed_and_replaced(self):
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
        reviews = iter(
            [
                {
                    "case_reviews": [
                        {
                            "case_id": "case-001",
                            "assessment": "approved",
                            "diagnosis": "Complete.",
                            "regeneration_guidance": "",
                        },
                        {
                            "case_id": "candidate-002",
                            "assessment": "invalid",
                            "diagnosis": "EOF leaves the loop condition true.",
                            "regeneration_guidance": "Append the zero sentinel.",
                        },
                    ]
                },
                {
                    "case_reviews": [
                        {
                            "case_id": "case-001",
                            "assessment": "approved",
                            "diagnosis": "The sentinel terminates the loop.",
                            "regeneration_guidance": "",
                        }
                    ]
                },
            ]
        )
        review_inputs = []

        def generate(_feedback):
            return next(generations), {}

        def review(cases, _deterministic_report):
            review_inputs.append(cases)
            return next(reviews), {}

        accepted = {"status": "ACCEPTED", "stdout": "ok\n", "stderr": ""}
        timed_out = {"status": "TIME_LIMIT_EXCEEDED", "stdout": "", "stderr": ""}
        c_runs = [accepted, accepted, timed_out, timed_out, accepted, accepted]
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
            ["case-001", "candidate-002"],
        )

    def test_inconclusive_review_disables_suite_without_regeneration(self):
        generation_count = 0

        def generate(_feedback):
            nonlocal generation_count
            generation_count += 1
            return {
                "strategy": "case",
                "cases": [{"purpose": "case", "input": "1\n"}],
            }, {}

        def review(_cases, _deterministic_report):
            return {
                "assessment": "inconclusive",
                "diagnosis": "The source does not establish the valid range.",
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

            self.assertEqual(suite["status"], "review_inconclusive")
            self.assertEqual(suite["case_count"], 0)
            self.assertEqual(generation_count, 1)

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
                "diagnosis": "The input is complete.",
                "verified_case_ids": ["case-001"],
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

    def test_unstable_c_output_rejects_the_candidate(self):
        c_runs = [
            {"status": "ACCEPTED", "stdout": "1\n", "stderr": ""},
            {"status": "ACCEPTED", "stdout": "2\n", "stderr": ""},
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
                    "C",
                    {"strategy": "case", "cases": [{"purpose": "case", "input": "1\n"}]},
                    temp_dir,
                    1,
                    "generation {c_code}",
                )

            self.assertEqual(suite["status"], "no_valid_cases")
            self.assertEqual(
                suite["rejected_cases"][0]["verdict"],
                "NONDETERMINISTIC_OUTPUT",
            )

    def test_empty_stable_output_is_exposed_to_review(self):
        review_reports = []

        def generate(_feedback):
            return {
                "strategy": "Exercise one input path.",
                "cases": [{"purpose": "exercise processing", "input": "1 a b"}],
            }, {}

        def review(_cases, deterministic_report):
            review_reports.append(deterministic_report)
            return {
                "assessment": "invalid",
                "diagnosis": "The input does not satisfy all required conversions.",
                "verified_case_ids": [],
                "invalid_case_ids": ["case-001"],
                "regeneration_guidance": "Preserve the required line boundaries.",
            }, {}

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

        evaluation = review_reports[0]["evaluations"][0]
        self.assertTrue(evaluation["stable_output_empty"])
        self.assertEqual(evaluation["first_output_bytes"], 0)
        self.assertEqual(evaluation["second_output_bytes"], 0)

    def test_approval_without_explicit_case_verification_is_rejected(self):
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
        self.assertIn("explicitly verify every case", suite["details"])


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
