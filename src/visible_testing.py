"""Language-agnostic visible-test suite materialization and execution."""

import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path

from judge_execution import compile_c, compile_rust, list_input_cases


PROMPT_PATH = Path("prompts/visible_test_generation_prompt.txt")
FAILURE_EXAMPLE_LIMIT = 3


def load_generation_prompt() -> str:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    if "{c_code}" not in prompt:
        raise ValueError(f"Visible-test prompt {PROMPT_PATH} must contain {{c_code}}.")
    return prompt


def source_sha256(c_code: str) -> str:
    return hashlib.sha256(c_code.encode("utf-8")).hexdigest()


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def find_reusable_suite(
    test_root: str | Path,
    c_code: str,
    generation_prompt: str | None = None,
) -> dict | None:
    root = Path(test_root)
    source_hash = source_sha256(c_code)
    generated_dir = root / source_hash[:12]
    manifest = _read_manifest(generated_dir)
    if manifest and manifest.get("source_sha256") == source_hash:
        expected_prompt_hash = (
            prompt_sha256(generation_prompt) if generation_prompt is not None else None
        )
        if expected_prompt_hash is None or manifest.get("prompt_sha256") == expected_prompt_hash:
            return {**manifest, "suite_dir": str(generated_dir), "reused": True}

    legacy_cases = _paired_cases(root)
    if legacy_cases:
        return {
            "status": "ready",
            "source": "preexisting",
            "source_sha256": source_hash,
            "case_count": len(legacy_cases),
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
    source_hash = source_sha256(c_code)
    suite_dir = Path(test_root) / source_hash[:12]
    suite_dir.mkdir(parents=True, exist_ok=True)

    candidates = generation.get("cases", [])
    generation_record = {
        "strategy": generation.get("strategy", ""),
        "cases": candidates,
        "prompt_sha256": prompt_sha256(generation_prompt),
    }
    _write_json(suite_dir / "generation.json", generation_record)

    with tempfile.TemporaryDirectory(prefix="oxcidation-visible-c-") as temp_dir:
        compilation, c_binary = compile_c(c_code, temp_dir)
        if compilation.returncode != 0:
            return _write_suite_manifest(
                suite_dir,
                {
                    "status": "baseline_compile_failed",
                    "source": "generated",
                    "source_sha256": source_hash,
                    "prompt_sha256": generation_record["prompt_sha256"],
                    "case_count": 0,
                    "candidate_count": len(candidates),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "rejected_cases": [],
                    "details": compilation.stderr,
                },
            )

        valid_cases = []
        rejected_cases = []
        seen_inputs = set()
        for candidate_index, candidate in enumerate(candidates, start=1):
            input_data = candidate.get("input", "")
            purpose = candidate.get("purpose", "").strip()
            if input_data in seen_inputs:
                rejected_cases.append(
                    _rejected_case(candidate_index, purpose, "duplicate", "Duplicate input.")
                )
                continue
            seen_inputs.add(input_data)

            c_run = run_program(c_binary, input_data, timeout_sec)
            if c_run["status"] != "ACCEPTED":
                rejected_cases.append(
                    _rejected_case(
                        candidate_index,
                        purpose,
                        c_run["status"],
                        c_run.get("stderr", ""),
                    )
                )
                continue

            case_id = f"case-{len(valid_cases) + 1:03d}"
            input_file = f"{case_id}.in"
            output_file = f"{case_id}.out"
            (suite_dir / input_file).write_text(input_data, encoding="utf-8")
            (suite_dir / output_file).write_text(c_run["stdout"], encoding="utf-8")
            valid_cases.append(
                {
                    "id": case_id,
                    "purpose": purpose,
                    "input_file": input_file,
                    "output_file": output_file,
                }
            )

    status = "ready" if valid_cases else "no_valid_cases"
    return _write_suite_manifest(
        suite_dir,
        {
            "status": status,
            "source": "generated",
            "source_sha256": source_hash,
            "prompt_sha256": generation_record["prompt_sha256"],
            "strategy": generation.get("strategy", ""),
            "candidate_count": len(candidates),
            "case_count": len(valid_cases),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cases": valid_cases,
            "rejected_cases": rejected_cases,
            "details": "" if valid_cases else "The C oracle rejected every generated input.",
        },
    )


def record_generation_failure(
    c_code: str,
    test_root: str | Path,
    generation_prompt: str,
    details: str,
) -> dict:
    source_hash = source_sha256(c_code)
    suite_dir = Path(test_root) / source_hash[:12]
    suite_dir.mkdir(parents=True, exist_ok=True)
    return _write_suite_manifest(
        suite_dir,
        {
            "status": "generation_failed",
            "source": "generated",
            "source_sha256": source_hash,
            "prompt_sha256": prompt_sha256(generation_prompt),
            "candidate_count": 0,
            "case_count": 0,
            "cases": [],
            "rejected_cases": [],
            "details": details,
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
    return {**manifest, "suite_dir": str(suite_dir), "reused": False}


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _rejected_case(index: int, purpose: str, verdict: str, details: str) -> dict:
    return {
        "candidate": index,
        "purpose": purpose,
        "verdict": verdict,
        "details": details[:1000],
    }
