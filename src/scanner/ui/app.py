"""Entry point of the user interface: `aktien-scanner`."""

from __future__ import annotations

import logging
import sys

from nicegui import ui

from scanner.config import ConfigError, ScannerConfig, load_config, load_exchanges
from scanner.core import store
from scanner.core.jobs import JobManager
from scanner.ui.layout import frame
from scanner.ui.pages import data_quality, overview, ranking, settings


def register_pages(config: ScannerConfig, jobs: JobManager) -> None:
    """Register all routes. Kept separate from main() so tests can import it."""

    @ui.page("/")
    def _overview() -> None:
        with frame("/", config):
            overview.render(config, jobs)

    @ui.page("/rangliste")
    def _ranking() -> None:
        with frame("/rangliste", config):
            ranking.render(config)

    @ui.page("/datenqualitaet")
    def _data_quality(run: int | None = None) -> None:
        with frame("/datenqualitaet", config):
            data_quality.render(config, run)

    @ui.page("/einstellungen")
    def _settings() -> None:
        with frame("/einstellungen", config):
            settings.render(config)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config()
        load_exchanges(config)
    except ConfigError as exc:
        # fail closed: do not start with an invalid configuration
        print(exc, file=sys.stderr)
        sys.exit(1)
    store.mark_stale_runs()  # runs interrupted by closing the program can be resumed
    jobs = JobManager(config)
    register_pages(config, jobs)
    ui.run(
        host=config.ui.host,
        port=config.ui.port,
        title=config.ui.title,
        favicon="📈",
        language="de",
        show=False,
        reload=False,
        show_welcome_message=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
