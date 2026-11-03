"""LLMOps Evaluation Framework."""

from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import json


class EvaluationMetricType(str, Enum):
    """Types of evaluation metrics."""

    CORRECTNESS = "correctness"
    FAITHFULNESS = "faithfulness"
    RELEVANCE = "relevance"
    COHERENCE = "coherence"
    CONSISTENCY = "consistency"
    LATENCY = "latency"
    COST = "cost"
    COMPLETENESS = "completeness"
    SAFETY = "safety"


@dataclass
class EvaluationCriteria:
    """Criteria for evaluation."""

    metric_type: EvaluationMetricType
    threshold: float
    weight: float = 1.0
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "metric_type": self.metric_type.value,
            "threshold": self.threshold,
            "weight": self.weight,
            "enabled": self.enabled,
            "description": self.description,
        }


@dataclass
class EvaluationResult:
    """Result of evaluation."""

    metric_type: EvaluationMetricType
    score: float
    passed: bool
    threshold: float
    evidence: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "metric_type": self.metric_type.value,
            "score": self.score,
            "passed": self.passed,
            "threshold": self.threshold,
            "evidence": self.evidence,
            "details": self.details,
        }


class EvaluationDataset:
    """Dataset for evaluation."""

    def __init__(self, name: str, samples: List[Dict[str, Any]]):
        """Initialize dataset."""
        self.name = name
        self.samples = samples

    def get_samples(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get samples from dataset."""
        if count is None:
            return self.samples
        return self.samples[:count]


class Evaluator:
    """Base evaluator class."""

    def __init__(self, metric_type: EvaluationMetricType):
        """Initialize evaluator."""
        self.metric_type = metric_type

    async def evaluate(
        self,
        prediction: str,
        reference: Optional[str] = None,
        **kwargs,
    ) -> EvaluationResult:
        """Evaluate prediction."""
        raise NotImplementedError


class CorrectnessEvaluator(Evaluator):
    """Evaluator for correctness metric."""

    def __init__(self):
        """Initialize correctness evaluator."""
        super().__init__(EvaluationMetricType.CORRECTNESS)

    async def evaluate(
        self,
        prediction: str,
        reference: str,
        **kwargs,
    ) -> EvaluationResult:
        """Evaluate correctness."""
        # Simple string similarity-based evaluation
        pred_lower = prediction.lower().strip()
        ref_lower = reference.lower().strip()

        score = 1.0 if pred_lower == ref_lower else 0.5

        return EvaluationResult(
            metric_type=self.metric_type,
            score=score,
            passed=score >= 0.8,
            threshold=0.8,
            evidence=f"Prediction: {prediction[:100]}... | Reference: {reference[:100]}...",
        )


class FaithfulnessEvaluator(Evaluator):
    """Evaluator for faithfulness metric."""

    def __init__(self):
        """Initialize faithfulness evaluator."""
        super().__init__(EvaluationMetricType.FAITHFULNESS)

    async def evaluate(
        self,
        prediction: str,
        source_context: str,
        **kwargs,
    ) -> EvaluationResult:
        """Evaluate faithfulness to source context."""
        # Check if prediction is grounded in source
        key_terms = [term.strip() for term in source_context.split() if len(term) > 5]
        matched_terms = sum(1 for term in key_terms if term.lower() in prediction.lower())

        score = matched_terms / len(key_terms) if key_terms else 0.5

        return EvaluationResult(
            metric_type=self.metric_type,
            score=score,
            passed=score >= 0.7,
            threshold=0.7,
            details={"matched_terms": matched_terms, "total_terms": len(key_terms)},
        )


class RelevanceEvaluator(Evaluator):
    """Evaluator for relevance metric."""

    def __init__(self):
        """Initialize relevance evaluator."""
        super().__init__(EvaluationMetricType.RELEVANCE)

    async def evaluate(
        self,
        prediction: str,
        query: str,
        **kwargs,
    ) -> EvaluationResult:
        """Evaluate relevance to query."""
        # Simple term overlap-based relevance
        query_terms = set(query.lower().split())
        pred_terms = set(prediction.lower().split())

        overlap = len(query_terms & pred_terms)
        score = overlap / len(query_terms) if query_terms else 0.5

        return EvaluationResult(
            metric_type=self.metric_type,
            score=score,
            passed=score >= 0.6,
            threshold=0.6,
            details={"overlap": overlap, "query_terms": len(query_terms)},
        )


class EvaluationFramework:
    """Main evaluation framework."""

    def __init__(self):
        """Initialize evaluation framework."""
        self.evaluators: Dict[EvaluationMetricType, Evaluator] = {
            EvaluationMetricType.CORRECTNESS: CorrectnessEvaluator(),
            EvaluationMetricType.FAITHFULNESS: FaithfulnessEvaluator(),
            EvaluationMetricType.RELEVANCE: RelevanceEvaluator(),
        }
        self.criteria: List[EvaluationCriteria] = []
        self.results: List[EvaluationResult] = []

    def add_criteria(self, criteria: EvaluationCriteria) -> None:
        """Add evaluation criteria."""
        self.criteria.append(criteria)

    def register_evaluator(
        self,
        metric_type: EvaluationMetricType,
        evaluator: Evaluator,
    ) -> None:
        """Register custom evaluator."""
        self.evaluators[metric_type] = evaluator

    async def evaluate(
        self,
        prediction: str,
        reference: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Run evaluation against all criteria."""
        self.results = []

        for criteria in self.criteria:
            if not criteria.enabled:
                continue

            evaluator = self.evaluators.get(criteria.metric_type)
            if not evaluator:
                continue

            try:
                result = await evaluator.evaluate(
                    prediction=prediction,
                    reference=reference,
                    **kwargs,
                )
                self.results.append(result)
            except Exception as e:
                print(f"Evaluation failed for {criteria.metric_type}: {str(e)}")

        return self.get_summary()

    def get_summary(self) -> Dict[str, Any]:
        """Get evaluation summary."""
        if not self.results:
            return {
                "passed": False,
                "overall_score": 0.0,
                "metrics": [],
            }

        total_weight = sum(
            c.weight for c in self.criteria if c.enabled
        )
        weighted_score = sum(
            r.score * next(
                c.weight for c in self.criteria
                if c.metric_type == r.metric_type
            )
            for r in self.results
        ) / total_weight if total_weight > 0 else 0.0

        passed = all(r.passed for r in self.results)

        return {
            "passed": passed,
            "overall_score": weighted_score,
            "metrics": [r.to_dict() for r in self.results],
        }

    def export_results(self, format: str = "json") -> str:
        """Export evaluation results."""
        summary = self.get_summary()
        if format == "json":
            return json.dumps(summary, indent=2, default=str)
        return json.dumps(summary, default=str)


# Global evaluation framework instance
evaluation_framework = EvaluationFramework()
