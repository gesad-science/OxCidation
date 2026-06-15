import os
import time
import asyncio
import json
from typing import TypedDict, Literal, List
from langgraph.graph import StateGraph, END
from langchain_core.runnables import RunnableConfig

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from logger_setup import setup_environment_and_logger

logger = setup_environment_and_logger(__name__)


# State
class StepLog(TypedDict):
    step_name: str
    duration_sec: float
    prompt_tokens: int
    completion_tokens: int


class TranslatorState(TypedDict):
    file_name: str
    c_code: str
    rust_code: str
    errors: str
    status: Literal["success", "failed", "in_progress"]
    repair_count: int
    execution_history: List[StepLog]


# Nodes

MAX_REPAIRS = 5


def route_after_compile(state: TranslatorState):

    if state["status"] == "success":
        return END

    if state["repair_count"] >= MAX_REPAIRS:
        logger.error(
            f"[{state['file_name']}] Max repair attempts reached."
        )
        return END

    return "repair_node"

async def translate_node(
    state: TranslatorState, config: RunnableConfig
) -> TranslatorState:
    """Sends the C code to the MCP translation tool."""
    logger.info(f"[{state['file_name']}] Translating C to Rust...")
    start_time = time.time()

    mcp_session: ClientSession = config["configurable"].get("mcp_session")
    if not mcp_session:
        return {"status": "failed", "errors": "MCP Client Session not found"}

    try:
        result = await mcp_session.call_tool(
            "translate_c_to_rust",
            arguments={"c_code": state["c_code"]},
        )
        parsed_result = json.loads(result.content[0].text)
        rust_code = parsed_result.get("rust_code", "")
        prompt_tokens = parsed_result.get("prompt_tokens", 0)
        completion_tokens = parsed_result.get("completion_tokens", 0)

        status = state.get("status", "in_progress")
        errors = state.get("errors", "")
    except Exception as e:
        logger.error(f"[{state['file_name']}] Translation error: {str(e)}")
        rust_code = ""
        prompt_tokens = 0
        completion_tokens = 0
        status = "failed"
        errors = f"Translation tool execution failed: {str(e)}"

    duration = time.time() - start_time
    history = state.get("execution_history", []) + [
        {
            "step_name": "translate",
            "duration_sec": duration,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
    ]

    return {
        "rust_code": rust_code,
        "status": status,
        "errors": errors,
        "execution_history": history,
    }

async def repair_node(
    state: TranslatorState,
    config: RunnableConfig,
) -> TranslatorState:

    logger.info(
        f"[{state['file_name']}] Repair attempt #{state['repair_count'] + 1}"
    )

    mcp_session: ClientSession = config["configurable"]["mcp_session"]

    result = await mcp_session.call_tool(
        "repair_rust_code",
        arguments={
            "rust_code": state["rust_code"],
            "errors": state["errors"],
        },
    )

    repaired_code = result.content[0].text

    logger.info(f"[{state['file_name']}] Repair completed, returning to compile step. RESULT:\n{repaired_code}")

    return {
        "rust_code": repaired_code,
        "repair_count": state["repair_count"] + 1,
    }

async def compile_node(
    state: TranslatorState, config: RunnableConfig
) -> TranslatorState:
    """Sends the generated Rust code to the MCP compiler tool."""
    logger.info(f"[{state['file_name']}] Compiling Rust code...")
    start_time = time.time()

    mcp_session: ClientSession = config["configurable"].get("mcp_session")
    if not mcp_session:
        return {"status": "failed", "errors": "MCP Client Session not found"}

    try:
        result = await mcp_session.call_tool(
            "compile_rust_code",
            arguments={"source_code": state["rust_code"]},
        )
        compiler_output = result.content[0].text

        if "Success:" in compiler_output:
            status = "success"
            errors = ""
        else:
            status = "failed"
            errors = compiler_output

    except Exception as e:
        status = "failed"
        errors = f"Compilation tool execution failed: {str(e)}"

    duration = time.time() - start_time
    history = state.get("execution_history", []) + [
        {
            "step_name": "compile",
            "duration_sec": duration,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
    ]

    return {
        "errors": errors,
        "status": status,
        "execution_history": history,
    }


# Graph
workflow = StateGraph(TranslatorState)

workflow.add_node("translate_node", translate_node)
workflow.add_node("compile_node", compile_node)
workflow.add_node("repair_node", repair_node)

workflow.set_entry_point("translate_node")

workflow.add_edge("translate_node", "compile_node")

workflow.add_conditional_edges(
    "compile_node",
    route_after_compile,
)

workflow.add_edge(
    "repair_node",
    "compile_node",
)
app = workflow.compile()


async def process_file(file_path: str, mcp_session: ClientSession):
    """Processes a single C file through the workflow."""
    file_name = os.path.basename(file_path)
    logger.info(f"--- Starting processing for {file_name} ---")

    with open(file_path, "r") as f:
        c_code = f.read()

    initial_state = {
        "file_name": file_name,
        "c_code": c_code,
        "status": "in_progress",
        "repair_count": 0,
        "execution_history": [],
    }

    config = {"configurable": {"mcp_session": mcp_session}}

    # Run graph
    result = await app.ainvoke(initial_state, config=config)

    # Save the generated Rust code for inspection
    out_name = file_name.replace(".c", ".rs")
    out_path = os.path.join("output_rust_files", out_name)
    if result["rust_code"]:
        with open(out_path, "w") as f:
            f.write(result["rust_code"])

    # Log compile result
    if result["status"] == "success":
        logger.info(f"[{file_name}] Successfully compiled. Saved to {out_path}")
    else:
        logger.error(
            f"[{file_name}] Failed to compile. Generated code saved to {out_path} for inspection."
        )
        logger.error(f"[{file_name}] Final Errors:\n{result['errors']}")

    # Logs operation time and token usage
    total_time = sum(step["duration_sec"] for step in result["execution_history"])
    total_prompt_tokens = sum(
        step.get("prompt_tokens", 0) for step in result["execution_history"]
    )
    total_comp_tokens = sum(
        step.get("completion_tokens", 0) for step in result["execution_history"]
    )

    logger.info(f"[{file_name}] Workflow completed in {total_time:.2f} seconds.")
    logger.info(
        f"[{file_name}] Tokens Used: {total_prompt_tokens} prompt / {total_comp_tokens} completion."
    )


async def main():
    input_dir = "input_c_files"
    c_files = [
        os.path.join(input_dir, f) for f in os.listdir(input_dir) if f.endswith(".c")
    ]

    if not c_files:
        logger.warning(
            f"No .c files found in {input_dir}. Please add some to start testing."
        )
        return

    # Starts MCP client
    server_params = StdioServerParameters(
        command="python",
        args=["server.py"],
    )

    logger.info("Initializing MCP Server connection...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            logger.info("MCP Server connected successfully.")

            for file_path in c_files:
                await process_file(file_path, session)


if __name__ == "__main__":
    asyncio.run(main())
