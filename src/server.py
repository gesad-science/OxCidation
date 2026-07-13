"""MCP tools for model interaction and visible-test execution."""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile

from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from config import ConfigDetails
from judge_execution import compile_c, compile_rust, list_input_cases
from rate_limit import RequestRateLimiter

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [SERVER:%(levelname)s] %(message)s",
)
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
mcp = FastMCP("RustToolkitRunnerServer")
configs = ConfigDetails()
request_rate_limiter = RequestRateLimiter(configs.request_rate_limit_rpm)


class TranslationResult(BaseModel):
    reasoning: str = Field(
        description="A concise translation rationale without hidden chain-of-thought."
    )
    rust_code: str = Field(description="Raw Rust code without markdown backticks.")


class SemanticValidationResult(BaseModel):
    diagnosis: str = Field(description="Concise diagnosis of the differential test failure.")
    repair_guidance: str = Field(description="Concrete repair guidance for the Rust translation.")
    semantic_discrepancies: list[str] = Field(
        description="Likely semantic discrepancies supported by the test report."
    )


def clean_markdown_code(raw_code: str) -> str:
    match = re.search(r"```[a-zA-Z]*\n(.*?)\n?```", raw_code, re.DOTALL)
    return match.group(1).strip() if match else raw_code.strip()


def get_llm():
    provider = configs.llm_provider.lower()
    if provider == "ollama":
        arguments = {
            "model": configs.llm_model,
            "base_url": configs.ollama_base_url,
            "temperature": 0,
        }
        if configs.think is False:
            arguments["think"] = False
        return ChatOllama(**arguments)
    if provider == "openrouter":
        return ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY", "dummy"),
            model=configs.llm_model,
        )
    if provider == "openai":
        return ChatOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "dummy"),
            model=configs.llm_model,
        )
    if provider == "gemini":
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
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")


def invoke_llm(llm, prompt: str):
    request_rate_limiter.wait_for_slot()
    return llm.invoke(prompt)


@mcp.tool()
def compile_rust_code(source_code: str) -> str:
    """Compiles Rust and returns compiler output."""
    with tempfile.TemporaryDirectory() as temp_dir:
        result, _ = compile_rust(source_code, temp_dir)
    return f"Success:\n{result.stdout}" if result.returncode == 0 else f"Compilation Failed:\n{result.stderr}"


@mcp.tool()
def translate_c_to_rust(c_code: str, prompt_template: str | None = None) -> str:
    """Translates C to Rust and returns a structured response."""
    if prompt_template is None:
        with open("prompts/direct_translation_prompt.txt", encoding="utf-8") as prompt_file:
            prompt_template = prompt_file.read()
    prompt = (
        f"{prompt_template.replace('{c_code}', c_code)}\n\n"
        "For the structured response, include a concise translation rationale that lists "
        "the important behavior-preserving choices. Do not provide hidden chain-of-thought."
    )
    llm = get_llm()
    try:
        response = invoke_llm(
            llm.with_structured_output(TranslationResult, method="json_schema", strict=True),
            prompt,
        )
        return json.dumps(
            {
                "rust_code": clean_markdown_code(response.rust_code),
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "raw_model_output": response.rust_code,
                "translation_reasoning": response.reasoning,
            }
        )
    except Exception as strict_error:
        logger.warning("Structured translation failed: %s", strict_error)
        try:
            parser = JsonOutputParser(pydantic_object=TranslationResult)
            response = invoke_llm(
                llm.bind(response_format={"type": "json_object"}),
                f"You are an expert C to Rust translator.\n{parser.get_format_instructions()}\n\n{prompt}",
            )
            payload = parser.invoke(response.content)
            usage = response.usage_metadata or {}
            return json.dumps(
                {
                    "rust_code": clean_markdown_code(payload.get("rust_code", "")),
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "raw_model_output": response.content,
                    "translation_reasoning": payload.get("reasoning", ""),
                }
            )
        except Exception as fallback_error:
            return json.dumps(
                {
                    "rust_code": "",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "raw_model_output": "",
                    "translation_reasoning": "",
                    "error": f"LLM parsing failed completely: {fallback_error}",
                }
            )


@mcp.tool()
def repair_rust_code(rust_code: str, errors: str, failure_category: str = "correctness") -> str:
    """Repairs Rust code from a compiler or visible-test report."""
    prompt = (
        "You are an expert Rust developer. Fix this Rust code.\n"
        f"Failure category: {failure_category}\n\nCode:\n{rust_code}\n\n"
        f"Issues:\n{errors}\n\nReturn ONLY fixed Rust code without markdown."
    )
    try:
        return clean_markdown_code(invoke_llm(get_llm(), prompt).content)
    except Exception as error:
        logger.error("Repair failed: %s", error)
        return ""


