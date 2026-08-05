"""Download and validate AOJ system tests for accepted-C CodeNet problems."""

from __future__ import annotations

import argparse
import csv
import email.utils
import hashlib
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


API_ROOT = "https://judgedat.u-aizu.ac.jp/testcases"
TOOL_VERSION = 2
PROBLEM_ID_RE = re.compile(r"p(\d{5})")
SAFE_CASE_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
REPORT_FIELDS = (
    "problem_id",
    "dataset",
    "external_problem_id",
    "status",
    "case_count",
    "input_bytes",
    "output_bytes",
    "fallback_cases",
    "details",
)


@dataclass(frozen=True)
class Problem:
    problem_id: str
    dataset: str


@dataclass(frozen=True)
class TestCaseHeader:
    serial: int
    name: str
    input_size: int
    output_size: int


class SuiteUnavailableError(ValueError):
    pass


class RequestRateLimiter:
    """Share a fixed request rate across all downloader workers."""

    def __init__(self, requests_per_second: float):
        self._interval = 1.0 / requests_per_second
        self._next_request = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_request - now)
            self._next_request = max(now, self._next_request) + self._interval
        if delay:
            time.sleep(delay)


class AojHttpClient:
    def __init__(
        self,
        requests_per_second: float,
        timeout_sec: float,
        retries: int,
        stop_event: threading.Event,
    ):
        self._rate_limiter = RequestRateLimiter(requests_per_second)
        self._timeout_sec = timeout_sec
        self._retries = retries
        self._stop_event = stop_event

    def get(self, url: str) -> bytes:
        for attempt in range(self._retries + 1):
            if self._stop_event.is_set():
                raise InterruptedError("Extraction interrupted.")
            self._rate_limiter.wait()
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "OxCidation-AOJ-test-prefetch/1"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout_sec) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt == self._retries:
                    raise
                delay = retry_delay(error.headers.get("Retry-After"), attempt)
            except (TimeoutError, urllib.error.URLError):
                if attempt == self._retries:
                    raise
                delay = retry_delay(None, attempt)
            if self._stop_event.wait(delay):
                raise InterruptedError("Extraction interrupted.")
        raise RuntimeError("HTTP retry loop ended unexpectedly.")


class AojSuiteDownloader:
    def __init__(
        self,
        output_root: Path,
        get_bytes: Callable[[str], bytes],
        stop_event: threading.Event | None = None,
    ):
        self.output_root = output_root
        self.partial_root = output_root / ".partial"
        self.get_bytes = get_bytes
        self.stop_event = stop_event or threading.Event()

    def download(self, problem: Problem) -> dict:
        if problem.dataset.casefold() != "aizu":
            return result_row(problem, "unsupported_dataset", details="AOJ tests are unavailable.")

        external_id = external_aoj_id(problem.problem_id)
        final_directory = self.output_root / problem.problem_id
        if final_directory.exists():
            try:
                manifest = validate_completed_suite(final_directory, problem, external_id)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                return result_row(
                    problem,
                    "invalid_existing_suite",
                    external_id,
                    details=str(error),
                )
            return result_from_manifest(problem, external_id, "already_complete", manifest)

        staging = self.partial_root / problem.problem_id
        staging.mkdir(parents=True, exist_ok=True)
        try:
            header_bytes = self._load_header(staging, external_id)
            cases = parse_header(header_bytes, external_id)
            unavailable = next(
                (case for case in cases if case.input_size == 0 or case.output_size == 0),
                None,
            )
            if unavailable:
                raise SuiteUnavailableError(
                    f"AOJ header marks case {unavailable.serial} as unavailable "
                    f"({unavailable.input_size}/{unavailable.output_size} bytes)."
                )
            case_records = [self._download_case(staging, external_id, case) for case in cases]
            manifest = build_suite_manifest(problem, external_id, header_bytes, case_records)
            atomic_write_json(staging / "suite_manifest.json", manifest)
            self.output_root.mkdir(parents=True, exist_ok=True)
            os.replace(staging, final_directory)
            return result_from_manifest(problem, external_id, "downloaded", manifest)
        except InterruptedError:
            raise
        except SuiteUnavailableError as error:
            return result_row(problem, "unavailable", external_id, details=str(error))
        except Exception as error:
            return result_row(problem, "failed", external_id, details=f"{type(error).__name__}: {error}")

    def _load_header(self, staging: Path, external_id: str) -> bytes:
        header_path = staging / "header.json"
        if header_path.is_file():
            header_bytes = header_path.read_bytes()
            parse_header(header_bytes, external_id)
            return header_bytes

        header_bytes = self.get_bytes(f"{API_ROOT}/{external_id}/header")
        parse_header(header_bytes, external_id)
        atomic_write_bytes(header_path, header_bytes)
        return header_bytes

    def _download_case(
        self,
        staging: Path,
        external_id: str,
        case: TestCaseHeader,
    ) -> dict:
        input_path = staging / f"{case.name}.in"
        output_path = staging / f"{case.name}.out"
        cached = read_valid_case(input_path, output_path, case)
        if cached:
            input_bytes, output_bytes, size_validation = cached
            return case_record(case, input_bytes, output_bytes, False, size_validation)

        combined_url = f"{API_ROOT}/{external_id}/{case.serial}"
        fallback_used = False
        try:
            payload = json.loads(self.get_bytes(combined_url))
            input_bytes = payload["in"].encode("utf-8")
            output_bytes = payload["out"].encode("utf-8")
            size_validation = validate_case_sizes(case, input_bytes, output_bytes)
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeError,
            json.JSONDecodeError,
            urllib.error.URLError,
        ):
            fallback_used = True
            input_bytes = self.get_bytes(f"{combined_url}/in")
            output_bytes = self.get_bytes(f"{combined_url}/out")
            size_validation = validate_case_sizes(case, input_bytes, output_bytes)

        atomic_write_bytes(input_path, input_bytes)
        atomic_write_bytes(output_path, output_bytes)
        return case_record(case, input_bytes, output_bytes, fallback_used, size_validation)


