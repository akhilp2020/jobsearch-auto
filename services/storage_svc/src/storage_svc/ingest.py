from __future__ import annotations

import json
import logging
import re
import os
from io import BytesIO
from tempfile import NamedTemporaryFile
from typing import Any, Iterable

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(\+?\d[\d\s\-().]{7,}\d)")
LOCATION_RE = re.compile(r"\b(?:based|located)\s+in\s+([A-Za-z\s,]+)", re.IGNORECASE)
REMOTE_RE = re.compile(r"\b(remote|hybrid)\b", re.IGNORECASE)


def redact_pii(value: str) -> str:
    """Mask common PII patterns so audit logs avoid leaking sensitive data."""

    redacted = value
    for pattern in (EMAIL_RE, PHONE_RE):
        redacted = pattern.sub("***REDACTED***", redacted)
    return redacted


def _save_named_tempfile(data: bytes, suffix: str) -> str:
    temp = NamedTemporaryFile(delete=False, suffix=suffix)
    temp.write(data)
    temp.flush()
    temp.close()
    return temp.name


def extract_text_from_bytes(filename: str, content_type: str | None, data: bytes) -> str:
    """Extract plain text from a raw CV payload."""

    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    name_lower = filename.lower()
    ct = (content_type or "").lower()

    try:
        if name_lower.endswith(".pdf") or "pdf" in ct:
            try:
                from pypdf import PdfReader
            except ImportError as exc:  # pragma: no cover - import guard
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="PDF support not available on server.",
                ) from exc

            reader = PdfReader(BytesIO(data))
            text_segments = []
            for page in reader.pages:
                extracted = page.extract_text() or ""
                if extracted:
                    text_segments.append(extracted)
            text = "\n".join(text_segments)
            if not text.strip():
                raise ValueError("No text extracted from PDF document.")
            return text

        if name_lower.endswith(".docx") or "word" in ct or name_lower.endswith(".doc"):
            try:
                import docx2txt
            except ImportError as exc:  # pragma: no cover - import guard
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="DOCX support not available on server.",
                ) from exc

            temp_path = _save_named_tempfile(data, suffix=".docx")
            try:
                text = docx2txt.process(temp_path) or ""
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:  # pragma: no cover - cleanup best effort
                    pass
            if not text.strip():
                raise ValueError("No text extracted from DOCX document.")
            return text

        # Fallback to textract for other document types.
        try:
            import textract
        except ImportError as exc:  # pragma: no cover - import guard
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file type and textract missing.",
            ) from exc

        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        temp_path = _save_named_tempfile(data, suffix=suffix)
        result_bytes: bytes
        try:
            result_bytes = textract.process(temp_path)
        finally:
            try:
                os.unlink(temp_path)
            except OSError:  # pragma: no cover - cleanup best effort
                pass
        text = result_bytes.decode("utf-8", errors="ignore")
        if not text.strip():
            raise ValueError("No text extracted from uploaded document.")
        return text
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _normalize_contact(email: str | None, phone: str | None) -> dict[str, Any]:
    contact: dict[str, Any] = {}
    if email:
        contact["email"] = email
    if phone:
        contact["phone"] = phone
    return contact


