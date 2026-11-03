"""Data Engineering Pipelines: Ingestion, Entity Resolution, Watchlists, and Feature Store."""

from src.data_engineering.entity_resolution import (
    EntityResolutionEngine,
    MatchCandidate,
)
from src.data_engineering.watchlist_pipeline import (
    WatchlistPipeline,
    SanctionMatch,
    SanctionScreenResult,
    DEFAULT_SANCTION_REGISTRY,
)
from src.data_engineering.document_pipeline import (
    DocumentIngestionPipeline,
)
from src.data_engineering.feature_store import (
    FeatureStore,
    HIGH_RISK_JURISDICTIONS,
)

__all__ = [
    "EntityResolutionEngine",
    "MatchCandidate",
    "WatchlistPipeline",
    "SanctionMatch",
    "SanctionScreenResult",
    "DEFAULT_SANCTION_REGISTRY",
    "DocumentIngestionPipeline",
    "FeatureStore",
    "HIGH_RISK_JURISDICTIONS",
]
