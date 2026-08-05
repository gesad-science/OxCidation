"""Extract the complete accepted-C subset from a Project CodeNet archive."""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PROBLEM_ID_RE = re.compile(r"p\d{5}")
REQUIRED_METADATA_COLUMNS = {
    "submission_id",
    "problem_id",
    "language",
    "filename_ext",
    "status",
}
PROBLEM_MANIFEST_FIELDS = (
    "problem_id",
    "name",
    "dataset",
    "time_limit",
    "memory_limit",
    "rating",
    "tags",
    "complexity",
    "accepted_c_submissions",
    "description_available",
    "sample_io_available",
    "sample_io_verification",
)


@dataclass
class ArchiveScan:
    archive_root: PurePosixPath
    metadata_fields: list[str]
    problem_list_fields: list[str]
    problem_list_rows: list[dict]
    eligible_problems: set[str]
    expected_sources: set[PurePosixPath]
    accepted_submissions: int


@dataclass
class ExtractedSupport:
    sources: set[PurePosixPath]
    descriptions: set[str]
    sample_inputs: set[str]
    sample_outputs: set[str]
    unverified_sample_io: set[str]
    no_solution_sample_io: set[str]


def extract_accepted_c_subset(archive_path: Path, output_root: Path) -> dict:
    archive_path = archive_path.resolve()
    output_root = output_root.resolve()
    _validate_inputs(archive_path, output_root)
    output_root.parent.mkdir(parents=True, exist_ok=True)

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}.",
            dir=output_root.parent,
        )
    )
    work_root = staging / ".extraction-work"
    candidates_path = work_root / "accepted_c_candidates.csv"
    try:
        work_root.mkdir()
        print("Pass 1/2: reading metadata and identifying accepted C submissions...")
        raw_metadata_root = work_root / "raw-metadata"
        _extract_archive_metadata(archive_path, raw_metadata_root)
        scan = scan_metadata_directory(
            raw_metadata_root / "metadata",
            candidates_path,
        )
        print(
            f"Identified {scan.accepted_submissions} accepted C submissions "
            f"across {len(scan.eligible_problems)} problems."
        )

        print("Pass 2/2: extracting C sources and supporting files...")
        _extract_c_sources_and_support(
            archive_path,
            staging,
            scan,
        )
        support = inspect_and_prune_support(staging, scan)
        missing_sources = scan.expected_sources - support.sources
        if missing_sources:
            examples = ", ".join(str(path) for path in sorted(missing_sources)[:5])
            raise ValueError(
                f"{len(missing_sources)} accepted C sources listed in metadata "
                f"were missing from the archive. Examples: {examples}"
            )

        summary = finalize_subset(
            archive_path,
            staging,
            candidates_path,
            scan,
            support,
        )
        shutil.rmtree(work_root)
        os.replace(staging, output_root)
        return summary
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _validate_inputs(archive_path: Path, output_root: Path) -> None:
    if not archive_path.is_file():
        raise FileNotFoundError(f"CodeNet archive does not exist: {archive_path}")
    if output_root.exists():
        raise FileExistsError(
            f"Output path already exists: {output_root}. "
            "Choose a new path to avoid mixing datasets."
        )
    if archive_path == output_root or archive_path in output_root.parents:
        raise ValueError("Output path must not contain the source archive.")


def _extract_archive_metadata(
    archive_path: Path,
    destination: Path,
) -> None:
    destination.mkdir(parents=True)
    _run_tar(
        archive_path,
        destination,
        ["Project_CodeNet/metadata/*"],
        wildcard_members=True,
    )