def external_aoj_id(problem_id: str) -> str:
    match = PROBLEM_ID_RE.fullmatch(problem_id)
    if not match:
        raise ValueError(f"Invalid CodeNet problem ID: {problem_id}")
    return match.group(1)[-4:]


def parse_header(header_bytes: bytes, expected_problem_id: str) -> list[TestCaseHeader]:
    payload = json.loads(header_bytes)
    if str(payload.get("problemId", "")) != expected_problem_id:
        raise ValueError("AOJ header problem ID does not match the requested problem.")
    raw_headers = payload.get("headers")
    if not isinstance(raw_headers, list) or not raw_headers:
        raise ValueError("AOJ header contains no test cases.")

    cases = []
    names = set()
    for raw_case in raw_headers:
        serial = int(raw_case["serial"])
        name = str(raw_case.get("name") or f"testcase_{serial:04d}")
        if not SAFE_CASE_NAME_RE.fullmatch(name) or name in names:
            name = f"testcase_{serial:04d}"
        if name in names:
            raise ValueError(f"Duplicate AOJ test-case name for serial {serial}.")
        names.add(name)
        case = TestCaseHeader(
            serial=serial,
            name=name,
            input_size=int(raw_case["inputSize"]),
            output_size=int(raw_case["outputSize"]),
        )
        if min(case.serial, case.input_size, case.output_size) < 0:
            raise ValueError("AOJ header contains a negative serial or file size.")
        cases.append(case)
    return cases


def validate_case_sizes(
    case: TestCaseHeader,
    input_bytes: bytes,
    output_bytes: bytes,
) -> str:
    input_status = validate_file_size(case.input_size, input_bytes)
    output_status = validate_file_size(case.output_size, output_bytes)
    if input_status and output_status:
        return "exact" if input_status == output_status == "exact" else "extra_terminal_newline"
    raise ValueError(
        f"Case {case.serial} size mismatch: expected "
        f"{case.input_size}/{case.output_size}, got {len(input_bytes)}/{len(output_bytes)}."
    )


def validate_file_size(expected_size: int, content: bytes) -> str:
    if len(content) == expected_size:
        return "exact"
    if len(content) == expected_size + 1 and content.endswith(b"\n"):
        return "extra_terminal_newline"
    return ""


def read_valid_case(
    input_path: Path,
    output_path: Path,
    case: TestCaseHeader,
) -> tuple[bytes, bytes, str] | None:
    if not input_path.is_file() or not output_path.is_file():
        return None
    input_bytes = input_path.read_bytes()
    output_bytes = output_path.read_bytes()
    try:
        size_validation = validate_case_sizes(case, input_bytes, output_bytes)
    except ValueError:
        return None
    return input_bytes, output_bytes, size_validation


