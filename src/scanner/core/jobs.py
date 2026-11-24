"""Runs a scan in a background thread so the user interface stays responsive."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable

from scanner.config import ScannerConfig
from scanner.core.pipeline import Progress, ScanRun
from scanner.core.sources.base import MarketDataSource

log = logging.getLogger(__name__)


def default_source() -> MarketDataSource:
    """Yahoo in normal operation; an offline fake for tests/demo (SCANNER_FAKE_SOURCE=1)."""
    if os.environ.get("SCANNER_FAKE_SOURCE") == "1":
        from scanner.core.sources.fake import FakeSource

        return FakeSource(delay=float(os.environ.get("SCANNER_FAKE_DELAY", "0.05")))
    from scanner.core.sources.yahoo import YahooSource

    return YahooSource()


class JobManager:
    """At most one scan at a time. Thread-safe enough for a single local user."""

    def __init__(
        self,
        config: ScannerConfig,
        source_factory: Callable[[], MarketDataSource] = default_source,
        run_factory: Callable[..., ScanRun] = ScanRun,
    ) -> None:
        self.config = config
        self.source_factory = source_factory
        self.run_factory = run_factory
        self.progress = Progress()
        self.error: str | None = None
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, scope: str) -> bool:
        return self._launch(lambda run: run.start(scope))

    def resume(self, run_id: int) -> bool:
        return self._launch(lambda run: run.resume(run_id))

    def cancel(self) -> None:
        self._cancel.set()
        self.progress.message = "Wird abgebrochen …"

    def _launch(self, action: Callable[[ScanRun], int]) -> bool:
        with self._lock:
            if self.running:
                return False
            self._cancel = threading.Event()
            self.progress = Progress(phase="Start")
            self.error = None
            run = self.run_factory(
                self.config, self.source_factory(), progress=self.progress, cancel=self._cancel
            )

            def target() -> None:
                try:
                    action(run)
                except Exception as exc:  # noqa: BLE001 – shown in the UI
                    log.exception("scan failed")
                    self.error = str(exc)
                    self.progress.phase = "Fehlgeschlagen"
                    self.progress.message = str(exc)

            self._thread = threading.Thread(target=target, name="scan", daemon=True)
            self._thread.start()
            return True
