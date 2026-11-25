"""Hand-built example company "Testco" with values that are easy to recompute by hand.

All amounts in EUR (millions are written out). Two annual reports (2025, 2024), three cash
flow years. See tests/test_metrics.py for the expected results and their derivation.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from scanner.core.metrics.inputs import FxRates, PriceHistory, Statement, StockInputs

M = 1e6
AS_OF = date(2026, 11, 20)
PERIODS = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]


def statement(rows: dict[str, list[float | None]]) -> dict[str, Any]:
    return {"periods": PERIODS, "items": list(rows),
            "values": [v + [None] * (len(PERIODS) - len(v)) for v in rows.values()]}


def company_income(**overrides: list[float | None]) -> dict[str, Any]:
    rows = {
        "Total Revenue": [1000 * M, 900 * M],
        "Gross Profit": [400 * M, 340 * M],
        "EBIT": [150 * M, 120 * M],
        "EBITDA": [200 * M, 170 * M],
        "Net Income": [100 * M, 80 * M],
        "Pretax Income": [130 * M, 105 * M],
        "Tax Provision": [32.5 * M, 26.25 * M],
    }
    rows.update(overrides)
    return statement(rows)


def company_balance(**overrides: list[float | None]) -> dict[str, Any]:
    rows = {
        "Total Assets": [1200 * M, 1100 * M],
        "Current Assets": [500 * M, 450 * M],
        "Current Liabilities": [250 * M, 250 * M],
        "Total Liabilities Net Minority Interest": [700 * M, 650 * M],
        "Stockholders Equity": [500 * M, 450 * M],
        "Total Debt": [300 * M, 320 * M],
        "Long Term Debt": [250 * M, 280 * M],
        "Cash And Cash Equivalents": [100 * M, 80 * M],
        "Retained Earnings": [400 * M, 350 * M],
        "Ordinary Shares Number": [100 * M, 100 * M],
    }
    rows.update(overrides)
    return statement(rows)


def company_cashflow(**overrides: list[float | None]) -> dict[str, Any]:
    rows = {
        "Operating Cash Flow": [180 * M, 150 * M, 140 * M],
        "Capital Expenditure": [-60 * M, -50 * M, -40 * M],
        "Cash Dividends Paid": [-50 * M, -45 * M, -40 * M],
    }
    rows.update(overrides)
    return statement(rows)


def trading_days(n: int, end: date = AS_OF) -> list[date]:
    days: list[date] = []
    d = end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


def momentum_closes() -> list[float]:
    """300 closes: 80 (48 days), then 100 (231 days), then 110 (last 21 days)."""
    return [80.0] * 48 + [100.0] * 231 + [110.0] * 21


def history(
    closes: list[float] | None = None,
    dividends: list[tuple[str, float]] | None = None,
    currency: str = "EUR",
    volume: float = 1_000_000,
) -> PriceHistory:
    closes = closes or [20.0] * 300
    days = trading_days(len(closes))
    return PriceHistory(
        dates=days, close=closes, adj_close=list(closes), volume=[volume] * len(closes),
        currency=currency,
        dividends=[(date.fromisoformat(d), a) for d, a in dividends or []],
        splits=[],
    )


def company(
    *,
    hist: PriceHistory | None = None,
    info: dict[str, Any] | None = None,
    income: dict[str, Any] | None = None,
    balance: dict[str, Any] | None = None,
    cashflow: dict[str, Any] | None = None,
    fx: dict[str, float] | None = None,
    name: str = "TESTCO AG",
    country: str = "Germany",
) -> StockInputs:
    base_info = {"quoteType": "EQUITY", "longName": "Testco AG", "currency": "EUR",
                 "financialCurrency": "EUR", "marketCap": 2000 * M,
                 "sharesOutstanding": 100 * M}
    base_info.update(info or {})
    return StockInputs(
        key="TST.DE", name=name, sector="Industrials", country=country, region="Europe",
        history=hist or history(),
        info=base_info,
        income=Statement(income or company_income()),
        balance=Statement(balance or company_balance()),
        cashflow=Statement(cashflow or company_cashflow()),
        fx=FxRates(fx or {}),
        as_of=AS_OF,
    )
