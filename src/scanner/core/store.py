"""SQLite storage: runs, start-list snapshots, per-item status and raw data.

Raw data is stored once per distinct content (deduplicated by hash, zlib-compressed) and linked
to every run that used it, so each run stays reproducible without duplicating unchanged data.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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

CREATE TABLE IF NOT EXISTS start_list (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    source_ticker   TEXT    NOT NULL,
    yahoo_ticker    TEXT,
    name            TEXT,
    sector          TEXT,
    country         TEXT,
    region          TEXT,
    exchange        TEXT,
    currency        TEXT,
    weight          REAL,
    status          TEXT    NOT NULL,
    reason          TEXT
);
CREATE INDEX IF NOT EXISTS start_list_run ON start_list(run_id);

CREATE TABLE IF NOT EXISTS raw_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key             TEXT    NOT NULL,
    dataset         TEXT    NOT NULL,
    fetched_at      TEXT    NOT NULL,
    sha256          TEXT    NOT NULL,
    payload         BLOB    NOT NULL,
    UNIQUE (key, dataset, sha256)
);
CREATE INDEX IF NOT EXISTS raw_data_lookup ON raw_data(key, dataset, fetched_at);

CREATE TABLE IF NOT EXISTS run_items (
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    key             TEXT    NOT NULL,
    dataset         TEXT    NOT NULL,
    status          TEXT    NOT NULL CHECK (status IN ('ok', 'cached', 'failed', 'skipped')),
    reason          TEXT,
    detail          TEXT,
    raw_id          INTEGER REFERENCES raw_data(id),
    updated_at      TEXT    NOT NULL,
    PRIMARY KEY (run_id, key, dataset)
);

CREATE TABLE IF NOT EXISTS evaluations (
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    key             TEXT    NOT NULL,
    status          TEXT    NOT NULL,   -- 'rated' or the stage that excluded the stock
    reason          TEXT,
    detail          TEXT,
    issues          TEXT    NOT NULL,   -- JSON list of [code, detail]
    flags           TEXT    NOT NULL,   -- JSON list of flag codes
    metrics         TEXT    NOT NULL,   -- JSON object of metric values
    evaluated_at    TEXT    NOT NULL,
    PRIMARY KEY (run_id, key)
);
"""

# Columns added after the first release; added to existing databases on connect.
RUN_COLUMNS: dict[str, str] = {
    "scope": "TEXT",
    "total_items": "INTEGER",
    "done_items": "INTEGER",
    "requests": "INTEGER",
}

# Failure reasons that are final for a run; other failures are retried when a run is resumed.
FINAL_REASONS = {"no_data", "ticker_not_found"}


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
    scope: str | None = None
    total_items: int | None = None
    done_items: int | None = None
    requests: int | None = None


