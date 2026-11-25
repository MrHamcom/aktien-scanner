"""Regression tests on real Yahoo payloads (5 companies, saved on 25.11.2026).

They guard against the format surprises found in Subphase C: CamelCase row names, an empty
newest fiscal year, prices in pence with the market cap in pounds, reports in another
currency than the quote, missing operating-cash-flow rows.
"""

import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from scanner.core.metrics.common import CORE_ROWS
from scanner.core.metrics.inputs import FxRates, PriceHistory, Statement, StockInputs
from scanner.core.validate import evaluate

DATA = json.loads(gzip.decompress(
    (Path(__file__).parent / "fixtures" / "yahoo_real.json.gz").read_bytes()))
AS_OF = date(2026, 11, 25)


def stock(key: str) -> StockInputs:
    d = DATA["stocks"][key]
    meta = d["meta"]
    return StockInputs(
        key=key, name=meta["name"], sector=meta["sector"], country=meta["country"],
        region=meta["region"], history=PriceHistory.from_payload(d["history"]), info=d["info"],
        income=Statement(d["income"], CORE_ROWS["income"]),
        balance=Statement(d["balance"], CORE_ROWS["balance"]),
        cashflow=Statement(d["cashflow"], CORE_ROWS["cashflow"]),
        fx=FxRates.from_payloads(DATA["fx"]), as_of=AS_OF,
    )


@pytest.mark.parametrize("key", ["AAPL", "ULVR.L", "0700.HK", "CSL.AX", "AMAT"])
def test_real_companies_pass_plausibility(key, config) -> None:
    ev = evaluate(stock(key), config)
    assert ev.status not in ("data", "plausibility"), (ev.reason, ev.detail)


def test_pence_market_cap_is_in_pounds(config) -> None:
    ev = evaluate(stock("ULVR.L"), config)
    gbp = DATA["fx"]["GBPEUR=X"]["close"][-1]
    assert ev.metrics["market_cap_eur"] == pytest.approx(
        DATA["stocks"]["ULVR.L"]["info"]["marketCap"] * gbp)
    assert 0.005 < ev.metrics["dividend_yield"] < 0.08


def test_empty_newest_fiscal_year_is_skipped() -> None:
    s = stock("AMAT")
    assert s.income.dropped_periods == ["2026-10-31"]
    assert s.income.value(("EBIT",)) is not None


def test_reporting_currency_differs(config) -> None:
    s = stock("0700.HK")
    assert s.quote_currency == "HKD" and s.financial_currency == "CNY"
    ev = evaluate(s, config)
    assert 0 < ev.metrics["earnings_yield"] < 0.2
