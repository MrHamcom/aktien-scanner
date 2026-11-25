"""Value factor: earnings yield (EBIT / enterprise value) and free-cash-flow yield."""

from __future__ import annotations

from scanner.core.metrics.common import (
    CASH,
    EBIT,
    MINORITY_INTEREST,
    TOTAL_DEBT,
    MetricResult,
    free_cash_flow,
    ratio,
)
from scanner.core.metrics.inputs import StockInputs


def compute(s: StockInputs, market_cap_eur: float | None) -> MetricResult:
    r = MetricResult()
    f_fx = s.financial_to_eur()
    if f_fx is None:
        r.missing("fx_missing", f"Bilanzwährung {s.financial_currency}")
        return r

    ebit = s.income.value(EBIT)
    debt = s.balance.value(TOTAL_DEBT)
    cash = s.balance.value(CASH)
    minority = s.balance.value(MINORITY_INTEREST) or 0.0
    fcf = free_cash_flow(s.cashflow)

    if ebit is None:
        r.missing("ebit_missing")
    if cash is None:
        r.missing("cash_missing")
    if fcf is None:
        r.missing("fcf_missing")
    # no debt row usually means no financial debt; treat as zero but keep it visible
    if debt is None:
        debt = 0.0
        r.flags.append("debt_row_missing")

    ev = None
    if market_cap_eur is not None and cash is not None:
        ev = market_cap_eur + (debt + minority - cash) * f_fx
        r.values["enterprise_value_eur"] = ev
        if ev <= 0:
            r.missing("ev_nonpositive", f"EV {ev:,.0f} €")
            ev = None

    r.values["ebit_eur"] = ebit * f_fx if ebit is not None else None
    r.values["fcf_eur"] = fcf * f_fx if fcf is not None else None
    r.values["earnings_yield"] = ratio(r.values["ebit_eur"], ev)
    r.values["fcf_yield"] = ratio(r.values["fcf_eur"], market_cap_eur)
    return r
