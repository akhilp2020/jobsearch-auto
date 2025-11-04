from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException

from .document_builder import CoverLetterBuilder, SupplementalBuilder
from .models import (
    CoverLetterRequest,
    CoverLetterResponse,
    SupplementalRequest,
    SupplementalResponse,
    ValidateRequest,
    ValidateResponse,
    ValidationViolation,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Doc Builder Service")

# Global builder instances
cover_letter_builder = CoverLetterBuilder()
supplemental_builder = SupplementalBuilder()


def _storage_service_url() -> str:
    """Get storage service URL from environment."""
    host = os.getenv("STORAGE_SERVICE_HOST", "localhost")
    port = os.getenv("STORAGE_SERVICE_PORT", "8000")
    return f"http://{host}:{port}"


async def _load_profile() -> dict:
    """Load canonical profile from storage."""
    storage_url = _storage_service_url()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{storage_url}/profile")
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Profile not found")
        return response.json()


async def _load_job(job_id: str) -> dict:
    """Load job data from storage."""
    import json
    import sys

    # Use MCP client to read job.json
    try:
        from mcp_clients import DirectFsClient
    except ImportError:
        # Fallback: Add mcp_clients to path
        repo_root = Path(__file__).resolve().parents[4]
        mcp_clients_path = repo_root / "libs" / "mcp_clients" / "src"
        sys.path.insert(0, str(mcp_clients_path))
        from mcp_clients import DirectFsClient

    # Find job folder
    storage_url = _storage_service_url()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{storage_url}/list?path=jobs")
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Jobs directory not found")

        data = response.json()
        entries = data.get("entries", [])

        job_folder = None
        for entry in entries:
            if entry.get("is_dir", False):
                folder_name = entry.get("name", "")
                # Normalize both for comparison (remove underscores and commas)
                normalized_job_id = job_id.replace("_", "").replace(",", "").lower()
                normalized_folder = folder_name.replace("_", "").replace(",", "").lower()
                if normalized_job_id in normalized_folder:
                    job_folder = folder_name
                    break

        if not job_folder:
            raise HTTPException(status_code=404, detail=f"Job folder not found for {job_id}")

    # Read job.json using MCP client
    fs_client = DirectFsClient()
    job_file_path = f"jobs/{job_folder}/job.json"

    try:
        result = await fs_client.read(job_file_path)
        content = result.get("content", "")
        return json.loads(content)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Job file not found: {exc}") from exc


async def _find_job_folder(job_id: str) -> str:
    """Find job folder name for a given job_id."""
    storage_url = _storage_service_url()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{storage_url}/list?path=jobs")
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Jobs directory not found")

        data = response.json()
        entries = data.get("entries", [])

        for entry in entries:
            if entry.get("is_dir", False):
                folder_name = entry.get("name", "")
                # Normalize both for comparison (remove underscores and commas)
                normalized_job_id = job_id.replace("_", "").replace(",", "").lower()
                normalized_folder = folder_name.replace("_", "").replace(",", "").lower()
                if normalized_job_id in normalized_folder:
                    return folder_name

        raise HTTPException(status_code=404, detail=f"Job folder not found for {job_id}")


async def _save_document_to_job_folder(
    job_id: str, filename: str, content: str, kind: str = "text"
) -> str:
    """Save document to job folder.

    Args:
        job_id: Job ID
        filename: Name of file to save
        content: File content
        kind: Content kind ("text" or "binary")

    Returns:
        Full path to saved file
    """
    job_folder = await _find_job_folder(job_id)
    storage_url = _storage_service_url()

    file_path = f"jobs/{job_folder}/{filename}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(
            f"{storage_url}/write",
            json={"path": file_path, "content": content, "kind": kind},
        )

    logger.info(f"Saved {filename} to {job_folder}")
    return file_path


async def _render_pdf(html_content: str, job_folder: str, filename: str) -> str:
    """Render PDF using MCP PDF service.

    Args:
        html_content: HTML content to render
        job_folder: Job folder name
        filename: Target filename (e.g., "cover_20241103.pdf")

    Returns:
        Path to generated PDF
    """
    import sys

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
    result = await client.call_tool("pdf.render", {"markup": html_content, "template": "simple"})

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

    target_pdf_path = job_folder_path / filename
    shutil.move(pdf_path, target_pdf_path)

    logger.info(f"Moved PDF to {target_pdf_path}")
    return str(target_pdf_path)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@app.post("/cover-letter", response_model=CoverLetterResponse)
