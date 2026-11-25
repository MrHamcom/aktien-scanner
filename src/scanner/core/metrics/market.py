"""Market data in EUR: price, shares, market capitalisation, liquidity."""

from __future__ import annotations

from scanner.config import ValidationRules
from scanner.core.metrics.common import SHARES, MetricResult, ratio
from scanner.core.metrics.inputs import StockInputs, main_currency


def compute(s: StockInputs, rules: ValidationRules, window: int) -> MetricResult:
    r = MetricResult()
    h = s.history
    if h is None or not h.close:
        r.missing("price_missing")
        return r

    q_fx = s.quote_to_eur()
    if q_fx is None:
        r.missing("fx_missing", f"Kurswährung {s.quote_currency}")
        return r

    price = h.last_price
    r.values["price_eur"] = price * q_fx if price else None

    # company-wide share count (all share classes, e.g. China A + H shares, GOOG + GOOGL):
    # Yahoo's market cap refers to the whole company, which is what EV and yields need
    shares = (s.info.get("impliedSharesOutstanding") or s.info.get("sharesOutstanding")
              or s.balance.value(SHARES, 0))
    r.values["shares"] = float(shares) if shares else None

    # prices may be quoted in pence/cents; Yahoo's market cap is in the main currency (GBP)
    main, unit = main_currency(s.quote_currency)
    main_fx = s.fx.to_eur(main)
    market_cap = s.info.get("marketCap")
    computed = price * shares * unit if price and shares else None
    if market_cap and computed:
        deviation = abs(market_cap / computed - 1)
        r.values["market_cap_deviation"] = deviation
        if deviation > rules.max_market_cap_deviation:
            r.missing("market_cap_mismatch",
                      f"Yahoo {market_cap:,.0f} vs. Kurs × Aktien {computed:,.0f}")
    market_cap = market_cap or computed
    if not market_cap:
        r.missing("market_cap_missing")
    r.values["market_cap_eur"] = market_cap * main_fx if market_cap and main_fx else None

    if len(h.close) >= window:
        turnover = [c * v for c, v in zip(h.close[-window:], h.volume[-window:], strict=True)]
        r.values["avg_daily_value_eur"] = sum(turnover) / window * q_fx
    else:
        r.missing("price_history_short", f"{len(h.close)} Handelstage")

    if h.last_date is not None and s.as_of is not None:
        age = (s.as_of - h.last_date).days
        r.values["price_age_days"] = float(age)
        if age > rules.max_price_age_days:
            r.missing("price_stale", f"letzter Kurs {h.last_date.isoformat()}")

    # share count jumps by more than a factor of 2 between annual reports -> data problem
    shares_now, shares_prev = s.balance.value(SHARES, 0), s.balance.value(SHARES, 1)
    jump = ratio(shares_now, shares_prev)
    if jump is not None and jump > 0 and (jump > 2 or jump < 0.5):
        r.missing("shares_jump", f"Aktienanzahl Faktor {jump:.2f} zum Vorjahr")
    return r
