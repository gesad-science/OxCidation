"""Reviewed and resumable preparation of generated visible-test suites."""

import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from judge_execution import compile_c
from visible_testing import (
    OPERATIONAL_PREPARATION_STATUSES,
    outputs_equal,
    prompt_sha256,
    run_program,
    source_sha256,
)


MAX_GENERATION_ATTEMPTS = 2


@dataclass
class PreparationContext:
    suite_root: Path
    c_code: str
    generation_prompt: str
    review_prompt: str
    model_provider: str
    model_id: str
    history: list[dict] = field(default_factory=list)
    generation_prompt_tokens: int = 0
    generation_completion_tokens: int = 0
    review_prompt_tokens: int = 0
    review_completion_tokens: int = 0
    generated_candidate_count: int = 0
    rejected_candidate_count: int = 0
    invalid_case_count: int = 0
    inconclusive_case_count: int = 0

    def record(self, attempt_number: int, agent: str, action: str, data: dict) -> None:
        self.history.append(
            {
                "sequence": len(self.history) + 1,
                "attempt_number": attempt_number,
                "agent": agent,
                "action": action,
                "data": data,
            }
        )

    def add_generation(self, generation: dict, usage: dict, attempt: dict) -> None:
        self.generation_prompt_tokens += usage.get("input_tokens", 0)
        self.generation_completion_tokens += usage.get("output_tokens", 0)
        self.generated_candidate_count += len(generation.get("cases", []))
        self.rejected_candidate_count += len(attempt.get("rejected_cases", []))

    def add_review(self, review: dict, usage: dict) -> None:
        self.review_prompt_tokens += usage.get("input_tokens", 0)
        self.review_completion_tokens += usage.get("output_tokens", 0)
        self.invalid_case_count += len(review["invalid_case_ids"])
        self.inconclusive_case_count += len(review["inconclusive_case_ids"])

    def finalize(
        self,
        status: str,
        review_status: str,
        attempt_number: int,
        *,
        attempt: dict | None = None,
        review: dict | None = None,
        details: str = "",
    ) -> dict:
        operational_failure = status in OPERATIONAL_PREPARATION_STATUSES
        active_attempt = (
            attempt["attempt_path"] if status == "ready" and attempt else ""
        )
        active_dir = self.suite_root / active_attempt if active_attempt else None
        suite_hash = suite_sha256(active_dir) if active_dir else ""
        history_path = self.suite_root / "preparation_history.json"
        self.record(
            attempt_number,
            "orchestrator",
            "preparation_failed" if operational_failure else "preparation_completed",
            {
                "status": status,
                "review_status": review_status,
                "active_attempt": active_attempt,
                "suite_sha256": suite_hash,
                "details": details,
            },
        )
        _write_json(history_path, self.history)
        manifest = {
            "status": status,
            "source": "generated",
            "source_sha256": source_sha256(self.c_code),
            "prompt_sha256": prompt_sha256(self.generation_prompt),
            "review_prompt_sha256": prompt_sha256(self.review_prompt),
            "model_provider": self.model_provider,
            "model_id": self.model_id,
            "review_status": review_status,
            "generation_attempt_count": attempt_number,
            "candidate_count": attempt.get("candidate_count", 0) if attempt else 0,
            "generated_candidate_count": self.generated_candidate_count,
            "rejected_candidate_count": self.rejected_candidate_count,
            "invalid_case_count": self.invalid_case_count,
            "inconclusive_case_count": self.inconclusive_case_count,
            "unresolved_replacement_count": (
                attempt.get("unresolved_replacement_count", 0) if attempt else 0
            ),
            "case_count": attempt.get("case_count", 0) if active_attempt else 0,
            "strategy": attempt.get("strategy", "") if attempt else "",
            "cases": attempt.get("cases", []) if active_attempt else [],
            "rejected_cases": attempt.get("rejected_cases", []) if attempt else [],
            "review": review or {},
            "prompt_tokens": self.generation_prompt_tokens,
            "completion_tokens": self.generation_completion_tokens,
            "review_prompt_tokens": self.review_prompt_tokens,
            "review_completion_tokens": self.review_completion_tokens,
            "active_attempt": active_attempt,
            "suite_sha256": suite_hash,
            "preparation_history_path": str(history_path),
            "frozen": not operational_failure,
            "details": details,
            "c_compile_profile": (
                attempt.get("c_compile_profile", "") if attempt else ""
            ),
            "c_compile_attempts": (
                attempt.get("c_compile_attempts", []) if attempt else []
            ),
        }
        return _write_suite_manifest(self.suite_root, manifest)


