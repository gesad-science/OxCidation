"""Local request pacing for providers with requests-per-minute limits."""

import threading
import time
from collections.abc import Callable


class RequestRateLimiter:
    def __init__(
        self,
        requests_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_minute < 0:
            raise ValueError("Requests per minute cannot be negative.")
        self._interval = 60 / requests_per_minute if requests_per_minute else 0
        self._clock = clock
        self._sleep = sleep
        self._next_request_at = 0.0
        self._lock = threading.Lock()

    def wait_for_slot(self) -> None:
        if not self._interval:
            return

        with self._lock:
            now = self._clock()
            request_at = max(now, self._next_request_at)
            self._next_request_at = request_at + self._interval

        delay = request_at - now
        if delay > 0:
            self._sleep(delay)
