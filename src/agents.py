import json
import logging
import time
from typing import TYPE_CHECKING, List, TypedDict

from mcp import ClientSession

from contracts import (
    AgentInteraction,
    FailureCategory,
    JudgeResult,
    PipelineStatus,
    TestReport,
    ValidationDecision,
    ValidatorReport,
    VisibleTestSuite,
)
from logger_setup import log_compact_compile, log_compact_judge, log_compact_test
from validator import (
    validate_compile_result,
    validate_judge_result,
    validate_visible_tests,
)

if TYPE_CHECKING:
    from judge_comparison import JudgeComparison

logger = logging.getLogger(__name__)
CLEAR_ERROR_ACTIONS = {
    "compile_translation",
    "run_visible_tests",
    "run_judge",
    "stop_success",
    "stop_evaluated",
    "skip",
}
VALIDATOR_EVIDENCE_FIELDS = (
    "status",
    "c_compilation",
    "rust_compilation",
    "total_tests",
    "c_passed",
    "c_failed",
    "rust_passed",
    "rust_failed",
    "failed_rust_where_c_passed",
    "verdict_counts",
    "failure_examples",
    "baseline_failures",
)


class StepLog(TypedDict):
    step_name: str
    duration_sec: float
    prompt_tokens: int
    completion_tokens: int


class AgentState(TypedDict, total=False):
    file_name: str
    problem_id: str
    c_code: str
    rust_code: str
    prompt_id: str
    prompt_template: str
    raw_model_output: str
    compile_status: str
    errors: str
    status: PipelineStatus
    repair_count: int
    failure_category: FailureCategory
    execution_history: List[StepLog]
    test_metrics: TestReport
    visible_test_root: str
    visible_test_suite: VisibleTestSuite
    agent_interactions: List[AgentInteraction]
    validator_report: ValidatorReport
    judge_result: JudgeResult
    baseline_judge: dict
    initial_rust_code: str
    initial_evaluation: dict
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


def _interaction(
    state: AgentState,
    agent: str,
    action: str,
    data: dict,
    *,
    repair_count: int | None = None,
) -> List[AgentInteraction]:
    interactions = state.get("agent_interactions", [])
    interaction: AgentInteraction = {
        "sequence": len(interactions) + 1,
        "agent": agent,
        "action": action,
        "repair_count": (
            state.get("repair_count", 0) if repair_count is None else repair_count
        ),
        "data": data,
    }
    if interactions:
        interaction["caused_by_sequence"] = interactions[-1]["sequence"]
    return interactions + [interaction]


def _latest_interaction_sequence(state: AgentState, action: str) -> int | None:
    for interaction in reversed(state.get("agent_interactions", [])):
        if interaction.get("action") == action:
            return interaction["sequence"]
    return None


