from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException

from .models import TailorRequest, TailorResponse
from .tailor import CVTailor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="CV Builder Service")

# Global tailor instance
cv_tailor = CVTailor()


def _storage_service_url() -> str:
    """Get storage service URL from environment."""
    host = os.getenv("STORAGE_SERVICE_HOST", "localhost")
    port = os.getenv("STORAGE_SERVICE_PORT", "8000")
    return f"http://{host}:{port}"


def _sanitize_for_path(text: str) -> str:
    """Sanitize text for use in file paths."""
    sanitized = re.sub(r'[<>:"/\\|?*]', "", text)
    sanitized = re.sub(r"[\s\-]+", "_", sanitized)
    return sanitized[:50]


async def _load_profile() -> dict:
    """Load canonical profile from storage."""
    storage_url = _storage_service_url()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{storage_url}/read?path=profile/canonical_profile.json")
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Profile not found")
        return response.json()


async def _load_base_cv() -> str:
    """Load base CV from storage."""
    storage_url = _storage_service_url()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{storage_url}/read?path=profile/base_cv.md")
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Base CV not found")
        return response.text


async def _load_job(job_id: str) -> dict:
    """Load job data from storage."""
    # Parse job_id to find job folder
    # Expected format: "gh_company_12345" or similar
    company_match = re.search(r"_([a-zA-Z]+)_", job_id)
    if not company_match:
        raise HTTPException(status_code=400, detail="Invalid job_id format")

    # Try to find job.json file
    # We need to search for the job folder
    storage_url = _storage_service_url()
    async with httpx.AsyncClient(timeout=30.0) as client:
        # List jobs directory
        response = await client.get(f"{storage_url}/list?path=jobs")
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Jobs directory not found")

        # Find matching job folder
        data = response.json()
        entries = data.get("entries", [])

        job_folder = None
        for entry in entries:
            if entry.get("type") == "directory":
                folder_name = entry.get("name", "")
                if job_id.replace("_", "").lower() in folder_name.replace("_", "").lower():
                    job_folder = folder_name
                    break

        if not job_folder:
            raise HTTPException(status_code=404, detail=f"Job folder not found for {job_id}")

        # Load job.json
        job_file_path = f"jobs/{job_folder}/job.json"
        response = await client.get(f"{storage_url}/read?path={job_file_path}")
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail=f"Job file not found at {job_file_path}")

        return response.json()


async def _save_cv_to_job_folder(
    job_id: str, cv_markdown: str, cv_html: str, timestamp: str
) -> str:
    """Save CV files to job folder.

    Returns:
        Job folder name
    """
    storage_url = _storage_service_url()
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Find job folder (same logic as _load_job)
        response = await client.get(f"{storage_url}/list?path=jobs")
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Jobs directory not found")

        data = response.json()
        entries = data.get("entries", [])

        job_folder = None
        for entry in entries:
            if entry.get("type") == "directory":
                folder_name = entry.get("name", "")
                if job_id.replace("_", "").lower() in folder_name.replace("_", "").lower():
                    job_folder = folder_name
                    break

        if not job_folder:
            raise HTTPException(status_code=404, detail=f"Job folder not found for {job_id}")

        # Save markdown
        md_path = f"jobs/{job_folder}/cv_{timestamp}.md"
        await client.post(
            f"{storage_url}/write",
            json={"path": md_path, "content": cv_markdown, "kind": "text"},
        )

        # Save HTML
        html_path = f"jobs/{job_folder}/cv_{timestamp}.html"
        await client.post(
            f"{storage_url}/write",
            json={"path": html_path, "content": cv_html, "kind": "text"},
        )

        logger.info(f"Saved CV files to {job_folder}")
        return job_folder


async def _render_pdf(cv_html: str, job_folder: str, timestamp: str) -> str:
    """Render PDF using MCP PDF service.

    Returns:
        Path to generated PDF (will be moved to job folder)
    """
    import sys
    from pathlib import Path

    # Use MCP client to call pdf.render
    try:
        from mcp_clients import StdIOClient
    except ImportError:
        # Fallback: Add mcp_clients to path
        repo_root = Path(__file__).resolve().parents[4]
        mcp_clients_path = repo_root / "libs" / "mcp_clients" / "src"
        sys.path.insert(0, str(mcp_clients_path))
        from mcp_clients import StdIOClient

    # Call MCP PDF service
    client = StdIOClient("mcp_pdf")
    result = await client.call_tool("pdf.render", {"markup": cv_html, "template": "simple"})

    # Extract PDF path from result
    structured = result.structuredContent
    if hasattr(structured, "model_dump"):
        structured_dict = structured.model_dump()
    else:
        structured_dict = structured

    pdf_path = structured_dict.get("path", "")
    if not pdf_path:
        raise RuntimeError("PDF rendering failed - no path returned")

    # Move PDF to job folder
    jobsearch_home = Path(os.getenv("JOBSEARCH_HOME", str(Path.home() / "JobSearch")))
    job_folder_path = jobsearch_home / "jobs" / job_folder
    job_folder_path.mkdir(parents=True, exist_ok=True)

    target_pdf_path = job_folder_path / f"cv_{timestamp}.pdf"
    shutil.move(pdf_path, target_pdf_path)

    logger.info(f"Moved PDF to {target_pdf_path}")
    return str(target_pdf_path)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@app.post("/tailor-cv", response_model=TailorResponse)
async def tailor_cv(request: TailorRequest) -> TailorResponse:
    """Tailor CV for a specific job.

    Args:
        request: Job ID to tailor CV for

    Returns:
        TailorResponse with CV content and PDF path
    """
    job_id = request.job_id
    logger.info(f"Tailoring CV for job {job_id}")

    # Load required data
    profile = await _load_profile()
    base_cv = await _load_base_cv()
    job = await _load_job(job_id)

    logger.info(f"Loaded profile, base CV, and job data for {job['title']} at {job['company']}")

    # Generate tailored CV
    cv_markdown, cv_html, diff_summary = cv_tailor.tailor_cv(profile, job, base_cv)

    logger.info(
        f"Generated tailored CV: {len(diff_summary.added_bullets)} bullets added, "
        f"{len(diff_summary.removed_bullets)} bullets removed"
    )

    # Create timestamp
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    # Save CV files to job folder
    job_folder = await _save_cv_to_job_folder(job_id, cv_markdown, cv_html, timestamp)

    # Render PDF
    pdf_path = await _render_pdf(cv_html, job_folder, timestamp)

    logger.info(f"CV tailoring complete. PDF saved to {pdf_path}")

    return TailorResponse(
        job_id=job_id,
        cv_markdown=cv_markdown,
        cv_html=cv_html,
        pdf_path=pdf_path,
        diff_summary=diff_summary,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9002)
