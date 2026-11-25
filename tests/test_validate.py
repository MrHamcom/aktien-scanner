"""Plausibility checks, universe rule and value-trap filter."""

import pytest
from metric_builders import M, company, company_balance, company_cashflow, company_income, history

from scanner.core.evaluation import _company_key, dedupe_share_classes
from scanner.core.validate import RATED, Evaluation, evaluate, name_similarity


def test_example_company_is_rated(config) -> None:
    ev = evaluate(company(), config)
    assert ev.rated, (ev.status, ev.reason, ev.detail)
    assert ev.metrics["earnings_yield"] == pytest.approx(150 / 2200)


def test_missing_dataset_excludes_first(config) -> None:
    ev = evaluate(company(), config, missing_datasets=["balance"])
    assert (ev.status, ev.reason, ev.detail) == ("data", "dataset_missing", "balance")


def test_missing_required_value_fails_closed(config) -> None:
    ev = evaluate(company(income=company_income(EBIT=[None, None])), config)
    assert ev.status == "plausibility"
    assert ev.reason == "ebit_missing"


def test_non_positive_enterprise_value(config) -> None:
    rich = company_balance(**{"Cash And Cash Equivalents": [3000 * M, 80 * M]})
    ev = evaluate(company(balance=rich), config)
    assert (ev.status, ev.reason) == ("plausibility", "ev_nonpositive")


def test_stale_statements(config) -> None:
    old = company_income()
    old["periods"] = ["2024-12-31", "2023-12-31", "2022-12-31", "2021-12-31"]
    ev = evaluate(company(income=old), config)
    assert ev.reason == "statements_stale"


def test_size_threshold(config) -> None:
    # 100 Mio shares x 15 € = 1.5 Mrd € < 2 Mrd €
    ev = evaluate(company(hist=history([15.0] * 300), info={"marketCap": 1500 * M}), config)
    assert (ev.status, ev.reason) == ("size", "market_cap_below")


def test_liquidity_threshold(config) -> None:
    ev = evaluate(company(hist=history([20.0] * 300, volume=100_000)), config)
    assert (ev.status, ev.reason) == ("liquidity", "turnover_below")
    assert ev.detail == "2.0 Mio. € pro Tag"


def test_negative_fcf_in_two_of_three_years(config) -> None:
    cf = company_cashflow(**{"Operating Cash Flow": [180 * M, 20 * M, 10 * M]})
    ev = evaluate(company(cashflow=cf), config)
    assert (ev.status, ev.reason) == ("value_trap", "negative_fcf")


def test_low_altman_z(config) -> None:
    # heavy liabilities and losses push Z below 1.8
    bal = company_balance(**{"Total Liabilities Net Minority Interest": [9000 * M, 650 * M],
                             "Retained Earnings": [-800 * M, 350 * M]})
    ev = evaluate(company(balance=bal), config)
    assert (ev.status, ev.reason) == ("value_trap", "altman_z_low")


def test_dilution_filter(config) -> None:
    bal = company_balance(**{"Ordinary Shares Number": [115 * M, 100 * M]})
    ev = evaluate(company(balance=bal, info={"sharesOutstanding": 115 * M,
                                             "marketCap": 2300 * M}), config)
    assert (ev.status, ev.reason) == ("value_trap", "dilution")


def test_wrong_security_type(config) -> None:
    ev = evaluate(company(info={"quoteType": "ETF"}), config)
    assert ev.reason == "security_type"


@pytest.mark.parametrize(
    ("ishares", "yahoo", "ok"),
    [
        ("NVIDIA CORP", "NVIDIA Corporation", True),
        ("TAIWAN SEMICONDUCTOR MANUFACTURING", "Taiwan Semiconductor Manufacturing Company", True),
        ("META PLATFORMS INC CLASS A", "Meta Platforms, Inc.", True),
        ("TENAGA NASIONAL", "Tenaga Nasional Berhad", True),
        ("SD GUTHRIE", "SD Guthrie Berhad", True),
        ("TOYOTA MOTOR CORP", "Toyota Motor Corporation", True),
        ("LOREAL SA", "L'Oréal S.A.", True),
        ("ORSTED A/S", "Ørsted A/S", True),
        ("WALMART DE MEXICO V", "Wal-Mart de México, S.A.B. de C.V.", True),
        ("DIETEREN (D) SA", "D'Ieteren Group SA", True),
        ("MOL HUNGARIAN OIL AND GAS", "MOL Magyar Olaj- és Gázipari Nyrt", True),
        ("KOC HOLDING A", "Koç Holding A.S.", True),
        ("BMW", "Bayerische Motoren Werke Aktiengesellschaft", True),
        ("DSM FIRMENICH AG", "DSM-Firmenich AG", True),
        ("AL-ELM INFORMATION SECURITY COMPAN", "Elm Company", True),
        ("TENAGA NASIONAL", "Telekom Malaysia Berhad", False),
        ("APPLE INC", "Microsoft Corporation", False),
    ],
)
def test_name_similarity(ishares, yahoo, ok, config) -> None:
    assert (name_similarity(ishares, yahoo) >= config.validation.min_name_similarity) is ok


def test_name_mismatch_excludes(config) -> None:
    ev = evaluate(company(name="APPLE INC", info={"longName": "Microsoft Corporation"}), config)
    assert ev.reason == "name_mismatch"


def test_second_share_class_is_removed(config) -> None:
    a = company(info={"longName": "Alphabet Inc."}, name="ALPHABET INC CLASS A")
    b = company(info={"longName": "Alphabet Inc."}, name="ALPHABET INC CLASS C")
    b.key = "GOOG"
    a.key = "GOOGL"
    ev_a = Evaluation("GOOGL", metrics={"avg_daily_value_eur": 50 * M})
    ev_b = Evaluation("GOOG", metrics={"avg_daily_value_eur": 30 * M})
    dedupe_share_classes([ev_a, ev_b], {"GOOGL": a, "GOOG": b})
    assert ev_a.status == RATED
    assert (ev_b.status, ev_b.reason) == ("share_class", "second_share_class")


def test_company_key_ignores_class_suffix() -> None:
    assert _company_key("Alphabet Inc. Class A", "US") == _company_key("Alphabet Inc.", "US")
    assert _company_key("Volvo AB Ser. B", "SE") == _company_key("Volvo AB", "SE")


def test_value_trap_as_flag_only(config) -> None:
    traps = config.value_trap_filters.model_copy(update={"negative_fcf_action": "flag"})
    cfg = config.model_copy(update={"value_trap_filters": traps})
    cf = company_cashflow(**{"Operating Cash Flow": [180 * M, 20 * M, 10 * M]})
    ev = evaluate(company(cashflow=cf), cfg)
    assert ev.rated
    assert "negative_fcf" in ev.flags
