"""Data coverage per region, failure reasons and mapping problems of a run."""

from __future__ import annotations

from nicegui import ui

from scanner.config import ScannerConfig
from scanner.core import coverage, store
from scanner.core.sources.base import STATEMENTS
from scanner.core.universe import scope_labels
from scanner.ui import format as fmt
from scanner.ui.layout import empty_state, page_title

PRICE_TARGET = 0.95       # Subphase B: price data for >= 95 % of the start list
FUNDAMENTAL_TARGET = 0.80  # Subphase B: statements and dividends for >= 80 %

REASON_LABELS = {
    "no_data": "keine Daten bei der Quelle",
    "ticker_not_found": "Ticker bei der Quelle unbekannt",
    "rate_limited": "Abrufsperre",
    "transient": "Verbindungsproblem",
    "error": "unerwarteter Fehler",
}
DATASET_LABELS = {
    "history": "Kurse/Dividenden",
    "info": "Stammdaten",
    "income": "GuV",
    "balance": "Bilanz",
    "cashflow": "Cashflow",
    "fx": "Devisenkurs",
}


def _reason_text(label: str) -> str:
    dataset, _, reason = label.partition(": ")
    return f"{DATASET_LABELS.get(dataset, dataset)} – {REASON_LABELS.get(reason, reason)}"


def _criterion(ok: bool, text: str, value: str) -> None:
    with ui.row().classes("w-full items-center no-wrap gap-3 py-1"):
        ui.icon("check_circle" if ok else "radio_button_unchecked", size="22px").classes(
            "text-positive" if ok else "text-warning"
        )
        ui.label(text).classes("flex-1")
        ui.label(value).classes("font-medium")


def _statements_share(cov: coverage.RegionCoverage) -> float | None:
    if not cov.included:
        return None
    return min(cov.loaded[s] for s in STATEMENTS) / cov.included


