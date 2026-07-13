"""Run an isolated C-to-Rust prompt benchmark and export one CSV row per run."""

import argparse
import asyncio
import csv
import hashlib
import json
import logging
import os
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import ConfigDetails
from judge_comparison import JudgeComparison, JudgeProfile
from logger_setup import RunRecorder, configure_log_directory
from orchestrator import process_file

LOGGER = logging.getLogger(__name__)
PROMPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
VERDICTS = (
    "ACCEPTED",
    "WRONG_ANSWER",
    "TIME_LIMIT_EXCEEDED",
    "RUNTIME_ERROR",
    "MEMORY_LIMIT_EXCEEDED",
    "INFRA_ERROR",
)
CSV_FIELDS = (
    "experiment_id",
    "snippet_id",
    "problem_id",
    "source_file",
    "prompt_id",
    "prompt_sha256",
    "model_provider",
    "model_id",
    "final_status",
    "failure_category",
    "compile_status",
    "visible_test_status",
    "visible_cases_total",
    "visible_cases_passed",
    "baseline_status",
    "baseline_test_layout",
    "baseline_c_compile_status",
    "baseline_c_judge_status",
    "judge_status",
    "judge_cases_total",
    "judge_cases_passed",
    "judge_cases_failed",
    "judge_first_failure_case",
    "judge_first_failure_verdict",
    "repair_attempts",
    "duration_seconds",
    "prompt_tokens",
    "completion_tokens",
    "raw_output_path",
    "translation_reasoning_path",
    "test_report_path",
    "validator_report_path",
    "translated_code_path",
    "result_path",
) + tuple(f"judge_{verdict.lower()}_count" for verdict in VERDICTS)


@dataclass(frozen=True)
class Prompt:
    prompt_id: str
    template: str
    sha256: str


@dataclass(frozen=True)
class SourceProgram:
    problem_id: str
    path: Path


def load_prompts(prompt_dir: Path) -> list[Prompt]:
    prompt_paths = sorted(prompt_dir.glob("*.txt"))
    if not prompt_paths:
        raise ValueError(f"No .txt prompts found in {prompt_dir}.")

    prompts = []
    for path in prompt_paths:
        if not PROMPT_ID_RE.fullmatch(path.stem):
            raise ValueError(f"Invalid prompt identifier: {path.stem}")
        template = path.read_text(encoding="utf-8")
        if "{c_code}" not in template:
            raise ValueError(f"Prompt {path} must contain the {{c_code}} placeholder.")
        prompts.append(
            Prompt(
                prompt_id=path.stem,
                template=template,
                sha256=hashlib.sha256(template.encode("utf-8")).hexdigest(),
            )
        )
    return prompts


def load_sources(input_dir: Path, source_manifest: Path | None) -> list[SourceProgram]:
    if source_manifest is None:
        return [SourceProgram(path.stem, path) for path in sorted(input_dir.glob("*.c"))]

    with source_manifest.open(newline="", encoding="utf-8") as manifest_file:
        reader = csv.DictReader(manifest_file)
        required_columns = {"problem_id", "source_file"}
        if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
            raise ValueError("Source manifest must contain problem_id and source_file columns.")
        sources = []
        for row in reader:
            problem_id = row["problem_id"].strip()
            source_file = Path(row["source_file"].strip())
            source_path = source_file if source_file.is_absolute() else input_dir / source_file
            if not problem_id or source_path.suffix != ".c" or not source_path.is_file():
                raise ValueError(f"Invalid source manifest row: {row}")
            sources.append(SourceProgram(problem_id, source_path))

    problem_ids = [source.problem_id for source in sources]
    if len(problem_ids) != len(set(problem_ids)):
        raise ValueError("Source manifest must contain exactly one C program per problem_id.")
    return sorted(sources, key=lambda source: (source.problem_id, source.path.name))


