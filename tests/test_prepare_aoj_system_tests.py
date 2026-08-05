import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prepare_aoj_system_tests import (  # noqa: E402
    API_ROOT,
    AojSuiteDownloader,
    Problem,
    external_aoj_id,
    failed_problem_ids,
    load_problems,
    validate_completed_suite,
)


class AojSystemTestPreparationTests(unittest.TestCase):
    def test_maps_codenet_ids_to_four_digit_aoj_ids(self):
        self.assertEqual(external_aoj_id("p00001"), "0001")
        self.assertEqual(external_aoj_id("p02300"), "2300")

    def test_loads_unique_problems_and_requires_dataset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "problems.csv"
            with manifest.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=("problem_id", "dataset"))
                writer.writeheader()
                writer.writerows(
                    [
                        {"problem_id": "p00002", "dataset": "AIZU"},
                        {"problem_id": "p00001", "dataset": "AIZU"},
                        {"problem_id": "p00001", "dataset": "AIZU"},
                    ]
                )

            self.assertEqual(
                load_problems(manifest),
                [Problem("p00001", "AIZU"), Problem("p00002", "AIZU")],
            )

    def test_downloads_complete_suite_and_reuses_valid_cache(self):
        header = {
            "problemId": "0001",
            "headers": [
                {
                    "serial": 1,
                    "name": "testcase_00",
                    "inputSize": 2,
                    "outputSize": 2,
                }
            ],
        }
        responses = {
            f"{API_ROOT}/0001/header": json.dumps(header).encode(),
            f"{API_ROOT}/0001/1": json.dumps({"in": "1\n", "out": "2\n"}).encode(),
        }
        requests = []

        def get_bytes(url):
            requests.append(url)
            return responses[url]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "tests"
            problem = Problem("p00001", "AIZU")
            first = AojSuiteDownloader(output_root, get_bytes).download(problem)

            self.assertEqual(first["status"], "downloaded")
            self.assertEqual(first["case_count"], 1)
            self.assertEqual((output_root / "p00001" / "testcase_00.in").read_text(), "1\n")
            validate_completed_suite(output_root / "p00001", problem, "0001")

            second = AojSuiteDownloader(
                output_root,
                lambda _url: self.fail("A completed suite must not use the network."),
            ).download(problem)
            self.assertEqual(second["status"], "already_complete")
            self.assertEqual(len(requests), 2)

    def test_falls_back_when_combined_response_has_wrong_byte_size(self):
        header = {
            "problemId": "2300",
            "headers": [
                {
                    "serial": 7,
                    "name": "testcase_06",
                    "inputSize": 4,
                    "outputSize": 3,
                }
            ],
        }
        responses = {
            f"{API_ROOT}/2300/header": json.dumps(header).encode(),
            f"{API_ROOT}/2300/7": json.dumps({"in": "x", "out": "y"}).encode(),
            f"{API_ROOT}/2300/7/in": b"abc\n",
            f"{API_ROOT}/2300/7/out": b"ok\n",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "tests"
            result = AojSuiteDownloader(output_root, responses.__getitem__).download(
                Problem("p02300", "AIZU")
            )
            manifest = json.loads(
                (output_root / "p02300" / "suite_manifest.json").read_text(encoding="utf-8")
            )

            self.assertEqual(result["status"], "downloaded")
            self.assertEqual(result["fallback_cases"], 1)
            self.assertTrue(manifest["cases"][0]["separate_endpoint_fallback"])

    def test_resumes_case_files_from_partial_directory(self):
        header = {
            "problemId": "0002",
            "headers": [
                {"serial": 1, "name": "case_1", "inputSize": 2, "outputSize": 2},
                {"serial": 2, "name": "case_2", "inputSize": 2, "outputSize": 2},
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "tests"
            partial = output_root / ".partial" / "p00002"
            partial.mkdir(parents=True)
            (partial / "header.json").write_text(json.dumps(header), encoding="utf-8")
            (partial / "case_1.in").write_bytes(b"a\n")
            (partial / "case_1.out").write_bytes(b"b\n")
            requested = []

            def get_bytes(url):
                requested.append(url)
                return json.dumps({"in": "c\n", "out": "d\n"}).encode()

            result = AojSuiteDownloader(output_root, get_bytes).download(
                Problem("p00002", "AIZU")
            )

            self.assertEqual(result["case_count"], 2)
            self.assertEqual(requested, [f"{API_ROOT}/0002/2"])

    def test_classifies_zero_sized_header_as_unavailable_without_case_request(self):
        header = {
            "problemId": "0248",
            "headers": [
                {"serial": 1, "name": "judge_data", "inputSize": 0, "outputSize": 0}
            ],
        }
        requests = []

        def get_bytes(url):
            requests.append(url)
            return json.dumps(header).encode()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = AojSuiteDownloader(Path(temp_dir), get_bytes).download(
                Problem("p00248", "AIZU")
            )

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(requests, [f"{API_ROOT}/0248/header"])

    def test_accepts_and_records_extra_terminal_newline(self):
        header = {
            "problemId": "0072",
            "headers": [
                {"serial": 1, "name": "judge_data", "inputSize": 2, "outputSize": 2}
            ],
        }
        responses = {
            f"{API_ROOT}/0072/header": json.dumps(header).encode(),
            f"{API_ROOT}/0072/1": json.dumps({"in": "12\n", "out": "3\n"}).encode(),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            result = AojSuiteDownloader(output_root, responses.__getitem__).download(
                Problem("p00072", "AIZU")
            )
            manifest = json.loads(
                (output_root / "p00072" / "suite_manifest.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(manifest["cases"][0]["size_validation"], "extra_terminal_newline")
        self.assertEqual(manifest["cases"][0]["expected_input_size"], 2)
        self.assertEqual(manifest["cases"][0]["input_size"], 3)

    def test_selects_only_failed_rows_for_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "prefetch_results.csv"
            with report.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(
                    output,
                    fieldnames=(
                        "problem_id",
                        "dataset",
                        "external_problem_id",
                        "status",
                        "case_count",
                        "input_bytes",
                        "output_bytes",
                        "fallback_cases",
                        "details",
                    ),
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {"problem_id": "p00001", "status": "downloaded"},
                        {"problem_id": "p00002", "status": "failed"},
                        {"problem_id": "p00003", "status": "unavailable"},
                    ]
                )

            self.assertEqual(failed_problem_ids(report), {"p00002"})


if __name__ == "__main__":
    unittest.main()
