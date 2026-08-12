"""Experiment identity, scheduling, and resume support."""

import hashlib
import json
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from visible_testing import (
    PROMPT_PATH,
    REVIEW_PROMPT_PATH,
    load_generation_prompt,
    load_review_prompt,
    prompt_sha256,
)


IMPLEMENTATION_PATHS = (
    Path("llm_providers.py"),
    Path("src"),
)
REQUIRED_ARTIFACTS = (
    "source.c",
    "raw_response.txt",
    "translated.rs",
    "test_report.json",
    "validator_report.json",
    "agent_interactions.json",
    "attempts.json",
    "initial_judge_comparison.json",
    "judge_comparison.json",
    "result.json",
)
EXPERIMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class ScheduledRun:
    source: object
    prompt: object
    execution_order: int
    prompt_position: int


def build_manifest(
    experiment_id: str,
    sources: list,
    prompts: list,
    seed: int,
    configs,
    judge_profile,
) -> dict:
    visible_prompt = load_generation_prompt()
    visible_review_prompt = load_review_prompt()
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
                {
                    "problem_id": source.problem_id,
                    "source_file": str(source.path),
                    "source_sha256": _file_sha256(source.path),
                }
                for source in sources
            ],
        },
        "model": {
            "provider": configs.llm_provider,
            "id": configs.llm_model,
        },
        "visible_tests": {
            "input_context": "c_source_only",
            "generator_provider": configs.llm_provider,
            "generator_model": configs.llm_model,
            "prompt_path": str(PROMPT_PATH),
            "prompt_sha256": prompt_sha256(visible_prompt),
            "prompt_template": visible_prompt,
            "review_prompt_path": str(REVIEW_PROMPT_PATH),
            "review_prompt_sha256": prompt_sha256(visible_review_prompt),
            "review_prompt_template": visible_review_prompt,
            "oracle": "accepted_c_execution",
            "reuse_policy": "one_suite_per_c_program",
            "generation_attempt_limit": 2,
            "stability_executions_per_candidate": 2,
            "untrusted_evidence_policy": "no_translation_repair",
        },
        "pipeline": {
            "config_file": str(Path(configs.config_file).resolve()),
            "configuration": configs.config_data,
            "max_repair_attempts": configs.max_repair_attempts,
            "request_rate_limit_rpm": configs.request_rate_limit_rpm,
            "judge_backend": configs.judge_backend,
            "visible_test_time_limit_sec": configs.visible_test_time_limit_sec,
            "judge_compare_mode": configs.judge_compare_mode,
        },
        "judge_comparison": _judge_manifest(judge_profile),
        "prompts": [
            {
                "prompt_id": prompt.prompt_id,
                "sha256": prompt.sha256,
                "template": prompt.template,
            }
            for prompt in prompts
        ],
        "implementation": implementation_identity(),
    }
    manifest["resume_identity_sha256"] = _identity_sha256(manifest)
    return manifest


def _judge_manifest(profile) -> dict | None:
    if profile is None:
        return None
    return {
        "runtime": profile.runtime,
        "c_image": profile.c_image,
        "rust_image": profile.rust_image,
        "backend": profile.backend,
        "compare_mode": profile.compare_mode,
        "tests_root": str(profile.tests_root.resolve()),
        "metadata_root": str(profile.metadata_root.resolve()),
        "c_compile_command": "gcc -O2 -pipe source.c -o program -lm",
        "rust_compile_command": "rustc -O source.rs -o program",
        "stack_policy": "problem_memory_limit",
    }


def implementation_identity(root: Path | None = None) -> dict:
    root = root or Path(__file__).resolve().parent.parent
    files = []
    for configured_path in IMPLEMENTATION_PATHS:
        path = root / configured_path
        candidates = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_file():
                files.append(
                    {
                        "path": str(candidate.relative_to(root)),
                        "sha256": _file_sha256(candidate),
                    }
                )
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "files": files,
    }