def _validator_evidence(test_report: TestReport) -> dict:
    return {
        field: test_report[field]
        for field in VALIDATOR_EVIDENCE_FIELDS
        if field in test_report
    }


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
            response_text = result.content[0].text
            if result.isError:
                raise RuntimeError(response_text)
            payload = json.loads(response_text)
            rust_code = payload.get("rust_code", "")
            prompt_tokens = payload.get("prompt_tokens", 0)
            completion_tokens = payload.get("completion_tokens", 0)
            raw_model_output = payload.get("raw_model_output", rust_code)
            errors = payload.get("error", "")
            status = "in_progress" if rust_code and not errors else "failed"
            if not errors and not rust_code:
                errors = "Translation tool returned no Rust code."
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
            "agent_interactions": _interaction(
                state,
                "translator",
                "translation",
                {
                    "status": "success" if status == "in_progress" else status,
                    "errors": errors,
                    "rust_code": rust_code,
                },
            ),
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
        compiler_output = ""

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
            compiler_output = errors

        return {
            "errors": errors,
            "status": status,
            "compile_status": status,
            "agent_interactions": _interaction(
                state,
                "translator",
                "compilation",
                {"status": status, "compiler_output": compiler_output},
            ),
            "execution_history": _history(state, "compile", started_at),
        }

    async def repair(self, state: AgentState) -> AgentState:
        attempt = state.get("repair_count", 0) + 1
        logger.info(f"[{state['file_name']}] Translator: repair attempt #{attempt}")
        started_at = time.time()

        result = await self.mcp_session.call_tool(
            "repair_rust_code",
            arguments={
                "c_code": state.get("c_code", ""),
                "rust_code": state.get("rust_code", ""),
                "errors": state.get("errors", ""),
                "failure_category": state.get("failure_category", "correctness"),
            },
        )

        response_text = result.content[0].text
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError:
            payload = {"rust_code": response_text}
        repaired_code = payload.get("rust_code", "")
        prompt_tokens = payload.get("prompt_tokens", 0)
        completion_tokens = payload.get("completion_tokens", 0)
        repair_data = {
            "attempt": attempt,
            "failure_category": state.get("failure_category", "correctness"),
            "c_source_ref": "source.c",
            "rust_code_after": repaired_code,
        }
        if state.get("failure_category") == "compile":
            feedback_sequence = _latest_interaction_sequence(state, "compilation")
            if feedback_sequence is not None:
                repair_data["feedback_source_sequence"] = feedback_sequence
        else:
            repair_data["feedback"] = state.get("errors", "")

        return {
            "rust_code": repaired_code,
            "repair_count": attempt,
            "status": "in_progress",
            "agent_interactions": _interaction(
                state,
                "translator",
                "repair",
                repair_data,
                repair_count=attempt,
            ),
            "execution_history": _history(
                state,
                "repair",
                started_at,
                prompt_tokens,
                completion_tokens,
            ),
        }


