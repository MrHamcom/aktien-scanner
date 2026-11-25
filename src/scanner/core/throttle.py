"""Request pacing and retries."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

from scanner.core.sources.base import NoData, RateLimited, SourceError, TransientError

T = TypeVar("T")


class Cancelled(Exception):
    """The run was cancelled by the user."""


class RateLimiter:
    """Ensures a minimum interval between requests."""

    def __init__(
        self,
        max_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = 60.0 / max_per_minute
        self.clock = clock
        self.sleep = sleep
        self._next = 0.0

    def acquire(self) -> None:
        now = self.clock()
        if now < self._next:
            self.sleep(self._next - now)
            now = self._next
        self._next = now + self.interval


def interruptible_sleep(seconds: float, cancel: threading.Event | None) -> None:
    """Sleep, but wake up immediately when the run is cancelled."""
    if cancel is None:
        time.sleep(seconds)
        return
    if cancel.wait(seconds):
        raise Cancelled()


class Fetcher:
    """Paces requests, retries rate limits and transient errors with exponential backoff."""

    def __init__(
        self,
        limiter: RateLimiter,
        max_retries: int,
        retry_base_seconds: float,
        cancel: threading.Event | None = None,
        on_wait: Callable[[str], None] | None = None,
        sleep: Callable[[float, threading.Event | None], None] = interruptible_sleep,
        transient_retries: int | None = None,
        transient_retry_base_seconds: float | None = None,
    ) -> None:
        self.limiter = limiter
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        # Connection problems of a single ticker rarely heal within minutes: retry fewer, shorter.
        self.transient_retries = max_retries if transient_retries is None else transient_retries
        self.transient_retry_base_seconds = (
            retry_base_seconds
            if transient_retry_base_seconds is None
            else transient_retry_base_seconds
        )
        self.cancel = cancel
        self.on_wait = on_wait or (lambda _msg: None)
        self.sleep = sleep
        self.requests = 0

    def call(self, fn: Callable[[], T]) -> T:
        """Run fn; NoData is raised at once, other source errors after the last retry."""
        attempt = 0
        while True:
            if self.cancel is not None and self.cancel.is_set():
                raise Cancelled()
            self.limiter.acquire()
            self.requests += 1
            try:
                return fn()
            except NoData:
                raise
            except (RateLimited, TransientError) as exc:
                limited = isinstance(exc, RateLimited)
                retries = self.max_retries if limited else self.transient_retries
                base = self.retry_base_seconds if limited else self.transient_retry_base_seconds
                if attempt >= retries:
                    raise
                wait = base * (2**attempt)
                kind = "Abrufsperre" if limited else "Verbindungsproblem"
                self.on_wait(f"{kind} – neuer Versuch in {wait:.0f} s")
                self.sleep(wait, self.cancel)
                attempt += 1
            except SourceError:
                raise
