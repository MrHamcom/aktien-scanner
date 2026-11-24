"""Yahoo Finance via yfinance (unofficial interface, private use only)."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
import yfinance as yf
from yfinance import exceptions as yf_exc

from scanner.core.sources.base import NoData, RateLimited, TransientError

_STATEMENT_GETTERS = {
    "income": "get_income_stmt",
    "balance": "get_balance_sheet",
    "cashflow": "get_cashflow",
}


def _clean(value: Any) -> Any:
    """Convert pandas/numpy scalars to JSON-friendly Python values (NaN -> None)."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _classify(exc: Exception) -> Exception:
    """Map yfinance/network exceptions to the source error types."""
    if isinstance(exc, yf_exc.YFRateLimitError):
        return RateLimited(str(exc))
    if isinstance(exc, (yf_exc.YFTickerMissingError, yf_exc.YFPricesMissingError)):
        return NoData(str(exc))
    text = str(exc).lower()
    if "too many requests" in text or "429" in text or "rate limit" in text:
        return RateLimited(str(exc))
    if "404" in text or "not found" in text or "delisted" in text or "no data" in text:
        return NoData(str(exc))
    return TransientError(f"{type(exc).__name__}: {exc}")


class YahooSource:
    name = "yfinance"

    def history(self, ticker: str, price_days: int) -> dict[str, Any]:
        try:
            t = yf.Ticker(ticker)
            df = t.history(
                period="max", interval="1d", auto_adjust=False, actions=True, raise_errors=True
            )
            currency = (t.history_metadata or {}).get("currency")
        except Exception as exc:  # noqa: BLE001 – classified below
            raise _classify(exc) from exc
        if df is None or df.empty or "Close" not in df:
            raise NoData("no price history")

        prices = df.tail(price_days)
        empty = pd.Series(dtype=float)
        dividends = df["Dividends"][df["Dividends"] > 0] if "Dividends" in df else empty
        splits = df["Stock Splits"][df["Stock Splits"] > 0] if "Stock Splits" in df else empty
        adj = prices["Adj Close"] if "Adj Close" in prices else prices["Close"]
        volume = prices["Volume"] if "Volume" in prices else empty
        return {
            "currency": currency,
            "prices": {
                "date": [_clean(d) for d in prices.index],
                "close": [_clean(v) for v in prices["Close"]],
                "adj_close": [_clean(v) for v in adj],
                "volume": [_clean(v) for v in volume],
            },
            "dividends": [[_clean(d), _clean(v)] for d, v in dividends.items()],
            "splits": [[_clean(d), _clean(v)] for d, v in splits.items()],
        }

    def info(self, ticker: str) -> dict[str, Any]:
        try:
            data = yf.Ticker(ticker).get_info()
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from exc
        if not data or not (data.get("quoteType") or data.get("shortName")):
            raise NoData("no company info")
        return {str(k): _clean(v) if not isinstance(v, (list, dict)) else v
                for k, v in data.items()}

    def statement(self, ticker: str, kind: str) -> dict[str, Any]:
        getter = _STATEMENT_GETTERS[kind]
        try:
            df = getattr(yf.Ticker(ticker), getter)(freq="yearly")
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from exc
        if df is None or df.empty:
            raise NoData(f"no {kind} statement")
        return {
            "periods": [_clean(pd.Timestamp(c)) for c in df.columns],
            "items": [str(i) for i in df.index],
            "values": [[_clean(v) for v in row] for row in df.to_numpy().tolist()],
        }

    def fx_history(self, pair: str, price_days: int) -> dict[str, Any]:
        try:
            df = yf.Ticker(pair).history(
                period=f"{price_days}d", interval="1d", auto_adjust=False, raise_errors=True
            )
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from exc
        if df is None or df.empty:
            raise NoData(f"no fx data for {pair}")
        return {
            "date": [_clean(d) for d in df.index],
            "close": [_clean(v) for v in df["Close"]],
        }
