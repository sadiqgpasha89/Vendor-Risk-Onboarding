"""Risk Assessor Agent: Synthesizes quantitative Tier 2 ML scoring with qualitative risk dimensions."""

import json
import logging
from typing import Dict, Any, List
from src.agents.definitions import AgentState, RiskAssessmentResult
from src.schemas.vendor import VendorProfile, VendorRiskTier
from src.datascience.hybrid_engine import HybridRiskEngine
from src.llmops.llm_gateway import llm_gateway
from src.llmops.tracer import trace_agent_execution

logger = logging.getLogger(__name__)


class RiskAssessorAgent:
    """Agent evaluating multi-dimensional vendor risk: Financial, Operational, Cyber, and Fraud."""

    def __init__(self):
        self.hybrid_engine = HybridRiskEngine()

    @trace_agent_execution("RiskAssessorAgent")
    async def assess(self, state: AgentState, vendor_data: Dict[str, Any]) -> AgentState:
        """Perform comprehensive risk assessment."""
        logger.info(f"RiskAssessorAgent: Assessing risk profile for vendor {state.vendor_id}")

        # 1. Instantiate VendorProfile from vendor_data
        vendor_profile = VendorProfile(
            id=state.vendor_id,
            name=vendor_data.get("name", "Unknown Vendor"),
            legal_name=vendor_data.get("legal_name", vendor_data.get("name", "Unknown")),
            registration_number=vendor_data.get("registration_number", ""),
            country=vendor_data.get("country", "US"),
            industry=vendor_data.get("industry"),
            annual_revenue_usd=vendor_data.get("annual_revenue_usd"),
            employee_count=vendor_data.get("employee_count"),
            bank_account_number=vendor_data.get("bank_account_number"),
            metadata=vendor_data.get("metadata", {}),
        )

        # 2. Run Tier 1 + Tier 2 Hybrid Quantitative Engine
        hybrid_eval = await self.hybrid_engine.evaluate(vendor_profile)
        composite_score = hybrid_eval["composite_score"]
        tier1_violations = hybrid_eval["tier1_violations"]
        tier2_ml = hybrid_eval["tier2_ml"]

        # 3. Qualitative LLM Synthesis
        prompt = f"""Conduct comprehensive risk assessment for vendor:
Vendor ID: {state.vendor_id}
Vendor Profile: {json.dumps(vendor_data, indent=2, default=str)}
Document Findings: {json.dumps(state.agent_results.get("document_processing", {}), indent=2, default=str)[:2000]}
KYC Results: {json.dumps(state.agent_results.get("kyc_validation", {}), indent=2, default=str)[:2000]}
Tier 1 Hard Rule Violations: {[v.__dict__ if hasattr(v, '__dict__') else str(v) for v in tier1_violations]}
Tier 2 ML Risk Probability: {tier2_ml.calibrated_risk_probability if tier2_ml else 'N/A'} (Anomaly Score: {tier2_ml.raw_anomaly_score if tier2_ml else 'N/A'})

Evaluate risk across:
1. Financial Risk (0-100)
2. KYC / Fraud Risk (0-100)
3. Compliance Risk (0-100)
4. Operational / Supply Chain Risk (0-100)

Return JSON with scores, justifications, key red flags, and recommended remediation."""

        llm_response = await llm_gateway.invoke(prompt)

        # 4. Synthesize dimension scores
        kyc_score = 90.0 if not state.kyc_verified else (20.0 if state.kyc_data and state.kyc_data.is_verified else 50.0)
        fin_score = composite_score * 0.9
        comp_score = 80.0 if tier1_violations else composite_score * 0.8
        op_score = composite_score * 0.7

        overall_score = round(float(0.35 * kyc_score + 0.25 * fin_score + 0.25 * comp_score + 0.15 * op_score), 1)

        if overall_score >= 80 or any(v.severity == "HARD_BLOCK" for v in tier1_violations):
            risk_level = "CRITICAL"
        elif overall_score >= 60:
            risk_level = "HIGH"
        elif overall_score >= 30:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        findings = [f"Tier 1 Violations: {len(tier1_violations)}"]
        for v in tier1_violations:
            findings.append(f"[{v.severity}] {v.rule_name}: {v.description}")
        if tier2_ml and tier2_ml.top_risk_drivers:
            for d in tier2_ml.top_risk_drivers[:2]:
                findings.append(f"[ML Driver] {d.description} (+{d.contribution:.2f})")

        assessment_result = RiskAssessmentResult(
            vendor_id=state.vendor_id,
            kyc_score=kyc_score,
            financial_score=fin_score,
            compliance_score=comp_score,
            operational_score=op_score,
            overall_score=overall_score,
            risk_level=risk_level,
            findings=findings,
            recommendations=[
                "Enforce dual-authorization for any changes to vendor settlement accounts.",
                "Review annual audited balance sheets upon contract renewal.",
            ],
        )

        state.risk_assessment = assessment_result
        state.risk_findings = findings
        state.agent_results["risk_assessment"] = {
            "overall_score": overall_score,
            "risk_level": risk_level,
            "dimension_scores": {
                "kyc": kyc_score,
                "financial": fin_score,
                "compliance": comp_score,
                "operational": op_score,
            },
            "tier1_violations": [v.__dict__ if hasattr(v, "__dict__") else str(v) for v in tier1_violations],
            "tier2_ml": tier2_ml.model_dump(mode="json") if hasattr(tier2_ml, "model_dump") else str(tier2_ml),
            "qualitative_analysis": llm_response,
        }

        return state
