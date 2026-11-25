"""Optional command line for self-test and automation. Daily use happens in the UI."""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

from scanner import __version__
from scanner.config import ConfigError, load_config, load_exchanges
from scanner.core import coverage, store
from scanner.core.jobs import default_source
from scanner.core.pipeline import Progress, ScanRun
from scanner.core.universe import scope_labels
from scanner.paths import PROJECT_ROOT, config_path, database_path


def _check() -> int:
    """Validate configuration and database; print a short summary."""
    try:
        config = load_config()
        exchanges = load_exchanges(config)
    except ConfigError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    run = store.latest_run()
    print(f"Aktien-Scanner {__version__}")
    print(f"Konfiguration: OK (Version {config.config_version}, {config_path()})")
    for profile in config.profiles.values():
        weights = ", ".join(f"{k} {v:.0f} %" for k, v in profile.weights.items())
        print(f"  Profil {profile.label}: {weights}")
    print(f"Börsen-Zuordnung: OK ({len(exchanges.exchanges)} Börsen)")
    print(f"Datenbank: OK ({database_path()})")
    print(f"Letzter Lauf: {'noch keiner' if run is None else run.started_at.isoformat()}")
    print(f"Oberfläche: http://localhost:{config.ui.port}")
    return 0


def _run(scope: str, resume: int | None) -> int:
    config = load_config()
    progress = Progress()
    scan = ScanRun(config, default_source(), progress=progress)
    if resume is None and scope not in scope_labels(config):
        print(f"Unbekannter Umfang: {scope}. Möglich: {', '.join(scope_labels(config))}")
        return 2
    started = time.monotonic()
    run_id = scan.resume(resume) if resume is not None else scan.start(scope)
    run = store.get_run(run_id)
    print(f"Lauf {run_id}: {run.status if run else '?'} – {progress.message}")
    print(f"Dauer {time.monotonic() - started:.0f} s, Abrufe {progress.requests}")
    cov = coverage.compute(run_id)
    for region in [*cov.regions, cov.total]:
        share = region.complete_share
        print(f"  {region.region:<24} {region.included:>5} Aktien, vollständig "
              f"{'–' if share is None else f'{share:.0%}'}")
    return 0 if run and run.status == "finished" else 1


def _evaluate(run_id: int | None) -> int:
    from scanner.core.evaluation import evaluate_run

    config = load_config()
    run = store.get_run(run_id) if run_id else store.latest_run()
    if run is None:
        print("Kein Lauf gefunden")
        return 1
    summary = evaluate_run(run.id, config)
    print(f"Lauf {run.id}: {summary.message}")
    for stage, count in summary.by_stage.most_common():
        print(f"  {stage:<14} {count:>5}")
    return 0


def _windows_downloads() -> Path | None:
    """The Windows Downloads folder as seen from WSL, if exactly one user folder has one."""
    users = Path("/mnt/c/Users")
    if not users.is_dir():
        return None
    skip = {"public", "default", "default user", "all users"}
    candidates = [
        d / "Downloads"
        for d in users.iterdir()
        if d.name.casefold() not in skip and (d / "Downloads").is_dir()
    ]
    return candidates[0] if len(candidates) == 1 else None


def _export_db(target: str | None) -> int:
    """Consistent copy of the database (SQLite backup API, safe while the UI is running)."""
    source = database_path()
    if not source.is_file():
        print(f"Keine Datenbank gefunden: {source}")
        return 1
    folder = Path(target) if target else (_windows_downloads() or PROJECT_ROOT / "exports")
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"aktien-scanner-{time.strftime('%Y%m%d-%H%M')}.sqlite3"
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    size_mb = destination.stat().st_size / 1e6
    print(f"Datenbank kopiert: {destination} ({size_mb:.0f} MB)")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="scanner", description="Aktien-Scanner – Hilfsbefehle")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Konfiguration und Datenbank prüfen")
    sub.add_parser("ui", help="Oberfläche starten")
    run_parser = sub.add_parser("run", help="Datenlauf ohne Oberfläche (für Automatisierung)")
    run_parser.add_argument("--scope", default="full", help="probe_100, probe_500 oder full")
    run_parser.add_argument("--resume", type=int, help="Lauf-Nummer fortsetzen")
    eval_parser = sub.add_parser("evaluate", help="Kennzahlen eines Laufs neu berechnen")
    eval_parser.add_argument("run", nargs="?", type=int, help="Lauf-Nummer (Standard: letzter)")
    export_parser = sub.add_parser(
        "export-db", help="Kopie der Datenbank (Standard: Windows-Downloads-Ordner)"
    )
    export_parser.add_argument("--to", help="Zielordner")
    args = parser.parse_args(argv)

    if args.command == "check":
        sys.exit(_check())
    if args.command == "run":
        sys.exit(_run(args.scope, args.resume))
    if args.command == "evaluate":
        sys.exit(_evaluate(args.run))
    if args.command == "export-db":
        sys.exit(_export_db(args.to))
    if args.command == "ui":
        from scanner.ui.app import main as ui_main

        ui_main()


if __name__ == "__main__":
    main()