def prepare_generated_suite(
    c_code: str,
    test_root: str | Path,
    timeout_sec: float,
    generation_prompt: str,
    review_prompt: str,
    model_provider: str,
    model_id: str,
    generate_candidates: Callable[[str], tuple[dict, dict]],
    review_candidates: Callable[[list[dict], dict], tuple[dict, dict]],
) -> dict:
    suite_root = Path(test_root) / source_sha256(c_code)[:12]
    suite_root.mkdir(parents=True, exist_ok=True)
    context = PreparationContext(
        suite_root,
        c_code,
        generation_prompt,
        review_prompt,
        model_provider,
        model_id,
    )
    regeneration_feedback = ""
    approved_cases: list[dict] = []
    discarded_cases: list[dict] = []
    saw_inconclusive = False
    replacement_target = 0

    for attempt_number in range(1, MAX_GENERATION_ATTEMPTS + 1):
        try:
            generation, generation_usage = generate_candidates(regeneration_feedback)
        except Exception as error:
            context.record(
                attempt_number,
                "tester",
                "generation_failed",
                {"details": str(error)},
            )
            return context.finalize(
                "generation_failed",
                "not_completed",
                attempt_number,
                details=f"Visible-test generation failed: {error}",
            )

        attempt = materialize_generation_attempt(
            c_code,
            generation,
            suite_root,
            attempt_number,
            timeout_sec,
            generation_prompt,
            regeneration_feedback,
            {case["input"] for case in approved_cases},
            replacement_limit=(
                json.loads(regeneration_feedback)["replacement_count"]
                if regeneration_feedback
                else None
            ),
        )
        context.add_generation(generation, generation_usage, attempt)
        _record_deterministic_results(context, attempt_number, attempt)

        if attempt["status"] == "baseline_compile_failed":
            return context.finalize(
                "baseline_compile_failed",
                "not_completed",
                attempt_number,
                attempt=attempt,
                details=attempt["details"],
            )

        review_cases = attempt.get("review_cases", [])
        try:
            review, review_usage = _review_attempt(
                review_cases,
                attempt,
                review_candidates,
            )
        except Exception as error:
            details = f"Visible-test review failed: {error}"
            context.record(
                attempt_number,
                "validator",
                "review_failed",
                {"details": details, "attempt_path": attempt["attempt_path"]},
            )
            return context.finalize(
                "review_failed",
                "not_completed",
                attempt_number,
                attempt=attempt,
                details=details,
            )
        context.add_review(review, review_usage)
        _record_review(context, attempt_number, attempt, review)

        approved_in_attempt = _collect_approved_cases(attempt, review)
        approved_cases.extend(approved_in_attempt)
        rejected_for_replacement = _replacement_rejections(attempt, review)
        discarded_cases.extend(_discarded_review_cases(attempt, review))
        discarded_cases.extend(_discarded_deterministic_cases(attempt))
        saw_inconclusive = saw_inconclusive or bool(review["inconclusive_case_ids"])

        if rejected_for_replacement and attempt_number < MAX_GENERATION_ATTEMPTS:
            replacement_target = len(rejected_for_replacement)
            regeneration_feedback = _replacement_feedback(rejected_for_replacement)
            context.record(
                attempt_number,
                "validator",
                "replacement_requested",
                {
                    "replacement_count": len(rejected_for_replacement),
                    "rejected_cases": rejected_for_replacement,
                    "guidance": regeneration_feedback,
                },
            )
            continue

        if approved_cases:
            unresolved_replacements = (
                max(0, replacement_target - len(approved_in_attempt))
                if attempt_number > 1
                else 0
            )
            frozen = _freeze_approved_cases(
                context,
                approved_cases,
                discarded_cases,
                attempt,
                unresolved_replacements,
            )
            final_review = _approved_frozen_review(frozen, discarded_cases)
            return context.finalize(
                "ready",
                "approved",
                attempt_number,
                attempt=frozen,
                review=final_review,
                details=frozen["details"],
            )

        status = "review_inconclusive" if saw_inconclusive else "invalid_visible_tests"
        review_status = "inconclusive" if saw_inconclusive else "invalid"
        return context.finalize(
            status,
            review_status,
            attempt_number,
            attempt=attempt,
            review=review,
            details=review["diagnosis"],
        )

    raise AssertionError("Visible-test preparation exhausted without a terminal result.")


