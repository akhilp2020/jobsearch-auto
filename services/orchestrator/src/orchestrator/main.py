from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .models import (
    ApplicationStatus,
    ApplyRequest,
    ApplyResponse,
    ApproveRequest,
    JobPreparation,
    PrepareRequest,
    PrepareResponse,
    RejectRequest,
    RequiredField,
    ReviewResponse,
)

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


def _load_dashboard() -> dict:
    """Load dashboard from file."""
    dashboard_path = _jobsearch_home() / "review_dashboard.json"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="No dashboard found. Run /prepare first.")
    return json.loads(dashboard_path.read_text())


def _save_dashboard(dashboard_data: dict) -> None:
    """Save dashboard to file."""
    dashboard_path = _jobsearch_home() / "review_dashboard.json"
    dashboard_path.write_text(json.dumps(dashboard_data, indent=2))


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
                    "status": job.status.value,
                    "rejection_reason": job.rejection_reason,
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


@app.get("/review", response_model=ReviewResponse)
async def get_review_dashboard() -> ReviewResponse:
    """Get the latest review dashboard.

    Returns:
        ReviewResponse with all jobs and their status
    """
    dashboard_data = _load_dashboard()

    jobs = []
    for job_data in dashboard_data.get("jobs", []):
        jobs.append(
            JobPreparation(
                job_id=job_data["job_id"],
                job_title=job_data["job_title"],
                company=job_data["company"],
                location=job_data["location"],
                apply_url=job_data["apply_url"],
                fit_score=job_data["fit_score"],
                cv_path=job_data.get("cv_path", ""),
                cv_html_path=job_data.get("cv_html_path", ""),
                cv_pdf_path=job_data.get("cv_pdf_path", ""),
                cover_letter_path=job_data.get("cover_letter_path", ""),
                cover_letter_html_path=job_data.get("cover_letter_html_path", ""),
                cover_letter_pdf_path=job_data.get("cover_letter_pdf_path", ""),
                supplemental_path=job_data.get("supplemental_path", ""),
                supplemental_html_path=job_data.get("supplemental_html_path", ""),
                supplemental_pdf_path=job_data.get("supplemental_pdf_path", ""),
                validation_passed=job_data.get("validation_passed", False),
                validation_violations=job_data.get("validation_violations", 0),
                status=ApplicationStatus(job_data.get("status", "PENDING_REVIEW")),
                rejection_reason=job_data.get("rejection_reason", ""),
            )
        )

    return ReviewResponse(
        jobs_prepared=dashboard_data.get("jobs_prepared", 0),
        total_violations=dashboard_data.get("total_violations", 0),
        jobs=jobs,
    )


@app.post("/approve")
async def approve_application(request: ApproveRequest) -> dict[str, str]:
    """Approve a job application.

    Args:
        request: Job ID to approve

    Returns:
        Success message
    """
    dashboard_data = _load_dashboard()

    job_found = False
    for job_data in dashboard_data.get("jobs", []):
        if job_data["job_id"] == request.job_id:
            job_data["status"] = ApplicationStatus.READY_TO_APPLY.value
            job_data["rejection_reason"] = ""
            job_found = True
            logger.info(f"Approved job {request.job_id}")
            break

    if not job_found:
        raise HTTPException(status_code=404, detail=f"Job {request.job_id} not found")

    _save_dashboard(dashboard_data)

    return {"status": "approved", "job_id": request.job_id}


@app.post("/reject")
async def reject_application(request: RejectRequest) -> dict[str, str]:
    """Reject a job application.

    Args:
        request: Job ID and rejection reason

    Returns:
        Success message
    """
    dashboard_data = _load_dashboard()

    job_found = False
    for job_data in dashboard_data.get("jobs", []):
        if job_data["job_id"] == request.job_id:
            job_data["status"] = ApplicationStatus.REJECTED.value
            job_data["rejection_reason"] = request.reason
            job_found = True
            logger.info(f"Rejected job {request.job_id}: {request.reason}")
            break

    if not job_found:
        raise HTTPException(status_code=404, detail=f"Job {request.job_id} not found")

    _save_dashboard(dashboard_data)

    return {"status": "rejected", "job_id": request.job_id, "reason": request.reason}


