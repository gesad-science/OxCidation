import argparse
import asyncio
import json
import logging
import os
import sys

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agents import (
    AgentState,
    CodeEvaluator,
    CodeTranslatorAgent,
    CodeValidator,
    TesterAgent,
)
from config import ConfigDetails
from logger_setup import RunRecorder, setup_environment_and_logger

logger = setup_environment_and_logger(__name__)
test_logger = logging.getLogger("tests")
configs = ConfigDetails()

COMPILE_ROUTES = {
    "run_visible_tests": "test_node",
    "run_judge": "judge_node",
    "repair_translation": "repair_node",
    "stop_failed": END,
}
TRANSLATION_ROUTES = {
    "compile_translation": "compile_node",
    "stop_failed": END,
}
VISIBLE_TEST_ROUTES = {
    "run_judge": "judge_node",
    "repair_translation": "repair_node",
    "stop_failed": END,
}
JUDGE_ROUTES = {
    "stop_success": END,
    "stop_evaluated": END,
    "stop_failed": END,
    "skip": END,
}


def _mcp_session(config: RunnableConfig) -> ClientSession:
    return config["configurable"]["mcp_session"]


def _judge_comparison(config: RunnableConfig):
    return config["configurable"].get("judge_comparison")


def route_after_compile_validation(state: AgentState):
    return state["validation_decision"]["next_action"]


def route_after_translation_validation(state: AgentState):
    return state["validation_decision"]["next_action"]


def route_after_visible_validation(state: AgentState):
    return state["validation_decision"]["next_action"]


def route_after_judge_validation(state: AgentState):
    return state["validation_decision"]["next_action"]


async def translate_node(
    state: AgentState,
    config: RunnableConfig,
) -> AgentState:
    return await CodeTranslatorAgent(_mcp_session(config)).translate(state)


async def compile_node(
    state: AgentState,
    config: RunnableConfig,
) -> AgentState:
    compile_result = await CodeTranslatorAgent(_mcp_session(config)).compile(
        state
    )
    compiled_state = {**state, **compile_result}
    initial_evaluation = await CodeEvaluator(
        _judge_comparison(config)
    ).evaluate_initial(compiled_state)
    return {**compile_result, **initial_evaluation}


async def validate_translation_node(state: AgentState) -> AgentState:
    return CodeValidator(configs.max_repair_attempts).from_translation(state)


async def validate_compile_node(state: AgentState) -> AgentState:
    return CodeValidator(configs.max_repair_attempts).from_compile(state)


async def repair_node(
    state: AgentState,
    config: RunnableConfig,
) -> AgentState:
    return await CodeTranslatorAgent(_mcp_session(config)).repair(state)


async def test_node(
    state: AgentState,
    config: RunnableConfig,
) -> AgentState:
    return await TesterAgent(_mcp_session(config)).run_suite(state)


async def analyze_visible_node(
    state: AgentState,
    config: RunnableConfig,
) -> AgentState:
    return await CodeValidator(configs.max_repair_attempts).analyze_test_report(
        state,
        _mcp_session(config),
    )


async def validate_visible_node(state: AgentState) -> AgentState:
    return CodeValidator(configs.max_repair_attempts).from_tests(state)


async def judge_node(
    state: AgentState,
    config: RunnableConfig,
) -> AgentState:
    return await CodeEvaluator(_judge_comparison(config)).evaluate(state)


async def validate_judge_node(state: AgentState) -> AgentState:
    return CodeValidator(configs.max_repair_attempts).from_judge(state)


workflow = StateGraph(AgentState)
workflow.add_node("translate_node", translate_node)
workflow.add_node("validate_translation_node", validate_translation_node)
workflow.add_node("compile_node", compile_node)
workflow.add_node("validate_compile_node", validate_compile_node)
workflow.add_node("repair_node", repair_node)
workflow.add_node("test_node", test_node)
workflow.add_node("analyze_visible_node", analyze_visible_node)
workflow.add_node("validate_visible_node", validate_visible_node)
workflow.add_node("judge_node", judge_node)
workflow.add_node("validate_judge_node", validate_judge_node)

workflow.set_entry_point("translate_node")
workflow.add_edge("translate_node", "validate_translation_node")
workflow.add_conditional_edges(
    "validate_translation_node",
    route_after_translation_validation,
    TRANSLATION_ROUTES,
)
workflow.add_edge("compile_node", "validate_compile_node")
workflow.add_conditional_edges(
    "validate_compile_node",
    route_after_compile_validation,
    COMPILE_ROUTES,
)
workflow.add_edge("repair_node", "compile_node")
workflow.add_edge("test_node", "analyze_visible_node")
workflow.add_edge("analyze_visible_node", "validate_visible_node")
workflow.add_conditional_edges(
    "validate_visible_node",
    route_after_visible_validation,
    VISIBLE_TEST_ROUTES,
)
workflow.add_edge("judge_node", "validate_judge_node")
workflow.add_conditional_edges(
    "validate_judge_node",
    route_after_judge_validation,
    JUDGE_ROUTES,
)
app = workflow.compile()


