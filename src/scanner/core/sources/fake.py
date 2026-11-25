"""Deterministic offline data source for tests and the demo mode (SCANNER_FAKE_SOURCE=1)."""

from __future__ import annotations

import hashlib
import time
from datetime import date, timedelta
from typing import Any

from scanner.core.sources.base import NoData, RateLimited


def _last_dividend_year() -> int:
    today = date.today()
    return today.year if today > date(today.year, 6, 15) else today.year - 1


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
        start = date.today() - timedelta(days=price_days)
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
            "dividends": [[f"{y}-06-15", round(0.5 + (seed % 10) / 10 + 0.05 * (y - 2000), 2)]
                          for y in range(date.today().year - 16, _last_dividend_year() + 1)]
            if seed % 3 else [],
            "splits": [],
        }

    def info(self, ticker: str) -> dict[str, Any]:
        seed = self._call(ticker, "info")
        shares = 100_000_000 + seed % 900_000_000
        price = 20 + _seed(f"{ticker}:history") % 200
        return {
            "quoteType": "EQUITY",
            "currency": "USD",
            "financialCurrency": "USD",
            "sharesOutstanding": shares,
            "marketCap": round(price * (1 + 0.0004 * 399), 2) * shares,
        }

    def statement(self, ticker: str, kind: str) -> dict[str, Any]:
        """Coherent annual statements (four years, newest first) scaled to the market cap."""
        seed = self._call(ticker, kind)
        info_seed = _seed(f"{ticker}:info")
        price = 20 + _seed(f"{ticker}:history") % 200
        scale = price * (100_000_000 + info_seed % 900_000_000) * 0.6  # revenue ~ 60 % of cap
        margin = 0.08 + (seed % 15) / 100
        growth = [1.0, 0.95, 0.9, 0.86]
        revenue = [scale * g for g in growth]
        rows: dict[str, list[float]] = {}
        if kind == "income":
            ebit = [r * margin for r in revenue]
            rows = {
                "Total Revenue": revenue,
                "Gross Profit": [r * (0.35 + margin) for r in revenue],
                "EBIT": ebit,
                "EBITDA": [e * 1.3 for e in ebit],
                "Pretax Income": [e * 0.9 for e in ebit],
                "Tax Provision": [e * 0.9 * 0.24 for e in ebit],
                "Net Income": [e * 0.9 * 0.76 for e in ebit],
            }
        elif kind == "balance":
            assets = [r * 1.2 for r in revenue]
            rows = {
                "Total Assets": assets,
                "Current Assets": [a * 0.4 for a in assets],
                "Current Liabilities": [a * 0.2 for a in assets],
                "Total Liabilities Net Minority Interest": [a * 0.5 for a in assets],
                "Stockholders Equity": [a * 0.5 for a in assets],
                "Total Debt": [a * 0.25 for a in assets],
                "Long Term Debt": [a * 0.2 for a in assets],
                "Cash And Cash Equivalents": [a * 0.08 for a in assets],
                "Retained Earnings": [a * 0.35 for a in assets],
                "Ordinary Shares Number": [float(100_000_000 + info_seed % 900_000_000)] * 4,
            }
        else:
            ocf = [r * (margin + 0.05) for r in revenue]
            rows = {
                "Operating Cash Flow": ocf,
                "Capital Expenditure": [-r * 0.04 for r in revenue],
                "Cash Dividends Paid": [-o * 0.3 for o in ocf],
            }
        return {
            "periods": [f"{date.today().year - 1 - i}-12-31" for i in range(4)],
            "items": list(rows),
            "values": [[round(v, 2) for v in values] for values in rows.values()],
        }

    def fx_history(self, pair: str, price_days: int) -> dict[str, Any]:
        self._call(pair, "fx")
        start = date.today() - timedelta(days=price_days)
        return {
            "date": [(start + timedelta(days=i)).isoformat() for i in range(price_days)],
            "close": [0.92] * price_days,
        }
