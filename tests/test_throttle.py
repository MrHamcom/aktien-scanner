import threading

import pytest

from scanner.core.sources.base import NoData, RateLimited, TransientError
from scanner.core.throttle import Cancelled, Fetcher, RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_rate_limiter_spaces_requests() -> None:
    clock = FakeClock()
    limiter = RateLimiter(60, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        limiter.acquire()
    assert clock.slept == [1.0, 1.0]


def _fetcher(retries: int = 3, cancel: threading.Event | None = None):
    clock = FakeClock()
    waits: list[float] = []
    fetcher = Fetcher(
        RateLimiter(6000, clock=clock, sleep=clock.sleep),
        max_retries=retries,
        retry_base_seconds=10,
        cancel=cancel,
        sleep=lambda s, _c: waits.append(s),
    )
    return fetcher, waits


def test_retries_rate_limit_with_backoff() -> None:
    fetcher, waits = _fetcher()
    outcomes = iter([RateLimited("429"), TransientError("timeout"), "ok"])

    def fn():
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    assert fetcher.call(fn) == "ok"
    assert waits == [10, 20]
    assert fetcher.requests == 3


def test_gives_up_after_max_retries() -> None:
    fetcher, waits = _fetcher(retries=2)

    def fn():
        raise RateLimited("429")

    with pytest.raises(RateLimited):
        fetcher.call(fn)
    assert waits == [10, 20]


def test_no_data_is_not_retried() -> None:
    fetcher, waits = _fetcher()

    def fn():
        raise NoData("unknown")

    with pytest.raises(NoData):
        fetcher.call(fn)
    assert waits == [] and fetcher.requests == 1


def test_cancel_stops_before_request() -> None:
    cancel = threading.Event()
    cancel.set()
    fetcher, _ = _fetcher(cancel=cancel)
    with pytest.raises(Cancelled):
        fetcher.call(lambda: "never")
