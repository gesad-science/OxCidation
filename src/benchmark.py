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
from dataclasses import dataclass
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agents import TesterAgent
from benchmark_experiment import (
    build_manifest,
    completed_result_rows,
    prepare_experiment_dir,
    record_resume,
    schedule_runs,
)
from benchmark_reporting import (
    ATTEMPT_FIELDS,
    RESULT_FIELDS,
    build_attempt_rows,
    build_result_row,
    read_csv,
    summarize,
    write_artifacts,
    write_csv,
)
from config import ConfigDetails
from judge_comparison import JudgeComparison, JudgeProfile
from logger_setup import RunRecorder, configure_log_directory
from orchestrator import process_file
from review_workbook import generate_review_workbook
from visible_testing import OPERATIONAL_PREPARATION_STATUSES

LOGGER = logging.getLogger(__name__)
PROMPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
DEFAULT_INPUT_DIR = Path("data/processed/input_c_files")
DATASET_SOURCE_DIR = Path("data")
DATASET_METADATA_DIR = Path("metadata")
DATASET_MANIFEST_PATH = Path("manifests/aoj_problem_mapping/benchmark_population.csv")
DATASET_JUDGE_TESTS_DIR = Path("judge_tests")


@dataclass(frozen=True)
class Prompt:
    prompt_id: str
    template: str
    sha256: str


@dataclass(frozen=True)
class SourceProgram:
    problem_id: str
    path: Path


@dataclass(frozen=True)
class DatasetPaths:
    input_dir: Path
    source_manifest: Path | None
    judge_tests_root: Path | None
    metadata_root: Path | None


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


def select_prompts(prompts: list[Prompt], prompt_ids: list[str] | None) -> list[Prompt]:
    if not prompt_ids:
        return prompts

    requested = set(prompt_ids)
    available = {prompt.prompt_id for prompt in prompts}
    unknown = sorted(requested - available)
    if unknown:
        raise ValueError(f"Unknown prompt IDs: {', '.join(unknown)}.")
    return [prompt for prompt in prompts if prompt.prompt_id in requested]


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


def filter_judge_eligible_sources(
    sources: list[SourceProgram],
    judge_comparison: JudgeComparison,
) -> list[SourceProgram]:
    return [
        source
        for source in sources
        if judge_comparison.can_evaluate(source.path.stem, source.problem_id)
    ]


def resolve_dataset_paths(args: argparse.Namespace) -> DatasetPaths:
    if not args.dataset_root:
        return DatasetPaths(
            input_dir=Path(args.input_dir) if args.input_dir else DEFAULT_INPUT_DIR,
            source_manifest=(
                Path(args.source_manifest) if args.source_manifest else None
            ),
            judge_tests_root=(
                Path(args.judge_tests_root) if args.judge_tests_root else None
            ),
            metadata_root=Path(args.metadata_root) if args.metadata_root else None,
        )

    root = Path(args.dataset_root)
    paths = DatasetPaths(
        input_dir=Path(args.input_dir) if args.input_dir else root / DATASET_SOURCE_DIR,
        source_manifest=(
            Path(args.source_manifest)
            if args.source_manifest
            else root / DATASET_MANIFEST_PATH
        ),
        judge_tests_root=(
            Path(args.judge_tests_root)
            if args.judge_tests_root
            else root / DATASET_JUDGE_TESTS_DIR
        ),
        metadata_root=(
            Path(args.metadata_root)
            if args.metadata_root
            else root / DATASET_METADATA_DIR
        ),
    )
    expected_paths = {
        "C sources": paths.input_dir,
        "source manifest": paths.source_manifest,
        "Judge tests": paths.judge_tests_root,
        "metadata": paths.metadata_root,
    }
    missing = [
        f"{label} ({path})"
        for label, path in expected_paths.items()
        if path is not None and not path.exists()
    ]
    if missing:
        raise ValueError(
            "Invalid --dataset-root layout; missing " + ", ".join(missing) + "."
        )
    return paths


def server_environment(configs: ConfigDetails) -> dict[str, str]:
    environment = os.environ.copy()
    environment["OXCIDATION_CONFIG_FILE"] = str(Path(configs.config_file).resolve())
    return environment


