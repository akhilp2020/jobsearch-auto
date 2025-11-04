from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OperationType(str, Enum):
    """Type of operation being audited."""

    PREPARE = "PREPARE"
    RANK = "RANK"
    BUILD_CV = "BUILD_CV"
    BUILD_COVER = "BUILD_COVER"
    BUILD_SUPPLEMENTAL = "BUILD_SUPPLEMENTAL"
    VALIDATE = "VALIDATE"
    APPLY = "APPLY"
    NOTIFY = "NOTIFY"


class ToolCall(BaseModel):
    """Record of a tool call (e.g., MCP, LLM)."""

    tool_name: str = Field(..., description="Name of the tool called")
    timestamp: str = Field(..., description="ISO timestamp of call")
    input_hash: str = Field(default="", description="Hash of input parameters")
    output_hash: str = Field(default="", description="Hash of output")
    duration_ms: int = Field(default=0, description="Duration in milliseconds")
    error: str = Field(default="", description="Error message if failed")


class ArtifactRecord(BaseModel):
    """Record of an artifact file."""

    path: str = Field(..., description="Path to artifact")
    type: str = Field(..., description="Type: cv, cover_letter, supplemental, screenshot, evidence")
    hash: str = Field(default="", description="SHA256 hash of file contents")
    size_bytes: int = Field(default=0, description="File size in bytes")


class AuditEntry(BaseModel):
    """Single audit entry for an operation."""

    entry_id: str = Field(..., description="Unique entry ID")
    run_id: str = Field(..., description="Run ID this entry belongs to")
    operation: OperationType = Field(..., description="Type of operation")
    timestamp_start: str = Field(..., description="ISO timestamp when operation started")
    timestamp_end: str = Field(default="", description="ISO timestamp when operation ended")
    prompt_redacted: str = Field(default="", description="Redacted prompt (PII removed)")
    tool_calls: list[ToolCall] = Field(default_factory=list, description="Tool calls made")
    artifacts: list[ArtifactRecord] = Field(default_factory=list, description="Artifacts created")
    status: str = Field(..., description="SUCCESS, FAILED, PARTIAL")
    error_message: str = Field(default="", description="Error message if failed")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class AuditRun(BaseModel):
    """Complete audit trail for a run."""

    run_id: str = Field(..., description="Unique run ID")
    created_at: str = Field(..., description="ISO timestamp when run started")
    completed_at: str = Field(default="", description="ISO timestamp when run completed")
    trigger: str = Field(..., description="What triggered this run: USER, SCHEDULED, API")
    job_ids: list[str] = Field(default_factory=list, description="Job IDs processed in this run")
    entries: list[AuditEntry] = Field(default_factory=list, description="Audit entries")
    total_operations: int = Field(default=0, description="Total operations in this run")
    successful_operations: int = Field(default=0, description="Successful operations")
    failed_operations: int = Field(default=0, description="Failed operations")


class LogAuditRequest(BaseModel):
    """Request to log an audit entry."""

    run_id: str = Field(..., description="Run ID")
    operation: OperationType = Field(..., description="Operation type")
    timestamp_start: str = Field(..., description="Start timestamp")
    timestamp_end: str = Field(default="", description="End timestamp")
    prompt_redacted: str = Field(default="", description="Redacted prompt")
    tool_calls: list[ToolCall] = Field(default_factory=list, description="Tool calls")
    artifacts: list[ArtifactRecord] = Field(default_factory=list, description="Artifacts")
    status: str = Field(..., description="Operation status")
    error_message: str = Field(default="", description="Error message")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class CreateRunRequest(BaseModel):
    """Request to create a new audit run."""

    trigger: str = Field(..., description="What triggered this run")
    job_ids: list[str] = Field(default_factory=list, description="Job IDs to process")


class CreateRunResponse(BaseModel):
    """Response with new run ID."""

    run_id: str = Field(..., description="Created run ID")
    created_at: str = Field(..., description="Creation timestamp")
