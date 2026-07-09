from contracts import FailureCategory, JudgeResult, ValidationDecision

JUDGE_FAILURE_CATEGORIES: dict[str, FailureCategory] = {
    "COMPILATION_ERROR": "compile",
    "RUNTIME_ERROR": "runtime",
    "WRONG_ANSWER": "correctness",
    "TIME_LIMIT_EXCEEDED": "timeout",
    "MEMORY_LIMIT_EXCEEDED": "memory",
    "INFRA_ERROR": "infrastructure",
}


def _repair_or_stop(
    repair_count: int,
    max_repairs: int,
    failure_category: FailureCategory,
    reason: str,
) -> ValidationDecision:
    fix_suggestion = (
        f"Failure category: {failure_category}. "
        f"Use the report below to repair the translated Rust code without changing the intended algorithm.\n"
        f"{reason}"
    )
    if repair_count >= max_repairs:
        return {
            "next_action": "stop_failed",
            "failure_category": failure_category,
            "reason": f"{reason} Max repair attempts reached.",
            "fix_suggestion": fix_suggestion,
        }

    return {
        "next_action": "repair_translation",
        "failure_category": failure_category,
        "reason": reason,
        "fix_suggestion": fix_suggestion,
    }


def validate_compile_result(
    status: str,
    errors: str,
    repair_count: int,
    max_repairs: int,
) -> ValidationDecision:
    if status == "success":
        return {
            "next_action": "run_visible_tests",
            "failure_category": "none",
            "reason": "Rust compilation succeeded.",
            "fix_suggestion": "",
        }

    reason = errors or "Rust compilation failed."
    return _repair_or_stop(repair_count, max_repairs, "compile", reason)


def validate_visible_tests(
    test_result: dict,
    repair_count: int,
    max_repairs: int,
) -> ValidationDecision:
    status = test_result.get("status", "failed")

    if status == "success":
        return {
            "next_action": "run_judge",
            "failure_category": "none",
            "reason": "Visible tests passed.",
            "fix_suggestion": "",
        }

    if status == "skipped":
        return {
            "next_action": "run_judge",
            "failure_category": "missing_tests",
            "reason": test_result.get("reason", "Visible tests were skipped."),
            "fix_suggestion": "",
        }

    if status == "c_failed_compilation":
        return {
            "next_action": "stop_failed",
            "failure_category": "compile",
            "reason": "Original C source failed to compile.",
            "fix_suggestion": "",
        }

    category = _visible_failure_category(status, test_result)
    reason = test_result.get("details") or "Visible tests failed."
    return _repair_or_stop(repair_count, max_repairs, category, reason)


def _visible_failure_category(status: str, test_result: dict) -> FailureCategory:
    if test_result.get("rust_compilation") == "failed":
        return "compile"

    return {
        "TIME_LIMIT_EXCEEDED": "timeout",
        "RUNTIME_ERROR": "runtime",
    }.get(status, "correctness")


def validate_judge_result(
    judge_result: JudgeResult,
) -> ValidationDecision:
    status = judge_result.get("status", "INFRA_ERROR")

    if status == "ACCEPTED":
        return {
            "next_action": "stop_success",
            "failure_category": "none",
            "reason": "Judge accepted the translated Rust program.",
            "fix_suggestion": "",
        }

    if status == "SKIPPED":
        return {
            "next_action": "skip",
            "failure_category": "missing_tests",
            "reason": judge_result.get("details", "Judge tests were skipped."),
            "fix_suggestion": "",
        }

    category = JUDGE_FAILURE_CATEGORIES.get(status, "infrastructure")
    reason = judge_result.get("details") or f"Judge returned {status}."
    return {
        "next_action": "stop_evaluated",
        "failure_category": category,
        "reason": reason,
        "fix_suggestion": "",
    }