async def prepare_visible_suite(
    session: ClientSession,
    source: SourceProgram,
    experiment_dir: Path,
) -> dict:
    test_root = experiment_dir / "visible_tests" / source.path.stem
    try:
        suite = await TesterAgent(session).prepare_suite(
            source.path.read_text(encoding="utf-8"),
            str(test_root),
        )
    except Exception as error:
        raise RuntimeError(
            f"Visible-test preparation failed for {source.path.name}: {error}"
        ) from error

    if suite.get("status") in OPERATIONAL_PREPARATION_STATUSES:
        raise RuntimeError(
            f"Visible-test preparation failed for {source.path.name}: "
            f"{suite.get('details', suite['status'])}"
        )
    return suite


def build_judge_comparison(
    dataset_paths: DatasetPaths,
    args: argparse.Namespace,
    configs: ConfigDetails,
) -> JudgeComparison | None:
    configured_values = (
        dataset_paths.judge_tests_root,
        dataset_paths.metadata_root,
    )
    if not any(configured_values):
        return None
    if not all(configured_values):
        raise ValueError("--judge-tests-root and --metadata-root must be provided together.")
    profile = JudgeProfile(
        tests_root=dataset_paths.judge_tests_root,
        metadata_root=dataset_paths.metadata_root,
        runtime=args.judge_runtime,
        c_image=args.c_judge_image,
        rust_image=args.rust_judge_image,
        backend=configs.judge_backend,
        compare_mode=configs.judge_compare_mode,
    )
    return JudgeComparison(profile)


def _sorted_result_rows(rows) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: (
            row.get("problem_id", ""),
            row.get("snippet_id", ""),
            row.get("prompt_id", ""),
        ),
    )


def _sorted_attempt_rows(rows) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: (
            row.get("problem_id", ""),
            row.get("snippet_id", ""),
            row.get("prompt_id", ""),
            int(row.get("attempt_number", 0)),
        ),
    )


