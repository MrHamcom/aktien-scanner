"""Shared types and statement item names for the metric modules."""

from __future__ import annotations

from dataclasses import dataclass, field

# Yahoo statement rows (yfinance names). Synonyms are tried in order.
REVENUE = ("Total Revenue", "Operating Revenue")
GROSS_PROFIT = ("Gross Profit",)
EBIT = ("EBIT", "Operating Income")
EBITDA = ("EBITDA", "Normalized EBITDA")
NET_INCOME = ("Net Income Common Stockholders", "Net Income")
PRETAX_INCOME = ("Pretax Income",)
TAX = ("Tax Provision",)

TOTAL_ASSETS = ("Total Assets",)
CURRENT_ASSETS = ("Current Assets",)
CURRENT_LIABILITIES = ("Current Liabilities",)
TOTAL_LIABILITIES = ("Total Liabilities Net Minority Interest",)
EQUITY = ("Stockholders Equity", "Common Stock Equity")
MINORITY_INTEREST = ("Minority Interest",)
TOTAL_DEBT = ("Total Debt",)
LONG_TERM_DEBT = ("Long Term Debt", "Long Term Debt And Capital Lease Obligation")
CASH = ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
RETAINED_EARNINGS = ("Retained Earnings",)
WORKING_CAPITAL = ("Working Capital",)
SHARES = ("Ordinary Shares Number", "Share Issued")

OPERATING_CASH_FLOW = ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
CAPEX = ("Capital Expenditure",)
FREE_CASH_FLOW = ("Free Cash Flow",)
DIVIDENDS_PAID = ("Cash Dividends Paid", "Common Stock Dividend Paid")


@dataclass
class Issue:
    """A data problem found while computing metrics. `code` is stable and used in reports."""

    code: str
    detail: str = ""


@dataclass
class MetricResult:
    values: dict[str, float | None] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)  # missing or implausible inputs
    flags: list[str] = field(default_factory=list)  # warnings shown to the user

    def missing(self, code: str, detail: str = "") -> None:
        self.issues.append(Issue(code, detail))

    def merge(self, other: MetricResult) -> MetricResult:
        self.values.update(other.values)
        self.issues.extend(other.issues)
        self.flags.extend(f for f in other.flags if f not in self.flags)
        return self


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def free_cash_flow(cashflow, year: int = 0) -> float | None:
    """Operating cash flow plus capital expenditure (capex is negative in Yahoo data)."""
    ocf = cashflow.value(OPERATING_CASH_FLOW, year)
    capex = cashflow.value(CAPEX, year)
    if ocf is not None and capex is not None:
        return ocf + capex if capex <= 0 else ocf - capex
    return cashflow.value(FREE_CASH_FLOW, year)


# Rows that must be filled for a period to count as a complete annual report
CORE_ROWS = {
    "income": ("Total Revenue", "Net Income"),
    "balance": ("Total Assets", "Stockholders Equity"),
    "cashflow": ("Operating Cash Flow",),
}
