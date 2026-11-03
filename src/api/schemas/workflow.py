"""Workflow schemas."""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel


class WorkflowCreate(BaseModel):
    """Schema for creating a workflow."""

    vendor_id: str
    workflow_type: str


class WorkflowUpdate(BaseModel):
    """Schema for updating a workflow."""

    status: Optional[str] = None


class WorkflowResponse(BaseModel):
    """Schema for workflow response."""

    id: str
    vendor_id: str
    created_by: Optional[str]
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


class WorkflowExecutionLogEvent(BaseModel):
    """Workflow execution log event."""

    timestamp: datetime
    event_type: str
    agent: str
    status: str
    data: Dict[str, Any]


class WorkflowLogResponse(BaseModel):
    """Schema for workflow log response."""

    workflow_id: str
    events: List[WorkflowExecutionLogEvent]
