from __future__ import annotations

import difflib
import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from .models import CVDiffSummary

logger = logging.getLogger(__name__)


class CVTailor:
    """Tailors CVs based on job requirements using LLM."""

    def __init__(self) -> None:
        self.llm_provider = os.getenv("LLM_PROVIDER", "openai")
        self.llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")

    def tailor_cv(
        self, profile: dict[str, Any], job: dict[str, Any], base_cv_md: str
    ) -> tuple[str, str, CVDiffSummary]:
        """Generate tailored CV in Markdown and HTML with evidence tracking.

        Args:
            profile: Canonical profile data
            job: Job posting data
            base_cv_md: Base CV in Markdown

        Returns:
            Tuple of (cv_markdown, cv_html, diff_summary)
        """
        # Generate tailored CV using LLM
        tailored_md = self._generate_tailored_cv(profile, job)

        # Convert to HTML with evidence comments
        tailored_html = self._markdown_to_html_with_evidence(tailored_md, profile)

        # Generate diff summary
        diff_summary = self._generate_diff_summary(base_cv_md, tailored_md)

        return tailored_md, tailored_html, diff_summary

    def _generate_tailored_cv(self, profile: dict[str, Any], job: dict[str, Any]) -> str:
        """Use LLM to generate tailored CV content."""
        prompt = self._build_cv_prompt(profile, job)

        try:
            if self.llm_provider.lower() == "openai":
                return self._call_openai(prompt)
            else:
                logger.warning(f"Unsupported LLM provider: {self.llm_provider}, using basic template")
                return self._basic_template(profile, job)
        except Exception as exc:
            logger.error(f"LLM API call failed: {exc}")
            return self._basic_template(profile, job)

    def _build_cv_prompt(self, profile: dict[str, Any], job: dict[str, Any]) -> str:
        """Build LLM prompt for CV tailoring."""
        # Extract job info
        job_title = job.get("title", "")
        company = job.get("company", "")
        jd_text = job.get("jd_text", "")[:2000]  # Limit to 2000 chars

        # Extract profile info
        contact = profile.get("contact", {})
        skills = profile.get("skills", [])
        roles = profile.get("roles", [])
        education = profile.get("education", [])
        achievements = profile.get("achievements", [])

        prompt = f"""Create a tailored 1-2 page CV in Markdown format for this job application.

JOB POSTING:
Title: {job_title}
Company: {company}
Description: {jd_text}

CANDIDATE PROFILE:
Name: {contact.get('name', 'Candidate')}
Email: {contact.get('email', '')}
Phone: {contact.get('phone', '')}

Skills: {', '.join(skills[:10])}

Work Experience:
{self._format_roles_for_prompt(roles[:4])}

Education:
{chr(10).join(education[:3])}

Achievements:
{chr(10).join(achievements[:5])}

REQUIREMENTS:
1. Create a professional CV in Markdown format
2. Emphasize skills and experience relevant to the job
3. Use ONLY facts from the profile - DO NOT invent experience
4. Include contact info, work experience, education, and skills
5. Keep it 1-2 pages (approximately 40-60 lines)
6. Use clear section headers (##)
7. Use bullet points (-) for achievements and responsibilities

Return ONLY the Markdown CV, no other text."""

        return prompt

    def _format_roles_for_prompt(self, roles: list[dict[str, Any]]) -> str:
        """Format roles for LLM prompt."""
        lines = []
        for role in roles:
            title = role.get("title", "")
            company = role.get("company", "")
            start = role.get("start", "")
            end = role.get("end", "")
            lines.append(f"- {title} at {company} ({start} - {end})")
        return "\n".join(lines)

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
        }

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    def _basic_template(self, profile: dict[str, Any], job: dict[str, Any]) -> str:
        """Fallback basic CV template."""
        contact = profile.get("contact", {})
        name = contact.get("name", "Candidate")
        email = contact.get("email", "")
        phone = contact.get("phone", "")

        # Build CV sections
        sections = []

        # Header
        sections.append(f"# {name}\n")
        sections.append(f"Email: {email} | Phone: {phone}\n")

        # Professional Experience
        sections.append("## Professional Experience\n")
        for role in profile.get("roles", [])[:4]:
            title = role.get("title", "")
            company = role.get("company", "")
            start = role.get("start", "")
            end = role.get("end", "")
            sections.append(f"### {title}")
            sections.append(f"**{company}** | {start} - {end}\n")

        # Education
        education = profile.get("education", [])
        if education:
            sections.append("## Education\n")
            for edu in education[:3]:
                sections.append(f"- {edu}")
            sections.append("")

        # Skills
        skills = profile.get("skills", [])
        if skills:
            sections.append("## Technical Skills\n")
            for skill in skills[:10]:
                sections.append(f"- {skill}")

        return "\n".join(sections)

    def _markdown_to_html_with_evidence(self, markdown: str, profile: dict[str, Any]) -> str:
        """Convert Markdown to HTML and add evidence comments."""
        # Simple Markdown to HTML conversion
        html_lines = []
        html_lines.append("<!DOCTYPE html>")
        html_lines.append("<html>")
        html_lines.append("<head>")
        html_lines.append("<meta charset='UTF-8'>")
        html_lines.append("<style>")
        html_lines.append("body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; line-height: 1.6; }")
        html_lines.append("h1 { border-bottom: 2px solid #333; padding-bottom: 10px; }")
        html_lines.append("h2 { color: #2c3e50; margin-top: 30px; border-bottom: 1px solid #ccc; padding-bottom: 5px; }")
        html_lines.append("h3 { color: #34495e; margin-top: 20px; margin-bottom: 5px; }")
        html_lines.append("ul { list-style-type: disc; margin-left: 20px; }")
        html_lines.append("</style>")
        html_lines.append("</head>")
        html_lines.append("<body>")

        for line in markdown.split("\n"):
            line = line.strip()
            if not line:
                html_lines.append("<br>")
                continue

            # Add evidence comments for bullets
            evidence_comment = self._find_evidence(line, profile)

            if line.startswith("# "):
                html_lines.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("## "):
                html_lines.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("### "):
                html_lines.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith("- "):
                if evidence_comment:
                    html_lines.append(f"<!-- evidence:{evidence_comment} -->")
                html_lines.append(f"<li>{line[2:]}</li>")
            elif line.startswith("**") and line.endswith("**"):
                html_lines.append(f"<strong>{line[2:-2]}</strong>")
            else:
                if evidence_comment and any(keyword in line.lower() for keyword in ["led", "achieved", "reduced", "enabled", "implemented"]):
                    html_lines.append(f"<!-- evidence:{evidence_comment} -->")
                html_lines.append(f"<p>{line}</p>")

        html_lines.append("</body>")
        html_lines.append("</html>")

        return "\n".join(html_lines)

    def _find_evidence(self, line: str, profile: dict[str, Any]) -> str:
        """Find evidence path in profile for a CV line."""
        line_lower = line.lower()

        # Check achievements
        achievements = profile.get("achievements", [])
        for idx, achievement in enumerate(achievements):
            if achievement.lower() in line_lower or line_lower in achievement.lower():
                return f"achievements[{idx}]"

        # Check skills
        skills = profile.get("skills", [])
        for idx, skill in enumerate(skills):
            if skill.lower() in line_lower:
                return f"skills[{idx}]"

        # Check roles
        roles = profile.get("roles", [])
        for idx, role in enumerate(roles):
            role_title = role.get("title", "").lower()
            role_company = role.get("company", "").lower()
            if role_title in line_lower or role_company in line_lower:
                return f"roles[{idx}]"

        # Check education
        education = profile.get("education", [])
        for idx, edu in enumerate(education):
            if edu.lower() in line_lower or any(word in line_lower for word in edu.lower().split()[:3]):
                return f"education[{idx}]"

        return ""

    def _generate_diff_summary(self, base_cv: str, tailored_cv: str) -> CVDiffSummary:
        """Generate diff summary between base and tailored CV."""
        base_lines = [line.strip() for line in base_cv.split("\n") if line.strip().startswith("-")]
        tailored_lines = [line.strip() for line in tailored_cv.split("\n") if line.strip().startswith("-")]

        # Find added and removed bullets
        base_set = set(base_lines)
        tailored_set = set(tailored_lines)

        added_bullets = list(tailored_set - base_set)
        removed_bullets = list(base_set - tailored_set)

        # Find section changes
        base_sections = [line.strip() for line in base_cv.split("\n") if line.strip().startswith("##")]
        tailored_sections = [line.strip() for line in tailored_cv.split("\n") if line.strip().startswith("##")]

        added_sections = [s for s in tailored_sections if s not in base_sections]
        modified_sections = []

        # Check for modified sections (same header, different content)
        for section in base_sections:
            if section in tailored_sections:
                # Section exists in both - might be modified
                if self._section_content_differs(section, base_cv, tailored_cv):
                    modified_sections.append(section)

        return CVDiffSummary(
            added_bullets=added_bullets[:10],  # Limit to 10
            removed_bullets=removed_bullets[:10],
            added_sections=added_sections,
            modified_sections=modified_sections,
        )

    def _section_content_differs(self, section_header: str, base_cv: str, tailored_cv: str) -> bool:
        """Check if section content differs between base and tailored CV."""
        # Simple heuristic: extract content between this section and next
        base_content = self._extract_section_content(section_header, base_cv)
        tailored_content = self._extract_section_content(section_header, tailored_cv)
        return base_content != tailored_content

    def _extract_section_content(self, section_header: str, cv_text: str) -> str:
        """Extract content of a section."""
        lines = cv_text.split("\n")
        content_lines = []
        in_section = False

        for line in lines:
            if line.strip() == section_header:
                in_section = True
                continue
            if in_section:
                if line.strip().startswith("##"):
                    # Next section started
                    break
                content_lines.append(line)

        return "\n".join(content_lines).strip()
