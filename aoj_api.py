"""Shared HTTP and atomic-cache helpers for AOJ data preparation."""

from __future__ import annotations

import email.utils
import hashlib
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


class RequestRateLimiter:
    def __init__(self, requests_per_second: float):
        self._interval = 1.0 / requests_per_second
        self._next_request = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_request - now)
            self._next_request = max(now, self._next_request) + self._interval
        if delay:
            time.sleep(delay)


class AojHttpClient:
    def __init__(
        self,
        requests_per_second: float,
        timeout_sec: float,
        retries: int,
        stop_event: threading.Event,
        user_agent: str = "OxCidation-AOJ-data-preparation/1",
    ):
        self._rate_limiter = RequestRateLimiter(requests_per_second)
        self._timeout_sec = timeout_sec
        self._retries = retries
        self._stop_event = stop_event
        self._user_agent = user_agent

    def get(self, url: str) -> bytes:
        for attempt in range(self._retries + 1):
            if self._stop_event.is_set():
                raise InterruptedError("AOJ request interrupted.")
            self._rate_limiter.wait()
            request = urllib.request.Request(
                url,
                headers={"User-Agent": self._user_agent},
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout_sec) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt == self._retries:
                    raise
                delay = retry_delay(error.headers.get("Retry-After"), attempt)
            except (TimeoutError, urllib.error.URLError):
                if attempt == self._retries:
                    raise
                delay = retry_delay(None, attempt)
            if self._stop_event.wait(delay):
                raise InterruptedError("AOJ request interrupted.")
        raise RuntimeError("HTTP retry loop ended unexpectedly.")


def retry_delay(retry_after: str | None, attempt: int) -> float:
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            retry_time = email.utils.parsedate_to_datetime(retry_after)
            return max(0.0, retry_time.timestamp() - time.time())
    return min(30.0, 0.5 * (2**attempt)) + random.uniform(0.0, 0.25)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def atomic_write_json(path: Path, payload: object) -> None:
    atomic_write_bytes(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
