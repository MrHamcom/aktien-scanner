"""Shared page frame: header, navigation drawer, theme."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from nicegui import app, ui

from scanner import __version__
from scanner.config import ScannerConfig

NAV_ITEMS: list[tuple[str, str, str]] = [
    ("/", "Übersicht", "space_dashboard"),
    ("/rangliste", "Rangliste", "leaderboard"),
    ("/datenqualitaet", "Datenqualität", "fact_check"),
    ("/einstellungen", "Einstellungen", "tune"),
]

CSS = """
:root { --as-radius: 14px; }
body { font-family: Inter, 'Segoe UI', system-ui, -apple-system, sans-serif; }
body.body--light { background: #f5f7fb; }
body.body--dark  { background: #0f1420; }
.as-card {
  border-radius: var(--as-radius);
  box-shadow: 0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.08);
}
.body--light .as-card { background: #ffffff; border: 1px solid #e6eaf2; }
.body--dark  .as-card { background: #161d2c; border: 1px solid #243049; }
.as-muted { opacity: .65; }
.as-kpi { font-size: 1.75rem; font-weight: 600; letter-spacing: -.01em; }
.as-nav .q-item { border-radius: 10px; margin: 2px 8px; }
.as-nav .as-active { background: rgba(59, 91, 219, .12); color: #3b5bdb; font-weight: 600; }
.body--dark .as-nav .as-active { background: rgba(116, 143, 252, .16); color: #91a7ff; }
"""


def apply_theme() -> None:
    """Colors and global styles shared by all pages."""
    ui.colors(primary="#3b5bdb", secondary="#5c7cfa", accent="#c9a227", positive="#2f9e44",
              negative="#e03131", warning="#f08c00", info="#1c7ed6")
    ui.add_css(CSS)


@contextmanager
def frame(active: str, config: ScannerConfig) -> Iterator[None]:
    """Render header and navigation, then yield the content area."""
    apply_theme()
    if "dark_mode" not in app.storage.general:
        app.storage.general["dark_mode"] = False
    dark = ui.dark_mode().bind_value(app.storage.general, "dark_mode")

    with ui.header(elevated=False).classes("items-center px-6 py-3 bg-primary"):
        ui.icon("query_stats", size="28px").classes("text-white")
        with ui.column().classes("gap-0"):
            ui.label(config.ui.title).classes("text-lg font-semibold text-white leading-tight")
            ui.label("Rangliste nach Bewertung, Qualität, Momentum und Dividende").classes(
                "text-xs text-white/75 leading-tight"
            )
        ui.space()
        ui.button(icon="dark_mode", on_click=dark.toggle).props("flat round color=white").tooltip(
            "Hell / Dunkel umschalten"
        )

    with ui.left_drawer(value=True, bordered=True).classes("as-nav pt-4").props("width=230"):
        for path, label, icon in NAV_ITEMS:
            classes = "as-active" if path == active else ""
            with ui.item(on_click=lambda p=path: ui.navigate.to(p)).classes(classes):
                with ui.item_section().props("avatar"):
                    ui.icon(icon)
                with ui.item_section():
                    ui.label(label)
        ui.space()
        with ui.column().classes("px-5 pb-4 gap-1 absolute-bottom"):
            ui.label(f"Version {__version__} · Konfiguration v{config.config_version}").classes(
                "text-xs as-muted"
            )
            ui.label("Keine Anlageberatung").classes("text-xs as-muted")

    with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-6"):
        yield


def page_title(title: str, subtitle: str) -> None:
    with ui.column().classes("gap-1"):
        ui.label(title).classes("text-2xl font-semibold")
        ui.label(subtitle).classes("as-muted")


def empty_state(icon: str, title: str, text: str) -> None:
    with ui.card().classes("as-card w-full items-center py-14 gap-2"):
        ui.icon(icon, size="48px").classes("text-primary opacity-70")
        ui.label(title).classes("text-lg font-medium")
        ui.label(text).classes("as-muted text-center max-w-lg")
