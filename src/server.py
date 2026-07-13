from mcp.server.fastmcp import FastMCP
import subprocess
import tempfile
import os
import sys
import json
import logging
import re
import shutil
import time
from pydantic import BaseModel, Field
from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from config import ConfigDetails
from rate_limit import RequestRateLimiter

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [SERVER:%(levelname)s] %(message)s",
)
logging.getLogger("mcp").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

mcp = FastMCP("RustToolkitRunnerServer")

configs = ConfigDetails()
request_rate_limiter = RequestRateLimiter(configs.request_rate_limit_rpm)

OJ_VERDICT_RE = re.compile(r"\[(?:SUCCESS|FAILURE)\]\s+(AC|WA|TLE|MLE|RE)\b")
OJ_FAILED_SUMMARY_RE = re.compile(r"test failed:\s+(\d+)\s+AC\s*/\s*(\d+)\s+cases")
OJ_SUCCESS_SUMMARY_RE = re.compile(r"test success:\s+(\d+)\s+cases")
OJ_STATUS_BY_VERDICT = {
    "AC": "ACCEPTED",
    "WA": "WRONG_ANSWER",
    "TLE": "TIME_LIMIT_EXCEEDED",
    "MLE": "MEMORY_LIMIT_EXCEEDED",
    "RE": "RUNTIME_ERROR",
}
JUDGE_STATUS_PRIORITY = [
    "TIME_LIMIT_EXCEEDED",
    "MEMORY_LIMIT_EXCEEDED",
    "RUNTIME_ERROR",
    "WRONG_ANSWER",
    "INFRA_ERROR",
]


class TranslationResult(BaseModel):
    reasoning: str = Field(
        description="A concise translation rationale without hidden chain-of-thought."
    )
    rust_code: str = Field(
        description="The raw, unformatted Rust code. Do not use markdown backticks."
    )


class SemanticValidationResult(BaseModel):
    diagnosis: str = Field(description="Concise diagnosis of the differential test failure.")
    repair_guidance: str = Field(description="Concrete repair guidance for the Rust translation.")
    semantic_discrepancies: list[str] = Field(
        description="Likely semantic discrepancies supported by the test report."
    )


def _base_name(file_name: str) -> str:
    return file_name.replace(".c", "")


def clean_markdown_code(raw_code: str) -> str:
    """Removes markdown code block wrappers from a model response."""
    match = re.search(r"```[a-zA-Z]*\n(.*?)\n?```", raw_code, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw_code.strip()


def get_llm():
    provider = configs.llm_provider.lower()

    if provider == "ollama":
        kwargs = {
            "model": configs.llm_model,
            "base_url": configs.ollama_base_url,
            "temperature": 0,
        }
        
        if configs.think is False:
            kwargs["think"] = False
            
        return ChatOllama(**kwargs)

    elif provider == "openrouter":
        return ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY", "dummy"),
            model=configs.llm_model
        )

    elif provider == "openai":
        return ChatOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "dummy"),
            model=configs.llm_model
        )

    elif provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set when provider is gemini.")
        return ChatOpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=api_key,
            model=configs.llm_model,
            temperature=0,
            max_retries=0,
        )

    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")


def invoke_llm(llm, prompt: str):
    request_rate_limiter.wait_for_slot()
    return llm.invoke(prompt)


def _compile_c(c_code: str, temp_dir: str):
    c_file_path = os.path.join(temp_dir, "prog.c")
    c_bin_path = os.path.join(temp_dir, "prog_c")
    with open(c_file_path, "w") as f:
        f.write(c_code)

    result = subprocess.run(
        ["gcc", c_file_path, "-o", c_bin_path, "-lm"],
        capture_output=True,
        text=True,
    )
    return result, c_bin_path


