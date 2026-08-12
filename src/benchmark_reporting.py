"""Artifacts and tabular reports for prompt benchmark experiments."""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


VERDICTS = (
    "ACCEPTED",
    "WRONG_ANSWER",
    "TIME_LIMIT_EXCEEDED",
    "RUNTIME_ERROR",
    "MEMORY_LIMIT_EXCEEDED",
    "INFRA_ERROR",
)

RESULT_FIELDS = (
    "experiment_id",
    "execution_order",
    "prompt_position",
    "review_id",
    "snippet_id",
    "problem_id",
    "source_file",
    "prompt_id",
    "prompt_sha256",
    "model_provider",
    "model_id",
    "initial_translation_status",
    "initial_compile_status",
    "initial_visible_test_status",
    "initial_judge_status",
    "initial_judge_cases_total",
    "initial_judge_cases_passed",
    "initial_judge_cases_failed",
    "final_status",
    "failure_category",
    "compile_status",
    "visible_test_status",
    "visible_suite_status",
    "visible_suite_source",
    "visible_suite_candidates",
    "visible_suite_cases",
    "visible_suite_review_status",
    "visible_suite_c_compile_profile",
    "visible_suite_generation_attempts",
    "visible_suite_generated_candidates",
    "visible_suite_rejected_candidates",
    "visible_suite_invalid_cases",
    "visible_suite_inconclusive_cases",
    "visible_suite_unresolved_replacements",
    "visible_suite_sha256",
    "visible_suite_details",
    "visible_suite_reused",
    "visible_suite_path",
    "visible_suite_preparation_history_path",
    "visible_generation_prompt_tokens",
    "visible_generation_completion_tokens",
    "visible_review_prompt_tokens",
    "visible_review_completion_tokens",
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
    "initial_code_path",
    "final_code_path",
    "test_report_path",
    "validator_report_path",
    "agent_interactions_path",
    "attempts_path",
    "validator_completed_analysis_count",
    "validator_invalid_visible_test_count",
    "validator_inconclusive_count",
    "result_path",
) + tuple(f"judge_{verdict.lower()}_count" for verdict in VERDICTS)

ATTEMPT_FIELDS = (
    "experiment_id",
    "execution_order",
    "review_id",
    "snippet_id",
    "problem_id",
    "prompt_id",
    "prompt_sha256",
    "attempt_number",
    "attempt_kind",
    "is_final",
    "code_path",
    "translation_status",
    "compile_status",
    "compiler_output_excerpt",
    "visible_test_status",
    "visible_cases_total",
    "visible_cases_passed",
    "visible_cases_failed",
    "visible_verdict_counts",
    "validator_status",
    "validator_test_assessment",
    "validator_diagnosis",
    "validator_repair_guidance",
    "repair_failure_category",
    "repair_feedback",
    "initial_judge_status",
    "initial_judge_cases_total",
    "initial_judge_cases_passed",
    "initial_judge_cases_failed",
    "final_judge_status",
    "final_judge_cases_total",
    "final_judge_cases_passed",
    "final_judge_cases_failed",
    "interaction_sequences",
    "agent_interactions_path",
)


def review_id(experiment_id: str, snippet_id: str, prompt_sha256: str) -> str:
    value = f"{experiment_id}:{snippet_id}:{prompt_sha256}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:16]