def scan_metadata_directory(
    metadata_root: Path,
    candidates_path: Path,
) -> ArchiveScan:
    metadata_fields = None
    candidate_writer = None
    eligible_problems: set[str] = set()
    expected_sources: set[PurePosixPath] = set()
    problem_list_fields: list[str] = []
    problem_list_rows: list[dict] = []
    accepted_submissions = 0
    metadata_files = 0
    with candidates_path.open("w", newline="", encoding="utf-8") as candidates:
        for metadata_path in sorted(metadata_root.glob("*.csv")):
            with metadata_path.open(newline="", encoding="utf-8-sig") as metadata_file:
                reader = csv.DictReader(metadata_file)
                fields = reader.fieldnames or []
                rows = list(reader)

            if metadata_path.name == "problem_list.csv":
                problem_list_fields = fields
                problem_list_rows = rows
                continue
            if not re.fullmatch(r"p\d{5}\.csv", metadata_path.name):
                continue
            if not REQUIRED_METADATA_COLUMNS.issubset(fields):
                raise ValueError(
                    f"Metadata file {metadata_path} is missing required CodeNet columns."
                )
            if metadata_fields is None:
                metadata_fields = fields
                candidate_writer = csv.DictWriter(
                    candidates,
                    fieldnames=[*metadata_fields, "source_file"],
                )
                candidate_writer.writeheader()
            elif metadata_fields != fields:
                raise ValueError(
                    f"Metadata schema differs in {metadata_path}."
                )

            problem_id = metadata_path.stem
            for row in rows:
                if not _is_accepted_c(row):
                    continue
                if row["problem_id"].strip() != problem_id:
                    raise ValueError(
                        f"Metadata problem mismatch in {metadata_path}."
                    )
                source_file = PurePosixPath(
                    "data",
                    problem_id,
                    "C",
                    f"{row['submission_id'].strip()}.c",
                )
                candidate_writer.writerow(
                    {
                        **{
                            field: row.get(field, "").strip()
                            for field in metadata_fields
                        },
                        "source_file": str(source_file),
                    }
                )
                eligible_problems.add(problem_id)
                expected_sources.add(source_file)
                accepted_submissions += 1

            metadata_files += 1
            if metadata_files % 500 == 0:
                print(
                    f"  scanned {metadata_files} problem metadata files; "
                    f"{len(eligible_problems)} contain accepted C"
                )

    if metadata_fields is None:
        raise ValueError("Archive does not contain Project CodeNet problem metadata.")
    if not problem_list_fields or not problem_list_rows:
        raise ValueError("Archive does not contain metadata/problem_list.csv.")
    if not expected_sources:
        raise ValueError("Archive metadata contains no accepted C submissions.")

    return ArchiveScan(
        archive_root=PurePosixPath("Project_CodeNet"),
        metadata_fields=metadata_fields,
        problem_list_fields=problem_list_fields,
        problem_list_rows=problem_list_rows,
        eligible_problems=eligible_problems,
        expected_sources=expected_sources,
        accepted_submissions=accepted_submissions,
    )


def _is_accepted_c(row: dict) -> bool:
    return (
        row.get("language", "").strip().casefold() == "c"
        and row.get("status", "").strip().casefold() == "accepted"
        and row.get("filename_ext", "").strip().casefold() == "c"
        and bool(row.get("submission_id", "").strip())
    )


def _extract_c_sources_and_support(
    archive_path: Path,
    staging: Path,
    scan: ArchiveScan,
) -> None:
    _run_tar(
        archive_path,
        staging,
        [
            f"{scan.archive_root}/README.md",
            f"{scan.archive_root}/data/*/C/*.c",
            f"{scan.archive_root}/problem_descriptions/*",
            f"{scan.archive_root}/derived/input_output/*",
        ],
        wildcard_members=True,
        activity_message="  still scanning the archive and extracting C files...",
    )


def _run_tar(
    archive_path: Path,
    destination: Path,
    members: list[str],
    *,
    wildcard_members: bool = False,
    activity_message: str | None = None,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        "tar",
        "--extract",
        "--gzip",
        f"--file={archive_path}",
        f"--directory={destination}",
        "--strip-components=1",
        "--no-same-owner",
        "--no-same-permissions",
    ]
    if wildcard_members:
        command.append("--wildcards")
    command.extend(members)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    while True:
        try:
            timeout = 60 if activity_message else None
            stdout, stderr = process.communicate(timeout=timeout)
            break
        except subprocess.TimeoutExpired:
            print(activity_message, flush=True)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise

    if process.returncode != 0:
        details = stderr.strip() or stdout.strip()
        raise RuntimeError(f"Selective tar extraction failed: {details}")