def _finalize_reports(experiment_dir: Path, rows: list[dict]) -> None:
    csv_path = experiment_dir / "results.csv"
    (experiment_dir / "summary.json").write_text(
        json.dumps(summarize(rows), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    workbook_path = generate_review_workbook(experiment_dir)
    LOGGER.info("Benchmark complete. CSV: %s", csv_path)
    LOGGER.info("Review workbook: %s", workbook_path)


async def run_benchmark(args: argparse.Namespace) -> None:
    dataset_paths = resolve_dataset_paths(args)
    input_dir = dataset_paths.input_dir
    prompt_dir = Path(args.prompts_dir)
    root_dir = Path(args.output_root)
    prompts = select_prompts(load_prompts(prompt_dir), args.prompt_id)
    source_manifest = dataset_paths.source_manifest
    population = load_sources(input_dir, source_manifest)
    configs = ConfigDetails()
    judge_comparison = build_judge_comparison(dataset_paths, args, configs)
    if judge_comparison is not None:
        population = filter_judge_eligible_sources(population, judge_comparison)
        LOGGER.info(
            "Judge-eligible population: %d programs with limits and test cases.",
            len(population),
        )
    sources = select_sources(population, args.sample_size, args.seed)
    manifest = build_manifest(
        args.experiment_id,
        sources,
        prompts,
        args.seed,
        configs,
        judge_comparison.profile if judge_comparison else None,
    )
    experiment_dir, resumed = prepare_experiment_dir(
        root_dir,
        args.experiment_id,
        manifest,
        args.resume,
    )
    configure_log_directory(str(experiment_dir / "logs"))

    csv_path = experiment_dir / "results.csv"
    attempts_csv_path = experiment_dir / "attempts.csv"
    recorder = RunRecorder(str(experiment_dir / "runs.jsonl"))
    schedule = schedule_runs(sources, prompts, args.seed)
    scheduled_keys = {
        (item.source.path.stem, item.prompt.prompt_id) for item in schedule
    }
    completed = {
        key: row
        for key, row in completed_result_rows(
            experiment_dir, read_csv(csv_path)
        ).items()
        if key in scheduled_keys
    }
    rows_by_key = dict(completed)
    attempt_rows = []
    for item in schedule:
        key = (item.source.path.stem, item.prompt.prompt_id)
        if key not in completed:
            continue
        artifact_dir = (
            experiment_dir
            / "model_outputs"
            / item.source.path.stem
            / item.prompt.prompt_id
        )
        saved_result = json.loads(
            (artifact_dir / "result.json").read_text(encoding="utf-8")
        )
        attempt_rows.extend(
            build_attempt_rows(
                completed[key],
                saved_result,
                artifact_dir,
                experiment_dir,
            )
        )
    if resumed:
        record_resume(
            experiment_dir,
            len(completed),
            len(schedule) - len(completed),
        )
        LOGGER.info(
            "Resuming %s: %d completed, %d pending.",
            args.experiment_id,
            len(completed),
            len(schedule) - len(completed),
        )
    write_csv(
        csv_path,
        RESULT_FIELDS,
        _sorted_result_rows(rows_by_key.values()),
    )
    write_csv(
        attempts_csv_path,
        ATTEMPT_FIELDS,
        _sorted_attempt_rows(attempt_rows),
    )
    if len(completed) == len(schedule):
        _finalize_reports(
            experiment_dir,
            _sorted_result_rows(rows_by_key.values()),
        )
        return

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["src/server.py"],
        env=server_environment(configs),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for source in sources:
                source_schedule = [
                    item
                    for item in schedule
                    if item.source == source
                    and (source.path.stem, item.prompt.prompt_id)
                    not in completed
                ]
                if not source_schedule:
                    continue

                visible_test_suite = await prepare_visible_suite(
                    session,
                    source,
                    experiment_dir,
                )
                for item in source_schedule:
                    prompt = item.prompt
                    key = (source.path.stem, prompt.prompt_id)
                    artifact_dir = (
                        experiment_dir
                        / "model_outputs"
                        / source.path.stem
                        / prompt.prompt_id
                    )
                    LOGGER.info(
                        "Benchmarking %s with prompt %s (%d/%d)",
                        source.path.name,
                        prompt.prompt_id,
                        item.prompt_position,
                        len(prompts),
                    )
                    result = await process_file(
                        str(source.path),
                        session,
                        recorder,
                        output_path=str(artifact_dir / "translated.rs"),
                        prompt_id=prompt.prompt_id,
                        prompt_template=prompt.template,
                        record_metadata={
                            "experiment_id": args.experiment_id,
                            "execution_order": item.execution_order,
                            "prompt_position": item.prompt_position,
                            "snippet_id": source.path.stem,
                            "problem_id": source.problem_id,
                            "source_file": str(source.path),
                            "prompt_sha256": prompt.sha256,
                            "model_provider": configs.llm_provider,
                            "model_id": configs.llm_model,
                        },
                        problem_id=source.problem_id,
                        judge_comparison=judge_comparison,
                        visible_tests_root=str(
                            experiment_dir / "visible_tests"
                        ),
                        visible_test_suite=visible_test_suite,
                    )
                    write_artifacts(artifact_dir, source, result)
                    row = build_result_row(
                        args.experiment_id,
                        source,
                        prompt,
                        configs,
                        result,
                        artifact_dir,
                        experiment_dir,
                        item.execution_order,
                        item.prompt_position,
                    )
                    rows_by_key[key] = row
                    attempt_rows = [
                        existing
                        for existing in attempt_rows
                        if (
                            existing.get("snippet_id"),
                            existing.get("prompt_id"),
                        )
                        != key
                    ]
                    attempt_rows.extend(
                        build_attempt_rows(
                            row,
                            result,
                            artifact_dir,
                            experiment_dir,
                        )
                    )
                    write_csv(
                        csv_path,
                        RESULT_FIELDS,
                        _sorted_result_rows(rows_by_key.values()),
                    )
                    write_csv(
                        attempts_csv_path,
                        ATTEMPT_FIELDS,
                        _sorted_attempt_rows(attempt_rows),
                    )

    rows = _sorted_result_rows(rows_by_key.values())
    _finalize_reports(experiment_dir, rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an isolated prompt benchmark.")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument(
        "--dataset-root",
        help=(
            "Dataset root containing data/, metadata/, "
            "manifests/aoj_problem_mapping/benchmark_population.csv, and judge_tests/."
        ),
    )
    parser.add_argument("--input-dir")
    parser.add_argument(
        "--source-manifest",
        help="CSV with problem_id and source_file, required for one-program-per-problem sampling.",
    )
    parser.add_argument("--prompts-dir", default="prompts/benchmark")
    parser.add_argument(
        "--prompt-id",
        action="append",
        help="Run only this prompt ID. Repeat to select multiple prompts.",
    )
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--sample-size", type=int, default=324)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted experiment after validating its manifest and artifacts.",
    )
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
