import csv
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace

from prepare_aoj_problem_mapping import (
    AojProblem,
    CodeNetProblem,
    DescriptionRecord,
    build_mapping_rows,
    load_accepted_population,
    load_or_fetch_description,
    run,
    write_mapped_source_manifest,
)


PROBLEM_FIELDS = (
    "problem_id",
    "name",
    "dataset",
    "accepted_c_submissions",
)


class AojProblemMappingTests(unittest.TestCase):
    def test_loads_only_accepted_c_aizu_problems_and_hashes_descriptions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            descriptions = root / "descriptions"
            descriptions.mkdir()
            (descriptions / "p00565.html").write_text("Sugoroku body", encoding="utf-8")
            manifest = root / "problems.csv"
            self._write_csv(
                manifest,
                PROBLEM_FIELDS,
                [
                    {
                        "problem_id": "p00565",
                        "name": "Sugoroku",
                        "dataset": "AIZU",
                        "accepted_c_submissions": "10",
                    },
                    {
                        "problem_id": "p03000",
                        "name": "AtCoder problem",
                        "dataset": "AtCoder",
                        "accepted_c_submissions": "2",
                    },
                ],
            )

            population = load_accepted_population(manifest, descriptions)

            self.assertEqual(population.total_problems, 2)
            self.assertEqual(population.non_aizu_problems, 1)
            self.assertEqual(len(population.aizu_problems), 1)
            self.assertTrue(population.aizu_problems[0].description_sha256)

    def test_maps_only_a_unique_exact_description_hash(self):
        problem = self._problem("p00565", "hash-a")
        rows = build_mapping_rows(
            (problem,),
            [AojProblem("0544", "Sugoroku"), AojProblem("0642", "Sugoroku")],
            [
                self._description("0544", "hash-b"),
                self._description("0642", "hash-a"),
            ],
        )

        self.assertEqual(rows[0]["status"], "matched")
        self.assertEqual(rows[0]["aoj_problem_id"], "0642")
        self.assertEqual(rows[0]["mapping_source"], "exact_description_sha256")

    def test_rejects_ambiguous_remote_hashes(self):
        rows = build_mapping_rows(
            (self._problem("p00001", "shared"),),
            [AojProblem("0001", "One"), AojProblem("9999", "Copy")],
            [
                self._description("0001", "shared"),
                self._description("9999", "shared"),
            ],
        )

        self.assertEqual(rows[0]["status"], "ambiguous_aoj_description_match")
        self.assertEqual(rows[0]["details"], "0001,9999")

    def test_two_languages_for_the_same_aoj_problem_are_not_ambiguous(self):
        descriptions = [
            self._description("1050", "shared"),
            DescriptionRecord(
                aoj_problem_id="1050",
                requested_language="ja",
                response_language="ja",
                status="available",
                html_sha256="shared",
                cached=False,
            ),
        ]

        rows = build_mapping_rows(
            (self._problem("p00636", "shared"),),
            [AojProblem("1050", "The Last Dungeon")],
            descriptions,
        )

        self.assertEqual(rows[0]["status"], "matched")
        self.assertEqual(rows[0]["aoj_problem_id"], "1050")
        self.assertEqual(rows[0]["aoj_description_language"], "en,ja")

    def test_records_missing_codenet_description_without_guessing(self):
        rows = build_mapping_rows(
            (self._problem("p02479", ""),),
            [AojProblem("0001", "One")],
            [self._description("0001", "hash")],
        )

        self.assertEqual(rows[0]["status"], "missing_codenet_description")
        self.assertEqual(rows[0]["aoj_problem_id"], "")

    def test_description_cache_avoids_a_second_request(self):
        payload = {"language": "ja", "html": "same body"}
        requests = []

        def get_bytes(url):
            requests.append(url)
            return json.dumps(payload).encode()

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir)
            first = load_or_fetch_description(cache, "1050", "en", get_bytes)
            second = load_or_fetch_description(
                cache,
                "1050",
                "en",
                lambda _url: self.fail("Cached descriptions must not use the network."),
            )

        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(first.html_sha256, second.html_sha256)
        self.assertEqual(len(requests), 1)

    def test_caches_a_missing_language_as_unavailable(self):
        def unavailable(url):
            raise urllib.error.HTTPError(url, 404, "missing", {}, None)

        with tempfile.TemporaryDirectory() as temp_dir:
            record = load_or_fetch_description(Path(temp_dir), "1050", "en", unavailable)

        self.assertEqual(record.status, "unavailable")
        self.assertEqual(record.html_sha256, "")

    def test_filters_source_manifest_and_adds_mapping_provenance(self):
        mapping_rows = [
            {
                "problem_id": "p00565",
                "status": "matched",
                "aoj_problem_id": "0642",
                "aoj_name": "Sugoroku",
                "codenet_description_sha256": "hash",
                "mapping_source": "exact_description_sha256",
            },
            {"problem_id": "p00600", "status": "no_exact_description_match"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "population.csv"
            output = root / "mapped.csv"
            self._write_csv(
                source,
                ("problem_id", "source_file"),
                [
                    {"problem_id": "p00565", "source_file": "p00565/C/a.c"},
                    {"problem_id": "p00600", "source_file": "p00600/C/b.c"},
                ],
            )

            counts = write_mapped_source_manifest(source, output, mapping_rows)
            with output.open(newline="", encoding="utf-8") as output_file:
                rows = list(csv.DictReader(output_file))

        self.assertEqual(counts, (2, 1))
        self.assertEqual(rows[0]["problem_id"], "p00565")
        self.assertEqual(rows[0]["aoj_problem_id"], "0642")

    def test_cached_end_to_end_run_writes_judge_and_benchmark_manifests(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            descriptions = root / "descriptions"
            descriptions.mkdir()
            html = "Sugoroku body"
            (descriptions / "p00565.html").write_text(html, encoding="utf-8")
            problem_manifest = root / "problems.csv"
            self._write_csv(
                problem_manifest,
                PROBLEM_FIELDS,
                [
                    {
                        "problem_id": "p00565",
                        "name": "Sugoroku",
                        "dataset": "AIZU",
                        "accepted_c_submissions": "10",
                    }
                ],
            )
            source_manifest = root / "population.csv"
            self._write_csv(
                source_manifest,
                ("problem_id", "source_file"),
                [{"problem_id": "p00565", "source_file": "p00565/C/a.c"}],
            )
            output_root = root / "mapping"
            cache = output_root / "cache"
            cache.mkdir(parents=True)
            (cache / "problems.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "problems": [{"id": "0642", "name": "Sugoroku"}],
                    }
                ),
                encoding="utf-8",
            )
            cached_description = cache / "descriptions" / "en" / "0642.json"
            cached_description.parent.mkdir(parents=True)
            cached_description.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "aoj_problem_id": "0642",
                        "requested_language": "en",
                        "response_language": "ja",
                        "status": "available",
                        "html": html,
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                problem_manifest=problem_manifest,
                descriptions_root=descriptions,
                source_manifest=source_manifest,
                output_root=output_root,
                workers=1,
                requests_per_second=1.0,
                timeout_sec=1.0,
                retries=0,
                refresh_catalog=False,
            )

            exit_code = run(args)
            with (output_root / "mapped_problems.csv").open(
                newline="", encoding="utf-8"
            ) as mapped_file:
                mapped_problems = list(csv.DictReader(mapped_file))
            with (output_root / "benchmark_population.csv").open(
                newline="", encoding="utf-8"
            ) as benchmark_file:
                benchmark_rows = list(csv.DictReader(benchmark_file))

        self.assertEqual(exit_code, 0)
        self.assertEqual(mapped_problems[0]["aoj_problem_id"], "0642")
        self.assertEqual(benchmark_rows[0]["aoj_problem_id"], "0642")

    @staticmethod
    def _problem(problem_id, description_hash):
        return CodeNetProblem(
            problem_id=problem_id,
            name="Problem",
            dataset="AIZU",
            description_sha256=description_hash,
            manifest_row={
                "problem_id": problem_id,
                "name": "Problem",
                "dataset": "AIZU",
                "accepted_c_submissions": "1",
            },
        )

    @staticmethod
    def _description(problem_id, description_hash):
        return DescriptionRecord(
            aoj_problem_id=problem_id,
            requested_language="en",
            response_language="en",
            status="available",
            html_sha256=description_hash,
            cached=False,
        )

    @staticmethod
    def _write_csv(path, fieldnames, rows):
        with path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