@dataclass(frozen=True)
class StartListEntry:
    source_ticker: str
    yahoo_ticker: str | None
    name: str
    sector: str
    country: str
    region: str | None
    exchange: str
    currency: str
    weight: float
    status: str  # 'included' | 'excluded' | 'unmapped'
    reason: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    for column, kind in RUN_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {kind}")


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open the database, create/migrate the schema and commit on success."""
    conn = sqlite3.connect(db_path or database_path(), timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- runs -------------------------------------------------------------------------------------

_RUN_SELECT = (
    "SELECT id, started_at, finished_at, status, config_version, start_list_size, rated_count,"
    " note, scope, total_items, done_items, requests FROM runs"
)


def _to_run(row: tuple[Any, ...]) -> Run:
    return Run(
        id=row[0],
        started_at=datetime.fromisoformat(row[1]),
        finished_at=datetime.fromisoformat(row[2]) if row[2] else None,
        status=row[3],
        config_version=row[4],
        start_list_size=row[5],
        rated_count=row[6],
        note=row[7],
        scope=row[8],
        total_items=row[9],
        done_items=row[10],
        requests=row[11],
    )


def start_run(config_version: int, scope: str | None = None, db_path: Path | None = None) -> int:
    """Insert a new run in status 'running' and return its id."""
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status, config_version, scope, done_items, requests)"
            " VALUES (?, 'running', ?, ?, 0, 0)",
            (_now(), config_version, scope),
        )
        return int(cur.lastrowid)


def reopen_run(run_id: int, db_path: Path | None = None) -> None:
    """Set a cancelled or failed run back to 'running' to resume it."""
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET status = 'running', finished_at = NULL WHERE id = ?", (run_id,)
        )


def update_progress(
    run_id: int, done_items: int, total_items: int, requests: int, db_path: Path | None = None
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET done_items = ?, total_items = ?, requests = ? WHERE id = ?",
            (done_items, total_items, requests, run_id),
        )


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
            "UPDATE runs SET finished_at = ?, status = ?,"
            " start_list_size = COALESCE(?, start_list_size),"
            " rated_count = COALESCE(?, rated_count), note = ? WHERE id = ?",
            (_now(), status, start_list_size, rated_count, note, run_id),
        )


def latest_run(db_path: Path | None = None) -> Run | None:
    """Return the most recent run, or None if there is none yet."""
    with connect(db_path) as conn:
        row = conn.execute(f"{_RUN_SELECT} ORDER BY id DESC LIMIT 1").fetchone()
    return _to_run(row) if row else None


def get_run(run_id: int, db_path: Path | None = None) -> Run | None:
    with connect(db_path) as conn:
        row = conn.execute(f"{_RUN_SELECT} WHERE id = ?", (run_id,)).fetchone()
    return _to_run(row) if row else None


def list_runs(limit: int = 20, db_path: Path | None = None) -> list[Run]:
    with connect(db_path) as conn:
        rows = conn.execute(f"{_RUN_SELECT} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_to_run(row) for row in rows]


def mark_stale_runs(db_path: Path | None = None) -> None:
    """Runs left in 'running' after a restart were interrupted: mark them as cancelled."""
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET status = 'cancelled', finished_at = ?,"
            " note = 'Unterbrochen (Programm beendet) – kann fortgesetzt werden'"
            " WHERE status = 'running'",
            (_now(),),
        )


# --- start list -------------------------------------------------------------------------------


def save_start_list(
    run_id: int, entries: Iterable[StartListEntry], db_path: Path | None = None
) -> None:
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO start_list (run_id, source_ticker, yahoo_ticker, name, sector, country,"
            " region, exchange, currency, weight, status, reason)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id, e.source_ticker, e.yahoo_ticker, e.name, e.sector, e.country,
                    e.region, e.exchange, e.currency, e.weight, e.status, e.reason,
                )
                for e in entries
            ],
        )


def get_start_list(run_id: int, db_path: Path | None = None) -> list[StartListEntry]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT source_ticker, yahoo_ticker, name, sector, country, region, exchange,"
            " currency, weight, status, reason FROM start_list WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
    return [StartListEntry(*row) for row in rows]


# --- raw data ---------------------------------------------------------------------------------


def encode_payload(obj: Any) -> bytes:
    """JSON-encode and compress a payload (dict/list from the source adapters)."""
    return zlib.compress(json.dumps(obj, sort_keys=True, default=str).encode("utf-8"), 6)


def decode_payload(blob: bytes) -> Any:
    return json.loads(zlib.decompress(blob).decode("utf-8"))


def put_raw(key: str, dataset: str, obj: Any, db_path: Path | None = None) -> int:
    """Store a payload (deduplicated) and return its id. Refreshes fetched_at if unchanged."""
    blob = encode_payload(obj)
    digest = hashlib.sha256(blob).hexdigest()
    with connect(db_path) as conn:
        row = conn.execute(
            "INSERT INTO raw_data (key, dataset, fetched_at, sha256, payload)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (key, dataset, sha256) DO UPDATE SET fetched_at = excluded.fetched_at"
            " RETURNING id",
            (key, dataset, _now(), digest, blob),
        ).fetchone()
    return int(row[0])


def fresh_raw_id(
    key: str, dataset: str, max_age: timedelta, db_path: Path | None = None
) -> int | None:
    """Id of the newest stored payload younger than max_age, else None."""
    cutoff = (datetime.now(UTC) - max_age).isoformat()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM raw_data WHERE key = ? AND dataset = ? AND fetched_at >= ?"
            " ORDER BY fetched_at DESC LIMIT 1",
            (key, dataset, cutoff),
        ).fetchone()
    return int(row[0]) if row else None


def load_raw(raw_id: int, db_path: Path | None = None) -> Any:
    with connect(db_path) as conn:
        row = conn.execute("SELECT payload FROM raw_data WHERE id = ?", (raw_id,)).fetchone()
    if row is None:
        raise KeyError(raw_id)
    return decode_payload(row[0])


# --- run items --------------------------------------------------------------------------------


def set_item(
    run_id: int,
    key: str,
    dataset: str,
    status: str,
    reason: str | None = None,
    detail: str | None = None,
    raw_id: int | None = None,
    db_path: Path | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO run_items (run_id, key, dataset, status, reason, detail, raw_id,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (run_id, key, dataset) DO UPDATE SET status = excluded.status,"
            " reason = excluded.reason, detail = excluded.detail, raw_id = excluded.raw_id,"
            " updated_at = excluded.updated_at",
            (run_id, key, dataset, status, reason, (detail or "")[:500] or None, raw_id, _now()),
        )


def completed_items(run_id: int, db_path: Path | None = None) -> set[tuple[str, str]]:
    """(key, dataset) pairs that need no further work when resuming a run."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT key, dataset, status, reason FROM run_items WHERE run_id = ?", (run_id,)
        ).fetchall()
    return {
        (key, dataset)
        for key, dataset, status, reason in rows
        if status in {"ok", "cached", "skipped"} or reason in FINAL_REASONS
    }


