from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ApplicationStatus(str, Enum):
    """Application status for a job."""

    PENDING_REVIEW = "PENDING_REVIEW"
    READY_TO_APPLY = "READY_TO_APPLY"
    REJECTED = "REJECTED"


class PrepareRequest(BaseModel):
    """Request to prepare job application materials."""

    titles: list[str] = Field(..., description="Job titles to search for")
    locations: list[str] = Field(..., description="Locations to search in")
    remote: bool | None = Field(default=None, description="Filter for remote positions")
    salary_min: int | None = Field(default=None, description="Minimum salary in USD")
    top_n: int = Field(default=5, description="Number of top jobs to prepare materials for", ge=1, le=20)
    generate_cover_letter: bool = Field(default=True, description="Generate cover letters")
    cover_letter_tone: str = Field(
        default="concise, impact-focused",
        description="Tone for cover letters",
    )
    generate_supplementals: bool = Field(default=False, description="Generate supplemental answers")
    supplemental_questions: list[dict] = Field(
        default_factory=list,
        description="List of supplemental questions with 'question' and optional 'max_words'",
    )


class JobPreparation(BaseModel):
    """Preparation status for a single job."""

    job_id: str = Field(..., description="Job ID")
    job_title: str = Field(..., description="Job title")
    company: str = Field(..., description="Company name")
    location: str = Field(..., description="Job location")
    apply_url: str = Field(..., description="URL to apply for the job")
    fit_score: int = Field(..., description="Fit score 0-100", ge=0, le=100)
    cv_path: str = Field(default="", description="Path to tailored CV")
    cv_html_path: str = Field(default="", description="Path to CV HTML")
    cv_pdf_path: str = Field(default="", description="Path to CV PDF")
    cover_letter_path: str = Field(default="", description="Path to cover letter markdown")
    cover_letter_html_path: str = Field(default="", description="Path to cover letter HTML")
    cover_letter_pdf_path: str = Field(default="", description="Path to cover letter PDF")
    supplemental_path: str = Field(default="", description="Path to supplemental markdown")
    supplemental_html_path: str = Field(default="", description="Path to supplemental HTML")
    supplemental_pdf_path: str = Field(default="", description="Path to supplemental PDF")
    validation_passed: bool = Field(default=False, description="Whether validation passed")
    validation_violations: int = Field(default=0, description="Number of validation violations")
    status: ApplicationStatus = Field(
        default=ApplicationStatus.PENDING_REVIEW, description="Application status"
    )
    rejection_reason: str = Field(default="", description="Reason for rejection if status is REJECTED")


class PrepareResponse(BaseModel):
    """Response with preparation results."""

    dashboard_path: str = Field(..., description="Path to review dashboard JSON")
    jobs_prepared: int = Field(..., description="Number of jobs prepared")
    jobs: list[JobPreparation] = Field(..., description="List of prepared jobs with details")
    total_violations: int = Field(default=0, description="Total validation violations across all jobs")


class ApproveRequest(BaseModel):
    """Request to approve a job application."""

    job_id: str = Field(..., description="Job ID to approve")


class RejectRequest(BaseModel):
    """Request to reject a job application."""

    job_id: str = Field(..., description="Job ID to reject")
    reason: str = Field(..., description="Reason for rejection")


class ReviewResponse(BaseModel):
    """Response containing review dashboard data."""

    jobs_prepared: int = Field(..., description="Number of jobs prepared")
    total_violations: int = Field(default=0, description="Total validation violations")
    jobs: list[JobPreparation] = Field(..., description="List of jobs with status")


class ApplyRequest(BaseModel):
    """Request to apply to a job."""

    job_id: str = Field(..., description="Job ID to apply to")


class RequiredField(BaseModel):
    """Field that requires user input."""

    selector: str = Field(..., description="CSS selector for the field")
    field_type: str = Field(..., description="Type of field (text, select, file, etc)")
    label: str = Field(default="", description="Field label if available")
    suggested_value: str = Field(default="", description="Suggested value if inferable")


class ApplyResponse(BaseModel):
    """Response from job application."""

    job_id: str = Field(..., description="Job ID")
    status: str = Field(
        ...,
        description="Application status: SUCCESS, NEEDS_INPUT, FAILED",
    )
    method: str = Field(default="", description="Application method used: API or BROWSER")
    confirmation_id: str = Field(default="", description="Confirmation ID if successful")
    evidence_path: str = Field(default="", description="Path to evidence.json")
    screenshots: list[str] = Field(default_factory=list, description="Paths to screenshots")
    required_fields: list[RequiredField] = Field(
        default_factory=list, description="Fields requiring input (if NEEDS_INPUT)"
    )
    error_message: str = Field(default="", description="Error message if failed")
