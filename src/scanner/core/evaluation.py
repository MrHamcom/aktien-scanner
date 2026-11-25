"""Evaluate all stocks of a run from the stored raw data (no network access).

Can be repeated for any finished run, e.g. after a rule or bug fix, without loading data again.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from scanner.config import ScannerConfig
from scanner.core import store
from scanner.core.metrics.inputs import FxRates, PriceHistory, Statement, StockInputs, fx_pair
from scanner.core.sources.base import DATASETS
from scanner.core.validate import RATED, STAGES, Evaluation, evaluate

FX_MAX_AGE = timedelta(days=7)


@dataclass
class EvaluationSummary:
    run_id: int
    total: int = 0
    rated: int = 0
    by_stage: Counter = field(default_factory=Counter)

    @property
    def message(self) -> str:
        return f"{self.rated} von {self.total} Aktien bewertbar"


def needed_fx_pairs(infos: list[dict], quote_currencies: list[str | None]) -> set[str]:
    currencies = set(quote_currencies)
    currencies.update(i.get("financialCurrency") for i in infos if i)
    return {p for c in currencies if (p := fx_pair(c))}


def _fx_rates(run_id: int, pairs: set[str], raw_ids: dict[tuple[str, str], int],
              db_path: Path | None) -> FxRates:
    ids: dict[str, int] = {}
    for pair in pairs:
        raw_id = raw_ids.get((pair, "fx")) or store.fresh_raw_id(pair, "fx", FX_MAX_AGE, db_path)
        if raw_id is not None:
            ids[pair] = raw_id
    payloads = store.load_raw_many(list(ids.values()), db_path)
    return FxRates.from_payloads({pair: payloads[i] for pair, i in ids.items() if i in payloads})


_COMPANY_SUFFIX = re.compile(r"\b(class|cl|series|ser)\.?\s+[a-z]\b|\b(adr|ord|pref|reg)\b")


def _company_key(name: str, country: str) -> str:
    cleaned = _COMPANY_SUFFIX.sub(" ", name.casefold())
    return f"{country}|{' '.join(re.findall(r'[a-z0-9]+', cleaned))}"


def dedupe_share_classes(evaluations: list[Evaluation], inputs: dict[str, StockInputs]) -> None:
    """Keep one share class per company: the most liquid one (rule: one class per company)."""
    groups: dict[str, list[Evaluation]] = defaultdict(list)
    for ev in evaluations:
        if ev.status not in (RATED, "value_trap"):
            continue
        s = inputs[ev.key]
        name = str(s.info.get("longName") or s.info.get("shortName") or s.name)
        groups[_company_key(name, s.country)].append(ev)
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda e: e.metrics.get("avg_daily_value_eur") or 0.0, reverse=True)
        keeper = members[0]
        for ev in members[1:]:
            ev.status, ev.reason, ev.detail = (
                "share_class", "second_share_class", f"weitere Gattung von {keeper.key}"
            )


def evaluate_run(
    run_id: int,
    config: ScannerConfig,
    db_path: Path | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> EvaluationSummary:
    run = store.get_run(run_id, db_path)
    if run is None:
        raise ValueError(f"Lauf {run_id} nicht gefunden")
    as_of = run.started_at.date()
    entries = [e for e in store.get_start_list(run_id, db_path)
               if e.status == "included" and e.yahoo_ticker]
    raw_ids = store.raw_ids_for_run(run_id, db_path)

    wanted = [raw_ids[(e.yahoo_ticker, d)] for e in entries for d in DATASETS
              if (e.yahoo_ticker, d) in raw_ids]
    payloads = store.load_raw_many(wanted, db_path)

    def payload(key: str, dataset: str):
        raw_id = raw_ids.get((key, dataset))
        return payloads.get(raw_id) if raw_id is not None else None

    infos = [payload(e.yahoo_ticker or "", "info") or {} for e in entries]
    fx = _fx_rates(run_id, needed_fx_pairs(infos, [e.currency for e in entries]), raw_ids,
                   db_path)

    evaluations: list[Evaluation] = []
    inputs: dict[str, StockInputs] = {}
    for i, entry in enumerate(entries):
        key = entry.yahoo_ticker or ""
        if on_progress:
            on_progress(i, len(entries), f"{key} – {entry.name}")
        history = payload(key, "history")
        s = StockInputs(
            key=key, name=entry.name or "", sector=entry.sector or "",
            country=entry.country or "", region=entry.region,
            history=PriceHistory.from_payload(history) if history else None,
            info=payload(key, "info") or {},
            income=Statement(payload(key, "income")),
            balance=Statement(payload(key, "balance")),
            cashflow=Statement(payload(key, "cashflow")),
            fx=fx, as_of=as_of,
        )
        inputs[key] = s
        missing = [d for d in DATASETS if (key, d) not in raw_ids]
        evaluations.append(evaluate(s, config, missing))

    dedupe_share_classes(evaluations, inputs)

    store.save_evaluations(run_id, [
        store.EvaluationRow(
            key=ev.key, status=ev.status, reason=ev.reason, detail=ev.detail,
            issues=[(i.code, i.detail) for i in ev.issues], flags=ev.flags, metrics=ev.metrics,
        )
        for ev in evaluations
    ], db_path)

    summary = EvaluationSummary(run_id=run_id, total=len(evaluations))
    for ev in evaluations:
        summary.by_stage[ev.status] += 1
    summary.rated = summary.by_stage[RATED]
    return summary


__all__ = ["STAGES", "EvaluationSummary", "ExclusionReport", "evaluate_run", "exclusion_report",
           "needed_fx_pairs"]


@dataclass
class ExclusionReport:
    """Exclusion funnel per region and the reasons behind it (for the data quality page)."""

    regions: dict[str, Counter]  # region -> stage/rated -> count
    reasons: list[tuple[str, str, int, list[str]]]  # stage, reason, count, tickers
    flags: Counter

    @property
    def total(self) -> Counter:
        result: Counter = Counter()
        for counts in self.regions.values():
            result.update(counts)
        return result


def exclusion_report(run_id: int, db_path: Path | None = None) -> ExclusionReport | None:
    rows = store.get_evaluations(run_id, db_path)
    if not rows:
        return None
    region_of = {e.yahoo_ticker: e.region or "ohne Region"
                 for e in store.get_start_list(run_id, db_path) if e.yahoo_ticker}
    regions: dict[str, Counter] = defaultdict(Counter)
    reasons: dict[tuple[str, str], list[str]] = defaultdict(list)
    flags: Counter = Counter()
    for row in rows:
        regions[region_of.get(row.key, "ohne Region")][row.status] += 1
        if row.status != RATED:
            reasons[(row.status, row.reason or "")].append(row.key)
        else:
            flags.update(row.flags)
    ordered = sorted(reasons.items(),
                     key=lambda kv: (STAGES.index(kv[0][0]) if kv[0][0] in STAGES else 99,
                                     -len(kv[1])))
    return ExclusionReport(
        regions=dict(sorted(regions.items(), key=lambda kv: -sum(kv[1].values()))),
        reasons=[(stage, reason, len(keys), sorted(keys)) for (stage, reason), keys in ordered],
        flags=flags,
    )
