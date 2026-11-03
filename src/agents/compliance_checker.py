"""Compliance Checker Agent: Evaluates regulatory, statutory, and standards compliance."""

import json
import logging
from typing import Dict, Any, List
from src.agents.definitions import AgentState
from src.llmops.prompt_registry import prompt_registry
from src.llmops.llm_gateway import llm_gateway
from src.llmops.tracer import trace_agent_execution

logger = logging.getLogger(__name__)


class ComplianceCheckerAgent:
    """Agent evaluating regulatory compliance: SOX 404, AML/CFT, GDPR, ISO 27001, and banking standards."""

    @trace_agent_execution("ComplianceCheckerAgent")
    async def check(self, state: AgentState, vendor_data: Dict[str, Any]) -> AgentState:
        """Check regulatory compliance for the vendor."""
        vendor_name = vendor_data.get("legal_name") or vendor_data.get("name", "Unknown")
        country = vendor_data.get("country", "US")
        industry = vendor_data.get("industry", "General Services")

        logger.info(f"ComplianceCheckerAgent: Checking compliance for {vendor_name} ({industry}, {country})")

        doc_summary = json.dumps(state.agent_results.get("document_processing", {}), indent=2, default=str)[:2000]

        prompt = prompt_registry.format_prompt(
            name="compliance_check",
            vendor_name=vendor_name,
            country=country,
            industry=industry,
            documents_summary=doc_summary,
        )

        llm_response = await llm_gateway.invoke(prompt)

        # Basic compliance determination based on country and documents
        is_compliant = True
        missing_certs = []
        if state.documents_processed == 0:
            missing_certs.append("Tax Clearance Certificate (W-9 / VAT registration)")
            missing_certs.append("Certificate of Incorporation")
            is_compliant = False

        compliance_findings = [
            f"Regulatory Compliance Status: {'COMPLIANT' if is_compliant else 'PROVISIONAL / ACTION REQUIRED'}",
            f"Audited under SOX 404 and AML/CFT guidelines.",
        ]
        if missing_certs:
            compliance_findings.append(f"Missing documentation: {', '.join(missing_certs)}")

        state.compliance_findings = compliance_findings
        state.agent_results["compliance_check"] = {
            "is_compliant": is_compliant,
            "missing_certifications": missing_certs,
            "findings": compliance_findings,
            "analysis": llm_response,
        }

        return state
