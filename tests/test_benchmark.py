import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from benchmark import (
    Prompt,
    SourceProgram,
    filter_judge_eligible_sources,
    load_sources,
    prepare_visible_suite,
    resolve_dataset_paths,
    select_prompts,
    select_sources,
    server_environment,
)
from benchmark_reporting import (
    build_result_row,
    extract_attempts,
    summarize,
    write_artifacts,
)


class BenchmarkSelectionTests(unittest.TestCase):
    def test_selects_only_requested_prompt_ids(self):
        prompts = [
            Prompt("direct", "{c_code}", "direct-hash"),
            Prompt("research", "{c_code}", "research-hash"),
        ]

        self.assertEqual(
            select_prompts(prompts, ["research"]),
            [prompts[1]],
        )
        with self.assertRaisesRegex(ValueError, "Unknown prompt IDs: missing"):
            select_prompts(prompts, ["missing"])

    def test_dataset_root_resolves_the_standard_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data").mkdir()
            (root / "metadata").mkdir()
            (root / "judge_tests").mkdir()
            manifest = root / "manifests" / "aoj_problem_mapping"
            manifest.mkdir(parents=True)
            (manifest / "benchmark_population.csv").write_text(
                "problem_id,source_file\n",
                encoding="utf-8",
            )
            args = SimpleNamespace(
                dataset_root=str(root),
                input_dir=None,
                source_manifest=None,
                judge_tests_root=None,
                metadata_root=None,
            )

            paths = resolve_dataset_paths(args)

            self.assertEqual(paths.input_dir, root / "data")
            self.assertEqual(paths.metadata_root, root / "metadata")
            self.assertEqual(paths.judge_tests_root, root / "judge_tests")
            self.assertEqual(
                paths.source_manifest,
                manifest / "benchmark_population.csv",
            )

    def test_dataset_root_rejects_an_incomplete_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(
                dataset_root=temp_dir,
                input_dir=None,
                source_manifest=None,
                judge_tests_root=None,
                metadata_root=None,
            )

            with self.assertRaisesRegex(ValueError, "Invalid --dataset-root layout"):
                resolve_dataset_paths(args)

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

    def test_judge_filter_runs_before_sampling(self):
        sources = [SourceProgram(f"p{index}", Path(f"s{index}.c")) for index in range(4)]
        judge = _JudgeCoverage({("s1", "p1"), ("s3", "p3")})

        eligible = filter_judge_eligible_sources(sources, judge)
        selected = select_sources(eligible, 2, 42)

        self.assertEqual({source.problem_id for source in selected}, {"p1", "p3"})