@mcp.tool()
def analyze_translation_discrepancy(c_code: str, rust_code: str, test_report: dict) -> str:
    """Diagnoses a visible differential failure and produces repair guidance."""
    prompt = (
        "You are a code validation specialist for behavior-preserving C to Rust translation.\n"
        "Analyze the C source, Rust translation, and differential visible-test report. "
        "Identify only supported discrepancies and give concise repair guidance. "
        "Do not reveal hidden chain-of-thought.\n\n"
        f"C source:\n{c_code}\n\nRust translation:\n{rust_code}\n\n"
        f"Differential test report:\n{json.dumps(test_report, ensure_ascii=False)}"
    )
    llm = get_llm()
    try:
        response = invoke_llm(
            llm.with_structured_output(SemanticValidationResult, method="json_schema", strict=True),
            prompt,
        )
        return json.dumps(response.model_dump())
    except Exception as strict_error:
        logger.warning("Structured validator analysis failed: %s", strict_error)
        parser = JsonOutputParser(pydantic_object=SemanticValidationResult)
        response = invoke_llm(
            llm.bind(response_format={"type": "json_object"}),
            f"{parser.get_format_instructions()}\n\n{prompt}",
        )
        return json.dumps(parser.invoke(response.content))


@mcp.tool()
def evaluate_test_cases(file_name: str, c_code: str, rust_code: str) -> str:
    """Runs the local visible I/O suite for C and Rust."""
    test_dir = os.path.join("data/processed/tests", file_name.removesuffix(".c"))
    if not os.path.isdir(test_dir):
        return json.dumps({"status": "skipped", "reason": f"No tests found for {file_name} in {test_dir}"})
    input_cases = list_input_cases(test_dir)
    if not input_cases:
        return json.dumps({"status": "skipped", "reason": f"No .in files found in {test_dir}"})

    report = {
        "status": "success",
        "c_compilation": "success",
        "rust_compilation": "success",
        "total_tests": len(input_cases),
        "c_passed": 0,
        "c_failed": 0,
        "rust_passed": 0,
        "rust_failed": 0,
        "failed_rust_where_c_passed": 0,
        "passed_rust_where_c_failed": 0,
        "failed_tests": [],
        "details": "",
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        c_compile, c_binary = compile_c(c_code, temp_dir)
        if c_compile.returncode != 0:
            report.update(status="c_failed_compilation", c_compilation="failed", details=c_compile.stderr)
            return json.dumps(report)
        rust_compile, rust_binary = compile_rust(rust_code, temp_dir)
        if rust_compile.returncode != 0:
            report.update(status="failed", rust_compilation="failed", details=rust_compile.stderr)
            return json.dumps(report)

        for input_name in input_cases:
            input_path = os.path.join(test_dir, input_name)
            output_path = os.path.join(test_dir, input_name.replace(".in", ".out"))
            with open(input_path, encoding="utf-8") as input_file:
                input_data = input_file.read()
            expected_output = ""
            if os.path.exists(output_path):
                with open(output_path, encoding="utf-8") as output_file:
                    expected_output = output_file.read()
            c_output = run_visible_program(c_binary, input_data)
            rust_output = run_visible_program(rust_binary, input_data)
            c_passed = c_output.split() == expected_output.split()
            rust_passed = rust_output.split() == expected_output.split()
            report["c_passed" if c_passed else "c_failed"] += 1
            report["rust_passed" if rust_passed else "rust_failed"] += 1
            if c_passed and not rust_passed:
                report["status"] = "failed"
                report["failed_tests"].append(input_name)
                report["failed_rust_where_c_passed"] += 1
                report["details"] += (
                    f"Test {input_name} failed.\nExpected (first 10 lines):\n"
                    f"{' '.join(expected_output.splitlines()[:10])}\n\nRust Output (first 10 lines):\n"
                    f"{' '.join(rust_output.splitlines()[:10])}\n\n"
                )
            elif rust_passed and not c_passed:
                report["passed_rust_where_c_failed"] += 1
    return json.dumps(report)


def run_visible_program(command: str, input_data: str) -> str:
    try:
        return subprocess.run(
            [command], input=input_data, capture_output=True, text=True,
            timeout=configs.visible_test_time_limit_sec,
        ).stdout
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


if __name__ == "__main__":
    mcp.run()
