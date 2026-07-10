import csv
import tempfile
import unittest
from pathlib import Path

from prepare_benchmark_population import build_population


METADATA_HEADER = (
    "submission_id,problem_id,user_id,date,language,original_language,filename_ext,"
    "status,cpu_time,memory,code_size,accuracy\n"
)


class PopulationBuilderTests(unittest.TestCase):
    def test_ignores_dataset_level_problem_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data"
            metadata_root = root / "metadata"
            (data_root / "p00001" / "C").mkdir(parents=True)
            metadata_root.mkdir()
            (data_root / "p00001" / "C" / "s000000001.c").write_text(
                "int main(void) { return 0; }", encoding="utf-8"
            )
            (metadata_root / "problem_list.csv").write_text(
                "id,name\np00001,example\n", encoding="utf-8"
            )
            (metadata_root / "p00001.csv").write_text(
                METADATA_HEADER + "s000000001,p00001,u1,0,C,C,c,Accepted,0,0,0,\n",
                encoding="utf-8",
            )

            rows, skipped = build_population(data_root, metadata_root, False, None)

            self.assertEqual(skipped, {})
            self.assertEqual(len(rows), 1)

    def test_keeps_only_verified_accepted_c_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data"
            metadata_root = root / "metadata"
            (data_root / "p00001" / "C").mkdir(parents=True)
            metadata_root.mkdir()
            (data_root / "p00001" / "C" / "s000000002.c").write_text(
                "int main(void) { return 0; }", encoding="utf-8"
            )
            (metadata_root / "p00001.csv").write_text(
                METADATA_HEADER
                + "s000000001,p00001,u1,0,C,C,c,Wrong Answer,0,0,0,\n"
                + "s000000002,p00001,u1,0,C,C,c,Accepted,0,0,0,\n",
                encoding="utf-8",
            )

            rows, skipped = build_population(data_root, metadata_root, False, None)

            self.assertEqual(skipped, {})
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["submission_id"], "s000000002")
            self.assertEqual(rows[0]["status"], "Accepted")

    def test_historical_gold_standard_requires_accepted_rust(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data"
            metadata_root = root / "metadata"
            (data_root / "p00001" / "C").mkdir(parents=True)
            metadata_root.mkdir()
            (data_root / "p00001" / "C" / "s000000001.c").write_text(
                "int main(void) { return 0; }", encoding="utf-8"
            )
            (metadata_root / "p00001.csv").write_text(
                METADATA_HEADER
                + "s000000001,p00001,u1,0,C,C,c,Accepted,0,0,0,\n"
                + "s000000002,p00001,u1,0,Rust,Rust,rs,Wrong Answer,0,0,0,\n",
                encoding="utf-8",
            )

            rows, skipped = build_population(data_root, metadata_root, True, None)

            self.assertEqual(rows, [])
            self.assertEqual(skipped, {"no_accepted_rust": 1})
