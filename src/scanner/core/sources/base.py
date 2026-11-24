"""Interface and error types shared by all data sources."""

from __future__ import annotations

from typing import Any, Protocol

# Datasets loaded per stock, in this order. "history" contains prices, dividends and splits.
DATASETS: tuple[str, ...] = ("history", "info", "income", "balance", "cashflow")
STATEMENTS: tuple[str, ...] = ("income", "balance", "cashflow")


class SourceError(Exception):
    """Base class for data source errors. `reason` is a short machine-readable code."""

    reason = "error"


class NoData(SourceError):
    """The source has no data for this request (unknown ticker, empty result). Not retried."""

    reason = "no_data"


class RateLimited(SourceError):
    """The source refused the request because of too many requests. Retried with backoff."""

    reason = "rate_limited"


class TransientError(SourceError):
    """Network or server problem. Retried with backoff."""

    reason = "transient"


class MarketDataSource(Protocol):
    """A provider of prices, dividends, company info and financial statements."""

    name: str

    def history(self, ticker: str, price_days: int) -> dict[str, Any]:
        """Daily prices of the last `price_days` days plus full dividend and split history.

        Returns {"currency": str|None, "prices": {"date": [...], "close": [...],
        "adj_close": [...], "volume": [...]}, "dividends": [[date, amount], ...],
        "splits": [[date, ratio], ...]}.
        """
        ...

    def info(self, ticker: str) -> dict[str, Any]:
        """Company master data (sector, currency, shares outstanding, ...)."""
        ...

    def statement(self, ticker: str, kind: str) -> dict[str, Any]:
        """Annual statement `kind` in {"income", "balance", "cashflow"}.

        Returns {"periods": [date, ...], "items": [name, ...], "values": [[...], ...]}
        with values[i][j] = item i in period j (None if missing).
        """
        ...

    def fx_history(self, pair: str, price_days: int) -> dict[str, Any]:
        """Daily closes of an FX pair such as "USDEUR=X": {"date": [...], "close": [...]}."""
        ...