def inspect_and_prune_support(
    staging: Path,
    scan: ArchiveScan,
) -> ExtractedSupport:
    support = ExtractedSupport(set(), set(), set(), set(), set(), set())
    support.sources = _prune_c_sources(staging, scan.expected_sources)

    descriptions_root = staging / "problem_descriptions"
    if descriptions_root.is_dir():
        for path in descriptions_root.glob("p*.html"):
            if path.stem in scan.eligible_problems:
                support.descriptions.add(path.stem)
            else:
                path.unlink()

    io_root = staging / "derived/input_output"
    support.unverified_sample_io = _read_problem_id_file(
        io_root / "unverified_accepted_solutions.txt"
    )
    support.no_solution_sample_io = _read_problem_id_file(
        io_root / "no_solutions.txt"
    )
    io_data_root = io_root / "data"
    if io_data_root.is_dir():
        for problem_dir in io_data_root.iterdir():
            if not problem_dir.is_dir():
                continue
            if problem_dir.name not in scan.eligible_problems:
                shutil.rmtree(problem_dir)
                continue
            if (problem_dir / "input.txt").is_file():
                support.sample_inputs.add(problem_dir.name)
            if (problem_dir / "output.txt").is_file():
                support.sample_outputs.add(problem_dir.name)
    return support


def _prune_c_sources(
    staging: Path,
    expected_sources: set[PurePosixPath],
) -> set[PurePosixPath]:
    data_root = staging / "data"
    retained: set[PurePosixPath] = set()
    removed = 0
    if not data_root.is_dir():
        return retained

    for problem_root in data_root.iterdir():
        c_root = problem_root / "C"
        if not c_root.is_dir():
            continue
        for source_path in c_root.glob("*.c"):
            relative_path = PurePosixPath(source_path.relative_to(staging).as_posix())
            if relative_path in expected_sources:
                retained.add(relative_path)
            else:
                source_path.unlink()
                removed += 1
        if not any(c_root.iterdir()):
            c_root.rmdir()
        if not any(problem_root.iterdir()):
            problem_root.rmdir()

    print(
        f"Retained {len(retained)} accepted C sources and removed "
        f"{removed} other C sources."
    )
    return retained


def _read_problem_id_file(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if PROBLEM_ID_RE.fullmatch(line.strip())
    }


def finalize_subset(
    archive_path: Path,
    staging: Path,
    candidates_path: Path,
    scan: ArchiveScan,
    support: ExtractedSupport,
) -> dict:
    manifests = staging / "manifests"
    metadata = staging / "metadata"
    manifests.mkdir(parents=True, exist_ok=True)
    metadata.mkdir(parents=True, exist_ok=True)

    accepted_counts = _write_verified_metadata(
        candidates_path,
        manifests / "accepted_c_submissions.csv",
        metadata,
        scan.metadata_fields,
        support.sources,
    )
    _write_filtered_problem_list(
        metadata / "problem_list.csv",
        scan,
        accepted_counts,
    )
    _write_problem_manifest(
        manifests / "problems.csv",
        scan,
        accepted_counts,
        support,
    )
    _write_filtered_problem_ids(
        staging / "derived/input_output/unverified_accepted_solutions.txt",
        support.unverified_sample_io & set(accepted_counts),
    )
    _write_filtered_problem_ids(
        staging / "derived/input_output/no_solutions.txt",
        support.no_solution_sample_io & set(accepted_counts),
    )

    io_available = support.sample_inputs & support.sample_outputs
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_archive": str(archive_path),
        "source_archive_size_bytes": archive_path.stat().st_size,
        "selection": {
            "language": "C",
            "status": "Accepted",
            "filename_extension": "c",
            "submission_policy": "all_matching_submissions",
        },
        "accepted_c_submissions": sum(accepted_counts.values()),
        "eligible_problems": len(accepted_counts),
        "support": {
            "problem_descriptions": len(support.descriptions & set(accepted_counts)),
            "sample_io_pairs": len(io_available & set(accepted_counts)),
            "sample_io_unverified": len(
                support.unverified_sample_io & set(accepted_counts)
            ),
            "problems_without_descriptions": len(
                set(accepted_counts) - support.descriptions
            ),
            "problems_without_sample_io_pairs": len(
                set(accepted_counts) - io_available
            ),
        },
        "notes": [
            "Sample I/O is extracted from problem descriptions and is not a hidden Judge suite.",
            "Per-problem metadata contains only verified accepted C submissions.",
            "Use manifests/accepted_c_submissions.csv for counting and later sampling.",
        ],
    }
    (staging / "extraction_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (staging / "SUBSET_README.md").write_text(
        _subset_readme(summary),
        encoding="utf-8",
    )
    return summary


