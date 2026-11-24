"""YahooSource conversion and error mapping, with yfinance replaced by a stub (no network)."""

import json

import numpy as np
import pandas as pd
import pytest
from yfinance import exceptions as yf_exc

from scanner.core.sources import NoData, RateLimited, TransientError, yahoo
from scanner.core.store import decode_payload, encode_payload


class StubTicker:
    def __init__(self, history=None, info=None, statements=None, error=None):
        self._history = history
        self._info = info
        self._statements = statements or {}
        self._error = error
        self.history_metadata = {"currency": "EUR"}

    def history(self, **kwargs):
        if self._error:
            raise self._error
        return self._history

    def get_info(self):
        if self._error:
            raise self._error
        return self._info

    def get_income_stmt(self, freq):
        return self._statements.get("income")

    def get_balance_sheet(self, freq):
        return self._statements.get("balance")

    def get_cashflow(self, freq):
        return self._statements.get("cashflow")


@pytest.fixture
def patch_ticker(monkeypatch):
    def apply(stub):
        monkeypatch.setattr(yahoo.yf, "Ticker", lambda _t: stub)

    return apply


def _history_frame(days: int = 500) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=days, freq="D", tz="Europe/Berlin")
    df = pd.DataFrame(
        {
            "Open": 1.0, "High": 1.0, "Low": 1.0,
            "Close": np.linspace(100, 120, days),
            "Adj Close": np.linspace(95, 120, days),
            "Volume": 1000,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
        index=index,
    )
    df.iloc[10, df.columns.get_loc("Dividends")] = 2.5
    df.iloc[300, df.columns.get_loc("Dividends")] = 2.7
    df.iloc[200, df.columns.get_loc("Stock Splits")] = 2.0
    df.iloc[5, df.columns.get_loc("Close")] = np.nan
    return df


def test_history_conversion(patch_ticker) -> None:
    patch_ticker(StubTicker(history=_history_frame()))
    data = yahoo.YahooSource().history("SAP.DE", price_days=400)
    assert data["currency"] == "EUR"
    assert len(data["prices"]["date"]) == 400
    assert data["prices"]["date"][-1] == "2026-05-15"
    assert data["dividends"] == [["2025-01-11", 2.5], ["2025-10-28", 2.7]]  # full history
    assert data["splits"] == [["2025-07-20", 2.0]]
    # JSON round trip works (no numpy types, NaN -> None)
    assert decode_payload(encode_payload(data)) == json.loads(json.dumps(data))


def test_nan_becomes_none(patch_ticker) -> None:
    patch_ticker(StubTicker(history=_history_frame(400)))
    data = yahoo.YahooSource().history("X", price_days=400)
    assert data["prices"]["close"][5] is None


def test_empty_history_is_no_data(patch_ticker) -> None:
    patch_ticker(StubTicker(history=pd.DataFrame()))
    with pytest.raises(NoData):
        yahoo.YahooSource().history("NOPE", 400)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (yf_exc.YFRateLimitError(), RateLimited),
        (RuntimeError("HTTP Error 429: Too Many Requests"), RateLimited),
        (RuntimeError("HTTP Error 404: Not Found"), NoData),
        (ConnectionError("connection reset"), TransientError),
    ],
)
def test_error_mapping(patch_ticker, error, expected) -> None:
    patch_ticker(StubTicker(error=error))
    with pytest.raises(expected):
        yahoo.YahooSource().history("X", 400)


def test_info_without_identity_is_no_data(patch_ticker) -> None:
    patch_ticker(StubTicker(info={"trailingPegRatio": None}))
    with pytest.raises(NoData):
        yahoo.YahooSource().info("X")


def test_info_values_are_cleaned(patch_ticker) -> None:
    patch_ticker(StubTicker(info={"quoteType": "EQUITY", "marketCap": np.int64(5),
                                  "beta": float("nan"), "officers": [{"name": "A"}]}))
    info = yahoo.YahooSource().info("X")
    assert info == {"quoteType": "EQUITY", "marketCap": 5, "beta": None,
                    "officers": [{"name": "A"}]}


def test_statement_conversion(patch_ticker) -> None:
    df = pd.DataFrame(
        [[10.0, np.nan], [3.0, 2.0]],
        index=["Total Revenue", "EBIT"],
        columns=[pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")],
    )
    patch_ticker(StubTicker(statements={"income": df}))
    data = yahoo.YahooSource().statement("X", "income")
    assert data == {
        "periods": ["2025-12-31", "2024-12-31"],
        "items": ["Total Revenue", "EBIT"],
        "values": [[10.0, None], [3.0, 2.0]],
    }
