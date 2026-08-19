import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from judge_comparison import (
    JudgeComparison,
    JudgeProfile,
    ProblemLimits,
    compile_program,
    has_test_cases,
    resolve_test_directory,
    start_execution_container,
)
from judge_execution import judge_result


class SmokeJudgeTestDirectoryTests(unittest.TestCase):
    def test_prefers_submission_io_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cases = root / "s1"
            cases.mkdir()
            (cases / "1.in").write_text("1\n", encoding="utf-8")
            (cases / "1.out").write_text("1\n", encoding="utf-8")
            (cases / "suite_manifest.json").write_text("{}", encoding="utf-8")

            directory, layout = resolve_test_directory(root, "s1", "p1", root / "normalized")

            self.assertEqual(directory, cases)
            self.assertEqual(layout, "io-directory")

    def test_normalizes_codenet_single_case_by_problem(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            problem = root / "p1"
            problem.mkdir()
            (problem / "input.txt").write_text("1\n", encoding="utf-8")
            (problem / "output.txt").write_text("2\n", encoding="utf-8")

            directory, layout = resolve_test_directory(root, "s1", "p1", root / "normalized")

            self.assertEqual(layout, "codenet-single-case")
            self.assertEqual((directory / "1.in").read_text(encoding="utf-8"), "1\n")
            self.assertEqual((directory / "1.out").read_text(encoding="utf-8"), "2\n")

    def test_requires_a_matching_output_for_io_directory_coverage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cases = root / "p1"
            cases.mkdir()
            (cases / "1.in").write_text("1\n", encoding="utf-8")

            self.assertFalse(has_test_cases(root, "s1", "p1"))

            (cases / "1.out").write_text("2\n", encoding="utf-8")

            self.assertTrue(has_test_cases(root, "s1", "p1"))

            (cases / "2.in").write_text("2\n", encoding="utf-8")

            self.assertFalse(has_test_cases(root, "s1", "p1"))

    def test_container_command_uses_problem_memory_for_stack_and_memory(self):
        profile = JudgeProfile(Path("tests"), Path("metadata"))
        with patch("judge_comparison.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "container-id\n"
            container_id = start_execution_container(
                Path("/tmp"),
                "c",
                ProblemLimits(time_limit_ms=1000, memory_limit_kib=131072),
                profile,
            )

        command = run.call_args.args[0]
        self.assertEqual(container_id, "container-id")
        self.assertIn("--memory", command)
        self.assertIn("131072k", command)
        self.assertIn("--memory-swap", command)
        self.assertIn("131073k", command)
        self.assertIn("stack=134217728:134217728", command)

    def test_container_compilation_prepares_readable_source_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir) / "work"
            work_dir.mkdir()
            profile = JudgeProfile(Path("tests"), Path("metadata"))
            with patch("judge_comparison.subprocess.run") as run:
                run.return_value.returncode = 1
                compile_program("c", "int main(void) {}", work_dir, profile)

            command = run.call_args.args[0]
            self.assertEqual((work_dir / "source.c").stat().st_mode & 0o777, 0o644)
            self.assertEqual(work_dir.stat().st_mode & 0o777, 0o755)
            self.assertIn(f"{work_dir}:/work:Z", command)

    def test_container_c_compilation_falls_back_to_gnu89(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            (work_dir / "program-c").touch()
            profile = JudgeProfile(Path("tests"), Path("metadata"))
            failed = Mock(returncode=1, stderr="gnu11 failed")
            succeeded = Mock(returncode=0, stderr="")

            with patch(
                "judge_comparison.subprocess.run",
                side_effect=[failed, succeeded],
            ) as run:
                compilation = compile_program(
                    "c",
                    "main() { return 0; }",
                    work_dir,
                    profile,
                )

            self.assertEqual(compilation.profile, "gnu89-compat")
            self.assertEqual(
                compilation.attempts,
                [
                    {"profile": "gnu11", "status": "failed"},
                    {"profile": "gnu89-compat", "status": "success"},
                ],
            )
            self.assertIn("-std=gnu11", run.call_args_list[0].args[0])
            self.assertIn("-std=gnu89", run.call_args_list[1].args[0])

    def test_invalid_c_baseline_skips_rust_evaluation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata = root / "metadata"
            metadata.mkdir()
            (metadata / "problem_list.csv").write_text(
                "id,name,dataset,time_limit,memory_limit,rating,tags,complexity\n"
                "p1,Example,AIZU,1000,131072,,,\n",
                encoding="utf-8",
            )
            cases = root / "cases" / "p1"
            cases.mkdir(parents=True)
            (cases / "1.in").write_text("1\n", encoding="utf-8")
            (cases / "1.out").write_text("1\n", encoding="utf-8")
            failed_c = {
                "compile_status": "success",
                "compiler_output": "",
                "judge": judge_result("WRONG_ANSWER", 0, 1, 1, 1, "C output differs."),
            }

            with patch("judge_comparison.evaluate_program", return_value=failed_c) as evaluate:
                comparison = JudgeComparison(
                    JudgeProfile(root / "cases", metadata, runtime="local")
                ).evaluate("s1", "p1", "int main() {}", "fn main() {}")

            self.assertEqual(comparison["baseline_status"], "invalid")
            self.assertEqual(comparison["rust"]["compile_status"], "not_run")
            self.assertEqual(evaluate.call_count, 1)

    def test_evaluate_c_baseline_exposes_c_only_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata = root / "metadata"
            metadata.mkdir()
            (metadata / "problem_list.csv").write_text(
                "id,name,dataset,time_limit,memory_limit,rating,tags,complexity\n"
                "p1,Example,AIZU,1000,131072,,,\n",
                encoding="utf-8",
            )
            cases = root / "cases" / "p1"
            cases.mkdir(parents=True)
            (cases / "1.in").write_text("1\n", encoding="utf-8")
            (cases / "1.out").write_text("1\n", encoding="utf-8")
            accepted_c = {
                "compile_status": "success",
                "compiler_output": "",
                "compile_profile": "gnu11",
                "compile_attempts": [{"profile": "gnu11", "status": "success"}],
                "judge": judge_result("ACCEPTED", 1, 0, 1, 1, "Accepted."),
            }

            with patch(
                "judge_comparison.evaluate_program",
                return_value=accepted_c,
            ) as evaluate:
                result = JudgeComparison(
                    JudgeProfile(root / "cases", metadata, runtime="local")
                ).evaluate_c_baseline("s1", "p1", "int main() {}")

            self.assertEqual(result["baseline_status"], "valid")
            self.assertEqual(result["c"], accepted_c)
            evaluate.assert_called_once()

    def test_evaluate_c_baseline_reports_missing_target_without_compilation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata = root / "metadata"
            metadata.mkdir()
            (metadata / "problem_list.csv").write_text(
                "id,name,dataset,time_limit,memory_limit,rating,tags,complexity\n",
                encoding="utf-8",
            )

            with patch("judge_comparison.evaluate_program") as evaluate:
                result = JudgeComparison(
                    JudgeProfile(root / "cases", metadata, runtime="local")
                ).evaluate_c_baseline("s1", "p1", "int main() {}")

            self.assertEqual(result["baseline_status"], "missing")
            self.assertEqual(result["c"]["judge"]["status"], "SKIPPED")
            evaluate.assert_not_called()

    def test_ignores_metadata_rows_without_limits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metadata = Path(temp_dir) / "metadata"
            metadata.mkdir()
            (metadata / "problem_list.csv").write_text(
                "id,name,dataset,time_limit,memory_limit,rating,tags,complexity\n"
                "p_missing,Missing,AIZU,,,,,\n"
                "p_valid,Valid,AIZU,1000,131072,,,\n",
                encoding="utf-8",
            )

            comparison = JudgeComparison(JudgeProfile(Path(temp_dir), metadata))

            self.assertNotIn("p_missing", comparison._limits)
            self.assertEqual(comparison._limits["p_valid"].time_limit_ms, 1000)