def _run_totals(result: AgentState) -> dict:
    history = result.get("execution_history", [])
    return {
        "duration_sec": round(sum(step["duration_sec"] for step in history), 3),
        "prompt_tokens": sum(step.get("prompt_tokens", 0) for step in history),
        "completion_tokens": sum(step.get("completion_tokens", 0) for step in history),
    }


def _log_file_outcome(file_name: str, out_path: str, result: AgentState):
    status = result.get("status", "failed")
    judge_status = result.get("judge_result", {}).get("status")

    if status == "success":
        if judge_status == "ACCEPTED":
            logger.info(f"[{file_name}] Judge accepted. Saved Rust output to {out_path}")
        else:
            logger.info(
                f"[{file_name}] Visible validation passed. "
                f"Saved Rust output to {out_path}"
            )
        if judge_status and judge_status != "ACCEPTED":
            logger.info(f"[{file_name}] Judge evaluation status: {judge_status}")
        return

    if status == "skipped":
        logger.info(f"[{file_name}] Validation skipped. Saved Rust output to {out_path}")
        if judge_status:
            logger.info(f"[{file_name}] Judge evaluation status: {judge_status}")
        return

    if status == "evaluated":
        logger.info(
            f"[{file_name}] Judge evaluation completed with status {judge_status}. "
            f"Saved Rust output to {out_path}"
        )
        return

    logger.error(f"[{file_name}] Final status: {status}")
    logger.error(f"[{file_name}] Final reason:\n{result.get('errors', '')}")


async def process_file(
    file_path: str,
    mcp_session: ClientSession,
    recorder: RunRecorder,
    *,
    output_path: str | None = None,
    prompt_id: str = "default",
    prompt_template: str | None = None,
    record_metadata: dict | None = None,
    problem_id: str = "",
    judge_comparison=None,
    visible_tests_root: str = "data/processed/tests",
    visible_test_suite: dict | None = None,
) -> AgentState:
    file_name = os.path.basename(file_path)
    logger.info(f"--- Starting processing for {file_name} ---")

    with open(file_path, "r") as f:
        c_code = f.read()

    initial_state = {
        "file_name": file_name,
        "problem_id": problem_id,
        "c_code": c_code,
        "rust_code": "",
        "status": "in_progress",
        "repair_count": 0,
        "failure_category": "none",
        "execution_history": [],
        "agent_interactions": [],
        "test_metrics": {},
        "judge_result": {},
        "initial_evaluation": {},
        "prompt_id": prompt_id,
        "visible_test_root": os.path.join(
            visible_tests_root,
            file_name.removesuffix(".c"),
        ),
    }
    if visible_test_suite is not None:
        initial_state["visible_test_suite"] = visible_test_suite
    if prompt_template is not None:
        initial_state["prompt_template"] = prompt_template

    result = await app.ainvoke(
        initial_state,
        config={
            "configurable": {
                "mcp_session": mcp_session,
                "judge_comparison": judge_comparison,
            }
        },
    )

    out_name = file_name.replace(".c", ".rs")
    out_path = output_path or os.path.join("data/processed/output_rust_files", out_name)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if result.get("rust_code"):
        with open(out_path, "w") as f:
            f.write(result["rust_code"])

    totals = _run_totals(result)
    judge_result = result.get("judge_result", {})
    record = {
        "file_name": file_name,
        "final_status": result.get("status", "failed"),
        "compile_status": result.get("compile_status", "not_reached"),
        "judge_status": judge_result.get("status"),
        "judge_passed": judge_result.get("passed", 0),
        "judge_failed": judge_result.get("failed", 0),
        "judge_total": judge_result.get("total", 0),
        "judge_verdict_counts": judge_result.get("verdict_counts", {}),
        "judge_first_failure": judge_result.get("first_failure", {}),
        "failure_category": result.get("failure_category", "infrastructure"),
        "repair_attempts": result.get("repair_count", 0),
        "visible_tests": result.get("test_metrics", {}),
        "visible_test_suite": result.get("visible_test_suite", {}),
        "agent_interactions": result.get("agent_interactions", []),
        "validator_report": result.get("validator_report", {}),
        "baseline_judge": result.get("baseline_judge", {}),
        "initial_evaluation": result.get("initial_evaluation", {}),
        "judge": judge_result,
        "prompt_id": prompt_id,
        **totals,
    }
    if record_metadata:
        record.update(record_metadata)
    recorder.write(record)

    logger.info(f"[{file_name}] Workflow completed in {totals['duration_sec']:.2f} seconds")
    logger.info(
        f"[{file_name}] Tokens Used: {totals['prompt_tokens']} prompt / "
        f"{totals['completion_tokens']} completion"
    )

    _log_file_outcome(file_name, out_path, result)

    return result


