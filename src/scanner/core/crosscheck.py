"""Cross-check of Yahoo annual figures against SEC EDGAR for US companies of a run.

Compares raw inputs (not derived metrics): if revenue, earnings, cash flow, dividends and the
balance sheet agree with the official filing, the metrics computed from them agree as well.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from scanner.core import store
from scanner.core.metrics.common import (
    CAPEX,
    DIVIDENDS_PAID,
    EQUITY,
    NET_INCOME,
    OPERATING_CASH_FLOW,
    REVENUE,
    TOTAL_ASSETS,
)
from scanner.core.metrics.inputs import Statement
from scanner.core.sources.base import SourceError
from scanner.core.sources.edgar import EdgarClient, annual_value

TOLERANCE = 0.02  # Subphase C: values may deviate at most 2 %

# item label -> (Yahoo statement, Yahoo rows, EDGAR concepts, instant?)
ITEMS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], bool]] = {
    "Umsatz": ("income", REVENUE, (
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax"), False),
    "Jahresüberschuss": ("income", NET_INCOME, (
        "NetIncomeLossAvailableToCommonStockholdersBasic", "NetIncomeLoss"), False),
    "Bilanzsumme": ("balance", TOTAL_ASSETS, ("Assets",), True),
    "Eigenkapital": ("balance", EQUITY, ("StockholdersEquity",), True),
    "Operativer Cashflow": ("cashflow", OPERATING_CASH_FLOW, (
        "NetCashProvidedByUsedInOperatingActivities",), False),
    "Investitionen": ("cashflow", CAPEX, ("PaymentsToAcquirePropertyPlantAndEquipment",), False),
    "Gezahlte Dividenden": ("cashflow", DIVIDENDS_PAID, (
        "PaymentsOfDividendsCommonStock", "PaymentsOfDividends"), False),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS crosschecks (
    run_id      INTEGER NOT NULL,
    key         TEXT    NOT NULL,
    item        TEXT    NOT NULL,
    period      TEXT,
    yahoo       REAL,
    edgar       REAL,
    deviation   REAL,
    status      TEXT    NOT NULL,  -- ok | deviation | edgar_missing | yahoo_missing | error
    PRIMARY KEY (run_id, key, item)
);
"""


@dataclass(frozen=True)
class CheckRow:
    key: str
    item: str
    period: str | None
    yahoo: float | None
    edgar: float | None
    deviation: float | None
    status: str


def compare(yahoo: float | None, edgar: float | None) -> tuple[float | None, str]:
    if yahoo is None:
        return None, "yahoo_missing"
    if edgar is None:
        return None, "edgar_missing"
    if edgar == 0:
        return (0.0, "ok") if yahoo == 0 else (None, "deviation")
    deviation = abs(abs(yahoo) / abs(edgar) - 1)  # signs differ by convention (outflows)
    return deviation, "ok" if deviation <= TOLERANCE else "deviation"


def check_company(
    client: EdgarClient, key: str, statements: dict[str, Statement]
) -> list[CheckRow]:
    cik = client.cik(key)
    if cik is None:
        return [CheckRow(key, item, None, None, None, None, "edgar_missing") for item in ITEMS]
    facts = client.company_facts(cik)
    rows = []
    for item, (kind, yahoo_rows, concepts, instant) in ITEMS.items():
        st = statements[kind]
        period = st.period_date(0)
        yahoo = st.value(yahoo_rows, 0)
        edgar = annual_value(facts, concepts, period, instant) if period else None
        deviation, status = compare(yahoo, edgar)
        rows.append(CheckRow(key, item, period.isoformat() if period else None, yahoo, edgar,
                             deviation, status))
    return rows


def run_crosscheck(
    run_id: int,
    client: EdgarClient,
    sample_size: int = 30,
    db_path: Path | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
    seed: int = 1,
) -> list[CheckRow]:
    """Check a reproducible random sample of rated US stocks of the run."""
    evaluations = {e.key: e for e in store.get_evaluations(run_id, db_path)}
    rated = {key for key, e in evaluations.items() if e.status == "rated"}
    us = sorted(e.yahoo_ticker for e in store.get_start_list(run_id, db_path)
                if e.country == "United States" and e.yahoo_ticker in rated)
    sample = sorted(random.Random(seed).sample(us, min(sample_size, len(us))))
    raw_ids = store.raw_ids_for_run(run_id, db_path)
    results: list[CheckRow] = []
    for i, key in enumerate(sample):
        if on_progress:
            on_progress(i, len(sample), key)
        ids = {kind: raw_ids.get((key, kind)) for kind in ("income", "balance", "cashflow")}
        payloads = store.load_raw_many([i for i in ids.values() if i], db_path)
        statements = {kind: Statement(payloads.get(raw_id) if raw_id else None)
                      for kind, raw_id in ids.items()}
        try:
            results.extend(check_company(client, key, statements))
        except SourceError as exc:
            results.extend(CheckRow(key, item, None, None, None, None, "error") for item in ITEMS)
            if on_progress:
                on_progress(i, len(sample), f"{key}: {exc}")
    save(run_id, results, db_path)
    return results


def save(run_id: int, rows: list[CheckRow], db_path: Path | None = None) -> None:
    with store.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM crosschecks WHERE run_id = ?", (run_id,))
        conn.executemany(
            "INSERT INTO crosschecks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(run_id, r.key, r.item, r.period, r.yahoo, r.edgar, r.deviation, r.status)
             for r in rows],
        )


def load(run_id: int, db_path: Path | None = None) -> list[CheckRow]:
    with store.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        rows = conn.execute(
            "SELECT key, item, period, yahoo, edgar, deviation, status FROM crosschecks"
            " WHERE run_id = ? ORDER BY key, item", (run_id,)
        ).fetchall()
    return [CheckRow(*r) for r in rows]
