"""Evaluation of one stock: metrics, plausibility (fail closed), universe rule, value-trap filter.

The result says whether the stock can be ranked and, if not, at which stage it dropped out and
why. All metric values are kept even for excluded stocks so the user can see what was wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from scanner.config import ScannerConfig
from scanner.core.metrics import dividend, market, momentum, quality, value
from scanner.core.metrics.common import Issue, MetricResult
from scanner.core.metrics.inputs import StockInputs

# Stages in the order they are applied (also the order of the exclusion funnel in the UI)
STAGES: tuple[str, ...] = (
    "data",          # a required dataset could not be loaded
    "plausibility",  # required values missing or implausible
    "size",          # market capitalisation below the threshold
    "liquidity",     # average daily trading value below the threshold
    "share_class",   # second share class of the same company
    "value_trap",    # negative free cash flow, Altman Z, dilution
)
RATED = "rated"

_NAME_STOPWORDS = {
    "inc", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "ag", "sa", "se",
    "nv", "ab", "asa", "as", "spa", "holdings", "holding", "group", "class", "cl", "the", "and",
    "berhad", "bhd", "tbk", "pt", "pcl", "public", "kk", "adr", "ord", "shs", "reg", "sab",
    "de", "cv", "oyj", "ltda", "lp", "a", "b", "c", "h", "n", "v", "i", "ii", "s", "of", "jsc",
    "pjsc", "gmbh", "kgaa", "ltd.", "intl", "international", "industries", "co.", "shares",
}


@dataclass
class Evaluation:
    key: str
    status: str = RATED  # "rated" or the stage that excluded the stock
    reason: str | None = None
    detail: str = ""
    issues: list[Issue] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)

    @property
    def rated(self) -> bool:
        return self.status == RATED

    def exclude(self, stage: str, reason: str, detail: str = "") -> None:
        if self.rated:  # the first failing stage wins
            self.status, self.reason, self.detail = stage, reason, detail


def _tokens(name: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", name.casefold())
    return {w for w in words if w not in _NAME_STOPWORDS and len(w) > 1}


def name_similarity(a: str, b: str) -> float:
    """Share of the shorter name's significant words found in the other name.
    Words match on their first four letters ("MANUFACTURING" ~ "Manufacturing Co")."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 1.0  # nothing to compare -> no evidence against the match
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    prefixes = {w[:4] for w in large}
    hits = sum(1 for w in small if w[:4] in prefixes)
    return hits / len(small)


# Issues that do not make the whole stock unusable
_SOFT_ISSUES = {"dividends_paid_missing"}


def evaluate(
    s: StockInputs,
    config: ScannerConfig,
    missing_datasets: list[str] | None = None,
) -> Evaluation:
    ev = Evaluation(key=s.key)
    if missing_datasets:
        ev.exclude("data", "dataset_missing", ", ".join(missing_datasets))
        return ev

    rules = config.validation
    result = MetricResult()
    m = market.compute(s, rules, config.universe_rule.avg_daily_value_window_days)
    result.merge(m)
    market_cap = m.values.get("market_cap_eur")
    result.merge(value.compute(s, market_cap))
    result.merge(quality.compute(s, market_cap, rules))
    result.merge(momentum.compute(s))
    result.merge(dividend.compute(s, config.dividend))

    # checks that need more than one module
    quote_type = str(s.info.get("quoteType") or "").upper()
    if quote_type and quote_type != "EQUITY":
        result.missing("security_type", quote_type)
    yahoo_name = str(s.info.get("longName") or s.info.get("shortName") or "")
    similarity = name_similarity(s.name, yahoo_name) if yahoo_name else 1.0
    result.values["name_similarity"] = similarity
    if similarity < rules.min_name_similarity:
        result.missing("name_mismatch", f"Startliste „{s.name}“ / Yahoo „{yahoo_name}“")
    statement_date = s.income.period_date(0)
    if statement_date is None:
        result.missing("statements_missing")
    elif s.as_of is not None and (s.as_of - statement_date).days > rules.max_statement_age_days:
        result.missing("statements_stale", f"letzter Jahresabschluss {statement_date.isoformat()}")

    ev.metrics, ev.issues, ev.flags = result.values, result.issues, result.flags
    hard = [i for i in result.issues if i.code not in _SOFT_ISSUES]
    if hard:
        ev.exclude("plausibility", hard[0].code, hard[0].detail)
        return ev

    rule = config.universe_rule
    cap = ev.metrics.get("market_cap_eur") or 0.0
    if cap < rule.min_market_cap_eur:
        ev.exclude("size", "market_cap_below", f"{cap / 1e9:.2f} Mrd. €")
    adv = ev.metrics.get("avg_daily_value_eur") or 0.0
    if adv < rule.min_avg_daily_value_eur:
        ev.exclude("liquidity", "turnover_below", f"{adv / 1e6:.1f} Mio. € pro Tag")

    traps = config.value_trap_filters
    negative = ev.metrics.get("negative_fcf_years")
    if negative is not None and negative >= traps.negative_fcf_years_of_last_3:
        ev.exclude("value_trap", "negative_fcf", f"{negative:.0f} von 3 Jahren")
    z = ev.metrics.get("altman_z")
    if z is not None and z < traps.min_altman_z:
        ev.exclude("value_trap", "altman_z_low", f"Z = {z:.2f}")
    dilution = ev.metrics.get("share_change_1y")
    if dilution is not None and dilution > traps.max_share_dilution_12m:
        ev.exclude("value_trap", "dilution", f"Aktienanzahl {dilution:+.0%} in 12 Monaten")
    return ev

