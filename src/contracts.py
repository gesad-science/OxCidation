from typing import Literal, TypedDict


PipelineStatus = Literal[
    "success",
    "failed",
    "in_progress",
    "evaluated",
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
    "invalid_tests",
    "inconclusive_tests",
    "invalid_baseline",
    "infrastructure",
]

TestAssessment = Literal[
    "translation_discrepancy",
    "invalid_visible_test",
    "inconclusive",
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


class ValidatorReport(TypedDict, total=False):
    status: str
    test_assessment: TestAssessment
    diagnosis: str
    repair_guidance: str
    semantic_discrepancies: list[str]
    error: str


class VisibleTestSuite(TypedDict, total=False):
    status: str
    source: str
    source_sha256: str
    prompt_sha256: str
    strategy: str
    candidate_count: int
    case_count: int
    suite_dir: str
    reused: bool
    prompt_tokens: int
    completion_tokens: int
    review_prompt_tokens: int
    review_completion_tokens: int
    review_status: str
    review_count: int
    generation_attempt_count: int
    generated_candidate_count: int
    deterministic_rejection_count: int
    validator_replacement_count: int
    unresolved_replacement_count: int
    suite_sha256: str
    preparation_history_path: str
    frozen: bool
    details: str
    c_compile_profile: str
    c_compile_attempts: list[dict]


class TestReport(TypedDict, total=False):
    status: PipelineStatus
    failure_category: FailureCategory
    suite_dir: str
    c_compilation: str
    rust_compilation: str
    total_tests: int
    c_passed: int
    c_failed: int
    rust_passed: int
    rust_failed: int
    failed_rust_where_c_passed: int
    failed_tests: list[str]
    verdict_counts: dict[str, int]
    failure_examples: list[dict]
    baseline_failures: list[dict]
    details: str


class AgentInteraction(TypedDict, total=False):
    sequence: int
    agent: str
    action: str
    repair_count: int
    caused_by_sequence: int
    data: dict


class RepairRequest(TypedDict):
    c_code: str
    rust_code: str
    feedback: str
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
    baseline_status: str
