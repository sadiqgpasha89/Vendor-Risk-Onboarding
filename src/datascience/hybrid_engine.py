from dataclasses import dataclass, field
import logging
from typing import Dict, Any, List, Optional, Union
from src.schemas.vendor import VendorProfile, VendorRiskTier
from src.schemas.assessment import (
    Tier1RuleViolation,
    Tier2MLResult,
    ActionRecommendation,
)
from src.datascience.tier1_rules.engine import Tier1RuleEngine
from src.datascience.tier2_ml.scorer import QuantitativeRiskScorer
from src.data_engineering.feature_store import FeatureStore

logger = logging.getLogger(__name__)


@dataclass
class HybridEvaluationResult:
    vendor_id: str
    composite_score: float
    risk_tier: VendorRiskTier
    recommendation: ActionRecommendation
    decision: ActionRecommendation
    tier1_violations: List[Tier1RuleViolation]
    tier2_ml: Tier2MLResult
    feature_vector: Dict[str, Any]
    hitl_required: bool
    hitl_reason: Optional[str]
    recommendations: List[str]
    requires_agentic_investigation: bool

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vendor_id": self.vendor_id,
            "composite_score": self.composite_score,
            "risk_tier": self.risk_tier.value if hasattr(self.risk_tier, "value") else str(self.risk_tier),
            "recommendation": self.recommendation.value if hasattr(self.recommendation, "value") else str(self.recommendation),
            "decision": self.decision.value if hasattr(self.decision, "value") else str(self.decision),
            "tier1_violations": [v.__dict__ for v in self.tier1_violations],
            "hitl_required": self.hitl_required,
            "hitl_reason": self.hitl_reason,
            "recommendations": self.recommendations,
            "requires_agentic_investigation": self.requires_agentic_investigation,
        }


class HybridRiskEngine:
    """Coordinates Tier 1 Deterministic Rules and Tier 2 Quantitative Machine Learning."""

    def __init__(
        self,
        rule_engine: Optional[Tier1RuleEngine] = None,
        ml_scorer: Optional[QuantitativeRiskScorer] = None,
        feature_store: Optional[FeatureStore] = None,
    ):
        self.rule_engine = rule_engine or Tier1RuleEngine()
        self.ml_scorer = ml_scorer or QuantitativeRiskScorer()
        self.feature_store = feature_store or FeatureStore()

    def evaluate_sync(
        self,
        vendor: Union[VendorProfile, Dict[str, Any]],
        existing_vendor_bank_accounts: Optional[List[str]] = None,
    ) -> HybridEvaluationResult:
        """Perform synchronous hybrid Tier 1 + Tier 2 evaluation."""
        # 1. Compute feature vector
        features = self.feature_store.compute_features(
            vendor=vendor,
            existing_vendor_bank_accounts=existing_vendor_bank_accounts,
        )

        vendor_id = vendor.get("id") or vendor.get("vendor_id") if isinstance(vendor, dict) else vendor.id

        # 2. Tier 1 Deterministic Rules
        violations: List[Tier1RuleViolation] = self.rule_engine.evaluate_rules(vendor, features)

        has_hard_block = any(v.severity == "HARD_BLOCK" for v in violations)
        has_critical_hold = any(v.severity == "CRITICAL_HOLD" for v in violations)

        # 3. Tier 2 Quantitative ML Scoring
        ml_result: Tier2MLResult = self.ml_scorer.predict_risk(features)

        # 4. Composite Score Synthesis
        base_score = ml_result.calibrated_risk_probability * 100.0

        if has_hard_block:
            composite_score = max(base_score, 95.0)
            risk_tier = VendorRiskTier.CRITICAL
            recommendation = ActionRecommendation.REJECT
            hitl_required = True
            hitl_reason = "Hard statutory policy violation detected (embargo/sanctions match)."
        elif has_critical_hold:
            composite_score = max(base_score, 75.0)
            risk_tier = VendorRiskTier.HIGH
            recommendation = ActionRecommendation.HOLD_FOR_AUDIT
            hitl_required = True
            hitl_reason = "Critical policy hold triggered (tax ID/bank update anomaly)."
        elif base_score >= 60.0:
            composite_score = base_score
            risk_tier = VendorRiskTier.HIGH
            recommendation = ActionRecommendation.REQUEST_MANUAL_KYC
            hitl_required = True
            hitl_reason = "High quantitative ML risk score."
        elif base_score >= 30.0:
            composite_score = base_score
            risk_tier = VendorRiskTier.MEDIUM
            recommendation = ActionRecommendation.CONDITIONAL_APPROVE
            hitl_required = False
            hitl_reason = None
        else:
            composite_score = base_score
            risk_tier = VendorRiskTier.LOW
            recommendation = ActionRecommendation.AUTO_APPROVE
            hitl_required = False
            hitl_reason = None

        recommendations_list = [f"Recommendation: {recommendation.value}"]
        for v in violations:
            recommendations_list.append(v.description)

        return HybridEvaluationResult(
            vendor_id=vendor_id or "UNKNOWN",
            composite_score=round(composite_score, 2),
            risk_tier=risk_tier,
            recommendation=recommendation,
            decision=recommendation,
            tier1_violations=violations,
            tier2_ml=ml_result,
            feature_vector=features,
            hitl_required=hitl_required,
            hitl_reason=hitl_reason,
            recommendations=recommendations_list,
            requires_agentic_investigation=(composite_score >= 25.0 or len(violations) > 0),
        )

    async def evaluate(
        self,
        vendor: Union[VendorProfile, Dict[str, Any]],
        existing_vendor_bank_accounts: Optional[List[str]] = None,
    ) -> HybridEvaluationResult:
        """Perform asynchronous hybrid Tier 1 + Tier 2 evaluation."""
        return self.evaluate_sync(vendor, existing_vendor_bank_accounts)
