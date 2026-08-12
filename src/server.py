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
from visible_test_preparation import prepare_generated_suite
from visible_testing import (
    evaluate_visible_suite,
    find_reusable_suite,
    load_generation_prompt,
    load_review_prompt,
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
    test_assessment: Literal[
        "translation_discrepancy",
        "invalid_visible_test",
        "inconclusive",
    ] = Field(
        description=(
            "Whether the evidence demonstrates a Rust translation discrepancy or an "
            "invalid visible test, or is insufficient for either conclusion."
        )
    )
    diagnosis: str = Field(description="Concise diagnosis of the differential test failure.")
    repair_guidance: str = Field(
        description=(
            "Concrete repair guidance for a translation_discrepancy; empty otherwise."
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


class VisibleTestCaseReview(BaseModel):
    case_id: str = Field(description="Identifier of the reviewed generated case.")
    assessment: Literal["approved", "invalid", "inconclusive"] = Field(
        description="Whether this individual input is supported by the C source."
    )
    diagnosis: str = Field(description="Concise evidence for this case assessment.")
    regeneration_guidance: str = Field(
        description="Replacement guidance for this case; empty when approved."
    )


class VisibleTestSuiteReview(BaseModel):
    case_reviews: list[VisibleTestCaseReview] = Field(
        min_length=1,
        description="Exactly one review for every supplied case identifier.",
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


def token_usage(response) -> dict:
    usage = getattr(response, "usage_metadata", None) or {}
    if not usage:
        metadata = getattr(response, "response_metadata", None) or {}
        usage = metadata.get("token_usage", {})
    return {
        "input_tokens": (
            usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
        ),
        "output_tokens": (
            usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        ),
    }


def invoke_structured(llm, schema, prompt: str, operation: str) -> tuple[dict, dict]:
    try:
        response = invoke_llm(
            llm.with_structured_output(
                schema,
                method="json_schema",
                strict=True,
                include_raw=True,
            ),
            prompt,
        )
        if response.get("parsing_error"):
            raise response["parsing_error"]
        return response["parsed"].model_dump(), token_usage(response["raw"])
    except Exception as strict_error:
        logger.warning("Structured %s failed: %s", operation, strict_error)
        parser = JsonOutputParser(pydantic_object=schema)
        response = invoke_llm(
            llm.bind(response_format={"type": "json_object"}),
            f"{parser.get_format_instructions()}\n\n{prompt}",
        )
        return parser.invoke(response.content), token_usage(response)


@mcp.tool()
def compile_rust_code(source_code: str) -> str:
    """Compiles Rust and returns compiler output."""
    with tempfile.TemporaryDirectory() as temp_dir:
        result, _ = compile_rust(source_code, temp_dir)
    if result.returncode == 0:
        return f"Success:\n{result.stdout}"
    return f"Compilation Failed:\n{result.stderr}"


@mcp.tool()
def translate_c_to_rust(c_code: str, prompt_template: str | None = None) -> str:
    """Translates C to Rust and returns a structured response."""
    if prompt_template is None:
        with open("prompts/direct_translation_prompt.txt", encoding="utf-8") as prompt_file:
            prompt_template = prompt_file.read()
    prompt = prompt_template.replace("{c_code}", c_code)
    llm = get_llm()
    try:
        payload, usage = invoke_structured(
            llm,
            TranslationResult,
            prompt,
            "translation",
        )
        rust_code = clean_markdown_code(payload.get("rust_code", ""))
        return json.dumps(
            {
                "rust_code": rust_code,
                "prompt_tokens": usage["input_tokens"],
                "completion_tokens": usage["output_tokens"],
                "raw_model_output": rust_code,
            }
        )
    except Exception as error:
        return json.dumps(
            {
                "rust_code": "",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "raw_model_output": "",
                "error": f"LLM parsing failed completely: {error}",
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
        response = invoke_llm(get_llm(), prompt)
        usage = token_usage(response)
        return json.dumps(
            {
                "rust_code": clean_markdown_code(response.content),
                "prompt_tokens": usage["input_tokens"],
                "completion_tokens": usage["output_tokens"],
            }
        )
    except Exception as error:
        logger.error("Repair failed: %s", error)
        return json.dumps(
            {
                "rust_code": "",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "error": str(error),
            }
        )


@mcp.tool()
def analyze_translation_discrepancy(c_code: str, rust_code: str, test_report: dict) -> str:
    """Diagnoses a visible differential failure and produces repair guidance."""
    prompt = (
        "You are a code validation specialist for behavior-preserving C to Rust translation.\n"
        "Analyze the C source, Rust translation, and differential visible-test report. "
        "First verify that the failing inputs are complete and valid for every input operation "
        "performed by the C source. If an input is malformed, incomplete, or makes the C oracle "
        "depend on undefined or uninitialized data, classify it as invalid_visible_test and do "
        "not recommend changing Rust to accept it. If the available evidence cannot support "
        "either conclusion, classify it as inconclusive. Otherwise classify it as "
        "translation_discrepancy and provide concise behavior-preserving repair guidance. "
        "Identify only supported discrepancies. "
        "Do not reveal hidden chain-of-thought.\n\n"
        f"C source:\n{c_code}\n\nRust translation:\n{rust_code}\n\n"
        f"Differential test report:\n{json.dumps(test_report, ensure_ascii=False)}"
    )
    llm = get_llm()
    try:
        payload, usage = invoke_structured(
            llm,
            SemanticValidationResult,
            prompt,
            "translation-discrepancy analysis",
        )
        return json.dumps(
            {
                **payload,
                "prompt_tokens": usage["input_tokens"],
                "completion_tokens": usage["output_tokens"],
            }
        )
    except Exception as error:
        logger.error("Validator analysis failed: %s", error)
        raise


@mcp.tool()
def generate_visible_test_suite(c_code: str, test_root: str) -> str:
    """Generates, reviews, and freezes one language-agnostic visible-test suite."""
    generation_prompt = load_generation_prompt()
    review_prompt = load_review_prompt()
    existing_suite = find_reusable_suite(
        test_root,
        c_code,
        generation_prompt,
        review_prompt,
        configs.llm_provider,
        configs.llm_model,
    )
    if existing_suite is not None:
        return json.dumps(existing_suite, ensure_ascii=False)

    llm = None

    def active_llm():
        nonlocal llm
        if llm is None:
            llm = get_llm()
        return llm

    def generate_candidates(regeneration_feedback: str) -> tuple[dict, dict]:
        prompt = generation_prompt.replace("{c_code}", c_code)
        if regeneration_feedback:
            prompt += (
                "\n\nGenerate replacement cases only for the rejected candidates described "
                "below. Previously approved cases are preserved; do not repeat or rewrite "
                "them. Follow the requested replacement count.\n"
                f"Replacement guidance: {regeneration_feedback}"
            )
        return invoke_structured(
            active_llm(),
            GeneratedVisibleTestSuite,
            prompt,
            "visible-test generation",
        )

    def review_candidates(
        cases: list[dict],
        deterministic_report: dict,
    ) -> tuple[dict, dict]:
        prompt = review_prompt.replace("{c_code}", c_code).replace(
            "{cases}",
            json.dumps(cases, ensure_ascii=False),
        )
        prompt = prompt.replace(
            "{deterministic_report}",
            json.dumps(deterministic_report, ensure_ascii=False),
        )
        return invoke_structured(
            active_llm(),
            VisibleTestSuiteReview,
            prompt,
            "visible-test review",
        )

    suite = prepare_generated_suite(
        c_code,
        test_root,
        configs.visible_test_time_limit_sec,
        generation_prompt,
        review_prompt,
        configs.llm_provider,
        configs.llm_model,
        generate_candidates,
        review_candidates,
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
