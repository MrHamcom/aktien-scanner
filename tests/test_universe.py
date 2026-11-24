import pytest

from scanner.config import load_exchanges
from scanner.core.universe import (
    FULL_SCOPE,
    Holding,
    StartListError,
    build_start_list,
    parse_ishares_csv,
    select_scope,
    to_yahoo_ticker,
)


def _holding(ticker: str, exchange: str, country: str = "United States") -> Holding:
    return Holding(ticker, "X", "Industrials", "Equity", 1.0, country, exchange, "USD")


def test_parse_skips_metadata_and_footer(sample_csv: str) -> None:
    holdings = parse_ishares_csv(sample_csv)
    assert holdings[0].ticker == "NVDA"
    assert holdings[0].weight == pytest.approx(4.68)
    assert holdings[-1].ticker == "USD"  # cash row is parsed, filtered later
    assert len(holdings) == 15


def test_parse_rejects_unexpected_format() -> None:
    with pytest.raises(StartListError, match="Kopfzeile"):
        parse_ishares_csv("Access denied")


def test_parse_recognises_html_page() -> None:
    with pytest.raises(StartListError, match="Webseite"):
        parse_ishares_csv("<!DOCTYPE html>\n<html lang='en-US'><head></head></html>")


def test_download_url_points_to_csv(config) -> None:
    assert config.start_list.url.endswith(".csv")


@pytest.mark.parametrize(
    ("ticker", "exchange", "country", "expected"),
    [
        ("NVDA", "NASDAQ", "United States", "NVDA"),
        ("BRK.B", "New York Stock Exchange Inc.", "United States", "BRK-B"),
        ("BRKB", "New York Stock Exchange Inc.", "United States", "BRK-B"),  # override
        ("SAP", "Xetra", "Germany", "SAP.DE"),
        ("700", "Hong Kong Exchanges And Clearing Ltd", "China", "0700.HK"),
        ("7203", "Tokyo Stock Exchange", "Japan", "7203.T"),
        ("BP.", "London Stock Exchange", "United Kingdom", "BP.L"),
        ("BT/A", "London Stock Exchange", "United Kingdom", "BT-A.L"),
        ("VOLV B", "Nasdaq Omx Nordic", "Sweden", "VOLV-B.ST"),
        ("5930", "Korea Exchange (Stock Market)", "Korea (South)", "005930.KS"),
        ("SAP", "XETRA", "Germany", "SAP.DE"),  # case-insensitive exchange name
    ],
)
def test_yahoo_ticker_mapping(config, ticker, exchange, country, expected) -> None:
    yahoo, reason = to_yahoo_ticker(_holding(ticker, exchange, country), load_exchanges(config))
    assert reason is None
    assert yahoo == expected


def test_unmapped_exchange_is_reported(config) -> None:
    yahoo, reason = to_yahoo_ticker(_holding("ABC", "Atlantis Stock Exchange"),
                                    load_exchanges(config))
    assert yahoo is None
    assert reason == "exchange_unmapped: Atlantis Stock Exchange"


def test_nordic_exchange_needs_known_country(config) -> None:
    yahoo, reason = to_yahoo_ticker(_holding("X", "Nasdaq Omx Nordic", "Iceland"),
                                    load_exchanges(config))
    assert yahoo is None and reason.startswith("exchange_country_unmapped")


def test_build_start_list(config, sample_csv) -> None:
    entries = build_start_list(parse_ishares_csv(sample_csv), config, load_exchanges(config))
    by_ticker = {e.source_ticker: e for e in entries}
    assert "USD" not in by_ticker  # cash is not an equity
    assert by_ticker["SAP"].status == "included" and by_ticker["SAP"].region == "Europe"
    assert by_ticker["BRKB"].status == "excluded"  # Financials
    assert by_ticker["PLD"].status == "excluded"  # Real Estate
    assert by_ticker["ABC"].status == "unmapped" and by_ticker["ABC"].region is None
    assert by_ticker["700"].region == "Emerging Markets"
    weights = [e.weight for e in entries]
    assert weights == sorted(weights, reverse=True)


def test_probe_100_takes_largest_us_and_german_names(config, sample_csv) -> None:
    entries = build_start_list(parse_ishares_csv(sample_csv), config, load_exchanges(config))
    chosen = select_scope(entries, "probe_100", config)
    countries = {e.country for e in chosen}
    assert countries <= {"United States", "Germany"}
    assert {"NVDA", "SAP", "SIE"} <= {e.source_ticker for e in chosen}


def test_probe_500_limits_per_region(config, sample_csv) -> None:
    entries = build_start_list(parse_ishares_csv(sample_csv), config, load_exchanges(config))
    chosen = select_scope(entries, "probe_500", config)
    assert {e.source_ticker for e in chosen if e.status == "included"} == {
        e.source_ticker for e in entries if e.status == "included" and e.region
    }


def test_full_scope_keeps_everything(config, sample_csv) -> None:
    entries = build_start_list(parse_ishares_csv(sample_csv), config, load_exchanges(config))
    assert select_scope(entries, FULL_SCOPE, config) == entries


def test_unknown_scope(config) -> None:
    with pytest.raises(ValueError):
        select_scope([], "nonsense", config)
