from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DocumentBuilder:
    """Base class for building documents using LLM."""

    def __init__(self) -> None:
        self.llm_provider = os.getenv("LLM_PROVIDER", "openai")
        self.llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")

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

    def _markdown_to_html_with_evidence(self, markdown: str, profile: dict[str, Any]) -> str:
        """Convert Markdown to HTML and add evidence comments."""
        html_lines = []
        html_lines.append("<!DOCTYPE html>")
        html_lines.append("<html>")
        html_lines.append("<head>")
        html_lines.append("<meta charset='UTF-8'>")
        html_lines.append("<style>")
        html_lines.append(
            "body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; line-height: 1.6; }"
        )
        html_lines.append("h1 { border-bottom: 2px solid #333; padding-bottom: 10px; }")
        html_lines.append(
            "h2 { color: #2c3e50; margin-top: 30px; border-bottom: 1px solid #ccc; padding-bottom: 5px; }"
        )
        html_lines.append("h3 { color: #34495e; margin-top: 20px; margin-bottom: 5px; }")
        html_lines.append("ul { list-style-type: disc; margin-left: 20px; }")
        html_lines.append("p { margin: 10px 0; }")
        html_lines.append("</style>")
        html_lines.append("</head>")
        html_lines.append("<body>")

        for line in markdown.split("\n"):
            line = line.strip()
            if not line:
                html_lines.append("<br>")
                continue

            # Add evidence comments for bullets and paragraphs
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
                # Add evidence for substantive paragraphs
                if evidence_comment and any(
                    keyword in line.lower()
                    for keyword in [
                        "led",
                        "achieved",
                        "reduced",
                        "enabled",
                        "implemented",
                        "developed",
                        "created",
                        "managed",
                        "experience",
                        "skill",
                    ]
                ):
                    html_lines.append(f"<!-- evidence:{evidence_comment} -->")
                html_lines.append(f"<p>{line}</p>")

        html_lines.append("</body>")
        html_lines.append("</html>")

        return "\n".join(html_lines)

    def _find_evidence(self, line: str, profile: dict[str, Any]) -> str:
        """Find evidence path in profile for a document line."""
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
            role_description = role.get("description", "").lower() if isinstance(role.get("description"), str) else ""

            if role_title in line_lower or role_company in line_lower:
                return f"roles[{idx}]"

            # Check if any significant words from the line appear in role description
            if role_description and len(line_lower.split()) > 5:
                significant_words = [w for w in line_lower.split() if len(w) > 4]
                matches = sum(1 for w in significant_words if w in role_description)
                if matches >= 2:
                    return f"roles[{idx}]"

        # Check education
        education = profile.get("education", [])
        for idx, edu in enumerate(education):
            if edu.lower() in line_lower or any(
                word in line_lower for word in edu.lower().split()[:3]
            ):
                return f"education[{idx}]"

        return ""


class CoverLetterBuilder(DocumentBuilder):
    """Builds cover letters based on job requirements."""

    def generate_cover_letter(
        self, profile: dict[str, Any], job: dict[str, Any], tone: str = "concise, impact-focused"
    ) -> tuple[str, str]:
        """Generate cover letter in Markdown and HTML.

        Args:
            profile: Canonical profile data
            job: Job posting data
            tone: Tone for the cover letter

        Returns:
            Tuple of (cover_letter_markdown, cover_letter_html)
        """
        prompt = self._build_cover_letter_prompt(profile, job, tone)

        try:
            if self.llm_provider.lower() == "openai":
                cover_letter_md = self._call_openai(prompt)
            else:
                logger.warning(
                    f"Unsupported LLM provider: {self.llm_provider}, using basic template"
                )
                cover_letter_md = self._basic_cover_letter_template(profile, job)
        except Exception as exc:
            logger.error(f"LLM API call failed: {exc}")
            cover_letter_md = self._basic_cover_letter_template(profile, job)

        # Convert to HTML with evidence
        cover_letter_html = self._markdown_to_html_with_evidence(cover_letter_md, profile)

        return cover_letter_md, cover_letter_html

    def _build_cover_letter_prompt(
        self, profile: dict[str, Any], job: dict[str, Any], tone: str
    ) -> str:
        """Build LLM prompt for cover letter generation."""
        job_title = job.get("title", "")
        company = job.get("company", "")
        jd_text = job.get("jd_text", "")[:2000]

        contact = profile.get("contact", {})
        skills = profile.get("skills", [])
        roles = profile.get("roles", [])
        achievements = profile.get("achievements", [])

        prompt = f"""Create a compelling cover letter in Markdown format for this job application.

JOB POSTING:
Title: {job_title}
Company: {company}
Description: {jd_text}

CANDIDATE PROFILE:
Name: {contact.get('name', 'Candidate')}
Email: {contact.get('email', '')}
Phone: {contact.get('phone', '')}

Top Skills: {', '.join(skills[:10])}

Recent Work Experience:
{self._format_roles_for_prompt(roles[:3])}

Key Achievements:
{chr(10).join(achievements[:5])}

REQUIREMENTS:
1. Create a professional cover letter in Markdown format
2. Tone: {tone}
3. Highlight relevant skills and experience for THIS specific job
4. Use ONLY facts from the profile - DO NOT invent experience
5. Keep it concise (3-4 paragraphs, approximately 250-300 words)
6. Structure:
   - Opening paragraph: Express interest and mention the role
   - Middle paragraphs: Highlight 2-3 most relevant experiences/achievements
   - Closing paragraph: Express enthusiasm and next steps
7. Use specific examples and quantifiable achievements when possible
8. Match the tone requested: {tone}

Return ONLY the Markdown cover letter, no other text."""

        return prompt

    def _format_roles_for_prompt(self, roles: list[dict[str, Any]]) -> str:
        """Format roles for LLM prompt."""
        lines = []
        for role in roles:
            title = role.get("title", "")
            company = role.get("company", "")
            start = role.get("start", "")
            end = role.get("end", "")
            description = role.get("description", "")
            if isinstance(description, list):
                description = " ".join(description[:2])
            lines.append(f"- {title} at {company} ({start} - {end})")
            if description:
                lines.append(f"  {description[:200]}")
        return "\n".join(lines)

    def _basic_cover_letter_template(self, profile: dict[str, Any], job: dict[str, Any]) -> str:
        """Fallback basic cover letter template."""
        contact = profile.get("contact", {})
        name = contact.get("name", "Candidate")

        job_title = job.get("title", "the position")
        company = job.get("company", "your company")

        return f"""Dear Hiring Manager,

I am writing to express my strong interest in the {job_title} position at {company}.

With my background in {', '.join(profile.get('skills', [])[:3])}, I am confident in my ability to contribute to your team. In my recent roles, I have successfully delivered results and driven impact.

I would welcome the opportunity to discuss how my experience aligns with your needs.

Best regards,
{name}"""


