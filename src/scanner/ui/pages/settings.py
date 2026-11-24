"""Read-only view of the active configuration."""

from __future__ import annotations

from nicegui import ui

from scanner.config import FACTORS, ScannerConfig
from scanner.paths import config_path
from scanner.ui.layout import page_title

FACTOR_LABELS = {
    "value": "Bewertung",
    "quality": "Qualität",
    "momentum": "Momentum",
    "dividend": "Dividende",
}
NON_PAYER_LABELS = {
    "redistribute": "Gewicht auf übrige Faktoren verteilt",
    "lowest": "niedrigster Dividenden-Score",
    "exclude": "ausgeschlossen",
}


def _row(label: str, value: str) -> None:
    with ui.row().classes("w-full justify-between items-baseline no-wrap gap-4 py-1"):
        ui.label(label).classes("as-muted shrink-0")
        ui.label(value).classes("font-medium text-right")


def render(config: ScannerConfig) -> None:
    page_title("Einstellungen", "Aktive Regeln und Gewichte – nur zur Ansicht")

    with ui.card().classes("as-card w-full p-4"):
        with ui.row().classes("w-full items-center no-wrap gap-3"):
            ui.icon("lock", size="22px").classes("text-warning shrink-0")
            ui.label(
                "Die Regeln werden bewusst nicht in der Oberfläche geändert. Jede Änderung startet "
                "die Zählung im Vorwärtstest neu und erfolgt über eine neue Konfigurationsversion."
            ).classes("text-sm")

    with ui.grid(columns="repeat(auto-fit, minmax(320px, 1fr))").classes("w-full gap-4"):
        for profile in config.profiles.values():
            with ui.card().classes("as-card p-6 gap-3"):
                ui.label(f"Profil „{profile.label}“").classes("text-lg font-medium")
                for factor in FACTORS:
                    weight = profile.weights[factor]
                    with ui.column().classes("w-full gap-1"):
                        with ui.row().classes("w-full justify-between"):
                            ui.label(FACTOR_LABELS[factor])
                            ui.label(f"{weight:.0f} %").classes("font-medium")
                        ui.linear_progress(value=weight / 100, show_value=False).props(
                            "rounded size=8px"
                        )
                ui.separator()
                _row("Ohne Dividende", NON_PAYER_LABELS[profile.non_payer_dividend])
                if profile.min_years_without_cut:
                    _row("Jahre ohne Kürzung", f"≥ {profile.min_years_without_cut}")
                if profile.exclude_dividend_traps:
                    _row("Dividendenfallen", "ausgeschlossen")

        rule = config.universe_rule
        with ui.card().classes("as-card p-6 gap-1"):
            ui.label("Universum-Regel").classes("text-lg font-medium mb-2")
            _row("Startliste", f"{config.start_list.etf} (MSCI ACWI)")
            _row("Mindest-Börsenwert", f"{rule.min_market_cap_eur / 1e9:.0f} Mrd. €")
            _row(
                f"Ø-Tagesumsatz ({rule.avg_daily_value_window_days} Tage)",
                f"≥ {rule.min_avg_daily_value_eur / 1e6:.0f} Mio. €",
            )
            _row("Ausgeschlossene Sektoren", ", ".join(rule.excluded_sectors))
            _row("Vergleichsgruppe", "Sektor × Region")
            _row("Mindestgröße Gruppe", f"{config.ranking.min_peer_group_size} Titel")

        traps = config.value_trap_filters
        with ui.card().classes("as-card p-6 gap-1"):
            ui.label("Warnsignale").classes("text-lg font-medium mb-2")
            _row("Negativer Free Cashflow", f"in {traps.negative_fcf_years_of_last_3} von 3 Jahren")
            _row("Altman-Z unter", f"{traps.min_altman_z:.1f}")
            _row("Verwässerung über", f"{traps.max_share_dilution_12m:.0%} in 12 Monaten")
            _row("Dividendenrendite über", f"{config.dividend.trap_yield_above:.0%}")

        with ui.card().classes("as-card p-6 gap-1"):
            ui.label("Betrieb").classes("text-lg font-medium mb-2")
            _row("Datenquelle", config.data_source.provider)
            ds = config.data_source
            _row("Abrufe pro Minute (max.)", str(ds.max_requests_per_minute))
            _row("Wiederholungen bei Sperre", f"{ds.max_retries}× ab {ds.retry_base_seconds} s")
            _row("Kurse/Stammdaten neu nach",
                 f"{ds.refresh.history_hours} h / {ds.refresh.info_days} Tagen")
            _row("Abschlüsse neu nach", f"{ds.refresh.statements_days} Tagen")
            _row("Rhythmus", "manuell" if config.schedule.mode == "manual" else "monatlich")
            _row("Konfigurationsversion", str(config.config_version))
            ui.label(str(config_path())).classes("text-xs as-muted mt-2 break-all")

    with ui.expansion("Regionen (Vergleichsgruppen)", icon="public").classes("as-card w-full"):
        with ui.column().classes("p-4 gap-2"):
            for region, countries in config.regions.items():
                _row(region, ", ".join(countries))