def render(config: ScannerConfig, run_id: int | None = None) -> None:
    page_title("Datenqualität", "Wie vollständig die Daten je Region sind – und was fehlt")
    runs = [r for r in store.list_runs(limit=30) if r.total_items]
    if not runs:
        empty_state(
            "fact_check",
            "Noch keine Daten",
            "Nach dem ersten Lauf siehst du hier je Region, für wie viele Aktien Kurse, "
            "Dividenden, Stammdaten und Abschlüsse geladen wurden – und warum etwas fehlt.",
        )
        return

    selected = run_id if any(r.id == run_id for r in runs) else runs[0].id
    labels = scope_labels(config)
    options = {
        r.id: f"Lauf {r.id} · {fmt.timestamp(r.started_at)} · {labels.get(r.scope or '', '')}"
        for r in runs
    }
    ui.select(options, value=selected, label="Lauf",
              on_change=lambda e: ui.navigate.to(f"/datenqualitaet?run={e.value}")).props(
        "outlined dense"
    ).classes("w-96")

    cov = coverage.compute(selected)
    total = cov.total
    price_share = total.share("history")
    fund_share = _statements_share(total)

    with ui.grid(columns="repeat(auto-fit, minmax(320px, 1fr))").classes("w-full gap-4"):
        with ui.card().classes("as-card p-6 gap-1"):
            ui.label("Abschlusskriterien Subphase B").classes("text-lg font-medium mb-2")
            _criterion((price_share or 0) >= PRICE_TARGET,
                       f"Kurse für ≥ {PRICE_TARGET:.0%} der Aktien", fmt.percent(price_share))
            _criterion((fund_share or 0) >= FUNDAMENTAL_TARGET,
                       f"Abschlüsse für ≥ {FUNDAMENTAL_TARGET:.0%} der Aktien",
                       fmt.percent(fund_share))
            _criterion(not cov.unmapped_exchanges, "Alle Börsen zugeordnet",
                       fmt.number(sum(n for _e, n in cov.unmapped_exchanges)) + " offen")
            _criterion(not cov.fx_failed, "Alle Devisenkurse geladen",
                       fmt.number(len(cov.fx_failed)) + " fehlen")
        with ui.card().classes("as-card p-6 gap-1"):
            ui.label("Umfang").classes("text-lg font-medium mb-2")
            for label, value in (
                ("Positionen in diesem Lauf", total.listed),
                ("davon ausgeschlossen (Sektor, nicht handelbar)", total.excluded),
                ("davon ohne Börsen-Zuordnung", total.unmapped),
                ("abgefragt", total.included),
                ("vollständig geladen", total.complete),
            ):
                with ui.row().classes("w-full justify-between no-wrap py-1"):
                    ui.label(label).classes("as-muted")
                    ui.label(fmt.number(value)).classes("font-medium")

    columns = [
        {"name": "region", "label": "Region", "field": "region", "align": "left"},
        {"name": "included", "label": "Abgefragt", "field": "included"},
        {"name": "history", "label": "Kurse/Dividenden", "field": "history"},
        {"name": "info", "label": "Stammdaten", "field": "info"},
        {"name": "income", "label": "GuV", "field": "income"},
        {"name": "balance", "label": "Bilanz", "field": "balance"},
        {"name": "cashflow", "label": "Cashflow", "field": "cashflow"},
        {"name": "complete", "label": "Vollständig", "field": "complete"},
    ]
    rows = [
        {
            "region": r.region,
            "included": fmt.number(r.included),
            **{d: fmt.percent(r.share(d)) for d in ("history", "info", *STATEMENTS)},
            "complete": fmt.percent(r.complete_share),
        }
        for r in [*cov.regions, total]
        if r.included or r is total
    ]
    with ui.card().classes("as-card w-full p-0"):
        ui.label("Abdeckung je Region").classes("text-lg font-medium px-6 pt-5")
        ui.table(columns=columns, rows=rows, row_key="region").props(
            "flat dense separator=horizontal"
        ).classes("w-full px-4 pb-4")

    if cov.failure_reasons:
        with ui.card().classes("as-card w-full p-0"):
            ui.label("Was fehlt – und warum").classes("text-lg font-medium px-6 pt-5")
            ui.table(
                columns=[
                    {"name": "reason", "label": "Grund", "field": "reason", "align": "left"},
                    {"name": "count", "label": "Anzahl", "field": "count"},
                    {"name": "examples", "label": "Beispiele", "field": "examples",
                     "align": "left"},
                ],
                rows=[
                    {"reason": _reason_text(label), "count": fmt.number(count),
                     "examples": ", ".join(examples[:5]) + (" …" if len(examples) > 5 else "")}
                    for label, count, examples in cov.failure_reasons
                ],
                row_key="reason",
            ).props("flat dense separator=horizontal").classes("w-full px-4 pb-4")
            with ui.expansion("Alle betroffenen Ticker (zum Kopieren)", icon="list").classes(
                "w-full px-4 pb-2"
            ):
                text = "\n".join(
                    f"{_reason_text(label)}: {', '.join(examples)}"
                    for label, _count, examples in cov.failure_reasons
                )
                ui.textarea(value=text).props("readonly outlined autogrow").classes(
                    "w-full font-mono text-xs"
                )

    if cov.unmapped_exchanges:
        with ui.card().classes("as-card w-full p-6 gap-2"):
            ui.label("Börsen ohne Zuordnung").classes("text-lg font-medium")
            ui.label(
                "Diese Börsennamen aus der Startliste sind in config/exchanges.yaml noch nicht "
                "erfasst. Die Aktien wurden deshalb nicht abgefragt."
            ).classes("as-muted text-sm")
            for exchange, count in cov.unmapped_exchanges:
                with ui.row().classes("w-full justify-between no-wrap"):
                    ui.label(exchange)
                    ui.label(f"{fmt.number(count)} {'Aktie' if count == 1 else 'Aktien'}").classes(
                        "as-muted"
                    )
