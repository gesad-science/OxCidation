import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from visible_testing import (
    evaluate_visible_suite,
    find_reusable_suite,
    load_generation_prompt,
    materialize_generated_suite,
)


class VisibleTestGenerationTests(unittest.TestCase):
    def test_prompt_uses_only_the_c_source_and_leaves_case_count_to_the_model(self):
        prompt = load_generation_prompt()

        self.assertIn("{c_code}", prompt)
        self.assertIn("Choose how many cases are necessary", prompt)
        self.assertIn("Do not use or assume a problem statement", prompt)
        self.assertIn("input-dependent loops", prompt)

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
                patch("visible_testing.compile_c", return_value=(SimpleNamespace(returncode=0), "c")),
                patch("visible_testing.run_program", side_effect=c_runs),
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
                patch("visible_testing.compile_c", return_value=(SimpleNamespace(returncode=0), "c")),
                patch("visible_testing.compile_rust", return_value=(SimpleNamespace(returncode=0), "rust")),
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
                patch("visible_testing.compile_c", return_value=(SimpleNamespace(returncode=0), "c")),
                patch("visible_testing.compile_rust", return_value=(SimpleNamespace(returncode=0), "rust")),
                patch("visible_testing.run_program", side_effect=runs),
            ):
                report = evaluate_visible_suite("C", "Rust", suite_dir, timeout_sec=1)

        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["failed_rust_where_c_passed"], 0)
        self.assertEqual(report["baseline_failures"][0]["verdict"], "RUNTIME_ERROR")
