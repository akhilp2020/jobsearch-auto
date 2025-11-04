from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TailorRequest(BaseModel):
    """Request to tailor a CV for a specific job."""

    job_id: str = Field(..., description="Job ID to tailor CV for")


class CVDiffSummary(BaseModel):
    """Summary of changes between base CV and tailored CV."""

    added_bullets: list[str] = Field(default_factory=list, description="Bullets added in tailored CV")
    removed_bullets: list[str] = Field(default_factory=list, description="Bullets removed from base CV")
    added_sections: list[str] = Field(default_factory=list, description="Sections added")
    modified_sections: list[str] = Field(default_factory=list, description="Sections modified")


class TailorResponse(BaseModel):
    """Response with tailored CV."""

    job_id: str = Field(..., description="Job ID")
    cv_markdown: str = Field(..., description="Tailored CV in Markdown format")
    cv_html: str = Field(..., description="Tailored CV in HTML format")
    pdf_path: str = Field(..., description="Path to generated PDF")
    diff_summary: CVDiffSummary = Field(..., description="Summary of changes from base CV")


class ValidationViolation(BaseModel):
    """Validation violation."""

    artifact: str = Field(..., description="Artifact path with violation")
    line: int | None = Field(None, description="Line number of violation")
    reason: str = Field(..., description="Reason for violation")


class ValidateRequest(BaseModel):
    """Request to validate artifacts."""

    artifact_paths: list[str] = Field(..., description="Paths to artifacts to validate (relative to JOBSEARCH_HOME)")
    fail_on_violations: bool = Field(default=True, description="Whether to fail if violations present")


class ValidateResponse(BaseModel):
    """Response from validation."""

    passed: bool = Field(..., description="Whether validation passed")
    violations: list[ValidationViolation] = Field(default_factory=list, description="List of violations")
    suggestions: list[str] = Field(default_factory=list, description="Suggestions for improvement")
