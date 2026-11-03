"""Workflow state and event schemas."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class WorkflowStepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class WorkflowStepRecord(BaseModel):
    step_name: str
    status: WorkflowStepStatus
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_ms: float = 0.0
    error_message: Optional[str] = None
    output_summary: Optional[Dict[str, Any]] = None


class WorkflowExecutionRecord(BaseModel):
    workflow_id: str
    vendor_id: str
    workflow_type: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    total_latency_ms: float = 0.0
    steps: List[WorkflowStepRecord] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
