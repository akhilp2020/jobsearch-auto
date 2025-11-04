from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from io import StringIO
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .models import (
    ArtifactRecord,
    AuditEntry,
    AuditRun,
    CreateRunRequest,
    CreateRunResponse,
    LogAuditRequest,
    OperationType,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Audit Service")


def _audit_dir() -> Path:
    """Get audit storage directory."""
    home = os.getenv("JOBSEARCH_HOME", str(Path.home() / "JobSearch"))
    audit_dir = Path(home) / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    return audit_dir


def _redact_pii(text: str) -> str:
    """Redact PII from text.

    Args:
        text: Text to redact

    Returns:
        Redacted text with PII removed
    """
    # Redact email addresses
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)

    # Redact phone numbers (various formats)
    text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]', text)
    text = re.sub(r'\b\(\d{3}\)\s*\d{3}[-.]?\d{4}\b', '[PHONE]', text)

    # Redact API keys/tokens (common patterns)
    text = re.sub(r'sk-[a-zA-Z0-9]{48}', '[API_KEY]', text)
    text = re.sub(r'Bearer\s+[a-zA-Z0-9_-]+', 'Bearer [TOKEN]', text)

    # Redact credit card numbers
    text = re.sub(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', '[CARD]', text)

    # Redact SSN
    text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]', text)

    return text


def _compute_hash(content: str | bytes) -> str:
    """Compute SHA256 hash of content.

    Args:
        content: Content to hash

    Returns:
        Hex digest of hash
    """
    if isinstance(content, str):
        content = content.encode('utf-8')
    return hashlib.sha256(content).hexdigest()


def _generate_run_id() -> str:
    """Generate unique run ID."""
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    return f"run_{timestamp}_{os.urandom(4).hex()}"


def _generate_entry_id() -> str:
    """Generate unique entry ID."""
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    return f"entry_{timestamp}_{os.urandom(4).hex()}"


def _load_run(run_id: str) -> AuditRun:
    """Load audit run from storage.

    Args:
        run_id: Run ID to load

    Returns:
        AuditRun object

    Raises:
        HTTPException: If run not found
    """
    audit_dir = _audit_dir()
    run_file = audit_dir / f"{run_id}.json"

    if not run_file.exists():
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    run_data = json.loads(run_file.read_text())
    return AuditRun(**run_data)


def _save_run(run: AuditRun) -> None:
    """Save audit run to storage.

    Args:
        run: AuditRun to save
    """
    audit_dir = _audit_dir()
    run_file = audit_dir / f"{run.run_id}.json"
    run_file.write_text(json.dumps(run.model_dump(), indent=2))
    logger.info(f"Saved audit run {run.run_id}")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@app.post("/audit/run", response_model=CreateRunResponse)
async def create_run(request: CreateRunRequest) -> CreateRunResponse:
    """Create a new audit run.

    Args:
        request: Run creation parameters

    Returns:
        CreateRunResponse with run ID
    """
    run_id = _generate_run_id()
    created_at = datetime.now().isoformat()

    run = AuditRun(
        run_id=run_id,
        created_at=created_at,
        trigger=request.trigger,
        job_ids=request.job_ids,
    )

    _save_run(run)

    logger.info(f"Created audit run {run_id} for trigger {request.trigger}")

    return CreateRunResponse(
        run_id=run_id,
        created_at=created_at,
    )


