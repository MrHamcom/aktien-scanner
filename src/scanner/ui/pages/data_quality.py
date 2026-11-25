"""Data coverage per region, failure reasons and mapping problems of a run."""

from __future__ import annotations

from nicegui import ui

from scanner.config import ScannerConfig
from scanner.core import coverage, store
from scanner.core.evaluation import ExclusionReport, exclusion_report
from scanner.core.sources.base import STATEMENTS
from scanner.core.universe import scope_labels
from scanner.core.validate import RATED, STAGES
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


STAGE_LABELS = {
    "data": "Daten fehlen",
    "plausibility": "Unplausibel",
    "size": "Zu klein",
    "liquidity": "Zu wenig Umsatz",
    "share_class": "Zweite Gattung",
    "value_trap": "Value-Trap",
}
REASON_TEXT = {
    "dataset_missing": "Datensatz nicht geladen",
    "price_missing": "kein Kurs",
    "price_history_short": "Kurshistorie zu kurz",
    "price_stale": "Kurs veraltet",
    "fx_missing": "Devisenkurs fehlt",
    "market_cap_missing": "Börsenwert fehlt",
    "market_cap_mismatch": "Börsenwert passt nicht zu Kurs × Aktien",
    "shares_jump": "Aktienanzahl springt",
    "ebit_missing": "EBIT fehlt",
    "cash_missing": "Kassenbestand fehlt",
    "fcf_missing": "Free Cashflow fehlt",
    "ev_nonpositive": "Unternehmenswert ≤ 0",
    "roic_inputs_missing": "Werte für ROIC fehlen",
    "invested_capital_nonpositive": "Investiertes Kapital ≤ 0",
    "piotroski_incomplete": "Piotroski nicht berechenbar",
    "ebitda_missing": "EBITDA fehlt",
    "altman_inputs_missing": "Werte für Altman-Z fehlen",
    "dividend_implausible": "Dividendenrendite unplausibel",
    "security_type": "keine Stammaktie",
    "name_mismatch": "Name passt nicht (falscher Ticker?)",
    "statements_missing": "kein Jahresabschluss",
    "statements_stale": "Jahresabschluss veraltet",
    "market_cap_below": "Börsenwert unter Schwelle",
    "turnover_below": "Tagesumsatz unter Schwelle",
    "second_share_class": "weitere Aktiengattung",
    "negative_fcf": "Free Cashflow negativ (2 von 3 Jahren)",
    "altman_z_low": "Altman-Z unter Schwelle",
    "dilution": "Verwässerung über Schwelle",
}
FLAG_TEXT = {
    "dividend_cut": "Dividende gekürzt",
    "dividend_suspended": "Dividende ausgesetzt",
    "dividend_yield_high": "Dividendenrendite über 10 %",
    "dividend_not_covered": "Dividende nicht durch Free Cashflow gedeckt",
    "dividend_share_funded": "Aktienanzahl steigt trotz Dividende",
    "dividend_history_short": "Dividendenhistorie kurz",
    "debt_row_missing": "keine Schulden-Zeile (als 0 gewertet)",
    "fcf_history_short": "Free-Cashflow-Historie kürzer als 3 Jahre",
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

    report = exclusion_report(selected)
    with ui.tabs().props("dense no-caps align=left active-color=primary indicator-color=primary"
                         ).classes("w-full") as tabs:
        tab_eval = ui.tab("Bewertung & Ausschlüsse", icon="filter_alt")
        tab_load = ui.tab("Datenabruf", icon="cloud_download")
    with ui.tab_panels(tabs, value=tab_eval if report else tab_load).props(
        "animated keep-alive"
    ).classes("w-full bg-transparent"):
        with ui.tab_panel(tab_eval).classes("p-0 gap-4"):
            _evaluation_section(report)
        with ui.tab_panel(tab_load).classes("p-0 gap-4"):
            _loading_section(selected)


def _evaluation_section(report: ExclusionReport | None) -> None:
    if report is None:
        empty_state(
            "filter_alt",
            "Noch nicht bewertet",
            "Dieser Lauf wurde vor Subphase C geladen. Starte einen neuen Lauf – die Daten "
            "kommen aus dem Zwischenspeicher, danach werden die Kennzahlen berechnet.",
        )
        return
    total = report.total
    queried = sum(total.values())
    rated = total[RATED]
    with ui.grid(columns="repeat(auto-fit, minmax(220px, 1fr))").classes("w-full gap-4"):
        for icon, label, value, caption in (
            ("inventory_2", "Abgefragt", fmt.number(queried), "Aktien mit Daten-Abruf"),
            ("verified", "Bewertbar", fmt.number(rated),
             f"{fmt.percent(rated / queried if queried else None)} der abgefragten"),
            ("block", "Ausgeschlossen", fmt.number(queried - rated), "mit Grund protokolliert"),
        ):
            with ui.card().classes("as-card p-5 gap-1"):
                with ui.row().classes("items-center gap-2 as-muted"):
                    ui.icon(icon, size="20px")
                    ui.label(label).classes("text-sm")
                ui.label(value).classes("as-kpi")
                ui.label(caption).classes("text-xs as-muted")

    columns = [{"name": "region", "label": "Region", "field": "region", "align": "left"},
               {"name": "queried", "label": "Abgefragt", "field": "queried"}]
    columns += [{"name": st, "label": STAGE_LABELS[st], "field": st} for st in STAGES]
    columns += [{"name": "rated", "label": "Bewertbar", "field": "rated",
                 "classes": "font-medium", "headerClasses": "font-medium"}]
    rows = []
    for region, counts in [*report.regions.items(), ("Gesamt", total)]:
        n = sum(counts.values())
        rows.append({"region": region, "queried": fmt.number(n),
                     **{st: fmt.number(counts[st]) if counts[st] else "–" for st in STAGES},
                     "rated": f"{fmt.number(counts[RATED])} ({fmt.percent(counts[RATED] / n)})"})
    with ui.card().classes("as-card w-full p-0"):
        with ui.column().classes("px-6 pt-5 gap-1"):
            ui.label("Ausschlüsse je Region").classes("text-lg font-medium")
            ui.label("Stufen von links nach rechts: Jede Aktie zählt bei der ersten Stufe, an "
                     "der sie scheitert.").classes("text-sm as-muted")
        ui.table(columns=columns, rows=rows, row_key="region").props(
            "flat dense separator=horizontal"
        ).classes("w-full px-4 pb-4")

    if report.reasons:
        with ui.card().classes("as-card w-full p-0"):
            ui.label("Gründe").classes("text-lg font-medium px-6 pt-5")
            ui.table(
                columns=[
                    {"name": "stage", "label": "Stufe", "field": "stage", "align": "left"},
                    {"name": "reason", "label": "Grund", "field": "reason", "align": "left"},
                    {"name": "count", "label": "Anzahl", "field": "count"},
                    {"name": "examples", "label": "Beispiele", "field": "examples",
                     "align": "left"},
                ],
                rows=[
                    {"id": f"{stage}:{reason}", "stage": STAGE_LABELS.get(stage, stage),
                     "reason": REASON_TEXT.get(reason, reason), "count": fmt.number(count),
                     "examples": ", ".join(keys[:5]) + (" …" if len(keys) > 5 else "")}
                    for stage, reason, count, keys in report.reasons
                ],
                row_key="id",
            ).props("flat dense separator=horizontal").classes("w-full px-4 pb-4")
            with ui.expansion("Alle betroffenen Ticker (zum Kopieren)", icon="list").classes(
                "w-full px-4 pb-2"
            ):
                text = "\n".join(
                    f"{STAGE_LABELS.get(stage, stage)} – {REASON_TEXT.get(reason, reason)}: "
                    f"{', '.join(keys)}"
                    for stage, reason, _count, keys in report.reasons
                )
                ui.textarea(value=text).props("readonly outlined autogrow").classes(
                    "w-full font-mono text-xs"
                )

    if report.flags:
        with ui.card().classes("as-card w-full p-6 gap-2"):
            ui.label("Warnhinweise bei bewertbaren Aktien").classes("text-lg font-medium")
            ui.label("Kein Ausschluss – wird in der Rangliste angezeigt; das Profil „Dividende“ "
                     "schließt Dividendenfallen aus.").classes("text-sm as-muted")
            for flag, count in report.flags.most_common():
                with ui.row().classes("w-full justify-between no-wrap"):
                    ui.label(FLAG_TEXT.get(flag, flag))
                    ui.label(fmt.number(count)).classes("as-muted")


def _loading_section(selected: int) -> None:
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
