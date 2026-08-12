"""Map accepted-C CodeNet problems to AOJ IDs by exact description content."""

from __future__ import annotations

import argparse
import csv
import json
import re
import threading
import urllib.error
from collections import Counter, defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from aoj_api import AojHttpClient, atomic_write_json, sha256


AOJ_API_ROOT = "https://judgeapi.u-aizu.ac.jp"
CATALOG_PAGE_SIZE = 1000
SCHEMA_VERSION = 1
AOJ_ID_RE = re.compile(r"[A-Za-z0-9_]+")
REQUIRED_PROBLEM_FIELDS = {"problem_id", "dataset", "accepted_c_submissions"}
MAPPING_FIELDS = (
    "problem_id",
    "name",
    "dataset",
    "status",
    "aoj_problem_id",
    "aoj_name",
    "codenet_description_sha256",
    "aoj_description_sha256",
    "aoj_description_language",
    "mapping_source",
    "details",
)
MAPPING_METADATA_FIELDS = (
    "aoj_problem_id",
    "aoj_name",
    "description_sha256",
    "mapping_source",
)


@dataclass(frozen=True)
class CodeNetProblem:
    problem_id: str
    name: str
    dataset: str
    description_sha256: str
    manifest_row: dict[str, str]


@dataclass(frozen=True)
class AcceptedPopulation:
    fieldnames: tuple[str, ...]
    total_problems: int
    non_aizu_problems: int
    aizu_problems: tuple[CodeNetProblem, ...]


@dataclass(frozen=True)
class AojProblem:
    problem_id: str
    name: str


@dataclass(frozen=True)
class DescriptionRecord:
    aoj_problem_id: str
    requested_language: str
    response_language: str
    status: str
    html_sha256: str
    cached: bool