def _find_section_lines(text: str, section_name: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    collected: list[str] = []
    capture = False
    section_token = section_name.lower()
    for line in lines:
        lower = line.lower()
        if section_token in lower and len(lower) < 60:
            capture = True
            continue
        if capture and any(marker in lower for marker in ("summary", "experience", "education", "skills", "projects")):
            capture = False
        if capture:
            collected.append(line)
    return collected


def _extract_roles(lines: Iterable[str]) -> list[dict[str, Any]]:
    roles: list[dict[str, Any]] = []
    role_pattern = re.compile(
        r"(?P<title>[A-Za-z &/]+)\s+[-@]\s+(?P<company>[A-Za-z0-9 .,&/]+)\s+\((?P<dates>[^)]+)\)"
    )
    for line in lines:
        match = role_pattern.search(line)
        if not match:
            continue
        dates = match.group("dates")
        start, _, end = dates.partition("-")
        roles.append(
            {
                "title": match.group("title").strip(),
                "company": match.group("company").strip(),
                "start": start.strip() or None,
                "end": end.strip() or None,
            }
        )
    return roles


def _extract_skills(text: str) -> list[str]:
    sections = _find_section_lines(text, "Skills")
    skills: set[str] = set()
    for line in sections:
        for token in re.split(r"[;,]", line):
            token = token.strip()
            if token and 2 < len(token) < 32:
                skills.add(token)
    return sorted(skills)


def _extract_education(text: str) -> list[str]:
    return _find_section_lines(text, "Education")


def _extract_achievements(lines: Iterable[str]) -> list[str]:
    achievements: list[str] = []
    for line in lines:
        if any(char.isdigit() for char in line) and len(line) < 200:
            achievements.append(line.strip())
    return achievements


def _extract_preferences(text: str) -> dict[str, Any]:
    preferences: dict[str, Any] = {}
    location_match = LOCATION_RE.search(text)
    if location_match:
        preferences["location"] = location_match.group(1).strip()
    remote_match = REMOTE_RE.search(text)
    if remote_match:
        preferences["remote"] = remote_match.group(1).lower()
    if "visa" in text.lower():
        preferences["visa"] = True
    return preferences


def rule_based_profile(text: str) -> dict[str, Any]:
    email_match = EMAIL_RE.search(text)
    phone_match = PHONE_RE.search(text)
    contact = _normalize_contact(
        email_match.group(0) if email_match else None,
        phone_match.group(0) if phone_match else None,
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    profile = {
        "contact": contact,
        "roles": _extract_roles(lines),
        "skills": _extract_skills(text),
        "education": _extract_education(text),
        "achievements": _extract_achievements(lines),
        "preferences": _extract_preferences(text),
    }
    return profile


def merge_profiles(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    combined = primary.copy()
    for key, value in secondary.items():
        if not value:
            continue
        if isinstance(value, dict):
            existing = combined.get(key, {})
            if not isinstance(existing, dict):
                combined[key] = value
            else:
                merged = existing.copy()
                merged.update({k: v for k, v in value.items() if v})
                combined[key] = merged
        else:
            combined[key] = value
    return combined


def clean_llm_response(raw: str) -> str:
    """Strip markdown code blocks and extra text from LLM response.

    Handles common patterns like:
    - ```json ... ```
    - ```\n...\n```
    - Extra explanatory text before/after JSON
    """
    text = raw.strip()

    # Remove markdown code blocks
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        lines = text.split("\n", 1)
        if len(lines) > 1:
            text = lines[1]
        else:
            text = ""

        # Remove closing fence
        if text.endswith("```"):
            text = text[:-3].strip()

    # Try to find JSON object boundaries
    # Look for the first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")

    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]

    return text.strip()


def parse_llm_json(raw: str) -> dict[str, Any]:
    """Parse LLM response as JSON, with automatic cleanup of common formatting issues."""
    cleaned = clean_llm_response(raw)
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("LLM returned unexpected data.")
        return data
    except json.JSONDecodeError as exc:
        raise ValueError("Failed to parse LLM output as JSON.") from exc


def canonicalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Ensure the serialized profile uses the expected schema."""

    def _as_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _as_list(value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    contact = _as_dict(profile.get("contact"))
    roles_input = _as_list(profile.get("roles"))
    roles: list[dict[str, Any]] = []
    for entry in roles_input:
        if not isinstance(entry, dict):
            continue
        roles.append(
            {
                "title": entry.get("title"),
                "company": entry.get("company"),
                "start": entry.get("start"),
                "end": entry.get("end"),
            }
        )

    canonical = {
        "contact": contact,
        "roles": roles,
        "skills": _as_list(profile.get("skills")),
        "education": _as_list(profile.get("education")),
        "achievements": _as_list(profile.get("achievements")),
        "preferences": _as_dict(profile.get("preferences")),
    }
    return canonical
