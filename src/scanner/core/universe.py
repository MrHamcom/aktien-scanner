"""Start list: load the ETF holdings file, map tickers to Yahoo, select ramp-up samples.

The holdings file is the only external input here; everything else is pure and unit-tested.
"""

from __future__ import annotations

import csv
import io
import re
import urllib.request
from collections import defaultdict
from dataclasses import dataclass

from scanner.config import ExchangesConfig, ScannerConfig
from scanner.core.store import StartListEntry
from scanner.paths import resolve_project_path

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
}

FULL_SCOPE = "full"


class StartListError(RuntimeError):
    """The start list could not be loaded or parsed."""


@dataclass(frozen=True)
class Holding:
    ticker: str
    name: str
    sector: str
    asset_class: str
    weight: float
    country: str
    exchange: str
    currency: str


# --- loading ----------------------------------------------------------------------------------


def fetch_holdings_text(config: ScannerConfig, timeout: float = 60) -> tuple[str, str]:
    """Return (csv_text, origin). A local file, if present, takes precedence over the download."""
    local = resolve_project_path(config.start_list.local_file)
    if local.is_file():
        return local.read_text(encoding="utf-8-sig", errors="replace"), f"Datei {local}"
    request = urllib.request.Request(config.start_list.url, headers=BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except OSError as exc:
        raise StartListError(
            f"Startliste konnte nicht geladen werden ({exc}). Ausweg: CSV von der iShares-Seite "
            f"herunterladen und als {local} speichern."
        ) from exc
    text = raw.decode("utf-8-sig", errors="replace")
    if _looks_like_html(text):
        raise StartListError(
            "Startliste: iShares lieferte eine Webseite statt einer CSV-Datei – die Download-"
            f"Adresse ist vermutlich veraltet. Ausweg: CSV von der iShares-Seite herunterladen "
            f"und als {local} speichern."
        )
    return text, "Download iShares"


def _looks_like_html(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


def _number(text: str) -> float:
    cleaned = text.replace(",", "").replace("%", "").strip()
    if cleaned in {"", "-", "--"}:
        return 0.0
    return float(cleaned)


def parse_ishares_csv(text: str) -> list[Holding]:
    """Parse an iShares holdings CSV (metadata lines, header line, rows, disclaimer footer)."""
    lines = text.splitlines()
    header_index = next(
        (i for i, line in enumerate(lines) if line.lstrip('"').startswith("Ticker")), None
    )
    if header_index is None:
        if _looks_like_html(text):
            raise StartListError("Startliste: Webseite statt CSV-Datei erhalten")
        first = next((line for line in lines if line.strip()), "")[:60]
        raise StartListError(
            f"Startliste: Kopfzeile mit 'Ticker' nicht gefunden (Beginn: {first!r})"
        )

    reader = csv.reader(io.StringIO("\n".join(lines[header_index:])))
    header = [h.strip() for h in next(reader)]
    required = {"Ticker", "Name", "Sector", "Asset Class", "Weight (%)", "Location", "Exchange"}
    missing = required - set(header)
    if missing:
        raise StartListError(f"Startliste: Spalten fehlen: {sorted(missing)}")
    col = {name: header.index(name) for name in header}

    holdings: list[Holding] = []
    for row in reader:
        if len(row) < len(header) or not row[col["Ticker"]].strip():
            break  # end of the table (blank line or disclaimer)
        try:
            weight = _number(row[col["Weight (%)"]])
        except ValueError:
            break
        holdings.append(
            Holding(
                ticker=row[col["Ticker"]].strip(),
                name=row[col["Name"]].strip(),
                sector=row[col["Sector"]].strip(),
                asset_class=row[col["Asset Class"]].strip(),
                weight=weight,
                country=row[col["Location"]].strip(),
                exchange=row[col["Exchange"]].strip(),
                currency=row[col["Currency"]].strip() if "Currency" in col else "",
            )
        )
    if not holdings:
        raise StartListError("Startliste: keine Positionen gefunden")
    return holdings


# --- mapping ----------------------------------------------------------------------------------


def to_yahoo_ticker(holding: Holding, exchanges: ExchangesConfig) -> tuple[str | None, str | None]:
    """Return (yahoo_ticker, None) or (None, reason)."""
    if holding.ticker in exchanges.ticker_overrides:
        return exchanges.ticker_overrides[holding.ticker], None
    rule = exchanges.rule_for(holding.exchange)
    if rule is None:
        return None, f"exchange_unmapped: {holding.exchange}"
    if rule.by_country is not None:
        suffix = rule.by_country.get(holding.country)
        if suffix is None:
            return None, f"exchange_country_unmapped: {holding.exchange} / {holding.country}"
    else:
        suffix = rule.suffix or ""

    symbol = holding.ticker.strip().rstrip(".")
    if rule.zero_pad and symbol.isdigit():
        symbol = symbol.zfill(rule.zero_pad)
    if rule.separator is not None:
        symbol = re.sub(r"[./ ]", rule.separator, symbol)
    if not symbol:
        return None, "ticker_empty"
    return f"{symbol}{suffix}", None


def build_start_list(
    holdings: list[Holding], config: ScannerConfig, exchanges: ExchangesConfig
) -> list[StartListEntry]:
    """Equities only, one entry per Yahoo ticker, with region, mapping and sector exclusion."""
    excluded_sectors = {s.casefold() for s in config.universe_rule.excluded_sectors}
    entries: list[StartListEntry] = []
    seen: set[str] = set()
    for h in sorted(holdings, key=lambda x: x.weight, reverse=True):
        if h.asset_class.casefold() != "equity":
            continue
        yahoo, reason = to_yahoo_ticker(h, exchanges)
        region = config.region_of(h.country)
        status = "included"
        if yahoo is None:
            status = "unmapped"
        elif yahoo in seen:
            continue  # duplicate listing of the same security
        elif h.sector.casefold() in excluded_sectors:
            status, reason = "excluded", f"sector: {h.sector}"
        if yahoo:
            seen.add(yahoo)
        entries.append(
            StartListEntry(
                source_ticker=h.ticker, yahoo_ticker=yahoo, name=h.name, sector=h.sector,
                country=h.country, region=region, exchange=h.exchange, currency=h.currency,
                weight=h.weight, status=status, reason=reason,
            )
        )
    return entries


# --- ramp-up samples --------------------------------------------------------------------------


def scope_labels(config: ScannerConfig) -> dict[str, str]:
    labels = {key: sample.label for key, sample in config.ramp_up.items()}
    labels[FULL_SCOPE] = "Vollständig"
    return labels


def select_scope(
    entries: list[StartListEntry], scope: str, config: ScannerConfig
) -> list[StartListEntry]:
    """Keep the entries of a ramp-up sample (largest weights first) or all for 'full'."""
    if scope == FULL_SCOPE:
        return entries
    if scope not in config.ramp_up:
        raise ValueError(f"unknown scope: {scope}")
    sample = config.ramp_up[scope]
    ordered = sorted(entries, key=lambda e: e.weight, reverse=True)
    counts: dict[str, int] = defaultdict(int)
    chosen: list[StartListEntry] = []
    for entry in ordered:
        if sample.per_country is not None:
            group, limit = entry.country, sample.per_country.get(entry.country, 0)
        else:
            group, limit = entry.region or "?", sample.per_region or 0
        if limit <= 0:
            continue
        if entry.status != "included":
            chosen.append(entry)  # costs no requests; keeps mapping problems visible
        elif counts[group] < limit:
            counts[group] += 1
            chosen.append(entry)
    return chosen
