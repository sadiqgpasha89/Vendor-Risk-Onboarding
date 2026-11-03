"""Orchestrator agent for vendor risk onboarding workflow."""

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import json

from src.agents.definitions import AgentState, AgentType
from src.llmops.monitoring import workflow_logger, performance_monitor, monitor_llm_call
from src.config.settings import settings


class OrchestratorAgent:
    """Main orchestrator agent that coordinates all sub-agents."""

    def __init__(self):
        """Initialize orchestrator agent."""
        self.agent_type = AgentType.ORCHESTRATOR
        self.llm = self._initialize_llm()
        self.sub_agents: Dict[str, Any] = {}
        self.workflow_state: Optional[AgentState] = None

    def _initialize_llm(self):
        """Initialize LLM for orchestrator."""
        try:
            return ChatOpenAI(
                model=settings.llm.model,
                temperature=settings.llm.temperature,
                max_tokens=settings.llm.max_tokens,
                api_key=settings.llm.openai_api_key or "mock-key",
            )
        except Exception:
            return None

    @monitor_llm_call
    async def orchestrate_vendor_onboarding(
        self,
        vendor_id: str,
        vendor_data: Dict[str, Any],
        documents: List[Dict[str, Any]],
    ) -> AgentState:
        """Orchestrate complete vendor onboarding workflow."""

        workflow_id = str(uuid.uuid4())
        state = AgentState(
            vendor_id=vendor_id,
            workflow_id=workflow_id,
            workflow_type="vendor_onboarding",
            documents=[self._create_document(doc) for doc in documents],
        )

        self.workflow_state = state

        try:
            # Step 1: Document Processing
            await self._execute_step(
                state,
                "document_processing",
                self._process_documents,
            )

            # Step 2: KYC Validation
            await self._execute_step(
                state,
                "kyc_validation",
                self._validate_kyc,
                vendor_data,
            )

            # Step 3: Risk Assessment
            await self._execute_step(
                state,
                "risk_assessment",
                self._assess_risk,
                vendor_data,
            )

            # Step 4: Compliance Check
            await self._execute_step(
                state,
                "compliance_check",
                self._check_compliance,
                vendor_data,
            )

            # Step 5: Report Generation
            await self._execute_step(
                state,
                "report_generation",
                self._generate_report,
            )

            state.status = "completed"
            state.end_time = datetime.utcnow()

        except Exception as e:
            state.status = "failed"
            state.errors.append(str(e))
            workflow_logger.log_event(
                workflow_id,
                "workflow_failed",
                "OrchestratorAgent",
                {"error": str(e)},
                status="error",
            )

        return state

    async def _execute_step(
        self,
        state: AgentState,
        step_name: str,
        step_func,
        *args,
    ) -> None:
        """Execute a workflow step with monitoring."""
        with performance_monitor.track_operation(f"workflow_step_{step_name}"):
            try:
                await step_func(state, *args)
                workflow_logger.log_event(
                    state.workflow_id,
                    "step_completed",
                    step_name,
                    status="success",
                )
            except Exception as e:
                state.errors.append(f"{step_name}: {str(e)}")
                workflow_logger.log_event(
                    state.workflow_id,
                    "step_failed",
                    step_name,
                    {"error": str(e)},
                    status="error",
                )
                raise

    async def _process_documents(self, state: AgentState) -> None:
        """Process vendor documents using document processor agent."""
        if not state.documents:
            return

        prompt = f"""Analyze the following vendor documents and extract key information:

Documents:
{json.dumps([d.__dict__ for d in state.documents], indent=2)}

For each document:
1. Identify document type
2. Extract key information
3. Identify risks or red flags
4. Assess document quality

Provide structured analysis as JSON."""

        response = await self._call_llm(prompt)
        state.agent_results["document_processing"] = response
        state.documents_processed = len(state.documents)

    async def _validate_kyc(self, state: AgentState, vendor_data: Dict[str, Any]) -> None:
        """Validate KYC information."""
        prompt = f"""Perform KYC validation for the following vendor:

Vendor Information:
{json.dumps(vendor_data, indent=2)}

Validate against:
1. Company registration records
2. Sanctions lists
3. PEP databases
4. Known fraud indicators

Provide:
- Verification status (verified/unverified/failed)
- Risk flags
- Confidence score
- Recommendations

Return as JSON."""

        response = await self._call_llm(prompt)
        state.agent_results["kyc_validation"] = response
        state.kyc_verified = "verified" in response.lower()

    async def _assess_risk(self, state: AgentState, vendor_data: Dict[str, Any]) -> None:
        """Perform risk assessment."""
        prompt = f"""Conduct comprehensive risk assessment for vendor:

Vendor Data:
{json.dumps(vendor_data, indent=2)}

Document Findings:
{json.dumps(state.agent_results.get("document_processing", {}), indent=2)}

KYC Results:
{json.dumps(state.agent_results.get("kyc_validation", {}), indent=2)}

Assess risk in:
1. KYC/AML Risk (0-100)
2. Financial Risk (0-100)
3. Compliance Risk (0-100)
4. Operational Risk (0-100)

Provide:
- Individual risk scores with justification
- Overall risk score (0-100)
- Risk level (CRITICAL/HIGH/MEDIUM/LOW/MINIMAL)
- Key findings
- Recommendations

Return as JSON."""

        response = await self._call_llm(prompt)
        state.agent_results["risk_assessment"] = response
        state.risk_findings = self._extract_findings(response)

    async def _check_compliance(self, state: AgentState, vendor_data: Dict[str, Any]) -> None:
        """Check regulatory compliance."""
        prompt = f"""Evaluate regulatory compliance for vendor:

Vendor Information:
{json.dumps(vendor_data, indent=2)}

Risk Assessment:
{json.dumps(state.agent_results.get("risk_assessment", {}), indent=2)}

Verify compliance with:
1. Banking regulations
2. AML/CFT requirements
3. Country-specific regulations
4. Industry standards
5. Data protection laws

Provide:
- Compliance status
- Missing requirements
- Remediation timeline
- Regulatory risks
- Recommendations

Return as JSON."""

        response = await self._call_llm(prompt)
        state.agent_results["compliance_check"] = response
        state.compliance_findings = self._extract_findings(response)

    async def _generate_report(self, state: AgentState) -> None:
        """Generate final audit-ready report."""
        prompt = f"""Generate comprehensive vendor risk onboarding report:

Vendor ID: {state.vendor_id}

All Analysis Results:
{json.dumps(state.agent_results, indent=2)}

Create professional audit-ready report with:
1. Executive Summary
2. Vendor Profile
3. Document Analysis Summary
4. KYC Findings
5. Risk Assessment with detailed scores
6. Compliance Status
7. Key Findings and Red Flags
8. Recommendations
9. Approval/Rejection Recommendation
10. Action Items and Timeline

Use professional tone suitable for bank executives and auditors."""

        report = await self._call_llm(prompt)
        state.agent_results["report"] = report
        state.report = report

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM with fallback for async compatibility."""
        try:
            message = HumanMessage(content=prompt)
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.llm.invoke([
                    SystemMessage(content="You are an expert vendor risk assessment analyst for banking institutions."),
                    message,
                ]),
            )
            return response.content
        except Exception as e:
            # Fallback for sync LLM
            message = HumanMessage(content=prompt)
            response = self.llm.invoke([
                SystemMessage(content="You are an expert vendor risk assessment analyst for banking institutions."),
                message,
            ])
            return response.content

    @staticmethod
    def _create_document(doc_data: Dict[str, Any]):
        """Create document object from data."""
        from src.agents.definitions import Document

        return Document(
            id=str(uuid.uuid4()),
            vendor_id=doc_data.get("vendor_id", ""),
            file_name=doc_data.get("file_name", ""),
            file_path=doc_data.get("file_path", ""),
            content=doc_data.get("content", ""),
            document_type=doc_data.get("document_type"),
        )

    @staticmethod
    def _extract_findings(response: str) -> List[str]:
        """Extract findings from LLM response."""
        try:
            data = json.loads(response)
            if isinstance(data, dict):
                if "findings" in data:
                    findings = data["findings"]
                    if isinstance(findings, list):
                        return findings
                    return [findings]
            return []
        except json.JSONDecodeError:
            # Extract findings from text response
            if "finding" in response.lower():
                lines = response.split("\n")
                return [line.strip() for line in lines if line.strip() and "-" in line]
            return []


# Global orchestrator instance
orchestrator = OrchestratorAgent()
