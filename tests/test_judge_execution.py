import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from judge_execution import classify_oj_output, compile_c, run_oj_suite
from judge_comparison import (
    JudgeProfile,
    ProblemLimits,
    ProgramCompilation,
    evaluate_program,
)


class JudgeOutputParsingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("gcc"), "gcc is required for this integration test")
    def test_real_c_compilation_uses_gnu89_fallback(self):
        source = (
            "inline int answer(void) { return 42; }\n"
            "int (*answer_ptr)(void) = answer;\n"
            "int main(void) { return answer_ptr() != 42; }\n"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result, executable = compile_c(source, temp_dir)

        self.assertEqual(result.compile_profile, "gnu89-compat")
        self.assertEqual(
            result.compile_attempts,
            [
                {"profile": "gnu11", "status": "failed"},
                {"profile": "gnu89-compat", "status": "success"},
            ],
        )
        self.assertTrue(executable.endswith("prog_c"))

    def test_c_compilation_falls_back_to_gnu89_compatibility(self):
        failed = SimpleNamespace(returncode=1, stdout="", stderr="gnu11 failed")
        succeeded = SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "judge_execution.subprocess.run",
                side_effect=[failed, succeeded],
            ) as run,
        ):
            result, _ = compile_c("main() { return 0; }", temp_dir)

        self.assertEqual(result.compile_profile, "gnu89-compat")
        self.assertEqual(
            result.compile_attempts,
            [
                {"profile": "gnu11", "status": "failed"},
                {"profile": "gnu89-compat", "status": "success"},
            ],
        )
        self.assertIn("-std=gnu11", run.call_args_list[0].args[0])
        self.assertIn("-std=gnu89", run.call_args_list[1].args[0])

    def test_c_compilation_exposes_exhausted_profiles(self):
        failed = SimpleNamespace(returncode=1, stdout="", stderr="failed")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "judge_execution.subprocess.run",
                side_effect=[failed, failed],
            ),
        ):
            result, _ = compile_c("invalid", temp_dir)

        self.assertEqual(result.compile_profile, "")
        self.assertEqual(
            [attempt["status"] for attempt in result.compile_attempts],
            ["failed", "failed"],
        )

    def test_judge_compile_failure_is_reported_without_running_cases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "case.in").write_text("1\n", encoding="utf-8")
            (root / "case.out").write_text("1\n", encoding="utf-8")
            profile = JudgeProfile(root, root, runtime="local")

            with patch(
                "judge_comparison.compile_program",
                return_value=ProgramCompilation(
                    compiler_output="compiler error",
                    executable=None,
                    profile="",
                    attempts=[{"profile": "rustc", "status": "failed"}],
                ),
            ):
                result = evaluate_program(
                    "rust",
                    "invalid",
                    root,
                    ProblemLimits(1000, 65536),
                    profile,
                )

        self.assertEqual(result["compile_status"], "failed")
        self.assertEqual(result["judge"]["status"], "COMPILATION_ERROR")
        self.assertEqual(result["judge"]["total"], 1)

    def test_reports_all_verdicts_and_the_first_failure(self):
        output = """[INFO] sample-01.in
[SUCCESS] AC
[INFO] sample-02.in
[FAILURE] WA
expected: 7
actual: 8
[INFO] sample-03.in
[FAILURE] TLE
test failed: 1 AC / 3 cases
"""

        result = classify_oj_output(1, output, total=3, elapsed_ms=42)

        self.assertEqual(result["status"], "TIME_LIMIT_EXCEEDED")
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 2)
        self.assertEqual(result["verdict_counts"]["ACCEPTED"], 1)
        self.assertEqual(result["verdict_counts"]["WRONG_ANSWER"], 1)
        self.assertEqual(result["verdict_counts"]["TIME_LIMIT_EXCEEDED"], 1)
        self.assertEqual(result["first_failure"]["case"], "sample-02.in")
        self.assertEqual(result["first_failure"]["verdict"], "WRONG_ANSWER")

    def test_keeps_an_accepted_suite_accepted(self):
        result = classify_oj_output(
            0,
            "[SUCCESS] AC\n[SUCCESS] AC\ntest success: 2 cases",
            total=2,
            elapsed_ms=10,
        )

        self.assertEqual(result["status"], "ACCEPTED")
        self.assertEqual(result["passed"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["verdict_counts"]["ACCEPTED"], 2)

    def test_oj_receives_only_explicit_case_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            suite = Path(temp_dir)
            (suite / "judge_data.in").write_text("1\n", encoding="utf-8")
            (suite / "judge_data.out").write_text("1\n", encoding="utf-8")
            (suite / "suite_manifest.json").write_text("{}", encoding="utf-8")

            completed = SimpleNamespace(
                returncode=0,
                stdout="[SUCCESS] AC\ntest success: 1 cases",
                stderr="",
            )
            with (
                patch("judge_execution.shutil.which", return_value="/usr/bin/oj"),
                patch("judge_execution.subprocess.run", return_value=completed) as run,
            ):
                result = run_oj_suite(
                    str(suite),
                    "/work/program",
                    1.0,
                    "ignore-spaces-and-newlines",
                )

            command = run.call_args.args[0]
            self.assertIn(str(suite / "judge_data.in"), command)
            self.assertIn(str(suite / "judge_data.out"), command)
            self.assertNotIn(str(suite / "suite_manifest.json"), command)
            self.assertEqual(result["status"], "ACCEPTED")
