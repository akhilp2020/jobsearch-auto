from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel

from mcp_clients import FsClient, MCPClientError

ALLOWED_TOP_LEVEL = {"profile", "jobs", "logs", "exports"}


class DirectoryEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    modified: float


class ListResponse(BaseModel):
    entries: list[DirectoryEntry]


class WriteRequest(BaseModel):
    path: str
    content: str
    kind: Literal["text", "binary"] = "text"


class WriteResponse(BaseModel):
    path: str
    size: int
    modified: float


app = FastAPI(title="Storage Service")
fs_client = FsClient()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


def _jobsearch_home() -> Path:
    raw = os.getenv("JOBSEARCH_HOME")
    if not raw:
        raise RuntimeError("JOBSEARCH_HOME environment variable is required")
    base = Path(raw).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ensure_default_structure() -> None:
    base = _jobsearch_home()
    for folder in ALLOWED_TOP_LEVEL:
        (base / folder).mkdir(parents=True, exist_ok=True)


def _validate_job_folder(name: str) -> None:
    segments = [segment for segment in name.split("_") if segment]
    if len(segments) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job directories must follow jobs/{company}_{title}_{jobId}/ structure.",
        )
    job_id = segments[-1]
    if not job_id.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job directory suffix must be a numeric jobId.",
        )


def _normalize_path(raw: str, *, for_listing: bool) -> str:
    try:
        candidate = PurePosixPath(raw)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path format.") from exc

    if candidate.is_absolute():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path must be relative.")

    parts = candidate.parts
    if not parts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path is required.")

    if any(part in ("", ".", "..") for part in parts):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path contains invalid segments.")

    top_level = parts[0]
    if top_level not in ALLOWED_TOP_LEVEL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Top-level directory '{top_level}' is not allowed.",
        )

    if top_level == "jobs":
        if len(parts) == 1 and not for_listing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Write paths under jobs/ must target a specific job directory.",
            )
        if len(parts) >= 2:
            _validate_job_folder(parts[1])
        if not for_listing and len(parts) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Write paths under jobs/ must include a file inside a job directory.",
            )
    else:
        if not for_listing and len(parts) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Write paths under {top_level}/ must include a file name.",
            )

    return "/".join(parts)


@app.on_event("startup")
async def startup() -> None:
    """Ensure directory scaffolding is present before serving traffic."""
    _ensure_default_structure()


@app.get("/list", response_model=ListResponse)
async def list_entries(path: str | None = Query(default=None)) -> ListResponse:
    """List files within the managed storage hierarchy."""
    normalized_path = None
    if path:
        normalized_path = _normalize_path(path, for_listing=True)
    try:
        listing = await fs_client.list(normalized_path)
    except MCPClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MCP fs.list failed: {exc}",
        ) from exc

    entries_raw = listing.get("entries", [])
    entries = [DirectoryEntry.model_validate(entry) for entry in entries_raw]
    return ListResponse(entries=entries)


@app.post("/write", response_model=WriteResponse)
async def write_file(payload: WriteRequest) -> WriteResponse:
    """Write file contents via the MCP FS server."""
    normalized_path = _normalize_path(payload.path, for_listing=False)
    try:
        metadata: dict[str, Any] = await fs_client.write(
            normalized_path,
            payload.content,
            payload.kind,
        )
    except MCPClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MCP fs.write failed: {exc}",
        ) from exc

    return WriteResponse.model_validate(metadata)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
