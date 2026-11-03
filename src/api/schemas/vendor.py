"""API request/response schemas."""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, EmailStr


# ==================== VENDOR SCHEMAS ====================

class VendorCreate(BaseModel):
    """Schema for creating a vendor."""

    name: str
    legal_name: Optional[str] = None
    registration_number: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    contact_email: Optional[str] = None
    phone: Optional[str] = None


class VendorUpdate(BaseModel):
    """Schema for updating a vendor."""

    name: Optional[str] = None
    legal_name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    contact_email: Optional[str] = None
    phone: Optional[str] = None


class VendorResponse(BaseModel):
    """Schema for vendor response."""

    id: str
    name: str
    legal_name: Optional[str]
    registration_number: Optional[str]
    country: Optional[str]
    industry: Optional[str]
    website: Optional[str]
    contact_email: Optional[str]
    phone: Optional[str]
    status: str
    risk_level: str
    risk_score: float
    kyc_verified: bool
    kyc_verified_date: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VendorListResponse(BaseModel):
    """Schema for vendor list response."""

    items: List[VendorResponse]
    total: int
    skip: int
    limit: int


# ==================== WORKFLOW SCHEMAS ====================

class WorkflowCreate(BaseModel):
    """Schema for creating a workflow."""

    vendor_id: str
    workflow_type: str


class WorkflowResponse(BaseModel):
    """Schema for workflow response."""

    id: str
    vendor_id: str
    workflow_type: str
    status: str
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[float]
    created_at: datetime

    class Config:
        from_attributes = True


class WorkflowListResponse(BaseModel):
    """Schema for workflow list response."""

    items: List[WorkflowResponse]
    total: int
    skip: int
    limit: int


# ==================== EVALUATION SCHEMAS ====================

class EvaluationMetricResult(BaseModel):
    """Evaluation metric result."""

    metric_name: str
    score: float
    passed: bool
    threshold: Optional[float]


class EvaluationResponse(BaseModel):
    """Schema for evaluation response."""

    evaluation_id: str
    workflow_id: str
    status: str
    metrics: List[EvaluationMetricResult]
    overall_score: float
    created_at: datetime
    completed_at: Optional[datetime]


# ==================== DOCUMENT SCHEMAS ====================

class DocumentResponse(BaseModel):
    """Schema for document response."""

    id: str
    vendor_id: str
    file_name: str
    file_path: str
    document_type: Optional[str]
    file_size: Optional[int]
    created_at: datetime
    uploaded_at: datetime


# ==================== AUDIT LOG SCHEMAS ====================

class AuditLogResponse(BaseModel):
    """Schema for audit log response."""

    id: str
    user_id: Optional[str]
    vendor_id: Optional[str]
    action: str
    resource_type: str
    resource_id: Optional[str]
    old_value: Optional[Dict[str, Any]]
    new_value: Optional[Dict[str, Any]]
    reason: Optional[str]
    created_at: datetime


# ==================== USER SCHEMAS ====================

class UserCreate(BaseModel):
    """Schema for creating a user."""

    username: str
    email: EmailStr
    full_name: Optional[str] = None
    password: str
    role: str = "viewer"


class UserResponse(BaseModel):
    """Schema for user response."""

    id: str
    username: str
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== MONITORING SCHEMAS ====================

class MetricsResponse(BaseModel):
    """Schema for metrics response."""

    operation: str
    metrics: List[Dict[str, Any]]


class CostSummaryResponse(BaseModel):
    """Schema for cost summary response."""

    total_cost: float
    cost_by_model: Dict[str, float]
    usage_by_model: Dict[str, Dict[str, int]]


class WorkflowLogResponse(BaseModel):
    """Schema for workflow log response."""

    workflow_id: str
    events: List[Dict[str, Any]]
