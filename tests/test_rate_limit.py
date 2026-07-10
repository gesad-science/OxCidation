import unittest

from rate_limit import RequestRateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.delays = []

    def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.now += delay


class RequestRateLimiterTests(unittest.TestCase):
    def test_fifteen_rpm_spaces_requests_by_four_seconds(self):
        clock = FakeClock()
        limiter = RequestRateLimiter(15, clock=lambda: clock.now, sleep=clock.sleep)

        limiter.wait_for_slot()
        limiter.wait_for_slot()
        limiter.wait_for_slot()

        self.assertEqual(clock.delays, [4.0, 4.0])

    def test_zero_disables_pacing(self):
        clock = FakeClock()
        limiter = RequestRateLimiter(0, clock=lambda: clock.now, sleep=clock.sleep)

        limiter.wait_for_slot()

        self.assertEqual(clock.delays, [])
