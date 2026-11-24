"""Overview: last run, key figures, start button."""

from __future__ import annotations

from nicegui import ui

from scanner.config import ScannerConfig
from scanner.core.store import latest_run
from scanner.ui.layout import page_title

STATUS_LABELS = {
    "running": "läuft",
    "finished": "abgeschlossen",
    "failed": "fehlgeschlagen",
    "cancelled": "abgebrochen",
}


def _kpi(icon: str, label: str, value: str, caption: str) -> None:
    with ui.card().classes("as-card p-5 gap-1"):
        with ui.row().classes("items-center gap-2 as-muted"):
            ui.icon(icon, size="20px")
            ui.label(label).classes("text-sm")
        ui.label(value).classes("as-kpi")
        ui.label(caption).classes("text-xs as-muted")


def render(config: ScannerConfig) -> None:
    page_title("Übersicht", "Stand des letzten Laufs und Start eines neuen Laufs")
    run = latest_run()

    with ui.grid(columns="repeat(auto-fit, minmax(220px, 1fr))").classes("w-full gap-4"):
        if run is None:
            _kpi("history", "Letzter Lauf", "–", "Noch kein Lauf durchgeführt")
            _kpi("format_list_numbered", "Bewertete Aktien", "–", "Ergebnis des letzten Laufs")
        else:
            when = run.started_at.astimezone().strftime("%d.%m.%Y %H:%M")
            _kpi("history", "Letzter Lauf", when, STATUS_LABELS.get(run.status, run.status))
            rated = f"{run.rated_count:,}".replace(",", ".") if run.rated_count is not None else "–"
            listed = run.start_list_size or 0
            caption = f"von {listed} in der Startliste"
            _kpi("format_list_numbered", "Bewertete Aktien", rated, caption)
        _kpi("public", "Startliste", config.start_list.etf, "Welt-ETF (MSCI ACWI)")
        _kpi("cloud_download", "Datenquelle", config.data_source.provider, "Kurse und Kennzahlen")

    with ui.card().classes("as-card w-full p-6"):
        with ui.row().classes("w-full items-center justify-between gap-4"):
            with ui.column().classes("gap-1"):
                ui.label("Neuer Lauf").classes("text-lg font-medium")
                ui.label(
                    "Lädt die Startliste, holt Kurse und Kennzahlen und erstellt die Ranglisten."
                ).classes("as-muted")
            button = ui.button("Neuen Lauf starten", icon="play_arrow").props(
                "unelevated no-caps size=lg"
            )
            button.disable()
            button.tooltip("Verfügbar ab Subphase B")
        ui.linear_progress(value=0, show_value=False).props("rounded size=8px").classes("mt-4")
        ui.label("Bereit – die Datenanbindung folgt in Subphase B.").classes("text-xs as-muted")

    rule = config.universe_rule
    with ui.card().classes("as-card w-full p-6 gap-2"):
        ui.label("Wer wird bewertet?").classes("text-lg font-medium")
        ui.label(
            "Keine feste Anzahl: bewertet wird jede Aktie der Startliste, die alle Bedingungen "
            "erfüllt und für die vollständige Daten vorliegen."
        ).classes("as-muted")
        with ui.row().classes("gap-2 mt-2"):
            for text in (
                f"Börsenwert ≥ {rule.min_market_cap_eur / 1e9:.0f} Mrd. €",
                f"Ø-Tagesumsatz ≥ {rule.min_avg_daily_value_eur / 1e6:.0f} Mio. €",
                "nur Stammaktien",
                "ohne " + " / ".join(rule.excluded_sectors),
                "Daten vollständig",
            ):
                ui.badge(text).props("outline rounded color=primary").classes("px-3 py-1 text-sm")
