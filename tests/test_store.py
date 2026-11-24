import re
from pathlib import Path

import pytest

from scanner.core.store import finish_run, latest_run, start_run


def test_no_run_yet(tmp_path: Path) -> None:
    assert latest_run(tmp_path / "db.sqlite3") is None


def test_run_lifecycle(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    run_id = start_run(config_version=1, db_path=db)
    run = latest_run(db)
    assert run is not None and run.id == run_id and run.status == "running"

    finish_run(run_id, "finished", start_list_size=2200, rated_count=1500, db_path=db)
    run = latest_run(db)
    assert run is not None
    assert run.status == "finished"
    assert run.finished_at is not None
    assert (run.start_list_size, run.rated_count) == (2200, 1500)


def test_invalid_final_status(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    run_id = start_run(config_version=1, db_path=db)
    with pytest.raises(ValueError):
        finish_run(run_id, "running", db_path=db)


def test_engine_does_not_import_ui() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "scanner" / "core"
    pattern = re.compile(r"^\s*(from|import)\s+(scanner\.ui|nicegui)\b", re.MULTILINE)
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), f"{path} imports the UI"