def case_record(
    case: TestCaseHeader,
    input_bytes: bytes,
    output_bytes: bytes,
    fallback_used: bool,
    size_validation: str,
) -> dict:
    return {
        "serial": case.serial,
        "name": case.name,
        "input_file": f"{case.name}.in",
        "output_file": f"{case.name}.out",
        "input_size": len(input_bytes),
        "output_size": len(output_bytes),
        "expected_input_size": case.input_size,
        "expected_output_size": case.output_size,
        "size_validation": size_validation,
        "input_sha256": sha256(input_bytes),
        "output_sha256": sha256(output_bytes),
        "separate_endpoint_fallback": fallback_used,
    }


def build_suite_manifest(
    problem: Problem,
    external_id: str,
    header_bytes: bytes,
    cases: list[dict],
) -> dict:
    return {
        "schema_version": TOOL_VERSION,
        "status": "complete",
        "problem_id": problem.problem_id,
        "dataset": problem.dataset,
        "external_problem_id": external_id,
        "source": "aoj_system_tests",
        "header_url": f"{API_ROOT}/{external_id}/header",
        "header_sha256": sha256(header_bytes),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(cases),
        "input_bytes": sum(case["input_size"] for case in cases),
        "output_bytes": sum(case["output_size"] for case in cases),
        "fallback_cases": sum(case["separate_endpoint_fallback"] for case in cases),
        "cases": cases,
    }


