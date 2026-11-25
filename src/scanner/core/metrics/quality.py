"""Quality factor (ROIC, Piotroski F-Score, net debt / EBITDA) and value-trap inputs
(Altman Z, negative free cash flow, share dilution)."""

from __future__ import annotations

from scanner.config import ValidationRules
from scanner.core.metrics.common import (
    CASH,
    CURRENT_ASSETS,
    CURRENT_LIABILITIES,
    EBIT,
    EBITDA,
    EQUITY,
    GROSS_PROFIT,
    LONG_TERM_DEBT,
    NET_INCOME,
    OPERATING_CASH_FLOW,
    PRETAX_INCOME,
    RETAINED_EARNINGS,
    REVENUE,
    SHARES,
    TAX,
    TOTAL_ASSETS,
    TOTAL_DEBT,
    TOTAL_LIABILITIES,
    WORKING_CAPITAL,
    MetricResult,
    free_cash_flow,
    ratio,
)
from scanner.core.metrics.inputs import StockInputs

NET_DEBT_EBITDA_WORST = 20.0  # used when EBITDA <= 0 but the company has net debt
ROIC_CAP = 1.0  # +-100 %: beyond that the ratio says nothing more for the ranking

DEFAULT_TAX_RATE = 0.25


def tax_rate(s: StockInputs) -> float:
    """Effective tax rate of the last year, clipped to 0–50 %; 25 % if not meaningful."""
    rate = ratio(s.income.value(TAX), s.income.value(PRETAX_INCOME))
    if rate is None or rate < 0 or rate > 0.5:
        return DEFAULT_TAX_RATE
    return rate


def roic(s: StockInputs) -> tuple[float | None, str | None]:
    """NOPAT / invested capital (debt + equity - cash), latest year. Returns (value, issue)."""
    ebit = s.income.value(EBIT)
    equity = s.balance.value(EQUITY)
    debt = s.balance.value(TOTAL_DEBT) or 0.0
    cash = s.balance.value(CASH)
    if ebit is None or equity is None or cash is None:
        return None, "roic_inputs_missing"
    invested = debt + equity - cash
    if invested <= 0:
        # more cash than debt + equity (e.g. buybacks below zero equity): the business needs
        # no net capital. Profitable -> best possible ROIC, otherwise worst.
        return (ROIC_CAP if ebit > 0 else -ROIC_CAP), "roic_capped"
    return max(-ROIC_CAP, min(ROIC_CAP, ebit * (1 - tax_rate(s)) / invested)), None


def piotroski(s: StockInputs) -> tuple[float | None, int, list[str]]:
    """Piotroski F-Score from the last two annual reports.

    Returns (score scaled to 0–9, number of signals that could be evaluated, failed signals).
    Signals that cannot be evaluated are skipped; the score is scaled to 9 so that missing
    gross-profit rows (common outside the US) do not penalise a company.
    """
    inc, bal, cf = s.income, s.balance, s.cashflow
    signals: dict[str, bool | None] = {}

    ta0, ta1 = bal.value(TOTAL_ASSETS, 0), bal.value(TOTAL_ASSETS, 1)
    ni0, ni1 = inc.value(NET_INCOME, 0), inc.value(NET_INCOME, 1)
    cfo0 = cf.value(OPERATING_CASH_FLOW, 0)
    roa0, roa1 = ratio(ni0, ta0), ratio(ni1, ta1)

    signals["roa_positive"] = None if roa0 is None else roa0 > 0
    signals["cfo_positive"] = None if cfo0 is None else cfo0 > 0
    signals["roa_improved"] = None if roa0 is None or roa1 is None else roa0 > roa1
    signals["accruals"] = None if cfo0 is None or ni0 is None else cfo0 > ni0

    def long_term_debt(year: int) -> float | None:
        # a reported total debt without a long-term row means no long-term debt
        if bal.value(TOTAL_DEBT, year) is None and bal.value(LONG_TERM_DEBT, year) is None:
            return None
        return bal.value(LONG_TERM_DEBT, year) or 0.0

    lev0, lev1 = ratio(long_term_debt(0), ta0), ratio(long_term_debt(1), ta1)
    signals["leverage_lower"] = None if lev0 is None or lev1 is None else lev0 <= lev1

    cr0 = ratio(bal.value(CURRENT_ASSETS, 0), bal.value(CURRENT_LIABILITIES, 0))
    cr1 = ratio(bal.value(CURRENT_ASSETS, 1), bal.value(CURRENT_LIABILITIES, 1))
    signals["liquidity_improved"] = None if cr0 is None or cr1 is None else cr0 > cr1

    sh0, sh1 = bal.value(SHARES, 0), bal.value(SHARES, 1)
    signals["no_dilution"] = None if sh0 is None or sh1 is None else sh0 <= sh1 * 1.005

    rev0, rev1 = inc.value(REVENUE, 0), inc.value(REVENUE, 1)
    gm0, gm1 = ratio(inc.value(GROSS_PROFIT, 0), rev0), ratio(inc.value(GROSS_PROFIT, 1), rev1)
    signals["margin_improved"] = None if gm0 is None or gm1 is None else gm0 > gm1

    at0, at1 = ratio(rev0, ta0), ratio(rev1, ta1)
    signals["turnover_improved"] = None if at0 is None or at1 is None else at0 > at1

    available = [v for v in signals.values() if v is not None]
    failed = [k for k, v in signals.items() if v is False]
    if not available:
        return None, 0, failed
    return sum(available) / len(available) * 9, len(available), failed


