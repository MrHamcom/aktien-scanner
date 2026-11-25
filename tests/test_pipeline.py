import threading
from pathlib import Path

import pytest

from scanner.config import ScannerConfig
from scanner.core import coverage, store
from scanner.core.pipeline import ScanRun, fx_pair
from scanner.core.sources.base import DATASETS
from scanner.core.sources.fake import FakeSource
from scanner.core.universe import StartListError


def _run(config: ScannerConfig, db: Path, csv_text: str, source=None, **kwargs) -> ScanRun:
    return ScanRun(
        config,
        source or FakeSource(),
        db_path=db,
        holdings_loader=lambda _cfg: (csv_text, "Testdatei"),
        sleep=lambda _s, _c: None,
        **kwargs,
    )


def _fast(config: ScannerConfig) -> ScannerConfig:
    ds = config.data_source.model_copy(update={"max_requests_per_minute": 600_000})
    return config.model_copy(update={"data_source": ds})


def test_fx_pair() -> None:
    assert fx_pair("USD") == "USDEUR=X"
    assert fx_pair("GBp") == "GBPEUR=X"
    assert fx_pair("EUR") is None
    assert fx_pair("") is None


def test_full_run_loads_all_datasets(config, db, sample_csv) -> None:
    config = _fast(config)
    source = FakeSource()
    run_id = _run(config, db, sample_csv, source).start("full")

    run = store.get_run(run_id, db)
    assert run is not None and run.status == "finished"
    entries = store.get_start_list(run_id, db)
    included = [e for e in entries if e.status == "included"]
    # every included stock except the one without data is complete
    assert run.rated_count == len(included) - 1

    statuses = {(k, d): (s, r) for k, d, s, r in store.item_statuses(run_id, db)}
    assert statuses[("MISSINGCO", "history")] == ("failed", "no_data")
    assert statuses[("MISSINGCO", "info")] == ("skipped", "ticker_not_found")
    # excluded and unmapped stocks were never requested
    requested = {ticker for ticker, _ in source.calls}
    assert "BRK-B" not in requested and "PLD" not in requested
    # FX pairs for all non-EUR currencies of included stocks
    assert statuses[("USDEUR=X", "fx")][0] == "ok"
    assert ("EUREUR=X", "fx") not in statuses


def test_second_run_uses_cache(config, db, sample_csv) -> None:
    config = _fast(config)
    _run(config, db, sample_csv).start("full")
    source = FakeSource()
    run_id = _run(config, db, sample_csv, source).start("full")
    assert source.calls == [("MISSINGCO", "history")]  # only the failed one is retried
    statuses = {s for _k, _d, s, _r in store.item_statuses(run_id, db)}
    assert "cached" in statuses and "ok" not in statuses


def test_raw_data_is_deduplicated(config, db, sample_csv) -> None:
    config = _fast(config)
    run_id = _run(config, db, sample_csv).start("probe_100")
    with store.connect(db) as conn:
        before = conn.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
    # identical content stored again -> same row
    item = next(i for i in store.item_statuses(run_id, db) if i[2] == "ok")
    raw_id = store.fresh_raw_id(item[0], item[1], __import__("datetime").timedelta(days=1), db)
    payload = store.load_raw(raw_id, db)
    assert store.put_raw(item[0], item[1], payload, db) == raw_id
    with store.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0] == before


def test_cancel_and_resume(config, db, sample_csv) -> None:
    config = _fast(config)
    cancel = threading.Event()
    source = FakeSource()
    original = source.info

    def info_then_cancel(ticker):
        cancel.set()  # cancel during the first stock
        return original(ticker)

    source.info = info_then_cancel
    run_id = _run(config, db, sample_csv, source, cancel=cancel).start("full")
    assert store.get_run(run_id, db).status == "cancelled"

    resumed_source = FakeSource()
    _run(config, db, sample_csv, resumed_source).resume(run_id)
    run = store.get_run(run_id, db)
    assert run.status == "finished"
    # history and info of the first stock were loaded before the cancel took effect
    assert ("NVDA", "history") not in resumed_source.calls
    assert ("NVDA", "info") not in resumed_source.calls
    assert ("NVDA", "income") in resumed_source.calls


def test_persistent_rate_limit_stops_run(config, db, tmp_path, sample_csv) -> None:
    ds = config.data_source.model_copy(update={
        "max_requests_per_minute": 600_000, "max_retries": 0,
        "abort_after_consecutive_rate_limits": 2,
    })
    config = config.model_copy(update={"data_source": ds})
    csv = sample_csv.replace('"NVDA"', '"LIMITA"').replace('"AAPL"', '"LIMITB"')
    source = FakeSource(rate_limit_failures=10)
    run_id = _run(config, db, csv, source).start("full")
    run = store.get_run(run_id, db)
    assert run.status == "failed"
    assert "Yahoo sperrt" in (run.note or "")


def test_broken_start_list_fails_closed(config, db) -> None:
    with pytest.raises(StartListError):
        _run(config, db, "<html>blocked</html>").start("full")
    run = store.latest_run(db)
    assert run is not None and run.status == "failed"
    assert run.note.startswith("Startliste")


def test_coverage_report(config, db, sample_csv) -> None:
    run_id = _run(_fast(config), db, sample_csv).start("full")
    cov = coverage.compute(run_id, db)
    assert cov.total.listed == 14
    assert cov.total.excluded == 2 and cov.total.unmapped == 1
    assert cov.total.complete == cov.total.included - 1
    assert cov.total.loaded["history"] == cov.total.included - 1
    assert ("Atlantis Stock Exchange", 1) in cov.unmapped_exchanges
    assert any(reason.startswith("history: no_data") for reason, _n, _ex in cov.failure_reasons)
    europe = next(r for r in cov.regions if r.region == "Europe")
    assert europe.complete_share == 1.0
    assert set(DATASETS) <= set(europe.loaded)


def test_run_ends_with_evaluation(config, db, sample_csv) -> None:
    run_id = _run(_fast(config), db, sample_csv).start("full")
    evaluations = {e.key: e for e in store.get_evaluations(run_id, db)}
    included = [e for e in store.get_start_list(run_id, db) if e.status == "included"]
    assert len(evaluations) == len(included)
    assert evaluations["MISSINGCO"].status == "data"
    assert any(e.status == "rated" for e in evaluations.values())
    assert "bewertbar" in (store.get_run(run_id, db).note or "")