def _compile_rust(rust_code: str, temp_dir: str):
    rust_file_path = os.path.join(temp_dir, "prog.rs")
    rust_bin_path = os.path.join(temp_dir, "prog_rust")
    with open(rust_file_path, "w") as f:
        f.write(rust_code)

    result = subprocess.run(
        ["rustc", rust_file_path, "-o", rust_bin_path],
        capture_output=True,
        text=True,
    )
    return result, rust_bin_path


def _list_input_cases(test_dir: str):
    return sorted([f for f in os.listdir(test_dir) if f.endswith(".in")])


def _empty_verdict_counts() -> dict:
    return {
        "ACCEPTED": 0,
        "WRONG_ANSWER": 0,
        "TIME_LIMIT_EXCEEDED": 0,
        "MEMORY_LIMIT_EXCEEDED": 0,
        "RUNTIME_ERROR": 0,
        "INFRA_ERROR": 0,
    }


def _judge_result(
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
        "verdict_counts": verdict_counts or _empty_verdict_counts(),
        "first_failure": first_failure or {},
        "raw_output": raw_output,
    }


def _aggregate_judge_status(verdict_counts: dict, returncode: int) -> str:
    if returncode == 0:
        return "ACCEPTED"

    for status in JUDGE_STATUS_PRIORITY:
        if verdict_counts.get(status, 0):
            return status

    return "INFRA_ERROR"


def _strip_oj_update_noise(output: str) -> str:
    noisy_fragments = [
        "https://pypi.org/pypi/online-judge-tools/json",
        "failed to check update",
    ]
    lines = [
        line for line in output.splitlines()
        if not any(fragment in line for fragment in noisy_fragments)
    ]
    return "\n".join(lines).strip()


def _is_oj_case_info(text: str) -> bool:
    ignored_prefixes = (
        "time:",
        "slowest:",
        "max memory:",
        "online-judge-tools",
    )
    return not text.startswith(ignored_prefixes) and "cases found" not in text


def _first_failure_from_oj_output(output: str) -> dict:
    lines = output.splitlines()
    for index, line in enumerate(lines):
        match = OJ_VERDICT_RE.search(line)
        if not match or match.group(1) == "AC":
            continue

        case_name = ""
        for previous in reversed(lines[:index]):
            info_match = re.match(r"\[INFO\]\s+(.+)", previous)
            if info_match and _is_oj_case_info(info_match.group(1).strip()):
                case_name = info_match.group(1).strip()
                break

        excerpt = "\n".join(lines[index:index + 20]).strip()
        return {
            "case": case_name,
            "verdict": OJ_STATUS_BY_VERDICT.get(match.group(1), "INFRA_ERROR"),
            "excerpt": excerpt,
        }

    return {}


def _classify_oj_output(
    returncode: int,
    output: str,
    total: int,
    elapsed_ms: int,
) -> dict:
    cleaned_output = _strip_oj_update_noise(output)
    verdict_counts = _empty_verdict_counts()

    for verdict in OJ_VERDICT_RE.findall(cleaned_output):
        status = OJ_STATUS_BY_VERDICT.get(verdict, "INFRA_ERROR")
        verdict_counts[status] += 1

    success_summary = OJ_SUCCESS_SUMMARY_RE.search(cleaned_output)
    failed_summary = OJ_FAILED_SUMMARY_RE.search(cleaned_output)
    if success_summary and not verdict_counts["ACCEPTED"]:
        verdict_counts["ACCEPTED"] = int(success_summary.group(1))

    if failed_summary:
        passed = int(failed_summary.group(1))
        total = int(failed_summary.group(2))
    else:
        passed = verdict_counts["ACCEPTED"] if returncode == 0 else 0

    status = _aggregate_judge_status(verdict_counts, returncode)
    failed = max(total - passed, 0)
    first_failure = _first_failure_from_oj_output(cleaned_output)

    details = f"oj status={status}; passed={passed}; failed={failed}; total={total}"
    if first_failure:
        details = f"{details}; first_failure={first_failure['verdict']}"

    return _judge_result(
        status=status,
        passed=passed,
        failed=failed,
        total=total,
        time_ms=elapsed_ms,
        details=details,
        verdict_counts=verdict_counts,
        first_failure=first_failure,
        raw_output=cleaned_output,
    )


