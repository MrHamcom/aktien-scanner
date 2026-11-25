"""Dividend factor: yield, payout ratios, continuity, growth and dividend-trap flags.

Yahoo delivers individual payments (ex-dates, split-adjusted, in the quote currency) without
marking special dividends. Two problems are handled here:

* Payment rhythm: annual, semi-annual and quarterly payers are summed per *dividend year*.
  The year boundary is placed in the middle of the longest gap between the usual payment
  dates, so a payment that moves from December to January does not create a year with
  zero and a year with two dividends.
* Special dividends: a payment far above the usual amount, or an extra payment squeezed in
  next to a regular one, is treated as special and left out of yield and growth.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from scanner.config import DividendRules
from scanner.core.metrics.common import (
    DIVIDENDS_PAID,
    NET_INCOME,
    SHARES,
    MetricResult,
    free_cash_flow,
    ratio,
)
from scanner.core.metrics.inputs import StockInputs

FREQUENCIES = (1, 2, 4, 12)


@dataclass
class DividendHistory:
    frequency: int | None = None
    regular: list[tuple[date, float]] = field(default_factory=list)
    specials: list[tuple[date, float]] = field(default_factory=list)
    cut_day_of_year: int | None = None
    annual: dict[int, float] = field(default_factory=dict)  # dividend year -> regular sum
    last_complete_year: int | None = None


def detect_frequency(payments: list[tuple[date, float]], as_of: date) -> int | None:
    recent = [d for d, _ in payments if as_of - timedelta(days=3 * 365) < d <= as_of]
    if not recent:
        return None
    span_years = min(3.0, max(1.0, (as_of - payments[0][0]).days / 365.25))
    per_year = len(recent) / span_years
    return min(FREQUENCIES, key=lambda f: abs(f - per_year))


def split_specials(
    payments: list[tuple[date, float]], frequency: int, rules: DividendRules
) -> tuple[list[tuple[date, float]], list[tuple[date, float]]]:
    """Separate special dividends from regular ones."""
    if len(payments) < 2:
        return payments, []
    typical = statistics.median(a for _, a in payments[-max(4, 3 * frequency):])
    special_idx: set[int] = set()
    for i, (_, amount) in enumerate(payments):
        if amount > rules.special_factor * typical:
            special_idx.add(i)
    # an extra payment much closer to its neighbour than the usual interval
    min_gap = 365 / frequency * 0.4
    for i in range(1, len(payments)):
        if i in special_idx or i - 1 in special_idx:
            continue
        (d0, a0), (d1, a1) = payments[i - 1], payments[i]
        if (d1 - d0).days < min_gap:
            special_idx.add(i if abs(a1 - typical) >= abs(a0 - typical) else i - 1)
    regular = [p for i, p in enumerate(payments) if i not in special_idx]
    specials = [p for i, p in enumerate(payments) if i in special_idx]
    return regular, specials


def cut_day_of_year(payments: list[tuple[date, float]]) -> int:
    """Day of year in the middle of the longest gap between usual payment dates."""
    days = sorted({d.timetuple().tm_yday for d, _ in payments})
    if len(days) == 1:
        return (days[0] + 182) % 365 or 365
    gaps = [(days[(i + 1) % len(days)] - days[i]) % 365 for i in range(len(days))]
    i = max(range(len(gaps)), key=lambda k: gaps[k])
    return (days[i] + gaps[i] // 2 - 1) % 365 + 1


def _boundary(year: int, day_of_year: int) -> date:
    return date(year, 1, 1) + timedelta(days=min(day_of_year, 365) - 1)


def analyse(
    payments: list[tuple[date, float]], as_of: date, rules: DividendRules
) -> DividendHistory:
    payments = sorted(payments)
    result = DividendHistory()
    if not payments:
        return result
    frequency = detect_frequency(payments, as_of)
    if frequency is None:  # nothing paid in the last three years
        frequency = 1
    regular, specials = split_specials(payments, frequency, rules)
    result.frequency, result.regular, result.specials = frequency, regular, specials
    if not regular:
        return result

    recent = [p for p in regular if p[0] > as_of - timedelta(days=10 * 365)] or regular
    cut = cut_day_of_year(recent)
    result.cut_day_of_year = cut

    # dividend year Y covers (boundary(Y-1), boundary(Y)]; the year containing the first
    # payment is usually incomplete and is skipped
    first = regular[0][0]
    first_year = first.year if first <= _boundary(first.year, cut) else first.year + 1
    last_year = as_of.year if _boundary(as_of.year, cut) <= as_of else as_of.year - 1
    for year in range(first_year + 1, last_year + 1):
        start, end = _boundary(year - 1, cut), _boundary(year, cut)
        result.annual[year] = sum(a for d, a in regular if start < d <= end)
    result.last_complete_year = last_year if last_year in result.annual else None
    return result


def streak_without_cut(annual: dict[int, float], last: int, tolerance: float, cap: int) -> int:
    years = 0
    year = last
    while year - 1 in annual and annual[year] > 0 and years < cap:
        if annual[year] < annual[year - 1] * (1 - tolerance):
            break
        years += 1
        year -= 1
    return years


def compute(s: StockInputs, rules: DividendRules) -> MetricResult:
    r = MetricResult()
    h = s.history
    as_of = s.as_of or (h.last_date if h else None)
    if h is None or as_of is None or not h.last_price:
        r.missing("price_missing")
        return r

    hist = analyse(h.dividends, as_of, rules)
    last_payment = hist.regular[-1][0] if hist.regular else None
    payer_window = timedelta(days=rules.payer_window_days)
    is_payer = last_payment is not None and as_of - last_payment <= payer_window
    r.values["dividend_frequency"] = float(hist.frequency) if hist.frequency else None
    r.values["special_dividends_5y"] = float(
        sum(1 for d, _ in hist.specials if d > as_of - timedelta(days=5 * 365))
    )

    if not is_payer:
        r.values.update(is_payer=0.0, dividend_yield=0.0, dividend_streak=0.0,
                        dividend_growth=None, payout_fcf=None, payout_fcf_3y=None,
                        payout_earnings=None)
        if last_payment is not None and as_of - last_payment <= timedelta(days=2 * 365):
            r.flags.append("dividend_suspended")
        return r

    last = hist.last_complete_year
    current = hist.annual.get(last) if last is not None else None
    previous = hist.annual.get(last - 1) if last is not None else None
    if not current:
        # pays, but not yet a complete dividend year in the data (e.g. new listing)
        current = sum(a for d, a in hist.regular if d > as_of - timedelta(days=365))
        r.flags.append("dividend_history_short")

    r.values["is_payer"] = 1.0
    r.values["dividend_per_share"] = current
    r.values["dividend_yield"] = current / h.last_price
    if r.values["dividend_yield"] > rules.max_plausible_yield:
        r.missing("dividend_implausible",
                  f"Rendite {r.values['dividend_yield']:.0%} – Währung/Einheit prüfen")

    streak = (streak_without_cut(hist.annual, last, rules.cut_tolerance, rules.streak_cap_years)
              if last is not None else 0)
    r.values["dividend_streak"] = float(streak)

    base_year = last - rules.growth_years if last is not None else None
    base = hist.annual.get(base_year) if base_year is not None else None
    r.values["dividend_growth"] = (
        (current / base) ** (1 / rules.growth_years) - 1 if base and current else None
    )

    cut = previous is not None and current < previous * (1 - rules.cut_tolerance)
    regular_gap = timedelta(days=365 / (hist.frequency or 1) * 1.5 + 45)
    if cut or (last_payment is not None and as_of - last_payment > regular_gap):
        r.flags.append("dividend_cut")

    # payout ratios from the cash flow statement (dividends paid are negative there)
    paid = [s.cashflow.value(DIVIDENDS_PAID, y) for y in range(3)]
    fcf = [free_cash_flow(s.cashflow, y) for y in range(3)]
    paid_abs = [abs(p) if p is not None else None for p in paid]
    last_fcf = fcf[0]
    r.values["payout_fcf"] = (
        paid_abs[0] / last_fcf if paid_abs[0] is not None and last_fcf and last_fcf > 0 else None
    )
    known = [(p, f) for p, f in zip(paid_abs, fcf, strict=True) if p is not None and f is not None]
    fcf_sum = sum(f for _, f in known)
    r.values["payout_fcf_3y"] = (
        sum(p for p, _ in known) / fcf_sum if len(known) == 3 and fcf_sum > 0 else None
    )
    if paid_abs[0] is None:
        r.missing("dividends_paid_missing")
    elif len(known) == 3 and fcf_sum <= 0:
        r.flags.append("dividend_not_covered")
    ni = s.income.value(NET_INCOME)
    r.values["payout_earnings"] = paid_abs[0] / ni if paid_abs[0] is not None and ni and ni > 0 \
        else None

    # dividend trap flags (shown everywhere; excluded only in the dividend profile)
    if r.values["dividend_yield"] > rules.trap_yield_above:
        r.flags.append("dividend_yield_high")
    p1, p3 = r.values["payout_fcf"], r.values["payout_fcf_3y"]
    fcf_negative_last = last_fcf is not None and last_fcf <= 0 and (paid_abs[0] or 0) > 0
    if ((p1 is not None and p1 > rules.max_fcf_payout_last_year) or fcf_negative_last) and (
        p3 is None or p3 > rules.max_fcf_payout_avg_3y
    ):
        if "dividend_not_covered" not in r.flags:
            r.flags.append("dividend_not_covered")
    share_change = ratio(s.balance.value(SHARES, 0), s.balance.value(SHARES, 3))
    if share_change is not None and share_change - 1 > rules.share_increase_flag_3y:
        r.flags.append("dividend_share_funded")
    return r
