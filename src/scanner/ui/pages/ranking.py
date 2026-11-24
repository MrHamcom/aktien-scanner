"""Ranking list per profile (filled in Subphase D)."""

from __future__ import annotations

from nicegui import ui

from scanner.config import ScannerConfig
from scanner.ui.layout import empty_state, page_title


def render(config: ScannerConfig) -> None:
    page_title("Rangliste", "Beste Kandidaten je Profil, mit Faktor-Scores und Warnflaggen")
    options = {key: profile.label for key, profile in config.profiles.items()}
    with ui.row().classes("w-full items-center gap-4"):
        ui.toggle(options, value=next(iter(options))).props("unelevated rounded no-caps")
        ui.input(placeholder="Suche nach Name oder Ticker").props(
            "outlined dense clearable disable"
        ).classes("w-72")
    empty_state(
        "leaderboard",
        "Noch keine Rangliste",
        "Sobald der erste vollständige Lauf durchgelaufen ist, erscheinen hier die Ranglisten "
        "„Gesamt“ und „Dividende“ – mit Filtern nach Region, Sektor und Warnflaggen.",
    )
