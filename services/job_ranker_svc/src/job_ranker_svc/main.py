from __future__ import annotations

import json
import logging
import os
import re

import httpx
from fastapi import FastAPI, HTTPException

from .models import RankRequest, RankResponse, RankedJob
from .ranker import JobRanker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Job Ranker Service")

# Global ranker instance
ranker = JobRanker()


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


async def _save_fit_report(job_id: str, company: str, title: str, fit_data: dict) -> bool:
    """Save fit report to storage service.

    Args:
        job_id: Job ID (used to extract numeric portion)
        company: Company name
        title: Job title
        fit_data: Fit score data to save

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        # Parse job_id to extract components
        # Expected format: "gh_company_12345" or "lever_company_uuid"
        company_clean = _sanitize_for_path(company)
        title_clean = _sanitize_for_path(title)

        # Extract numeric ID if possible, otherwise use last part
        id_match = re.search(r"(\d+)$", job_id)
        job_id_clean = id_match.group(1) if id_match else _sanitize_for_path(job_id.split("_")[-1])

        # Create path: jobs/{company}_{title}_{id}/fit_report.json
        job_folder = f"jobs/{company_clean}_{title_clean}_{job_id_clean}"
        fit_report_path = f"{job_folder}/fit_report.json"

        # Write to storage service
        storage_url = _storage_service_url()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{storage_url}/write",
                json={
                    "path": fit_report_path,
                    "content": json.dumps(fit_data, indent=2),
                    "kind": "text",
                },
            )

            if response.status_code == 200:
                logger.info(f"Saved fit report for job {job_id} to {job_folder}")
                return True
            else:
                logger.warning(
                    f"Failed to save fit report for job {job_id}: {response.status_code} - {response.text}"
                )
                return False

    except Exception as exc:
        logger.error(f"Error saving fit report for job {job_id}: {exc}")
        return False


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@app.post("/rank", response_model=RankResponse)
async def rank_jobs(request: RankRequest) -> RankResponse:
    """Rank jobs based on profile fit.

    Args:
        request: Profile and list of jobs to rank

    Returns:
        RankResponse with ranked jobs and fit scores
    """
    logger.info(f"Ranking {len(request.jobs)} jobs for profile")

    if not request.jobs:
        return RankResponse(ranked_jobs=[], total_jobs=0, saved_reports=0)

    # Rank jobs
    scored_jobs = ranker.rank_jobs(request.profile, request.jobs)

    # Build response
    ranked_jobs: list[RankedJob] = []
    saved_count = 0

    for job, fit_score in scored_jobs:
        ranked_jobs.append(RankedJob(job=job, fit_score=fit_score))

        # Save fit report for top 10 jobs
        if len(ranked_jobs) <= 10:
            fit_data = {
                "job_id": job.id,
                "score": fit_score.score,
                "matched_skills": fit_score.matched_skills,
                "gaps": fit_score.gaps,
                "seniority_match": fit_score.seniority_match,
                "explanation": fit_score.explanation,
                "job_title": job.title,
                "company": job.company,
                "location": job.location,
            }

            success = await _save_fit_report(job.id, job.company, job.title, fit_data)
            if success:
                saved_count += 1

    logger.info(f"Ranked {len(ranked_jobs)} jobs, saved {saved_count} fit reports")

    return RankResponse(
        ranked_jobs=ranked_jobs,
        total_jobs=len(ranked_jobs),
        saved_reports=saved_count,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9001)
