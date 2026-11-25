"""Data coverage of a run, per region – the basis for the Subphase B exit criteria."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from scanner.core import store
from scanner.core.sources.base import DATASETS

UNKNOWN_REGION = "ohne Region"


@dataclass
class RegionCoverage:
    region: str
    listed: int = 0
    unmapped: int = 0
    excluded: int = 0
    included: int = 0
    loaded: Counter = field(default_factory=Counter)  # dataset -> count ok/cached
    complete: int = 0

    def share(self, dataset: str) -> float | None:
        return self.loaded[dataset] / self.included if self.included else None

    @property
    def complete_share(self) -> float | None:
        return self.complete / self.included if self.included else None


@dataclass
class Coverage:
    regions: list[RegionCoverage]
    total: RegionCoverage
    failure_reasons: list[tuple[str, int, list[str]]]  # reason, count, example keys
    unmapped_exchanges: list[tuple[str, int]]
    fx_failed: list[str]


def compute(run_id: int, db_path: Path | None = None) -> Coverage:
    entries = store.get_start_list(run_id, db_path=db_path)
    items = store.item_statuses(run_id, db_path=db_path)

    good: dict[str, set[str]] = defaultdict(set)
    reasons: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    fx_failed: list[str] = []
    for key, dataset, status, reason in items:
        if status in {"ok", "cached"}:
            good[key].add(dataset)
        elif status == "failed":
            if dataset == "fx":
                fx_failed.append(key)
            label = f"{dataset}: {reason}"
            reasons[label] += 1
            if len(examples[label]) < 200:
                examples[label].append(key)

    by_region: dict[str, RegionCoverage] = {}
    total = RegionCoverage(region="Gesamt")
    unmapped_exchanges: Counter = Counter()
    for entry in entries:
        region = entry.region or UNKNOWN_REGION
        cov = by_region.setdefault(region, RegionCoverage(region=region))
        for target in (cov, total):
            target.listed += 1
            if entry.status == "unmapped":
                target.unmapped += 1
            elif entry.status == "excluded":
                target.excluded += 1
            else:
                target.included += 1
                loaded = good.get(entry.yahoo_ticker or "", set())
                for dataset in DATASETS:
                    if dataset in loaded:
                        target.loaded[dataset] += 1
                if loaded >= set(DATASETS):
                    target.complete += 1
        if entry.status == "unmapped" and entry.reason and entry.reason.startswith("exchange"):
            unmapped_exchanges[entry.exchange] += 1

    regions = sorted(by_region.values(), key=lambda c: c.listed, reverse=True)
    failure_list = [(label, count, examples[label]) for label, count in reasons.most_common()]
    return Coverage(
        regions=regions,
        total=total,
        failure_reasons=failure_list,
        unmapped_exchanges=unmapped_exchanges.most_common(),
        fx_failed=fx_failed,
    )