class BenchmarkCsvTests(unittest.TestCase):
    def test_attempt_keeps_initial_and_final_judge_results_separate(self):
        result = {
            "repair_count": 0,
            "agent_interactions": [
                {
                    "sequence": 1,
                    "action": "translation",
                    "repair_count": 0,
                    "data": {
                        "status": "in_progress",
                        "rust_code": "fn main() {}",
                    },
                },
                {
                    "sequence": 2,
                    "action": "initial_judge_evaluation",
                    "repair_count": 0,
                    "data": {
                        "judge_result": {
                            "status": "WRONG_ANSWER",
                            "total": 2,
                            "passed": 1,
                            "failed": 1,
                        }
                    },
                },
                {
                    "sequence": 3,
                    "action": "judge_evaluation",
                    "repair_count": 0,
                    "data": {
                        "judge_result": {
                            "status": "WRONG_ANSWER",
                            "total": 2,
                            "passed": 1,
                            "failed": 1,
                        }
                    },
                },
            ],
        }

        attempt = extract_attempts(result)[0]

        self.assertEqual(attempt["translation_status"], "success")
        self.assertEqual(attempt["initial_judge_status"], "WRONG_ANSWER")
        self.assertEqual(attempt["final_judge_status"], "WRONG_ANSWER")

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
                "visible_test_suite": {
                    "status": "ready",
                    "source": "generated",
                    "candidate_count": 3,
                    "case_count": 2,
                    "review_status": "approved",
                    "c_compile_profile": "gnu89-compat",
                    "review_count": 2,
                    "generation_attempt_count": 2,
                    "generated_candidate_count": 5,
                    "deterministic_rejection_count": 1,
                    "validator_replacement_count": 1,
                    "suite_sha256": "suite-hash",
                    "details": "",
                    "preparation_history_path": str(
                        root / "visible_tests" / "s1" / "preparation_history.json"
                    ),
                    "suite_dir": str(root / "visible_tests" / "s1" / "hash"),
                },
                "judge_result": {"status": "WRONG_ANSWER", "total": 3, "passed": 2, "failed": 1, "verdict_counts": {"WRONG_ANSWER": 1}},
                "execution_history": [],
                "validator_report": {"status": "not_required"},
                "agent_interactions": [
                    {
                        "sequence": 1,
                        "agent": "validator",
                        "action": "semantic_analysis",
                        "repair_count": 0,
                        "data": {
                            "validator_report": {
                                "status": "completed",
                                "test_assessment": "invalid_visible_test",
                            }
                        },
                    },
                    {
                        "sequence": 2,
                        "agent": "validator",
                        "action": "semantic_analysis",
                        "repair_count": 1,
                        "data": {"validator_report": {"status": "not_required"}},
                    },
                ],
            }

            row = build_result_row(
                "experiment",
                source,
                prompt,
                type("Config", (), {"llm_provider": "openai", "llm_model": "model"})(),
                result,
                artifact_dir,
                root,
                1,
                1,
            )

            self.assertEqual(row["judge_wrong_answer_count"], 1)
            self.assertEqual(row["judge_accepted_count"], 0)
            self.assertEqual(row["visible_suite_cases"], 2)
            self.assertEqual(row["visible_suite_review_status"], "approved")
            self.assertEqual(
                row["visible_suite_c_compile_profile"],
                "gnu89-compat",
            )
            self.assertEqual(row["visible_suite_generation_attempts"], 2)
            self.assertEqual(row["visible_suite_review_count"], 2)
            self.assertEqual(row["visible_suite_generated_candidates"], 5)
            self.assertEqual(row["visible_suite_deterministic_rejections"], 1)
            self.assertEqual(row["visible_suite_validator_replacements"], 1)
            self.assertEqual(row["visible_suite_sha256"], "suite-hash")
            self.assertEqual(row["visible_suite_details"], "")
            self.assertEqual(
                row["visible_suite_preparation_history_path"],
                "visible_tests/s1/preparation_history.json",
            )
            self.assertEqual(row["visible_suite_path"], "visible_tests/s1/hash")
            self.assertEqual(row["validator_completed_analysis_count"], 1)
            self.assertEqual(row["validator_invalid_visible_test_count"], 1)
            summary = summarize([row])["by_prompt"]["direct"]
            self.assertEqual(summary["validator_completed_analyses"], 1)
            self.assertEqual(summary["validator_invalid_visible_tests"], 1)
            suite_summary = summarize([row])["visible_suite_population"]
            self.assertEqual(suite_summary["programs"], 1)
            self.assertEqual(suite_summary["regenerated"], 1)
            self.assertEqual(suite_summary["reviews"], 2)
            self.assertEqual(suite_summary["generated_candidates"], 5)
            self.assertEqual(suite_summary["deterministic_rejections"], 1)
            self.assertEqual(suite_summary["validator_replacements"], 1)
            self.assertEqual(suite_summary["approved_cases"], 2)

            source.path.write_text("int main() {}", encoding="utf-8")
            write_artifacts(artifact_dir, source, result)
            interactions = json.loads(
                (artifact_dir / "agent_interactions.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                interactions[0]["data"]["validator_report"]["status"],
                "completed",
            )


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

    def test_operational_visible_preparation_failure_stops_the_benchmark(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "sample.c"
            source_path.write_text("int main(void) { return 0; }", encoding="utf-8")
            source = SourceProgram("p1", source_path)
            session = _VisiblePreparationSession(
                {
                    "status": "review_failed",
                    "details": "Visible-test review failed: provider unavailable.",
                }
            )

            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                asyncio.run(prepare_visible_suite(session, source, root))


class _VisiblePreparationSession:
    def __init__(self, payload):
        self.payload = payload

    async def call_tool(self, tool_name, arguments):
        self.tool_name = tool_name
        self.arguments = arguments
        return SimpleNamespace(
            content=[SimpleNamespace(text=json.dumps(self.payload))],
            isError=False,
        )


class _JudgeCoverage:
    def __init__(self, covered):
        self.covered = covered

    def can_evaluate(self, snippet_id, problem_id):
        return (snippet_id, problem_id) in self.covered
