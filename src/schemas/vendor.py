"""Strongly-typed vendor domain schemas."""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class VendorRiskTier(str, Enum):
    MINIMAL = "MINIMAL"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class VendorOnboardingStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    IN_ASSESSMENT = "IN_ASSESSMENT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED_FOR_REVIEW = "FLAGGED_FOR_REVIEW"
    FROZEN = "FROZEN"


class VendorProfile(BaseModel):
    """Normalized vendor profile model."""
    id: str = Field(..., description="Unique vendor ID")
    name: str = Field(..., description="Vendor business trade name")
    legal_name: str = Field(..., description="Registered legal corporate entity name")
    registration_number: str = Field(..., description="Official corporate registration / tax ID")
    country: str = Field(..., description="Country of incorporation (ISO 2-letter or name)")
    industry: Optional[str] = None
    website: Optional[str] = None
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_routing_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_country: Optional[str] = None
    bank_account_updated_at: Optional[datetime] = None
    incorporation_date: Optional[datetime] = None
    annual_revenue_usd: Optional[float] = None
    employee_count: Optional[int] = None
    parent_company: Optional[str] = None
    beneficial_owners: List[str] = Field(default_factory=list)
    status: VendorOnboardingStatus = VendorOnboardingStatus.PENDING_VERIFICATION
    risk_level: VendorRiskTier = VendorRiskTier.MEDIUM
    risk_score: float = 0.0
    kyc_verified: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BatchVendorScreenRequest(BaseModel):
    """Request schema for batch screening multiple vendors."""
    vendors: List[VendorProfile]
    run_deep_agentic_eval: bool = False
    priority: str = "normal"
