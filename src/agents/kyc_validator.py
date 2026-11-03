"""KYC Validator Agent: Validates vendor legal identity, corporate registries, and sanctions/PEP."""

import json
import logging
from typing import Dict, Any, List
from datetime import datetime
from src.agents.definitions import AgentState, KYCData
from src.data_engineering.watchlist_pipeline import WatchlistPipeline, SanctionScreenResult
from src.llmops.prompt_registry import prompt_registry
from src.llmops.llm_gateway import llm_gateway
from src.llmops.tracer import trace_agent_execution

logger = logging.getLogger(__name__)


class KYCValidatorAgent:
    """Agent responsible for corporate identity, registry validation, and sanctions/PEP checks."""

    def __init__(self):
        self.watchlist = WatchlistPipeline()

    @trace_agent_execution("KYCValidatorAgent")
    async def validate(self, state: AgentState, vendor_data: Dict[str, Any]) -> AgentState:
        """Execute KYC and statutory screening."""
        vendor_name = vendor_data.get("legal_name") or vendor_data.get("name", "")
        tax_id = vendor_data.get("registration_number", "")
        country = vendor_data.get("country", "")

        logger.info(f"KYCValidatorAgent: Validating '{vendor_name}' ({country})")

        # 1. Pipeline Sanctions and PEP screening
        sanction_res: SanctionScreenResult = self.watchlist.screen_entity(
            name=vendor_name,
            tax_id=tax_id,
            country=country,
        )

        sanctions_summary = {
            "has_hit": sanction_res.has_hit,
            "is_exact_block": sanction_res.is_exact_block,
            "highest_match_score": sanction_res.highest_match_score,
            "matches": [
                {
                    "list": m.list_name,
                    "entry_id": m.entry_id,
                    "name": m.sanctioned_entity_name,
                    "score": m.match_score,
                }
                for m in sanction_res.matches
            ],
        }

        # 2. Invoke LLM with versioned prompt
        prompt = prompt_registry.format_prompt(
            name="kyc_validation",
            legal_name=vendor_name,
            registration_number=tax_id or "Not Provided",
            country=country or "Not Provided",
            sanctions_results=json.dumps(sanctions_summary, indent=2),
        )

        llm_response = await llm_gateway.invoke(prompt)

        # 3. Update State
        is_verified = not sanction_res.is_exact_block and sanction_res.highest_match_score < 0.85
        risk_flags = []
        if sanction_res.is_exact_block:
            risk_flags.append(f"CRITICAL: Exact match on sanctions list ({sanctions_summary['matches'][0]['list']})")
        elif sanction_res.has_hit:
            risk_flags.append(f"WARNING: Potential fuzzy sanctions match (score: {sanction_res.highest_match_score:.2f})")

        kyc_data = KYCData(
            vendor_id=state.vendor_id,
            legal_name=vendor_name,
            registration_number=tax_id,
            country=country,
            is_verified=is_verified,
            verification_date=datetime.utcnow(),
            verification_details={"sanctions": sanctions_summary, "llm_analysis": llm_response},
            risk_flags=risk_flags,
        )

        state.kyc_data = kyc_data
        state.kyc_verified = is_verified
        state.kyc_findings = risk_flags + [f"KYC Verification status: {'VERIFIED' if is_verified else 'FLAGGED'}"]
        state.agent_results["kyc_validation"] = {
            "is_verified": is_verified,
            "sanctions": sanctions_summary,
            "analysis": llm_response,
            "risk_flags": risk_flags,
        }

        return state
