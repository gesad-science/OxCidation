"""Language-agnostic visible-test suite materialization and execution."""

import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path

from judge_execution import compile_c, compile_rust, list_input_cases


PROMPT_PATH = Path("prompts/visible_test_generation_prompt.txt")
REVIEW_PROMPT_PATH = Path("prompts/visible_test_review_prompt.txt")
FAILURE_EXAMPLE_LIMIT = 3
OPERATIONAL_PREPARATION_STATUSES = frozenset(
    {"generation_failed", "review_failed"}
)
REUSABLE_PREPARATION_STATUSES = frozenset(
    {
        "ready",
        "invalid_visible_tests",
        "baseline_compile_failed",
    }
)


def load_generation_prompt() -> str:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    if "{c_code}" not in prompt:
        raise ValueError(f"Visible-test prompt {PROMPT_PATH} must contain {{c_code}}.")
    return prompt


def load_review_prompt() -> str:
    prompt = REVIEW_PROMPT_PATH.read_text(encoding="utf-8")
    required_placeholders = ("{c_code}", "{cases}", "{deterministic_report}")
    missing = [placeholder for placeholder in required_placeholders if placeholder not in prompt]
    if missing:
        raise ValueError(
            f"Visible-test review prompt {REVIEW_PROMPT_PATH} is missing "
            f"{', '.join(missing)}."
        )
    return prompt


def source_sha256(c_code: str) -> str:
    return hashlib.sha256(c_code.encode("utf-8")).hexdigest()


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def find_reusable_suite(
    test_root: str | Path,
    c_code: str,
    generation_prompt: str | None = None,
    review_prompt: str | None = None,
    model_provider: str | None = None,
    model_id: str | None = None,
) -> dict | None:
    root = Path(test_root)
    source_hash = source_sha256(c_code)
    generated_dir = root / source_hash[:12]
    manifest = _read_manifest(generated_dir)
    if manifest and manifest.get("source_sha256") == source_hash:
        identities = {
            "prompt_sha256": (
                prompt_sha256(generation_prompt) if generation_prompt is not None else None
            ),
            "review_prompt_sha256": (
                prompt_sha256(review_prompt) if review_prompt is not None else None
            ),
            "model_provider": model_provider,
            "model_id": model_id,
        }
        matches = all(
            expected is None or manifest.get(field) == expected
            for field, expected in identities.items()
        )
        if matches and manifest.get("status") in REUSABLE_PREPARATION_STATUSES:
            history_path = generated_dir / "preparation_history.json"
            if manifest.get("review_prompt_sha256") and not history_path.is_file():
                return None
            active_attempt = manifest.get("active_attempt", "")
            suite_dir = generated_dir / active_attempt if active_attempt else generated_dir
            if manifest.get("status") == "ready":
                paired_cases = _paired_cases(suite_dir)
                if len(paired_cases) != manifest.get("case_count", 0):
                    return None
                from visible_test_preparation import suite_sha256

                if suite_sha256(suite_dir) != manifest.get("suite_sha256"):
                    return None
            return {
                **manifest,
                "suite_dir": str(suite_dir),
                "preparation_history_path": str(history_path),
                "reused": True,
            }

    legacy_cases = _paired_cases(root)
    if legacy_cases:
        return {
            "status": "ready",
            "source": "preexisting",
            "source_sha256": source_hash,
            "case_count": len(legacy_cases),
            "review_status": "not_applicable",
            "generation_attempt_count": 0,
            "suite_dir": str(root),
            "reused": True,
        }
    return None


