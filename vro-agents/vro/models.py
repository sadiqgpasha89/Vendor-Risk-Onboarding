"""Contracts (plan §6.2, §15.1). Pydantic is the source; JSON Schemas are exported to contracts/."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .util import now, word_count

DataType = Literal["none", "public", "internal", "confidential", "customer_pii", "payment_card",
                   "authentication_secrets", "regulated_other"]
Volume = Literal["none", "low", "medium", "high", "very_high"]
AccessType = Literal["none", "read_only", "read_write", "privileged", "network_connectivity"]
Criticality = Literal["low", "medium", "high", "critical"]
Substitutability = Literal["easy", "moderate", "hard", "very_hard"]
Jurisdiction = Literal["US", "EU", "IN", "UK", "OTHER"]
Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
Domain = Literal["security", "resilience", "privacy", "financial", "contract", "concentration", "entity",
                 "regulatory", "screening", "document_integrity"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataAccess(Strict):
    data_types: list[DataType] = Field(min_length=1)
    volume: Volume
    storage_locations: list[str] = []
    access_type: AccessType


class DeclaredOwner(Strict):
    name: str
    pct: float = Field(ge=0, le=100)
    country_iso2: str | None = None
    is_person: bool = False


class VendorIntake(Strict):
    legal_name: str = Field(min_length=2, max_length=300)
    trade_names: list[str] = []
    country_iso2: str = Field(pattern=r"^[A-Z]{2}$")
    registration_number: str | None = None
    lei: str | None = Field(default=None, pattern=r"^[A-Z0-9]{18}[0-9]{2}$")
    website: str | None = None
    service_description: str = Field(max_length=4000)
    business_owner: str
    annual_spend_usd: float | None = Field(default=None, ge=0)
    data_access: DataAccess
    criticality_hint: Criticality
    substitutability: Substitutability = "moderate"
    subcontractors: list[str] = []
    jurisdictions: list[Jurisdiction] = Field(min_length=1)
    emergency: bool = False
    # Extensions to the plan's schema (documented in docs/BUILD_LOG.md): inputs the scoring factors and
    # ownership screening need but the abridged schema omitted.
    customer_facing: bool = False
    regulatory_critical: bool = False
    declared_owners: list[DeclaredOwner] = []
    directors: list[str] = []
    contract_text_doc_hint: str | None = None


class Evidence(Strict):
    source_type: Literal["document", "api", "list", "human"]
    doc_id: str | None = None
    chunk_id: str | None = None
    page: int | None = None
    locator: str | None = None
    quote: str | None = None  # <= 40 words, verbatim (GR-003)
    source_sha256: str
    source_version: str | None = None
    retrieved_at: datetime = Field(default_factory=now)
    stance: Literal["SUPPORTS", "CONTRADICTS"] = "SUPPORTS"

    @field_validator("quote")
    @classmethod
    def _quote_len(cls, v):
        if v is not None and word_count(v) > 40:
            raise ValueError("quote exceeds 40 words")
        return v


class Claim(Strict):
    claim_id: str | None = None
    subject: str
    predicate: str
    object: Any = None
    statement: str
    evidence: list[Evidence] = Field(min_length=1)  # R2: no claim without evidence
    confidence: float = Field(ge=0, le=1)
    valid_until: datetime | None = None


class Finding(Strict):
    domain: Domain
    severity: Severity
    title: str
    description: str
    claim_ids: list[str] = Field(min_length=1)
    regulation_refs: list[str] = []
    remediation: str | None = None
    rule_id: str | None = None


class Question(Strict):
    to_role: Literal["analyst", "infosec", "legal", "aml", "sponsor", "vendor_via_analyst"]
    text: str
    why_it_matters: str
    blocking: bool = False
    options: list[str] | None = None


class AgentResult(Strict):
    status: Literal["OK", "NEEDS_INPUT", "INSUFFICIENT_EVIDENCE", "ERROR", "REFUSED_UNSAFE_INPUT"]
    claims: list[Claim] = []
    findings: list[Finding] = []
    questions: list[Question] = []
    confidence: float = Field(default=0.0, ge=0, le=1)
    notes: str | None = None
    flags: list[str] = []
    data: dict = {}   # agent-specific structured payload (e.g. TierProposal, VerificationReport)


class ExtractedField(Strict):
    name: str
    value: Any = None
    found: bool = False
    page: int | None = None
    quote: str | None = None


class DocExtraction(Strict):
    """Reader (A4) output: schema-only, produced without tools (GR-008)."""
    doc_id: str
    doc_type: str
    fields: list[ExtractedField] = []
    lists: dict[str, list[dict]] = {}
    flags: list[str] = []


class GateDecision(Strict):
    decision: Literal["APPROVE", "REJECT", "CLEAR", "CONFIRM_MATCH", "CONFIRM", "OVERRIDE", "ACCEPT_RISK",
                      "REQUEST_REWORK", "ESCALATE"]
    rationale: str = Field(min_length=3)
    conditions: list[str] = []
    override_tier: int | None = Field(default=None, ge=1, le=4)
    reason_code: str | None = None
    expires_at: str | None = None
    subject: str | None = None  # screening subject or finding id the decision applies to


class TierProposal(Strict):
    inherent_score: float
    tier: int
    factors: dict[str, dict]
    floors_applied: list[str]
    rationale: str
    scoring_version: str


class ScreeningRecommendation(Strict):
    subject_name: str
    top_score: float
    recommendation: Literal["NO_CANDIDATE", "LIKELY_FALSE_POSITIVE", "LIKELY_TRUE_MATCH", "NEEDS_HUMAN"]
    explanation: str
