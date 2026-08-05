import csv
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extract_accepted_codenet import extract_accepted_c_subset


METADATA_HEADER = (
    "submission_id,problem_id,user_id,date,language,original_language,"
    "filename_ext,status,cpu_time,memory,code_size,accuracy\n"
)


class AcceptedCExtractionTests(unittest.TestCase):
    def test_extracts_only_verified_accepted_c_with_supporting_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "Project_CodeNet.tar.gz"
            output = root / "accepted-c"
            self._build_archive(archive)

            summary = extract_accepted_c_subset(archive, output)

            self.assertEqual(summary["accepted_c_submissions"], 1)
            self.assertEqual(summary["eligible_problems"], 1)
            self.assertTrue(
                (output / "data/p00001/C/s000000001.c").is_file()
            )
            self.assertFalse(
                (output / "data/p00001/C/s000000002.c").exists()
            )
            self.assertFalse(
                (output / "data/p00001/Rust/s000000003.rs").exists()
            )
            metadata_rows = self._read_csv(output / "metadata/p00001.csv")
            self.assertEqual(len(metadata_rows), 1)
            self.assertEqual(metadata_rows[0]["status"], "Accepted")
            self.assertEqual(metadata_rows[0]["language"], "C")
            manifest_rows = self._read_csv(
                output / "manifests/accepted_c_submissions.csv"
            )
            self.assertEqual(
                manifest_rows[0]["source_file"],
                "data/p00001/C/s000000001.c",
            )
            problem_rows = self._read_csv(output / "manifests/problems.csv")
            self.assertEqual(problem_rows[0]["sample_io_verification"], "unverified")
            self.assertTrue(
                (output / "problem_descriptions/p00001.html").is_file()
            )
            self.assertTrue(
                (output / "derived/input_output/data/p00001/input.txt").is_file()
            )
            self.assertEqual(
                json.loads(
                    (output / "extraction_summary.json").read_text(
                        encoding="utf-8"
                    )
                )["accepted_c_submissions"],
                1,
            )

    def test_refuses_to_mix_with_an_existing_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "Project_CodeNet.tar.gz"
            output = root / "accepted-c"
            self._build_archive(archive)
            output.mkdir()

            with self.assertRaises(FileExistsError):
                extract_accepted_c_subset(archive, output)

    def test_removes_staging_directory_when_interrupted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "Project_CodeNet.tar.gz"
            output = root / "accepted-c"
            archive.touch()

            with patch(
                "extract_accepted_codenet._extract_archive_metadata",
                side_effect=KeyboardInterrupt,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    extract_accepted_c_subset(archive, output)

            self.assertEqual(list(root.glob(".accepted-c.*")), [])

    @staticmethod
    def _read_csv(path: Path) -> list[dict]:
        with path.open(newline="", encoding="utf-8") as input_file:
            return list(csv.DictReader(input_file))

    @staticmethod
    def _build_archive(path: Path) -> None:
        files = {
            "Project_CodeNet/README.md": "CodeNet\n",
            "Project_CodeNet/metadata/problem_list.csv": (
                "id,name,dataset,time_limit,memory_limit,rating,tags,complexity\n"
                "p00001,One,AIZU,1000,131072,,,\n"
                "p00002,Two,AIZU,1000,131072,,,\n"
            ),
            "Project_CodeNet/metadata/p00001.csv": (
                METADATA_HEADER
                + "s000000001,p00001,u1,0,C,C,c,Accepted,1,2,3,1/1\n"
                + "s000000002,p00001,u1,0,C,C,c,Wrong Answer,1,2,3,0/1\n"
                + "s000000003,p00001,u1,0,Rust,Rust,rs,Accepted,1,2,3,1/1\n"
            ),
            "Project_CodeNet/metadata/p00002.csv": (
                METADATA_HEADER
                + "s000000004,p00002,u1,0,C,C,c,Wrong Answer,1,2,3,0/1\n"
            ),
            "Project_CodeNet/data/p00001/C/s000000001.c": "int main(void){return 0;}\n",
            "Project_CodeNet/data/p00001/C/s000000002.c": "wrong\n",
            "Project_CodeNet/data/p00001/Rust/s000000003.rs": "fn main() {}\n",
            "Project_CodeNet/problem_descriptions/p00001.html": "<html>One</html>\n",
            "Project_CodeNet/problem_descriptions/p00002.html": "<html>Two</html>\n",
            "Project_CodeNet/derived/input_output/README.md": "Sample I/O\n",
            "Project_CodeNet/derived/input_output/unverified_accepted_solutions.txt": (
                "p00001\np00002\n"
            ),
            "Project_CodeNet/derived/input_output/no_solutions.txt": "p00002\n",
            "Project_CodeNet/derived/input_output/data/p00001/input.txt": "1\n",
            "Project_CodeNet/derived/input_output/data/p00001/output.txt": "1\n",
            "Project_CodeNet/derived/input_output/data/p00002/input.txt": "2\n",
            "Project_CodeNet/derived/input_output/data/p00002/output.txt": "2\n",
        }
        with tarfile.open(path, "w:gz") as archive:
            for name, content in files.items():
                data = content.encode("utf-8")
                member = tarfile.TarInfo(name)
                member.size = len(data)
                if name.endswith(
                    (
                        "unverified_accepted_solutions.txt",
                        "no_solutions.txt",
                    )
                ):
                    member.mode = 0o444
                archive.addfile(member, io.BytesIO(data))
