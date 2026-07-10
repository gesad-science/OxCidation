import json
import logging
import time
from typing import List, TypedDict

from mcp import ClientSession

from contracts import JudgeResult, PipelineStatus, ValidationDecision
from logger_setup import log_compact_compile, log_compact_judge, log_compact_test
from validator import (
    validate_compile_result,
    validate_judge_result,
    validate_visible_tests,
)

logger = logging.getLogger(__name__)
CLEAR_ERROR_ACTIONS = {
    "run_visible_tests",
    "run_judge",
    "stop_success",
    "stop_evaluated",
    "skip",
}


class StepLog(TypedDict):
    step_name: str
    duration_sec: float
    prompt_tokens: int
    completion_tokens: int


class AgentState(TypedDict, total=False):
    file_name: str
    c_code: str
    rust_code: str
    prompt_id: str
    prompt_template: str
    raw_model_output: str
    compile_status: str
    errors: str
    status: PipelineStatus
    repair_count: int
    failure_category: str
    execution_history: List[StepLog]
    test_metrics: dict
    judge_result: JudgeResult
    validation_decision: ValidationDecision


def _history(
    state: AgentState,
    step_name: str,
    started_at: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> List[StepLog]:
    return state.get("execution_history", []) + [
        {
            "step_name": step_name,
            "duration_sec": time.time() - started_at,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
    ]


class CodeTranslatorAgent:
    def __init__(self, mcp_session: ClientSession):
        self.mcp_session = mcp_session

    async def translate(self, state: AgentState) -> AgentState:
        logger.info(f"[{state['file_name']}] Translator: translating C to Rust")
        started_at = time.time()

        try:
            arguments = {"c_code": state["c_code"]}
            if state.get("prompt_template") is not None:
                arguments["prompt_template"] = state["prompt_template"]
            result = await self.mcp_session.call_tool(
                "translate_c_to_rust",
                arguments=arguments,
            )
            payload = json.loads(result.content[0].text)
            rust_code = payload.get("rust_code", "")
            prompt_tokens = payload.get("prompt_tokens", 0)
            completion_tokens = payload.get("completion_tokens", 0)
            raw_model_output = payload.get("raw_model_output", rust_code)
            status = "in_progress"
            errors = payload.get("error", "")
        except Exception as exc:
            logger.error(f"[{state['file_name']}] Translation failed: {exc}")
            rust_code = ""
            prompt_tokens = 0
            completion_tokens = 0
            status = "failed"
            errors = f"Translation tool execution failed: {exc}"
            raw_model_output = ""

        return {
            "rust_code": rust_code,
            "status": status,
            "errors": errors,
            "raw_model_output": raw_model_output,
            "execution_history": _history(
                state,
                "translate",
                started_at,
                prompt_tokens,
                completion_tokens,
            ),
        }

    async def compile(self, state: AgentState) -> AgentState:
        logger.info(f"[{state['file_name']}] Translator: compiling Rust code")
        started_at = time.time()

        try:
            result = await self.mcp_session.call_tool(
                "compile_rust_code",
                arguments={"source_code": state.get("rust_code", "")},
            )
            compiler_output = result.content[0].text
            success = "Success:" in compiler_output
            status = "success" if success else "failed"
            errors = "" if success else compiler_output
            log_compact_compile(
                state["file_name"],
                state.get("repair_count", 0),
                compiler_output,
                success,
            )
        except Exception as exc:
            status = "failed"
            errors = f"Compilation tool execution failed: {exc}"

        return {
            "errors": errors,
            "status": status,
            "compile_status": status,
            "execution_history": _history(state, "compile", started_at),
        }

    async def repair(self, state: AgentState) -> AgentState:
        attempt = state.get("repair_count", 0) + 1
        logger.info(f"[{state['file_name']}] Translator: repair attempt #{attempt}")

        result = await self.mcp_session.call_tool(
            "repair_rust_code",
            arguments={
                "rust_code": state.get("rust_code", ""),
                "errors": state.get("errors", ""),
                "failure_category": state.get("failure_category", "correctness"),
            },
        )

        return {
            "rust_code": result.content[0].text,
            "repair_count": attempt,
            "status": "in_progress",
        }


class TesterAgent:
    def __init__(self, mcp_session: ClientSession):
        self.mcp_session = mcp_session

    async def run_suite(self, state: AgentState) -> AgentState:
        logger.info(f"[{state['file_name']}] Tester: running visible test suite")
        started_at = time.time()

        try:
            result = await self.mcp_session.call_tool(
                "evaluate_test_cases",
                arguments={
                    "file_name": state["file_name"],
                    "c_code": state["c_code"],
                    "rust_code": state.get("rust_code", ""),
                },
            )
            test_output = json.loads(result.content[0].text)
            status = test_output.get("status", "failed")
            errors = "" if status in ["success", "skipped"] else test_output.get(
                "details",
                "Visible tests failed.",
            )
            log_compact_test(state["file_name"], status, errors)
        except Exception as exc:
            test_output = {}
            status = "failed"
            errors = f"Visible test evaluation failed: {exc}"
            logger.error(f"[{state['file_name']}] {errors}")

        return {
            "status": status,
            "errors": errors,
            "test_metrics": test_output,
            "execution_history": _history(state, "visible_tests", started_at),
        }


class CodeValidator:
    def __init__(self, max_repairs: int):
        self.max_repairs = max_repairs

    def from_compile(self, state: AgentState) -> AgentState:
        decision = validate_compile_result(
            state.get("status", "failed"),
            state.get("errors", ""),
            state.get("repair_count", 0),
            self.max_repairs,
        )
        return self._state_from_decision(decision)

    def from_tests(self, state: AgentState) -> AgentState:
        decision = validate_visible_tests(
            state.get("test_metrics", {}),
            state.get("repair_count", 0),
            self.max_repairs,
        )
        return self._state_from_decision(decision)

    def from_judge(self, state: AgentState) -> AgentState:
        decision = validate_judge_result(
            state.get("judge_result", {}),
        )
        next_state = self._state_from_decision(decision)
        next_state["status"] = _status_after_judge(
            state.get("status", "success"),
            decision,
        )
        return next_state

    def _state_from_decision(
        self,
        decision: ValidationDecision,
    ) -> AgentState:
        should_clear_errors = decision["next_action"] in CLEAR_ERROR_ACTIONS

        return {
            "validation_decision": decision,
            "failure_category": decision["failure_category"],
            "errors": "" if should_clear_errors else decision["fix_suggestion"],
        }


def _status_after_judge(
    previous_status: PipelineStatus,
    decision: ValidationDecision,
) -> PipelineStatus:
    if decision["next_action"] == "stop_success":
        return "success"
    return previous_status


class CodeEvaluator:
    def __init__(self, mcp_session: ClientSession):
        self.mcp_session = mcp_session

    async def evaluate(self, state: AgentState) -> AgentState:
        logger.info(f"[{state['file_name']}] Evaluator: running judge validation")
        started_at = time.time()

        try:
            result = await self.mcp_session.call_tool(
                "evaluate_judge_cases",
                arguments={
                    "file_name": state["file_name"],
                    "rust_code": state.get("rust_code", ""),
                },
            )
            judge_result = json.loads(result.content[0].text)
            judge_status = judge_result.get("status", "INFRA_ERROR")
            errors = ""
            log_compact_judge(
                state["file_name"],
                judge_status,
                judge_result.get("details", ""),
                judge_result.get("verdict_counts", {}),
            )
        except Exception as exc:
            judge_result = {
                "status": "INFRA_ERROR",
                "passed": 0,
                "failed": 0,
                "total": 0,
                "time_ms": 0,
                "details": f"Judge evaluation failed: {exc}",
            }
            judge_status = "INFRA_ERROR"
            errors = ""
            logger.error(f"[{state['file_name']}] {judge_result['details']}")

        return {
            "status": state.get("status", "success"),
            "errors": errors,
            "judge_result": judge_result,
            "execution_history": _history(state, "judge", started_at),
        }