async def create_cover_letter(request: CoverLetterRequest) -> CoverLetterResponse:
    """Generate a cover letter for a job.

    Args:
        request: Cover letter request with job_id and optional tone

    Returns:
        CoverLetterResponse with markdown, HTML, and PDF path
    """
    job_id = request.job_id
    tone = request.tone
    logger.info(f"Generating cover letter for job {job_id} with tone: {tone}")

    # Load required data
    profile = await _load_profile()
    job = await _load_job(job_id)

    logger.info(f"Loaded profile and job data for {job['title']} at {job['company']}")

    # Generate cover letter
    cover_letter_md, cover_letter_html = cover_letter_builder.generate_cover_letter(
        profile, job, tone
    )

    logger.info("Generated cover letter")

    # Create timestamp
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    # Save markdown to job folder
    await _save_document_to_job_folder(
        job_id, f"cover_{timestamp}.md", cover_letter_md, "text"
    )

    # Save HTML to job folder
    await _save_document_to_job_folder(
        job_id, f"cover_{timestamp}.html", cover_letter_html, "text"
    )

    # Render PDF (optional - may fail if MCP PDF service unavailable)
    job_folder = await _find_job_folder(job_id)
    pdf_path = ""
    try:
        pdf_path = await _render_pdf(cover_letter_html, job_folder, f"cover_{timestamp}.pdf")
        logger.info(f"PDF rendered successfully: {pdf_path}")
    except Exception as exc:
        logger.warning(f"PDF rendering failed (continuing without PDF): {exc}")
        pdf_path = f"PDF rendering failed: {exc}"

    logger.info(f"Cover letter complete. Markdown and HTML saved to {job_folder}")

    return CoverLetterResponse(
        job_id=job_id,
        cover_letter_markdown=cover_letter_md,
        cover_letter_html=cover_letter_html,
        pdf_path=pdf_path,
        tone=tone,
    )


@app.post("/supplementals", response_model=SupplementalResponse)
async def create_supplementals(request: SupplementalRequest) -> SupplementalResponse:
    """Generate supplemental documents answering specific questions.

    Args:
        request: Supplemental request with job_id and questions

    Returns:
        SupplementalResponse with markdown, HTML, and PDF paths
    """
    job_id = request.job_id
    questions = request.questions
    logger.info(f"Generating supplemental documents for job {job_id} with {len(questions)} questions")

    # Load required data
    profile = await _load_profile()
    job = await _load_job(job_id)

    logger.info(f"Loaded profile and job data for {job['title']} at {job['company']}")

    # Convert questions to dict format
    questions_dict = [q.model_dump() for q in questions]

    # Generate supplemental document
    supplemental_md, supplemental_html = supplemental_builder.generate_supplemental(
        profile, job, questions_dict
    )

    logger.info("Generated supplemental documents")

    # Create timestamp
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    # Save markdown to job folder
    md_path = await _save_document_to_job_folder(
        job_id, f"supplemental_{timestamp}.md", supplemental_md, "text"
    )

    # Save HTML to job folder
    await _save_document_to_job_folder(
        job_id, f"supplemental_{timestamp}.html", supplemental_html, "text"
    )

    # Render PDF (optional - may fail if MCP PDF service unavailable)
    job_folder = await _find_job_folder(job_id)
    pdf_path = ""
    try:
        pdf_path = await _render_pdf(supplemental_html, job_folder, f"supplemental_{timestamp}.pdf")
        logger.info(f"PDF rendered successfully: {pdf_path}")
    except Exception as exc:
        logger.warning(f"PDF rendering failed (continuing without PDF): {exc}")
        pdf_path = f"PDF rendering failed: {exc}"

    logger.info(f"Supplemental documents complete. Markdown and HTML saved to {job_folder}")

    return SupplementalResponse(
        job_id=job_id,
        supplemental_markdown=supplemental_md,
        supplemental_html=supplemental_html,
        pdf_path=pdf_path,
        markdown_path=md_path,
    )


@app.post("/validate", response_model=ValidateResponse)
async def validate_artifacts_endpoint(request: ValidateRequest) -> ValidateResponse:
    """Validate artifacts against profile guardrails.

    Args:
        request: Validation request with artifact paths

    Returns:
        ValidateResponse with pass/fail and violations
    """
    import sys

    # Add guardrails to path
    try:
        from guardrails import validate_artifacts
    except ImportError:
        repo_root = Path(__file__).resolve().parents[4]
        guardrails_path = repo_root / "libs" / "guardrails" / "src"
        sys.path.insert(0, str(guardrails_path))
        from guardrails import validate_artifacts

    # Get paths
    jobsearch_home = Path(os.getenv("JOBSEARCH_HOME", str(Path.home() / "JobSearch")))
    profile_path = jobsearch_home / "profile" / "canonical_profile.json"

    # Convert relative paths to absolute
    artifact_paths = [jobsearch_home / path for path in request.artifact_paths]

    # Run validation
    result = validate_artifacts(str(profile_path), [str(p) for p in artifact_paths])

    # Convert to response model
    violations = [
        ValidationViolation(
            artifact=v.artifact,
            line=v.line,
            reason=v.reason,
        )
        for v in result.violations
    ]

    # Fail if requested
    if request.fail_on_violations and not result.passed:
        raise HTTPException(
            status_code=400,
            detail=f"Validation failed with {len(violations)} violations",
        )

    logger.info(
        f"Validation complete: {len(violations)} violations, passed={result.passed}"
    )

    return ValidateResponse(
        passed=result.passed,
        violations=violations,
        suggestions=result.suggestions,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
