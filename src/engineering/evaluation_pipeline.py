"""Evaluation Pipeline - Comprehensive metrics and evaluation framework for RAG/Agent quality."""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import asyncio
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Types of metrics."""

    RELEVANCE = "relevance"
    ACCURACY = "accuracy"
    PRECISION = "precision"
    RECALL = "recall"
    F1_SCORE = "f1_score"
    LATENCY = "latency"
    THROUGHPUT = "throughput"
    COVERAGE = "coverage"
    CONSISTENCY = "consistency"
    HALLUCINATION = "hallucination"


@dataclass
class EvaluationMetric:
    """Single evaluation metric."""

    name: str
    metric_type: MetricType
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_passed: bool = True
    error: Optional[str] = None

    def __repr__(self) -> str:
        return f"{self.name}: {self.value:.4f}"


@dataclass
class EvaluationResult:
    """Results from evaluation run."""

    evaluation_id: str
    test_case_id: str
    metrics: List[EvaluationMetric] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    passed: bool = True
    notes: str = ""

    def get_duration(self) -> float:
        """Get evaluation duration."""
        end = self.end_time or datetime.utcnow()
        return (end - self.start_time).total_seconds()

    def get_metric_by_name(self, name: str) -> Optional[EvaluationMetric]:
        """Get metric by name."""
        return next((m for m in self.metrics if m.name == name), None)

    def get_summary(self) -> Dict[str, float]:
        """Get summary of all metrics."""
        return {m.name: m.value for m in self.metrics}


class MetricEvaluator(ABC):
    """Abstract base class for metric evaluators."""

    @abstractmethod
    async def evaluate(
        self,
        predicted: str,
        reference: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Evaluate and return metric value (0-1)."""
        pass


