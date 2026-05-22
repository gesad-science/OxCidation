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
    provider = os.getenv("LLM_PROVIDER", "openrouter")

    if provider == "openrouter":
        return ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY", "dummy"),
            model=os.getenv("LLM_MODEL", "openai/gpt-oss-120b:free"),
        )
    else:
        return ChatOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "dummy"),
            model=os.getenv("LLM_MODEL", "gpt-4o"),
        )


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
    base_prompt = f"Translate the following C code to Rust:\n\n{c_code}"

    try:
        # Enforce strict JSON Schema mode instead of function calling
        structured_llm = llm.with_structured_output(
            TranslationResult, method="json_schema", strict=True
        )
        response = structured_llm.invoke(base_prompt)

        rust_code = clean_markdown_code(response.rust_code)
        prompt_tokens = 0
        completion_tokens = 0

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
    Repairs Rust code based on compiler errors using an LLM.
    """
    # TODO: Initialize OpenAI client and prompt here
    # from langchain_openai import ChatOpenAI
    # llm = ChatOpenAI(model="gpt-4")
    # prompt = f"Fix this Rust code:\n{rust_code}\n\nCompiler Errors:\n{errors}"
    # return llm.invoke(prompt).content

    # Mock response for now
    return 'fn main() {\n    let x = 5;\n    println!("Fixed! x is {}", x);\n}'


if __name__ == "__main__":
    mcp.run()