def materialize_generation_attempt(
    c_code: str,
    generation: dict,
    suite_root: Path,
    attempt_number: int,
    timeout_sec: float,
    generation_prompt: str,
    regeneration_feedback: str,
    preserved_inputs: set[str] | None = None,
    replacement_limit: int | None = None,
) -> dict:
    attempt_path = Path("attempts") / f"attempt-{attempt_number:02d}"
    attempt_dir = suite_root / attempt_path
    attempt_dir.mkdir(parents=True, exist_ok=True)
    for path in attempt_dir.glob("case-*.*"):
        path.unlink()

    generated_candidates = generation.get("cases", [])
    candidates = (
        generated_candidates[:replacement_limit]
        if replacement_limit is not None
        else generated_candidates
    )
    _write_json(
        attempt_dir / "generation.json",
        {
            "strategy": generation.get("strategy", ""),
            "cases": generated_candidates,
            "selected_replacements": len(candidates),
            "requested_replacements": replacement_limit,
            "prompt_sha256": prompt_sha256(generation_prompt),
            "regeneration_feedback": regeneration_feedback,
        },
    )
    result = _new_attempt_result(
        attempt_dir,
        attempt_path,
        generation.get("strategy", ""),
        len(candidates),
        generation_prompt,
    )

    with tempfile.TemporaryDirectory(prefix="oxcidation-visible-c-") as temp_dir:
        compilation, c_binary = compile_c(c_code, temp_dir)
        result["c_compile_profile"] = getattr(
            compilation,
            "compile_profile",
            "unknown",
        )
        result["c_compile_attempts"] = getattr(
            compilation,
            "compile_attempts",
            [],
        )
        if compilation.returncode != 0:
            result.update(status="baseline_compile_failed", details=compilation.stderr)
            return result

        seen_inputs = set(preserved_inputs or ())
        for candidate_index, candidate in enumerate(candidates, start=1):
            _materialize_candidate(
                result,
                attempt_dir,
                c_binary,
                candidate_index,
                candidate,
                timeout_sec,
                seen_inputs,
            )

    result["case_count"] = len(result["cases"])
    if result["case_count"]:
        result.update(status="ready", details="")
    return result


def _new_attempt_result(
    attempt_dir: Path,
    attempt_path: Path,
    strategy: str,
    candidate_count: int,
    generation_prompt: str,
) -> dict:
    return {
        "status": "no_valid_cases",
        "suite_dir": str(attempt_dir),
        "attempt_path": str(attempt_path),
        "prompt_sha256": prompt_sha256(generation_prompt),
        "strategy": strategy,
        "candidate_count": candidate_count,
        "case_count": 0,
        "cases": [],
        "rejected_cases": [],
        "deterministic_evaluations": [],
        "review_cases": [],
        "details": "The C oracle rejected every generated input.",
    }


