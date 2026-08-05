"""MCP tools for model interaction and visible-test execution."""

import json
import logging
import os
import re
import sys
import tempfile
from typing import Literal

from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from config import ConfigDetails
from judge_execution import compile_rust
from rate_limit import RequestRateLimiter
from visible_testing import (
    evaluate_visible_suite,
    find_reusable_suite,
    load_generation_prompt,
    materialize_generated_suite,
    record_generation_failure,
)

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
    rust_code: str = Field(description="Raw Rust code without markdown backticks.")


class SemanticValidationResult(BaseModel):
    test_assessment: Literal["translation_discrepancy", "invalid_visible_test"] = Field(
        description=(
            "Whether the evidence demonstrates a Rust translation discrepancy or an "
            "invalid, incomplete, or unreliable visible test."
        )
    )
    diagnosis: str = Field(description="Concise diagnosis of the differential test failure.")
    repair_guidance: str = Field(
        description=(
            "Concrete repair guidance for a translation_discrepancy; empty for an "
            "invalid_visible_test."
        )
    )
    semantic_discrepancies: list[str] = Field(
        description="Likely semantic discrepancies supported by the test report."
    )


class GeneratedVisibleTestCase(BaseModel):
    purpose: str = Field(description="The observable behavior or path exercised by this case.")
    input: str = Field(description="Complete text to send to the program's standard input.")


class GeneratedVisibleTestSuite(BaseModel):
    strategy: str = Field(description="A concise summary of the behaviors covered by the suite.")
    cases: list[GeneratedVisibleTestCase] = Field(
        min_length=1,
        description="Concrete standard-input cases. Choose the necessary number of cases.",
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
    prompt = prompt_template.replace("{c_code}", c_code)
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
                }
            )
        except Exception as fallback_error:
            return json.dumps(
                {
                    "rust_code": "",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "raw_model_output": "",
                    "error": f"LLM parsing failed completely: {fallback_error}",
                }
            )


@mcp.tool()
def repair_rust_code(
    c_code: str,
    rust_code: str,
    errors: str,
    failure_category: str = "correctness",
) -> str:
    """Repairs Rust code from a compiler or visible-test report."""
    prompt = (
        "You are an expert C-to-Rust translator. Repair the Rust translation while "
        "preserving the C program's behavior and intended algorithm.\n"
        f"Failure category: {failure_category}\n\nC source:\n{c_code}\n\n"
        f"Current Rust translation:\n{rust_code}\n\n"
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
        "First verify that the failing inputs are complete and valid for every input operation "
        "performed by the C source. If an input is malformed, incomplete, or makes the C oracle "
        "depend on undefined or uninitialized data, classify it as invalid_visible_test and do "
        "not recommend changing Rust to accept it. Otherwise classify it as "
        "translation_discrepancy and provide concise behavior-preserving repair guidance. "
        "Identify only supported discrepancies. "
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
def generate_visible_test_suite(c_code: str, test_root: str) -> str:
    """Generates language-agnostic inputs and materializes C oracle outputs."""
    prompt_template = load_generation_prompt()
    existing_suite = find_reusable_suite(test_root, c_code, prompt_template)
    if existing_suite is not None:
        return json.dumps(existing_suite, ensure_ascii=False)

    prompt = prompt_template.replace("{c_code}", c_code)
    try:
        llm = get_llm()
    except Exception as error:
        suite = record_generation_failure(
            c_code,
            test_root,
            prompt_template,
            f"Visible-test model initialization failed: {error}",
        )
        return json.dumps(suite, ensure_ascii=False)

    try:
        response = invoke_llm(
            llm.with_structured_output(
                GeneratedVisibleTestSuite,
                method="json_schema",
                strict=True,
            ),
            prompt,
        )
        generation = response.model_dump()
        usage = {}
    except Exception as strict_error:
        logger.warning("Structured visible-test generation failed: %s", strict_error)
        try:
            parser = JsonOutputParser(pydantic_object=GeneratedVisibleTestSuite)
            response = invoke_llm(
                llm.bind(response_format={"type": "json_object"}),
                f"{parser.get_format_instructions()}\n\n{prompt}",
            )
            generation = parser.invoke(response.content)
            usage = response.usage_metadata or {}
        except Exception as fallback_error:
            suite = record_generation_failure(
                c_code,
                test_root,
                prompt_template,
                f"Visible-test generation failed: {fallback_error}",
            )
            return json.dumps(suite, ensure_ascii=False)

    suite = materialize_generated_suite(
        c_code,
        generation,
        test_root,
        configs.visible_test_time_limit_sec,
        prompt_template,
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
    )
    return json.dumps(suite, ensure_ascii=False)


@mcp.tool()
def evaluate_test_cases(c_code: str, rust_code: str, suite_dir: str) -> str:
    """Executes C and Rust against one language-agnostic visible-test suite."""
    report = evaluate_visible_suite(
        c_code,
        rust_code,
        suite_dir,
        configs.visible_test_time_limit_sec,
    )
    return json.dumps(report, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
