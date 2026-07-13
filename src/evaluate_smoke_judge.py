"""Run the benchmark Judge comparison for an existing experiment."""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from judge_comparison import JudgeComparison, JudgeProfile


CSV_FIELDS = (
    "experiment_id",
    "evaluation_id",
    "snippet_id",
    "problem_id",
    "prompt_id",
    "baseline_status",
    "test_directory",
    "test_layout",
    "c_compile_status",
    "c_judge_status",
    "rust_compile_status",
    "rust_judge_status",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate C and Rust artifacts from one experiment.")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--evaluation-id", required=True)
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--judge-tests-root", required=True)
    parser.add_argument("--metadata-root", required=True)
    parser.add_argument("--judge-runtime", choices=("podman", "local"), default="podman")
    parser.add_argument("--c-judge-image", default="docker.io/library/gcc:5.4")
    parser.add_argument("--rust-judge-image", default="docker.io/library/rust:1.85.0-bookworm")
    parser.add_argument("--judge-compare-mode", default="ignore-spaces-and-newlines")
    return parser.parse_args()


def artifact_directory(experiment_dir: Path, row: dict) -> Path:
    translated_path = row.get("translated_code_path", "")
    if translated_path:
        return (experiment_dir / translated_path).parent
    return experiment_dir / "model_outputs" / row["snippet_id"] / row["prompt_id"]


def main(args: argparse.Namespace) -> None:
    experiment_dir = Path(args.output_root) / args.experiment_id
    evaluation_dir = experiment_dir / "judge_evaluations" / args.evaluation_id
    if evaluation_dir.exists():
        raise FileExistsError(f"Evaluation directory already exists: {evaluation_dir}")

    profile = JudgeProfile(
        tests_root=Path(args.judge_tests_root),
        metadata_root=Path(args.metadata_root),
        runtime=args.judge_runtime,
        c_image=args.c_judge_image,
        rust_image=args.rust_judge_image,
        compare_mode=args.judge_compare_mode,
    )
    comparison_runner = JudgeComparison(profile)
    with (experiment_dir / "results.csv").open(newline="", encoding="utf-8") as results_file:
        benchmark_rows = list(csv.DictReader(results_file))

    evaluation_dir.mkdir(parents=True)
    rows = []
    with (evaluation_dir / "runs.jsonl").open("w", encoding="utf-8") as runs_file:
        for benchmark_row in benchmark_rows:
            artifacts = artifact_directory(experiment_dir, benchmark_row)
            comparison = comparison_runner.evaluate(
                benchmark_row["snippet_id"],
                benchmark_row["problem_id"],
                (artifacts / "source.c").read_text(encoding="utf-8"),
                (artifacts / "translated.rs").read_text(encoding="utf-8"),
            )
            runs_file.write(json.dumps(comparison, ensure_ascii=False) + "\n")
            rows.append(
                {
                    "experiment_id": args.experiment_id,
                    "evaluation_id": args.evaluation_id,
                    "snippet_id": benchmark_row["snippet_id"],
                    "problem_id": benchmark_row["problem_id"],
                    "prompt_id": benchmark_row["prompt_id"],
                    "baseline_status": comparison["baseline_status"],
                    "test_directory": comparison["test_directory"],
                    "test_layout": comparison["test_layout"],
                    "c_compile_status": comparison["c"]["compile_status"],
                    "c_judge_status": comparison["c"]["judge"]["status"],
                    "rust_compile_status": comparison["rust"]["compile_status"],
                    "rust_judge_status": comparison["rust"]["judge"]["status"],
                }
            )

    with (evaluation_dir / "results.csv").open("w", newline="", encoding="utf-8") as results_file:
        writer = csv.DictWriter(results_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "experiment_id": args.experiment_id,
        "evaluation_id": args.evaluation_id,
        "runs": len(rows),
        "baseline_statuses": dict(Counter(row["baseline_status"] for row in rows)),
        "c_judge_statuses": dict(Counter(row["c_judge_status"] for row in rows)),
        "rust_judge_statuses": dict(Counter(row["rust_judge_status"] for row in rows)),
    }
    (evaluation_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Judge comparison complete. CSV: {evaluation_dir / 'results.csv'}")


if __name__ == "__main__":
    main(parse_args())