def load_accepted_population(
    manifest_path: Path,
    descriptions_root: Path,
) -> AcceptedPopulation:
    with manifest_path.open(newline="", encoding="utf-8-sig") as manifest_file:
        reader = csv.DictReader(manifest_file)
        fieldnames = tuple(reader.fieldnames or ())
        if not REQUIRED_PROBLEM_FIELDS.issubset(fieldnames):
            raise ValueError(
                "Accepted-C problem manifest must contain "
                f"{sorted(REQUIRED_PROBLEM_FIELDS)}."
            )
        rows = list(reader)

    seen_ids = set()
    aizu_problems = []
    non_aizu_problems = 0
    for row in rows:
        problem_id = row["problem_id"].strip()
        if not problem_id or problem_id in seen_ids:
            raise ValueError(
                f"Invalid or duplicate problem ID in accepted-C manifest: {problem_id}"
            )
        seen_ids.add(problem_id)
        try:
            accepted_count = int(row["accepted_c_submissions"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid accepted-C count for {problem_id}.") from error
        if accepted_count < 1:
            raise ValueError(f"Problem {problem_id} has no accepted C submissions.")

        dataset = row["dataset"].strip()
        if dataset.casefold() != "aizu":
            non_aizu_problems += 1
            continue
        description_path = descriptions_root / f"{problem_id}.html"
        description_hash = (
            sha256(description_path.read_bytes()) if description_path.is_file() else ""
        )
        aizu_problems.append(
            CodeNetProblem(
                problem_id=problem_id,
                name=row.get("name", "").strip(),
                dataset=dataset,
                description_sha256=description_hash,
                manifest_row={field: row.get(field, "") for field in fieldnames},
            )
        )

    if not aizu_problems:
        raise ValueError("Accepted-C manifest contains no AIZU problems.")
    return AcceptedPopulation(
        fieldnames=fieldnames,
        total_problems=len(rows),
        non_aizu_problems=non_aizu_problems,
        aizu_problems=tuple(sorted(aizu_problems, key=lambda problem: problem.problem_id)),
    )


def catalog_page_url(page: int) -> str:
    return f"{AOJ_API_ROOT}/problems?page={page}&size={CATALOG_PAGE_SIZE}"


def load_or_fetch_catalog(
    cache_path: Path,
    get_bytes: Callable[[str], bytes],
    refresh: bool = False,
) -> tuple[list[AojProblem], bool]:
    if cache_path.is_file() and not refresh:
        return parse_catalog_cache(cache_path), True

    raw_problems = []
    page = 0
    while True:
        payload = json.loads(get_bytes(catalog_page_url(page)))
        if not isinstance(payload, list):
            raise ValueError("AOJ problem catalog response is not a list.")
        raw_problems.extend(payload)
        if len(payload) < CATALOG_PAGE_SIZE:
            break
        page += 1

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "source": f"{AOJ_API_ROOT}/problems",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "problems": raw_problems,
    }
    atomic_write_json(cache_path, envelope)
    return parse_catalog_payload(raw_problems), False


def parse_catalog_cache(cache_path: Path) -> list[AojProblem]:
    envelope = json.loads(cache_path.read_text(encoding="utf-8"))
    if envelope.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported AOJ catalog cache schema: {cache_path}")
    return parse_catalog_payload(envelope.get("problems"))


def parse_catalog_payload(payload: object) -> list[AojProblem]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("AOJ problem catalog is empty or invalid.")
    problems = []
    seen_ids = set()
    for raw_problem in payload:
        if not isinstance(raw_problem, dict):
            raise ValueError("AOJ problem catalog contains an invalid row.")
        problem_id = str(raw_problem.get("id", "")).strip()
        if not AOJ_ID_RE.fullmatch(problem_id) or problem_id in seen_ids:
            raise ValueError(f"Invalid or duplicate AOJ problem ID: {problem_id}")
        seen_ids.add(problem_id)
        problems.append(AojProblem(problem_id, str(raw_problem.get("name", "")).strip()))
    return sorted(problems, key=lambda problem: problem.problem_id)


def description_url(aoj_problem_id: str, language: str) -> str:
    return f"{AOJ_API_ROOT}/resources/descriptions/{language}/{aoj_problem_id}"


def description_cache_path(cache_root: Path, aoj_problem_id: str, language: str) -> Path:
    if not AOJ_ID_RE.fullmatch(aoj_problem_id):
        raise ValueError(f"Invalid AOJ problem ID: {aoj_problem_id}")
    return cache_root / language / f"{aoj_problem_id}.json"


def load_or_fetch_description(
    cache_root: Path,
    aoj_problem_id: str,
    language: str,
    get_bytes: Callable[[str], bytes],
) -> DescriptionRecord:
    cache_path = description_cache_path(cache_root, aoj_problem_id, language)
    if cache_path.is_file():
        return parse_description_cache(cache_path, cached=True)

    try:
        payload = json.loads(get_bytes(description_url(aoj_problem_id, language)))
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "aoj_problem_id": aoj_problem_id,
            "requested_language": language,
            "response_language": "",
            "status": "unavailable",
            "html": "",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        if not isinstance(payload, dict) or not isinstance(payload.get("html"), str):
            raise ValueError(f"Invalid AOJ description response for {aoj_problem_id}/{language}.")
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "aoj_problem_id": aoj_problem_id,
            "requested_language": language,
            "response_language": str(payload.get("language", "")).strip(),
            "status": "available",
            "html": payload["html"],
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
    atomic_write_json(cache_path, envelope)
    return parse_description_payload(envelope, cached=False)


def parse_description_cache(cache_path: Path, cached: bool) -> DescriptionRecord:
    envelope = json.loads(cache_path.read_text(encoding="utf-8"))
    if envelope.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported AOJ description cache schema: {cache_path}")
    return parse_description_payload(envelope, cached)


def parse_description_payload(payload: dict, cached: bool) -> DescriptionRecord:
    aoj_problem_id = str(payload.get("aoj_problem_id", "")).strip()
    requested_language = str(payload.get("requested_language", "")).strip()
    status = str(payload.get("status", "")).strip()
    html = payload.get("html")
    if (
        not AOJ_ID_RE.fullmatch(aoj_problem_id)
        or requested_language not in {"en", "ja"}
        or status not in {"available", "unavailable"}
        or not isinstance(html, str)
    ):
        raise ValueError(f"Invalid AOJ description cache for {aoj_problem_id}.")
    return DescriptionRecord(
        aoj_problem_id=aoj_problem_id,
        requested_language=requested_language,
        response_language=str(payload.get("response_language", "")).strip(),
        status=status,
        html_sha256=sha256(html.encode("utf-8")) if status == "available" else "",
        cached=cached,
    )


def prepare_descriptions(
    aoj_problems: list[AojProblem],
    cache_root: Path,
    get_bytes: Callable[[str], bytes],
    workers: int,
    stop_event: threading.Event,
) -> list[DescriptionRecord]:
    english = fetch_description_batch(
        [(problem.problem_id, "en") for problem in aoj_problems],
        cache_root,
        get_bytes,
        workers,
        stop_event,
        "en",
    )
    english_by_id = {record.aoj_problem_id: record for record in english}
    japanese_tasks = [
        (problem.problem_id, "ja")
        for problem in aoj_problems
        if english_by_id[problem.problem_id].response_language != "ja"
    ]
    japanese = fetch_description_batch(
        japanese_tasks,
        cache_root,
        get_bytes,
        workers,
        stop_event,
        "ja",
    )
    return english + japanese


def fetch_description_batch(
    tasks: list[tuple[str, str]],
    cache_root: Path,
    get_bytes: Callable[[str], bytes],
    workers: int,
    stop_event: threading.Event,
    label: str,
) -> list[DescriptionRecord]:
    if not tasks:
        return []
    records = []
    executor = ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix=f"aoj-description-{label}",
    )
    futures: dict[Future, tuple[str, str]] = {
        executor.submit(load_or_fetch_description, cache_root, problem_id, language, get_bytes): (
            problem_id,
            language,
        )
        for problem_id, language in tasks
    }
    try:
        for completed, future in enumerate(as_completed(futures), start=1):
            records.append(future.result())
            if completed % 100 == 0 or completed == len(tasks):
                print(f"[{label}] {completed}/{len(tasks)} AOJ descriptions prepared", flush=True)
    except (KeyboardInterrupt, InterruptedError) as error:
        stop_event.set()
        for future in futures:
            future.cancel()
        raise InterruptedError("AOJ description preparation interrupted.") from error
    except BaseException:
        stop_event.set()
        for future in futures:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    return sorted(
        records,
        key=lambda record: (record.aoj_problem_id, record.requested_language),
    )