def extract_attempts(result: dict) -> list[dict]:
    attempts: dict[int, dict] = {}

    def attempt(number: int) -> dict:
        return attempts.setdefault(
            number,
            {
                "attempt_number": number,
                "attempt_kind": "initial" if number == 0 else "repair",
                "rust_code": "",
                "interaction_sequences": [],
            },
        )

    for interaction in result.get("agent_interactions", []):
        number = int(interaction.get("repair_count", 0))
        data = interaction.get("data", {})
        action = interaction.get("action")
        current = attempt(number)
        current["interaction_sequences"].append(interaction.get("sequence"))

        if action == "translation":
            current["rust_code"] = data.get("rust_code", "")
            translation_status = data.get("status", "")
            if translation_status == "in_progress" and current["rust_code"]:
                translation_status = "success"
            current["translation_status"] = translation_status
        elif action == "repair":
            current["rust_code"] = data.get("rust_code_after", "")
            current["repair_failure_category"] = data.get("failure_category", "")
            current["repair_feedback"] = data.get("feedback", "")
        elif action == "compilation":
            current["compile_status"] = data.get("status", "")
            current["compiler_output_excerpt"] = _excerpt(
                data.get("compiler_output", "")
            )
        elif action == "visible_test_report":
            report = data.get("test_report", {})
            current.update(
                {
                    "visible_test_status": report.get("status", ""),
                    "visible_cases_total": report.get("total_tests", 0),
                    "visible_cases_passed": report.get("rust_passed", 0),
                    "visible_cases_failed": report.get("rust_failed", 0),
                    "visible_verdict_counts": json.dumps(
                        report.get("verdict_counts", {}),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
        elif action == "semantic_analysis":
            report = data.get("validator_report", {})
            current.update(
                {
                    "validator_status": report.get("status", ""),
                    "validator_test_assessment": report.get(
                        "test_assessment", ""
                    ),
                    "validator_diagnosis": report.get("diagnosis", ""),
                    "validator_repair_guidance": report.get(
                        "repair_guidance", ""
                    ),
                }
            )
        elif action == "semantic_analysis_skipped":
            current["validator_status"] = "not_required"
        elif action == "initial_judge_evaluation":
            _add_judge(current, "initial", data.get("judge_result", {}))
        elif action == "judge_evaluation":
            _add_judge(current, "final", data.get("judge_result", {}))

    final_number = int(result.get("repair_count", 0))
    if not attempts:
        attempts[0] = {
            "attempt_number": 0,
            "attempt_kind": "initial",
            "rust_code": result.get("rust_code", ""),
            "interaction_sequences": [],
        }
    attempts.setdefault(final_number, attempt(final_number))
    attempts[final_number]["is_final"] = True
    for number, item in attempts.items():
        item.setdefault("is_final", number == final_number)
    return [attempts[number] for number in sorted(attempts)]


def _add_judge(attempt: dict, stage: str, judge: dict) -> None:
    attempt.update(
        {
            f"{stage}_judge_status": judge.get("status", ""),
            f"{stage}_judge_cases_total": judge.get("total", 0),
            f"{stage}_judge_cases_passed": judge.get("passed", 0),
            f"{stage}_judge_cases_failed": judge.get("failed", 0),
        }
    )


def _excerpt(value: str, limit: int = 500) -> str:
    value = value.strip()
    return value if len(value) <= limit else f"{value[:limit - 3]}..."


def experiment_relative_path(path: str | Path, experiment_dir: Path) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).relative_to(experiment_dir))
    except ValueError:
        return str(path)


def build_result_row(
    experiment_id: str,
    source,
    prompt,
    configs,
    result: dict,
    artifact_dir: Path,
    experiment_dir: Path,
    execution_order: int,
    prompt_position: int,
) -> dict:
    visible = result.get("test_metrics", {})
    visible_suite = result.get("visible_test_suite", {})
    baseline = result.get("baseline_judge", {})
    baseline_c = baseline.get("c", {})
    judge = result.get("judge_result", {})
    initial = result.get("initial_evaluation", {}).get("rust", {}).get(
        "judge", {}
    )
    verdict_counts = judge.get("verdict_counts", {})
    first_failure = judge.get("first_failure", {})
    history = result.get("execution_history", [])
    attempts = extract_attempts(result)
    initial_attempt = attempts[0]
    identifier = review_id(
        experiment_id,
        source.path.stem,
        prompt.sha256,
    )

    row = {
        "experiment_id": experiment_id,
        "execution_order": execution_order,
        "prompt_position": prompt_position,
        "review_id": identifier,
        "snippet_id": source.path.stem,
        "problem_id": source.problem_id,
        "source_file": str(source.path),
        "prompt_id": prompt.prompt_id,
        "prompt_sha256": prompt.sha256,
        "model_provider": configs.llm_provider,
        "model_id": configs.llm_model,
        "initial_translation_status": initial_attempt.get(
            "translation_status", "not_reached"
        ),
        "initial_compile_status": initial_attempt.get(
            "compile_status", "not_reached"
        ),
        "initial_visible_test_status": initial_attempt.get(
            "visible_test_status", "not_reached"
        ),
        "initial_judge_status": initial.get("status", "not_reached"),
        "initial_judge_cases_total": initial.get("total", 0),
        "initial_judge_cases_passed": initial.get("passed", 0),
        "initial_judge_cases_failed": initial.get("failed", 0),
        "final_status": result.get("status", "failed"),
        "failure_category": result.get("failure_category", "infrastructure"),
        "compile_status": result.get("compile_status", "not_reached"),
        "visible_test_status": visible.get("status", "not_reached"),
        "visible_suite_status": visible_suite.get("status", "not_reached"),
        "visible_suite_source": visible_suite.get("source", ""),
        "visible_suite_candidates": visible_suite.get("candidate_count", 0),
        "visible_suite_cases": visible_suite.get("case_count", 0),
        "visible_suite_review_status": visible_suite.get("review_status", ""),
        "visible_suite_c_compile_profile": visible_suite.get(
            "c_compile_profile", ""
        ),
        "visible_suite_generation_attempts": visible_suite.get(
            "generation_attempt_count", 0
        ),
        "visible_suite_generated_candidates": visible_suite.get(
            "generated_candidate_count", 0
        ),
        "visible_suite_rejected_candidates": visible_suite.get(
            "rejected_candidate_count", 0
        ),
        "visible_suite_invalid_cases": visible_suite.get("invalid_case_count", 0),
        "visible_suite_inconclusive_cases": visible_suite.get(
            "inconclusive_case_count", 0
        ),
        "visible_suite_unresolved_replacements": visible_suite.get(
            "unresolved_replacement_count", 0
        ),
        "visible_suite_sha256": visible_suite.get("suite_sha256", ""),
        "visible_suite_details": visible_suite.get("details", ""),
        "visible_suite_reused": visible_suite.get("reused", False),
        "visible_suite_path": experiment_relative_path(
            visible_suite.get("suite_dir", ""),
            experiment_dir,
        ),
        "visible_suite_preparation_history_path": experiment_relative_path(
            visible_suite.get("preparation_history_path", ""),
            experiment_dir,
        ),
        "visible_generation_prompt_tokens": visible_suite.get(
            "prompt_tokens", 0
        ),
        "visible_generation_completion_tokens": visible_suite.get(
            "completion_tokens", 0
        ),
        "visible_review_prompt_tokens": visible_suite.get(
            "review_prompt_tokens", 0
        ),
        "visible_review_completion_tokens": visible_suite.get(
            "review_completion_tokens", 0
        ),
        "visible_cases_total": visible.get("total_tests", 0),
        "visible_cases_passed": visible.get("rust_passed", 0),
        "baseline_status": baseline.get("baseline_status", "not_configured"),
        "baseline_test_layout": baseline.get("test_layout", ""),
        "baseline_c_compile_status": baseline_c.get(
            "compile_status", "not_run"
        ),
        "baseline_c_judge_status": baseline_c.get("judge", {}).get(
            "status", "not_run"
        ),
        "judge_status": judge.get("status", "not_reached"),
        "judge_cases_total": judge.get("total", 0),
        "judge_cases_passed": judge.get("passed", 0),
        "judge_cases_failed": judge.get("failed", 0),
        "judge_first_failure_case": first_failure.get("case", ""),
        "judge_first_failure_verdict": first_failure.get("verdict", ""),
        "repair_attempts": result.get("repair_count", 0),
        "duration_seconds": round(
            sum(step["duration_sec"] for step in history), 3
        ),
        "prompt_tokens": sum(
            step.get("prompt_tokens", 0) for step in history
        ),
        "completion_tokens": sum(
            step.get("completion_tokens", 0) for step in history
        ),
        "raw_output_path": experiment_relative_path(
            artifact_dir / "raw_response.txt", experiment_dir
        ),
        "initial_code_path": experiment_relative_path(
            artifact_dir / "attempts" / "attempt-00-initial.rs",
            experiment_dir,
        ),
        "final_code_path": experiment_relative_path(
            artifact_dir / "translated.rs", experiment_dir
        ),
        "test_report_path": experiment_relative_path(
            artifact_dir / "test_report.json", experiment_dir
        ),
        "validator_report_path": experiment_relative_path(
            artifact_dir / "validator_report.json", experiment_dir
        ),
        "agent_interactions_path": experiment_relative_path(
            artifact_dir / "agent_interactions.json", experiment_dir
        ),
        "attempts_path": experiment_relative_path(
            artifact_dir / "attempts.json", experiment_dir
        ),
        "validator_completed_analysis_count": sum(
            interaction.get("action") == "semantic_analysis"
            and interaction.get("data", {})
            .get("validator_report", {})
            .get("status")
            == "completed"
            for interaction in result.get("agent_interactions", [])
        ),
        "validator_invalid_visible_test_count": sum(
            interaction.get("action") == "semantic_analysis"
            and interaction.get("data", {})
            .get("validator_report", {})
            .get("test_assessment")
            == "invalid_visible_test"
            for interaction in result.get("agent_interactions", [])
        ),
        "validator_inconclusive_count": sum(
            interaction.get("action") == "semantic_analysis"
            and interaction.get("data", {})
            .get("validator_report", {})
            .get("test_assessment")
            == "inconclusive"
            for interaction in result.get("agent_interactions", [])
        ),
        "result_path": experiment_relative_path(
            artifact_dir / "result.json", experiment_dir
        ),
    }
    for verdict in VERDICTS:
        row[f"judge_{verdict.lower()}_count"] = verdict_counts.get(verdict, 0)
    return row


def build_attempt_rows(
    result_row: dict,
    result: dict,
    artifact_dir: Path,
    experiment_dir: Path,
) -> list[dict]:
    interaction_path = experiment_relative_path(
        artifact_dir / "agent_interactions.json", experiment_dir
    )
    rows = []
    for attempt in extract_attempts(result):
        number = attempt["attempt_number"]
        kind = attempt["attempt_kind"]
        row = {
            key: result_row[key]
            for key in (
                "experiment_id",
                "execution_order",
                "review_id",
                "snippet_id",
                "problem_id",
                "prompt_id",
                "prompt_sha256",
            )
        }
        row.update(attempt)
        row["code_path"] = experiment_relative_path(
            artifact_dir
            / "attempts"
            / f"attempt-{number:02d}-{kind}.rs",
            experiment_dir,
        )
        row["interaction_sequences"] = json.dumps(
            attempt.get("interaction_sequences", []),
            separators=(",", ":"),
        )
        row["agent_interactions_path"] = interaction_path
        rows.append(row)
    return rows


def write_artifacts(artifact_dir: Path, source, result: dict) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "source.c").write_text(
        source.path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (artifact_dir / "raw_response.txt").write_text(
        result.get("raw_model_output", ""), encoding="utf-8"
    )
    _write_json(artifact_dir / "test_report.json", result.get("test_metrics", {}))
    _write_json(
        artifact_dir / "test_suite.json",
        result.get("visible_test_suite", {}),
    )
    _write_json(
        artifact_dir / "validator_report.json",
        result.get("validator_report", {}),
    )
    _write_json(
        artifact_dir / "agent_interactions.json",
        result.get("agent_interactions", []),
    )
    _write_json(
        artifact_dir / "initial_judge_comparison.json",
        result.get("initial_evaluation", {}),
    )
    _write_json(
        artifact_dir / "judge_comparison.json",
        result.get("baseline_judge", {}),
    )

    attempts = extract_attempts(result)
    attempts_dir = artifact_dir / "attempts"
    attempts_dir.mkdir(exist_ok=True)
    for attempt in attempts:
        filename = (
            f"attempt-{attempt['attempt_number']:02d}-"
            f"{attempt['attempt_kind']}.rs"
        )
        (attempts_dir / filename).write_text(
            attempt.get("rust_code", ""), encoding="utf-8"
        )
    _write_json(
        artifact_dir / "attempts.json",
        [{key: value for key, value in item.items() if key != "rust_code"} for item in attempts],
    )

    (artifact_dir / "translated.rs").write_text(
        result.get("rust_code", ""), encoding="utf-8"
    )
    _write_json(artifact_dir / "result.json", result)


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    temporary.replace(path)


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def summarize(rows: list[dict]) -> dict:
    by_prompt: dict[str, dict] = defaultdict(
        lambda: {
            "runs": 0,
            "initial_judge_status": Counter(),
            "final_status": Counter(),
            "visible_test_status": Counter(),
            "judge_status": Counter(),
            "judge_verdict_counts": Counter(),
            "baseline_status": Counter(),
            "baseline_c_judge_status": Counter(),
            "validator_completed_analyses": 0,
            "validator_invalid_visible_tests": 0,
            "validator_inconclusive": 0,
        }
    )
    for row in rows:
        summary = by_prompt[row["prompt_id"]]
        summary["runs"] += 1
        for field in (
            "initial_judge_status",
            "final_status",
            "visible_test_status",
            "judge_status",
            "baseline_status",
            "baseline_c_judge_status",
        ):
            summary[field][row[field]] += 1
        summary["validator_completed_analyses"] += int(
            row["validator_completed_analysis_count"]
        )
        summary["validator_invalid_visible_tests"] += int(
            row["validator_invalid_visible_test_count"]
        )
        summary["validator_inconclusive"] += int(
            row["validator_inconclusive_count"]
        )
        for verdict in VERDICTS:
            summary["judge_verdict_counts"][verdict] += int(
                row[f"judge_{verdict.lower()}_count"]
            )
    suites = list({row["snippet_id"]: row for row in rows}.values())
    suite_statuses = Counter(row.get("visible_suite_status", "") for row in suites)
    review_statuses = Counter(
        row.get("visible_suite_review_status", "") for row in suites
    )
    return {
        "total_runs": len(rows),
        "visible_suite_population": {
            "programs": len(suites),
            "status": dict(suite_statuses),
            "review_status": dict(review_statuses),
            "regenerated": sum(
                int(row.get("visible_suite_generation_attempts", 0) or 0) > 1
                for row in suites
            ),
            "generated_candidates": sum(
                int(row.get("visible_suite_generated_candidates", 0) or 0)
                for row in suites
            ),
            "rejected_candidates": sum(
                int(row.get("visible_suite_rejected_candidates", 0) or 0)
                for row in suites
            ),
            "invalid_cases": sum(
                int(row.get("visible_suite_invalid_cases", 0) or 0)
                for row in suites
            ),
            "inconclusive_cases": sum(
                int(row.get("visible_suite_inconclusive_cases", 0) or 0)
                for row in suites
            ),
            "unresolved_replacements": sum(
                int(row.get("visible_suite_unresolved_replacements", 0) or 0)
                for row in suites
            ),
            "approved_cases": sum(
                int(row.get("visible_suite_cases", 0) or 0) for row in suites
            ),
        },
        "by_prompt": {
            prompt_id: {
                key: dict(value) if isinstance(value, Counter) else value
                for key, value in values.items()
            }
            for prompt_id, values in sorted(by_prompt.items())
        },
    }