def prepare_experiment_dir(
    root_dir: Path,
    experiment_id: str,
    manifest: dict,
    resume: bool,
) -> tuple[Path, bool]:
    if not EXPERIMENT_ID_RE.fullmatch(experiment_id):
        raise ValueError(
            "Experiment id may contain only letters, numbers, dots, "
            "underscores, and hyphens."
        )
    experiment_dir = root_dir / experiment_id
    manifest_path = experiment_dir / "manifest.json"

    if resume:
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"Cannot resume {experiment_dir}: manifest.json is missing."
            )
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("resume_identity_sha256") != manifest.get(
            "resume_identity_sha256"
        ):
            raise ValueError(
                "Cannot resume because sources, prompts, model, pipeline, Judge, "
                "or implementation files differ from the original manifest."
            )
        return experiment_dir, True

    if experiment_dir.exists() and any(experiment_dir.iterdir()):
        raise FileExistsError(
            f"Experiment directory already exists: {experiment_dir}. "
            "Choose a new id or pass --resume."
        )
    experiment_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return experiment_dir, False


def schedule_runs(sources: list, prompts: list, seed: int) -> list[ScheduledRun]:
    schedule = []
    execution_order = 0
    for source in sources:
        ordered_prompts = list(prompts)
        prompt_seed = hashlib.sha256(
            f"{seed}:{source.problem_id}:{source.path.stem}".encode("utf-8")
        ).digest()
        random.Random(prompt_seed).shuffle(ordered_prompts)
        for position, prompt in enumerate(ordered_prompts, start=1):
            execution_order += 1
            schedule.append(
                ScheduledRun(
                    source=source,
                    prompt=prompt,
                    execution_order=execution_order,
                    prompt_position=position,
                )
            )
    return schedule


def completed_result_rows(
    experiment_dir: Path,
    rows: list[dict],
) -> dict[tuple[str, str], dict]:
    completed = {}
    for row in rows:
        key = (row.get("snippet_id", ""), row.get("prompt_id", ""))
        if all(key) and _artifacts_complete(experiment_dir, row):
            completed[key] = row
    return completed


def _artifacts_complete(experiment_dir: Path, row: dict) -> bool:
    result_path = experiment_dir / row.get("result_path", "")
    artifact_dir = result_path.parent
    expected_dir = (
        experiment_dir
        / "model_outputs"
        / row.get("snippet_id", "")
        / row.get("prompt_id", "")
    )
    if artifact_dir != expected_dir or not result_path.is_file():
        return False
    if not all((artifact_dir / name).is_file() for name in REQUIRED_ARTIFACTS):
        return False
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    row_matches_result = (
        result.get("prompt_id") == row.get("prompt_id")
        and isinstance(result.get("agent_interactions"), list)
        and result.get("status", "failed") == row.get("final_status")
        and result.get("judge_result", {}).get("status", "not_reached")
        == row.get("judge_status")
        and str(result.get("repair_count", 0))
        == str(row.get("repair_attempts", ""))
    )
    if not row_matches_result:
        return False
    if row.get("visible_suite_source") == "generated":
        preparation_path = experiment_dir / row.get(
            "visible_suite_preparation_history_path", ""
        )
        if not preparation_path.is_file():
            return False
        if result.get("visible_test_suite", {}).get("suite_sha256", "") != row.get(
            "visible_suite_sha256", ""
        ):
            return False
    try:
        return (artifact_dir / "translated.rs").read_text(
            encoding="utf-8"
        ) == result.get("rust_code", "")
    except OSError:
        return False


def record_resume(
    experiment_dir: Path,
    completed_count: int,
    pending_count: int,
) -> None:
    record = {
        "resumed_at": datetime.now(timezone.utc).isoformat(),
        "completed_runs": completed_count,
        "pending_runs": pending_count,
    }
    with (experiment_dir / "resume_history.jsonl").open(
        "a", encoding="utf-8"
    ) as resume_file:
        resume_file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _identity_sha256(manifest: dict) -> str:
    identity = {
        key: value
        for key, value in manifest.items()
        if key not in {"created_at", "resume_identity_sha256"}
    }
    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
