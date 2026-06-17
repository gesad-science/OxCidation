from mcp.server.fastmcp import FastMCP
import subprocess
import tempfile
import os
import sys
import json
import logging
import re
from pydantic import BaseModel, Field
from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from config import ConfigDetails

from dotenv import load_dotenv

load_dotenv()

# Configure logging to write to stderr
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [SERVER:%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("RustToolkitRunnerServer")

configs = ConfigDetails()

class TranslationResult(BaseModel):
    reasoning: str = Field(
        description="Step-by-step reasoning on how to translate the C code."
    )
    rust_code: str = Field(
        description="The raw, unformatted Rust code. Do not use markdown backticks."
    )


def clean_markdown_code(raw_code: str) -> str:
    """Removes markdown code block wrappers (e.g., ```rust ... ```) from a string."""
    # Matches ```<optional_language>\n ...code... \n```
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
        
        # Disable native thinking process via Ollama API options if requested
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

    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")

@mcp.tool()
def compile_rust_code(source_code: str) -> str:
    """
    Compiles a Rust snippet using rustc and returns the compiler output.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = os.path.join(temp_dir, "compiled_rust.rs")
        with open(file_path, "w") as f:
            f.write(source_code)

        # Execute rustc
        result = subprocess.run(
            ["rustc", file_path, "--out-dir", temp_dir], capture_output=True, text=True
        )

        # Return output to the LLM
        if result.returncode == 0:
            return f"Success:\n{result.stdout}"
        else:
            return f"Compilation Failed:\n{result.stderr}"


@mcp.tool()
def translate_c_to_rust(c_code: str) -> str:
    """
    Translates C code to Rust using an LLM.
    Returns a JSON string containing the rust_code and token usage.
    """
    llm = get_llm()
    with open("prompts/direct_translation_prompt.txt", "r", encoding="utf-8") as f:
        prompt_template = f.read()
    base_prompt = prompt_template.format(c_code=c_code)

    try:
        # Enforce strict JSON Schema mode instead of function calling
        structured_llm = llm.with_structured_output(
            TranslationResult, method="json_schema", strict=True
        )
        response = structured_llm.invoke(base_prompt)

        rust_code = clean_markdown_code(response.rust_code)
        prompt_tokens = 0
        completion_tokens = 0

        logger.info(f"LLM response type: {type(response)}")
        logger.info(f"LLM response: {response}")

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
                f"{base_prompt}"
            )

            fallback_response = fallback_llm.invoke(fallback_prompt)
            parsed_json = parser.invoke(fallback_response.content)

            raw_rust = parsed_json.get("rust_code", "")
            rust_code = clean_markdown_code(raw_rust)

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
            # If the fallback fails, log what the model returned
            if "fallback_response" in locals():
                logger.error(f"Raw Model Output was:\n{fallback_response.content}")
            return json.dumps(
                {
                    "rust_code": "",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "error": f"LLM parsing failed completely: {str(fallback_err)}",
                }
            )

    orchestrator_payload = {
        "rust_code": rust_code,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }

    return json.dumps(orchestrator_payload)


@mcp.tool()
def repair_rust_code(rust_code: str, errors: str) -> str:
    """
    Repairs Rust code based on compiler errors or test failures using an LLM.
    """
    llm = get_llm()
    
    repair_prompt = (
        f"You are an expert Rust developer. Fix this Rust code to resolve the issues (compiler errors or test failures):\n\n"
        f"Code:\n{rust_code}\n\n"
        f"Issues:\n{errors}\n\n"
        f"Return ONLY the fixed Rust code, no explanations or markdown wrappers."
    )
    
    try:
        response = llm.invoke(repair_prompt)
        repaired_code = clean_markdown_code(response.content)
        logger.info(f"Repair completed successfully")
        return repaired_code
    except Exception as e:
        logger.error(f"Repair failed: {str(e)}")
        return ""


@mcp.tool()
def evaluate_test_cases(file_name: str, c_code: str, rust_code: str) -> str:
    """
    Compiles and evaluates both C and Rust code against I/O test cases.
    """
    base_name = file_name.replace(".c", "")
    test_dir = os.path.join("data/processed/tests", base_name)
    
    if not os.path.exists(test_dir):
        return json.dumps({
            "status": "skipped",
            "reason": f"No tests found for {file_name} in {test_dir}"
        })
        
    in_files = sorted([f for f in os.listdir(test_dir) if f.endswith(".in")])
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
        c_file_path = os.path.join(temp_dir, "prog.c")
        c_bin_path = os.path.join(temp_dir, "prog_c")
        rust_file_path = os.path.join(temp_dir, "prog.rs")
        rust_bin_path = os.path.join(temp_dir, "prog_rust")
        
        with open(c_file_path, "w") as f:
            f.write(c_code)
        with open(rust_file_path, "w") as f:
            f.write(rust_code)
            
        # Compile C
        c_compile = subprocess.run(["gcc", c_file_path, "-o", c_bin_path], capture_output=True, text=True)
        if c_compile.returncode != 0:
            result["c_compilation"] = "failed"
            result["status"] = "c_failed_compilation"
            result["details"] = c_compile.stderr
            return json.dumps(result)
            
        # Compile Rust
        rust_compile = subprocess.run(["rustc", rust_file_path, "-o", rust_bin_path], capture_output=True, text=True)
        if rust_compile.returncode != 0:
            result["rust_compilation"] = "failed"
            result["status"] = "failed"
            result["details"] = rust_compile.stderr
            return json.dumps(result)
            
        # Run tests
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
                    
            # Run C
            try:
                c_run = subprocess.run([c_bin_path], input=input_data, capture_output=True, text=True, timeout=5)
                c_out = c_run.stdout
            except subprocess.TimeoutExpired:
                c_out = "TIMEOUT"
                
            # Run Rust
            try:
                rust_run = subprocess.run([rust_bin_path], input=input_data, capture_output=True, text=True, timeout=5)
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
            elif not c_passed:
                # If C failed, we ignore the test failure on the rust side (behavioral fidelity)
                pass
                
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
