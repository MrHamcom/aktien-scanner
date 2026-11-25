"""EDGAR cross-check without network: a fake fetch returns hand-written company facts."""

import json
from datetime import date

import pytest
from metric_builders import M, company_balance, company_cashflow, company_income

from scanner.core.crosscheck import check_company, compare
from scanner.core.metrics.inputs import Statement
from scanner.core.sources.edgar import EdgarClient, annual_value

FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {"units": {"USD": [
                # quarterly value (must be ignored), annual value, later restatement
                {"start": "2025-10-01", "end": "2025-12-31", "val": 260e6, "form": "10-K",
                 "filed": "2026-02-10"},
                {"start": "2025-01-01", "end": "2025-12-31", "val": 1000e6, "form": "10-K",
                 "filed": "2026-02-10"},
                {"start": "2024-01-01", "end": "2024-12-31", "val": 900e6, "form": "10-K",
                 "filed": "2025-02-10"},
            ]}},
            "NetIncomeLoss": {"units": {"USD": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 104e6, "form": "10-K",
                 "filed": "2026-02-10"},
            ]}},
            "Assets": {"units": {"USD": [
                {"end": "2025-12-31", "val": 1200e6, "form": "10-K", "filed": "2026-02-10"},
                {"end": "2025-12-31", "val": 1199e6, "form": "10-Q", "filed": "2026-02-10"},
            ]}},
            "StockholdersEquity": {"units": {"USD": [
                {"end": "2025-12-31", "val": 500e6, "form": "10-K", "filed": "2026-02-10"},
            ]}},
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 180e6, "form": "10-K",
                 "filed": "2026-02-10"},
            ]}},
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 60e6, "form": "10-K",
                 "filed": "2026-02-10"},
            ]}},
        }
    }
}
TICKERS = {"0": {"cik_str": 1234, "ticker": "TST", "title": "Testco"},
           "1": {"cik_str": 99, "ticker": "BRK-B", "title": "Berkshire"}}


def fake_fetch(url: str, headers: dict[str, str]) -> bytes:
    assert "@" in headers["User-Agent"]
    if url.endswith("company_tickers.json"):
        return json.dumps(TICKERS).encode()
    assert url.endswith("CIK0000001234.json")
    return json.dumps(FACTS).encode()


def client() -> EdgarClient:
    return EdgarClient("Test User test@example.com", fetch=fake_fetch, sleep=lambda _s: None)


def test_user_agent_required() -> None:
    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        EdgarClient("")


def test_annual_value_picks_full_year_10k() -> None:
    assert annual_value(FACTS, ("Revenues",), date(2025, 12, 31)) == 1000e6
    assert annual_value(FACTS, ("Assets",), date(2025, 12, 31), instant=True) == 1200e6
    assert annual_value(FACTS, ("Revenues",), date(2023, 12, 31)) is None


def test_cik_lookup() -> None:
    c = client()
    assert c.cik("TST") == 1234
    assert c.cik("BRK-B") == 99
    assert c.cik("NOPE") is None


@pytest.mark.parametrize(
    ("yahoo", "edgar", "status"),
    [(100.0, 101.0, "ok"), (100.0, 110.0, "deviation"), (-60.0, 60.0, "ok"),
     (None, 1.0, "yahoo_missing"), (1.0, None, "edgar_missing")],
)
def test_compare(yahoo, edgar, status) -> None:
    assert compare(yahoo, edgar)[1] == status


def test_check_company() -> None:
    statements = {"income": Statement(company_income()), "balance": Statement(company_balance()),
                  "cashflow": Statement(company_cashflow())}
    rows = {r.item: r for r in check_company(client(), "TST", statements)}
    assert rows["Umsatz"].status == "ok"
    assert rows["Bilanzsumme"].status == "ok"
    assert rows["Investitionen"].status == "ok"  # -60 (Yahoo) vs 60 (EDGAR)
    # Yahoo 100 vs EDGAR 104 -> 3.8 % deviation
    assert rows["Jahresüberschuss"].status == "deviation"
    assert rows["Jahresüberschuss"].deviation == pytest.approx(1 - 100 / 104)
    assert rows["Gezahlte Dividenden"].status == "edgar_missing"
    assert 100 * M == statements["income"].value("Net Income")
