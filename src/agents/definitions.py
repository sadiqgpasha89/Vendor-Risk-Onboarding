"""LangGraph agent definitions for vendor risk onboarding."""

from typing import Any, Dict, List, Optional, Annotated
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from langgraph.graph import StateGraph, END
from langchain_core.prompts import PromptTemplate
import operator


class AgentType(str, Enum):
    """Agent types in the system."""

    ORCHESTRATOR = "orchestrator"
    DOCUMENT_PROCESSOR = "document_processor"
    KYC_VALIDATOR = "kyc_validator"
    RISK_ASSESSOR = "risk_assessor"
    COMPLIANCE_CHECKER = "compliance_checker"
    REPORT_GENERATOR = "report_generator"


@dataclass
class Document:
    """Document structure."""

    id: str
    vendor_id: str
    file_name: str
    file_path: str
    content: str
    document_type: Optional[str] = None
    extracted_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KYCData:
    """KYC validation data."""

    vendor_id: str
    legal_name: str
    registration_number: str
    country: str
    is_verified: bool = False
    verification_date: Optional[datetime] = None
    verification_details: Dict[str, Any] = field(default_factory=dict)
    risk_flags: List[str] = field(default_factory=list)


@dataclass
class RiskAssessmentResult:
    """Risk assessment results."""

    vendor_id: str
    kyc_score: float = 0.0
    financial_score: float = 0.0
    compliance_score: float = 0.0
    operational_score: float = 0.0
    overall_score: float = 0.0
    risk_level: str = "MEDIUM"
    findings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class AgentState:
    """State object for LangGraph workflow."""

    # Workflow tracking
    vendor_id: str
    workflow_id: str
    workflow_type: str = "vendor_onboarding"
    status: str = "in_progress"
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None

    # Documents
    documents: List[Document] = field(default_factory=list)
    documents_processed: Annotated[int, operator.add] = 0

    # KYC Information
    kyc_data: Optional[KYCData] = None
    kyc_verified: bool = False
    kyc_findings: List[str] = field(default_factory=list)

    # Risk Assessment
    risk_assessment: Optional[RiskAssessmentResult] = None
    risk_findings: List[str] = field(default_factory=list)
    compliance_findings: List[str] = field(default_factory=list)

    # Report Generation
    report: Optional[str] = None
    report_path: Optional[str] = None

    # Execution tracking
    agent_results: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    logs: List[Dict[str, Any]] = field(default_factory=list)


class DocumentProcessorPrompt:
    """Prompts for document processor agent."""

    EXTRACTION_PROMPT = PromptTemplate(
        input_variables=["document_content", "document_type"],
        template="""Analyze the following {document_type} document and extract key information:

Document Content:
{document_content}

Please extract:
1. Key financial information (if applicable)
2. Compliance certifications
3. Risk indicators
4. Company structure and ownership
5. Historical information

Provide structured JSON output with extracted data.""",
    )

    VALIDATION_PROMPT = PromptTemplate(
        input_variables=["extracted_data"],
        template="""Validate and enhance the following extracted vendor data:

Extracted Data:
{extracted_data}

Check for:
1. Data consistency
2. Missing critical information
3. Potential data quality issues
4. Confidence levels for each field

Return validation report as JSON.""",
    )


class KYCValidatorPrompt:
    """Prompts for KYC validator agent."""

    KYC_CHECK_PROMPT = PromptTemplate(
        input_variables=["legal_name", "registration_number", "country"],
        template="""Perform KYC validation for:
- Legal Name: {legal_name}
- Registration Number: {registration_number}
- Country: {country}

Check against:
1. Public registries and databases
2. Sanctions lists (OFAC, UN, etc.)
3. PEP (Politically Exposed Person) databases
4. Company registration records
5. Known fraud indicators

Provide KYC validation report with:
- Verification status
- Risk flags if any
- Confidence score
- Recommendations""",
    )


class RiskAssessorPrompt:
    """Prompts for risk assessor agent."""

    ASSESSMENT_PROMPT = PromptTemplate(
        input_variables=["vendor_name", "kyc_status", "financial_data", "compliance_data"],
        template="""Perform comprehensive risk assessment for vendor: {vendor_name}

Input Data:
- KYC Status: {kyc_status}
- Financial Data: {financial_data}
- Compliance Data: {compliance_data}

Evaluate Risk in:
1. KYC/AML Risk (0-100)
2. Financial Risk (0-100)
3. Compliance Risk (0-100)
4. Operational Risk (0-100)

Provide:
- Individual scores with justification
- Overall risk score
- Risk level classification (CRITICAL/HIGH/MEDIUM/LOW/MINIMAL)
- Key findings
- Recommended actions""",
    )


