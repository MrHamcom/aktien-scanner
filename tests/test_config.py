from pathlib import Path

import pytest
import yaml

from scanner.config import FACTORS, ConfigError, load_config
from scanner.paths import PROJECT_ROOT

DEFAULT = PROJECT_ROOT / "config" / "scanner.yaml"


def _write_variant(tmp_path: Path, mutate) -> Path:
    raw = yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "scanner.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_default_config_loads() -> None:
    config = load_config(DEFAULT)
    assert config.config_version >= 1
    assert set(config.profiles) == {"overall", "dividend"}


def test_profile_weights_sum_to_100() -> None:
    config = load_config(DEFAULT)
    for profile in config.profiles.values():
        assert set(profile.weights) == set(FACTORS)
        assert sum(profile.weights.values()) == pytest.approx(100)


def test_decisions_are_reflected() -> None:
    config = load_config(DEFAULT)
    assert config.start_list.etf == "ACWI"
    assert config.universe_rule.min_market_cap_eur == 2_000_000_000
    assert config.universe_rule.min_avg_daily_value_eur == 10_000_000
    assert {"Financials", "Real Estate"} <= set(config.universe_rule.excluded_sectors)
    assert config.profiles["overall"].non_payer_dividend == "redistribute"
    assert config.data_source.provider == "yfinance"
    assert config.schedule.mode == "manual"


def test_wrong_weight_sum_is_rejected(tmp_path: Path) -> None:
    def mutate(raw: dict) -> None:
        raw["profiles"]["overall"]["weights"]["value"] = 50

    with pytest.raises(ConfigError, match="sum to 100"):
        load_config(_write_variant(tmp_path, mutate))


def test_missing_factor_is_rejected(tmp_path: Path) -> None:
    def mutate(raw: dict) -> None:
        del raw["profiles"]["dividend"]["weights"]["momentum"]

    with pytest.raises(ConfigError, match="exactly"):
        load_config(_write_variant(tmp_path, mutate))


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    def mutate(raw: dict) -> None:
        raw["universe_rule"]["typo_key"] = 1

    with pytest.raises(ConfigError):
        load_config(_write_variant(tmp_path, mutate))


def test_country_in_two_regions_is_rejected(tmp_path: Path) -> None:
    def mutate(raw: dict) -> None:
        raw["regions"]["Japan"].append("Germany")

    with pytest.raises(ConfigError, match="Germany"):
        load_config(_write_variant(tmp_path, mutate))


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="fehlt"):
        load_config(tmp_path / "missing.yaml")


def test_region_lookup() -> None:
    config = load_config(DEFAULT)
    assert config.region_of("Germany") == "Europe"
    assert config.region_of("United States") == "North America"
    assert config.region_of("Atlantis") is None


def test_value_trap_decision_c(config) -> None:
    # decision 25.11.2026: negative FCF and Altman Z are warnings, dilution excludes
    traps = config.value_trap_filters
    assert (traps.negative_fcf_action, traps.altman_action, traps.dilution_action) == (
        "flag", "flag", "exclude")