def _materialize_candidate(
    result: dict,
    attempt_dir: Path,
    c_binary: str,
    candidate_index: int,
    candidate: dict,
    timeout_sec: float,
    seen_inputs: set[str],
) -> None:
    input_data = candidate.get("input", "")
    purpose = candidate.get("purpose", "").strip()
    if input_data in seen_inputs:
        rejection = _rejected_case(
            candidate_index,
            purpose,
            "DUPLICATE_INPUT",
            "Duplicate input.",
        )
        rejection["input"] = input_data
        result["rejected_cases"].append(rejection)
        result["review_cases"].append(
            {
                "id": f"candidate-{candidate_index:03d}",
                "purpose": purpose,
                "input": input_data,
            }
        )
        result["deterministic_evaluations"].append(
            _deterministic_evaluation(candidate_index, rejection["verdict"])
        )
        return
    seen_inputs.add(input_data)

    first_run = run_program(c_binary, input_data, timeout_sec)
    second_run = run_program(c_binary, input_data, timeout_sec)
    rejection = _stability_rejection(
        candidate_index,
        purpose,
        first_run,
        second_run,
    )
    if rejection:
        rejection["input"] = input_data
        result["rejected_cases"].append(rejection)
        result["review_cases"].append(
            {
                "id": f"candidate-{candidate_index:03d}",
                "purpose": purpose,
                "input": input_data,
            }
        )
        result["deterministic_evaluations"].append(
            _deterministic_evaluation(
                candidate_index,
                rejection["verdict"],
                first_run,
                second_run,
            )
        )
        return

    case_id = f"case-{len(result['cases']) + 1:03d}"
    input_file = f"{case_id}.in"
    output_file = f"{case_id}.out"
    (attempt_dir / input_file).write_text(input_data, encoding="utf-8")
    (attempt_dir / output_file).write_text(first_run["stdout"], encoding="utf-8")
    result["cases"].append(
        {
            "id": case_id,
            "candidate_id": f"candidate-{candidate_index:03d}",
            "purpose": purpose,
            "input_file": input_file,
            "output_file": output_file,
        }
    )
    result["review_cases"].append(
        {"id": case_id, "purpose": purpose, "input": input_data}
    )
    result["deterministic_evaluations"].append(
        _deterministic_evaluation(
            candidate_index,
            "ACCEPTED_STABLE",
            first_run,
            second_run,
            case_id,
        )
    )


def _review_attempt(
    review_cases: list[dict],
    attempt: dict,
    review_candidates: Callable[[list[dict], dict], tuple[dict, dict]],
) -> tuple[dict, dict]:
    if not review_cases:
        return {
            "assessment": "invalid",
            "diagnosis": "The deterministic C oracle rejected every generated input.",
            "verified_case_ids": [],
            "invalid_case_ids": [],
            "inconclusive_case_ids": [],
            "case_reviews": [],
            "regeneration_guidance": (
                "Generate complete inputs that terminate normally and produce stable output "
                "when executed by the C program."
            ),
        }, {}
    deterministic_report = {
        "candidate_count": attempt["candidate_count"],
        "accepted_count": attempt["case_count"],
        "rejected_cases": attempt["rejected_cases"],
        "evaluations": attempt["deterministic_evaluations"],
    }
    review, usage = review_candidates(review_cases, deterministic_report)
    return _normalize_review(review, {case["id"] for case in review_cases}), usage


def _record_deterministic_results(
    context: PreparationContext,
    attempt_number: int,
    attempt: dict,
) -> None:
    context.record(
        attempt_number,
        "tester",
        "generated_candidates",
        {
            "candidate_count": attempt["candidate_count"],
            "strategy": attempt["strategy"],
            "attempt_path": attempt["attempt_path"],
        },
    )
    context.record(
        attempt_number,
        "tester",
        "deterministic_validation",
        {
            "status": attempt["status"],
            "c_compile_profile": attempt.get("c_compile_profile", ""),
            "c_compile_attempts": attempt.get("c_compile_attempts", []),
            "accepted_count": attempt["case_count"],
            "rejected_count": len(attempt["rejected_cases"]),
            "evaluations": attempt["deterministic_evaluations"],
            "attempt_path": attempt["attempt_path"],
        },
    )


def _record_review(
    context: PreparationContext,
    attempt_number: int,
    attempt: dict,
    review: dict,
) -> None:
    attempt_dir = Path(attempt["suite_dir"])
    _write_json(attempt_dir / "review.json", review)
    attempt_manifest = {
        key: value
        for key, value in attempt.items()
        if key not in {"suite_dir", "review_cases"}
    }
    attempt_manifest["review"] = review
    _write_json(attempt_dir / "attempt.json", attempt_manifest)
    context.record(
        attempt_number,
        "validator",
        "case_review",
        {
            "assessment": review["assessment"],
            "diagnosis": review["diagnosis"],
            "approved_case_count": len(review["verified_case_ids"]),
            "invalid_case_count": len(review["invalid_case_ids"]),
            "inconclusive_case_count": len(review["inconclusive_case_ids"]),
            "case_reviews": review["case_reviews"],
            "attempt_path": attempt["attempt_path"],
        },
    )


