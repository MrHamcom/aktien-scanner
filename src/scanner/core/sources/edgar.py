"""SEC EDGAR (data.sec.gov): official XBRL annual figures of US companies, used as a
cross-check of the Yahoo data.

Fair-access rules (sec.gov, checked 25.11.2026): at most 10 requests per second and a
User-Agent with name and e-mail address. The User-Agent is read from SEC_USER_AGENT in .env.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date
from typing import Any

from scanner.core.sources.base import NoData, RateLimited, SourceError, TransientError

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
MAX_PER_SECOND = 5  # half the permitted rate


class EdgarClient:
    def __init__(
        self,
        user_agent: str,
        fetch: Callable[[str, dict[str, str]], bytes] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError("SEC_USER_AGENT fehlt oder enthält keine E-Mail-Adresse (.env)")
        self.headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self._fetch = fetch or _http_get
        self._sleep, self._clock = sleep, clock
        self._last = 0.0
        self._tickers: dict[str, int] | None = None

    def _get_json(self, url: str) -> Any:
        wait = 1 / MAX_PER_SECOND - (self._clock() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = self._clock()
        return json.loads(self._fetch(url, self.headers))

    def cik(self, ticker: str) -> int | None:
        if self._tickers is None:
            data = self._get_json(TICKERS_URL)
            self._tickers = {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}
        symbol = ticker.upper()
        return self._tickers.get(symbol) or self._tickers.get(symbol.replace("-", "."))

    def company_facts(self, cik: int) -> dict[str, Any]:
        return self._get_json(FACTS_URL.format(cik=cik))


def _http_get(url: str, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return body
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NoData(f"EDGAR: {url} nicht gefunden") from exc
        if exc.code in (403, 429):
            raise RateLimited(f"EDGAR: HTTP {exc.code}") from exc
        raise SourceError(f"EDGAR: HTTP {exc.code}") from exc
    except OSError as exc:
        raise TransientError(f"EDGAR: {exc}") from exc


def annual_value(
    facts: dict[str, Any], concepts: tuple[str, ...], period_end: date, instant: bool = False
) -> float | None:
    """Value of the first matching us-gaap concept from a 10-K for the fiscal year ending at
    `period_end` (± 7 days). Flow items must cover roughly one year."""
    gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    for concept in concepts:
        units = gaap.get(concept, {}).get("units", {})
        for unit, rows in units.items():
            if unit not in ("USD", "shares"):
                continue
            candidates = []
            for row in rows:
                if not str(row.get("form", "")).startswith("10-K"):
                    continue
                end = date.fromisoformat(row["end"])
                if abs((end - period_end).days) > 7:
                    continue
                if not instant:
                    if "start" not in row:
                        continue
                    days = (end - date.fromisoformat(row["start"])).days
                    if not 350 <= days <= 380:
                        continue
                candidates.append(row)
            if candidates:
                latest = max(candidates, key=lambda r: r.get("filed", ""))  # restated wins
                return float(latest["val"])
    return None