def validate_completed_suite(directory: Path, problem: Problem, external_id: str) -> dict:
    manifest = json.loads((directory / "suite_manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("status") != "complete"
        or manifest.get("problem_id") != problem.problem_id
        or manifest.get("external_problem_id") != external_id
    ):
        raise ValueError("Suite manifest identity or status is invalid.")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != manifest.get("case_count"):
        raise ValueError("Suite manifest case count is invalid.")
    for case in cases:
        for field in ("input", "output"):
            path = directory / case[f"{field}_file"]
            content = path.read_bytes()
            if len(content) != case[f"{field}_size"] or sha256(content) != case[f"{field}_sha256"]:
                raise ValueError(f"Cached file failed validation: {path.name}")
    return manifest


def load_problems(manifest_path: Path) -> list[Problem]:
    with manifest_path.open(newline="", encoding="utf-8") as manifest_file:
        reader = csv.DictReader(manifest_file)
        required = {"problem_id", "dataset"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"Problem manifest must contain {sorted(required)}; use the accepted-C "
                "subset's manifests/problems.csv file."
            )
        problems = {
            row["problem_id"].strip(): Problem(
                problem_id=row["problem_id"].strip(),
                dataset=row["dataset"].strip(),
            )
            for row in reader
            if row["problem_id"].strip()
        }
    return [problems[problem_id] for problem_id in sorted(problems)]


def result_row(
    problem: Problem,
    status: str,
    external_id: str = "",
    case_count: int = 0,
    input_bytes: int = 0,
    output_bytes: int = 0,
    fallback_cases: int = 0,
    details: str = "",
) -> dict:
    return {
        "problem_id": problem.problem_id,
        "dataset": problem.dataset,
        "external_problem_id": external_id,
        "status": status,
        "case_count": case_count,
        "input_bytes": input_bytes,
        "output_bytes": output_bytes,
        "fallback_cases": fallback_cases,
        "details": details,
    }


def result_from_manifest(problem: Problem, external_id: str, status: str, manifest: dict) -> dict:
    return result_row(
        problem,
        status,
        external_id,
        manifest["case_count"],
        manifest["input_bytes"],
        manifest["output_bytes"],
        manifest["fallback_cases"],
    )


def retry_delay(retry_after: str | None, attempt: int) -> float:
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            retry_time = email.utils.parsedate_to_datetime(retry_after)
            return max(0.0, retry_time.timestamp() - time.time())
    return min(30.0, 0.5 * (2**attempt)) + random.uniform(0.0, 0.25)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def atomic_write_json(path: Path, payload: dict) -> None:
    atomic_write_bytes(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def write_report(output_root: Path, rows: list[dict], interrupted: bool) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: row["problem_id"])
    report_path = output_root / "prefetch_results.csv"
    temporary = report_path.with_name(f".{report_path.name}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as report_file:
        writer = csv.DictWriter(report_file, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)
    os.replace(temporary, report_path)

    status_counts: dict[str, int] = {}
    for row in ordered:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "interrupted": interrupted,
        "processed_problems": len(ordered),
        "status_counts": dict(sorted(status_counts.items())),
        "case_count": sum(int(row["case_count"]) for row in ordered),
        "input_bytes": sum(int(row["input_bytes"]) for row in ordered),
        "output_bytes": sum(int(row["output_bytes"]) for row in ordered),
    }
    atomic_write_json(output_root / "prefetch_summary.json", summary)


def load_report(report_path: Path) -> dict[str, dict]:
    if not report_path.is_file():
        return {}
    with report_path.open(newline="", encoding="utf-8") as report_file:
        reader = csv.DictReader(report_file)
        if not reader.fieldnames or not set(REPORT_FIELDS).issubset(reader.fieldnames):
            raise ValueError(f"Invalid prefetch report: {report_path}")
        return {row["problem_id"]: row for row in reader}


def failed_problem_ids(report_path: Path) -> set[str]:
    return {
        problem_id
        for problem_id, row in load_report(report_path).items()
        if row["status"] == "failed"
    }


def run(args: argparse.Namespace) -> int:
    problems = load_problems(args.problem_manifest)
    selected_ids = set(args.problem_id or [])
    if args.retry_failed_from:
        selected_ids = failed_problem_ids(args.retry_failed_from)
        if not selected_ids:
            raise ValueError(f"No failed problems were found in {args.retry_failed_from}.")
    if selected_ids:
        problems = [problem for problem in problems if problem.problem_id in selected_ids]
        missing = selected_ids - {problem.problem_id for problem in problems}
        if missing:
            raise ValueError(f"Problem IDs not found in manifest: {', '.join(sorted(missing))}")
    if args.limit is not None:
        problems = problems[: args.limit]
    if not problems:
        raise ValueError("No problems were selected.")

    stop_event = threading.Event()
    client = AojHttpClient(args.requests_per_second, args.timeout_sec, args.retries, stop_event)
    downloader = AojSuiteDownloader(args.output_root, client.get, stop_event)
    report_path = args.output_root / "prefetch_results.csv"
    report_rows = load_report(report_path)
    rows = []
    interrupted = False
    executor = ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="aoj-prefetch")
    futures: dict[Future, Problem] = {
        executor.submit(downloader.download, problem): problem for problem in problems
    }
    try:
        for completed, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            rows.append(row)
            print(
                f"[{completed}/{len(problems)}] {row['problem_id']}: {row['status']} "
                f"({row['case_count']} cases)",
                flush=True,
            )
    except (KeyboardInterrupt, InterruptedError):
        interrupted = True
        stop_event.set()
        for future in futures:
            future.cancel()
        print("Stopping after in-flight requests finish. Partial suites remain resumable.", flush=True)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        for future, problem in futures.items():
            if future.done() and not future.cancelled() and not any(
                row["problem_id"] == problem.problem_id for row in rows
            ):
                try:
                    rows.append(future.result())
                except InterruptedError:
                    pass
        report_rows.update({row["problem_id"]: row for row in rows})
        write_report(args.output_root, list(report_rows.values()), interrupted)

    print(f"Report: {args.output_root / 'prefetch_results.csv'}")
    print(f"Summary: {args.output_root / 'prefetch_summary.json'}")
    return 130 if interrupted else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prefetch validated AOJ system suites for accepted-C CodeNet problems."
    )
    parser.add_argument(
        "--problem-manifest",
        required=True,
        type=Path,
        help="Accepted-C manifests/problems.csv with problem_id and dataset columns.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/processed/aoj_system_tests"),
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--requests-per-second", type=float, default=8.0)
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=4)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--problem-id",
        action="append",
        help="Restrict retrieval to this CodeNet ID.",
    )
    selection.add_argument(
        "--retry-failed-from",
        type=Path,
        help="Retry only rows whose status is failed in this prefetch_results.csv.",
    )
    parser.add_argument("--limit", type=int, help="Process only the first N selected problems.")
    args = parser.parse_args()
    if args.workers < 1 or args.requests_per_second <= 0 or args.timeout_sec <= 0 or args.retries < 0:
        parser.error("workers, request rate, and timeout must be positive; retries cannot be negative.")
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive.")
    return args


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