def _normalize_review(review: dict, known_case_ids: set[str]) -> dict:
    case_reviews = review.get("case_reviews")
    if not isinstance(case_reviews, list):
        case_reviews = _legacy_case_reviews(review, known_case_ids)

    reviewed_ids = [item.get("case_id") for item in case_reviews]
    duplicate_ids = {case_id for case_id in reviewed_ids if reviewed_ids.count(case_id) > 1}
    if duplicate_ids:
        raise ValueError(
            "Visible-test review repeated cases: " + ", ".join(sorted(duplicate_ids))
        )
    reviewed_set = set(reviewed_ids)
    if reviewed_set != known_case_ids:
        missing = known_case_ids - reviewed_set
        unknown = reviewed_set - known_case_ids
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown " + ", ".join(sorted(unknown)))
        raise ValueError(
            "Visible-test review must assess every supplied case: " + "; ".join(details)
        )

    normalized_cases = []
    for item in case_reviews:
        assessment = item.get("assessment")
        if assessment not in {"approved", "invalid", "inconclusive"}:
            raise ValueError(
                f"Unsupported visible-test case assessment: {assessment}"
            )
        normalized_cases.append(
            {
                "case_id": item["case_id"],
                "assessment": assessment,
                "diagnosis": str(item.get("diagnosis", "")).strip(),
                "regeneration_guidance": str(
                    item.get("regeneration_guidance", "")
                ).strip(),
            }
        )

    verified_case_ids = [
        item["case_id"] for item in normalized_cases if item["assessment"] == "approved"
    ]
    invalid_case_ids = [
        item["case_id"] for item in normalized_cases if item["assessment"] == "invalid"
    ]
    inconclusive_case_ids = [
        item["case_id"]
        for item in normalized_cases
        if item["assessment"] == "inconclusive"
    ]
    assessment = (
        "invalid"
        if invalid_case_ids
        else "inconclusive"
        if inconclusive_case_ids
        else "approved"
    )
    diagnosis = " ".join(
        f"{item['case_id']}: {item['diagnosis']}"
        for item in normalized_cases
        if item["diagnosis"]
    )
    regeneration_guidance = " ".join(
        f"{item['case_id']}: {item['regeneration_guidance']}"
        for item in normalized_cases
        if item["assessment"] == "invalid" and item["regeneration_guidance"]
    )

    return {
        "assessment": assessment,
        "diagnosis": diagnosis,
        "verified_case_ids": verified_case_ids,
        "invalid_case_ids": invalid_case_ids,
        "inconclusive_case_ids": inconclusive_case_ids,
        "case_reviews": normalized_cases,
        "regeneration_guidance": regeneration_guidance,
    }


def _legacy_case_reviews(review: dict, known_case_ids: set[str]) -> list[dict]:
    assessment = review.get("assessment")
    if assessment not in {"approved", "invalid", "inconclusive"}:
        raise ValueError("Visible-test review must contain case_reviews.")
    verified = set(review.get("verified_case_ids", []))
    invalid = set(review.get("invalid_case_ids", []))
    if verified & invalid:
        raise ValueError("A visible-test case cannot be both verified and invalid.")
    if assessment == "approved" and verified != known_case_ids:
        raise ValueError(
            "An approved visible-test review must explicitly verify every case."
        )
    if assessment == "invalid" and not invalid:
        raise ValueError("An invalid visible-test review must identify at least one case.")
    case_reviews = []
    for case_id in sorted(known_case_ids):
        case_assessment = (
            "approved"
            if case_id in verified
            else "invalid"
            if case_id in invalid
            else "inconclusive"
        )
        case_reviews.append(
            {
                "case_id": case_id,
                "assessment": case_assessment,
                "diagnosis": review.get("diagnosis", ""),
                "regeneration_guidance": (
                    review.get("regeneration_guidance", "")
                    if case_assessment == "invalid"
                    else ""
                ),
            }
        )
    return case_reviews


def _collect_approved_cases(attempt: dict, review: dict) -> list[dict]:
    approved_ids = set(review["verified_case_ids"])
    attempt_dir = Path(attempt["suite_dir"])
    approved = []
    for case in attempt["cases"]:
        if case["id"] not in approved_ids:
            continue
        approved.append(
            {
                "purpose": case["purpose"],
                "input": (attempt_dir / case["input_file"]).read_text(encoding="utf-8"),
                "output": (attempt_dir / case["output_file"]).read_text(encoding="utf-8"),
                "origin_attempt": attempt["attempt_path"],
                "origin_case_id": case["id"],
                "origin_candidate_id": case["candidate_id"],
            }
        )
    return approved


