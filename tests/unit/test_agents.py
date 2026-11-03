"""Unit tests for agents."""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import uuid

from src.agents.orchestrator import OrchestratorAgent
from src.agents.definitions import AgentState, AgentType


@pytest.mark.unit
class TestOrchestratorAgent:
    """Tests for orchestrator agent."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator instance."""
        return OrchestratorAgent()

    def test_orchestrator_initialization(self, orchestrator):
        """Test orchestrator initialization."""
        assert orchestrator.agent_type == AgentType.ORCHESTRATOR
        assert orchestrator.llm is not None
        assert orchestrator.workflow_state is None

    @pytest.mark.asyncio
    async def test_orchestrate_vendor_onboarding(self, orchestrator):
        """Test vendor onboarding orchestration."""
        vendor_id = str(uuid.uuid4())
        vendor_data = {
            "name": "Test Vendor",
            "legal_name": "Test Vendor Inc",
            "country": "US",
        }
        documents = []

        with patch.object(
            orchestrator, "_process_documents", new_callable=AsyncMock
        ), patch.object(
            orchestrator, "_validate_kyc", new_callable=AsyncMock
        ), patch.object(
            orchestrator, "_assess_risk", new_callable=AsyncMock
        ), patch.object(
            orchestrator, "_check_compliance", new_callable=AsyncMock
        ), patch.object(
            orchestrator, "_generate_report", new_callable=AsyncMock
        ):
            state = await orchestrator.orchestrate_vendor_onboarding(
                vendor_id=vendor_id,
                vendor_data=vendor_data,
                documents=documents,
            )

        assert state.vendor_id == vendor_id
        assert state.status == "completed"
        assert state.end_time is not None

    def test_create_document(self, orchestrator):
        """Test document creation."""
        doc_data = {
            "vendor_id": str(uuid.uuid4()),
            "file_name": "test.pdf",
            "file_path": "/path/test.pdf",
            "content": "Test content",
        }

        doc = orchestrator._create_document(doc_data)

        assert doc.file_name == "test.pdf"
        assert doc.content == "Test content"
        assert doc.vendor_id == doc_data["vendor_id"]

    def test_extract_findings_from_json(self, orchestrator):
        """Test extracting findings from JSON response."""
        response = '{"findings": ["Risk A", "Risk B", "Risk C"]}'
        findings = orchestrator._extract_findings(response)

        assert len(findings) == 3
        assert "Risk A" in findings

    def test_extract_findings_from_text(self, orchestrator):
        """Test extracting findings from text response."""
        response = """
        Findings:
        - Finding 1
        - Finding 2
        - Finding 3
        """
        findings = orchestrator._extract_findings(response)

        assert len(findings) >= 1
