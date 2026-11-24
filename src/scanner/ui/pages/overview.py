"""Overview: last run, key figures, start/cancel/resume with live progress."""

from __future__ import annotations

from nicegui import ui

from scanner.config import ScannerConfig
from scanner.core import store
from scanner.core.jobs import JobManager
from scanner.core.sources.base import DATASETS
from scanner.core.universe import FULL_SCOPE, scope_labels
from scanner.ui import format as fmt
from scanner.ui.layout import page_title

STATUS_LABELS = {
    "running": "läuft",
    "finished": "abgeschlossen",
    "failed": "gestoppt",
    "cancelled": "abgebrochen",
}
FULL_SCOPE_ESTIMATE = 2000  # included stocks expected in a full run (start list minus exclusions)


def _kpi(icon: str, label: str, value: str, caption: str) -> None:
    with ui.card().classes("as-card p-5 gap-1"):
        with ui.row().classes("items-center gap-2 as-muted"):
            ui.icon(icon, size="20px")
            ui.label(label).classes("text-sm")
        ui.label(value).classes("as-kpi")
        ui.label(caption).classes("text-xs as-muted")


def _scope_size(config: ScannerConfig, scope: str) -> int:
    if scope == FULL_SCOPE:
        return FULL_SCOPE_ESTIMATE
    sample = config.ramp_up[scope]
    if sample.per_country:
        return sum(sample.per_country.values())
    return (sample.per_region or 0) * len(config.regions)


def _estimate(config: ScannerConfig, scope: str) -> str:
    requests = _scope_size(config, scope) * len(DATASETS)
    minutes = requests / config.data_source.max_requests_per_minute
    text = fmt.duration(minutes * 60)
    return f"ca. {text}" + (" – am besten über Nacht" if minutes > 90 else "")


def render(config: ScannerConfig, jobs: JobManager) -> None:
    page_title("Übersicht", "Stand des letzten Laufs und Start eines neuen Laufs")
    labels = scope_labels(config)
    state = {"running": jobs.running, "scope": next(iter(labels))}

    @ui.refreshable
    def kpis() -> None:
        run = store.latest_run()
        with ui.grid(columns="repeat(auto-fit, minmax(220px, 1fr))").classes("w-full gap-4"):
            if run is None:
                _kpi("history", "Letzter Lauf", "–", "Noch kein Lauf durchgeführt")
                _kpi("task_alt", "Vollständig geladen", "–", "Aktien mit allen Datensätzen")
            else:
                scope = labels.get(run.scope or "", run.scope or "")
                _kpi("history", "Letzter Lauf", fmt.timestamp(run.started_at),
                     f"{STATUS_LABELS.get(run.status, run.status)} · {scope}")
                queried = sum(1 for e in store.get_start_list(run.id) if e.status == "included")
                _kpi("task_alt", "Vollständig geladen", fmt.number(run.rated_count),
                     f"von {fmt.number(queried)} abgefragten Aktien" if queried
                     else "Startliste nicht geladen")
            _kpi("public", "Startliste", config.start_list.etf, "Welt-ETF (MSCI ACWI)")
            _kpi("cloud_download", "Datenquelle", config.data_source.provider,
                 f"max. {config.data_source.max_requests_per_minute} Abrufe pro Minute")

    @ui.refreshable
    def run_card() -> None:
        with ui.card().classes("as-card w-full p-6 gap-3"):
            if jobs.running:
                _running_view()
            else:
                _idle_view()

    def _running_view() -> None:
        p = jobs.progress
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            with ui.column().classes("gap-1"):
                phase = ui.label(p.phase).classes("text-lg font-medium")
                current = ui.label("").classes("as-muted")
            ui.button("Abbrechen", icon="stop", on_click=jobs.cancel).props(
                "outline no-caps color=negative"
            )
        bar = ui.linear_progress(value=0, show_value=False).props("rounded size=10px")
        with ui.row().classes("w-full justify-between text-sm"):
            counts = ui.label("")
            eta = ui.label("").classes("as-muted")
        message = ui.label("").classes("text-sm as-muted")

        def update() -> None:
            phase.text = p.phase
            current.text = p.current
            bar.value = p.fraction
            counts.text = (f"{fmt.number(p.done)} / {fmt.number(p.total)} · "
                           f"{fmt.number(p.requests)} Abrufe · {fmt.number(p.failures)} Lücken")
            eta.text = f"Restzeit {fmt.duration(p.eta_seconds())}"
            message.text = p.message

        update()
        ui.timer(1.0, update)

    def _idle_view() -> None:
        run = store.latest_run()
        with ui.row().classes("w-full items-start justify-between gap-6"):
            with ui.column().classes("gap-1 flex-1"):
                ui.label("Neuer Lauf").classes("text-lg font-medium")
                ui.label(
                    "Lädt die Startliste und holt Kurse, Dividenden, Stammdaten und Abschlüsse. "
                    "Bereits geladene, aktuelle Daten werden wiederverwendet."
                ).classes("as-muted")
            start = ui.button("Lauf starten", icon="play_arrow",
                              on_click=lambda: _start(state["scope"])).props(
                "unelevated no-caps size=lg"
            )
        toggle = ui.toggle(labels, value=state["scope"]).props("unelevated rounded no-caps")
        hint = ui.label(f"Dauer {_estimate(config, state['scope'])}").classes("text-sm as-muted")

        def on_scope(e) -> None:
            state["scope"] = e.value
            hint.text = f"Dauer {_estimate(config, e.value)}"

        toggle.on_value_change(on_scope)
        start.bind_enabled_from(toggle, "value", backward=bool)

        if jobs.error:
            ui.label(f"Letzter Fehler: {jobs.error}").classes("text-sm text-negative")
        if run and run.status in {"cancelled", "failed"} and run.total_items:
            with ui.row().classes("w-full items-center no-wrap gap-4 mt-2 p-3 rounded-lg").style(
                "background: rgba(245,158,11,.10); border: 1px solid rgba(245,158,11,.35)"
            ):
                ui.icon("pause_circle", size="24px").classes("text-warning shrink-0")
                ui.label(
                    f"Lauf {run.id}: {fmt.number(run.done_items)} von "
                    f"{fmt.number(run.total_items)} Schritten erledigt. {run.note or ''}"
                ).classes("text-sm flex-1")
                ui.button("Fortsetzen", icon="replay",
                          on_click=lambda: _resume(run.id)).props("outline no-caps")

    def _start(scope: str) -> None:
        if jobs.start(scope):
            ui.notify(f"Lauf gestartet: {labels[scope]}", type="positive")
        else:
            ui.notify("Es läuft bereits ein Lauf", type="warning")
        _sync()

    def _resume(run_id: int) -> None:
        if jobs.resume(run_id):
            ui.notify(f"Lauf {run_id} wird fortgesetzt", type="positive")
        _sync()

    def _sync() -> None:
        state["running"] = jobs.running
        run_card.refresh()
        kpis.refresh()

    def watch() -> None:
        if jobs.running != state["running"]:
            finished = state["running"] and not jobs.running
            _sync()
            if finished:
                ui.notify(f"Lauf beendet: {jobs.progress.message}",
                          type="negative" if jobs.error else "info", timeout=10000)

    kpis()
    run_card()
    ui.timer(1.0, watch)

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