def _replacement_rejections(attempt: dict, review: dict) -> list[dict]:
    cases_by_id = {case["id"]: case for case in attempt["review_cases"]}
    reviews_by_id = {item["case_id"]: item for item in review["case_reviews"]}
    deterministic_by_id = {
        f"candidate-{item['candidate']:03d}": item
        for item in attempt["rejected_cases"]
    }
    rejected = []
    for case_id, item in deterministic_by_id.items():
        case_review = reviews_by_id[case_id]
        rejected.append(
            {
                "origin": "deterministic_validation",
                "case_id": case_id,
                "purpose": item["purpose"],
                "input": item.get("input", ""),
                "verdict": item["verdict"],
                "guidance": (
                    case_review["regeneration_guidance"]
                    or case_review["diagnosis"]
                    or item.get("details", "")
                ),
            }
        )
    for case_id in review["invalid_case_ids"]:
        if case_id in deterministic_by_id:
            continue
        case_review = reviews_by_id[case_id]
        rejected.append(
            {
                "origin": "validator",
                "case_id": case_id,
                "purpose": cases_by_id[case_id]["purpose"],
                "input": cases_by_id[case_id]["input"],
                "verdict": "INVALID",
                "guidance": (
                    case_review["regeneration_guidance"]
                    or case_review["diagnosis"]
                ),
            }
        )
    return rejected


def _discarded_review_cases(attempt: dict, review: dict) -> list[dict]:
    cases_by_id = {case["id"]: case for case in attempt["review_cases"]}
    deterministic_ids = {
        f"candidate-{item['candidate']:03d}" for item in attempt["rejected_cases"]
    }
    return [
        {
            "origin_attempt": attempt["attempt_path"],
            "case_id": item["case_id"],
            "purpose": cases_by_id[item["case_id"]]["purpose"],
            "input": cases_by_id[item["case_id"]]["input"],
            "assessment": item["assessment"],
            "diagnosis": item["diagnosis"],
        }
        for item in review["case_reviews"]
        if item["assessment"] != "approved" and item["case_id"] not in deterministic_ids
    ]


def _discarded_deterministic_cases(attempt: dict) -> list[dict]:
    return [
        {
            "origin_attempt": attempt["attempt_path"],
            "candidate_id": f"candidate-{item['candidate']:03d}",
            "purpose": item["purpose"],
            "input": item.get("input", ""),
            "assessment": "deterministic_rejection",
            "diagnosis": item["verdict"],
        }
        for item in attempt["rejected_cases"]
    ]


def _replacement_feedback(rejected_cases: list[dict]) -> str:
    return json.dumps(
        {
            "replacement_count": len(rejected_cases),
            "rejected_cases": rejected_cases,
        },
        ensure_ascii=False,
    )


def _freeze_approved_cases(
    context: PreparationContext,
    approved_cases: list[dict],
    discarded_cases: list[dict],
    latest_attempt: dict,
    unresolved_replacement_count: int,
) -> dict:
    frozen_path = Path("frozen")
    frozen_dir = context.suite_root / frozen_path
    frozen_dir.mkdir(parents=True, exist_ok=True)
    for path in frozen_dir.glob("case-*.*"):
        path.unlink()

    cases = []
    for index, approved in enumerate(approved_cases, start=1):
        case_id = f"case-{index:03d}"
        input_file = f"{case_id}.in"
        output_file = f"{case_id}.out"
        (frozen_dir / input_file).write_text(approved["input"], encoding="utf-8")
        (frozen_dir / output_file).write_text(approved["output"], encoding="utf-8")
        cases.append(
            {
                "id": case_id,
                "purpose": approved["purpose"],
                "input_file": input_file,
                "output_file": output_file,
                "origin_attempt": approved["origin_attempt"],
                "origin_case_id": approved["origin_case_id"],
                "origin_candidate_id": approved["origin_candidate_id"],
            }
        )

    details = ""
    if unresolved_replacement_count:
        details = (
            f"Frozen {len(cases)} approved cases; "
            f"{unresolved_replacement_count} requested replacements remained unavailable."
        )
    frozen = {
        "status": "ready",
        "suite_dir": str(frozen_dir),
        "attempt_path": str(frozen_path),
        "strategy": "Approved cases preserved across generation attempts.",
        "candidate_count": len(cases),
        "case_count": len(cases),
        "cases": cases,
        "rejected_cases": discarded_cases,
        "deterministic_evaluations": [],
        "review_cases": [],
        "details": details,
        "unresolved_replacement_count": unresolved_replacement_count,
        "c_compile_profile": latest_attempt.get("c_compile_profile", ""),
        "c_compile_attempts": latest_attempt.get("c_compile_attempts", []),
    }
    _write_json(
        frozen_dir / "suite_composition.json",
        {
            "cases": cases,
            "discarded_cases": discarded_cases,
            "unresolved_replacement_count": unresolved_replacement_count,
        },
    )
    return frozen


