from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Profile(BaseModel):
    """User profile for job matching."""

    contact: dict[str, str] = Field(default_factory=dict)
    roles: list[dict[str, str]] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)


class JobPosting(BaseModel):
    """Job posting to be ranked."""

    id: str = Field(..., description="Unique job ID")
    title: str = Field(..., description="Job title")
    company: str = Field(..., description="Company name")
    location: str = Field(..., description="Job location")
    jd_text: str = Field(..., description="Job description text")
    requirements: str = Field(default="", description="Job requirements")
    source: str = Field(..., description="Source system")
    apply_url: str = Field(..., description="URL to apply")
    raw_data: dict[str, Any] = Field(default_factory=dict)


class FitScore(BaseModel):
    """Job fit score with detailed analysis."""

    job_id: str = Field(..., description="Job ID")
    score: int = Field(..., description="Overall fit score 0-100", ge=0, le=100)
    matched_skills: list[str] = Field(default_factory=list, description="Skills that match")
    gaps: list[str] = Field(default_factory=list, description="Missing skills or requirements")
    seniority_match: str = Field(..., description="How well seniority matches")
    explanation: str = Field(..., description="Detailed explanation of the fit")


class RankedJob(BaseModel):
    """Job posting with fit score."""

    job: JobPosting
    fit_score: FitScore


class RankRequest(BaseModel):
    """Request to rank jobs."""

    profile: Profile
    jobs: list[JobPosting]


class RankResponse(BaseModel):
    """Response with ranked jobs."""

    ranked_jobs: list[RankedJob]
    total_jobs: int
    saved_reports: int = 0