def net_debt_to_ebitda(s: StockInputs) -> float | None:
    debt = s.balance.value(TOTAL_DEBT) or 0.0
    cash = s.balance.value(CASH)
    ebitda = s.income.value(EBITDA)
    if cash is None or ebitda is None:
        return None
    net_debt = debt - cash
    if ebitda <= 0:
        return NET_DEBT_EBITDA_WORST if net_debt > 0 else 0.0
    return min(net_debt / ebitda, NET_DEBT_EBITDA_WORST)


def altman_z(s: StockInputs, market_cap_eur: float | None) -> float | None:
    """Original Altman Z-Score (1968). Market value of equity converted with the
    financial-currency rate so that all terms are in the same currency."""
    inc, bal = s.income, s.balance
    ta = bal.value(TOTAL_ASSETS)
    tl = bal.value(TOTAL_LIABILITIES)
    f_fx = s.financial_to_eur()
    wc = bal.value(WORKING_CAPITAL)
    if wc is None:
        ca, cl = bal.value(CURRENT_ASSETS), bal.value(CURRENT_LIABILITIES)
        wc = ca - cl if ca is not None and cl is not None else None
    re = bal.value(RETAINED_EARNINGS)
    ebit = inc.value(EBIT)
    sales = inc.value(REVENUE)
    if None in (ta, tl, wc, re, ebit, sales, market_cap_eur, f_fx) or not ta or not tl:
        return None
    mve = market_cap_eur / f_fx  # back into the financial currency
    return 1.2 * wc / ta + 1.4 * re / ta + 3.3 * ebit / ta + 0.6 * mve / tl + 1.0 * sales / ta


def compute(s: StockInputs, market_cap_eur: float | None, rules: ValidationRules) -> MetricResult:
    r = MetricResult()
    value, issue = roic(s)
    r.values["roic"] = value
    if issue == "roic_capped":
        r.flags.append(issue)
    elif issue:
        r.missing(issue)

    score, available, failed = piotroski(s)
    r.values["piotroski"] = score
    r.values["piotroski_signals"] = float(available)
    if available < rules.min_piotroski_signals:
        r.missing("piotroski_incomplete", f"{available} von 9 Signalen auswertbar")

    nd = net_debt_to_ebitda(s)
    r.values["net_debt_to_ebitda"] = nd
    if nd is None:
        r.missing("ebitda_missing")

    z = altman_z(s, market_cap_eur)
    r.values["altman_z"] = z
    if z is None:
        # only used by the value-trap filter; many IFRS reports have no retained-earnings
        # row, so the filter is skipped (and shown) instead of excluding the company
        r.flags.append("altman_unavailable")

    fcf = [free_cash_flow(s.cashflow, y) for y in range(3)]
    known = [v for v in fcf if v is not None]
    r.values["negative_fcf_years"] = float(sum(v < 0 for v in known)) if len(known) == 3 else None
    if len(known) < 3:
        r.flags.append("fcf_history_short")

    sh0, sh1 = s.balance.value(SHARES, 0), s.balance.value(SHARES, 1)
    r.values["share_change_1y"] = ratio(sh0, sh1) - 1 if ratio(sh0, sh1) is not None else None
    return r