def _approved_frozen_review(frozen: dict, discarded_cases: list[dict]) -> dict:
    return {
        "assessment": "approved",
        "diagnosis": "Every case in the frozen suite was individually approved.",
        "verified_case_ids": [case["id"] for case in frozen["cases"]],
        "invalid_case_ids": [],
        "inconclusive_case_ids": [],
        "case_reviews": [
            {
                "case_id": case["id"],
                "assessment": "approved",
                "diagnosis": (
                    f"Preserved from {case['origin_attempt']}:{case['origin_case_id']}."
                ),
                "regeneration_guidance": "",
            }
            for case in frozen["cases"]
        ],
        "regeneration_guidance": "",
        "discarded_cases": discarded_cases,
    }


def _stability_rejection(
    candidate_index: int,
    purpose: str,
    first_run: dict,
    second_run: dict,
) -> dict | None:
    if first_run["status"] != "ACCEPTED":
        return _rejected_case(
            candidate_index,
            purpose,
            first_run["status"],
            first_run.get("stderr", ""),
        )
    if second_run["status"] != "ACCEPTED":
        return _rejected_case(
            candidate_index,
            purpose,
            "UNSTABLE_EXECUTION",
            f"Second C execution returned {second_run['status']}. "
            f"{second_run.get('stderr', '')}",
        )
    if not outputs_equal(first_run["stdout"], second_run["stdout"]):
        return _rejected_case(
            candidate_index,
            purpose,
            "NONDETERMINISTIC_OUTPUT",
            "Repeated C executions produced different normalized outputs.",
        )
    return None


def suite_sha256(suite_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(suite_dir.glob("case-*.*")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _deterministic_evaluation(
    candidate_index: int,
    verdict: str,
    first_run: dict | None = None,
    second_run: dict | None = None,
    case_id: str = "",
) -> dict:
    first_run = first_run or {}
    second_run = second_run or {}
    first_stdout = first_run.get("stdout", "")
    second_stdout = second_run.get("stdout", "")
    return {
        "candidate_id": f"candidate-{candidate_index:03d}",
        "case_id": case_id,
        "verdict": verdict,
        "first_run_status": first_run.get("status", "not_run"),
        "second_run_status": second_run.get("status", "not_run"),
        "first_output_bytes": len(first_stdout.encode("utf-8")),
        "second_output_bytes": len(second_stdout.encode("utf-8")),
        "stable_output_empty": (
            bool(first_run)
            and bool(second_run)
            and not first_stdout
            and not second_stdout
        ),
        "normalized_outputs_match": (
            bool(first_run)
            and bool(second_run)
            and outputs_equal(
                first_stdout,
                second_stdout,
            )
        ),
    }


def _write_suite_manifest(suite_root: Path, manifest: dict) -> dict:
    _write_json(suite_root / "suite.json", manifest)
    active_attempt = manifest.get("active_attempt", "")
    active_dir = suite_root / active_attempt if active_attempt else suite_root
    return {**manifest, "suite_dir": str(active_dir), "reused": False}


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _rejected_case(index: int, purpose: str, verdict: str, details: str) -> dict:
    return {
        "candidate": index,
        "purpose": purpose,
        "verdict": verdict,
        "details": details[:1000],
    }
