"""Small formatting helpers (German number and time formats)."""

from __future__ import annotations

from datetime import datetime


def number(value: float | int | None) -> str:
    if value is None:
        return "–"
    return f"{value:,.0f}".replace(",", ".")


def percent(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value * 100:.0f} %"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    minutes = int(seconds // 60)
    if minutes < 1:
        return "< 1 min"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def timestamp(value: datetime | None) -> str:
    if value is None:
        return "–"
    return value.astimezone().strftime("%d.%m.%Y %H:%M")
