"""Market data source adapters. All adapters return plain JSON-serialisable structures."""

from scanner.core.sources.base import (
    DATASETS,
    MarketDataSource,
    NoData,
    RateLimited,
    SourceError,
    TransientError,
)

__all__ = [
    "DATASETS",
    "MarketDataSource",
    "NoData",
    "RateLimited",
    "SourceError",
    "TransientError",
]