def materialize_generated_suite(
    c_code: str,
    generation: dict,
    test_root: str | Path,
    timeout_sec: float,
    generation_prompt: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> dict:
    from visible_test_preparation import materialize_generation_attempt, suite_sha256

    source_hash = source_sha256(c_code)
    suite_dir = Path(test_root) / source_hash[:12]
    suite_dir.mkdir(parents=True, exist_ok=True)
    attempt = materialize_generation_attempt(
        c_code,
        generation,
        suite_dir,
        1,
        timeout_sec,
        generation_prompt,
        "",
    )
    attempt.pop("review_cases", None)
    attempt.pop("suite_dir", None)
    return _write_suite_manifest(
        suite_dir,
        {
            **attempt,
            "source": "generated",
            "source_sha256": source_hash,
            "review_status": "not_reviewed",
            "review_count": 0,
            "generation_attempt_count": 1,
            "generated_candidate_count": attempt.get("candidate_count", 0),
            "deterministic_rejection_count": len(
                attempt.get("rejected_cases", [])
            ),
            "validator_replacement_count": 0,
            "unresolved_replacement_count": 0,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "active_attempt": attempt["attempt_path"],
            "suite_sha256": suite_sha256(
                suite_dir / attempt["attempt_path"]
            ),
        },
    )


def evaluate_visible_suite(
    c_code: str,
    rust_code: str,
    suite_dir: str | Path,
    timeout_sec: float,
) -> dict:
    suite_path = Path(suite_dir)
    input_names = list_input_cases(str(suite_path)) if suite_path.is_dir() else []
    if not input_names:
        return _skipped_report(suite_path, "The generated suite contains no valid cases.")

    started_at = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="oxcidation-visible-run-") as temp_dir:
        c_compile, c_binary = compile_c(c_code, temp_dir)
        if c_compile.returncode != 0:
            report = _compile_failure_report(
                suite_path,
                "skipped",
                "c_compilation",
                c_compile.stderr,
                len(input_names),
            )
            report["failure_category"] = "infrastructure"
            report["reason"] = "The C baseline failed to compile for visible-test execution."
            report["c_compile_profile"] = getattr(
                c_compile,
                "compile_profile",
                "unknown",
            )
            report["c_compile_attempts"] = getattr(
                c_compile,
                "compile_attempts",
                [],
            )
            return report

        rust_compile, rust_binary = compile_rust(rust_code, temp_dir)
        if rust_compile.returncode != 0:
            return _compile_failure_report(
                suite_path,
                "failed",
                "rust_compilation",
                rust_compile.stderr,
                len(input_names),
            )

        report = _new_test_report(suite_path, len(input_names))
        report["c_compile_profile"] = getattr(
            c_compile,
            "compile_profile",
            "unknown",
        )
        report["c_compile_attempts"] = getattr(
            c_compile,
            "compile_attempts",
            [],
        )
        for input_name in input_names:
            _evaluate_case(
                report,
                suite_path,
                input_name,
                c_binary,
                rust_binary,
                timeout_sec,
            )

    differential_failures = report["failed_rust_where_c_passed"]
    if differential_failures:
        report["status"] = "failed"
    elif report["c_failed"]:
        report["status"] = "skipped"
        report["failure_category"] = "infrastructure"
        report["reason"] = "The C baseline could not reproduce every visible-test oracle."
    report["duration_ms"] = int((time.monotonic() - started_at) * 1000)
    report["details"] = _report_details(report)
    return report


