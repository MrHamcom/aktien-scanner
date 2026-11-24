"""Data quality and exclusions per region (filled in Subphase C)."""

from __future__ import annotations

from nicegui import ui

from scanner.config import ScannerConfig
from scanner.ui.layout import empty_state, page_title


def render(config: ScannerConfig) -> None:
    page_title("Datenqualität", "Welche Aktien herausgefallen sind – und warum")
    with ui.row().classes("gap-2"):
        for region in config.regions:
            ui.chip(region, icon="place").props("outline color=primary")
    empty_state(
        "fact_check",
        "Noch keine Daten",
        "Nach einem Lauf siehst du hier je Region, wie viele Aktien bewertet wurden und welche "
        "wegen fehlender Daten, Größe, Handelbarkeit oder Warnsignalen ausgeschlossen wurden.",
    )
