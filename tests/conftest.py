from pathlib import Path

import pytest

from scanner.config import ScannerConfig, load_config
from scanner.paths import PROJECT_ROOT

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def config() -> ScannerConfig:
    return load_config(PROJECT_ROOT / "config" / "scanner.yaml")


@pytest.fixture
def sample_csv() -> str:
    return (FIXTURES / "ishares_sample.csv").read_text(encoding="utf-8")


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite3"