def run_program(binary: str, input_data: str, timeout_sec: float) -> dict:
    try:
        run = subprocess.run(
            [binary],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return {"status": "TIME_LIMIT_EXCEEDED", "stdout": "", "stderr": ""}
    if run.returncode != 0:
        return {
            "status": "RUNTIME_ERROR",
            "stdout": run.stdout,
            "stderr": run.stderr[:1000],
        }
    return {"status": "ACCEPTED", "stdout": run.stdout, "stderr": run.stderr[:1000]}


def _evaluate_case(
    report: dict,
    suite_path: Path,
    input_name: str,
    c_binary: str,
    rust_binary: str,
    timeout_sec: float,
) -> None:
    input_data = (suite_path / input_name).read_text(encoding="utf-8")
    output_path = suite_path / input_name.replace(".in", ".out")
    expected_output = output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
    c_run = run_program(c_binary, input_data, timeout_sec)
    rust_run = run_program(rust_binary, input_data, timeout_sec)

    c_matches = c_run["status"] == "ACCEPTED" and outputs_equal(
        c_run["stdout"], expected_output
    )
    report["c_passed" if c_matches else "c_failed"] += 1
    if not c_matches:
        report["baseline_failures"].append(
            {
                "case": input_name,
                "verdict": c_run["status"] if c_run["status"] != "ACCEPTED" else "WRONG_ANSWER",
            }
        )
        return

    rust_verdict = rust_run["status"]
    if rust_verdict == "ACCEPTED" and not outputs_equal(rust_run["stdout"], expected_output):
        rust_verdict = "WRONG_ANSWER"
    report["verdict_counts"][rust_verdict] += 1
    report["case_results"].append({"case": input_name, "verdict": rust_verdict})
    if rust_verdict == "ACCEPTED":
        report["rust_passed"] += 1
        return

    report["rust_failed"] += 1
    report["failed_rust_where_c_passed"] += 1
    report["failed_tests"].append(input_name)
    if len(report["failure_examples"]) < FAILURE_EXAMPLE_LIMIT:
        report["failure_examples"].append(
            {
                "case": input_name,
                "verdict": rust_verdict,
                "input": input_data,
                "expected_output": expected_output,
                "rust_output": rust_run["stdout"],
                "rust_stderr": rust_run["stderr"],
            }
        )


def outputs_equal(actual: str, expected: str) -> bool:
    return actual.split() == expected.split()


def _new_test_report(suite_path: Path, total: int) -> dict:
    return {
        "status": "success",
        "suite_dir": str(suite_path),
        "c_compilation": "success",
        "rust_compilation": "success",
        "total_tests": total,
        "c_passed": 0,
        "c_failed": 0,
        "rust_passed": 0,
        "rust_failed": 0,
        "failed_rust_where_c_passed": 0,
        "failed_tests": [],
        "verdict_counts": {
            "ACCEPTED": 0,
            "WRONG_ANSWER": 0,
            "TIME_LIMIT_EXCEEDED": 0,
            "RUNTIME_ERROR": 0,
        },
        "case_results": [],
        "failure_examples": [],
        "baseline_failures": [],
        "details": "",
    }


def _compile_failure_report(
    suite_path: Path,
    status: str,
    failed_compiler: str,
    compiler_output: str,
    total: int,
) -> dict:
    report = _new_test_report(suite_path, total)
    report.update(status=status, details=compiler_output)
    report[failed_compiler] = "failed"
    return report


def _skipped_report(suite_path: Path, reason: str) -> dict:
    report = _new_test_report(suite_path, 0)
    report.update(status="skipped", reason=reason, details=reason)
    return report


def _report_details(report: dict) -> str:
    return (
        f"Visible tests: total={report['total_tests']}, C accepted={report['c_passed']}, "
        f"Rust accepted={report['rust_passed']}, differential failures="
        f"{report['failed_rust_where_c_passed']}."
    )


def _paired_cases(test_dir: Path) -> list[str]:
    if not test_dir.is_dir():
        return []
    return [
        input_name
        for input_name in list_input_cases(str(test_dir))
        if (test_dir / input_name.replace(".in", ".out")).is_file()
    ]


def _read_manifest(suite_dir: Path) -> dict | None:
    path = suite_dir / "suite.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_suite_manifest(suite_dir: Path, manifest: dict) -> dict:
    _write_json(suite_dir / "suite.json", manifest)
    active_attempt = manifest.get("active_attempt", "")
    active_dir = suite_dir / active_attempt if active_attempt else suite_dir
    return {**manifest, "suite_dir": str(active_dir), "reused": False}


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _rejected_case(index: int, purpose: str, verdict: str, details: str) -> dict:
    return {
        "candidate": index,
        "purpose": purpose,
        "verdict": verdict,
        "details": details[:1000],
    }
