"""Metric calculations against hand-computed values (see tests/metric_builders.py)."""

from datetime import date

import pytest
from metric_builders import (
    AS_OF,
    M,
    company,
    company_balance,
    company_cashflow,
    company_income,
    history,
    momentum_closes,
)

from scanner.core.metrics import dividend, market, momentum, quality, value
from scanner.core.metrics.inputs import FxRates, Statement, fx_pair, main_currency


def test_value_factor_by_hand(config) -> None:
    # EV = 2000 + 300 debt - 100 cash = 2200 Mio; EBIT 150 -> 6.818 %; FCF 180-60=120 -> 6 %
    r = value.compute(company(), 2000 * M)
    assert r.values["enterprise_value_eur"] == pytest.approx(2200 * M)
    assert r.values["earnings_yield"] == pytest.approx(150 / 2200)
    assert r.values["fcf_yield"] == pytest.approx(0.06)
    assert not r.issues


def test_quality_factor_by_hand(config) -> None:
    r = quality.compute(company(), 2000 * M, config.validation)
    # tax 32.5/130 = 25 %; NOPAT 112.5; invested capital 300+500-100 = 700
    assert r.values["roic"] == pytest.approx(112.5 / 700)
    # all nine Piotroski signals are positive by construction
    assert r.values["piotroski"] == pytest.approx(9)
    assert r.values["piotroski_signals"] == 9
    assert r.values["net_debt_to_ebitda"] == pytest.approx(1.0)
    # 1.2*250/1200 + 1.4*400/1200 + 3.3*150/1200 + 0.6*2000/700 + 1000/1200
    expected_z = 0.25 + 1.4 * 400 / 1200 + 0.4125 + 0.6 * 2000 / 700 + 1000 / 1200
    assert r.values["altman_z"] == pytest.approx(expected_z)
    assert r.values["altman_z"] == pytest.approx(3.676786, abs=1e-6)
    assert r.values["negative_fcf_years"] == 0
    assert r.values["share_change_1y"] == pytest.approx(0.0)
    assert not r.issues


def test_piotroski_counts_failed_signals(config) -> None:
    s = company(income=company_income(**{"Net Income": [-10 * M, 80 * M]}),
               balance=company_balance(**{"Ordinary Shares Number": [120 * M, 100 * M]}))
    score, available, failed = quality.piotroski(s)
    assert available == 9
    assert {"roa_positive", "roa_improved", "no_dilution"} <= set(failed)
    assert score == pytest.approx(9 - len(failed))


def test_piotroski_scaled_when_gross_profit_missing(config) -> None:
    s = company(income=company_income(**{"Gross Profit": [None, None]}))
    score, available, _ = quality.piotroski(s)
    assert available == 8
    assert score == pytest.approx(9.0)


def test_net_debt_with_negative_ebitda_is_worst(config) -> None:
    s = company(income=company_income(EBITDA=[-5 * M, 10 * M]))
    assert quality.net_debt_to_ebitda(s) == quality.NET_DEBT_EBITDA_WORST


def test_net_cash_gives_negative_ratio(config) -> None:
    s = company(balance=company_balance(**{"Cash And Cash Equivalents": [500 * M, 80 * M]}))
    assert quality.net_debt_to_ebitda(s) == pytest.approx((300 - 500) / 200)


def test_tax_rate_falls_back_when_not_meaningful() -> None:
    s = company(income=company_income(**{"Tax Provision": [80 * M, 0],
                                         "Pretax Income": [100 * M, 1]}))
    assert quality.tax_rate(s) == quality.DEFAULT_TAX_RATE


def test_momentum_by_hand() -> None:
    s = company(hist=history(momentum_closes()))
    r = momentum.compute(s)
    # price 21 trading days ago = 100, 253 days ago = 80 -> +25 %
    assert r.values["momentum_12_1"] == pytest.approx(0.25)
    # SMA200 = (179 x 100 + 21 x 110) / 200 = 101.05
    assert r.values["sma200_distance"] == pytest.approx(110 / 101.05 - 1)


def test_momentum_needs_one_year() -> None:
    r = momentum.compute(company(hist=history([20.0] * 200)))
    assert r.values["momentum_12_1"] is None
    assert r.issues[0].code == "price_history_short"


def test_market_values(config) -> None:
    r = market.compute(company(), config.validation, 20)
    assert r.values["market_cap_eur"] == pytest.approx(2000 * M)
    assert r.values["avg_daily_value_eur"] == pytest.approx(20 * 1_000_000)
    assert not r.issues


def test_market_cap_mismatch_is_reported(config) -> None:
    r = market.compute(company(info={"marketCap": 9000 * M}), config.validation, 20)
    assert [i.code for i in r.issues] == ["market_cap_mismatch"]


def test_share_jump_is_reported(config) -> None:
    s = company(balance=company_balance(**{"Ordinary Shares Number": [300 * M, 100 * M]}))
    assert "shares_jump" in [i.code for i in market.compute(s, config.validation, 20).issues]


