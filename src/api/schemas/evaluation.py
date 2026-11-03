"""Evaluation schemas."""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel


class EvaluationMetricResult(BaseModel):
    """Evaluation metric result."""

    metric_name: str
    score: float
    passed: bool
    threshold: Optional[float] = None
    details: Optional[Dict[str, Any]] = None


class EvaluationResponse(BaseModel):
    """Schema for evaluation response."""

    evaluation_id: str
    workflow_id: str
    status: str
    metrics: List[EvaluationMetricResult]
    overall_score: float
    passed: bool
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EvaluationListResponse(BaseModel):
    """Schema for evaluation list response."""

    items: List[EvaluationResponse]
    total: int
    skip: int
    limit: int


class EvaluationRequest(BaseModel):
    """Request to run evaluation."""

    workflow_id: str
    evaluation_names: Optional[List[str]] = None
