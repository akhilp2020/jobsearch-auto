"""Helper functions for audit logging."""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def _audit_service_url() -> str:
    """Get audit service URL."""
    host = os.getenv("AUDIT_SERVICE_HOST", "localhost")
    port = os.getenv("AUDIT_SERVICE_PORT", "8002")
    return f"http://{host}:{port}"


def _compute_file_hash(file_path: str | Path) -> str:
    """Compute SHA256 hash of file.

    Args:
        file_path: Path to file

    Returns:
        Hex digest of hash, or empty string if file doesn't exist
    """
    try:
        path = Path(file_path)
        if path.exists():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception as exc:
        logger.warning(f"Could not hash {file_path}: {exc}")
    return ""


async def create_audit_run(trigger: str, job_ids: list[str]) -> str:
    """Create a new audit run.

    Args:
        trigger: What triggered this run (USER, SCHEDULED, API)
        job_ids: Job IDs being processed

    Returns:
        Run ID
    """
    try:
        audit_url = _audit_service_url()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{audit_url}/audit/run",
                json={"trigger": trigger, "job_ids": job_ids},
            )

            if response.status_code == 200:
                data = response.json()
                run_id = data["run_id"]
                logger.info(f"Created audit run {run_id}")
                return run_id
            else:
                logger.warning(f"Failed to create audit run: {response.status_code}")
                return ""
    except Exception as exc:
        logger.error(f"Error creating audit run: {exc}")
        return ""


async def log_audit_entry(
    run_id: str,
    operation: str,
    timestamp_start: str,
    timestamp_end: str,
    status: str,
    prompt_redacted: str = "",
    tool_calls: list = None,
    artifacts: list = None,
    error_message: str = "",
    metadata: dict = None,
) -> None:
    """Log an audit entry.

    Args:
        run_id: Run ID
        operation: Operation type (PREPARE, APPLY, BUILD_CV, etc.)
        timestamp_start: Start timestamp
        timestamp_end: End timestamp
        status: Operation status (SUCCESS, FAILED, PARTIAL)
        prompt_redacted: Redacted prompt text
        tool_calls: List of tool calls made
        artifacts: List of artifact records
        error_message: Error message if failed
        metadata: Additional metadata
    """
    if not run_id:
        return

    try:
        audit_url = _audit_service_url()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{audit_url}/audit/log",
                json={
                    "run_id": run_id,
                    "operation": operation,
                    "timestamp_start": timestamp_start,
                    "timestamp_end": timestamp_end,
                    "status": status,
                    "prompt_redacted": prompt_redacted or "",
                    "tool_calls": tool_calls or [],
                    "artifacts": artifacts or [],
                    "error_message": error_message,
                    "metadata": metadata or {},
                },
            )

            if response.status_code == 200:
                logger.debug(f"Logged audit entry for {operation}")
            else:
                logger.warning(f"Failed to log audit entry: {response.status_code}")
    except Exception as exc:
        logger.error(f"Error logging audit entry: {exc}")


def create_artifact_record(file_path: str, artifact_type: str) -> dict:
    """Create an artifact record with hash.

    Args:
        file_path: Path to artifact file
        artifact_type: Type (cv, cover_letter, supplemental, screenshot, evidence)

    Returns:
        Artifact record dict
    """
    path = Path(file_path)
    return {
        "path": str(file_path),
        "type": artifact_type,
        "hash": _compute_file_hash(file_path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }
