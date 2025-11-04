from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CoverLetterRequest(BaseModel):
    """Request to generate a cover letter."""

    job_id: str = Field(..., description="Job ID to generate cover letter for")
    tone: str = Field(
        default="concise, impact-focused",
        description="Tone for the cover letter (e.g., 'concise, impact-focused', 'enthusiastic', 'professional')",
    )


class SupplementalQuestion(BaseModel):
    """A supplemental question to answer."""

    question: str = Field(..., description="The question text")
    max_words: int | None = Field(default=None, description="Maximum word count for answer")


class SupplementalRequest(BaseModel):
    """Request to generate supplemental documents."""

    job_id: str = Field(..., description="Job ID to generate supplemental documents for")
    questions: list[SupplementalQuestion] = Field(
        ..., description="List of questions to answer"
    )


class CoverLetterResponse(BaseModel):
    """Response with generated cover letter."""

    job_id: str = Field(..., description="Job ID")
    cover_letter_markdown: str = Field(..., description="Cover letter in Markdown format")
    cover_letter_html: str = Field(..., description="Cover letter in HTML format")
    pdf_path: str = Field(..., description="Path to generated PDF")
    tone: str = Field(..., description="Tone used for the cover letter")


class SupplementalResponse(BaseModel):
    """Response with generated supplemental documents."""

    job_id: str = Field(..., description="Job ID")
    supplemental_markdown: str = Field(..., description="Supplemental answers in Markdown format")
    supplemental_html: str = Field(..., description="Supplemental answers in HTML format")
    pdf_path: str = Field(..., description="Path to generated PDF")
    markdown_path: str = Field(..., description="Path to Markdown file")


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
