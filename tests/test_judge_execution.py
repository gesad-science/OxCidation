import unittest

from judge_execution import classify_oj_output


class JudgeOutputParsingTests(unittest.TestCase):
    def test_reports_all_verdicts_and_the_first_failure(self):
        output = """[INFO] sample-01.in
[SUCCESS] AC
[INFO] sample-02.in
[FAILURE] WA
expected: 7
actual: 8
[INFO] sample-03.in
[FAILURE] TLE
test failed: 1 AC / 3 cases
"""

        result = classify_oj_output(1, output, total=3, elapsed_ms=42)

        self.assertEqual(result["status"], "TIME_LIMIT_EXCEEDED")
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 2)
        self.assertEqual(result["verdict_counts"]["ACCEPTED"], 1)
        self.assertEqual(result["verdict_counts"]["WRONG_ANSWER"], 1)
        self.assertEqual(result["verdict_counts"]["TIME_LIMIT_EXCEEDED"], 1)
        self.assertEqual(result["first_failure"]["case"], "sample-02.in")
        self.assertEqual(result["first_failure"]["verdict"], "WRONG_ANSWER")

    def test_keeps_an_accepted_suite_accepted(self):
        result = classify_oj_output(
            0,
            "[SUCCESS] AC\n[SUCCESS] AC\ntest success: 2 cases",
            total=2,
            elapsed_ms=10,
        )

        self.assertEqual(result["status"], "ACCEPTED")
        self.assertEqual(result["passed"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["verdict_counts"]["ACCEPTED"], 2)