class TesterAgent:
    def __init__(self, mcp_session: ClientSession):
        self.mcp_session = mcp_session

    async def prepare_suite(self, c_code: str, test_root: str) -> VisibleTestSuite:
        result = await self.mcp_session.call_tool(
            "generate_visible_test_suite",
            arguments={"c_code": c_code, "test_root": test_root},
        )
        if result.isError:
            raise RuntimeError(result.content[0].text)
        suite = json.loads(result.content[0].text)
        reference_fields = (
            "status",
            "source",
            "source_sha256",
            "review_status",
            "generation_attempt_count",
            "candidate_count",
            "generated_candidate_count",
            "rejected_candidate_count",
            "invalid_case_count",
            "inconclusive_case_count",
            "unresolved_replacement_count",
            "case_count",
            "suite_sha256",
            "suite_dir",
            "preparation_history_path",
            "reused",
            "frozen",
            "details",
            "prompt_tokens",
            "completion_tokens",
            "review_prompt_tokens",
            "review_completion_tokens",
            "c_compile_profile",
            "c_compile_attempts",
        )
        return {field: suite[field] for field in reference_fields if field in suite}

    async def run_suite(self, state: AgentState) -> AgentState:
        logger.info(f"[{state['file_name']}] Tester: preparing visible test suite")
        started_at = time.time()

        try:
            suite, generation_usage = await self._ensure_suite(state)
            if suite.get("status") != "ready":
                reason = suite.get("details") or "No valid visible tests were generated."
                suite_status = suite.get("status")
                failure_category: FailureCategory
                if suite_status == "invalid_visible_tests":
                    failure_category = "invalid_tests"
                elif suite_status == "review_inconclusive":
                    failure_category = "inconclusive_tests"
                elif suite_status == "baseline_compile_failed":
                    failure_category = "invalid_baseline"
                elif suite_status in {
                    "generation_failed",
                    "review_failed",
                }:
                    failure_category = "infrastructure"
                else:
                    failure_category = "missing_tests"
                test_report: TestReport = {
                    "status": "skipped",
                    "suite_dir": suite.get("suite_dir", ""),
                    "total_tests": 0,
                    "failure_category": failure_category,
                    "reason": reason,
                    "details": reason,
                }
                status = "skipped"
                errors = ""
                log_compact_test(state["file_name"], status, reason)
                return self._result(
                    state,
                    suite,
                    test_report,
                    started_at,
                    generation_usage=generation_usage,
                )

            logger.info(f"[{state['file_name']}] Tester: running visible test suite")
            result = await self.mcp_session.call_tool(
                "evaluate_test_cases",
                arguments={
                    "c_code": state["c_code"],
                    "rust_code": state.get("rust_code", ""),
                    "suite_dir": suite["suite_dir"],
                },
            )
            if result.isError:
                raise RuntimeError(result.content[0].text)
            test_output = json.loads(result.content[0].text)
            status = test_output.get("status", "failed")
            errors = "" if status in ["success", "skipped"] else test_output.get(
                "details",
                "Visible tests failed.",
            )
            log_compact_test(state["file_name"], status, errors)
        except Exception as exc:
            suite = state.get("visible_test_suite", {})
            reason = f"Visible test infrastructure failed: {exc}"
            test_output = {
                "status": "skipped",
                "failure_category": "infrastructure",
                "reason": reason,
                "details": reason,
            }
            status = "skipped"
            errors = ""
            generation_usage = (0, 0)
            logger.error(f"[{state['file_name']}] {reason}")

        return self._result(
            state,
            suite,
            test_output,
            started_at,
            status=status,
            errors=errors,
            generation_usage=generation_usage,
        )

    async def _ensure_suite(
        self,
        state: AgentState,
    ) -> tuple[VisibleTestSuite, tuple[int, int]]:
        existing_suite = state.get("visible_test_suite", {})
        if existing_suite:
            return existing_suite, (0, 0)

        suite = await self.prepare_suite(state["c_code"], state["visible_test_root"])
        usage = (
            suite.get("prompt_tokens", 0),
            suite.get("completion_tokens", 0),
        )
        return suite, usage

    @staticmethod
    def _result(
        state: AgentState,
        suite: VisibleTestSuite,
        test_report: TestReport,
        started_at: float,
        *,
        status: str | None = None,
        errors: str = "",
        generation_usage: tuple[int, int] = (0, 0),
    ) -> AgentState:
        final_status = status or test_report.get("status", "failed")
        return {
            "status": final_status,
            "errors": errors,
            "test_metrics": test_report,
            "visible_test_suite": suite,
            "agent_interactions": _interaction(
                state,
                "tester",
                "visible_test_report",
                {
                    "suite": {
                        key: suite.get(key, "")
                        for key in (
                            "status",
                            "review_status",
                            "suite_sha256",
                            "preparation_history_path",
                        )
                    },
                    "test_report": test_report,
                },
            ),
            "execution_history": _history(
                state,
                "visible_tests",
                started_at,
                generation_usage[0],
                generation_usage[1],
            ),
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
        return self._decision_result(state, decision, "compile_decision")

    def from_translation(self, state: AgentState) -> AgentState:
        if state.get("status") == "in_progress" and state.get("rust_code"):
            decision: ValidationDecision = {
                "next_action": "compile_translation",
                "failure_category": "none",
                "reason": "Translation completed.",
                "fix_suggestion": "",
            }
        else:
            decision = {
                "next_action": "stop_failed",
                "failure_category": "infrastructure",
                "reason": state.get("errors", "Translation failed."),
                "fix_suggestion": "",
            }
        return self._decision_result(state, decision, "translation_decision")

    def from_tests(self, state: AgentState) -> AgentState:
        validator_report = state.get("validator_report", {})
        test_report = state.get("test_metrics", {})
        has_visible_failure = test_report.get("status") == "failed"
        assessment = validator_report.get("test_assessment")
        if has_visible_failure and assessment != "translation_discrepancy":
            diagnosis = validator_report.get("diagnosis", "").strip()
            invalid = assessment == "invalid_visible_test"
            decision: ValidationDecision = {
                "next_action": "run_judge",
                "failure_category": (
                    "invalid_tests" if invalid else "inconclusive_tests"
                ),
                "reason": (
                    f"Validator did not approve the visible-test evidence: {diagnosis}"
                    if diagnosis
                    else "Validator did not confirm a translation discrepancy."
                ),
                "fix_suggestion": "",
            }
            return self._decision_result(state, decision, "visible_test_decision")

        decision = validate_visible_tests(
            test_report,
            state.get("repair_count", 0),
            self.max_repairs,
        )
        decision = self._add_semantic_guidance(decision, state.get("validator_report", {}))
        return self._decision_result(state, decision, "visible_test_decision")

    async def analyze_test_report(
        self,
        state: AgentState,
        mcp_session: ClientSession,
    ) -> AgentState:
        test_report = state.get("test_metrics", {})
        has_differential_failure = (
            test_report.get("status") == "failed"
            and test_report.get("failed_rust_where_c_passed", 0) > 0
        )
        if not has_differential_failure:
            validator_report = {
                "status": "not_required",
                "semantic_discrepancies": [],
            }
            return {
                "validator_report": validator_report,
                "agent_interactions": _interaction(
                    state,
                    "validator",
                    "semantic_analysis_skipped",
                    {"reason": "No differential visible-test failure required analysis."},
                ),
            }

        logger.info(f"[{state['file_name']}] Validator: analyzing differential test report")
        started_at = time.time()
        try:
            result = await mcp_session.call_tool(
                "analyze_translation_discrepancy",
                arguments={
                    "c_code": state["c_code"],
                    "rust_code": state.get("rust_code", ""),
                    "test_report": _validator_evidence(test_report),
                },
            )
            response_text = result.content[0].text
            if result.isError:
                raise RuntimeError(response_text)
            validator_report = json.loads(response_text)
            prompt_tokens = validator_report.pop("prompt_tokens", 0)
            completion_tokens = validator_report.pop("completion_tokens", 0)
            validator_report["status"] = "completed"
        except Exception as exc:
            logger.warning(f"[{state['file_name']}] Validator analysis unavailable: {exc}")
            validator_report = {
                "status": "failed",
                "test_assessment": "inconclusive",
                "diagnosis": "The Validator could not establish reliable visible-test evidence.",
                "repair_guidance": "",
                "semantic_discrepancies": [],
                "error": str(exc),
            }
            prompt_tokens = 0
            completion_tokens = 0

        return {
            "validator_report": validator_report,
            "agent_interactions": _interaction(
                state,
                "validator",
                "semantic_analysis",
                {"validator_report": validator_report},
            ),
            "execution_history": _history(
                state,
                "validator_analysis",
                started_at,
                prompt_tokens,
                completion_tokens,
            ),
        }

    def from_judge(self, state: AgentState) -> AgentState:
        decision = validate_judge_result(
            state.get("judge_result", {}),
        )
        next_state = self._decision_result(state, decision, "judge_decision")
        next_state["status"] = _status_after_judge(
            state.get("status", "success"),
            decision,
        )
        return next_state

    def _decision_result(
        self,
        state: AgentState,
        decision: ValidationDecision,
        action: str,
    ) -> AgentState:
        result = self._state_from_decision(decision)
        result["agent_interactions"] = _interaction(
            state,
            "validator",
            action,
            {
                "decision": {
                    key: decision[key]
                    for key in ("next_action", "failure_category", "reason")
                }
            },
        )
        return result

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

    @staticmethod
    def _add_semantic_guidance(
        decision: ValidationDecision,
        validator_report: ValidatorReport,
    ) -> ValidationDecision:
        if decision["next_action"] != "repair_translation":
            return decision

        if validator_report.get("test_assessment") == "invalid_visible_test":
            return decision

        guidance = validator_report.get("repair_guidance", "").strip()
        if not guidance:
            return decision

        diagnosis = validator_report.get("diagnosis", "").strip()
        decision["fix_suggestion"] = (
            f"Failure category: {decision['failure_category']}. "
            "Repair the Rust translation without changing the C program's behavior.\n"
            f"Semantic diagnosis: {diagnosis}\n"
            f"Repair guidance: {guidance}"
        )
        return decision


def _status_after_judge(
    previous_status: PipelineStatus,
    decision: ValidationDecision,
) -> PipelineStatus:
    if decision["next_action"] == "stop_success":
        return "success"
    if decision["next_action"] == "stop_evaluated":
        return "evaluated"
    if decision["next_action"] == "skip":
        return "skipped"
    return previous_status


class CodeEvaluator:
    def __init__(
        self,
        judge_comparison: "JudgeComparison | None" = None,
    ):
        self.judge_comparison = judge_comparison

    async def evaluate_initial(self, state: AgentState) -> AgentState:
        if state.get("initial_evaluation"):
            return {}

        logger.info(f"[{state['file_name']}] Evaluator: evaluating initial translation")
        started_at = time.time()
        comparison, judge_result = self._run_comparison(state)
        self._log_result(state, judge_result)

        return {
            "initial_rust_code": state.get("rust_code", ""),
            "initial_evaluation": comparison,
            "agent_interactions": _interaction(
                state,
                "evaluator",
                "initial_judge_evaluation",
                {"judge_result": self._judge_summary(judge_result)},
            ),
            "execution_history": _history(state, "initial_judge", started_at),
        }

    async def evaluate(self, state: AgentState) -> AgentState:
        logger.info(f"[{state['file_name']}] Evaluator: running final judge evaluation")
        started_at = time.time()
        reused_initial = (
            bool(state.get("initial_evaluation"))
            and state.get("initial_rust_code") == state.get("rust_code", "")
        )
        if reused_initial:
            baseline_judge = state["initial_evaluation"]
            judge_result = baseline_judge["rust"]["judge"]
        else:
            baseline_judge, judge_result = self._run_comparison(state)
            self._log_result(state, judge_result)

        return {
            "status": state.get("status", "success"),
            "errors": "",
            "judge_result": judge_result,
            "baseline_judge": baseline_judge,
            "agent_interactions": _interaction(
                state,
                "evaluator",
                "judge_evaluation",
                {
                    "judge_result": self._judge_summary(judge_result),
                    "reused_initial_evaluation": reused_initial,
                },
            ),
            "execution_history": _history(state, "judge", started_at),
        }

    def _run_comparison(self, state: AgentState) -> tuple[dict, JudgeResult]:
        try:
            if self.judge_comparison is None:
                comparison = {
                    "baseline_status": "not_configured",
                    "c": {},
                    "rust": {
                        "judge": {
                            "status": "SKIPPED",
                            "details": "No CodeNet Judge profile was configured.",
                        }
                    },
                }
            else:
                comparison = self.judge_comparison.evaluate(
                    state["file_name"].removesuffix(".c"),
                    state["problem_id"],
                    state["c_code"],
                    state.get("rust_code", ""),
                )
            judge_result = comparison["rust"]["judge"]
            judge_result["baseline_status"] = comparison["baseline_status"]
            return comparison, judge_result
        except Exception as exc:
            judge_result: JudgeResult = {
                "status": "INFRA_ERROR",
                "passed": 0,
                "failed": 0,
                "total": 0,
                "time_ms": 0,
                "details": f"Judge evaluation failed: {exc}",
            }
            logger.error(f"[{state['file_name']}] {judge_result['details']}")
            return {
                "baseline_status": "infrastructure_error",
                "c": {},
                "rust": {"judge": judge_result},
            }, judge_result

    @staticmethod
    def _judge_summary(judge_result: JudgeResult) -> dict:
        return {
            key: judge_result.get(key)
            for key in (
                "status",
                "passed",
                "failed",
                "total",
                "time_ms",
                "details",
                "verdict_counts",
                "first_failure",
                "baseline_status",
            )
        }

    @staticmethod
    def _log_result(state: AgentState, judge_result: JudgeResult) -> None:
        log_compact_judge(
            state["file_name"],
            judge_result.get("status", "INFRA_ERROR"),
            judge_result.get("details", ""),
            judge_result.get("verdict_counts", {}),
        )
