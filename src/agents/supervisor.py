"""Supervisor Agent: Manages routing decisions, reflection loops, and HITL escalation gates."""

import logging
from typing import Dict, Any, Optional
from src.agents.definitions import AgentState

logger = logging.getLogger(__name__)


class SupervisorAgent:
    """Oversees agent execution flow, reflection loops, and Human-in-the-Loop gating."""

    @staticmethod
    def evaluate_routing(state: AgentState) -> str:
        """Determine next workflow path based on risk level and policy checks."""
        # 1. Check for hard blocks or critical violations
        risk_res = state.risk_assessment
        if risk_res and risk_res.risk_level in ("CRITICAL", "HIGH"):
            logger.warning(f"Vendor {state.vendor_id} marked as {risk_res.risk_level}. Directing to HITL Review.")
            return "hitl_gate"

        # 2. Check if groundedness quality gate passed
        quality_gate = state.agent_results.get("report_quality_gate", {})
        groundedness = quality_gate.get("groundedness_score", 1.0)
        if groundedness < 0.60:
            logger.warning(f"Report groundedness low ({groundedness:.2f}). Triggering reflection loop.")
            return "reflection_loop"

        # 3. Standard completion
        return "completed"

    @staticmethod
    def process_hitl_decision(state: AgentState, decision: str, reviewer_notes: Optional[str] = None) -> AgentState:
        """Apply human reviewer decision (APPROVE, REJECT, REQUEST_MORE_INFO)."""
        logger.info(f"Applying HITL decision '{decision}' for vendor {state.vendor_id}")
        state.agent_results["hitl_decision"] = {
            "decision": decision,
            "reviewer_notes": reviewer_notes,
        }
        if decision == "APPROVE":
            state.status = "approved_by_hitl"
        elif decision == "REJECT":
            state.status = "rejected_by_hitl"
        else:
            state.status = "hitl_pending_clarification"

        return state
