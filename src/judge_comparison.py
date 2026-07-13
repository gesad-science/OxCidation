"""Reproducible C/Rust Judge comparison for benchmark artifacts."""

import csv
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from server import (
    _compile_c,
    _compile_rust,
    _judge_result,
    _list_input_cases,
    _run_oj_suite,
    _run_python_io_suite,
)


@dataclass(frozen=True)
class ProblemLimits:
    time_limit_ms: int
    memory_limit_kib: int


@dataclass(frozen=True)
class JudgeProfile:
    tests_root: Path
    metadata_root: Path
    runtime: str = "podman"
    c_image: str = "docker.io/library/gcc:5.4"
    rust_image: str = "docker.io/library/rust:1.85.0-bookworm"
    backend: str = "auto"


class JudgeComparison:
    def __init__(self, profile: JudgeProfile):
        self.profile = profile
        self._limits = self._load_limits(profile.metadata_root / "problem_list.csv")

    def evaluate(
        self,
        snippet_id: str,
        problem_id: str,
        c_code: str,
        rust_code: str,
    ) -> dict:
        limits = self._limits.get(problem_id)
        if limits is None:
            return self._skipped_comparison("Problem limits are missing from metadata.")

        with tempfile.TemporaryDirectory(prefix="oxcidation-normalized-judge-") as temp_dir:
            test_directory, test_layout = resolve_test_directory(
                self.profile.tests_root,
                snippet_id,
                problem_id,
                Path(temp_dir),
            )
            if test_directory is None:
                return self._skipped_comparison("No matching Judge cases were found.")

            report_directory = self.profile.tests_root / (
                snippet_id if test_layout == "io-directory" and (self.profile.tests_root / snippet_id).is_dir()
                else problem_id
            )
            c_result = evaluate_program("c", c_code, test_directory, limits, self.profile)
            if c_result["judge"]["status"] != "ACCEPTED":
                return {
                    "baseline_status": "invalid",
                    "test_directory": str(report_directory),
                    "test_layout": test_layout,
                    "limits": limits.__dict__,
                    "c": c_result,
                    "rust": skipped_program("C baseline was not accepted on these Judge cases."),
                }

            return {
                "baseline_status": "valid",
                "test_directory": str(report_directory),
                "test_layout": test_layout,
                "limits": limits.__dict__,
                "c": c_result,
                "rust": evaluate_program("rust", rust_code, test_directory, limits, self.profile),
            }

    @staticmethod
    def _load_limits(path: Path) -> dict[str, ProblemLimits]:
        if not path.is_file():
            raise FileNotFoundError(f"Missing CodeNet problem metadata: {path}")
        with path.open(newline="", encoding="utf-8") as metadata_file:
            limits = {}
            for row in csv.DictReader(metadata_file):
                try:
                    limits[row["id"]] = ProblemLimits(
                        time_limit_ms=int(row["time_limit"]),
                        memory_limit_kib=int(row["memory_limit"]),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            return limits

    @staticmethod
    def _skipped_comparison(reason: str) -> dict:
        return {
            "baseline_status": "missing",
            "test_directory": "",
            "test_layout": "missing",
            "limits": {},
            "c": skipped_program(reason),
            "rust": skipped_program(reason),
        }


def resolve_test_directory(
    tests_root: Path,
    snippet_id: str,
    problem_id: str,
    temporary_root: Path,
) -> tuple[Path | None, str]:
    for key in (snippet_id, problem_id):
        candidate = tests_root / key
        if candidate.is_dir() and _list_input_cases(str(candidate)):
            return candidate, "io-directory"

        input_path = candidate / "input.txt"
        output_path = candidate / "output.txt"
        if input_path.is_file() and output_path.is_file():
            normalized = temporary_root / key
            normalized.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(input_path, normalized / "1.in")
            shutil.copyfile(output_path, normalized / "1.out")
            return normalized, "codenet-single-case"
    return None, "missing"


def skipped_program(reason: str) -> dict:
    return {
        "compile_status": "not_run",
        "compiler_output": "",
        "judge": _judge_result("SKIPPED", 0, 0, 0, 0, reason),
    }


def evaluate_program(
    language: str,
    source_code: str,
    test_directory: Path,
    limits: ProblemLimits,
    profile: JudgeProfile,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="oxcidation-judge-program-") as temp_dir:
        compiler_output, executable = compile_program(language, source_code, Path(temp_dir), profile)
        if executable is None:
            total = len(_list_input_cases(str(test_directory)))
            return {
                "compile_status": "failed",
                "compiler_output": compiler_output,
                "judge": _judge_result("COMPILATION_ERROR", 0, total, total, 0, compiler_output),
            }

        container_id = start_execution_container(
            Path(temp_dir),
            language,
            limits,
            profile,
        )
        if container_id is None:
            return {
                "compile_status": "success",
                "compiler_output": compiler_output,
                "judge": _judge_result(
                    "INFRA_ERROR",
                    0,
                    0,
                    len(_list_input_cases(str(test_directory))),
                    0,
                    "Could not start the constrained Judge container.",
                ),
            }
        try:
            command = execution_command(executable, profile, container_id)
            judge_result = run_judge_suite(test_directory, command, limits.time_limit_ms, profile.backend)
        finally:
            stop_execution_container(container_id, profile)
        return {
            "compile_status": "success",
            "compiler_output": compiler_output,
            "judge": judge_result,
        }


def compile_program(
    language: str,
    source_code: str,
    work_dir: Path,
    profile: JudgeProfile,
) -> tuple[str, Path | None]:
    if profile.runtime == "local":
        result, executable = (
            _compile_c(source_code, str(work_dir))
            if language == "c"
            else _compile_rust(source_code, str(work_dir))
        )
        return result.stderr, Path(executable) if result.returncode == 0 else None

    source_name = "source.c" if language == "c" else "source.rs"
    executable_name = f"program-{language}"
    os.chmod(work_dir, 0o755)
    source_path = work_dir / source_name
    source_path.write_text(source_code, encoding="utf-8")
    os.chmod(source_path, 0o644)
    image = profile.c_image if language == "c" else profile.rust_image
    compiler = ["gcc", "-O2", "-pipe", f"/work/{source_name}", "-o", f"/work/{executable_name}", "-lm"]
    if language == "rust":
        compiler = ["rustc", "-O", f"/work/{source_name}", "-o", f"/work/{executable_name}"]
    command = [
        profile.runtime,
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{work_dir}:/work:Z",
        image,
        *compiler,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    executable = work_dir / executable_name
    return result.stderr, executable if result.returncode == 0 and executable.is_file() else None


def execution_command(
    executable: Path,
    profile: JudgeProfile,
    container_id: str | None = None,
) -> str:
    if profile.runtime == "local":
        return str(executable)
    return shlex.join(
        [profile.runtime, "exec", "--interactive", container_id or "", f"/work/{executable.name}"]
    )


def start_execution_container(
    work_dir: Path,
    language: str,
    limits: ProblemLimits,
    profile: JudgeProfile,
) -> str | None:
    if profile.runtime == "local":
        return "local"

    image = profile.c_image if language == "c" else profile.rust_image
    memory_bytes = limits.memory_limit_kib * 1024
    command = [
        profile.runtime,
        "run",
        "--detach",
        "--rm",
        "--network",
        "none",
        "--memory",
        f"{limits.memory_limit_kib}k",
        "--memory-swap",
        f"{limits.memory_limit_kib + 1}k",
        "--ulimit",
        f"stack={memory_bytes}:{memory_bytes}",
        "-v",
        f"{work_dir}:/work:ro,Z",
        image,
        "sleep",
        "infinity",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def stop_execution_container(container_id: str, profile: JudgeProfile) -> None:
    if profile.runtime != "local":
        subprocess.run(
            [profile.runtime, "stop", container_id],
            capture_output=True,
            text=True,
        )


def run_judge_suite(
    test_directory: Path,
    command: str,
    time_limit_ms: int,
    backend: str,
) -> dict:
    timeout_sec = time_limit_ms / 1000
    if backend in {"auto", "oj"} and shutil.which("oj"):
        return _run_oj_suite(str(test_directory), command, timeout_sec)
    if " " not in command:
        return _run_python_io_suite(str(test_directory), command, timeout_sec)
    return _judge_result(
        "INFRA_ERROR",
        0,
        0,
        len(_list_input_cases(str(test_directory))),
        0,
        "online-judge-tools is required for containerized Judge execution.",
    )


def comparison_to_json(comparison: dict) -> str:
    return json.dumps(comparison, ensure_ascii=False, indent=2)
