"""Data loading run: start list -> FX rates -> per-stock datasets, with cache and resume.

Fail closed: every missing dataset is recorded with a reason; nothing is filled in or guessed.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from scanner.config import ScannerConfig, load_exchanges
from scanner.core import store
from scanner.core.evaluation import EvaluationSummary, evaluate_run, needed_fx_pairs
from scanner.core.metrics.inputs import fx_pair
from scanner.core.sources.base import (
    DATASETS,
    STATEMENTS,
    MarketDataSource,
    NoData,
    RateLimited,
    SourceError,
)
from scanner.core.throttle import Cancelled, Fetcher, RateLimiter
from scanner.core.universe import (
    build_start_list,
    fetch_holdings_text,
    parse_ishares_csv,
    scope_labels,
    select_scope,
)


class RunAborted(Exception):
    """Stopped because the source kept refusing requests; the run can be resumed later."""


@dataclass
class Progress:
    """Live state of a run, read by the user interface."""

    run_id: int | None = None
    phase: str = "Bereit"
    total: int = 0
    done: int = 0
    current: str = ""
    message: str = ""
    requests: int = 0
    started: float = field(default_factory=time.monotonic)
    failures: int = 0

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0

    def eta_seconds(self) -> float | None:
        if self.done == 0 or self.total == 0:
            return None
        elapsed = time.monotonic() - self.started
        return elapsed / self.done * (self.total - self.done)


def _max_age(config: ScannerConfig, dataset: str) -> timedelta:
    refresh = config.data_source.refresh
    if dataset == "history":
        return timedelta(hours=refresh.history_hours)
    if dataset == "info":
        return timedelta(days=refresh.info_days)
    if dataset in STATEMENTS:
        return timedelta(days=refresh.statements_days)
    if dataset == "fx":
        return timedelta(hours=refresh.fx_hours)
    raise ValueError(dataset)


class ScanRun:
    """One data loading run. Use `start()` for a new run or `resume(run_id)`."""

    def __init__(
        self,
        config: ScannerConfig,
        source: MarketDataSource,
        progress: Progress | None = None,
        cancel: threading.Event | None = None,
        db_path: Path | None = None,
        holdings_loader: Callable[[ScannerConfig], tuple[str, str]] = fetch_holdings_text,
        sleep: Callable[[float, threading.Event | None], None] | None = None,
    ) -> None:
        self.config = config
        self.source = source
        self.progress = progress or Progress()
        self.cancel = cancel or threading.Event()
        self.db = db_path
        self.holdings_loader = holdings_loader
        ds = config.data_source
        fetcher_kwargs: dict[str, Any] = {}
        if sleep is not None:
            fetcher_kwargs["sleep"] = sleep
        self.fetcher = Fetcher(
            RateLimiter(ds.max_requests_per_minute),
            max_retries=ds.max_retries,
            retry_base_seconds=ds.retry_base_seconds,
            transient_retries=ds.transient_retries,
            transient_retry_base_seconds=ds.transient_retry_base_seconds,
            cancel=self.cancel,
            on_wait=self._on_wait,
            **fetcher_kwargs,
        )
        self.consecutive_rate_limits = 0

    # --- public ---------------------------------------------------------------------------

    def start(self, scope: str) -> int:
        """Create a new run, load the start list and fetch all data."""
        if scope not in scope_labels(self.config):
            raise ValueError(f"unknown scope: {scope}")
        run_id = store.start_run(self.config.config_version, scope=scope, db_path=self.db)
        self.progress.run_id = run_id
        try:
            self._set_phase("Startliste laden")
            text, origin = self.holdings_loader(self.config)
            holdings = parse_ishares_csv(text)
            entries = build_start_list(holdings, self.config, load_exchanges(self.config))
            entries = select_scope(entries, scope, self.config)
            store.save_start_list(run_id, entries, db_path=self.db)
            self.progress.message = f"{len(entries)} Positionen aus {origin}"
        except Exception as exc:
            store.finish_run(run_id, "failed", note=f"Startliste: {exc}", db_path=self.db)
            self._set_phase("Fehlgeschlagen", str(exc))
            raise
        return self._execute(run_id)

    def resume(self, run_id: int) -> int:
        """Continue a cancelled or failed run; completed items are skipped."""
        run = store.get_run(run_id, db_path=self.db)
        if run is None:
            raise ValueError(f"run {run_id} not found")
        if not store.get_start_list(run_id, db_path=self.db):
            raise ValueError("Lauf hat keine Startliste und kann nicht fortgesetzt werden")
        store.reopen_run(run_id, db_path=self.db)
        self.progress.run_id = run_id
        return self._execute(run_id)

    # --- internals ------------------------------------------------------------------------

    def _on_wait(self, message: str) -> None:
        self.progress.message = message

    def _set_phase(self, phase: str, message: str = "") -> None:
        self.progress.phase = phase
        if message:
            self.progress.message = message

    def _execute(self, run_id: int) -> int:
        entries = store.get_start_list(run_id, db_path=self.db)
        included = [e for e in entries if e.status == "included" and e.yahoo_ticker]
        completed = store.completed_items(run_id, db_path=self.db)
        currencies = sorted({e.currency for e in included if e.currency})
        pairs = sorted({p for c in currencies if (p := fx_pair(c))})

        self.progress.total = len(included) + len(pairs)
        self.progress.done = 0
        self.progress.started = time.monotonic()
        try:
            self._set_phase("Devisenkurse laden")
            for pair in pairs:
                if (pair, "fx") not in completed:
                    self._load(run_id, pair, "fx", lambda p=pair: self.source.fx_history(
                        p, self.config.data_source.history_price_days))
                self._tick(run_id)

            self._set_phase("Aktiendaten laden")
            for entry in included:
                ticker = entry.yahoo_ticker or ""
                self.progress.current = f"{ticker} – {entry.name}"
                self._load_stock(run_id, ticker, completed)
                self._tick(run_id)
            self._load_financial_fx(run_id, included)
        except Cancelled:
            store.finish_run(run_id, "cancelled", start_list_size=len(entries),
                             note="Abgebrochen – kann fortgesetzt werden", db_path=self.db)
            self._set_phase("Abgebrochen", "Lauf abgebrochen – kann fortgesetzt werden")
            return run_id
        except RunAborted as exc:
            store.finish_run(run_id, "failed", start_list_size=len(entries), note=str(exc),
                             db_path=self.db)
            self._set_phase("Gestoppt", str(exc))
            return run_id

        loaded = self._count_complete(run_id, included)
        note = f"{loaded} von {len(included)} Aktien vollständig geladen"
        try:
            summary = self._evaluate(run_id)
            note += f", {summary.message}"
        except Exception as exc:  # noqa: BLE001 – data stays usable; evaluation can be repeated
            note += f" – Bewertung fehlgeschlagen: {type(exc).__name__}: {exc}"
        store.finish_run(run_id, "finished", start_list_size=len(entries), rated_count=loaded,
                         note=note, db_path=self.db)
        self._set_phase("Fertig", note)
        return run_id

    def _load_financial_fx(self, run_id: int, included: list[store.StartListEntry]) -> None:
        """FX for reporting currencies that differ from the trading currency (e.g. a Hong Kong
        listing reporting in CNY). Known only after the company data has been loaded."""
        raw_ids = store.raw_ids_for_run(run_id, db_path=self.db)
        info_ids = [raw_ids[(e.yahoo_ticker, "info")] for e in included
                    if (e.yahoo_ticker, "info") in raw_ids]
        infos = list(store.load_raw_many(info_ids, db_path=self.db).values())
        pairs = sorted(needed_fx_pairs(infos, [e.currency for e in included])
                       - {k for k, d in raw_ids if d == "fx"})
        if not pairs:
            return
        self._set_phase("Devisenkurse (Bilanzwährungen)")
        self.progress.total += len(pairs)
        for pair in pairs:
            self._load(run_id, pair, "fx", lambda p=pair: self.source.fx_history(
                p, self.config.data_source.history_price_days))
            self._tick(run_id)

    def _evaluate(self, run_id: int) -> EvaluationSummary:
        self._set_phase("Kennzahlen berechnen und prüfen")

        def progress(done: int, total: int, current: str) -> None:
            self.progress.current = current
            self.progress.message = f"Bewertung {done + 1} von {total}"

        return evaluate_run(run_id, self.config, db_path=self.db, on_progress=progress)

    def _tick(self, run_id: int) -> None:
        self.progress.done += 1
        self.progress.requests = self.fetcher.requests
        store.update_progress(run_id, self.progress.done, self.progress.total,
                              self.fetcher.requests, db_path=self.db)

    def _load_stock(self, run_id: int, ticker: str, completed: set[tuple[str, str]]) -> None:
        days = self.config.data_source.history_price_days
        loaders: dict[str, Callable[[], dict[str, Any]]] = {
            "history": lambda: self.source.history(ticker, days),
            "info": lambda: self.source.info(ticker),
        }
        for kind in STATEMENTS:
            loaders[kind] = lambda k=kind: self.source.statement(ticker, k)

        for dataset in DATASETS:
            if (ticker, dataset) in completed:
                continue
            ok = self._load(run_id, ticker, dataset, loaders[dataset])
            if dataset == "history" and not ok:
                # No prices -> ticker unknown at the source; skip the remaining requests.
                for rest in DATASETS[1:]:
                    store.set_item(run_id, ticker, rest, "skipped", reason="ticker_not_found",
                                   db_path=self.db)
                return

    def _load(
        self, run_id: int, key: str, dataset: str, loader: Callable[[], dict[str, Any]]
    ) -> bool:
        """Fetch one dataset (or reuse the cache) and record the outcome. True on success."""
        cached = store.fresh_raw_id(key, dataset, _max_age(self.config, dataset), db_path=self.db)
        if cached is not None:
            store.set_item(run_id, key, dataset, "cached", raw_id=cached, db_path=self.db)
            return True
        try:
            payload = self.fetcher.call(loader)
        except Cancelled:
            raise
        except NoData as exc:
            store.set_item(run_id, key, dataset, "failed", reason=exc.reason, detail=str(exc),
                           db_path=self.db)
            self.consecutive_rate_limits = 0
            self.progress.failures += 1
            return False
        except RateLimited as exc:
            store.set_item(run_id, key, dataset, "failed", reason=exc.reason, detail=str(exc),
                           db_path=self.db)
            self.progress.failures += 1
            self.consecutive_rate_limits += 1
            limit = self.config.data_source.abort_after_consecutive_rate_limits
            if self.consecutive_rate_limits >= limit:
                raise RunAborted(
                    "Yahoo sperrt die Abrufe dauerhaft – Lauf gestoppt. Später fortsetzen."
                ) from exc
            return False
        except SourceError as exc:
            store.set_item(run_id, key, dataset, "failed", reason=exc.reason, detail=str(exc),
                           db_path=self.db)
            self.progress.failures += 1
            return False
        except Exception as exc:  # noqa: BLE001 – unexpected: record, keep the run going
            store.set_item(run_id, key, dataset, "failed", reason="error",
                           detail=f"{type(exc).__name__}: {exc}", db_path=self.db)
            self.progress.failures += 1
            return False

        raw_id = store.put_raw(key, dataset, payload, db_path=self.db)
        store.set_item(run_id, key, dataset, "ok", raw_id=raw_id, db_path=self.db)
        self.consecutive_rate_limits = 0
        return True

    def _count_complete(self, run_id: int, included: list[store.StartListEntry]) -> int:
        good: dict[str, set[str]] = {}
        for key, dataset, status, _reason in store.item_statuses(run_id, db_path=self.db):
            if status in {"ok", "cached"}:
                good.setdefault(key, set()).add(dataset)
        return sum(1 for e in included if good.get(e.yahoo_ticker or "", set()) >= set(DATASETS))
