"""Momentum factor: 12-month return without the last month (12-1) and distance to the
200-day moving average."""

from __future__ import annotations

from scanner.core.metrics.common import MetricResult
from scanner.core.metrics.inputs import StockInputs

TRADING_DAYS_YEAR = 252
TRADING_DAYS_MONTH = 21
SMA_DAYS = 200


def compute(s: StockInputs) -> MetricResult:
    r = MetricResult()
    h = s.history
    if h is None or len(h.adj_close) < TRADING_DAYS_YEAR + 1:
        r.missing("price_history_short",
                  f"{0 if h is None else len(h.adj_close)} Handelstage, nötig "
                  f"{TRADING_DAYS_YEAR + 1}")
        r.values["momentum_12_1"] = None
        r.values["sma200_distance"] = None
        return r
    # adjusted closes include dividends: total-return momentum
    start = h.adj_close[-(TRADING_DAYS_YEAR + 1)]
    end = h.adj_close[-(TRADING_DAYS_MONTH + 1)]
    r.values["momentum_12_1"] = end / start - 1
    sma = sum(h.close[-SMA_DAYS:]) / SMA_DAYS
    r.values["sma200_distance"] = h.close[-1] / sma - 1
    return r
