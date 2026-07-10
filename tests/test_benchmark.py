import os
import tempfile
import unittest
from pathlib import Path

from benchmark import (
    Prompt,
    SourceProgram,
    build_csv_row,
    load_sources,
    select_sources,
    server_environment,
)


class BenchmarkSelectionTests(unittest.TestCase):
    def test_manifest_rejects_multiple_programs_for_one_problem(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "first.c").write_text("int main() {}", encoding="utf-8")
            (root / "second.c").write_text("int main() {}", encoding="utf-8")
            manifest = root / "sources.csv"
            manifest.write_text(
                "problem_id,source_file\np1,first.c\np1,second.c\n", encoding="utf-8"
            )

            with self.assertRaises(ValueError):
                load_sources(root, manifest)

    def test_selection_is_deterministic(self):
        sources = [SourceProgram(f"p{index}", Path(f"s{index}.c")) for index in range(10)]

        first = select_sources(sources, 4, 42)
        second = select_sources(sources, 4, 42)

        self.assertEqual(first, second)


class BenchmarkCsvTests(unittest.TestCase):
    def test_row_includes_each_judge_verdict_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_dir = root / "model_outputs" / "s1" / "direct"
            artifact_dir.mkdir(parents=True)
            source = SourceProgram("p1", root / "s1.c")
            prompt = Prompt("direct", "{c_code}", "hash")
            result = {
                "status": "success",
                "compile_status": "success",
                "test_metrics": {"status": "success", "total_tests": 2, "rust_passed": 2},
                "judge_result": {"status": "WRONG_ANSWER", "total": 3, "passed": 2, "failed": 1, "verdict_counts": {"WRONG_ANSWER": 1}},
                "execution_history": [],
            }

            row = build_csv_row(
                "experiment",
                source,
                prompt,
                type("Config", (), {"llm_provider": "openai", "llm_model": "model"})(),
                result,
                artifact_dir,
                root,
            )

            self.assertEqual(row["judge_wrong_answer_count"], 1)
            self.assertEqual(row["judge_accepted_count"], 0)


class BenchmarkProcessTests(unittest.TestCase):
    def test_server_inherits_the_resolved_config_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "gemini.yaml"
            config_path.write_text("provider: gemini\n", encoding="utf-8")
            config = type("Config", (), {"config_file": str(config_path)})()

            environment = server_environment(config)

            self.assertEqual(
                environment["OXCIDATION_CONFIG_FILE"],
                str(config_path.resolve()),
            )
            self.assertEqual(environment.get("PATH"), os.environ.get("PATH"))
