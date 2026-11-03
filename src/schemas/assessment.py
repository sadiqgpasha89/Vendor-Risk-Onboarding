"""Risk assessment, scoring, and SHAP explainability schemas."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from src.schemas.vendor import VendorRiskTier


class ActionRecommendation(str, Enum):
    AUTO_APPROVE = "AUTO_APPROVE"
    APPROVE_STANDARD_MONITORING = "APPROVE_STANDARD_MONITORING"
    CONDITIONAL_APPROVE = "CONDITIONAL_APPROVE"
    REQUEST_MANUAL_KYC = "REQUEST_MANUAL_KYC"
    HOLD_FOR_AUDIT = "HOLD_FOR_AUDIT"
    FREEZE_VENDOR = "FREEZE_VENDOR"
    REJECT = "REJECT"


class FeatureAttribution(BaseModel):
    """Local SHAP/Feature contribution."""
    feature_name: str
    feature_value: Any
    contribution: float
    description: str


class Tier1RuleViolation(BaseModel):
    """Deterministic rule failure."""
    rule_id: str
    rule_name: str
    severity: str  # HARD_BLOCK, CRITICAL_HOLD, WARNING
    description: str
    evidence: Dict[str, Any] = Field(default_factory=dict)


class Tier2MLResult(BaseModel):
    """Quantitative ML inference result."""
    raw_anomaly_score: float
    calibrated_risk_probability: float = Field(..., ge=0.0, le=1.0)
    risk_decile: int = Field(..., ge=1, le=10)
    model_name: str = "lgbm_isolation_ensemble"
    model_version: str = "1.0.0"
    top_risk_drivers: List[FeatureAttribution] = Field(default_factory=list)
    top_mitigating_factors: List[FeatureAttribution] = Field(default_factory=list)


class DimensionScore(BaseModel):
    """Risk breakdown across key operational dimensions."""
    dimension: str  # KYC, Financial, Regulatory/Compliance, Operational, Cyber
    score: float = Field(..., ge=0.0, le=100.0)
    risk_level: VendorRiskTier
    findings: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)


class ComprehensiveRiskDossier(BaseModel):
    """Final synthesized risk dossier combining all 3 tiers."""
    vendor_id: str
    assessment_id: str
    overall_score: float = Field(..., ge=0.0, le=100.0)
    overall_tier: VendorRiskTier
    recommendation: ActionRecommendation
    tier1_violations: List[Tier1RuleViolation] = Field(default_factory=list)
    tier2_ml: Optional[Tier2MLResult] = None
    dimension_scores: Dict[str, DimensionScore] = Field(default_factory=dict)
    executive_summary: str
    key_red_flags: List[str] = Field(default_factory=list)
    remediation_steps: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    hitl_required: bool = False
    hitl_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