def _run_python_io_suite(test_dir: str, command: str, timeout_sec: int) -> dict:
    in_files = _list_input_cases(test_dir)
    verdict_counts = _empty_verdict_counts()
    first_failure = {}
    details = []

    started_at = time.time()
    for in_file in in_files:
        out_file = in_file.replace(".in", ".out")
        in_path = os.path.join(test_dir, in_file)
        out_path = os.path.join(test_dir, out_file)

        with open(in_path, "r") as f:
            input_data = f.read()

        expected_output = ""
        if os.path.exists(out_path):
            with open(out_path, "r") as f:
                expected_output = f.read()

        try:
            run = subprocess.run(
                [command],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            verdict_counts["TIME_LIMIT_EXCEEDED"] += 1
            message = f"Test {in_file} exceeded {timeout_sec}s."
            details.append(message)
            if not first_failure:
                first_failure = {
                    "case": in_file,
                    "verdict": "TIME_LIMIT_EXCEEDED",
                    "excerpt": message,
                }
            continue

        if run.returncode != 0:
            verdict_counts["RUNTIME_ERROR"] += 1
            message = f"Test {in_file} runtime error:\n{run.stderr[:1000]}"
            details.append(message)
            if not first_failure:
                first_failure = {
                    "case": in_file,
                    "verdict": "RUNTIME_ERROR",
                    "excerpt": message,
                }
            continue

        if run.stdout.split() == expected_output.split():
            verdict_counts["ACCEPTED"] += 1
        else:
            expected_lines = "\n".join(expected_output.splitlines()[:10])
            actual_lines = "\n".join(run.stdout.splitlines()[:10])
            verdict_counts["WRONG_ANSWER"] += 1
            message = (
                f"Test {in_file} failed.\n"
                f"Expected (first 10 lines):\n{expected_lines}\n\n"
                f"Actual (first 10 lines):\n{actual_lines}\n\n"
            )
            details.append(message)
            if not first_failure:
                first_failure = {
                    "case": in_file,
                    "verdict": "WRONG_ANSWER",
                    "excerpt": message,
                }

    elapsed_ms = int((time.time() - started_at) * 1000)
    passed = verdict_counts["ACCEPTED"]
    total = len(in_files)
    failed = max(total - passed, 0)
    status = "ACCEPTED" if failed == 0 else _aggregate_judge_status(verdict_counts, 1)

    return _judge_result(
        status=status,
        passed=passed,
        failed=failed,
        total=total,
        time_ms=elapsed_ms,
        details="\n".join(details) or f"All {total} judge cases passed.",
        verdict_counts=verdict_counts,
        first_failure=first_failure,
    )


def _run_oj_suite(test_dir: str, command: str, timeout_sec: int) -> dict:
    if not shutil.which("oj"):
        return _judge_result(
            status="INFRA_ERROR",
            passed=0,
            failed=0,
            total=0,
            time_ms=0,
            details="online-judge-tools executable 'oj' was not found.",
        )

    env = _oj_env()
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
        configs.judge_compare_mode,
        "--display-mode",
        "all",
        "--tle",
        str(timeout_sec),
    ]

    started_at = time.time()
    run = subprocess.run(args, capture_output=True, text=True, env=env)
    elapsed_ms = int((time.time() - started_at) * 1000)
    output = f"{run.stdout}\n{run.stderr}".strip()
    total = len(_list_input_cases(test_dir))
    return _classify_oj_output(run.returncode, output, total, elapsed_ms)


def _run_judge_suite(test_dir: str, command: str) -> dict:
    backend = configs.judge_backend.lower()
    if backend in ["auto", "oj"] and shutil.which("oj"):
        return _run_oj_suite(test_dir, command, configs.judge_time_limit_sec)

    return _run_python_io_suite(test_dir, command, configs.judge_time_limit_sec)


