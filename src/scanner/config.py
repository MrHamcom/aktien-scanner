"""Load and validate config/scanner.yaml.

Invalid configuration fails closed: the application refuses to start and names the problem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scanner.paths import config_path

FACTORS: tuple[str, ...] = ("value", "quality", "momentum", "dividend")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StartList(_Strict):
    source: Literal["ishares_holdings_csv"]
    etf: str
    url: str


class UniverseRule(_Strict):
    min_market_cap_eur: float = Field(ge=0)
    min_avg_daily_value_eur: float = Field(ge=0)
    avg_daily_value_window_days: int = Field(ge=1)
    common_shares_only: bool
    one_share_class_per_company: bool
    excluded_sectors: list[str]


class ValueTrapFilters(_Strict):
    negative_fcf_years_of_last_3: int = Field(ge=1, le=3)
    min_altman_z: float
    max_share_dilution_12m: float = Field(ge=0)


class Ranking(_Strict):
    peer_group: list[Literal["sector", "region"]]
    min_peer_group_size: int = Field(ge=2)
    fallback_peer_group: list[Literal["sector", "region"]]


class Profile(_Strict):
    label: str
    weights: dict[str, float]
    non_payer_dividend: Literal["redistribute", "lowest", "exclude"]
    min_years_without_cut: int = Field(default=0, ge=0)
    exclude_dividend_traps: bool = False

    @field_validator("weights")
    @classmethod
    def _check_weights(cls, weights: dict[str, float]) -> dict[str, float]:
        if set(weights) != set(FACTORS):
            raise ValueError(f"weights must contain exactly {list(FACTORS)}, got {sorted(weights)}")
        if any(w < 0 for w in weights.values()):
            raise ValueError("weights must not be negative")
        total = sum(weights.values())
        if abs(total - 100) > 1e-9:
            raise ValueError(f"weights must sum to 100, got {total}")
        return weights


class Dividend(_Strict):
    trap_yield_above: float = Field(gt=0)
    max_fcf_payout_last_year: float = Field(gt=0)
    max_fcf_payout_avg_3y: float = Field(gt=0)
    streak_cap_years: int = Field(ge=1)
    growth_years: int = Field(ge=1)


class DataSource(_Strict):
    provider: Literal["yfinance"]
    max_requests_per_minute: int = Field(ge=1)
    fundamentals_refresh_days: int = Field(ge=1)


class Schedule(_Strict):
    mode: Literal["manual", "monthly"]


class Report(_Strict):
    top_n: int = Field(ge=1)


class UiSettings(_Strict):
    title: str
    host: str
    port: int = Field(ge=1024, le=65535)


class ScannerConfig(_Strict):
    config_version: int = Field(ge=1)
    start_list: StartList
    universe_rule: UniverseRule
    value_trap_filters: ValueTrapFilters
    ranking: Ranking
    profiles: dict[str, Profile]
    dividend: Dividend
    regions: dict[str, list[str]]
    data_source: DataSource
    schedule: Schedule
    report: Report
    ui: UiSettings

    @model_validator(mode="after")
    def _check_regions(self) -> ScannerConfig:
        seen: dict[str, str] = {}
        for region, countries in self.regions.items():
            for country in countries:
                if country in seen:
                    raise ValueError(
                        f"country '{country}' listed in '{seen[country]}' and '{region}'"
                    )
                seen[country] = region
        return self

    def region_of(self, country: str) -> str | None:
        """Return the region for a country, or None if the country is not mapped."""
        for region, countries in self.regions.items():
            if country in countries:
                return region
        return None


class ConfigError(RuntimeError):
    """Raised when the configuration file is missing or invalid."""


def load_config(path: Path | None = None) -> ScannerConfig:
    """Read and validate the configuration file."""
    path = path or config_path()
    if not path.is_file():
        raise ConfigError(f"Konfigurationsdatei fehlt: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return ScannerConfig.model_validate(raw)
    except (yaml.YAMLError, ValueError) as exc:
        raise ConfigError(f"Konfiguration ungültig ({path}):\n{exc}") from exc