# --- currencies --------------------------------------------------------------------------


def test_minor_units() -> None:
    assert main_currency("GBp") == ("GBP", 0.01)
    assert main_currency("ZAc") == ("ZAR", 0.01)
    assert main_currency("usd") == ("USD", 1.0)
    assert fx_pair("GBp") == "GBPEUR=X"
    assert fx_pair("EUR") is None


def test_pence_quote_with_pound_statements(config) -> None:
    # price 2,000 pence = 20 GBP; 1 GBP = 1.2 EUR -> market cap 100 Mio x 20 x 1.2 = 2.4 Mrd €
    # (Yahoo reports the market cap in pounds, the price in pence)
    s = company(hist=history([2000.0] * 300, currency="GBp"),
               info={"currency": "GBp", "financialCurrency": "GBP", "marketCap": 2000 * M},
               fx={"GBP": 1.2})
    r = market.compute(s, config.validation, 20)
    assert r.values["market_cap_eur"] == pytest.approx(2400 * M)
    v = value.compute(s, r.values["market_cap_eur"])
    # EV = 2400 + (300 - 100) x 1.2 = 2640 Mio €; EBIT 150 x 1.2 = 180
    assert v.values["earnings_yield"] == pytest.approx(180 / 2640)


def test_reporting_currency_differs_from_quote(config) -> None:
    # Hong Kong listing in HKD, reports in CNY
    s = company(hist=history([20.0] * 300, currency="HKD"),
               info={"currency": "HKD", "financialCurrency": "CNY"},
               fx={"HKD": 0.11, "CNY": 0.12})
    assert s.quote_to_eur() == pytest.approx(0.11)
    assert s.financial_to_eur() == pytest.approx(0.12)
    v = value.compute(s, 2000 * M * 0.11)
    assert v.values["ebit_eur"] == pytest.approx(150 * M * 0.12)


def test_missing_fx_fails_closed(config) -> None:
    s = company(hist=history([20.0] * 300, currency="USD"), info={"currency": "USD"})
    assert market.compute(s, config.validation, 20).issues[0].code == "fx_missing"


def test_fx_rates_from_payloads() -> None:
    fx = FxRates.from_payloads({"USDEUR=X": {"date": ["a", "b"], "close": [0.9, 0.92]}})
    assert fx.to_eur("USD") == pytest.approx(0.92)
    assert fx.to_eur("EUR") == 1.0
    assert fx.to_eur("JPY") is None


def test_statement_drops_empty_trailing_period() -> None:
    st = Statement({"periods": ["2025-12-31", "2024-12-31", "2021-12-31"],
                    "items": ["EBIT"], "values": [[1.0, 2.0, None]]})
    assert st.periods == ["2025-12-31", "2024-12-31"]
    assert st.value("EBIT", 1) == 2.0
    assert st.period_date(0) == date(2025, 12, 31)


# --- dividends -----------------------------------------------------------------------------


def annual_payer() -> list[tuple[str, float]]:
    amounts = [1.0, 1.0, 1.1, 1.2, 1.2, 1.3, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8]
    return [(f"{2015 + i}-05-10", a) for i, a in enumerate(amounts)]


def test_dividend_annual_payer_by_hand(config) -> None:
    s = company(hist=history([30.0] * 300, annual_payer()))
    r = dividend.compute(s, config.dividend)
    assert r.values["dividend_frequency"] == 1
    assert r.values["dividend_per_share"] == pytest.approx(1.8)
    assert r.values["dividend_yield"] == pytest.approx(0.06)
    # 2016..2026 complete dividend years -> 10 comparisons without a cut
    assert r.values["dividend_streak"] == 10
    assert r.values["dividend_growth"] == pytest.approx((1.8 / 1.3) ** 0.2 - 1)
    # payout: 50 / 120 FCF; 3 years (50+45+40)/(120+100+100); earnings 50/100
    assert r.values["payout_fcf"] == pytest.approx(50 / 120)
    assert r.values["payout_fcf_3y"] == pytest.approx(135 / 320)
    assert r.values["payout_earnings"] == pytest.approx(0.5)
    assert r.flags == []


def test_dividend_year_boundary_absorbs_shifted_payment(config) -> None:
    payments = []
    for year in range(2018, 2026):
        payments.append((f"{year}-06-15", 0.5))
        payments.append((f"{year}-12-15", 0.5) if year != 2023 else ("2024-01-05", 0.5))
    payments.append(("2026-06-15", 0.5))
    hist = dividend.analyse(
        [(date.fromisoformat(d), a) for d, a in payments], AS_OF, config.dividend
    )
    assert hist.frequency == 2
    # every complete dividend year sums to 1.0 although one payment slipped into January
    complete = {y: v for y, v in hist.annual.items() if y >= 2020}
    assert set(complete.values()) == {1.0}
    r = dividend.compute(company(hist=history([20.0] * 300, payments)), config.dividend)
    assert "dividend_cut" not in r.flags


