"""Build an auditable one-accepted-C-submission-per-problem manifest."""

import argparse
import csv
import json
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


REQUIRED_COLUMNS = {
    "submission_id",
    "problem_id",
    "language",
    "filename_ext",
    "status",
}
PROBLEM_METADATA_RE = re.compile(r"p\d{5}\.csv$")
MANIFEST_COLUMNS = (
    "problem_id",
    "source_file",
    "submission_id",
    "language",
    "filename_ext",
    "status",
)


@dataclass(frozen=True)
class Submission:
    problem_id: str
    submission_id: str
    language: str
    filename_ext: str
    status: str


def read_problem_metadata(metadata_path: Path) -> list[Submission]:
    with metadata_path.open(newline="", encoding="utf-8") as metadata_file:
        reader = csv.DictReader(metadata_file)
        if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise ValueError(f"Metadata file {metadata_path} is missing required CodeNet columns.")
        return [
            Submission(
                problem_id=row["problem_id"].strip(),
                submission_id=row["submission_id"].strip(),
                language=row["language"].strip(),
                filename_ext=row["filename_ext"].strip(),
                status=row["status"].strip(),
            )
            for row in reader
        ]


def accepted_submissions(submissions: list[Submission], language: str) -> list[Submission]:
    return [
        submission
        for submission in submissions
        if submission.language == language and submission.status == "Accepted"
    ]


def source_path(data_root: Path, submission: Submission) -> Path:
    return (
        data_root
        / submission.problem_id
        / submission.language
        / f"{submission.submission_id}.{submission.filename_ext}"
    )


def choose_submission(
    candidates: list[Submission],
    problem_id: str,
    seed: int | None,
) -> Submission:
    ordered = sorted(candidates, key=lambda submission: submission.submission_id)
    if seed is None:
        return ordered[0]
    return random.Random(f"{seed}:{problem_id}").choice(ordered)


def build_population(
    data_root: Path,
    metadata_root: Path,
    require_rust_accepted: bool,
    seed: int | None,
) -> tuple[list[dict], dict]:
    rows = []
    skipped = Counter()

    metadata_paths = sorted(
        path for path in metadata_root.iterdir() if PROBLEM_METADATA_RE.fullmatch(path.name)
    )
    for metadata_path in metadata_paths:
        submissions = read_problem_metadata(metadata_path)
        problem_ids = {submission.problem_id for submission in submissions}
        if len(problem_ids) != 1 or metadata_path.stem not in problem_ids:
            skipped["invalid_problem_metadata"] += 1
            continue

        accepted_c = accepted_submissions(submissions, "C")
        if not accepted_c:
            skipped["no_accepted_c"] += 1
            continue
        if require_rust_accepted and not accepted_submissions(submissions, "Rust"):
            skipped["no_accepted_rust"] += 1
            continue

        selected = choose_submission(accepted_c, metadata_path.stem, seed)
        if selected.filename_ext != "c":
            skipped["accepted_c_extension_mismatch"] += 1
            continue
        selected_path = source_path(data_root, selected)
        if not selected_path.is_file():
            skipped["accepted_c_source_missing"] += 1
            continue

        rows.append(
            {
                "problem_id": selected.problem_id,
                "source_file": str(selected_path.relative_to(data_root)),
                "submission_id": selected.submission_id,
                "language": selected.language,
                "filename_ext": selected.filename_ext,
                "status": selected.status,
            }
        )

    rows.sort(key=lambda row: row["problem_id"])
    return rows, dict(sorted(skipped.items()))


def write_population(output_path: Path, rows: list[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(
    output_path: Path,
    data_root: Path,
    metadata_root: Path,
    require_rust_accepted: bool,
    seed: int | None,
    rows: list[dict],
    skipped: dict,
) -> Path:
    summary_path = output_path.with_suffix(".summary.json")
    summary = {
        "data_root": str(data_root),
        "metadata_root": str(metadata_root),
        "selection": "accepted_c_with_accepted_rust" if require_rust_accepted else "accepted_c",
        "candidate_selection": "seeded_random" if seed is not None else "lowest_submission_id",
        "seed": seed,
        "selected_problems": len(rows),
        "skipped": skipped,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create one verified accepted C submission per CodeNet problem."
    )
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--metadata-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--require-rust-accepted",
        action="store_true",
        help="Keep only the historical Gold Standard intersection with an accepted Rust submission.",
    )
    parser.add_argument(
        "--selection-seed",
        type=int,
        help="Select one accepted C submission uniformly per problem using this deterministic seed.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.data_root.is_dir():
        raise ValueError(f"Data root does not exist: {args.data_root}")
    if not args.metadata_root.is_dir():
        raise ValueError(f"Metadata root does not exist: {args.metadata_root}")

    rows, skipped = build_population(
        args.data_root,
        args.metadata_root,
        args.require_rust_accepted,
        args.selection_seed,
    )
    if not rows:
        raise ValueError("No verified accepted C submissions were found.")

    write_population(args.output, rows)
    summary_path = write_summary(
        args.output,
        args.data_root,
        args.metadata_root,
        args.require_rust_accepted,
        args.selection_seed,
        rows,
        skipped,
    )
    print(f"Wrote {len(rows)} verified C submissions to {args.output}")
    print(f"Wrote selection summary to {summary_path}")


if __name__ == "__main__":
    main()
