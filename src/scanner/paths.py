"""Central place for file system locations."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


def config_path() -> Path:
    """Path of the active configuration file (override with SCANNER_CONFIG)."""
    override = os.environ.get("SCANNER_CONFIG")
    return Path(override) if override else PROJECT_ROOT / "config" / "scanner.yaml"


def data_dir() -> Path:
    """Directory for cache, snapshots and the SQLite database (override with SCANNER_DATA_DIR)."""
    override = os.environ.get("SCANNER_DATA_DIR")
    path = Path(override) if override else PROJECT_ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def exports_dir() -> Path:
    """Directory for CSV exports."""
    path = PROJECT_ROOT / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    """Path of the SQLite database."""
    return data_dir() / "scanner.sqlite3"
