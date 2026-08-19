"""Reproducible C/Rust Judge comparison for benchmark artifacts."""

import csv
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from judge_execution import (
    C_COMPILER_PROFILES,
    compile_c,
    compile_rust,
    judge_result,
    list_input_cases,
    run_oj_suite,
    run_python_io_suite,
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
    compare_mode: str = "ignore-spaces-and-newlines"


@dataclass(frozen=True)
class ProgramCompilation:
    compiler_output: str
    executable: Path | None
    profile: str
    attempts: list[dict]


@dataclass(frozen=True)
class JudgeTarget:
    test_directory: Path
    report_directory: Path
    test_layout: str
    limits: ProblemLimits


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
        with tempfile.TemporaryDirectory(prefix="oxcidation-normalized-judge-") as temp_dir:
            target, missing_reason = self._resolve_target(
                snippet_id,
                problem_id,
                Path(temp_dir),
            )
            if target is None:
                return self._skipped_comparison(missing_reason)

            c_result = evaluate_program(
                "c",
                c_code,
                target.test_directory,
                target.limits,
                self.profile,
            )
            baseline_status = baseline_status_for(c_result)
            if c_result["judge"]["status"] != "ACCEPTED":
                return {
                    "baseline_status": baseline_status,
                    "test_directory": str(target.report_directory),
                    "test_layout": target.test_layout,
                    "limits": target.limits.__dict__,
                    "c": c_result,
                    "rust": skipped_program("C baseline was not accepted on these Judge cases."),
                }

            return {
                "baseline_status": "valid",
                "test_directory": str(target.report_directory),
                "test_layout": target.test_layout,
                "limits": target.limits.__dict__,
                "c": c_result,
                "rust": evaluate_program(
                    "rust",
                    rust_code,
                    target.test_directory,
                    target.limits,
                    self.profile,
                ),
            }

    def evaluate_c_baseline(
        self,
        snippet_id: str,
        problem_id: str,
        c_code: str,
    ) -> dict:
        """Evaluate one C baseline without invoking the Rust translation flow."""
        with tempfile.TemporaryDirectory(prefix="oxcidation-normalized-judge-") as temp_dir:
            target, missing_reason = self._resolve_target(
                snippet_id,
                problem_id,
                Path(temp_dir),
            )
            if target is None:
                skipped = skipped_program(missing_reason)
                return {
                    "baseline_status": "missing",
                    "test_directory": "",
                    "test_layout": "missing",
                    "limits": {},
                    "c": skipped,
                }

            c_result = evaluate_program(
                "c",
                c_code,
                target.test_directory,
                target.limits,
                self.profile,
            )
            return {
                "baseline_status": baseline_status_for(c_result),
                "test_directory": str(target.report_directory),
                "test_layout": target.test_layout,
                "limits": target.limits.__dict__,
                "c": c_result,
            }

    def can_evaluate(self, snippet_id: str, problem_id: str) -> bool:
        return problem_id in self._limits and has_test_cases(
            self.profile.tests_root,
            snippet_id,
            problem_id,
        )

    def _resolve_target(
        self,
        snippet_id: str,
        problem_id: str,
        temporary_root: Path,
    ) -> tuple[JudgeTarget | None, str]:
        limits = self._limits.get(problem_id)
        if limits is None:
            return None, "Problem limits are missing from metadata."

        test_directory, test_layout = resolve_test_directory(
            self.profile.tests_root,
            snippet_id,
            problem_id,
            temporary_root,
        )
        if test_directory is None:
            return None, "No matching Judge cases were found."

        report_key = problem_id
        snippet_directory = self.profile.tests_root / snippet_id
        if test_layout == "io-directory" and snippet_directory.is_dir():
            report_key = snippet_id
        return (
            JudgeTarget(
                test_directory=test_directory,
                report_directory=self.profile.tests_root / report_key,
                test_layout=test_layout,
                limits=limits,
            ),
            "",
        )

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
        if has_paired_io_cases(candidate):
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


def has_test_cases(tests_root: Path, snippet_id: str, problem_id: str) -> bool:
    for key in (snippet_id, problem_id):
        candidate = tests_root / key
        if has_paired_io_cases(candidate):
            return True
        if (candidate / "input.txt").is_file() and (candidate / "output.txt").is_file():
            return True
    return False


def has_paired_io_cases(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    input_paths = list(directory.glob("*.in"))
    return bool(input_paths) and all(
        input_path.with_suffix(".out").is_file() for input_path in input_paths
    )


def skipped_program(reason: str) -> dict:
    return {
        "compile_status": "not_run",
        "compiler_output": "",
        "compile_profile": "",
        "compile_attempts": [],
        "judge": judge_result("SKIPPED", 0, 0, 0, 0, reason),
    }


def baseline_status_for(c_result: dict) -> str:
    if c_result["judge"]["status"] == "ACCEPTED":
        return "valid"
    if c_result["judge"]["status"] == "INFRA_ERROR":
        return "infrastructure_error"
    return "invalid"


def evaluate_program(
    language: str,
    source_code: str,
    test_directory: Path,
    limits: ProblemLimits,
    profile: JudgeProfile,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="oxcidation-judge-program-") as temp_dir:
        compilation = compile_program(language, source_code, Path(temp_dir), profile)
        if compilation.executable is None:
            total = len(list_input_cases(str(test_directory)))
            return {
                "compile_status": "failed",
                "compiler_output": compilation.compiler_output,
                "compile_profile": compilation.profile,
                "compile_attempts": compilation.attempts,
                "judge": judge_result(
                    "COMPILATION_ERROR",
                    0,
                    total,
                    total,
                    0,
                    compilation.compiler_output,
                ),
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
                "compiler_output": compilation.compiler_output,
                "compile_profile": compilation.profile,
                "compile_attempts": compilation.attempts,
                "judge": judge_result(
                    "INFRA_ERROR",
                    0,
                    0,
                    len(list_input_cases(str(test_directory))),
                    0,
                    "Could not start the constrained Judge container.",
                ),
            }
        try:
            command = execution_command(compilation.executable, profile, container_id)
            suite_result = run_judge_suite(
                test_directory,
                command,
                limits.time_limit_ms,
                profile,
            )
        finally:
            stop_execution_container(container_id, profile)
        return {
            "compile_status": "success",
            "compiler_output": compilation.compiler_output,
            "compile_profile": compilation.profile,
            "compile_attempts": compilation.attempts,
            "judge": suite_result,
        }


def compile_program(
    language: str,
    source_code: str,
    work_dir: Path,
    profile: JudgeProfile,
) -> ProgramCompilation:
    if profile.runtime == "local":
        result, executable = (
            compile_c(source_code, str(work_dir))
            if language == "c"
            else compile_rust(source_code, str(work_dir))
        )
        compile_profile = getattr(
            result,
            "compile_profile",
            "rustc" if language == "rust" and result.returncode == 0 else "",
        )
        compile_attempts = getattr(
            result,
            "compile_attempts",
            [
                {
                    "profile": "rustc",
                    "status": "success" if result.returncode == 0 else "failed",
                }
            ],
        )
        return ProgramCompilation(
            compiler_output=result.stderr,
            executable=Path(executable) if result.returncode == 0 else None,
            profile=compile_profile,
            attempts=compile_attempts,
        )

    source_name = "source.c" if language == "c" else "source.rs"
    executable_name = f"program-{language}"
    os.chmod(work_dir, 0o755)
    source_path = work_dir / source_name
    source_path.write_text(source_code, encoding="utf-8")
    os.chmod(source_path, 0o644)
    image = profile.c_image if language == "c" else profile.rust_image
    executable = work_dir / executable_name
    compiler_profiles = _container_compiler_profiles(language, source_name, executable_name)
    attempts = []
    outputs = []
    successful_profile = ""

    for compile_profile, compiler in compiler_profiles:
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
        status = "success" if result.returncode == 0 and executable.is_file() else "failed"
        attempts.append({"profile": compile_profile, "status": status})
        if result.stderr:
            outputs.append(f"[{compile_profile}]\n{result.stderr}")
        if status == "success":
            successful_profile = compile_profile
            break

    return ProgramCompilation(
        compiler_output="\n\n".join(outputs),
        executable=executable if successful_profile else None,
        profile=successful_profile,
        attempts=attempts,
    )


def _container_compiler_profiles(
    language: str,
    source_name: str,
    executable_name: str,
) -> list[tuple[str, list[str]]]:
    if language == "rust":
        return [
            (
                "rustc",
                [
                    "rustc",
                    "-O",
                    f"/work/{source_name}",
                    "-o",
                    f"/work/{executable_name}",
                ],
            )
        ]

    return [
        (
            compile_profile,
            [
                "gcc",
                *flags,
                "-O2",
                "-pipe",
                f"/work/{source_name}",
                "-o",
                f"/work/{executable_name}",
                "-lm",
            ],
        )
        for compile_profile, flags in C_COMPILER_PROFILES
    ]


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
    profile: JudgeProfile,
) -> dict:
    timeout_sec = time_limit_ms / 1000
    if profile.backend in {"auto", "oj"} and shutil.which("oj"):
        return run_oj_suite(str(test_directory), command, timeout_sec, profile.compare_mode)
    if " " not in command:
        return run_python_io_suite(str(test_directory), command, timeout_sec)
    return judge_result(
        "INFRA_ERROR",
        0,
        0,
        len(list_input_cases(str(test_directory))),
        0,
        "online-judge-tools is required for containerized Judge execution.",
    )