def _new_global_metrics() -> dict:
    return {
        "total_files": 0,
        "final_success": 0,
        "final_failed": 0,
        "final_skipped": 0,
        "final_evaluated": 0,
        "judge_accepted": 0,
        "judge_failed": 0,
        "judge_skipped": 0,
        "rust_compilation_failed": 0,
        "c_compilation_failed": 0,
        "visible_tests_skipped": 0,
        "visible_passed_but_judge_failed": 0,
        "total_repair_attempts": 0,
        "failure_categories": {},
        "judge_verdict_counts": {},
    }


def _update_global_metrics(metrics: dict, result: AgentState):
    metrics["total_files"] += 1
    status = result.get("status", "failed")
    if status == "success":
        metrics["final_success"] += 1
    elif status == "skipped":
        metrics["final_skipped"] += 1
    elif status == "evaluated":
        metrics["final_evaluated"] = metrics.get("final_evaluated", 0) + 1
    else:
        metrics["final_failed"] += 1

    judge_status = result.get("judge_result", {}).get("status")
    if judge_status == "ACCEPTED":
        metrics["judge_accepted"] += 1
    elif judge_status == "SKIPPED":
        metrics["judge_skipped"] += 1
    elif judge_status:
        metrics["judge_failed"] += 1

    verdict_counts = result.get("judge_result", {}).get("verdict_counts", {})
    for verdict, count in verdict_counts.items():
        current_count = metrics["judge_verdict_counts"].get(verdict, 0)
        metrics["judge_verdict_counts"][verdict] = current_count + count

    test_status = result.get("test_metrics", {}).get("status")
    if test_status == "skipped":
        metrics["visible_tests_skipped"] += 1
    elif test_status == "c_failed_compilation":
        metrics["c_compilation_failed"] += 1

    category = result.get("failure_category", "infrastructure")
    if category == "compile" and result.get("status") == "failed":
        metrics["rust_compilation_failed"] += 1

    if test_status == "success" and judge_status not in [None, "ACCEPTED", "SKIPPED"]:
        metrics["visible_passed_but_judge_failed"] += 1

    metrics["total_repair_attempts"] += result.get("repair_count", 0)
    categories = metrics["failure_categories"]
    categories[category] = categories.get(category, 0) + 1


async def main():
    parser = argparse.ArgumentParser(description="Run the C to Rust translation pipeline.")
    parser.add_argument(
        "--reset-progress",
        action="store_true",
        help="Reset progress and metrics.",
    )
    args = parser.parse_args()

    input_dir = "data/processed/input_c_files"
    c_files = [
        os.path.join(input_dir, f)
        for f in sorted(os.listdir(input_dir))
        if f.endswith(".c")
    ]

    if not c_files:
        logger.warning(f"No .c files found in {input_dir}.")
        return

    progress_file = "logs/progress.json"
    if args.reset_progress and os.path.exists(progress_file):
        os.remove(progress_file)
        logger.info("Progress log reset")

    global_metrics = _new_global_metrics()
    processed_files = set()

    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r") as f:
                data = json.load(f)
                global_metrics = data.get("metrics", global_metrics)
                processed_files = set(data.get("processed_files", []))
            logger.info(
                f"Loaded progress from {progress_file}. "
                f"{len(processed_files)} files already processed."
            )
        except Exception as exc:
            logger.error(f"Failed to load progress file: {exc}")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["src/server.py"],
    )
    recorder = RunRecorder()
    logger.info(f"Structured run log: {recorder.path}")

    logger.info("Initializing MCP Server connection")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            logger.info("MCP Server connected successfully")

            for file_path in c_files:
                file_name = os.path.basename(file_path)
                if file_name in processed_files:
                    logger.info(f"Skipping {file_name}, already processed")
                    continue

                result = await process_file(file_path, session, recorder)
                _update_global_metrics(global_metrics, result)
                processed_files.add(file_name)

                with open(progress_file, "w") as f:
                    json.dump(
                        {
                            "metrics": global_metrics,
                            "processed_files": sorted(processed_files),
                        },
                        f,
                        indent=2,
                    )

            test_logger.info("=== BATCH RUN SUMMARY ===")
            test_logger.info(json.dumps(global_metrics, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