def item_statuses(
    run_id: int, db_path: Path | None = None
) -> list[tuple[str, str, str, str | None]]:
    """(key, dataset, status, reason) for all items of a run."""
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT key, dataset, status, reason FROM run_items WHERE run_id = ?", (run_id,)
        ).fetchall()


def failure_details(
    run_id: int, limit: int = 200, db_path: Path | None = None
) -> list[tuple[str, str, str, str | None]]:
    """(key, dataset, reason, detail) of failed items, most recent first."""
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT key, dataset, reason, detail FROM run_items"
            " WHERE run_id = ? AND status = 'failed' ORDER BY updated_at DESC LIMIT ?",
            (run_id, limit),
        ).fetchall()


# --- evaluations ----------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationRow:
    key: str
    status: str
    reason: str | None
    detail: str | None
    issues: list[tuple[str, str]]
    flags: list[str]
    metrics: dict[str, float | None]


def save_evaluations(run_id: int, rows: list[EvaluationRow], db_path: Path | None = None) -> None:
    """Replace all evaluations of a run (evaluation can be repeated without refetching)."""
    now = _now()
    with connect(db_path) as conn:
        conn.execute("DELETE FROM evaluations WHERE run_id = ?", (run_id,))
        conn.executemany(
            "INSERT INTO evaluations (run_id, key, status, reason, detail, issues, flags, metrics,"
            " evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (run_id, r.key, r.status, r.reason, r.detail, json.dumps(r.issues),
                 json.dumps(r.flags), json.dumps(r.metrics), now)
                for r in rows
            ],
        )


def get_evaluations(run_id: int, db_path: Path | None = None) -> list[EvaluationRow]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT key, status, reason, detail, issues, flags, metrics FROM evaluations"
            " WHERE run_id = ? ORDER BY key",
            (run_id,),
        ).fetchall()
    return [
        EvaluationRow(
            key=r[0], status=r[1], reason=r[2], detail=r[3],
            issues=[tuple(i) for i in json.loads(r[4])], flags=json.loads(r[5]),
            metrics=json.loads(r[6]),
        )
        for r in rows
    ]


def raw_ids_for_run(run_id: int, db_path: Path | None = None) -> dict[tuple[str, str], int]:
    """(key, dataset) -> raw_id for every successfully loaded item of a run."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT key, dataset, raw_id FROM run_items WHERE run_id = ? AND raw_id IS NOT NULL"
            " AND status IN ('ok', 'cached')",
            (run_id,),
        ).fetchall()
    return {(k, d): int(i) for k, d, i in rows}


def load_raw_many(raw_ids: list[int], db_path: Path | None = None) -> dict[int, Any]:
    result: dict[int, Any] = {}
    with connect(db_path) as conn:
        for start in range(0, len(raw_ids), 500):
            chunk = raw_ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            for raw_id, payload in conn.execute(
                f"SELECT id, payload FROM raw_data WHERE id IN ({marks})", chunk
            ):
                result[int(raw_id)] = decode_payload(payload)
    return result