class RelevanceEvaluator(MetricEvaluator):
    """Evaluate relevance of response to query."""

    def __init__(self, threshold: float = 0.5):
        """Initialize relevance evaluator.

        Args:
            threshold: Relevance score threshold
        """
        self.threshold = threshold

    async def evaluate(
        self,
        predicted: str,
        reference: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Evaluate relevance."""
        if not predicted or not context or "query" not in context:
            return 0.0

        query = context["query"].lower()
        predicted_lower = predicted.lower()

        # Simple keyword matching relevance
        query_terms = set(query.split())
        predicted_terms = set(predicted_lower.split())

        if not query_terms:
            return 1.0

        matching_terms = query_terms & predicted_terms
        relevance = len(matching_terms) / len(query_terms)

        return min(relevance, 1.0)


class AccuracyEvaluator(MetricEvaluator):
    """Evaluate accuracy of response against reference."""

    async def evaluate(
        self,
        predicted: str,
        reference: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Evaluate accuracy."""
        if not reference:
            return 0.0

        # Exact match
        if predicted.strip().lower() == reference.strip().lower():
            return 1.0

        # Partial match (word-level)
        pred_words = set(predicted.lower().split())
        ref_words = set(reference.lower().split())

        if not ref_words:
            return 0.0

        matching = len(pred_words & ref_words)
        accuracy = matching / len(ref_words)

        return min(accuracy, 1.0)


class HallucinationEvaluator(MetricEvaluator):
    """Evaluate hallucination (unsupported claims)."""

    def __init__(self):
        """Initialize hallucination evaluator."""
        # Simple keyword check for hallucination indicators
        self.hallucination_indicators = [
            "i'm not sure",
            "i believe",
            "it seems",
            "probably",
            "maybe",
        ]

    async def evaluate(
        self,
        predicted: str,
        reference: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Evaluate hallucination score (0 = no hallucination, 1 = high)."""
        if not predicted:
            return 0.0

        predicted_lower = predicted.lower()

        # Count uncertainty indicators
        indicator_count = sum(
            1 for indicator in self.hallucination_indicators
            if indicator in predicted_lower
        )

        hallucination_score = min(indicator_count / 5.0, 1.0)

        return hallucination_score


class LatencyEvaluator(MetricEvaluator):
    """Evaluate response latency."""

    def __init__(self, target_latency_ms: float = 1000.0):
        """Initialize latency evaluator.

        Args:
            target_latency_ms: Target latency in milliseconds
        """
        self.target_latency_ms = target_latency_ms

    async def evaluate(
        self,
        predicted: str,
        reference: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Evaluate latency score."""
        if not context or "latency_ms" not in context:
            return 0.5

        latency_ms = context["latency_ms"]

        # Score: 1.0 if within target, decreases as latency increases
        if latency_ms <= self.target_latency_ms:
            return 1.0

        excess_ratio = latency_ms / self.target_latency_ms
        score = max(1.0 - (excess_ratio - 1.0) * 0.1, 0.0)

        return score


class CoverageEvaluator(MetricEvaluator):
    """Evaluate coverage of topics in response."""

    async def evaluate(
        self,
        predicted: str,
        reference: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Evaluate coverage."""
        if not context or "required_topics" not in context:
            return 0.5

        required_topics = context["required_topics"]
        if not required_topics:
            return 1.0

        predicted_lower = predicted.lower()

        covered_topics = sum(
            1 for topic in required_topics
            if topic.lower() in predicted_lower
        )

        coverage = covered_topics / len(required_topics)

        return min(coverage, 1.0)


class EvaluationPipeline:
    """Complete evaluation pipeline for multi-agent RAG system."""

    def __init__(self, name: str):
        """Initialize evaluation pipeline.

        Args:
            name: Pipeline name
        """
        self.name = name
        self.evaluators: Dict[str, MetricEvaluator] = {}
        self.results: List[EvaluationResult] = []
        self.thresholds: Dict[str, float] = {}

    def register_evaluator(
        self,
        metric_name: str,
        evaluator: MetricEvaluator,
        threshold: float = 0.5,
    ) -> "EvaluationPipeline":
        """Register a metric evaluator.

        Args:
            metric_name: Name of metric
            evaluator: Metric evaluator instance
            threshold: Pass/fail threshold (0-1)
        """
        self.evaluators[metric_name] = evaluator
        self.thresholds[metric_name] = threshold
        logger.info(f"Registered evaluator: {metric_name}")
        return self

    async def evaluate(
        self,
        test_case_id: str,
        predicted: str,
        reference: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """Run evaluation for a test case.

        Args:
            test_case_id: Test case identifier
            predicted: Predicted/generated output
            reference: Reference/ground truth output
            context: Additional context for evaluation

            Returns:
            Evaluation result
        """
        import uuid

        eval_id = str(uuid.uuid4())
        result = EvaluationResult(
            evaluation_id=eval_id,
            test_case_id=test_case_id,
        )

        try:
            for metric_name, evaluator in self.evaluators.items():
                try:
                    value = await evaluator.evaluate(predicted, reference, context)
                    threshold = self.thresholds.get(metric_name, 0.5)
                    passed = value >= threshold

                    metric = EvaluationMetric(
                        name=metric_name,
                        metric_type=MetricType[metric_name.upper()],
                        value=value,
                        is_passed=passed,
                    )
                    result.metrics.append(metric)

                    if not passed:
                        result.passed = False

                except Exception as e:
                    logger.error(f"Error evaluating {metric_name}: {e}")
                    metric = EvaluationMetric(
                        name=metric_name,
                        metric_type=MetricType.ACCURACY,
                        value=0.0,
                        is_passed=False,
                        error=str(e),
                    )
                    result.metrics.append(metric)
                    result.passed = False

        finally:
            result.end_time = datetime.utcnow()

        self.results.append(result)
        logger.info(
            f"Evaluation complete: {test_case_id} - "
            f"Passed: {result.passed} - Duration: {result.get_duration():.2f}s"
        )

        return result

    async def evaluate_batch(
        self,
        test_cases: List[Dict[str, Any]],
    ) -> List[EvaluationResult]:
        """Evaluate multiple test cases.

        Args:
            test_cases: List of test case dicts with:
                - id: Test case ID
                - predicted: Predicted output
                - reference: Reference output (optional)
                - context: Evaluation context (optional)

            Returns:
            List of evaluation results
        """
        logger.info(f"Starting batch evaluation with {len(test_cases)} test cases")

        tasks = []
        for test_case in test_cases:
            task = self.evaluate(
                test_case_id=test_case["id"],
                predicted=test_case["predicted"],
                reference=test_case.get("reference"),
                context=test_case.get("context"),
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks)
        return results

    def get_summary(self) -> Dict[str, Any]:
        """Get evaluation pipeline summary."""
        if not self.results:
            return {
                "pipeline_name": self.name,
                "total_evaluations": 0,
            }

        passed_count = sum(1 for r in self.results if r.passed)
        total_count = len(self.results)

        # Calculate average metric scores
        metric_averages = {}
        for metric_name in self.evaluators.keys():
            values = [
                m.value
                for r in self.results
                for m in r.metrics
                if m.name == metric_name
            ]
            if values:
                metric_averages[metric_name] = sum(values) / len(values)

        return {
            "pipeline_name": self.name,
            "total_evaluations": total_count,
            "passed_evaluations": passed_count,
            "pass_rate": passed_count / total_count if total_count > 0 else 0.0,
            "metric_averages": metric_averages,
            "recent_results": [
                {
                    "test_case_id": r.test_case_id,
                    "passed": r.passed,
                    "duration": r.get_duration(),
                    "metrics": r.get_summary(),
                }
                for r in self.results[-10:]
            ],
        }

    def export_results(self, format: str = "json") -> str:
        """Export evaluation results.

        Args:
            format: Export format (json, csv, etc)

            Returns:
            Exported results as string
        """
        if format == "json":
            import json

            results_data = [
                {
                    "evaluation_id": r.evaluation_id,
                    "test_case_id": r.test_case_id,
                    "passed": r.passed,
                    "duration": r.get_duration(),
                    "metrics": r.get_summary(),
                    "timestamp": r.start_time.isoformat(),
                }
                for r in self.results
            ]
            return json.dumps(results_data, indent=2)

        return ""


# Predefined evaluation pipeline for vendor risk assessment
def create_vendor_risk_eval_pipeline() -> EvaluationPipeline:
    """Create evaluation pipeline for vendor risk assessment use case."""
    pipeline = EvaluationPipeline("vendor_risk_assessment")

    # Register evaluators
    pipeline.register_evaluator(
        "relevance",
        RelevanceEvaluator(),
        threshold=0.7,
    )

    pipeline.register_evaluator(
        "accuracy",
        AccuracyEvaluator(),
        threshold=0.8,
    )

    pipeline.register_evaluator(
        "hallucination",
        HallucinationEvaluator(),
        threshold=0.3,  # Lower is better for hallucination
    )

    pipeline.register_evaluator(
        "coverage",
        CoverageEvaluator(),
        threshold=0.8,
    )

    pipeline.register_evaluator(
        "latency",
        LatencyEvaluator(target_latency_ms=2000),
        threshold=0.7,
    )

    return pipeline