def build_mapping_rows(
    problems: tuple[CodeNetProblem, ...],
    aoj_problems: list[AojProblem],
    descriptions: list[DescriptionRecord],
) -> list[dict]:
    aoj_names = {problem.problem_id: problem.name for problem in aoj_problems}
    local_hash_ids: dict[str, list[str]] = defaultdict(list)
    for problem in problems:
        if problem.description_sha256:
            local_hash_ids[problem.description_sha256].append(problem.problem_id)

    remote_hash_records: dict[str, list[DescriptionRecord]] = defaultdict(list)
    for record in descriptions:
        if record.status == "available":
            remote_hash_records[record.html_sha256].append(record)

    rows = []
    for problem in problems:
        common = {
            "problem_id": problem.problem_id,
            "name": problem.name,
            "dataset": problem.dataset,
            "aoj_problem_id": "",
            "aoj_name": "",
            "codenet_description_sha256": problem.description_sha256,
            "aoj_description_sha256": "",
            "aoj_description_language": "",
            "mapping_source": "",
            "details": "",
        }
        if not problem.description_sha256:
            rows.append({**common, "status": "missing_codenet_description"})
            continue
        if len(local_hash_ids[problem.description_sha256]) > 1:
            rows.append(
                {
                    **common,
                    "status": "ambiguous_codenet_description",
                    "details": ",".join(local_hash_ids[problem.description_sha256]),
                }
            )
            continue

        matching_records = remote_hash_records.get(problem.description_sha256, [])
        matching_ids = sorted({record.aoj_problem_id for record in matching_records})
        if not matching_ids:
            rows.append({**common, "status": "no_exact_description_match"})
            continue
        if len(matching_ids) > 1:
            rows.append(
                {
                    **common,
                    "status": "ambiguous_aoj_description_match",
                    "details": ",".join(matching_ids),
                }
            )
            continue

        aoj_problem_id = matching_ids[0]
        languages = sorted(
            {
                record.response_language or record.requested_language
                for record in matching_records
                if record.aoj_problem_id == aoj_problem_id
            }
        )
        rows.append(
            {
                **common,
                "status": "matched",
                "aoj_problem_id": aoj_problem_id,
                "aoj_name": aoj_names.get(aoj_problem_id, ""),
                "aoj_description_sha256": problem.description_sha256,
                "aoj_description_language": ",".join(languages),
                "mapping_source": "exact_description_sha256",
            }
        )
    return rows