class SupplementalBuilder(DocumentBuilder):
    """Builds supplemental documents answering specific questions."""

    def generate_supplemental(
        self,
        profile: dict[str, Any],
        job: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """Generate supplemental answers in Markdown and HTML.

        Args:
            profile: Canonical profile data
            job: Job posting data
            questions: List of questions to answer

        Returns:
            Tuple of (supplemental_markdown, supplemental_html)
        """
        prompt = self._build_supplemental_prompt(profile, job, questions)

        try:
            if self.llm_provider.lower() == "openai":
                supplemental_md = self._call_openai(prompt)
            else:
                logger.warning(
                    f"Unsupported LLM provider: {self.llm_provider}, using basic template"
                )
                supplemental_md = self._basic_supplemental_template(profile, job, questions)
        except Exception as exc:
            logger.error(f"LLM API call failed: {exc}")
            supplemental_md = self._basic_supplemental_template(profile, job, questions)

        # Convert to HTML with evidence
        supplemental_html = self._markdown_to_html_with_evidence(supplemental_md, profile)

        return supplemental_md, supplemental_html

    def _build_supplemental_prompt(
        self, profile: dict[str, Any], job: dict[str, Any], questions: list[dict[str, Any]]
    ) -> str:
        """Build LLM prompt for supplemental document generation."""
        job_title = job.get("title", "")
        company = job.get("company", "")

        contact = profile.get("contact", {})
        skills = profile.get("skills", [])
        roles = profile.get("roles", [])
        achievements = profile.get("achievements", [])

        questions_text = "\n".join(
            [
                f"{i+1}. {q.get('question', '')} "
                + (f"(Max {q.get('max_words', 'N/A')} words)" if q.get('max_words') else "")
                for i, q in enumerate(questions)
            ]
        )

        prompt = f"""Answer the following supplemental questions for this job application in Markdown format.

JOB POSTING:
Title: {job_title}
Company: {company}

CANDIDATE PROFILE:
Name: {contact.get('name', 'Candidate')}

Top Skills: {', '.join(skills[:10])}

Work Experience:
{self._format_roles_for_prompt(roles[:4])}

Key Achievements:
{chr(10).join(achievements[:8])}

QUESTIONS TO ANSWER:
{questions_text}

REQUIREMENTS:
1. Answer each question thoroughly and specifically
2. Use ONLY facts from the profile - DO NOT invent experience
3. Provide concrete examples with quantifiable results when possible
4. Respect word limits if specified
5. Use Markdown format with clear section headers (##) for each question
6. Be concise and impact-focused
7. Demonstrate how your experience directly addresses each question

Return ONLY the Markdown answers, no other text."""

        return prompt

    def _format_roles_for_prompt(self, roles: list[dict[str, Any]]) -> str:
        """Format roles for LLM prompt."""
        lines = []
        for role in roles:
            title = role.get("title", "")
            company = role.get("company", "")
            start = role.get("start", "")
            end = role.get("end", "")
            description = role.get("description", "")
            if isinstance(description, list):
                description = " ".join(description[:3])
            lines.append(f"- {title} at {company} ({start} - {end})")
            if description:
                lines.append(f"  {description[:300]}")
        return "\n".join(lines)

    def _basic_supplemental_template(
        self, profile: dict[str, Any], job: dict[str, Any], questions: list[dict[str, Any]]
    ) -> str:
        """Fallback basic supplemental template."""
        sections = []

        for i, q in enumerate(questions):
            question = q.get('question', '')
            sections.append(f"## Question {i+1}: {question}\n")
            sections.append("Based on my experience, I can contribute to this area through my background in relevant skills and achievements.\n")

        return "\n".join(sections)