def _write_verified_metadata(
    candidates_path: Path,
    manifest_path: Path,
    metadata_root: Path,
    metadata_fields: list[str],
    extracted_sources: set[PurePosixPath],
) -> Counter:
    counts = Counter()
    current_problem = None
    problem_file = None
    problem_writer = None

    with candidates_path.open(newline="", encoding="utf-8") as candidates:
        reader = csv.DictReader(candidates)
        manifest_fields = [*metadata_fields, "source_file"]
        with manifest_path.open("w", newline="", encoding="utf-8") as manifest:
            manifest_writer = csv.DictWriter(manifest, fieldnames=manifest_fields)
            manifest_writer.writeheader()
            try:
                for row in reader:
                    source_file = PurePosixPath(row["source_file"])
                    if source_file not in extracted_sources:
                        continue
                    problem_id = row["problem_id"]
                    if problem_id != current_problem:
                        if problem_file is not None:
                            problem_file.close()
                        current_problem = problem_id
                        problem_file = (metadata_root / f"{problem_id}.csv").open(
                            "w",
                            newline="",
                            encoding="utf-8",
                        )
                        problem_writer = csv.DictWriter(
                            problem_file,
                            fieldnames=metadata_fields,
                        )
                        problem_writer.writeheader()

                    manifest_writer.writerow(row)
                    problem_writer.writerow(
                        {field: row.get(field, "") for field in metadata_fields}
                    )
                    counts[problem_id] += 1
            finally:
                if problem_file is not None:
                    problem_file.close()
    return counts


def _write_filtered_problem_list(
    output_path: Path,
    scan: ArchiveScan,
    accepted_counts: Counter,
) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=scan.problem_list_fields)
        writer.writeheader()
        writer.writerows(
            row
            for row in scan.problem_list_rows
            if row.get("id", "").strip() in accepted_counts
        )


def _write_problem_manifest(
    output_path: Path,
    scan: ArchiveScan,
    accepted_counts: Counter,
    support: ExtractedSupport,
) -> None:
    problem_metadata = {
        row.get("id", "").strip(): row for row in scan.problem_list_rows
    }
    io_available = support.sample_inputs & support.sample_outputs

    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=PROBLEM_MANIFEST_FIELDS)
        writer.writeheader()
        for problem_id in sorted(accepted_counts):
            metadata = problem_metadata.get(problem_id, {})
            if problem_id not in io_available:
                verification = "missing"
            elif problem_id in support.unverified_sample_io:
                verification = "unverified"
            else:
                verification = "verified"
            writer.writerow(
                {
                    "problem_id": problem_id,
                    "name": metadata.get("name", ""),
                    "dataset": metadata.get("dataset", ""),
                    "time_limit": metadata.get("time_limit", ""),
                    "memory_limit": metadata.get("memory_limit", ""),
                    "rating": metadata.get("rating", ""),
                    "tags": metadata.get("tags", ""),
                    "complexity": metadata.get("complexity", ""),
                    "accepted_c_submissions": accepted_counts[problem_id],
                    "description_available": problem_id in support.descriptions,
                    "sample_io_available": problem_id in io_available,
                    "sample_io_verification": verification,
                }
            )


def _write_filtered_problem_ids(path: Path, problem_ids: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{problem_id}\n" for problem_id in sorted(problem_ids))
    replacement = path.with_name(f".{path.name}.tmp")
    replacement.write_text(text, encoding="utf-8")
    os.replace(replacement, path)


def _subset_readme(summary: dict) -> str:
    return f"""# Project CodeNet Accepted C Subset

This directory contains every C submission whose CodeNet metadata reports
`status=Accepted` and `filename_ext=c`.

- Accepted C submissions: {summary['accepted_c_submissions']}
- Eligible problems: {summary['eligible_problems']}
- Problems with extracted sample I/O: {summary['support']['sample_io_pairs']}

`manifests/accepted_c_submissions.csv` contains one row per extracted source.
`manifests/problems.csv` contains one row per eligible problem with source
counts and supporting-file availability. Per-problem metadata under `metadata/`
contains only the extracted accepted C submissions.

The files under `derived/input_output/` are samples extracted from problem
descriptions. They are useful visible inputs but are not hidden Judge suites.
See `extraction_summary.json` for the complete extraction record.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract all accepted C submissions and supporting Project CodeNet "
            "files without unpacking unrelated languages."
        )
    )
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = extract_accepted_c_subset(args.archive, args.output)
    print(
        f"Extracted {summary['accepted_c_submissions']} accepted C submissions "
        f"for {summary['eligible_problems']} problems into {args.output}"
    )


if __name__ == "__main__":
    main()