def write_csv(path: Path, fieldnames: tuple[str, ...] | list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_mapped_problem_manifest(
    output_path: Path,
    population: AcceptedPopulation,
    mapping_rows: list[dict],
) -> list[dict]:
    mapping_by_id = {
        row["problem_id"]: row for row in mapping_rows if row["status"] == "matched"
    }
    fieldnames = [
        *[field for field in population.fieldnames if field not in MAPPING_METADATA_FIELDS],
        *MAPPING_METADATA_FIELDS,
    ]
    rows = []
    for problem in population.aizu_problems:
        mapping = mapping_by_id.get(problem.problem_id)
        if mapping is None:
            continue
        rows.append(
            {
                **{
                    field: problem.manifest_row.get(field, "")
                    for field in fieldnames
                    if field not in MAPPING_METADATA_FIELDS
                },
                "aoj_problem_id": mapping["aoj_problem_id"],
                "aoj_name": mapping["aoj_name"],
                "description_sha256": mapping["codenet_description_sha256"],
                "mapping_source": mapping["mapping_source"],
            }
        )
    write_csv(output_path, fieldnames, rows)
    return rows


def write_mapped_source_manifest(
    source_manifest: Path,
    output_path: Path,
    mapping_rows: list[dict],
) -> tuple[int, int]:
    with source_manifest.open(newline="", encoding="utf-8-sig") as source_file:
        reader = csv.DictReader(source_file)
        fieldnames = list(reader.fieldnames or [])
        required = {"problem_id", "source_file"}
        if not required.issubset(fieldnames):
            raise ValueError(f"Source manifest must contain {sorted(required)}.")
        source_rows = list(reader)

    problem_ids = [row["problem_id"].strip() for row in source_rows]
    if len(problem_ids) != len(set(problem_ids)):
        raise ValueError("Source manifest must contain at most one program per problem.")
    mapping_by_id = {
        row["problem_id"]: row for row in mapping_rows if row["status"] == "matched"
    }
    output_fields = [
        *[field for field in fieldnames if field not in MAPPING_METADATA_FIELDS],
        *MAPPING_METADATA_FIELDS,
    ]
    mapped_rows = []
    for row in source_rows:
        mapping = mapping_by_id.get(row["problem_id"].strip())
        if mapping is None:
            continue
        mapped_rows.append(
            {
                **{
                    field: row.get(field, "")
                    for field in output_fields
                    if field not in MAPPING_METADATA_FIELDS
                },
                "aoj_problem_id": mapping["aoj_problem_id"],
                "aoj_name": mapping["aoj_name"],
                "description_sha256": mapping["codenet_description_sha256"],
                "mapping_source": mapping["mapping_source"],
            }
        )
    if not mapped_rows:
        raise ValueError("Source manifest contains no exactly mapped AOJ problems.")
    write_csv(output_path, output_fields, mapped_rows)
    return len(source_rows), len(mapped_rows)


def run(args: argparse.Namespace) -> int:
    if not args.problem_manifest.is_file():
        raise FileNotFoundError(f"Problem manifest does not exist: {args.problem_manifest}")
    if not args.descriptions_root.is_dir():
        raise FileNotFoundError(f"Descriptions root does not exist: {args.descriptions_root}")
    if args.source_manifest and not args.source_manifest.is_file():
        raise FileNotFoundError(f"Source manifest does not exist: {args.source_manifest}")

    population = load_accepted_population(args.problem_manifest, args.descriptions_root)
    args.output_root.mkdir(parents=True, exist_ok=True)
    cache_root = args.output_root / "cache"
    stop_event = threading.Event()
    client = AojHttpClient(
        args.requests_per_second,
        args.timeout_sec,
        args.retries,
        stop_event,
        user_agent="OxCidation-AOJ-problem-mapping/1",
    )
    try:
        aoj_problems, catalog_cached = load_or_fetch_catalog(
            cache_root / "problems.json",
            client.get,
            args.refresh_catalog,
        )
        descriptions = prepare_descriptions(
            aoj_problems,
            cache_root / "descriptions",
            client.get,
            args.workers,
            stop_event,
        )
    except InterruptedError:
        print("Mapping interrupted. Cached descriptions will be reused on restart.", flush=True)
        return 130

    mapping_rows = build_mapping_rows(population.aizu_problems, aoj_problems, descriptions)
    write_csv(args.output_root / "mapping_results.csv", MAPPING_FIELDS, mapping_rows)
    mapped_problem_rows = write_mapped_problem_manifest(
        args.output_root / "mapped_problems.csv",
        population,
        mapping_rows,
    )

    source_counts = None
    if args.source_manifest:
        source_counts = write_mapped_source_manifest(
            args.source_manifest,
            args.output_root / "benchmark_population.csv",
            mapping_rows,
        )

    status_counts = Counter(row["status"] for row in mapping_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mapping_method": "exact_description_sha256",
        "problem_manifest": str(args.problem_manifest),
        "problem_manifest_sha256": sha256(args.problem_manifest.read_bytes()),
        "accepted_c_problems": population.total_problems,
        "aizu_problems": len(population.aizu_problems),
        "non_aizu_problems_excluded": population.non_aizu_problems,
        "codenet_descriptions_available": sum(
            bool(problem.description_sha256) for problem in population.aizu_problems
        ),
        "aoj_catalog_problems": len(aoj_problems),
        "aoj_description_records": len(descriptions),
        "aoj_description_cache_hits": sum(record.cached for record in descriptions),
        "catalog_cache_hit": catalog_cached,
        "mapping_status_counts": dict(sorted(status_counts.items())),
        "mapped_problems": len(mapped_problem_rows),
    }
    if args.source_manifest and source_counts:
        summary["source_manifest"] = {
            "path": str(args.source_manifest),
            "sha256": sha256(args.source_manifest.read_bytes()),
            "input_programs": source_counts[0],
            "mapped_programs": source_counts[1],
            "output": str(args.output_root / "benchmark_population.csv"),
        }
    atomic_write_json(args.output_root / "mapping_summary.json", summary)

    print(f"Mapped problems: {len(mapped_problem_rows)}")
    print(f"Mapping report: {args.output_root / 'mapping_results.csv'}")
    print(f"Judge manifest: {args.output_root / 'mapped_problems.csv'}")
    if args.source_manifest:
        print(f"Benchmark population: {args.output_root / 'benchmark_population.csv'}")
    print(f"Summary: {args.output_root / 'mapping_summary.json'}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Map accepted-C CodeNet AIZU problems to AOJ IDs using only exact "
            "problem-description hashes."
        )
    )
    parser.add_argument(
        "--problem-manifest",
        required=True,
        type=Path,
        help="Accepted-C subset's manifests/problems.csv.",
    )
    parser.add_argument(
        "--descriptions-root",
        required=True,
        type=Path,
        help="Accepted-C subset's problem_descriptions directory.",
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        help="Optional one-program-per-problem manifest to filter for benchmark use.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/processed/aoj_problem_mapping"),
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--requests-per-second", type=float, default=8.0)
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument(
        "--refresh-catalog",
        action="store_true",
        help="Refresh the cached AOJ problem catalog; description caches remain reusable.",
    )
    args = parser.parse_args()
    if (
        args.workers < 1
        or args.requests_per_second <= 0
        or args.timeout_sec <= 0
        or args.retries < 0
    ):
        parser.error(
            "workers, request rate, and timeout must be positive; "
            "retries cannot be negative."
        )
    return args


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
