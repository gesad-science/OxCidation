"""Compilation and test-suite execution primitives shared by validation flows."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time


VERDICT_RE = re.compile(r"\[(?:SUCCESS|FAILURE)\]\s+(AC|WA|TLE|MLE|RE)\b")
FAILED_SUMMARY_RE = re.compile(r"test failed:\s+(\d+)\s+AC\s*/\s*(\d+)\s+cases")
SUCCESS_SUMMARY_RE = re.compile(r"test success:\s+(\d+)\s+cases")
STATUS_BY_VERDICT = {
    "AC": "ACCEPTED",
    "WA": "WRONG_ANSWER",
    "TLE": "TIME_LIMIT_EXCEEDED",
    "MLE": "MEMORY_LIMIT_EXCEEDED",
    "RE": "RUNTIME_ERROR",
}
STATUS_PRIORITY = [
    "TIME_LIMIT_EXCEEDED",
    "MEMORY_LIMIT_EXCEEDED",
    "RUNTIME_ERROR",
    "WRONG_ANSWER",
    "INFRA_ERROR",
]
C_COMPILER_PROFILES = (
    ("gnu11", ("-std=gnu11",)),
    ("gnu89-compat", ("-std=gnu89",)),
)


def compile_c(source_code: str, temp_dir: str) -> tuple[subprocess.CompletedProcess, str]:
    source_path = os.path.join(temp_dir, "prog.c")
    executable_path = os.path.join(temp_dir, "prog_c")
    with open(source_path, "w", encoding="utf-8") as source_file:
        source_file.write(source_code)
    attempts = []
    result = None
    for profile, flags in C_COMPILER_PROFILES:
        result = subprocess.run(
            ["gcc", *flags, source_path, "-o", executable_path, "-lm"],
            capture_output=True,
            text=True,
        )
        attempts.append(
            {
                "profile": profile,
                "status": "success" if result.returncode == 0 else "failed",
            }
        )
        if result.returncode == 0:
            break

    if result is None:
        raise RuntimeError("No C compiler profile was configured.")
    result.compile_profile = (
        attempts[-1]["profile"] if result.returncode == 0 else ""
    )
    result.compile_attempts = attempts
    return result, executable_path


def compile_rust(source_code: str, temp_dir: str) -> tuple[subprocess.CompletedProcess, str]:
    source_path = os.path.join(temp_dir, "prog.rs")
    executable_path = os.path.join(temp_dir, "prog_rust")
    with open(source_path, "w", encoding="utf-8") as source_file:
        source_file.write(source_code)
    result = subprocess.run(
        ["rustc", source_path, "-o", executable_path],
        capture_output=True,
        text=True,
    )
    return result, executable_path


def list_input_cases(test_dir: str) -> list[str]:
    return sorted(path.name for path in os.scandir(test_dir) if path.name.endswith(".in"))


def empty_verdict_counts() -> dict:
    return {status: 0 for status in (*STATUS_BY_VERDICT.values(), "INFRA_ERROR")}


def judge_result(
    status: str,
    passed: int,
    failed: int,
    total: int,
    time_ms: int,
    details: str,
    verdict_counts: dict | None = None,
    first_failure: dict | None = None,
    raw_output: str = "",
) -> dict:
    return {
        "status": status,
        "passed": passed,
        "failed": failed,
        "total": total,
        "time_ms": time_ms,
        "details": details,
        "verdict_counts": verdict_counts or empty_verdict_counts(),
        "first_failure": first_failure or {},
        "raw_output": raw_output,
    }


def run_python_io_suite(test_dir: str, command: str, timeout_sec: float) -> dict:
    verdict_counts = empty_verdict_counts()
    first_failure = {}
    details = []
    started_at = time.time()

    for input_name in list_input_cases(test_dir):
        input_path = os.path.join(test_dir, input_name)
        output_path = os.path.join(test_dir, input_name.replace(".in", ".out"))
        with open(input_path, encoding="utf-8") as input_file:
            input_data = input_file.read()
        expected_output = ""
        if os.path.exists(output_path):
            with open(output_path, encoding="utf-8") as output_file:
                expected_output = output_file.read()

        try:
            run = subprocess.run(
                [command],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            verdict = "TIME_LIMIT_EXCEEDED"
            message = f"Test {input_name} exceeded {timeout_sec}s."
        else:
            if run.returncode != 0:
                verdict = "RUNTIME_ERROR"
                message = f"Test {input_name} runtime error:\n{run.stderr[:1000]}"
            elif run.stdout.split() == expected_output.split():
                verdict_counts["ACCEPTED"] += 1
                continue
            else:
                verdict = "WRONG_ANSWER"
                message = (
                    f"Test {input_name} failed.\n"
                    f"Expected (first 10 lines):\n{' '.join(expected_output.splitlines()[:10])}\n\n"
                    f"Actual (first 10 lines):\n{' '.join(run.stdout.splitlines()[:10])}\n"
                )

        verdict_counts[verdict] += 1
        details.append(message)
        if not first_failure:
            first_failure = {"case": input_name, "verdict": verdict, "excerpt": message}

    elapsed_ms = int((time.time() - started_at) * 1000)
    total = len(list_input_cases(test_dir))
    passed = verdict_counts["ACCEPTED"]
    failed = max(total - passed, 0)
    status = "ACCEPTED" if failed == 0 else aggregate_status(verdict_counts, 1)
    return judge_result(
        status,
        passed,
        failed,
        total,
        elapsed_ms,
        "\n".join(details) or f"All {total} judge cases passed.",
        verdict_counts,
        first_failure,
    )


def run_oj_suite(
    test_dir: str,
    command: str,
    timeout_sec: float,
    compare_mode: str,
) -> dict:
    if not shutil.which("oj"):
        return judge_result(
            "INFRA_ERROR",
            0,
            0,
            0,
            0,
            "online-judge-tools executable 'oj' was not found.",
        )
    args = [
        "oj",
        "test",
        "--command",
        command,
        "--directory",
        test_dir,
        "--format",
        "%s.%e",
        "--compare-mode",
        compare_mode,
        "--display-mode",
        "all",
        "--tle",
        str(timeout_sec),
    ]
    for input_name in list_input_cases(test_dir):
        input_path = os.path.join(test_dir, input_name)
        args.extend((input_path, input_path.removesuffix(".in") + ".out"))
    started_at = time.time()
    run = subprocess.run(args, capture_output=True, text=True, env=oj_environment())
    return classify_oj_output(
        run.returncode,
        f"{run.stdout}\n{run.stderr}".strip(),
        len(list_input_cases(test_dir)),
        int((time.time() - started_at) * 1000),
    )


def classify_oj_output(returncode: int, output: str, total: int, elapsed_ms: int) -> dict:
    cleaned_output = strip_oj_update_noise(output)
    verdict_counts = empty_verdict_counts()
    for verdict in VERDICT_RE.findall(cleaned_output):
        verdict_counts[STATUS_BY_VERDICT.get(verdict, "INFRA_ERROR")] += 1

    success_summary = SUCCESS_SUMMARY_RE.search(cleaned_output)
    failed_summary = FAILED_SUMMARY_RE.search(cleaned_output)
    if success_summary and not verdict_counts["ACCEPTED"]:
        verdict_counts["ACCEPTED"] = int(success_summary.group(1))
    passed = int(failed_summary.group(1)) if failed_summary else (
        verdict_counts["ACCEPTED"] if returncode == 0 else 0
    )
    if failed_summary:
        total = int(failed_summary.group(2))
    first_failure = first_failure_from_oj_output(cleaned_output)
    status = aggregate_status(verdict_counts, returncode)
    failed = max(total - passed, 0)
    details = f"oj status={status}; passed={passed}; failed={failed}; total={total}"
    if first_failure:
        details = f"{details}; first_failure={first_failure['verdict']}"
    return judge_result(
        status,
        passed,
        failed,
        total,
        elapsed_ms,
        details,
        verdict_counts,
        first_failure,
        cleaned_output,
    )


def aggregate_status(verdict_counts: dict, returncode: int) -> str:
    if returncode == 0:
        return "ACCEPTED"
    return next((status for status in STATUS_PRIORITY if verdict_counts.get(status, 0)), "INFRA_ERROR")


def strip_oj_update_noise(output: str) -> str:
    noise = ("https://pypi.org/pypi/online-judge-tools/json", "failed to check update")
    kept_lines = [
        line
        for line in output.splitlines()
        if not any(item in line for item in noise)
    ]
    return "\n".join(kept_lines).strip()


def first_failure_from_oj_output(output: str) -> dict:
    lines = output.splitlines()
    for index, line in enumerate(lines):
        match = VERDICT_RE.search(line)
        if not match or match.group(1) == "AC":
            continue
        case_name = ""
        for previous in reversed(lines[:index]):
            info_match = re.match(r"\[INFO\]\s+(.+)", previous)
            info = info_match.group(1).strip() if info_match else ""
            if info and not info.startswith(("time:", "slowest:", "max memory:", "online-judge-tools")) and "cases found" not in info:
                case_name = info
                break
        return {
            "case": case_name,
            "verdict": STATUS_BY_VERDICT.get(match.group(1), "INFRA_ERROR"),
            "excerpt": "\n".join(lines[index:index + 20]).strip(),
        }
    return {}


def oj_environment() -> dict:
    import onlinejudge.__about__ as api_version
    import onlinejudge_command.__about__ as command_version

    cache_root = os.path.join(tempfile.gettempdir(), "oxcidation-oj-cache")
    cache_dir = os.path.join(cache_root, "online-judge-tools")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "pypi.json")
    if not os.path.exists(cache_path):
        with open(cache_path, "w", encoding="utf-8") as cache_file:
            json.dump(
                {
                    "online-judge-tools": {"time": int(time.time()), "version": command_version.__version__},
                    "online-judge-api-client": {"time": int(time.time()), "version": api_version.__version__},
                },
                cache_file,
            )
    environment = os.environ.copy()
    environment["XDG_CACHE_HOME"] = cache_root
    return environment
