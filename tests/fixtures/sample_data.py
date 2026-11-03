"""Test fixtures and sample data."""

import pytest
import uuid
from datetime import datetime
from typing import Dict, Any

from src.db.models import (
    User,
    Vendor,
    VendorDocument,
    VendorStatus,
    RiskLevel,
    UserRole,
)
from src.agents.definitions import AgentState, Document, KYCData, RiskAssessmentResult


@pytest.fixture
def sample_user() -> User:
    """Create sample user."""
    return User(
        id=str(uuid.uuid4()),
        username="testuser",
        email="test@example.com",
        full_name="Test User",
        hashed_password="hashed_password",
        role=UserRole.COMPLIANCE_OFFICER,
        is_active=True,
    )


@pytest.fixture
def sample_vendor() -> Vendor:
    """Create sample vendor."""
    return Vendor(
        id=str(uuid.uuid4()),
        name="Test Vendor Inc",
        legal_name="Test Vendor Incorporated",
        registration_number="REG123456",
        country="US",
        industry="Technology",
        website="https://testvendor.com",
        contact_email="contact@testvendor.com",
        phone="+1-555-0123",
        status=VendorStatus.PENDING,
        risk_level=RiskLevel.HIGH,
        kyc_verified=False,
    )


@pytest.fixture
def sample_document() -> VendorDocument:
    """Create sample document."""
    return VendorDocument(
        id=str(uuid.uuid4()),
        vendor_id=str(uuid.uuid4()),
        file_name="financial_report.pdf",
        file_path="/data/uploads/financial_report.pdf",
        document_type="financial_report",
        file_size=1024000,
    )


@pytest.fixture
def sample_agent_state() -> AgentState:
    """Create sample agent state."""
    return AgentState(
        vendor_id=str(uuid.uuid4()),
        workflow_id=str(uuid.uuid4()),
        workflow_type="vendor_onboarding",
    )


@pytest.fixture
def sample_kyc_data() -> KYCData:
    """Create sample KYC data."""
    return KYCData(
        vendor_id=str(uuid.uuid4()),
        legal_name="Test Vendor Incorporated",
        registration_number="REG123456",
        country="US",
        is_verified=True,
        verification_date=datetime.utcnow(),
    )


@pytest.fixture
def sample_risk_assessment() -> RiskAssessmentResult:
    """Create sample risk assessment."""
    return RiskAssessmentResult(
        vendor_id=str(uuid.uuid4()),
        kyc_score=85.0,
        financial_score=75.0,
        compliance_score=90.0,
        operational_score=80.0,
        overall_score=82.5,
        risk_level="MEDIUM",
    )


@pytest.fixture
def sample_vendor_data() -> Dict[str, Any]:
    """Create sample vendor data."""
    return {
        "id": str(uuid.uuid4()),
        "name": "Test Vendor",
        "legal_name": "Test Vendor Inc",
        "registration_number": "REG123456",
        "country": "US",
        "industry": "Financial Services",
        "website": "https://testvendor.com",
        "contact_email": "contact@testvendor.com",
    }


@pytest.fixture
def sample_documents() -> list:
    """Create sample documents."""
    return [
        {
            "vendor_id": str(uuid.uuid4()),
            "file_name": "financial_report.pdf",
            "file_path": "/data/uploads/financial_report.pdf",
            "content": "2023 Financial Report...",
            "document_type": "financial_report",
        },
        {
            "vendor_id": str(uuid.uuid4()),
            "file_name": "compliance_cert.pdf",
            "file_path": "/data/uploads/compliance_cert.pdf",
            "content": "ISO 27001 Certification...",
            "document_type": "compliance",
        },
    ]


class TestDataFactory:
    """Factory for creating test data."""

    @staticmethod
    def create_vendor(**kwargs) -> Vendor:
        """Create a vendor with optional overrides."""
        defaults = {
            "id": str(uuid.uuid4()),
            "name": "Test Vendor",
            "legal_name": "Test Vendor Inc",
            "registration_number": f"REG{uuid.uuid4().hex[:8].upper()}",
            "country": "US",
            "industry": "Technology",
            "website": "https://testvendor.com",
            "contact_email": "test@testvendor.com",
            "phone": "+1-555-0123",
            "status": VendorStatus.PENDING,
            "risk_level": RiskLevel.MEDIUM,
            "kyc_verified": False,
        }
        defaults.update(kwargs)
        return Vendor(**defaults)

    @staticmethod
    def create_user(**kwargs) -> User:
        """Create a user with optional overrides."""
        defaults = {
            "id": str(uuid.uuid4()),
            "username": f"user_{uuid.uuid4().hex[:8]}",
            "email": f"user_{uuid.uuid4().hex[:8]}@example.com",
            "full_name": "Test User",
            "hashed_password": "hashed_password",
            "role": UserRole.COMPLIANCE_OFFICER,
            "is_active": True,
        }
        defaults.update(kwargs)
        return User(**defaults)

    @staticmethod
    def create_document(**kwargs) -> VendorDocument:
        """Create a document with optional overrides."""
        defaults = {
            "id": str(uuid.uuid4()),
            "vendor_id": str(uuid.uuid4()),
            "file_name": "document.pdf",
            "file_path": "/data/uploads/document.pdf",
            "document_type": "compliance",
            "file_size": 1024000,
        }
        defaults.update(kwargs)
        return VendorDocument(**defaults)
