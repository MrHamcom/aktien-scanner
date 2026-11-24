"""Optional command line for self-test and automation. Daily use happens in the UI."""

from __future__ import annotations

import argparse
import sys

from scanner import __version__
from scanner.config import ConfigError, load_config
from scanner.core.store import latest_run
from scanner.paths import config_path, database_path


def _check() -> int:
    """Validate configuration and database; print a short summary."""
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    run = latest_run()
    print(f"Aktien-Scanner {__version__}")
    print(f"Konfiguration: OK (Version {config.config_version}, {config_path()})")
    for profile in config.profiles.values():
        weights = ", ".join(f"{k} {v:.0f} %" for k, v in profile.weights.items())
        print(f"  Profil {profile.label}: {weights}")
    print(f"Datenbank: OK ({database_path()})")
    print(f"Letzter Lauf: {'noch keiner' if run is None else run.started_at.isoformat()}")
    print(f"Oberfläche: http://localhost:{config.ui.port}")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="scanner", description="Aktien-Scanner – Hilfsbefehle")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Konfiguration und Datenbank prüfen")
    sub.add_parser("ui", help="Oberfläche starten")
    args = parser.parse_args(argv)

    if args.command == "check":
        sys.exit(_check())
    if args.command == "ui":
        from scanner.ui.app import main as ui_main

        ui_main()


if __name__ == "__main__":
    main()
