from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException

from .models import JobPreparation, PrepareRequest, PrepareResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Orchestrator")


def _service_url(service_name: str, default_port: str) -> str:
    """Get service URL from environment."""
    host = os.getenv(f"{service_name.upper()}_HOST", "localhost")
    port = os.getenv(f"{service_name.upper()}_PORT", default_port)
    return f"http://{host}:{port}"


def _storage_service_url() -> str:
    """Get storage service URL from environment."""
    return _service_url("STORAGE_SERVICE", "8000")


def _job_finder_url() -> str:
    """Get job finder service URL."""
    return _service_url("JOB_FINDER_SERVICE", "9000")


def _job_ranker_url() -> str:
    """Get job ranker service URL."""
    return _service_url("JOB_RANKER_SERVICE", "9001")


def _cv_builder_url() -> str:
    """Get CV builder service URL."""
    return _service_url("CV_BUILDER_SERVICE", "9002")


def _doc_builder_url() -> str:
    """Get document builder service URL."""
    return _service_url("DOC_BUILDER_SERVICE", "9003")


def _jobsearch_home() -> Path:
    """Get JOBSEARCH_HOME directory."""
    home = os.getenv("JOBSEARCH_HOME", str(Path.home() / "JobSearch"))
    return Path(home)


async def _load_profile() -> dict:
    """Load canonical profile from storage."""
    storage_url = _storage_service_url()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{storage_url}/profile")
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Profile not found")
        return response.json()


def _extract_paths_from_response(response_data: dict, job_id: str) -> tuple[str, str, str]:
    """Extract file paths from service response.

    Returns:
        Tuple of (markdown_path, html_path, pdf_path)
    """
    jobsearch_home = _jobsearch_home()

    # Find job folder
    try:
        normalized_job_id = job_id.replace("_", "").replace(",", "").lower()

        for folder in (jobsearch_home / "jobs").iterdir():
            if folder.is_dir():
                normalized_folder = folder.name.replace("_", "").replace(",", "").lower()
                if normalized_job_id in normalized_folder:
                    # Extract timestamp from response or use latest file
                    pdf_path = response_data.get("pdf_path", "")

                    if pdf_path and Path(pdf_path).exists():
                        # Extract timestamp from PDF filename
                        timestamp_match = re.search(r"_(\d{8}T\d{6}Z)", pdf_path)
                        if timestamp_match:
                            timestamp = timestamp_match.group(1)
                            return (
                                str(folder / f"cv_{timestamp}.md"),
                                str(folder / f"cv_{timestamp}.html"),
                                pdf_path,
                            )

                    # Fallback: find latest files
                    md_files = list(folder.glob("cv_*.md"))
                    if md_files:
                        latest_md = max(md_files, key=lambda p: p.stat().st_mtime)
                        timestamp = latest_md.stem.split("_")[-1]
                        return (
                            str(latest_md),
                            str(folder / f"cv_{timestamp}.html"),
                            str(folder / f"cv_{timestamp}.pdf"),
                        )
    except Exception as exc:
        logger.warning(f"Error extracting paths for job {job_id}: {exc}")

    return ("", "", "")


def _extract_doc_paths(response_data: dict, job_id: str, doc_type: str) -> tuple[str, str, str]:
    """Extract document paths (cover letter or supplemental) from response.

    Args:
        response_data: Service response data
        job_id: Job ID
        doc_type: "cover" or "supplemental"

    Returns:
        Tuple of (markdown_path, html_path, pdf_path)
    """
    jobsearch_home = _jobsearch_home()

    try:
        normalized_job_id = job_id.replace("_", "").replace(",", "").lower()

        for folder in (jobsearch_home / "jobs").iterdir():
            if folder.is_dir():
                normalized_folder = folder.name.replace("_", "").replace(",", "").lower()
                if normalized_job_id in normalized_folder:
                    pdf_path = response_data.get("pdf_path", "")

                    if pdf_path and Path(pdf_path).exists():
                        timestamp_match = re.search(r"_(\d{8}T\d{6}Z)", pdf_path)
                        if timestamp_match:
                            timestamp = timestamp_match.group(1)
                            return (
                                str(folder / f"{doc_type}_{timestamp}.md"),
                                str(folder / f"{doc_type}_{timestamp}.html"),
                                pdf_path,
                            )

                    # Fallback: find latest files
                    md_files = list(folder.glob(f"{doc_type}_*.md"))
                    if md_files:
                        latest_md = max(md_files, key=lambda p: p.stat().st_mtime)
                        timestamp = latest_md.stem.split("_")[-1]
                        return (
                            str(latest_md),
                            str(folder / f"{doc_type}_{timestamp}.html"),
                            str(folder / f"{doc_type}_{timestamp}.pdf"),
                        )
    except Exception as exc:
        logger.warning(f"Error extracting {doc_type} paths for job {job_id}: {exc}")

    return ("", "", "")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@app.post("/prepare", response_model=PrepareResponse)
