"""Document ingestion and extraction schemas."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class DocumentCategory(str, Enum):
    CERTIFICATE_OF_INCORPORATION = "CERTIFICATE_OF_INCORPORATION"
    FINANCIAL_STATEMENT = "FINANCIAL_STATEMENT"
    TAX_CLEARANCE_CERTIFICATE = "TAX_CLEARANCE_CERTIFICATE"
    ISO_COMPLIANCE_CERTIFICATE = "ISO_COMPLIANCE_CERTIFICATE"
    BANK_CONFIRMATION_LETTER = "BANK_CONFIRMATION_LETTER"
    SOC2_AUDIT_REPORT = "SOC2_AUDIT_REPORT"
    DIRECTOR_ID = "DIRECTOR_ID"
    SANCTIONS_DECLARATION = "SANCTIONS_DECLARATION"
    CONTRACT = "CONTRACT"
    OTHER = "OTHER"


class ExtractedField(BaseModel):
    """Extracted key-value pair with confidence and provenance."""
    field_name: str
    value: Any
    confidence: float = Field(..., ge=0.0, le=1.0)
    page_number: Optional[int] = 1
    bounding_box: Optional[List[float]] = None
    source_snippet: Optional[str] = None


class ExtractedDocumentData(BaseModel):
    """Normalized structured payload extracted from a document."""
    document_id: str
    vendor_id: str
    category: DocumentCategory
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    requires_manual_validation: bool = False
    fields: Dict[str, ExtractedField] = Field(default_factory=dict)
    tables: List[List[Dict[str, Any]]] = Field(default_factory=list)
    raw_text: str = ""
    red_flags: List[str] = Field(default_factory=list)
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
