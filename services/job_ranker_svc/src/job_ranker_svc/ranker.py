from __future__ import annotations

import json
import logging
import math
import os
import re
from typing import Any

import httpx

from .models import FitScore, JobPosting, Profile

logger = logging.getLogger(__name__)


class JobRanker:
    """Ranks jobs based on profile fit using LLM analysis."""

    def __init__(self) -> None:
        self.llm_provider = os.getenv("LLM_PROVIDER", "openai")
        self.llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")

    def rank_jobs(self, profile: Profile, jobs: list[JobPosting]) -> list[tuple[JobPosting, FitScore]]:
        """Rank jobs by fit score.

        Returns:
            List of (job, fit_score) tuples sorted by score descending
        """
        scored_jobs: list[tuple[JobPosting, FitScore]] = []

        for job in jobs:
            try:
                fit_score = self._score_job(profile, job)
                scored_jobs.append((job, fit_score))
            except Exception as exc:
                logger.error(f"Failed to score job {job.id}: {exc}")
                # Add default low score for failed jobs
                fit_score = FitScore(
                    job_id=job.id,
                    score=0,
                    matched_skills=[],
                    gaps=["Error analyzing fit"],
                    seniority_match="Unknown",
                    explanation="Failed to analyze this job",
                )
                scored_jobs.append((job, fit_score))

        # Sort by score descending
        scored_jobs.sort(key=lambda x: x[1].score, reverse=True)
        return scored_jobs

    def _score_job(self, profile: Profile, job: JobPosting) -> FitScore:
        """Score a single job against the profile using LLM."""
        # Use LLM to analyze fit
        fit_analysis = self._llm_analyze_fit(profile, job)

        # Parse LLM response
        return self._parse_fit_analysis(job.id, fit_analysis)

    def _llm_analyze_fit(self, profile: Profile, job: JobPosting) -> str:
        """Use LLM to analyze job fit."""
        prompt = self._build_analysis_prompt(profile, job)

        try:
            if self.llm_provider.lower() == "openai":
                return self._call_openai(prompt)
            else:
                logger.warning(f"Unsupported LLM provider: {self.llm_provider}, using basic scoring")
                return self._basic_scoring(profile, job)
        except Exception as exc:
            logger.error(f"LLM API call failed: {exc}")
            return self._basic_scoring(profile, job)

    def _build_analysis_prompt(self, profile: Profile, job: JobPosting) -> str:
        """Build prompt for LLM analysis."""
        # Extract key profile info
        skills = ", ".join(profile.skills[:10])  # Top 10 skills
        target_titles = profile.preferences.get("target_titles", [])
        seniority = profile.preferences.get("seniority", "")
        location_pref = profile.preferences.get("location", "")
        remote_pref = profile.preferences.get("remote", "")

        # Build job summary
        jd_excerpt = job.jd_text[:1000] if len(job.jd_text) > 1000 else job.jd_text

        prompt = f"""Analyze the fit between this candidate profile and job posting.

CANDIDATE PROFILE:
- Skills: {skills}
- Target Titles: {", ".join(target_titles) if target_titles else "Not specified"}
- Seniority: {seniority}
- Location Preference: {location_pref}
- Remote Preference: {remote_pref}

JOB POSTING:
- Title: {job.title}
- Company: {job.company}
- Location: {job.location}
- Description: {jd_excerpt}

Provide analysis in JSON format:
{{
  "score": <0-100>,
  "matched_skills": ["skill1", "skill2", ...],
  "gaps": ["gap1", "gap2", ...],
  "seniority_match": "Excellent|Good|Fair|Poor",
  "explanation": "Brief explanation of the fit"
}}

Focus on:
1. Skills alignment (technical and domain)
2. Seniority/level match
3. Location and remote work compatibility
4. Job title alignment with career goals

Return ONLY valid JSON."""

        return prompt

    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API."""
        headers = {
            "Authorization": f"Bearer {self.llm_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def _basic_scoring(self, profile: Profile, job: JobPosting) -> str:
        """Fallback basic scoring without LLM."""
        # Simple keyword matching
        profile_skills_lower = [s.lower() for s in profile.skills]
        job_text_lower = job.jd_text.lower() + " " + job.title.lower()

        matched_skills = [s for s in profile.skills if s.lower() in job_text_lower]
        gaps = [s for s in profile.skills[:5] if s.lower() not in job_text_lower]

        # Simple scoring based on matched skills
        score = min(100, len(matched_skills) * 10 + 40)

        # Check title match
        target_titles = profile.preferences.get("target_titles", [])
        title_match = any(t.lower() in job.title.lower() for t in target_titles)
        if title_match:
            score += 10

        # Location check
        location_pref = profile.preferences.get("location", "")
        if location_pref and location_pref.lower() in job.location.lower():
            score += 5

        score = min(100, score)

        result = {
            "score": score,
            "matched_skills": matched_skills[:10],
            "gaps": gaps[:5],
            "seniority_match": "Unknown",
            "explanation": f"Basic analysis: {len(matched_skills)} skills matched",
        }

        return json.dumps(result)

    def _parse_fit_analysis(self, job_id: str, analysis_json: str) -> FitScore:
        """Parse LLM JSON response into FitScore."""
        try:
            data = json.loads(analysis_json)

            return FitScore(
                job_id=job_id,
                score=int(data.get("score", 0)),
                matched_skills=data.get("matched_skills", [])[:10],  # Limit to 10
                gaps=data.get("gaps", [])[:10],  # Limit to 10
                seniority_match=data.get("seniority_match", "Unknown"),
                explanation=data.get("explanation", "No explanation provided"),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error(f"Failed to parse fit analysis: {exc}")
            return FitScore(
                job_id=job_id,
                score=0,
                matched_skills=[],
                gaps=["Failed to parse analysis"],
                seniority_match="Unknown",
                explanation="Error parsing LLM response",
            )
