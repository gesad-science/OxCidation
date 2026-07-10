from typing import Literal, TypedDict


PipelineStatus = Literal[
    "success",
    "failed",
    "in_progress",
    "c_failed_compilation",
    "skipped",
]

JudgeStatus = Literal[
    "ACCEPTED",
    "COMPILATION_ERROR",
    "RUNTIME_ERROR",
    "WRONG_ANSWER",
    "TIME_LIMIT_EXCEEDED",
    "MEMORY_LIMIT_EXCEEDED",
    "SKIPPED",
    "INFRA_ERROR",
]

FailureCategory = Literal[
    "none",
    "compile",
    "correctness",
    "runtime",
    "timeout",
    "memory",
    "missing_tests",
    "infrastructure",
]

NextAction = Literal[
    "compile_translation",
    "run_visible_tests",
    "run_judge",
    "repair_translation",
    "stop_success",
    "stop_evaluated",
    "stop_failed",
    "skip",
]


class TranslationRequest(TypedDict, total=False):
    file_name: str
    c_code: str
    attempt_context: str


class TranslationResult(TypedDict, total=False):
    rust_code: str
    status: PipelineStatus
    errors: str
    prompt_tokens: int
    completion_tokens: int


class RepairRequest(TypedDict):
    rust_code: str
    failure_report: str
    failure_category: FailureCategory
    attempt_number: int


class ValidationDecision(TypedDict):
    next_action: NextAction
    failure_category: FailureCategory
    reason: str
    fix_suggestion: str


class JudgeResult(TypedDict, total=False):
    status: JudgeStatus
    passed: int
    failed: int
    total: int
    time_ms: int
    details: str
    verdict_counts: dict
    first_failure: dict
    raw_output: str
