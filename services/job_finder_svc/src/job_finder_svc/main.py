from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, status

from .adapters import GreenhouseAdapter, LeverAdapter, WorkdayAdapter
from .models import JobPosting, SearchFilters, SearchResponse
from .rate_limiter import RateLimiter, RobotsChecker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Job Finder Service")

# Global instances
rate_limiter = RateLimiter(requests_per_second=2.0)
robots_checker = RobotsChecker()

# Adapters
greenhouse_adapter = GreenhouseAdapter()
lever_adapter = LeverAdapter()
workday_adapter = WorkdayAdapter()


def _storage_service_url() -> str:
    """Get storage service URL from environment."""
    host = os.getenv("STORAGE_SERVICE_HOST", "localhost")
    port = os.getenv("STORAGE_SERVICE_PORT", "8000")
    return f"http://{host}:{port}"


def _sanitize_for_path(text: str) -> str:
    """Sanitize text for use in file paths."""
    # Remove/replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', "", text)
    # Replace spaces and other chars with underscore
    sanitized = re.sub(r"[\s\-]+", "_", sanitized)
    # Limit length
    return sanitized[:50]


async def _save_job_to_storage(job: JobPosting) -> bool:
    """Save job posting to storage service."""
    try:
        # Create job folder path: jobs/{company}_{title}_{id}/
        company_clean = _sanitize_for_path(job.company)
        title_clean = _sanitize_for_path(job.title)
        # Extract numeric ID if possible, otherwise use last part
        id_match = re.search(r"(\d+)$", job.id)
        job_id_clean = id_match.group(1) if id_match else _sanitize_for_path(job.id.split("_")[-1])

        job_folder = f"jobs/{company_clean}_{title_clean}_{job_id_clean}"
        job_file_path = f"{job_folder}/job.json"

        # Prepare job data
        job_data = {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "jd_text": job.jd_text,
            "requirements": job.requirements,
            "source": job.source,
            "apply_url": job.apply_url,
            "raw_data": job.raw_data,
        }

        # Write to storage service
        storage_url = _storage_service_url()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{storage_url}/write",
                json={"path": job_file_path, "content": json.dumps(job_data, indent=2), "kind": "text"},
            )

            if response.status_code == 200:
                logger.info(f"Saved job {job.id} to {job_folder}")
                return True
            else:
                logger.warning(
                    f"Failed to save job {job.id}: {response.status_code} - {response.text}"
                )
                return False

    except Exception as exc:
        logger.error(f"Error saving job {job.id}: {exc}")
        return False


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
async def search_jobs(filters: SearchFilters) -> SearchResponse:
    """Search for job postings across multiple sources.

    Args:
        filters: Search filters including titles, locations, remote, salary_min

    Returns:
        SearchResponse with matching job postings
    """
    logger.info(f"Searching with filters: {filters.model_dump()}")

    all_postings: list[JobPosting] = []

    # Search Greenhouse
    try:
        greenhouse_jobs = await greenhouse_adapter.search(filters)
        all_postings.extend(greenhouse_jobs)
        logger.info(f"Found {len(greenhouse_jobs)} jobs from Greenhouse")
    except Exception as exc:
        logger.error(f"Greenhouse search failed: {exc}")

    # Search Lever
    try:
        lever_jobs = await lever_adapter.search(filters)
        all_postings.extend(lever_jobs)
        logger.info(f"Found {len(lever_jobs)} jobs from Lever")
    except Exception as exc:
        logger.error(f"Lever search failed: {exc}")

    # Search Workday (currently returns empty)
    try:
        workday_jobs = await workday_adapter.search(filters)
        all_postings.extend(workday_jobs)
        logger.info(f"Found {len(workday_jobs)} jobs from Workday")
    except Exception as exc:
        logger.error(f"Workday search failed: {exc}")

    # Deduplicate by apply_url
    seen_urls: set[str] = set()
    unique_postings: list[JobPosting] = []
    for posting in all_postings:
        if posting.apply_url not in seen_urls:
            seen_urls.add(posting.apply_url)
            unique_postings.append(posting)

    logger.info(f"Total unique jobs found: {len(unique_postings)}")

    # Save a subset of jobs to storage (to avoid overwhelming storage)
    saved_count = 0
    jobs_to_save = unique_postings[:10]  # Save first 10 jobs

    for job in jobs_to_save:
        success = await _save_job_to_storage(job)
        if success:
            saved_count += 1

    return SearchResponse(
        postings=unique_postings,
        total_found=len(unique_postings),
        saved_count=saved_count,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9000)
