"""Load and validate config/scanner.yaml.

Invalid configuration fails closed: the application refuses to start and names the problem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scanner.paths import config_path, resolve_project_path

FACTORS: tuple[str, ...] = ("value", "quality", "momentum", "dividend")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StartList(_Strict):
    source: Literal["ishares_holdings_csv"]
    etf: str
    url: str
    local_file: str
    exchanges_file: str


class RampUpSample(_Strict):
    label: str
    per_country: dict[str, int] | None = None
    per_region: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one_rule(self) -> RampUpSample:
        if (self.per_country is None) == (self.per_region is None):
            raise ValueError("ramp-up sample needs exactly one of per_country / per_region")
        return self


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


class Refresh(_Strict):
    history_hours: float = Field(gt=0)
    info_days: float = Field(gt=0)
    statements_days: float = Field(gt=0)
    fx_hours: float = Field(gt=0)


class DataSource(_Strict):
    provider: Literal["yfinance"]
    max_requests_per_minute: int = Field(ge=1)
    max_retries: int = Field(ge=0)
    retry_base_seconds: float = Field(ge=0)
    abort_after_consecutive_rate_limits: int = Field(ge=1)
    history_price_days: int = Field(ge=260)
    refresh: Refresh


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
    ramp_up: dict[str, RampUpSample]
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


class ExchangeRule(_Strict):
    suffix: str | None = None
    by_country: dict[str, str] | None = None
    zero_pad: int | None = Field(default=None, ge=1)
    separator: str | None = None

    @model_validator(mode="after")
    def _suffix_or_country(self) -> ExchangeRule:
        if (self.suffix is None) == (self.by_country is None):
            raise ValueError("exchange rule needs exactly one of suffix / by_country")
        return self


class ExchangesConfig(_Strict):
    exchanges: dict[str, ExchangeRule]
    ticker_overrides: dict[str, str] = Field(default_factory=dict)
    unlisted: list[str] = Field(default_factory=list)

    def is_unlisted(self, exchange: str) -> bool:
        wanted = exchange.strip().casefold()
        return any(name.strip().casefold() == wanted for name in self.unlisted)

    def rule_for(self, exchange: str) -> ExchangeRule | None:
        """Case-insensitive lookup of an exchange name."""
        wanted = exchange.strip().casefold()
        for name, rule in self.exchanges.items():
            if name.strip().casefold() == wanted:
                return rule
        return None


class ConfigError(RuntimeError):
    """Raised when the configuration file is missing or invalid."""


def load_exchanges(config: ScannerConfig) -> ExchangesConfig:
    """Read the exchange mapping referenced by the main configuration."""
    path = resolve_project_path(config.start_list.exchanges_file)
    if not path.is_file():
        raise ConfigError(f"Börsen-Zuordnung fehlt: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return ExchangesConfig.model_validate(raw)
    except (yaml.YAMLError, ValueError) as exc:
        raise ConfigError(f"Börsen-Zuordnung ungültig ({path}):\n{exc}") from exc


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