@app.get("/files/{file_path:path}")
async def serve_file(file_path: str) -> FileResponse:
    """Serve static files (PDFs, HTML) from JobSearch directory.

    Args:
        file_path: Relative path from JOBSEARCH_HOME

    Returns:
        File content
    """
    jobsearch_home = _jobsearch_home()
    full_path = jobsearch_home / file_path

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Security check: ensure file is within JOBSEARCH_HOME
    try:
        full_path.resolve().relative_to(jobsearch_home.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(full_path)


@app.get("/", response_class=HTMLResponse)
async def review_ui() -> str:
    """Serve the review dashboard UI.

    Returns:
        HTML page with job review interface
    """
    try:
        dashboard_data = _load_dashboard()
    except HTTPException:
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Job Review Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; max-width: 1200px; margin: 40px auto; padding: 20px; }
                .error { color: #d32f2f; background: #ffebee; padding: 20px; border-radius: 4px; }
            </style>
        </head>
        <body>
            <h1>Job Review Dashboard</h1>
            <div class="error">
                <p>No dashboard found. Please run POST /prepare first to generate application materials.</p>
            </div>
        </body>
        </html>
        """

    jobs = dashboard_data.get("jobs", [])

    jobs_html = ""
    for job in jobs:
        status = job.get("status", "PENDING_REVIEW")
        status_color = {
            "PENDING_REVIEW": "#ff9800",
            "READY_TO_APPLY": "#4caf50",
            "REJECTED": "#f44336",
        }.get(status, "#999")

        cv_link = ""
        if job.get("cv_pdf_path"):
            rel_path = Path(job["cv_pdf_path"]).relative_to(_jobsearch_home())
            cv_link = f'<a href="/files/{rel_path}" target="_blank">CV PDF</a>'

        cover_link = ""
        if job.get("cover_letter_pdf_path"):
            rel_path = Path(job["cover_letter_pdf_path"]).relative_to(_jobsearch_home())
            cover_link = f'<a href="/files/{rel_path}" target="_blank">Cover Letter PDF</a>'

        supp_link = ""
        if job.get("supplemental_pdf_path"):
            rel_path = Path(job["supplemental_pdf_path"]).relative_to(_jobsearch_home())
            supp_link = f'<a href="/files/{rel_path}" target="_blank">Supplemental PDF</a>'

        validation_badge = (
            '<span class="badge badge-success">✓ Validated</span>'
            if job.get("validation_passed")
            else f'<span class="badge badge-error">✗ {job.get("validation_violations", 0)} violations</span>'
        )

        rejection_reason = ""
        if status == "REJECTED" and job.get("rejection_reason"):
            rejection_reason = f'<p class="rejection-reason"><strong>Reason:</strong> {job["rejection_reason"]}</p>'

        jobs_html += f"""
        <div class="job-card">
            <div class="job-header">
                <div>
                    <h3>{job['job_title']}</h3>
                    <p class="company">{job['company']} • {job['location']}</p>
                </div>
                <div class="status-badge" style="background-color: {status_color};">
                    {status.replace('_', ' ')}
                </div>
            </div>
            <div class="job-details">
                <p><strong>Fit Score:</strong> {job['fit_score']}/100</p>
                <p><strong>Validation:</strong> {validation_badge}</p>
                {rejection_reason}
            </div>
            <div class="job-actions">
                <div class="links">
                    {cv_link} {cover_link} {supp_link}
                    <a href="{job['apply_url']}" target="_blank">Apply URL</a>
                </div>
                <div class="buttons">
                    <button onclick="approveJob('{job['job_id']}')" class="btn btn-approve">Approve</button>
                    <button onclick="showRejectModal('{job['job_id']}', '{job['job_title']}')" class="btn btn-reject">Reject</button>
                </div>
            </div>
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Job Review Dashboard</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            h1 {{ color: #1976d2; margin-bottom: 10px; }}
            .summary {{
                background: white;
                padding: 20px;
                border-radius: 8px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .job-card {{
                background: white;
                padding: 20px;
                margin-bottom: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .job-header {{
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                margin-bottom: 15px;
            }}
            h3 {{ margin: 0 0 5px 0; color: #333; }}
            .company {{ color: #666; margin: 0; font-size: 14px; }}
            .status-badge {{
                padding: 6px 12px;
                border-radius: 4px;
                color: white;
                font-size: 12px;
                font-weight: bold;
                text-transform: uppercase;
            }}
            .job-details {{ margin-bottom: 15px; }}
            .job-details p {{ margin: 5px 0; font-size: 14px; }}
            .badge {{
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }}
            .badge-success {{ background: #4caf50; color: white; }}
            .badge-error {{ background: #f44336; color: white; }}
            .job-actions {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding-top: 15px;
                border-top: 1px solid #eee;
            }}
            .links a {{
                margin-right: 15px;
                color: #1976d2;
                text-decoration: none;
            }}
            .links a:hover {{ text-decoration: underline; }}
            .buttons {{ display: flex; gap: 10px; }}
            .btn {{
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
                font-weight: 500;
            }}
            .btn-approve {{ background: #4caf50; color: white; }}
            .btn-approve:hover {{ background: #45a049; }}
            .btn-reject {{ background: #f44336; color: white; }}
            .btn-reject:hover {{ background: #da190b; }}
            .rejection-reason {{
                color: #d32f2f;
                background: #ffebee;
                padding: 10px;
                border-radius: 4px;
                margin-top: 10px;
            }}
            .modal {{
                display: none;
                position: fixed;
                z-index: 1000;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0,0,0,0.5);
            }}
            .modal-content {{
                background-color: white;
                margin: 15% auto;
                padding: 30px;
                border-radius: 8px;
                width: 500px;
                max-width: 90%;
            }}
            .modal-content h2 {{ margin-top: 0; }}
            .modal-content textarea {{
                width: 100%;
                min-height: 100px;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-family: inherit;
                font-size: 14px;
            }}
            .modal-buttons {{
                display: flex;
                gap: 10px;
                margin-top: 20px;
                justify-content: flex-end;
            }}
            .btn-cancel {{ background: #999; color: white; }}
            .btn-cancel:hover {{ background: #777; }}
        </style>
    </head>
    <body>
        <h1>Job Review Dashboard</h1>

        <div class="summary">
            <p><strong>Jobs Prepared:</strong> {dashboard_data.get('jobs_prepared', 0)}</p>
            <p><strong>Total Validation Violations:</strong> {dashboard_data.get('total_violations', 0)}</p>
        </div>

        {jobs_html}

        <!-- Reject Modal -->
        <div id="rejectModal" class="modal">
            <div class="modal-content">
                <h2>Reject Application</h2>
                <p id="rejectJobTitle"></p>
                <textarea id="rejectReason" placeholder="Enter rejection reason..."></textarea>
                <div class="modal-buttons">
                    <button onclick="closeRejectModal()" class="btn btn-cancel">Cancel</button>
                    <button onclick="submitReject()" class="btn btn-reject">Reject</button>
                </div>
            </div>
        </div>

        <script>
            let currentJobId = '';

            async function approveJob(jobId) {{
                try {{
                    const response = await fetch('/approve', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ job_id: jobId }})
                    }});

                    if (response.ok) {{
                        alert('Job approved!');
                        location.reload();
                    }} else {{
                        alert('Failed to approve job');
                    }}
                }} catch (error) {{
                    alert('Error: ' + error.message);
                }}
            }}

            function showRejectModal(jobId, jobTitle) {{
                currentJobId = jobId;
                document.getElementById('rejectJobTitle').textContent = 'Job: ' + jobTitle;
                document.getElementById('rejectModal').style.display = 'block';
            }}

            function closeRejectModal() {{
                document.getElementById('rejectModal').style.display = 'none';
                document.getElementById('rejectReason').value = '';
                currentJobId = '';
            }}

            async function submitReject() {{
                const reason = document.getElementById('rejectReason').value.trim();
                if (!reason) {{
                    alert('Please enter a rejection reason');
                    return;
                }}

                try {{
                    const response = await fetch('/reject', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ job_id: currentJobId, reason: reason }})
                    }});

                    if (response.ok) {{
                        alert('Job rejected');
                        location.reload();
                    }} else {{
                        alert('Failed to reject job');
                    }}
                }} catch (error) {{
                    alert('Error: ' + error.message);
                }}
            }}

            // Close modal when clicking outside
            window.onclick = function(event) {{
                const modal = document.getElementById('rejectModal');
                if (event.target == modal) {{
                    closeRejectModal();
                }}
            }}
        </script>
    </body>
    </html>
    """

    return html


@app.post("/apply", response_model=ApplyResponse)
async def apply_to_job(request: ApplyRequest) -> ApplyResponse:
    """Apply to a job using API or browser automation.

    Args:
        request: Job ID to apply to

    Returns:
        ApplyResponse with status and evidence
    """
    from datetime import datetime

    job_id = request.job_id
    logger.info(f"Starting application for job {job_id}")

    # Load dashboard to get job details
    dashboard_data = _load_dashboard()
    job_data = None
    for job in dashboard_data.get("jobs", []):
        if job["job_id"] == job_id:
            job_data = job
            break

    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Check if job is approved
    if job_data.get("status") != ApplicationStatus.READY_TO_APPLY.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job must be approved before applying. Current status: {job_data.get('status')}",
        )

    # Load profile for application data
    profile = await _load_profile()

    # Extract application details
    contact = profile.get("contact", {})
    full_name = contact.get("name", "")
    email = contact.get("email", "")
    phone = contact.get("phone", "")

    # Get job folder for storing evidence
    jobsearch_home = _jobsearch_home()
    normalized_job_id = job_id.replace("_", "").replace(",", "").lower()
    job_folder = None

    for folder in (jobsearch_home / "jobs").iterdir():
        if folder.is_dir():
            normalized_folder = folder.name.replace("_", "").replace(",", "").lower()
            if normalized_job_id in normalized_folder:
                job_folder = folder
                break

    if not job_folder:
        raise HTTPException(status_code=404, detail=f"Job folder not found for {job_id}")

    # Determine source from job_id prefix
    source = "unknown"
    if job_id.startswith("gh_"):
        source = "greenhouse"
    elif job_id.startswith("lever_"):
        source = "lever"
    elif job_id.startswith("wd_"):
        source = "workday"

    apply_url = job_data.get("apply_url", "")
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")

    # Try API-based application first for supported sources
    if source in ["greenhouse", "lever"]:
        try:
            result = await _apply_via_api(
                source=source,
                apply_url=apply_url,
                job_id=job_id,
                full_name=full_name,
                email=email,
                phone=phone,
                job_folder=job_folder,
                job_data=job_data,
                timestamp=timestamp,
            )
            return result
        except Exception as exc:
            logger.warning(f"API application failed: {exc}. Falling back to browser automation.")

    # Fallback to browser automation
    try:
        result = await _apply_via_browser(
            apply_url=apply_url,
            job_id=job_id,
            full_name=full_name,
            email=email,
            phone=phone,
            job_folder=job_folder,
            job_data=job_data,
            timestamp=timestamp,
        )
        return result
    except Exception as exc:
        logger.error(f"Browser automation failed: {exc}")
        return ApplyResponse(
            job_id=job_id,
            status="FAILED",
            method="BROWSER",
            error_message=str(exc),
        )


async def _apply_via_api(
    source: str,
    apply_url: str,
    job_id: str,
    full_name: str,
    email: str,
    phone: str,
    job_folder: Path,
    job_data: dict,
    timestamp: str,
) -> ApplyResponse:
    """Apply via API for Greenhouse or Lever.

    Args:
        source: Source system (greenhouse or lever)
        apply_url: Application URL
        job_id: Job ID
        full_name: Applicant full name
        email: Applicant email
        phone: Applicant phone
        job_folder: Path to job folder
        job_data: Job data from dashboard
        timestamp: Timestamp for file naming

    Returns:
        ApplyResponse with results
    """
    logger.info(f"Attempting API application for {source}")

    # Extract job posting ID from URL or job_id
    if source == "greenhouse":
        # Greenhouse URLs: https://boards.greenhouse.io/company/jobs/12345
        # or job_id format: gh_company_12345
        posting_id = job_id.split("_")[-1] if "_" in job_id else apply_url.split("/")[-1]
    elif source == "lever":
        # Lever URLs: https://jobs.lever.co/company/job-slug
        # or job_id format: lever_company_uuid
        posting_id = job_id.split("_")[-1] if "_" in job_id else apply_url.split("/")[-1]
    else:
        raise ValueError(f"Unsupported source: {source}")

    # For now, API application is not fully implemented (requires API keys/tokens)
    # Raise exception to fall back to browser automation
    raise NotImplementedError(
        f"{source.title()} API application requires authentication tokens not yet configured"
    )


async def _apply_via_browser(
    apply_url: str,
    job_id: str,
    full_name: str,
    email: str,
    phone: str,
    job_folder: Path,
    job_data: dict,
    timestamp: str,
) -> ApplyResponse:
    """Apply via browser automation using Playwright.

    Args:
        apply_url: Application URL
        job_id: Job ID
        full_name: Applicant full name
        email: Applicant email
        phone: Applicant phone
        job_folder: Path to job folder
        job_data: Job data from dashboard
        timestamp: Timestamp for file naming

    Returns:
        ApplyResponse with results
    """
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    from playwright.async_api import async_playwright

    logger.info(f"Starting browser automation for {apply_url}")

    screenshots = []
    required_fields = []
    confirmation_id = ""
    evidence_data = {
        "job_id": job_id,
        "apply_url": apply_url,
        "timestamp": timestamp,
        "steps": [],
    }

    try:
        async with async_playwright() as p:
            # Launch browser
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            # Step 1: Navigate to application page
            logger.info(f"Navigating to {apply_url}")
            await page.goto(apply_url, wait_until="networkidle", timeout=30000)

            screenshot_path = job_folder / f"apply_step1_load_{timestamp}.png"
            await page.screenshot(path=screenshot_path)
            screenshots.append(str(screenshot_path))
            evidence_data["steps"].append({"step": 1, "action": "navigate", "url": apply_url})

            # Step 2: Detect CAPTCHA
            captcha_selectors = [
                "iframe[src*='recaptcha']",
                "iframe[src*='hcaptcha']",
                ".g-recaptcha",
                "#recaptcha",
                "[data-callback='captcha']",
            ]

            for selector in captcha_selectors:
                if await page.query_selector(selector):
                    logger.warning("CAPTCHA detected")
                    evidence_data["steps"].append({"step": 2, "action": "captcha_detected"})

                    screenshot_path = job_folder / f"apply_captcha_{timestamp}.png"
                    await page.screenshot(path=screenshot_path)
                    screenshots.append(str(screenshot_path))

                    await browser.close()
                    return ApplyResponse(
                        job_id=job_id,
                        status="NEEDS_INPUT",
                        method="BROWSER",
                        screenshots=screenshots,
                        required_fields=[
                            RequiredField(
                                selector=selector,
                                field_type="captcha",
                                label="CAPTCHA verification required",
                            )
                        ],
                        evidence_path=str(job_folder / f"evidence_{timestamp}.json"),
                    )

            # Step 3: Fill common form fields
            field_mappings = {
                "name": [
                    'input[name*="name"]',
                    'input[placeholder*="name"]',
                    'input[id*="name"]',
                    'input[type="text"][name*="first"]',
                ],
                "email": [
                    'input[type="email"]',
                    'input[name*="email"]',
                    'input[placeholder*="email"]',
                ],
                "phone": [
                    'input[type="tel"]',
                    'input[name*="phone"]',
                    'input[placeholder*="phone"]',
                ],
            }

            filled_fields = {}

            # Try to fill name
            for selector in field_mappings["name"]:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        await element.fill(full_name)
                        filled_fields["name"] = selector
                        logger.info(f"Filled name field: {selector}")
                        break
                except Exception as exc:
                    logger.debug(f"Could not fill {selector}: {exc}")

            # Try to fill email
            for selector in field_mappings["email"]:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        await element.fill(email)
                        filled_fields["email"] = selector
                        logger.info(f"Filled email field: {selector}")
                        break
                except Exception as exc:
                    logger.debug(f"Could not fill {selector}: {exc}")

            # Try to fill phone
            for selector in field_mappings["phone"]:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        await element.fill(phone)
                        filled_fields["phone"] = selector
                        logger.info(f"Filled phone field: {selector}")
                        break
                except Exception as exc:
                    logger.debug(f"Could not fill {selector}: {exc}")

            evidence_data["steps"].append({"step": 3, "action": "fill_fields", "fields": filled_fields})

            screenshot_path = job_folder / f"apply_step3_filled_{timestamp}.png"
            await page.screenshot(path=screenshot_path)
            screenshots.append(str(screenshot_path))

            # Step 4: Upload CV and cover letter
            cv_path = job_data.get("cv_pdf_path", "")
            cover_path = job_data.get("cover_letter_pdf_path", "")

            upload_selectors = [
                'input[type="file"][name*="resume"]',
                'input[type="file"][name*="cv"]',
                'input[type="file"]',
            ]

            if cv_path and Path(cv_path).exists():
                for selector in upload_selectors:
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            await element.set_input_files(cv_path)
                            logger.info(f"Uploaded CV to {selector}")
                            evidence_data["steps"].append(
                                {"step": 4, "action": "upload_cv", "selector": selector}
                            )
                            break
                    except Exception as exc:
                        logger.debug(f"Could not upload to {selector}: {exc}")

            screenshot_path = job_folder / f"apply_step4_uploaded_{timestamp}.png"
            await page.screenshot(path=screenshot_path)
            screenshots.append(str(screenshot_path))

            # Step 5: Look for unknown/required fields
            # Check for empty required fields
            required_inputs = await page.query_selector_all('input[required]:not([type="file"])')
            required_selects = await page.query_selector_all("select[required]")
            required_textareas = await page.query_selector_all("textarea[required]")

            all_required = required_inputs + required_selects + required_textareas

            for element in all_required:
                try:
                    value = await element.input_value() if hasattr(element, "input_value") else ""
                    if not value:
                        # Get field label
                        label_text = ""
                        try:
                            label_element = await page.query_selector(
                                f'label[for="{await element.get_attribute("id")}"]'
                            )
                            if label_element:
                                label_text = await label_element.inner_text()
                        except Exception:
                            pass

                        field_name = await element.get_attribute("name") or ""
                        field_type = await element.get_attribute("type") or "text"
                        tag_name = await element.evaluate("el => el.tagName.toLowerCase()")

                        if tag_name == "select":
                            field_type = "select"
                        elif tag_name == "textarea":
                            field_type = "textarea"

                        required_fields.append(
                            RequiredField(
                                selector=f'[name="{field_name}"]' if field_name else str(element),
                                field_type=field_type,
                                label=label_text or field_name,
                            )
                        )
                except Exception as exc:
                    logger.debug(f"Error checking required field: {exc}")

            if required_fields:
                logger.warning(f"Found {len(required_fields)} unfilled required fields")
                screenshot_path = job_folder / f"apply_needs_input_{timestamp}.png"
                await page.screenshot(path=screenshot_path)
                screenshots.append(str(screenshot_path))

                evidence_path = job_folder / f"evidence_{timestamp}.json"
                evidence_path.write_text(json.dumps(evidence_data, indent=2))

                await browser.close()
                return ApplyResponse(
                    job_id=job_id,
                    status="NEEDS_INPUT",
                    method="BROWSER",
                    screenshots=screenshots,
                    required_fields=required_fields,
                    evidence_path=str(evidence_path),
                )

            # Step 6: Submit the form
            submit_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Submit")',
                'button:has-text("Apply")',
                'button:has-text("Send")',
            ]

            submitted = False
            for selector in submit_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element and await element.is_visible():
                        await element.click()
                        submitted = True
                        logger.info(f"Clicked submit button: {selector}")
                        evidence_data["steps"].append({"step": 6, "action": "submit", "selector": selector})
                        break
                except Exception as exc:
                    logger.debug(f"Could not click {selector}: {exc}")

            if not submitted:
                raise RuntimeError("Could not find submit button")

            # Wait for navigation or confirmation
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeout:
                logger.warning("Timeout waiting for page load after submit")

            screenshot_path = job_folder / f"apply_step6_submitted_{timestamp}.png"
            await page.screenshot(path=screenshot_path)
            screenshots.append(str(screenshot_path))

            # Try to extract confirmation ID
            confirmation_selectors = [
                '[class*="confirmation"]',
                '[id*="confirmation"]',
                '[class*="success"]',
                'h1',
                'h2',
            ]

            for selector in confirmation_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.inner_text()
                        if any(
                            keyword in text.lower()
                            for keyword in ["confirmation", "success", "submitted", "received"]
                        ):
                            confirmation_id = text[:100]  # Limit length
                            break
                except Exception:
                    pass

            evidence_data["confirmation_id"] = confirmation_id
            evidence_data["success"] = True

            evidence_path = job_folder / f"evidence_{timestamp}.json"
            evidence_path.write_text(json.dumps(evidence_data, indent=2))

            await browser.close()

            return ApplyResponse(
                job_id=job_id,
                status="SUCCESS",
                method="BROWSER",
                confirmation_id=confirmation_id,
                evidence_path=str(evidence_path),
                screenshots=screenshots,
            )

    except Exception as exc:
        logger.error(f"Browser automation error: {exc}")
        raise


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9004)