class ComplianceCheckerPrompt:
    """Prompts for compliance checker agent."""

    COMPLIANCE_CHECK_PROMPT = PromptTemplate(
        input_variables=["vendor_industry", "vendor_country", "risk_level"],
        template="""Perform compliance check for vendor:
- Industry: {vendor_industry}
- Country: {vendor_country}
- Risk Level: {risk_level}

Verify compliance with:
1. Regulatory requirements for industry
2. Country-specific regulations
3. International standards (ISO, etc.)
4. Banking compliance standards
5. AML/CFT requirements

Provide:
- Compliance status
- Missing certifications/requirements
- Timeline for compliance
- Regulatory risk assessment
- Recommendations for remediation""",
    )


class ReportGeneratorPrompt:
    """Prompts for report generator agent."""

    REPORT_PROMPT = PromptTemplate(
        input_variables=["vendor_name", "kyc_findings", "risk_assessment", "compliance_findings"],
        template="""Generate comprehensive vendor risk onboarding report:

Vendor: {vendor_name}

KYC Findings:
{kyc_findings}

Risk Assessment:
{risk_assessment}

Compliance Findings:
{compliance_findings}

Create professional report including:
1. Executive Summary
2. Vendor Profile
3. KYC Findings and Verification Status
4. Risk Assessment with scores
5. Compliance Status
6. Key Findings
7. Recommendations
8. Approval/Rejection Recommendation
9. Next Steps

Format as audit-ready document.""",
    )


class AgentFactory:
    """Factory for creating agent configurations."""

    @staticmethod
    def create_document_processor_config() -> Dict[str, Any]:
        """Create document processor agent configuration."""
        return {
            "name": "DocumentProcessorAgent",
            "type": AgentType.DOCUMENT_PROCESSOR,
            "prompts": {
                "extraction": DocumentProcessorPrompt.EXTRACTION_PROMPT,
                "validation": DocumentProcessorPrompt.VALIDATION_PROMPT,
            },
            "description": "Processes vendor documents and extracts key information",
            "timeout": 300,
        }

    @staticmethod
    def create_kyc_validator_config() -> Dict[str, Any]:
        """Create KYC validator agent configuration."""
        return {
            "name": "KYCValidatorAgent",
            "type": AgentType.KYC_VALIDATOR,
            "prompts": {
                "kyc_check": KYCValidatorPrompt.KYC_CHECK_PROMPT,
            },
            "description": "Validates vendor KYC information against registries",
            "timeout": 300,
        }

    @staticmethod
    def create_risk_assessor_config() -> Dict[str, Any]:
        """Create risk assessor agent configuration."""
        return {
            "name": "RiskAssessorAgent",
            "type": AgentType.RISK_ASSESSOR,
            "prompts": {
                "assessment": RiskAssessorPrompt.ASSESSMENT_PROMPT,
            },
            "description": "Performs risk assessment across multiple dimensions",
            "timeout": 300,
        }

    @staticmethod
    def create_compliance_checker_config() -> Dict[str, Any]:
        """Create compliance checker agent configuration."""
        return {
            "name": "ComplianceCheckerAgent",
            "type": AgentType.COMPLIANCE_CHECKER,
            "prompts": {
                "compliance_check": ComplianceCheckerPrompt.COMPLIANCE_CHECK_PROMPT,
            },
            "description": "Checks regulatory compliance requirements",
            "timeout": 300,
        }

    @staticmethod
    def create_report_generator_config() -> Dict[str, Any]:
        """Create report generator agent configuration."""
        return {
            "name": "ReportGeneratorAgent",
            "type": AgentType.REPORT_GENERATOR,
            "prompts": {
                "report": ReportGeneratorPrompt.REPORT_PROMPT,
            },
            "description": "Generates audit-ready compliance reports",
            "timeout": 300,
        }


def create_workflow_graph() -> StateGraph:
    """Create LangGraph workflow state machine."""

    workflow = StateGraph(AgentState)

    # Note: Actual node implementations would be added here
    # This is the structure definition

    return workflow
