"""Report Generator Agent: Compiles audit-ready compliance dossiers and grounded executive reports."""

import json
import logging
from typing import Dict, Any, List
from src.agents.definitions import AgentState
from src.llmops.prompt_registry import prompt_registry
from src.llmops.llm_gateway import llm_gateway
from src.llmops.hallucination_evaluator import HallucinationEvaluator
from src.llmops.tracer import trace_agent_execution

logger = logging.getLogger(__name__)


class ReportGeneratorAgent:
    """Agent responsible for compiling audit-ready compliance dossiers and executive reports."""

    def __init__(self):
        self.hallucination_evaluator = HallucinationEvaluator()

    @trace_agent_execution("ReportGeneratorAgent")
    async def generate_report(self, state: AgentState) -> AgentState:
        """Synthesize all specialist agent outputs into an audit-ready compliance report."""
        logger.info(f"ReportGeneratorAgent: Compiling report for vendor {state.vendor_id}")

        risk_results = state.agent_results.get("risk_assessment", {})
        tier1_violations = risk_results.get("tier1_violations", [])
        tier2_ml = risk_results.get("tier2_ml", {})
        kyc_findings = state.kyc_findings
        compliance_findings = state.compliance_findings

        prompt = prompt_registry.format_prompt(
            name="risk_synthesis",
            vendor_id=state.vendor_id,
            tier1_violations=json.dumps(tier1_violations, indent=2, default=str),
            tier2_ml_summary=json.dumps(tier2_ml, indent=2, default=str)[:1500],
            kyc_findings="\n".join(kyc_findings),
            compliance_findings="\n".join(compliance_findings),
        )

        llm_report = await llm_gateway.invoke(prompt)

        # Groundedness evaluation
        source_context = f"{json.dumps(state.agent_results, default=str)}"
        eval_res = self.hallucination_evaluator.evaluate_groundedness(
            generated_text=llm_report,
            source_context=source_context,
        )

        # Append audit summary metadata
        final_report = f"""{llm_report}

---
### Audit Verification & LLMOps Quality Gate
- **Groundedness Score:** {eval_res.groundedness_score:.2f} / 1.00 ({'PASSED' if eval_res.is_grounded else 'FLAGGED'})
- **Documents Analyzed:** {state.documents_processed}
- **KYC Verification:** {'VERIFIED' if state.kyc_verified else 'REQUIRES REVIEW'}
- **Overall Risk Score:** {state.risk_assessment.overall_score if state.risk_assessment else 'N/A'}/100 ({state.risk_assessment.risk_level if state.risk_assessment else 'UNKNOWN'})
"""

        state.report = final_report
        state.agent_results["report"] = final_report
        state.agent_results["report_quality_gate"] = {
            "groundedness_score": eval_res.groundedness_score,
            "is_grounded": eval_res.is_grounded,
            "unsupported_claims": eval_res.unsupported_claims,
        }

        return state
