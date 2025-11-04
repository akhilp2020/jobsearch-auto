from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    """Search filters for job postings."""

    titles: list[str] = Field(default_factory=list, description="Job titles to search for")
    locations: list[str] = Field(default_factory=list, description="Locations to search in")
    remote: bool | None = Field(default=None, description="Filter for remote positions")
    salary_min: int | None = Field(default=None, description="Minimum salary in USD")


class JobPosting(BaseModel):
    """Normalized job posting."""

    id: str = Field(..., description="Unique job ID")
    title: str = Field(..., description="Job title")
    company: str = Field(..., description="Company name")
    location: str = Field(..., description="Job location")
    jd_text: str = Field(..., description="Job description text")
    requirements: str = Field(default="", description="Job requirements")
    source: str = Field(..., description="Source system (greenhouse, lever, etc)")
    apply_url: str = Field(..., description="URL to apply for the job")
    raw_data: dict[str, Any] = Field(default_factory=dict, description="Raw job data from source")


class SearchResponse(BaseModel):
    """Response containing job search results."""

    postings: list[JobPosting]
    total_found: int
    saved_count: int = 0
