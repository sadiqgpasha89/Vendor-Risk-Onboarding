"""Database models for vendor risk onboarding."""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, Text, Enum, ForeignKey, JSON, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    """User roles for RBAC."""

    ADMIN = "admin"
    COMPLIANCE_OFFICER = "compliance_officer"
    RISK_MANAGER = "risk_manager"
    VENDOR_MANAGER = "vendor_manager"
    AUDITOR = "auditor"
    VIEWER = "viewer"


class VendorStatus(str, enum.Enum):
    """Vendor onboarding status."""

    PENDING = "pending"
    IN_REVIEW = "in_review"
    UNDER_ASSESSMENT = "under_assessment"
    APPROVED = "approved"
    CONDITIONAL_APPROVED = "conditional_approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class RiskLevel(str, enum.Enum):
    """Risk assessment levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MINIMAL = "minimal"


class User(Base):
    """User model for authentication and authorization."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.VIEWER, nullable=False)
    is_active = Column(Boolean, default=True)
    department = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    workflows = relationship("Workflow", back_populates="created_by_user")
    audit_logs = relationship("AuditLog", back_populates="user")

    __table_args__ = (Index("idx_user_email_active", "email", "is_active"),)


class Vendor(Base):
    """Vendor model for onboarding."""

    __tablename__ = "vendors"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False, index=True)
    legal_name = Column(String(255), nullable=True)
    registration_number = Column(String(255), unique=True, nullable=True, index=True)
    country = Column(String(100), nullable=True)
    industry = Column(String(255), nullable=True)
    website = Column(String(500), nullable=True)
    contact_email = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    status = Column(Enum(VendorStatus), default=VendorStatus.PENDING, nullable=False, index=True)
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.HIGH, nullable=False)
    risk_score = Column(Float, default=0.0)
    kyc_verified = Column(Boolean, default=False)
    kyc_verified_date = Column(DateTime, nullable=True)
    compliance_status = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    documents = relationship("VendorDocument", back_populates="vendor", cascade="all, delete-orphan")
    assessments = relationship("RiskAssessment", back_populates="vendor", cascade="all, delete-orphan")
    workflows = relationship("Workflow", back_populates="vendor")
    audit_records = relationship("AuditLog", back_populates="vendor")

    __table_args__ = (
        Index("idx_vendor_status_risk", "status", "risk_level"),
        Index("idx_vendor_reg_num", "registration_number"),
    )


class VendorDocument(Base):
    """Document model for vendor submissions."""

    __tablename__ = "vendor_documents"

    id = Column(String(36), primary_key=True)
    vendor_id = Column(String(36), ForeignKey("vendors.id"), nullable=False, index=True)
    file_name = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    document_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    extracted_text = Column(Text, nullable=True)
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    vendor = relationship("Vendor", back_populates="documents")
    analyses = relationship("DocumentAnalysis", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_document_vendor_type", "vendor_id", "document_type"),)


class DocumentAnalysis(Base):
    """Results of document analysis by agents."""

    __tablename__ = "document_analyses"

    id = Column(String(36), primary_key=True)
    document_id = Column(String(36), ForeignKey("vendor_documents.id"), nullable=False, index=True)
    agent_name = Column(String(100), nullable=False)
    analysis_type = Column(String(100), nullable=False)
    extracted_data = Column(JSON, nullable=True)
    findings = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)
    processing_time = Column(Float, nullable=True)
    status = Column(String(50), default="completed")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    document = relationship("VendorDocument", back_populates="analyses")

    __table_args__ = (Index("idx_analysis_doc_agent", "document_id", "agent_name"),)


class RiskAssessment(Base):
    """Risk assessment results."""

    __tablename__ = "risk_assessments"

    id = Column(String(36), primary_key=True)
    vendor_id = Column(String(36), ForeignKey("vendors.id"), nullable=False, index=True)
    workflow_id = Column(String(36), ForeignKey("workflows.id"), nullable=True)
    assessment_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    risk_level = Column(Enum(RiskLevel), nullable=False)
    overall_score = Column(Float, nullable=False)
    kyc_score = Column(Float, nullable=True)
    financial_score = Column(Float, nullable=True)
    compliance_score = Column(Float, nullable=True)
    operational_score = Column(Float, nullable=True)
    findings = Column(Text, nullable=True)
    recommendations = Column(Text, nullable=True)
    assessor_notes = Column(Text, nullable=True)
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    vendor = relationship("Vendor", back_populates="assessments")
    workflow = relationship("Workflow", back_populates="assessments")

    __table_args__ = (Index("idx_assessment_vendor_date", "vendor_id", "assessment_date"),)


class Workflow(Base):
    """Workflow execution tracking."""

    __tablename__ = "workflows"

    id = Column(String(36), primary_key=True)
    vendor_id = Column(String(36), ForeignKey("vendors.id"), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    workflow_type = Column(String(100), nullable=False)
    status = Column(String(50), default="in_progress")
    start_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    execution_log = Column(JSON, nullable=True)
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    vendor = relationship("Vendor", back_populates="workflows")
    created_by_user = relationship("User", back_populates="workflows")
    assessments = relationship("RiskAssessment", back_populates="workflow")

    __table_args__ = (Index("idx_workflow_vendor_status", "vendor_id", "status"),)


class AuditLog(Base):
    """Audit trail for compliance."""

    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    vendor_id = Column(String(36), ForeignKey("vendors.id"), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(100), nullable=False)
    resource_id = Column(String(36), nullable=True)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    reason = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    user = relationship("User", back_populates="audit_logs")
    vendor = relationship("Vendor", back_populates="audit_records")

    __table_args__ = (
        Index("idx_audit_user_action", "user_id", "action"),
        Index("idx_audit_resource", "resource_type", "resource_id"),
        Index("idx_audit_timestamp", "created_at"),
    )


class EvaluationResult(Base):
    """LLMOps evaluation results."""

    __tablename__ = "evaluation_results"

    id = Column(String(36), primary_key=True)
    workflow_id = Column(String(36), ForeignKey("workflows.id"), nullable=True)
    evaluation_name = Column(String(100), nullable=False)
    metric_name = Column(String(100), nullable=False)
    score = Column(Float, nullable=False)
    passed = Column(Boolean, nullable=False)
    threshold = Column(Float, nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (Index("idx_eval_workflow", "workflow_id"),)


class ModelMetrics(Base):
    """Track LLM model performance metrics."""

    __tablename__ = "model_metrics"

    id = Column(String(36), primary_key=True)
    model_name = Column(String(100), nullable=False, index=True)
    model_version = Column(String(50), nullable=True)
    metric_type = Column(String(100), nullable=False)
    metric_value = Column(Float, nullable=False)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cost = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (Index("idx_model_metrics_time", "model_name", "created_at"),)
