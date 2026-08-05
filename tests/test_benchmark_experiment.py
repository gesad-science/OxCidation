import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from benchmark import Prompt, SourceProgram
from benchmark_experiment import (
    REQUIRED_ARTIFACTS,
    completed_result_rows,
    prepare_experiment_dir,
    schedule_runs,
)


class BenchmarkScheduleTests(unittest.TestCase):
    def test_prompt_order_is_deterministic_and_varies_by_program(self):
        sources = [
            SourceProgram("p1", Path("s1.c")),
            SourceProgram("p2", Path("s2.c")),
        ]
        prompts = [
            Prompt(f"prompt-{index}", "{c_code}", str(index))
            for index in range(6)
        ]

        first = schedule_runs(sources, prompts, 42)
        second = schedule_runs(sources, prompts, 42)

        self.assertEqual(first, second)
        self.assertNotEqual(
            [item.prompt.prompt_id for item in first[:6]],
            [item.prompt.prompt_id for item in first[6:]],
        )
        self.assertEqual(
            [item.execution_order for item in first],
            list(range(1, 13)),
        )


class BenchmarkResumeTests(unittest.TestCase):
    def test_resume_rejects_a_different_manifest_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            experiment = root / "experiment"
            experiment.mkdir()
            (experiment / "manifest.json").write_text(
                json.dumps({"resume_identity_sha256": "original"}),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                prepare_experiment_dir(
                    root,
                    "experiment",
                    {"resume_identity_sha256": "changed"},
                    resume=True,
                )

    def test_completed_row_requires_all_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            experiment = Path(temp_dir)
            artifact_dir = experiment / "model_outputs" / "s1" / "p1"
            artifact_dir.mkdir(parents=True)
            row = {
                "snippet_id": "s1",
                "prompt_id": "p1",
                "result_path": "model_outputs/s1/p1/result.json",
            }
            (artifact_dir / "result.json").write_text(
                json.dumps(
                    {"prompt_id": "p1", "agent_interactions": []}
                ),
                encoding="utf-8",
            )

            self.assertEqual(completed_result_rows(experiment, [row]), {})

    def test_completed_row_accepts_consistent_result_and_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            experiment = Path(temp_dir)
            artifact_dir = experiment / "model_outputs" / "s1" / "p1"
            artifact_dir.mkdir(parents=True)
            result = {
                "prompt_id": "p1",
                "status": "success",
                "judge_result": {"status": "ACCEPTED"},
                "repair_count": 0,
                "rust_code": "fn main() {}",
                "agent_interactions": [],
            }
            for name in REQUIRED_ARTIFACTS:
                (artifact_dir / name).write_text("", encoding="utf-8")
            (artifact_dir / "translated.rs").write_text(
                result["rust_code"], encoding="utf-8"
            )
            (artifact_dir / "result.json").write_text(
                json.dumps(result), encoding="utf-8"
            )
            row = {
                "snippet_id": "s1",
                "prompt_id": "p1",
                "final_status": "success",
                "judge_status": "ACCEPTED",
                "repair_attempts": "0",
                "result_path": "model_outputs/s1/p1/result.json",
            }

            self.assertEqual(
                completed_result_rows(experiment, [row]),
                {("s1", "p1"): row},
            )
