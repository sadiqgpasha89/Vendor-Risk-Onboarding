"""Evaluation Criteria and Quality Gates for LLMOps & MLOps."""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum


class MetricType(str, Enum):
    STATISTICAL = "statistical"
    GROUNDEDNESS = "groundedness"
    COMPLIANCE = "compliance"
    LATENCY = "latency"


@dataclass
class QualityGateCriterion:
    name: str
    metric_type: MetricType
    threshold: float
    comparison: str  # ">=", "<=", "==", "!="
    description: str
    is_blocking: bool = True

    def evaluate(self, actual_value: float) -> bool:
        if self.comparison == ">=":
            return actual_value >= self.threshold
        elif self.comparison == "<=":
            return actual_value <= self.threshold
        elif self.comparison == ">":
            return actual_value > self.threshold
        elif self.comparison == "<":
            return actual_value < self.threshold
        elif self.comparison == "==":
            return actual_value == self.threshold
        return False


# Standard enterprise vendor risk quality gates
ENTERPRISE_EVAL_CRITERIA: List[QualityGateCriterion] = [
    QualityGateCriterion(
        name="tier1_rule_precision",
        metric_type=MetricType.COMPLIANCE,
        threshold=1.0,  # Zero false positives allowed on statutory sanctions
        comparison=">=",
        description="Precision of Tier 1 statutory rule triggers (OFAC, sanctions, embargoes)",
        is_blocking=True,
    ),
    QualityGateCriterion(
        name="tier1_rule_recall",
        metric_type=MetricType.COMPLIANCE,
        threshold=1.0,  # Zero false negatives allowed on hard sanctions
        comparison=">=",
        description="Recall of Tier 1 statutory rule triggers",
        is_blocking=True,
    ),
    QualityGateCriterion(
        name="auc_pr",
        metric_type=MetricType.STATISTICAL,
        threshold=0.70,
        comparison=">=",
        description="Area under Precision-Recall Curve for ML fraud anomaly scoring",
        is_blocking=True,
    ),
    QualityGateCriterion(
        name="brier_score",
        metric_type=MetricType.STATISTICAL,
        threshold=0.20,
        comparison="<=",
        description="Brier score calibration error",
        is_blocking=False,
    ),
    QualityGateCriterion(
        name="groundedness_score",
        metric_type=MetricType.GROUNDEDNESS,
        threshold=0.85,
        comparison=">=",
        description="Factual consistency of agent synthesis against source documents",
        is_blocking=True,
    ),
    QualityGateCriterion(
        name="p99_workflow_latency_sec",
        metric_type=MetricType.LATENCY,
        threshold=12.0,
        comparison="<=",
        description="P99 total parallel workflow execution latency",
        is_blocking=False,
    ),
]
