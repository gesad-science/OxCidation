"""Prepare reviewed, resumable visible-test batches from generated inputs."""

import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from judge_execution import compile_c
from visible_testing import (
    OPERATIONAL_PREPARATION_STATUSES,
    prompt_sha256,
    run_program,
    source_sha256,
)


MAX_GENERATION_ATTEMPTS = 3
MAX_REVIEW_ATTEMPTS = 2


@dataclass
class PreparationContext:
    suite_root: Path
    c_code: str
    generation_prompt: str
    review_prompt: str
    model_provider: str
    model_id: str
    history: list[dict] = field(default_factory=list)
    generation_attempt_count: int = 0
    review_count: int = 0
    generation_prompt_tokens: int = 0
    generation_completion_tokens: int = 0
    review_prompt_tokens: int = 0
    review_completion_tokens: int = 0
    generated_candidate_count: int = 0
    deterministic_rejection_count: int = 0
    validator_replacement_count: int = 0

    def record(self, agent: str, action: str, data: dict) -> None:
        self.history.append(
            {
                "sequence": len(self.history) + 1,
                "generation_attempt": self.generation_attempt_count,
                "review_attempt": self.review_count,
                "agent": agent,
                "action": action,
                "data": data,
            }
        )

    def add_generation(self, generation: dict, usage: dict, attempt: dict) -> None:
        self.generation_prompt_tokens += usage.get("input_tokens", 0)
        self.generation_completion_tokens += usage.get("output_tokens", 0)
        self.generated_candidate_count += len(generation.get("cases", []))
        self.deterministic_rejection_count += len(attempt["rejected_cases"])

    def add_review(self, review: dict, usage: dict) -> None:
        self.review_prompt_tokens += usage.get("input_tokens", 0)
        self.review_completion_tokens += usage.get("output_tokens", 0)
        self.validator_replacement_count += len(review["replacements"])

    def finalize(
        self,
        status: str,
        review_status: str,
        *,
        batch: dict | None = None,
        review: dict | None = None,
        unresolved_replacements: int = 0,
        details: str = "",
    ) -> dict:
        operational_failure = status in OPERATIONAL_PREPARATION_STATUSES
        active_attempt = batch["attempt_path"] if status == "ready" and batch else ""
        active_dir = self.suite_root / active_attempt if active_attempt else None
        suite_hash = suite_sha256(active_dir) if active_dir else ""
        history_path = self.suite_root / "preparation_history.json"
        self.record(
            "orchestrator",
            "preparation_failed" if operational_failure else "preparation_completed",
            {
                "status": status,
                "review_status": review_status,
                "active_attempt": active_attempt,
                "suite_sha256": suite_hash,
                "unresolved_replacements": unresolved_replacements,
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
            "generation_attempt_count": self.generation_attempt_count,
            "review_count": self.review_count,
            "candidate_count": batch.get("candidate_count", 0) if batch else 0,
            "generated_candidate_count": self.generated_candidate_count,
            "deterministic_rejection_count": self.deterministic_rejection_count,
            "validator_replacement_count": self.validator_replacement_count,
            "unresolved_replacement_count": unresolved_replacements,
            "case_count": batch.get("case_count", 0) if active_attempt else 0,
            "strategy": batch.get("strategy", "") if batch else "",
            "cases": batch.get("cases", []) if active_attempt else [],
            "rejected_cases": batch.get("rejected_cases", []) if batch else [],
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
            "c_compile_profile": batch.get("c_compile_profile", "") if batch else "",
            "c_compile_attempts": batch.get("c_compile_attempts", []) if batch else [],
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

    with tempfile.TemporaryDirectory(prefix="oxcidation-visible-c-") as temp_dir:
        compilation, c_binary = compile_c(c_code, temp_dir)
        compile_metadata = _compile_metadata(compilation)
        if compilation.returncode != 0:
            failed_batch = _empty_batch(compile_metadata, compilation.stderr)
            return context.finalize(
                "baseline_compile_failed",
                "not_completed",
                batch=failed_batch,
                details=compilation.stderr,
            )

        try:
            initial = _generate_attempt(
                context,
                generate_candidates,
                c_binary,
                timeout_sec,
                compile_metadata,
                feedback="",
            )
        except Exception as error:
            return _generation_failure(context, error)

        target_case_count = initial["candidate_count"]
        strategy = initial["strategy"]
        batch = _accepted_cases(initial)
        discarded = _discarded_deterministic_cases(initial)
        unresolved = set(_rejected_case_ids(initial))
        rejected_inputs = _rejected_inputs(initial)

        if unresolved and context.generation_attempt_count < MAX_GENERATION_ATTEMPTS:
            try:
                replacement = _generate_attempt(
                    context,
                    generate_candidates,
                    c_binary,
                    timeout_sec,
                    compile_metadata,
                    feedback=_replacement_request(
                        sorted(unresolved),
                        batch,
                        rejected_inputs,
                    ),
                    slot_ids=sorted(unresolved),
                    seen_inputs=_batch_inputs(batch) | rejected_inputs,
                )
            except Exception as error:
                return _generation_failure(
                    context,
                    error,
                    batch=_batch_result(
                        batch,
                        discarded,
                        target_case_count,
                        strategy,
                        compile_metadata,
                    ),
                )
            batch.update(_accepted_cases(replacement))
            discarded.extend(_discarded_deterministic_cases(replacement))
            unresolved = set(_rejected_case_ids(replacement))
            rejected_inputs.update(_rejected_inputs(replacement))

        if not batch:
            unavailable = _batch_result(
                batch,
                discarded,
                target_case_count,
                strategy,
                compile_metadata,
            )
            return context.finalize(
                "invalid_visible_tests",
                "not_reviewed",
                batch=unavailable,
                unresolved_replacements=len(unresolved),
                details="The C oracle rejected every generated input.",
            )

        review = _review_batch(context, batch, review_candidates)
        if review.get("error"):
            return context.finalize(
                "review_failed",
                "not_completed",
                batch=_batch_result(
                    batch,
                    discarded,
                    target_case_count,
                    strategy,
                    compile_metadata,
                ),
                details=review["error"],
            )

        if review["assessment"] == "revise":
            requested = {item["case_id"]: item for item in review["replacements"]}
            rejected_inputs.update(
                _discard_validator_replacements(batch, discarded, requested)
            )
            unresolved.update(requested)
            if context.generation_attempt_count < MAX_GENERATION_ATTEMPTS:
                try:
                    replacement = _generate_attempt(
                        context,
                        generate_candidates,
                        c_binary,
                        timeout_sec,
                        compile_metadata,
                        feedback=_replacement_request(
                            list(requested),
                            batch,
                            rejected_inputs,
                            requested,
                        ),
                        slot_ids=list(requested),
                        seen_inputs=_batch_inputs(batch) | rejected_inputs,
                    )
                except Exception as error:
                    return _generation_failure(
                        context,
                        error,
                        batch=_batch_result(
                            batch,
                            discarded,
                            target_case_count,
                            strategy,
                            compile_metadata,
                        ),
                    )
                batch.update(_accepted_cases(replacement))
                discarded.extend(_discarded_deterministic_cases(replacement))
                rejected_slots = set(_rejected_case_ids(replacement))
                unresolved.difference_update(batch)
                unresolved.update(rejected_slots)
                rejected_inputs.update(_rejected_inputs(replacement))

            if unresolved and context.generation_attempt_count < MAX_GENERATION_ATTEMPTS:
                try:
                    recovery = _generate_attempt(
                        context,
                        generate_candidates,
                        c_binary,
                        timeout_sec,
                        compile_metadata,
                        feedback=_replacement_request(
                            sorted(unresolved),
                            batch,
                            rejected_inputs,
                        ),
                        slot_ids=sorted(unresolved),
                        seen_inputs=_batch_inputs(batch) | rejected_inputs,
                    )
                except Exception as error:
                    return _generation_failure(
                        context,
                        error,
                        batch=_batch_result(
                            batch,
                            discarded,
                            target_case_count,
                            strategy,
                            compile_metadata,
                        ),
                    )
                batch.update(_accepted_cases(recovery))
                discarded.extend(_discarded_deterministic_cases(recovery))
                unresolved = set(_rejected_case_ids(recovery))

            if batch and context.review_count < MAX_REVIEW_ATTEMPTS:
                review = _review_batch(context, batch, review_candidates)
                if review.get("error"):
                    return context.finalize(
                        "review_failed",
                        "not_completed",
                        batch=_batch_result(
                            batch,
                            discarded,
                            target_case_count,
                            strategy,
                            compile_metadata,
                        ),
                        details=review["error"],
                    )
                if review["assessment"] == "revise":
                    final_replacements = {
                        item["case_id"]: item for item in review["replacements"]
                    }
                    rejected_inputs.update(
                        _discard_validator_replacements(
                            batch,
                            discarded,
                            final_replacements,
                        )
                    )
                    unresolved.update(final_replacements)

        if not batch:
            unavailable = _batch_result(
                batch,
                discarded,
                target_case_count,
                strategy,
                compile_metadata,
            )
            return context.finalize(
                "invalid_visible_tests",
                "revision_unresolved",
                batch=unavailable,
                review=review,
                unresolved_replacements=len(unresolved),
                details="No usable visible tests remained after batch review.",
            )

        frozen = _freeze_batch(
            context,
            batch,
            discarded,
            target_case_count,
            strategy,
            compile_metadata,
            len(unresolved),
        )
        review_status = (
            "approved" if review["assessment"] == "approved" else "revision_unresolved"
        )
        return context.finalize(
            "ready",
            review_status,
            batch=frozen,
            review=review,
            unresolved_replacements=len(unresolved),
            details=frozen["details"],
        )


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
    """Materialize one deterministic generation attempt without LLM review."""
    attempt_path = Path("attempts") / f"attempt-{attempt_number:02d}"
    attempt_dir = suite_root / attempt_path
    attempt_dir.mkdir(parents=True, exist_ok=True)
    _clear_case_files(attempt_dir)

    candidates = generation.get("cases", [])
    if replacement_limit is not None:
        candidates = candidates[:replacement_limit]
    slot_ids = _feedback_slot_ids(regeneration_feedback)
    if not slot_ids:
        slot_ids = [f"case-{index:03d}" for index in range(1, len(candidates) + 1)]
    slot_ids = slot_ids[: len(candidates)]

    with tempfile.TemporaryDirectory(prefix="oxcidation-visible-c-") as temp_dir:
        compilation, c_binary = compile_c(c_code, temp_dir)
        compile_metadata = _compile_metadata(compilation)
        if compilation.returncode != 0:
            result = _empty_attempt(
                attempt_dir,
                attempt_path,
                generation.get("strategy", ""),
                len(candidates),
                compile_metadata,
            )
            result["prompt_sha256"] = prompt_sha256(generation_prompt)
            result.update(status="baseline_compile_failed", details=compilation.stderr)
            return result
        result = _validate_candidates(
            candidates,
            slot_ids,
            attempt_dir,
            attempt_path,
            c_binary,
            timeout_sec,
            generation.get("strategy", ""),
            compile_metadata,
            set(preserved_inputs or ()),
        )
        result["prompt_sha256"] = prompt_sha256(generation_prompt)

    _write_json(
        attempt_dir / "generation.json",
        {
            "strategy": generation.get("strategy", ""),
            "cases": generation.get("cases", []),
            "selected_replacements": len(candidates),
            "requested_replacements": replacement_limit,
            "prompt_sha256": prompt_sha256(generation_prompt),
            "regeneration_feedback": regeneration_feedback,
        },
    )
    return result


def _generate_attempt(
    context: PreparationContext,
    generate_candidates: Callable[[str], tuple[dict, dict]],
    c_binary: str,
    timeout_sec: float,
    compile_metadata: dict,
    *,
    feedback: str,
    slot_ids: list[str] | None = None,
    seen_inputs: set[str] | None = None,
) -> dict:
    context.generation_attempt_count += 1
    attempt_number = context.generation_attempt_count
    request = _generation_request_summary(feedback)
    context.record(
        "orchestrator",
        "test_generation_requested",
        {
            "kind": "replacement" if feedback else "initial",
            **request,
        },
    )
    generation, usage = generate_candidates(feedback)
    attempt_path = Path("attempts") / f"attempt-{attempt_number:02d}"
    attempt_dir = context.suite_root / attempt_path
    attempt_dir.mkdir(parents=True, exist_ok=True)
    _clear_case_files(attempt_dir)

    generated = generation.get("cases", [])
    selected = generated[: len(slot_ids)] if slot_ids is not None else generated
    assigned_slots = slot_ids or [
        f"case-{index:03d}" for index in range(1, len(selected) + 1)
    ]
    result = _validate_candidates(
        selected,
        assigned_slots,
        attempt_dir,
        attempt_path,
        c_binary,
        timeout_sec,
        generation.get("strategy", ""),
        compile_metadata,
        set(seen_inputs or ()),
    )
    _write_json(
        attempt_dir / "generation.json",
        {
            "strategy": generation.get("strategy", ""),
            "cases": generated,
            "assigned_slots": assigned_slots,
            "selected_count": len(selected),
            "feedback": feedback,
            "prompt_sha256": prompt_sha256(context.generation_prompt),
        },
    )
    _write_json(attempt_dir / "deterministic_validation.json", result)
    context.add_generation(generation, usage, result)
    context.record(
        "tester",
        "deterministic_validation",
        {
            "attempt_path": str(attempt_path),
            "strategy": result["strategy"],
            "candidate_count": result["candidate_count"],
            "accepted_count": result["case_count"],
            "rejected_count": len(result["rejected_cases"]),
            "evaluations": result["deterministic_evaluations"],
        },
    )
    return result


def _validate_candidates(
    candidates: list[dict],
    slot_ids: list[str],
    attempt_dir: Path,
    attempt_path: Path,
    c_binary: str,
    timeout_sec: float,
    strategy: str,
    compile_metadata: dict,
    seen_inputs: set[str],
) -> dict:
    result = _empty_attempt(
        attempt_dir,
        attempt_path,
        strategy,
        len(slot_ids),
        compile_metadata,
    )
    for slot_id, candidate in zip(slot_ids, candidates):
        _validate_candidate(
            result,
            attempt_dir,
            c_binary,
            slot_id,
            candidate,
            timeout_sec,
            seen_inputs,
        )
    for slot_id in slot_ids[len(candidates) :]:
        candidate_id = f"candidate-{len(result['deterministic_evaluations']) + 1:03d}"
        rejection = _rejected_case(
            slot_id,
            candidate_id,
            "",
            "",
            "MISSING_REPLACEMENT",
            "The generator did not return a candidate for this requested slot.",
        )
        result["rejected_cases"].append(rejection)
        result["deterministic_evaluations"].append(
            _deterministic_evaluation(slot_id, candidate_id, rejection["verdict"])
        )
    result["case_count"] = len(result["cases"])
    result["status"] = "ready" if result["cases"] else "no_valid_cases"
    result["details"] = (
        "" if result["cases"] else "The C oracle rejected every generated input."
    )
    return result


def _validate_candidate(
    result: dict,
    attempt_dir: Path,
    c_binary: str,
    case_id: str,
    candidate: dict,
    timeout_sec: float,
    seen_inputs: set[str],
) -> None:
    input_data = candidate.get("input", "")
    purpose = candidate.get("purpose", "").strip()
    candidate_id = f"candidate-{len(result['deterministic_evaluations']) + 1:03d}"
    if input_data in seen_inputs:
        rejection = _rejected_case(
            case_id,
            candidate_id,
            purpose,
            input_data,
            "DUPLICATE_INPUT",
            "Duplicate or previously rejected input.",
        )
        result["rejected_cases"].append(rejection)
        result["deterministic_evaluations"].append(
            _deterministic_evaluation(case_id, candidate_id, rejection["verdict"])
        )
        return
    seen_inputs.add(input_data)

    execution = run_program(c_binary, input_data, timeout_sec)
    rejection = _execution_rejection(
        case_id,
        candidate_id,
        purpose,
        input_data,
        execution,
    )
    if rejection:
        result["rejected_cases"].append(rejection)
        result["deterministic_evaluations"].append(
            _deterministic_evaluation(
                case_id,
                candidate_id,
                rejection["verdict"],
                execution,
            )
        )
        return

    input_file = f"{case_id}.in"
    output_file = f"{case_id}.out"
    (attempt_dir / input_file).write_text(input_data, encoding="utf-8")
    (attempt_dir / output_file).write_text(execution["stdout"], encoding="utf-8")
    result["cases"].append(
        {
            "id": case_id,
            "candidate_id": candidate_id,
            "purpose": purpose,
            "input": input_data,
            "output": execution["stdout"],
            "input_file": input_file,
            "output_file": output_file,
            "origin_attempt": str(result["attempt_path"]),
        }
    )
    result["deterministic_evaluations"].append(
        _deterministic_evaluation(
            case_id,
            candidate_id,
            "ACCEPTED",
            execution,
        )
    )


def _review_batch(
    context: PreparationContext,
    batch: dict[str, dict],
    review_candidates: Callable[[list[dict], dict], tuple[dict, dict]],
) -> dict:
    context.review_count += 1
    cases = [
        {"id": case_id, "purpose": case["purpose"], "input": case["input"]}
        for case_id, case in sorted(batch.items())
    ]
    deterministic_report = {
        "case_count": len(cases),
        "executions_per_case": 1,
        "status": "all_cases_accepted",
    }
    try:
        raw_review, usage = review_candidates(cases, deterministic_report)
        review = _normalize_batch_review(raw_review, set(batch))
    except Exception as error:
        details = f"Visible-test batch review failed: {error}"
        context.record("validator", "review_failed", {"details": details})
        return {"error": details}

    context.add_review(review, usage)
    review_path = Path("reviews") / f"review-{context.review_count:02d}.json"
    _write_json(context.suite_root / review_path, {"cases": cases, "review": review})
    context.record(
        "validator",
        "batch_review",
        {
            "assessment": review["assessment"],
            "replacement_count": len(review["replacements"]),
            "replacements": review["replacements"],
            "review_path": str(review_path),
        },
    )
    return review


def _normalize_batch_review(review: dict, known_case_ids: set[str]) -> dict:
    assessment = review.get("assessment")
    replacements = review.get("replacements")
    if assessment not in {"approved", "revise"}:
        raise ValueError(f"Unsupported batch assessment: {assessment}")
    if not isinstance(replacements, list):
        raise ValueError("Visible-test batch review must contain replacements.")
    if assessment == "approved" and replacements:
        raise ValueError("An approved batch cannot request replacements.")
    if assessment == "revise" and not replacements:
        raise ValueError("A batch revision must request at least one replacement.")

    normalized = []
    seen = set()
    for item in replacements:
        case_id = item.get("case_id")
        if case_id not in known_case_ids:
            raise ValueError(f"Batch review referenced unknown case: {case_id}")
        if case_id in seen:
            raise ValueError(f"Batch review repeated case: {case_id}")
        reason = str(item.get("reason", "")).strip()
        requirements = str(item.get("requirements", "")).strip()
        if not reason or not requirements:
            raise ValueError("Every replacement needs a reason and requirements.")
        seen.add(case_id)
        normalized.append(
            {
                "case_id": case_id,
                "reason": reason,
                "requirements": requirements,
            }
        )
    return {"assessment": assessment, "replacements": normalized}


def _replacement_request(
    slot_ids: list[str],
    batch: dict[str, dict],
    rejected_inputs: set[str],
    validator_requests: dict[str, dict] | None = None,
) -> str:
    validator_requests = validator_requests or {}
    slots = []
    for case_id in slot_ids:
        request = validator_requests.get(case_id, {})
        slots.append(
            {
                "case_id": case_id,
                "requirements": request.get(
                    "requirements",
                    "Generate a valid input distinct from all retained and rejected inputs.",
                ),
            }
        )
    return json.dumps(
        {
            "replacement_slots": slots,
            "retained_cases": [
                {
                    "case_id": case_id,
                    "purpose": case["purpose"],
                    "input": case["input"],
                }
                for case_id, case in sorted(batch.items())
            ],
            "forbidden_inputs": sorted(rejected_inputs),
        },
        ensure_ascii=False,
    )


def _discard_validator_replacements(
    batch: dict[str, dict],
    discarded: list[dict],
    requested: dict[str, dict],
) -> set[str]:
    rejected_inputs = set()
    for case_id, feedback in requested.items():
        case = batch.pop(case_id)
        rejected_inputs.add(case["input"])
        discarded.append(
            {
                "origin": "validator",
                "case_id": case_id,
                "purpose": case["purpose"],
                "input": case["input"],
                "reason": feedback["reason"],
                "requirements": feedback["requirements"],
            }
        )
    return rejected_inputs


def _freeze_batch(
    context: PreparationContext,
    batch: dict[str, dict],
    discarded: list[dict],
    target_case_count: int,
    strategy: str,
    compile_metadata: dict,
    unresolved_replacements: int,
) -> dict:
    frozen_path = Path("frozen")
    frozen_dir = context.suite_root / frozen_path
    frozen_dir.mkdir(parents=True, exist_ok=True)
    _clear_case_files(frozen_dir)

    cases = []
    for case_id, case in sorted(batch.items()):
        input_file = f"{case_id}.in"
        output_file = f"{case_id}.out"
        (frozen_dir / input_file).write_text(case["input"], encoding="utf-8")
        (frozen_dir / output_file).write_text(case["output"], encoding="utf-8")
        cases.append(
            {
                "id": case_id,
                "purpose": case["purpose"],
                "input_file": input_file,
                "output_file": output_file,
                "origin_attempt": case["origin_attempt"],
                "origin_candidate_id": case["candidate_id"],
            }
        )

    details = ""
    if unresolved_replacements:
        details = (
            f"Frozen {len(cases)} usable cases; {unresolved_replacements} requested "
            "replacements remained unresolved."
        )
    result = {
        "status": "ready",
        "suite_dir": str(frozen_dir),
        "attempt_path": str(frozen_path),
        "strategy": strategy,
        "candidate_count": target_case_count,
        "case_count": len(cases),
        "cases": cases,
        "rejected_cases": discarded,
        "details": details,
        **compile_metadata,
    }
    _write_json(
        frozen_dir / "suite_composition.json",
        {
            "target_case_count": target_case_count,
            "cases": cases,
            "discarded_cases": discarded,
            "unresolved_replacement_count": unresolved_replacements,
        },
    )
    return result


def _batch_result(
    batch: dict[str, dict],
    discarded: list[dict],
    target_case_count: int,
    strategy: str,
    compile_metadata: dict,
) -> dict:
    return {
        "status": "ready" if batch else "no_valid_cases",
        "attempt_path": "",
        "candidate_count": target_case_count,
        "case_count": len(batch),
        "strategy": strategy,
        "cases": list(batch.values()),
        "rejected_cases": discarded,
        "details": "",
        **compile_metadata,
    }


def _empty_batch(compile_metadata: dict, details: str) -> dict:
    return {
        "status": "baseline_compile_failed",
        "attempt_path": "",
        "candidate_count": 0,
        "case_count": 0,
        "strategy": "",
        "cases": [],
        "rejected_cases": [],
        "details": details,
        **compile_metadata,
    }


def _empty_attempt(
    attempt_dir: Path,
    attempt_path: Path,
    strategy: str,
    candidate_count: int,
    compile_metadata: dict,
) -> dict:
    return {
        "status": "no_valid_cases",
        "suite_dir": str(attempt_dir),
        "attempt_path": str(attempt_path),
        "strategy": strategy,
        "candidate_count": candidate_count,
        "case_count": 0,
        "cases": [],
        "rejected_cases": [],
        "deterministic_evaluations": [],
        "details": "The C oracle rejected every generated input.",
        **compile_metadata,
    }


def _generation_failure(
    context: PreparationContext,
    error: Exception,
    *,
    batch: dict | None = None,
) -> dict:
    details = f"Visible-test generation failed: {error}"
    context.record("tester", "generation_failed", {"details": details})
    return context.finalize(
        "generation_failed",
        "not_completed",
        batch=batch,
        details=details,
    )


def _compile_metadata(compilation) -> dict:
    return {
        "c_compile_profile": getattr(compilation, "compile_profile", "unknown"),
        "c_compile_attempts": getattr(compilation, "compile_attempts", []),
    }


def _accepted_cases(attempt: dict) -> dict[str, dict]:
    return {case["id"]: case for case in attempt["cases"]}


def _batch_inputs(batch: dict[str, dict]) -> set[str]:
    return {case["input"] for case in batch.values()}


def _rejected_case_ids(attempt: dict) -> list[str]:
    return [case["case_id"] for case in attempt["rejected_cases"]]


def _rejected_inputs(attempt: dict) -> set[str]:
    return {case["input"] for case in attempt["rejected_cases"]}


def _discarded_deterministic_cases(attempt: dict) -> list[dict]:
    return [
        {
            "origin": "deterministic_validation",
            "case_id": case["case_id"],
            "purpose": case["purpose"],
            "input": case["input"],
            "verdict": case["verdict"],
        }
        for case in attempt["rejected_cases"]
    ]


def _feedback_slot_ids(feedback: str) -> list[str]:
    if not feedback:
        return []
    try:
        payload = json.loads(feedback)
    except json.JSONDecodeError:
        return []
    return [item["case_id"] for item in payload.get("replacement_slots", [])]


def _generation_request_summary(feedback: str) -> dict:
    if not feedback:
        return {
            "requested_case_ids": [],
            "retained_case_ids": [],
            "forbidden_input_count": 0,
        }
    try:
        payload = json.loads(feedback)
    except json.JSONDecodeError:
        return {
            "requested_case_ids": [],
            "retained_case_ids": [],
            "forbidden_input_count": 0,
        }
    return {
        "requested_case_ids": [
            item["case_id"] for item in payload.get("replacement_slots", [])
        ],
        "retained_case_ids": [
            item["case_id"] for item in payload.get("retained_cases", [])
        ],
        "forbidden_input_count": len(payload.get("forbidden_inputs", [])),
    }


def _clear_case_files(directory: Path) -> None:
    for path in directory.glob("case-*.*"):
        path.unlink()


def _execution_rejection(
    case_id: str,
    candidate_id: str,
    purpose: str,
    input_data: str,
    execution: dict,
) -> dict | None:
    if execution["status"] != "ACCEPTED":
        return _rejected_case(
            case_id,
            candidate_id,
            purpose,
            input_data,
            execution["status"],
            execution.get("stderr", ""),
        )
    return None


def _rejected_case(
    case_id: str,
    candidate_id: str,
    purpose: str,
    input_data: str,
    verdict: str,
    details: str,
) -> dict:
    return {
        "case_id": case_id,
        "candidate_id": candidate_id,
        "purpose": purpose,
        "input": input_data,
        "verdict": verdict,
        "details": details[:1000],
    }


def _deterministic_evaluation(
    case_id: str,
    candidate_id: str,
    verdict: str,
    execution: dict | None = None,
) -> dict:
    execution = execution or {}
    stdout = execution.get("stdout", "")
    return {
        "case_id": case_id,
        "candidate_id": candidate_id,
        "verdict": verdict,
        "run_status": execution.get("status", "not_run"),
        "output_bytes": len(stdout.encode("utf-8")),
    }


def suite_sha256(suite_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(suite_dir.glob("case-*.*")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_suite_manifest(suite_root: Path, manifest: dict) -> dict:
    _write_json(suite_root / "suite.json", manifest)
    active_attempt = manifest.get("active_attempt", "")
    active_dir = suite_root / active_attempt if active_attempt else suite_root
    return {**manifest, "suite_dir": str(active_dir), "reused": False}


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