def select_sources(sources: list[SourceProgram], sample_size: int, seed: int) -> list[SourceProgram]:
    if sample_size <= 0:
        raise ValueError("Sample size must be greater than zero.")
    if len(sources) < sample_size:
        raise ValueError(
            f"Requested {sample_size} programs, but the population contains only {len(sources)} C files."
        )
    return sorted(
        random.Random(seed).sample(sources, sample_size),
        key=lambda source: (source.problem_id, source.path.name),
    )


def create_experiment_dir(root_dir: Path, experiment_id: str) -> Path:
    if not PROMPT_ID_RE.fullmatch(experiment_id):
        raise ValueError("Experiment id may contain only letters, numbers, dots, underscores, and hyphens.")
    experiment_dir = root_dir / experiment_id
    if experiment_dir.exists() and any(experiment_dir.iterdir()):
        raise FileExistsError(
            f"Experiment directory already exists: {experiment_dir}. Choose a new id to avoid mixing results."
        )
    experiment_dir.mkdir(parents=True, exist_ok=True)
    return experiment_dir


def write_manifest(
    experiment_dir: Path,
    experiment_id: str,
    sources: list[SourceProgram],
    prompts: list[Prompt],
    seed: int,
    configs: ConfigDetails,
    judge_profile: JudgeProfile | None,
) -> None:
    manifest = {
        "experiment_id": experiment_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "unit_of_analysis": "one accepted C program per problem",
        "sampling": {
            "confidence_level": 0.95,
            "margin_of_error": 0.05,
            "seed": seed,
            "sample_size": len(sources),
            "selected_sources": [
                {"problem_id": source.problem_id, "source_file": str(source.path)}
                for source in sources
            ],
        },
        "model": {"provider": configs.llm_provider, "id": configs.llm_model},
        "pipeline": {
            "config_file": configs.config_file,
            "max_repair_attempts": configs.max_repair_attempts,
            "request_rate_limit_rpm": configs.request_rate_limit_rpm,
            "judge_backend": configs.judge_backend,
            "visible_test_time_limit_sec": configs.visible_test_time_limit_sec,
            "judge_compare_mode": configs.judge_compare_mode,
        },
        "judge_comparison": (
            None
            if judge_profile is None
            else {
                "runtime": judge_profile.runtime,
                "c_image": judge_profile.c_image,
                "rust_image": judge_profile.rust_image,
                "backend": judge_profile.backend,
                "compare_mode": judge_profile.compare_mode,
                "tests_root": str(judge_profile.tests_root),
                "metadata_root": str(judge_profile.metadata_root),
                "c_compile_command": "gcc -O2 -pipe source.c -o program -lm",
                "rust_compile_command": "rustc -O source.rs -o program",
                "stack_policy": "problem_memory_limit",
            }
        ),
        "prompts": [
            {
                "prompt_id": prompt.prompt_id,
                "sha256": prompt.sha256,
                "template": prompt.template,
            }
            for prompt in prompts
        ],
    }
    (experiment_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_csv_row(writer: csv.DictWriter, row: dict) -> None:
    writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def build_csv_row(
    experiment_id: str,
    source: SourceProgram,
    prompt: Prompt,
    configs: ConfigDetails,
    result: dict,
    artifact_dir: Path,
    experiment_dir: Path,
) -> dict:
    visible = result.get("test_metrics", {})
    baseline = result.get("baseline_judge", {})
    baseline_c = baseline.get("c", {})
    judge = result.get("judge_result", {})
    verdict_counts = judge.get("verdict_counts", {})
    first_failure = judge.get("first_failure", {})
    totals = result.get("execution_history", [])

    row = {
        "experiment_id": experiment_id,
        "snippet_id": source.path.stem,
        "problem_id": source.problem_id,
        "source_file": str(source.path),
        "prompt_id": prompt.prompt_id,
        "prompt_sha256": prompt.sha256,
        "model_provider": configs.llm_provider,
        "model_id": configs.llm_model,
        "final_status": result.get("status", "failed"),
        "failure_category": result.get("failure_category", "infrastructure"),
        "compile_status": result.get("compile_status", "not_reached"),
        "visible_test_status": visible.get("status", "not_reached"),
        "visible_cases_total": visible.get("total_tests", 0),
        "visible_cases_passed": visible.get("rust_passed", 0),
        "baseline_status": baseline.get("baseline_status", "not_configured"),
        "baseline_test_layout": baseline.get("test_layout", ""),
        "baseline_c_compile_status": baseline_c.get("compile_status", "not_run"),
        "baseline_c_judge_status": baseline_c.get("judge", {}).get("status", "not_run"),
        "judge_status": judge.get("status", "not_reached"),
        "judge_cases_total": judge.get("total", 0),
        "judge_cases_passed": judge.get("passed", 0),
        "judge_cases_failed": judge.get("failed", 0),
        "judge_first_failure_case": first_failure.get("case", ""),
        "judge_first_failure_verdict": first_failure.get("verdict", ""),
        "repair_attempts": result.get("repair_count", 0),
        "duration_seconds": round(sum(step["duration_sec"] for step in totals), 3),
        "prompt_tokens": sum(step.get("prompt_tokens", 0) for step in totals),
        "completion_tokens": sum(step.get("completion_tokens", 0) for step in totals),
        "raw_output_path": str((artifact_dir / "raw_response.txt").relative_to(experiment_dir)),
        "translation_reasoning_path": str(
            (artifact_dir / "translation_reasoning.txt").relative_to(experiment_dir)
        ),
        "test_report_path": str((artifact_dir / "test_report.json").relative_to(experiment_dir)),
        "validator_report_path": str(
            (artifact_dir / "validator_report.json").relative_to(experiment_dir)
        ),
        "translated_code_path": str((artifact_dir / "translated.rs").relative_to(experiment_dir)),
        "result_path": str((artifact_dir / "result.json").relative_to(experiment_dir)),
    }
    for verdict in VERDICTS:
        row[f"judge_{verdict.lower()}_count"] = verdict_counts.get(verdict, 0)
    return row


def write_artifacts(artifact_dir: Path, source: SourceProgram, result: dict) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "source.c").write_text(source.path.read_text(encoding="utf-8"), encoding="utf-8")
    (artifact_dir / "raw_response.txt").write_text(
        result.get("raw_model_output", ""), encoding="utf-8"
    )
    (artifact_dir / "translation_reasoning.txt").write_text(
        result.get("translation_reasoning", ""), encoding="utf-8"
    )
    (artifact_dir / "test_report.json").write_text(
        json.dumps(result.get("test_metrics", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "validator_report.json").write_text(
        json.dumps(result.get("validator_report", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "judge_comparison.json").write_text(
        json.dumps(result.get("baseline_judge", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "translated.rs").write_text(result.get("rust_code", ""), encoding="utf-8")
    (artifact_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def summarize(rows: list[dict]) -> dict:
    by_prompt: dict[str, dict] = defaultdict(
        lambda: {
            "runs": 0,
            "final_status": Counter(),
            "judge_status": Counter(),
            "judge_verdict_counts": Counter(),
            "baseline_status": Counter(),
            "baseline_c_judge_status": Counter(),
        }
    )
    for row in rows:
        summary = by_prompt[row["prompt_id"]]
        summary["runs"] += 1
        summary["final_status"][row["final_status"]] += 1
        summary["judge_status"][row["judge_status"]] += 1
        summary["baseline_status"][row["baseline_status"]] += 1
        summary["baseline_c_judge_status"][row["baseline_c_judge_status"]] += 1
        for verdict in VERDICTS:
            summary["judge_verdict_counts"][verdict] += int(row[f"judge_{verdict.lower()}_count"])
    return {
        "total_runs": len(rows),
        "by_prompt": {
            prompt_id: {
                key: dict(value) if isinstance(value, Counter) else value
                for key, value in values.items()
            }
            for prompt_id, values in by_prompt.items()
        },
    }


def server_environment(configs: ConfigDetails) -> dict[str, str]:
    environment = os.environ.copy()
    environment["OXCIDATION_CONFIG_FILE"] = str(Path(configs.config_file).resolve())
    return environment


def build_judge_comparison(args: argparse.Namespace, configs: ConfigDetails) -> JudgeComparison | None:
    configured_values = (args.judge_tests_root, args.metadata_root)
    if not any(configured_values):
        return None
    if not all(configured_values):
        raise ValueError("--judge-tests-root and --metadata-root must be provided together.")
    profile = JudgeProfile(
        tests_root=Path(args.judge_tests_root),
        metadata_root=Path(args.metadata_root),
        runtime=args.judge_runtime,
        c_image=args.c_judge_image,
        rust_image=args.rust_judge_image,
        backend=configs.judge_backend,
        compare_mode=configs.judge_compare_mode,
    )
    return JudgeComparison(profile)


async def run_benchmark(args: argparse.Namespace) -> None:
    input_dir = Path(args.input_dir)
    prompt_dir = Path(args.prompts_dir)
    root_dir = Path(args.output_root)
    prompts = load_prompts(prompt_dir)
    source_manifest = Path(args.source_manifest) if args.source_manifest else None
    population = load_sources(input_dir, source_manifest)
    sources = select_sources(population, args.sample_size, args.seed)
    configs = ConfigDetails()
    judge_comparison = build_judge_comparison(args, configs)
    experiment_dir = create_experiment_dir(root_dir, args.experiment_id)
    write_manifest(
        experiment_dir,
        args.experiment_id,
        sources,
        prompts,
        args.seed,
        configs,
        judge_comparison.profile if judge_comparison else None,
    )
    configure_log_directory(str(experiment_dir / "logs"))

    csv_path = experiment_dir / "results.csv"
    recorder = RunRecorder(str(experiment_dir / "runs.jsonl"))
    rows = []
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["src/server.py"],
        env=server_environment(configs),
    )

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        csv_file.flush()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for source in sources:
                    for prompt in prompts:
                        artifact_dir = (
                            experiment_dir / "model_outputs" / source.path.stem / prompt.prompt_id
                        )
                        LOGGER.info("Benchmarking %s with prompt %s", source.path.name, prompt.prompt_id)
                        result = await process_file(
                            str(source.path),
                            session,
                            recorder,
                            output_path=str(artifact_dir / "translated.rs"),
                            prompt_id=prompt.prompt_id,
                            prompt_template=prompt.template,
                            record_metadata={
                                "experiment_id": args.experiment_id,
                                "snippet_id": source.path.stem,
                                "problem_id": source.problem_id,
                                "source_file": str(source.path),
                                "prompt_sha256": prompt.sha256,
                                "model_provider": configs.llm_provider,
                                "model_id": configs.llm_model,
                            },
                            problem_id=source.problem_id,
                            judge_comparison=judge_comparison,
                        )
                        write_artifacts(artifact_dir, source, result)
                        row = build_csv_row(
                            args.experiment_id,
                            source,
                            prompt,
                            configs,
                            result,
                            artifact_dir,
                            experiment_dir,
                        )
                        write_csv_row(writer, row)
                        csv_file.flush()
                        rows.append(row)

    (experiment_dir / "summary.json").write_text(
        json.dumps(summarize(rows), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    LOGGER.info("Benchmark complete. CSV: %s", csv_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an isolated prompt benchmark.")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--input-dir", default="data/processed/input_c_files")
    parser.add_argument(
        "--source-manifest",
        help="CSV with problem_id and source_file, required for one-program-per-problem sampling.",
    )
    parser.add_argument("--prompts-dir", default="prompts/benchmark")
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--sample-size", type=int, default=324)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--judge-tests-root",
        help="Judge case root, with directories keyed by submission_id or problem_id.",
    )
    parser.add_argument(
        "--metadata-root",
        help="CodeNet metadata directory containing problem_list.csv.",
    )
    parser.add_argument("--judge-runtime", choices=("podman", "local"), default="podman")
    parser.add_argument("--c-judge-image", default="docker.io/library/gcc:5.4")
    parser.add_argument("--rust-judge-image", default="docker.io/library/rust:1.85.0-bookworm")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run_benchmark(parse_args()))
