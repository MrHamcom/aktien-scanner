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


def resolve_project_path(path: str | Path) -> Path:
    """Resolve a path from the configuration relative to the project folder."""
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def database_path() -> Path:
    """Path of the SQLite database."""
    return data_dir() / "scanner.sqlite3"


def env_value(key: str) -> str | None:
    """Setting from the environment or the project's .env file (environment wins).
    Secrets live only in .env – never in the configuration or the repository."""
    if os.environ.get(key):
        return os.environ[key]
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == key and not line.lstrip().startswith("#"):
            value = value.strip().strip('"').strip("'")
            return value or None
    return None