@app.post("/audit/log")
async def log_audit_entry(request: LogAuditRequest) -> dict[str, str]:
    """Log an audit entry to a run.

    Args:
        request: Audit entry data

    Returns:
        Success message with entry ID
    """
    # Load existing run
    run = _load_run(request.run_id)

    # Create entry
    entry_id = _generate_entry_id()

    # Redact prompt if not already redacted
    prompt_redacted = request.prompt_redacted
    if prompt_redacted and not any(marker in prompt_redacted for marker in ['[EMAIL]', '[PHONE]', '[API_KEY]']):
        prompt_redacted = _redact_pii(prompt_redacted)

    entry = AuditEntry(
        entry_id=entry_id,
        run_id=request.run_id,
        operation=request.operation,
        timestamp_start=request.timestamp_start,
        timestamp_end=request.timestamp_end or datetime.now().isoformat(),
        prompt_redacted=prompt_redacted,
        tool_calls=request.tool_calls,
        artifacts=request.artifacts,
        status=request.status,
        error_message=request.error_message,
        metadata=request.metadata,
    )

    # Add entry to run
    run.entries.append(entry)
    run.total_operations = len(run.entries)

    # Update success/failure counts
    run.successful_operations = sum(1 for e in run.entries if e.status == "SUCCESS")
    run.failed_operations = sum(1 for e in run.entries if e.status == "FAILED")

    # Update completion timestamp if not set
    if not run.completed_at:
        run.completed_at = datetime.now().isoformat()

    _save_run(run)

    logger.info(f"Logged {request.operation} entry {entry_id} to run {request.run_id}")

    return {"status": "logged", "entry_id": entry_id, "run_id": request.run_id}


@app.get("/audit/{run_id}", response_model=AuditRun)
async def get_audit_run(run_id: str) -> AuditRun:
    """Get audit run by ID.

    Args:
        run_id: Run ID to retrieve

    Returns:
        Complete audit run with all entries
    """
    return _load_run(run_id)


@app.get("/audit/export")
async def export_audit_csv(format: str = "csv") -> StreamingResponse:
    """Export all audit data to CSV.

    Args:
        format: Export format (currently only 'csv' supported)

    Returns:
        CSV file download
    """
    if format != "csv":
        raise HTTPException(status_code=400, detail="Only CSV format is supported")

    audit_dir = _audit_dir()
    all_runs = []

    # Load all runs
    for run_file in audit_dir.glob("run_*.json"):
        try:
            run_data = json.loads(run_file.read_text())
            all_runs.append(AuditRun(**run_data))
        except Exception as exc:
            logger.warning(f"Failed to load {run_file}: {exc}")

    # Build CSV
    output = StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        "run_id",
        "entry_id",
        "operation",
        "timestamp_start",
        "timestamp_end",
        "status",
        "prompt_redacted",
        "tool_calls_count",
        "artifacts_count",
        "artifacts_paths",
        "artifacts_hashes",
        "error_message",
        "job_ids",
        "trigger",
    ])

    # Write data
    for run in all_runs:
        for entry in run.entries:
            artifact_paths = ";".join(a.path for a in entry.artifacts)
            artifact_hashes = ";".join(a.hash for a in entry.artifacts)

            writer.writerow([
                run.run_id,
                entry.entry_id,
                entry.operation,
                entry.timestamp_start,
                entry.timestamp_end,
                entry.status,
                entry.prompt_redacted[:100] if entry.prompt_redacted else "",  # Truncate for CSV
                len(entry.tool_calls),
                len(entry.artifacts),
                artifact_paths,
                artifact_hashes,
                entry.error_message,
                ";".join(run.job_ids),
                run.trigger,
            ])

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_export.csv"},
    )


@app.get("/audit")
async def list_audit_runs() -> dict:
    """List all audit runs.

    Returns:
        List of run IDs with basic info
    """
    audit_dir = _audit_dir()
    runs = []

    for run_file in sorted(audit_dir.glob("run_*.json"), reverse=True):
        try:
            run_data = json.loads(run_file.read_text())
            runs.append({
                "run_id": run_data["run_id"],
                "created_at": run_data["created_at"],
                "trigger": run_data["trigger"],
                "total_operations": run_data.get("total_operations", 0),
                "successful_operations": run_data.get("successful_operations", 0),
                "failed_operations": run_data.get("failed_operations", 0),
                "job_ids": run_data.get("job_ids", []),
            })
        except Exception as exc:
            logger.warning(f"Failed to load {run_file}: {exc}")

    return {"runs": runs, "total": len(runs)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)