def test_quarterly_payer_with_special_dividend(config) -> None:
    payments = [(f"{y}-{m:02d}-10", 0.5) for y in range(2019, 2027) for m in (2, 5, 8, 11)]
    payments.append(("2025-12-20", 3.0))  # special: 6x the usual amount
    s = company(hist=history([40.0] * 300, sorted(payments)))
    r = dividend.compute(s, config.dividend)
    assert r.values["dividend_frequency"] == 4
    assert r.values["dividend_per_share"] == pytest.approx(2.0)
    assert r.values["dividend_yield"] == pytest.approx(0.05)
    assert r.values["special_dividends_5y"] == 1


def test_extra_payment_next_to_regular_one_is_special(config) -> None:
    payments = [(f"{y}-05-10", 1.0) for y in range(2015, 2027)] + [("2024-06-01", 0.8)]
    hist = dividend.analyse(
        [(date.fromisoformat(d), a) for d, a in sorted(payments)], AS_OF, config.dividend
    )
    assert [a for _, a in hist.specials] == [0.8]


def test_dividend_cut_is_flagged(config) -> None:
    payments = [(f"{y}-05-10", 1.0) for y in range(2015, 2026)] + [("2026-05-10", 0.5)]
    r = dividend.compute(company(hist=history([20.0] * 300, payments)), config.dividend)
    assert "dividend_cut" in r.flags
    assert r.values["dividend_streak"] == 0


def test_suspended_dividend(config) -> None:
    payments = [(f"{y}-05-10", 1.0) for y in range(2015, 2026)]  # nothing since May 2025
    r = dividend.compute(company(hist=history([20.0] * 300, payments)), config.dividend)
    assert r.values["is_payer"] == 0
    assert r.values["dividend_yield"] == 0
    assert "dividend_suspended" in r.flags


def test_non_payer_is_valid_not_missing(config) -> None:
    r = dividend.compute(company(), config.dividend)
    assert r.values["is_payer"] == 0 and r.values["dividend_yield"] == 0
    assert not r.issues and not r.flags


def test_dividend_traps(config) -> None:
    # yield 12 %, FCF does not cover the dividend, shares +20 % in 3 years
    payments = [(f"{y}-05-10", 2.4) for y in range(2015, 2027)]
    s = company(
        hist=history([20.0] * 300, payments),
        cashflow=company_cashflow(**{"Cash Dividends Paid": [-240 * M, -240 * M, -240 * M]}),
        balance=company_balance(**{"Ordinary Shares Number": [120 * M, 110 * M, 105 * M, 100 * M]}),
    )
    r = dividend.compute(s, config.dividend)
    assert {"dividend_yield_high", "dividend_not_covered", "dividend_share_funded"} <= set(r.flags)


def test_implausible_yield_is_an_issue(config) -> None:
    # e.g. dividends in pounds but prices in pence mixed up the other way round
    payments = [(f"{y}-05-10", 10.0) for y in range(2015, 2027)]
    r = dividend.compute(company(hist=history([20.0] * 300, payments)), config.dividend)
    assert "dividend_implausible" in [i.code for i in r.issues]


def test_cut_day_in_middle_of_largest_gap() -> None:
    may = [(date(2021, 5, 10), 1.0)]  # day 130
    assert dividend.cut_day_of_year(may) == (130 + 182) % 365


def test_statement_accepts_camel_case_rows() -> None:
    # yfinance get_balance_sheet() returns "CashAndCashEquivalents", not "Cash And ..."
    st = Statement({"periods": ["2025-12-31"], "items": ["CashAndCashEquivalents", "EBIT"],
                    "values": [[5.0], [7.0]]})
    assert st.value(("Cash And Cash Equivalents",)) == 5.0
    assert st.value("EBIT") == 7.0


def test_statement_drops_newest_period_without_core_rows() -> None:
    # Yahoo lists a just-ended fiscal year whose figures are still empty
    st = Statement({"periods": ["2026-10-31", "2025-10-31"],
                    "items": ["TotalRevenue", "NetIncome", "EBIT"],
                    "values": [[None, 100.0], [None, 10.0], [None, 15.0]]},
                   ("Total Revenue", "Net Income"))
    assert st.periods == ["2025-10-31"]
    assert st.value("EBIT") == 15.0
    assert st.dropped_periods == ["2026-10-31"]


def test_statement_keeps_periods_when_core_row_is_absent() -> None:
    # some reports have no "Operating Cash Flow" row at all – that is not an empty period
    st = Statement({"periods": ["2026-06-30"], "items": ["FreeCashFlow"], "values": [[5.0]]},
                   ("Operating Cash Flow",))
    assert st.periods == ["2026-06-30"]
