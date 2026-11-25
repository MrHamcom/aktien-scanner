"""Prepared inputs for the metric calculations: statements, prices, dividends, currencies.

Everything here is pure: it works on the raw payloads stored in the database and does not
fetch anything. All monetary values used across statements and market data are converted
to EUR so that ratios never mix currencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Quote units that are fractions of the main currency (prices in pence, cents, agorot)
MINOR_UNITS: dict[str, tuple[str, float]] = {
    "GBp": ("GBP", 0.01),
    "GBX": ("GBP", 0.01),
    "ZAc": ("ZAR", 0.01),
    "ILA": ("ILS", 0.01),
    "KWF": ("KWD", 0.001),
}


def main_currency(code: str | None) -> tuple[str | None, float]:
    """(ISO currency, factor to convert a quoted amount into that currency)."""
    if not code:
        return None, 1.0
    if code in MINOR_UNITS:
        return MINOR_UNITS[code]
    return code.upper(), 1.0


def fx_pair(currency: str | None) -> str | None:
    """Yahoo FX ticker converting `currency` into EUR (pence and cents map to the main unit)."""
    code, _factor = main_currency(currency)
    if not code or code == "EUR":
        return None
    return f"{code}EUR=X"


def _item_key(name: str) -> str:
    """Row names come as "Cash And Cash Equivalents" or "CashAndCashEquivalents" depending on
    the yfinance call; compare them without spaces and case."""
    return re.sub(r"[^a-z0-9]", "", name.casefold())


class Statement:
    """Annual statement as stored by the Yahoo adapter: items x periods, newest period first."""

    def __init__(self, payload: dict[str, Any] | None, required: tuple[str, ...] = ()) -> None:
        """`required`: core rows; newest periods where one of them is empty are dropped.
        Yahoo often lists a just-ended fiscal year before the figures are filled in."""
        payload = payload or {}
        self.periods: list[str] = list(payload.get("periods") or [])
        self._rows: dict[str, list[float | None]] = {
            _item_key(str(item)): list(values)
            for item, values in zip(payload.get("items") or [], payload.get("values") or [],
                                    strict=False)
        }
        # Yahoo sometimes appends an all-empty oldest column; drop trailing empty periods.
        while self.periods and all(
            (len(v) <= len(self.periods) - 1 or v[len(self.periods) - 1] is None)
            for v in self._rows.values()
        ):
            self.periods.pop()
        self.dropped_periods: list[str] = []
        keys = [k for k in (_item_key(r) for r in required) if k in self._rows]
        while self.periods and keys and any(
            not self._rows[k] or self._rows[k][0] is None for k in keys
        ):
            self.dropped_periods.append(self.periods.pop(0))
            for k in self._rows:
                self._rows[k] = self._rows[k][1:]

    def __bool__(self) -> bool:
        return bool(self.periods)

    def has(self, *items: str) -> bool:
        return any(_item_key(i) in self._rows for i in items)

    def value(self, items: tuple[str, ...] | str, year: int = 0) -> float | None:
        """First available value among synonyms `items` for period index `year` (0 = latest)."""
        names = (items,) if isinstance(items, str) else items
        for name in names:
            row = self._rows.get(_item_key(name))
            if row is not None and year < len(row) and year < len(self.periods):
                v = row[year]
                if v is not None:
                    return float(v)
        return None

    def series(self, items: tuple[str, ...] | str, years: int) -> list[float | None]:
        return [self.value(items, y) for y in range(years)]

    def period_date(self, year: int = 0) -> date | None:
        if year >= len(self.periods):
            return None
        return date.fromisoformat(self.periods[year][:10])


@dataclass(frozen=True)
class FxRates:
    """Latest FX close per currency into EUR (EUR itself is 1)."""

    rates: dict[str, float] = field(default_factory=dict)

    def to_eur(self, currency: str | None) -> float | None:
        code, factor = main_currency(currency)
        if code is None:
            return None
        if code == "EUR":
            return factor
        rate = self.rates.get(code)
        return None if rate is None else rate * factor

    @classmethod
    def from_payloads(cls, payloads: dict[str, dict[str, Any]]) -> FxRates:
        """payloads: FX pair ('USDEUR=X') -> fx_history payload."""
        rates: dict[str, float] = {}
        for pair, payload in payloads.items():
            closes = [c for c in (payload or {}).get("close") or [] if c]
            if closes and pair.endswith("EUR=X"):
                rates[pair[: -len("EUR=X")]] = float(closes[-1])
        return cls(rates)


@dataclass
class PriceHistory:
    dates: list[date]
    close: list[float]
    adj_close: list[float]
    volume: list[float]
    currency: str | None
    dividends: list[tuple[date, float]]
    splits: list[tuple[date, float]]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> PriceHistory:
        prices = payload.get("prices") or {}
        rows = [
            (date.fromisoformat(d[:10]), c, a if a is not None else c, v or 0.0)
            for d, c, a, v in zip(
                prices.get("date") or [],
                prices.get("close") or [],
                prices.get("adj_close") or prices.get("close") or [],
                prices.get("volume") or [0.0] * len(prices.get("date") or []),
                strict=False,
            )
            if d and c is not None and c > 0
        ]
        return cls(
            dates=[r[0] for r in rows],
            close=[float(r[1]) for r in rows],
            adj_close=[float(r[2]) for r in rows],
            volume=[float(r[3]) for r in rows],
            currency=payload.get("currency"),
            dividends=[(date.fromisoformat(d[:10]), float(v))
                       for d, v in payload.get("dividends") or [] if d and v],
            splits=[(date.fromisoformat(d[:10]), float(v))
                    for d, v in payload.get("splits") or [] if d and v],
        )

    @property
    def last_price(self) -> float | None:
        return self.close[-1] if self.close else None

    @property
    def last_date(self) -> date | None:
        return self.dates[-1] if self.dates else None


@dataclass
class StockInputs:
    """Everything needed to evaluate one stock."""

    key: str
    name: str
    sector: str
    country: str
    region: str | None
    history: PriceHistory | None
    info: dict[str, Any]
    income: Statement
    balance: Statement
    cashflow: Statement
    fx: FxRates
    as_of: date | None = None  # evaluation date (day of the run)

    @property
    def quote_currency(self) -> str | None:
        return (self.history.currency if self.history else None) or self.info.get("currency")

    @property
    def financial_currency(self) -> str | None:
        return self.info.get("financialCurrency") or self.quote_currency

    def quote_to_eur(self) -> float | None:
        return self.fx.to_eur(self.quote_currency)

    def financial_to_eur(self) -> float | None:
        return self.fx.to_eur(self.financial_currency)
