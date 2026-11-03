"""Production LangGraph Multi-Agent Workflow with Parallel Fan-Out and Reflection Loops."""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from langgraph.graph import StateGraph, END
from src.agents.definitions import AgentState
from src.agents.document_processor import DocumentProcessorAgent
from src.agents.kyc_validator import KYCValidatorAgent
from src.agents.risk_assessor import RiskAssessorAgent
from src.agents.compliance_checker import ComplianceCheckerAgent
from src.agents.report_generator import ReportGeneratorAgent
from src.agents.supervisor import SupervisorAgent

logger = logging.getLogger(__name__)


class VendorRiskWorkflow:
    """Compiled multi-agent LangGraph workflow for vendor onboarding and risk assessment."""

    def __init__(self):
        self.doc_processor = DocumentProcessorAgent()
        self.kyc_validator = KYCValidatorAgent()
        self.risk_assessor = RiskAssessorAgent()
        self.compliance_checker = ComplianceCheckerAgent()
        self.report_generator = ReportGeneratorAgent()
        self.supervisor = SupervisorAgent()
        self._vendor_data_cache: Dict[str, Dict[str, Any]] = {}

    async def execute_workflow(
        self,
        state: AgentState,
        vendor_data: Dict[str, Any],
    ) -> AgentState:
        """Execute the complete multi-agent workflow with parallel fan-out optimization."""
        self._vendor_data_cache[state.workflow_id] = vendor_data
        start_time = datetime.utcnow()
        logger.info(f"Starting Multi-Agent Workflow {state.workflow_id} for vendor {state.vendor_id}")

        try:
            # Step 1: Document Processing
            state = await self.doc_processor.process(state)

            # Step 2: High-throughput Parallel Fan-Out
            # KYC Validation, Compliance Check, and Quantitative Risk Assessment execute concurrently
            logger.info("Executing Parallel Fan-Out: [KYC Validator || Compliance Checker || Risk Assessor]")
            results = await asyncio.gather(
                self.kyc_validator.validate(state, vendor_data),
                self.compliance_checker.check(state, vendor_data),
                self.risk_assessor.assess(state, vendor_data),
                return_exceptions=True,
            )

            # Check for any exceptions in parallel branches
            for r in results:
                if isinstance(r, Exception):
                    state.errors.append(f"Parallel agent error: {str(r)}")
                    logger.error(f"Error in parallel branch: {r}")

            # Step 3: Fan-In Report Generation
            state = await self.report_generator.generate_report(state)

            # Step 4: Supervisor Routing & Reflection / HITL Gate
            routing_decision = self.supervisor.evaluate_routing(state)
            if routing_decision == "hitl_gate":
                state.status = "pending_hitl_approval"
                logger.info(f"Workflow {state.workflow_id} routed to HITL Gate.")
            elif routing_decision == "reflection_loop":
                logger.info(f"Workflow {state.workflow_id} triggering reflection loop for report refinement.")
                # Single pass reflection refinement
                state = await self.report_generator.generate_report(state)
                state.status = "completed"
            else:
                state.status = "completed"

            # Populate standard agent_results keys
            state.agent_results["document_processor"] = state.agent_results.get("document_processing")
            state.agent_results["kyc_validator"] = state.agent_results.get("kyc_validation")
            state.agent_results["compliance_checker"] = state.agent_results.get("compliance_check")
            state.agent_results["risk_assessor"] = state.agent_results.get("risk_assessment")
            state.agent_results["report_generator"] = {
                "report": state.report,
                "quality_gate": state.agent_results.get("report_quality_gate"),
            }
            state.agent_results["supervisor"] = {"routing_decision": routing_decision}

            state.end_time = datetime.utcnow()
            total_sec = (state.end_time - start_time).total_seconds()
            logger.info(f"Workflow {state.workflow_id} finished in {total_sec:.2f}s with status '{state.status}'.")

        except Exception as exc:
            state.status = "failed"
            state.errors.append(str(exc))
            state.end_time = datetime.utcnow()
            logger.error(f"Workflow {state.workflow_id} execution failed: {exc}", exc_info=True)

        return state

    async def execute(
        self,
        vendor_id: str,
        vendor_data: Dict[str, Any],
        documents: Optional[list] = None,
    ) -> AgentState:
        """Convenience method to execute full workflow from vendor dictionary and raw documents."""
        import uuid
        from src.agents.definitions import Document

        workflow_id = str(uuid.uuid4())
        doc_objs = []
        for d in (documents or []):
            if isinstance(d, Document):
                doc_objs.append(d)
            elif isinstance(d, dict):
                doc_objs.append(
                    Document(
                        id=d.get("id", str(uuid.uuid4())),
                        vendor_id=vendor_id,
                        file_name=d.get("name") or d.get("file_name", "doc.pdf"),
                        file_path=d.get("file_path", ""),
                        document_type=d.get("type") or d.get("document_type", "other"),
                        content=d.get("content", ""),
                    )
                )

        state = AgentState(
            vendor_id=vendor_id,
            workflow_id=workflow_id,
            workflow_type="vendor_onboarding",
            documents=doc_objs,
        )
        return await self.execute_workflow(state, vendor_data)


def build_langgraph_workflow() -> StateGraph:
    """Construct and compile the LangGraph StateGraph instance."""
    workflow = StateGraph(AgentState)

    agent_runner = VendorRiskWorkflow()

    async def doc_node(state: AgentState):
        return await agent_runner.doc_processor.process(state)

    async def report_node(state: AgentState):
        return await agent_runner.report_generator.generate_report(state)

    workflow.add_node("document_processing", doc_node)
    workflow.add_node("report_generation", report_node)

    workflow.set_entry_point("document_processing")
    workflow.add_edge("document_processing", "report_generation")
    workflow.add_edge("report_generation", END)

    return workflow


# Global workflow engine instance
vendor_risk_workflow = VendorRiskWorkflow()