async def prepare_applications(request: PrepareRequest) -> PrepareResponse:
    """Prepare application materials for top matching jobs.

    Args:
        request: Search filters and preparation options

    Returns:
        PrepareResponse with dashboard path and job details
    """
    logger.info(f"Starting preparation for titles: {request.titles}, locations: {request.locations}")

    # Step 1: Load profile
    profile = await _load_profile()
    logger.info("Loaded profile")

    # Step 2: Search for jobs
    job_finder_url = _job_finder_url()
    search_payload = {
        "titles": request.titles,
        "locations": request.locations,
        "remote": request.remote,
        "salary_min": request.salary_min,
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        logger.info(f"Searching jobs at {job_finder_url}/search")
        search_response = await client.post(
            f"{job_finder_url}/search",
            json=search_payload,
        )

        if search_response.status_code != 200:
            raise HTTPException(
                status_code=search_response.status_code,
                detail=f"Job search failed: {search_response.text}",
            )

        search_data = search_response.json()
        all_jobs = search_data.get("postings", [])
        logger.info(f"Found {len(all_jobs)} jobs")

        if not all_jobs:
            logger.warning("No jobs found, returning empty response")
            return PrepareResponse(
                dashboard_path="",
                jobs_prepared=0,
                jobs=[],
                total_violations=0,
            )

        # Step 3: Rank jobs
        job_ranker_url = _job_ranker_url()
        rank_payload = {
            "profile": profile,
            "jobs": all_jobs,
        }

        logger.info(f"Ranking {len(all_jobs)} jobs at {job_ranker_url}/rank")
        rank_response = await client.post(
            f"{job_ranker_url}/rank",
            json=rank_payload,
        )

        if rank_response.status_code != 200:
            raise HTTPException(
                status_code=rank_response.status_code,
                detail=f"Job ranking failed: {rank_response.text}",
            )

        rank_data = rank_response.json()
        ranked_jobs = rank_data.get("ranked_jobs", [])
        logger.info(f"Ranked {len(ranked_jobs)} jobs")

        # Step 4: Select top N jobs
        top_jobs = ranked_jobs[: request.top_n]
        logger.info(f"Selected top {len(top_jobs)} jobs for preparation")

        # Step 5: Prepare materials for each job
        prepared_jobs: list[JobPreparation] = []
        all_artifact_paths: list[str] = []

        cv_builder_url = _cv_builder_url()
        doc_builder_url = _doc_builder_url()

        for ranked_job in top_jobs:
            job = ranked_job["job"]
            fit_score = ranked_job["fit_score"]

            job_id = job["id"]
            logger.info(f"Preparing materials for {job['title']} at {job['company']} (score: {fit_score['score']})")

            job_prep = JobPreparation(
                job_id=job_id,
                job_title=job["title"],
                company=job["company"],
                location=job["location"],
                apply_url=job["apply_url"],
                fit_score=fit_score["score"],
            )

            # Generate tailored CV
            try:
                logger.info(f"Tailoring CV for job {job_id}")
                cv_response = await client.post(
                    f"{cv_builder_url}/tailor-cv",
                    json={"job_id": job_id},
                    timeout=120.0,
                )

                if cv_response.status_code == 200:
                    cv_data = cv_response.json()
                    md_path, html_path, pdf_path = _extract_paths_from_response(cv_data, job_id)
                    job_prep.cv_path = md_path
                    job_prep.cv_html_path = html_path
                    job_prep.cv_pdf_path = pdf_path

                    if html_path:
                        all_artifact_paths.append(html_path)

                    logger.info(f"CV generated: {pdf_path}")
                else:
                    logger.warning(f"CV generation failed: {cv_response.status_code} - {cv_response.text}")
            except Exception as exc:
                logger.error(f"Error generating CV for {job_id}: {exc}")

            # Generate cover letter
            if request.generate_cover_letter:
                try:
                    logger.info(f"Generating cover letter for job {job_id}")
                    cover_response = await client.post(
                        f"{doc_builder_url}/cover-letter",
                        json={"job_id": job_id, "tone": request.cover_letter_tone},
                        timeout=120.0,
                    )

                    if cover_response.status_code == 200:
                        cover_data = cover_response.json()
                        md_path, html_path, pdf_path = _extract_doc_paths(cover_data, job_id, "cover")
                        job_prep.cover_letter_path = md_path
                        job_prep.cover_letter_html_path = html_path
                        job_prep.cover_letter_pdf_path = pdf_path

                        if html_path:
                            all_artifact_paths.append(html_path)

                        logger.info(f"Cover letter generated: {pdf_path}")
                    else:
                        logger.warning(f"Cover letter generation failed: {cover_response.status_code} - {cover_response.text}")
                except Exception as exc:
                    logger.error(f"Error generating cover letter for {job_id}: {exc}")

            # Generate supplementals
            if request.generate_supplementals and request.supplemental_questions:
                try:
                    logger.info(f"Generating supplemental documents for job {job_id}")
                    supp_response = await client.post(
                        f"{doc_builder_url}/supplementals",
                        json={
                            "job_id": job_id,
                            "questions": request.supplemental_questions,
                        },
                        timeout=120.0,
                    )

                    if supp_response.status_code == 200:
                        supp_data = supp_response.json()
                        md_path, html_path, pdf_path = _extract_doc_paths(supp_data, job_id, "supplemental")
                        job_prep.supplemental_path = md_path
                        job_prep.supplemental_html_path = html_path
                        job_prep.supplemental_pdf_path = pdf_path

                        if html_path:
                            all_artifact_paths.append(html_path)

                        logger.info(f"Supplemental documents generated: {pdf_path}")
                    else:
                        logger.warning(f"Supplemental generation failed: {supp_response.status_code} - {supp_response.text}")
                except Exception as exc:
                    logger.error(f"Error generating supplementals for {job_id}: {exc}")

            prepared_jobs.append(job_prep)

        # Step 6: Run validation across all artifacts
        logger.info(f"Running validation on {len(all_artifact_paths)} artifacts")
        total_violations = 0
        jobsearch_home = _jobsearch_home()

        if all_artifact_paths:
            try:
                # Convert absolute paths to relative paths for validation
                relative_paths = []
                for abs_path in all_artifact_paths:
                    try:
                        rel_path = Path(abs_path).relative_to(jobsearch_home)
                        relative_paths.append(str(rel_path))
                    except ValueError:
                        logger.warning(f"Path {abs_path} not relative to {jobsearch_home}")

                if relative_paths:
                    validate_response = await client.post(
                        f"{doc_builder_url}/validate",
                        json={
                            "artifact_paths": relative_paths,
                            "fail_on_violations": False,  # Don't fail, just collect violations
                        },
                        timeout=60.0,
                    )

                    if validate_response.status_code == 200:
                        validate_data = validate_response.json()
                        violations = validate_data.get("violations", [])
                        total_violations = len(violations)

                        # Map violations to jobs
                        for job_prep in prepared_jobs:
                            job_violations = [
                                v for v in violations
                                if any(
                                    path in v.get("artifact", "")
                                    for path in [
                                        job_prep.cv_html_path,
                                        job_prep.cover_letter_html_path,
                                        job_prep.supplemental_html_path,
                                    ]
                                    if path
                                )
                            ]
                            job_prep.validation_violations = len(job_violations)
                            job_prep.validation_passed = len(job_violations) == 0

                        logger.info(f"Validation complete: {total_violations} total violations")
                    else:
                        logger.warning(f"Validation failed: {validate_response.status_code}")
            except Exception as exc:
                logger.error(f"Error running validation: {exc}")

        # Step 7: Create dashboard JSON
        dashboard_data = {
            "jobs_prepared": len(prepared_jobs),
            "total_violations": total_violations,
            "jobs": [
                {
                    "job_id": job.job_id,
                    "job_title": job.job_title,
                    "company": job.company,
                    "location": job.location,
                    "apply_url": job.apply_url,
                    "fit_score": job.fit_score,
                    "cv_path": job.cv_path,
                    "cv_html_path": job.cv_html_path,
                    "cv_pdf_path": job.cv_pdf_path,
                    "cover_letter_path": job.cover_letter_path,
                    "cover_letter_html_path": job.cover_letter_html_path,
                    "cover_letter_pdf_path": job.cover_letter_pdf_path,
                    "supplemental_path": job.supplemental_path,
                    "supplemental_html_path": job.supplemental_html_path,
                    "supplemental_pdf_path": job.supplemental_pdf_path,
                    "validation_passed": job.validation_passed,
                    "validation_violations": job.validation_violations,
                }
                for job in prepared_jobs
            ],
        }

        dashboard_path = jobsearch_home / "review_dashboard.json"
        dashboard_path.write_text(json.dumps(dashboard_data, indent=2))
        logger.info(f"Dashboard saved to {dashboard_path}")

        return PrepareResponse(
            dashboard_path=str(dashboard_path),
            jobs_prepared=len(prepared_jobs),
            jobs=prepared_jobs,
            total_violations=total_violations,
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9004)
