import json
import tempfile
import unittest
from pathlib import Path

from logger_setup import RunRecorder


class RunRecorderTests(unittest.TestCase):
    def test_writes_json_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runs.jsonl"
            recorder = RunRecorder(str(path))

            recorder.write({"status": "success"})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"status": "success"})