def _oj_env() -> dict:
    import onlinejudge.__about__ as api_version
    import onlinejudge_command.__about__ as command_version

    cache_root = os.path.join(tempfile.gettempdir(), "oxcidation-oj-cache")
    oj_cache_dir = os.path.join(cache_root, "online-judge-tools")
    os.makedirs(oj_cache_dir, exist_ok=True)

    cache_path = os.path.join(oj_cache_dir, "pypi.json")
    if not os.path.exists(cache_path):
        now = int(time.time())
        with open(cache_path, "w") as f:
            json.dump({
                "online-judge-tools": {
                    "time": now,
                    "version": command_version.__version__,
                },
                "online-judge-api-client": {
                    "time": now,
                    "version": api_version.__version__,
                },
            }, f)

    env = os.environ.copy()
    env["XDG_CACHE_HOME"] = cache_root
    return env


@mcp.tool()
def compile_rust_code(source_code: str) -> str:
    """
    Compiles a Rust snippet using rustc and returns the compiler output.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        result, _ = _compile_rust(source_code, temp_dir)

        if result.returncode == 0:
            return f"Success:\n{result.stdout}"

        return f"Compilation Failed:\n{result.stderr}"


@mcp.tool()
def translate_c_to_rust(c_code: str, prompt_template: str | None = None) -> str:
    """
    Translates C code to Rust using an LLM.
    Returns a JSON string containing the rust_code and token usage.
    """
    llm = get_llm()
    if prompt_template is None:
        with open("prompts/direct_translation_prompt.txt", "r", encoding="utf-8") as f:
            prompt_template = f.read()
    base_prompt = prompt_template.replace("{c_code}", c_code)
    structured_prompt = (
        f"{base_prompt}\n\n"
        "For the structured response, include a concise translation rationale that lists "
        "the important behavior-preserving choices. Do not provide hidden chain-of-thought."
    )

    try:
        structured_llm = llm.with_structured_output(
            TranslationResult, method="json_schema", strict=True
        )
        response = invoke_llm(structured_llm, structured_prompt)

        rust_code = clean_markdown_code(response.rust_code)
        raw_model_output = response.rust_code
        translation_reasoning = response.reasoning
        prompt_tokens = 0
        completion_tokens = 0

        logger.info("Translation completed with structured output.")

    except Exception as strict_err:
        logger.warning(
            f"Strict structured output failed (Model likely does not support json_schema). "
            f"Falling back to basic JSON mode. Error: {str(strict_err)}"
        )

        try:
            fallback_llm = llm.bind(response_format={"type": "json_object"})
            parser = JsonOutputParser(pydantic_object=TranslationResult)

            fallback_prompt = (
                "You are an expert C to Rust translator.\n"
                f"{parser.get_format_instructions()}\n\n"
                f"{structured_prompt}"
            )

            fallback_response = invoke_llm(fallback_llm, fallback_prompt)
            parsed_json = parser.invoke(fallback_response.content)

            raw_rust = parsed_json.get("rust_code", "")
            rust_code = clean_markdown_code(raw_rust)
            raw_model_output = fallback_response.content
            translation_reasoning = parsed_json.get("reasoning", "")

            prompt_tokens = (
                fallback_response.usage_metadata.get("input_tokens", 0)
                if fallback_response.usage_metadata
                else 0
            )
            completion_tokens = (
                fallback_response.usage_metadata.get("output_tokens", 0)
                if fallback_response.usage_metadata
                else 0
            )

        except Exception as fallback_err:
            logger.error(f"Fallback JSON parsing also failed: {str(fallback_err)}")
            if "fallback_response" in locals():
                logger.error(f"Raw Model Output was:\n{fallback_response.content}")
            return json.dumps(
                {
                    "rust_code": "",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "raw_model_output": "",
                    "translation_reasoning": "",
                    "error": f"LLM parsing failed completely: {str(fallback_err)}",
                }
            )

    orchestrator_payload = {
        "rust_code": rust_code,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "raw_model_output": raw_model_output,
        "translation_reasoning": translation_reasoning,
    }

    return json.dumps(orchestrator_payload)


@mcp.tool()
def repair_rust_code(
    rust_code: str,
    errors: str,
    failure_category: str = "correctness",
) -> str:
    """
    Repairs Rust code based on compiler errors or test failures using an LLM.
    """
    llm = get_llm()
    
    repair_prompt = (
        f"You are an expert Rust developer. Fix this Rust code.\n"
        f"Failure category: {failure_category}\n\n"
        f"Code:\n{rust_code}\n\n"
        f"Issues:\n{errors}\n\n"
        f"Return ONLY the fixed Rust code, no explanations or markdown wrappers."
    )
    
    try:
        response = invoke_llm(llm, repair_prompt)
        repaired_code = clean_markdown_code(response.content)
        logger.info("Repair completed successfully")
        return repaired_code
    except Exception as e:
        logger.error(f"Repair failed: {str(e)}")
        return ""


@mcp.tool()
def analyze_translation_discrepancy(
    c_code: str,
    rust_code: str,
    test_report: dict,
) -> str:
    """Diagnoses visible differential test failures and returns repair guidance."""
    llm = get_llm()
    report_json = json.dumps(test_report, ensure_ascii=False)
    analysis_prompt = (
        "You are a code validation specialist for behavior-preserving C to Rust translation.\n"
        "Analyze the C source, Rust translation, and differential visible-test report below. "
        "Identify only discrepancies supported by the report or source comparison. "
        "Provide concise, concrete repair guidance without redesigning the algorithm. "
        "Do not reveal hidden chain-of-thought.\n\n"
        f"C source:\n{c_code}\n\n"
        f"Rust translation:\n{rust_code}\n\n"
        f"Differential test report:\n{report_json}"
    )

    try:
        structured_llm = llm.with_structured_output(
            SemanticValidationResult,
            method="json_schema",
            strict=True,
        )
        response = invoke_llm(structured_llm, analysis_prompt)
        return json.dumps(response.model_dump())
    except Exception as strict_err:
        logger.warning("Structured validator analysis failed: %s", strict_err)
        try:
            fallback_llm = llm.bind(response_format={"type": "json_object"})
            parser = JsonOutputParser(pydantic_object=SemanticValidationResult)
            fallback_prompt = f"{parser.get_format_instructions()}\n\n{analysis_prompt}"
            response = invoke_llm(fallback_llm, fallback_prompt)
            return json.dumps(parser.invoke(response.content))
        except Exception as fallback_err:
            raise RuntimeError(f"Validator analysis failed: {fallback_err}") from fallback_err


@mcp.tool()
def evaluate_test_cases(file_name: str, c_code: str, rust_code: str) -> str:
    """
    Compiles and evaluates both C and Rust code against I/O test cases.
    """
    base_name = _base_name(file_name)
    test_dir = os.path.join("data/processed/tests", base_name)
    
    if not os.path.exists(test_dir):
        return json.dumps({
            "status": "skipped",
            "reason": f"No tests found for {file_name} in {test_dir}"
        })
        
    in_files = _list_input_cases(test_dir)
    if not in_files:
        return json.dumps({
            "status": "skipped",
            "reason": f"No .in files found in {test_dir}"
        })
        
    result = {
        "status": "success",
        "c_compilation": "success",
        "rust_compilation": "success",
        "total_tests": len(in_files),
        "c_passed": 0,
        "c_failed": 0,
        "rust_passed": 0,
        "rust_failed": 0,
        "failed_rust_where_c_passed": 0,
        "passed_rust_where_c_failed": 0,
        "failed_tests": [],
        "details": ""
    }
    
    with tempfile.TemporaryDirectory() as temp_dir:
        c_compile, c_bin_path = _compile_c(c_code, temp_dir)
        if c_compile.returncode != 0:
            result["c_compilation"] = "failed"
            result["status"] = "c_failed_compilation"
            result["details"] = c_compile.stderr
            return json.dumps(result)
            
        rust_compile, rust_bin_path = _compile_rust(rust_code, temp_dir)
        if rust_compile.returncode != 0:
            result["rust_compilation"] = "failed"
            result["status"] = "failed"
            result["details"] = rust_compile.stderr
            return json.dumps(result)
            
        for in_file in in_files:
            out_file = in_file.replace(".in", ".out")
            in_path = os.path.join(test_dir, in_file)
            out_path = os.path.join(test_dir, out_file)
            
            with open(in_path, "r") as f:
                input_data = f.read()
                
            expected_output = ""
            if os.path.exists(out_path):
                with open(out_path, "r") as f:
                    expected_output = f.read()

            try:
                c_run = subprocess.run(
                    [c_bin_path],
                    input=input_data,
                    capture_output=True,
                    text=True,
                    timeout=configs.judge_time_limit_sec,
                )
                c_out = c_run.stdout
            except subprocess.TimeoutExpired:
                c_out = "TIMEOUT"

            try:
                rust_run = subprocess.run(
                    [rust_bin_path],
                    input=input_data,
                    capture_output=True,
                    text=True,
                    timeout=configs.judge_time_limit_sec,
                )
                rust_out = rust_run.stdout
            except subprocess.TimeoutExpired:
                rust_out = "TIMEOUT"
                
            c_passed = (c_out.split() == expected_output.split())
            rust_passed = (rust_out.split() == expected_output.split())
            
            if c_passed:
                result["c_passed"] += 1
            else:
                result["c_failed"] += 1
                
            if rust_passed:
                result["rust_passed"] += 1
            else:
                result["rust_failed"] += 1
            
            if c_passed and not rust_passed:
                result["status"] = "failed"
                result["failed_tests"].append(in_file)
                result["failed_rust_where_c_passed"] += 1
                expected_lines = "\n".join(expected_output.splitlines()[:10])
                rust_lines = "\n".join(rust_out.splitlines()[:10])
                result["details"] += f"Test {in_file} failed.\nExpected (first 10 lines):\n{expected_lines}\n\nRust Output (first 10 lines):\n{rust_lines}\n\n"
            elif rust_passed and not c_passed:
                result["passed_rust_where_c_failed"] += 1
                
    return json.dumps(result)


@mcp.tool()
def evaluate_judge_cases(file_name: str, rust_code: str) -> str:
    """
    Compiles Rust and evaluates it against holdout judge cases.
    """
    base_name = _base_name(file_name)
    judge_dir = os.path.join("data/processed/judge_tests", base_name)

    if not os.path.exists(judge_dir):
        return json.dumps(
            _judge_result(
                status="SKIPPED",
                passed=0,
                failed=0,
                total=0,
                time_ms=0,
                details=f"No judge tests found for {file_name} in {judge_dir}",
            )
        )

    if not _list_input_cases(judge_dir):
        return json.dumps(
            _judge_result(
                status="SKIPPED",
                passed=0,
                failed=0,
                total=0,
                time_ms=0,
                details=f"No .in files found in {judge_dir}",
            )
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        rust_compile, rust_bin_path = _compile_rust(rust_code, temp_dir)
        if rust_compile.returncode != 0:
            total = len(_list_input_cases(judge_dir))
            return json.dumps(
                _judge_result(
                    status="COMPILATION_ERROR",
                    passed=0,
                    failed=total,
                    total=total,
                    time_ms=0,
                    details=rust_compile.stderr,
                    first_failure={
                        "case": "compile",
                        "verdict": "COMPILATION_ERROR",
                        "excerpt": rust_compile.stderr[:1000],
                    },
                )
            )

        return json.dumps(_run_judge_suite(judge_dir, rust_bin_path))


if __name__ == "__main__":
    mcp.run()
