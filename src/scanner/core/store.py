"""SQLite storage for runs and results.

Subphase A only creates the run table; snapshots, raw data and results follow in Subphase B.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scanner.paths import database_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT    NOT NULL,
    finished_at     TEXT,
    status          TEXT    NOT NULL
                    CHECK (status IN ('running', 'finished', 'failed', 'cancelled')),
    config_version  INTEGER NOT NULL,
    start_list_size INTEGER,
    rated_count     INTEGER,
    note            TEXT
);
"""


@dataclass(frozen=True)
class Run:
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    config_version: int
    start_list_size: int | None
    rated_count: int | None
    note: str | None


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open the database, create the schema if needed and commit on success."""
    conn = sqlite3.connect(db_path or database_path())
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def start_run(config_version: int, db_path: Path | None = None) -> int:
    """Insert a new run in status 'running' and return its id."""
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status, config_version) VALUES (?, 'running', ?)",
            (datetime.now(UTC).isoformat(), config_version),
        )
        return int(cur.lastrowid)


def finish_run(
    run_id: int,
    status: str,
    start_list_size: int | None = None,
    rated_count: int | None = None,
    note: str | None = None,
    db_path: Path | None = None,
) -> None:
    """Mark a run as finished, failed or cancelled."""
    if status not in {"finished", "failed", "cancelled"}:
        raise ValueError(f"invalid final status: {status}")
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, start_list_size = ?, rated_count = ?,"
            " note = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), status, start_list_size, rated_count, note, run_id),
        )


def latest_run(db_path: Path | None = None) -> Run | None:
    """Return the most recent run, or None if there is none yet."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, started_at, finished_at, status, config_version, start_list_size,"
            " rated_count, note FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return Run(
        id=row[0],
        started_at=datetime.fromisoformat(row[1]),
        finished_at=datetime.fromisoformat(row[2]) if row[2] else None,
        status=row[3],
        config_version=row[4],
        start_list_size=row[5],
        rated_count=row[6],
        note=row[7],
    )
