"""Hallucination, Groundedness, and Citation Evaluation Framework."""

import re
import logging
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class GroundednessEvaluationResult:
    is_grounded: bool
    groundedness_score: float  # 0.0 to 1.0
    unsupported_claims: List[str] = field(default_factory=list)
    valid_citations: List[str] = field(default_factory=list)
    missing_citations: List[str] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=datetime.utcnow)


class HallucinationEvaluator:
    """Evaluates agent-generated claims against retrieved source documents and evidence."""

    def __init__(self, min_groundedness_score: float = 0.80):
        self.min_groundedness_score = min_groundedness_score

    def evaluate_groundedness(
        self,
        generated_text: str,
        source_context: str,
        structured_evidence: Optional[Dict[str, Any]] = None,
    ) -> GroundednessEvaluationResult:
        """Evaluate if the assertions in generated_text are grounded in source_context."""
        if not generated_text:
            return GroundednessEvaluationResult(is_grounded=True, groundedness_score=1.0)

        # 1. Break generated response into sentences / claims
        sentences = [
            s.strip()
            for s in re.split(r"[.\n]", generated_text)
            if len(s.strip()) > 15 and not s.strip().startswith(("#", "-", "*", "|"))
        ]

        if not sentences:
            return GroundednessEvaluationResult(is_grounded=True, groundedness_score=1.0)

        source_lower = source_context.lower()
        if structured_evidence:
            source_lower += " " + str(structured_evidence).lower()

        unsupported: List[str] = []
        supported_count = 0

        for sentence in sentences:
            # Extract key nouns and alphanumeric tokens (e.g. IDs, amounts, names)
            tokens = [t.lower() for t in re.findall(r"\b[A-Za-z0-9\-_]{4,}\b", sentence)]
            if not tokens:
                supported_count += 1
                continue

            # Check overlap with source
            overlap = sum(1 for t in tokens if t in source_lower)
            overlap_ratio = overlap / len(tokens)

            # Heuristic groundedness threshold per sentence
            if overlap_ratio >= 0.40:
                supported_count += 1
            else:
                unsupported.append(sentence)

        groundedness_score = supported_count / len(sentences)

        # 2. Check for citations
        citation_pattern = r"\[(?:Evidence|Doc|Page|Source|Registry|ID)[^\]]+\]"
        citations_found = re.findall(citation_pattern, generated_text, re.IGNORECASE)

        is_grounded = groundedness_score >= self.min_groundedness_score

        return GroundednessEvaluationResult(
            is_grounded=is_grounded,
            groundedness_score=round(groundedness_score, 4),
            unsupported_claims=unsupported[:5],
            valid_citations=citations_found,
            missing_citations=["Missing citation for numerical assertion"] if not citations_found and "score" in generated_text.lower() else [],
        )
