"""Watchlist and Sanctions Data Pipeline: OFAC, UN, EU, and PEP screening."""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from src.data_engineering.entity_resolution import EntityResolutionEngine, MatchCandidate

logger = logging.getLogger(__name__)


@dataclass
class SanctionMatch:
    list_name: str
    entry_id: str
    sanctioned_entity_name: str
    country: Optional[str]
    match_score: float
    match_type: str
    programs: List[str] = field(default_factory=list)


@dataclass
class SanctionScreenResult:
    has_hit: bool
    is_exact_block: bool
    highest_match_score: float
    matches: List[SanctionMatch] = field(default_factory=list)
    screened_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def hits(self) -> List[SanctionMatch]:
        """Convenience alias for matches."""
        return self.matches


# Baseline known high-profile sanctioned benchmark entities for demonstration & testing
DEFAULT_SANCTION_REGISTRY: List[Dict[str, Any]] = [
    {
        "id": "OFAC-9812",
        "name": "Rosneft Oil Company",
        "country": "RU",
        "list": "OFAC_SDN",
        "programs": ["UKRAINE-EO13662"],
        "tax_id": "RU7706107510",
    },
    {
        "id": "OFAC-10294",
        "name": "VTB Bank Public Joint Stock Company",
        "country": "RU",
        "list": "OFAC_SDN",
        "programs": ["RUSSIA-EO14024"],
        "tax_id": "RU7702070139",
    },
    {
        "id": "OFAC-4412",
        "name": "Huawei Technologies Co., Ltd.",
        "country": "CN",
        "list": "ENTITY_LIST",
        "programs": ["EXPORT_CONTROL"],
        "tax_id": "CN914403001922038216",
    },
    {
        "id": "UN-8821",
        "name": "Korea Ryonbong General Corporation",
        "country": "KP",
        "list": "UN_CONSOLIDATED",
        "programs": ["DPRK"],
        "tax_id": "KP99881122",
    },
    {
        "id": "PEP-0012",
        "name": "Viktor Petrov Trading Group",
        "country": "UA",
        "list": "PEP_DATABASE",
        "programs": ["PEP_TIER_1"],
        "tax_id": "UA38192019",
    },
]


class WatchlistPipeline:
    """Manages ingestion, caching, and matching against sanctions and PEP registries."""

    def __init__(self, fuzzy_threshold: float = 0.85):
        self.registry: List[Dict[str, Any]] = list(DEFAULT_SANCTION_REGISTRY)
        self.entity_resolver = EntityResolutionEngine(fuzzy_threshold=fuzzy_threshold)

    def load_watchlist(self, records: List[Dict[str, Any]]) -> int:
        """Load external watchlist records into the memory index."""
        self.registry.extend(records)
        logger.info(f"Loaded {len(records)} records into watchlist index. Total: {len(self.registry)}")
        return len(self.registry)

    def screen_entity(
        self,
        name: str,
        tax_id: Optional[str] = None,
        country: Optional[str] = None,
    ) -> SanctionScreenResult:
        """Screen an entity against all loaded watchlists."""
        matches: List[SanctionMatch] = []
        highest_score = 0.0
        exact_block = False

        candidates = self.entity_resolver.match_against_registry(
            query_name=name,
            query_tax_id=tax_id,
            known_registry=self.registry,
        )

        for cand in candidates:
            # Locate record metadata
            rec = next((r for r in self.registry if str(r.get("id", "")) == cand.target_id), {})
            programs = rec.get("programs", [])
            list_name = rec.get("list", "SANCTIONS_LIST")

            highest_score = max(highest_score, cand.similarity_score)
            if cand.similarity_score >= 0.98 or cand.match_type == "EXACT_TAX_ID_MATCH":
                exact_block = True

            matches.append(
                SanctionMatch(
                    list_name=list_name,
                    entry_id=cand.target_id,
                    sanctioned_entity_name=cand.target_name,
                    country=rec.get("country"),
                    match_score=cand.similarity_score,
                    match_type=cand.match_type,
                    programs=programs,
                )
            )

        return SanctionScreenResult(
            has_hit=len(matches) > 0,
            is_exact_block=exact_block,
            highest_match_score=highest_score,
            matches=matches,
        )

    def screen_vendor(
        self,
        name: str,
        country: Optional[str] = None,
        tax_id: Optional[str] = None,
    ) -> SanctionScreenResult:
        """Screen vendor by name, country, and optional tax_id."""
        return self.screen_entity(name=name, tax_id=tax_id, country=country)
