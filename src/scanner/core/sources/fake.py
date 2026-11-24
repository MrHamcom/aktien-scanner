"""Deterministic offline data source for tests and the demo mode (SCANNER_FAKE_SOURCE=1)."""

from __future__ import annotations

import hashlib
import time
from datetime import date, timedelta
from typing import Any

from scanner.core.sources.base import NoData, RateLimited


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


class FakeSource:
    """Generates plausible data. Tickers containing 'MISSING' have no data; 'LIMIT' is throttled
    on the first `rate_limit_failures` calls."""

    name = "fake"

    def __init__(self, delay: float = 0.0, rate_limit_failures: int = 0) -> None:
        self.delay = delay
        self.rate_limit_failures = rate_limit_failures
        self.calls: list[tuple[str, str]] = []

    def _call(self, ticker: str, dataset: str) -> int:
        self.calls.append((ticker, dataset))
        if self.delay:
            time.sleep(self.delay)
        if "MISSING" in ticker:
            raise NoData("unknown ticker")
        if "LIMIT" in ticker and self.rate_limit_failures > 0:
            self.rate_limit_failures -= 1
            raise RateLimited("Too Many Requests")
        return _seed(f"{ticker}:{dataset}")

    def history(self, ticker: str, price_days: int) -> dict[str, Any]:
        seed = self._call(ticker, "history")
        start = date(2026, 11, 20) - timedelta(days=price_days)
        days = [start + timedelta(days=i) for i in range(price_days)]
        base = 20 + seed % 200
        close = [round(base * (1 + 0.0004 * i), 2) for i in range(price_days)]
        return {
            "currency": "USD",
            "prices": {
                "date": [d.isoformat() for d in days],
                "close": close,
                "adj_close": close,
                "volume": [100_000 + seed % 50_000] * price_days,
            },
            "dividends": [[f"{y}-06-15", round(0.5 + (seed % 10) / 10 + 0.05 * (y - 2010), 2)]
                          for y in range(2010, 2027)] if seed % 3 else [],
            "splits": [],
        }

    def info(self, ticker: str) -> dict[str, Any]:
        seed = self._call(ticker, "info")
        return {
            "quoteType": "EQUITY",
            "shortName": ticker,
            "currency": "USD",
            "sharesOutstanding": 100_000_000 + seed % 900_000_000,
            "sector": "Technology",
        }

    def statement(self, ticker: str, kind: str) -> dict[str, Any]:
        seed = self._call(ticker, kind)
        periods = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]
        items = {
            "income": ["Total Revenue", "EBIT", "Net Income"],
            "balance": ["Total Assets", "Total Debt", "Stockholders Equity"],
            "cashflow": ["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow"],
        }[kind]
        return {
            "periods": periods,
            "items": items,
            "values": [[float((seed % 1000 + 100) * (j + 1) * 1e6) for j in range(4)]
                       for _ in items],
        }

    def fx_history(self, pair: str, price_days: int) -> dict[str, Any]:
        self._call(pair, "fx")
        start = date(2026, 11, 20) - timedelta(days=price_days)
        return {
            "date": [(start + timedelta(days=i)).isoformat() for i in range(price_days)],
            "close": [0.92] * price_days,
        }
