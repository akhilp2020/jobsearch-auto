from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class Violation:
    """Represents a validation violation."""

    def __init__(self, artifact: str, line: int | None, reason: str):
        self.artifact = artifact
        self.line = line
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "line": self.line,
            "reason": self.reason,
        }


class ValidationResult:
    """Result of artifact validation."""

    def __init__(self, passed: bool, violations: list[Violation], suggestions: list[str]):
        self.passed = passed
        self.violations = violations
        self.suggestions = suggestions

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "suggestions": self.suggestions,
        }


def validate_artifacts(
    profile_path: str | Path, artifact_paths: list[str | Path]
) -> ValidationResult:
    """Validate artifacts against profile data.

    Rules:
    1. Every bullet must trace to an evidence comment that maps to a real profile entry
    2. Ban unverified skills (skills not in profile)
    3. Ban date/title mismatches (dates or titles that don't match profile roles)

    Args:
        profile_path: Path to canonical profile JSON
        artifact_paths: List of paths to HTML artifacts to validate

    Returns:
        ValidationResult with pass/fail status, violations, and suggestions
    """
    violations: list[Violation] = []
    suggestions: list[str] = []

    # Load profile
    profile_path = Path(profile_path)
    if not profile_path.exists():
        violations.append(Violation("profile", None, f"Profile not found at {profile_path}"))
        return ValidationResult(False, violations, suggestions)

    try:
        with open(profile_path) as f:
            profile = json.load(f)
    except Exception as exc:
        violations.append(Violation("profile", None, f"Failed to load profile: {exc}"))
        return ValidationResult(False, violations, suggestions)

    # Validate each artifact
    for artifact_path in artifact_paths:
        artifact_path = Path(artifact_path)
        if not artifact_path.exists():
            violations.append(
                Violation(str(artifact_path), None, f"Artifact not found at {artifact_path}")
            )
            continue

        try:
            with open(artifact_path) as f:
                artifact_content = f.read()
        except Exception as exc:
            violations.append(
                Violation(str(artifact_path), None, f"Failed to read artifact: {exc}")
            )
            continue

        # Run validation rules
        _validate_evidence_tracing(
            str(artifact_path), artifact_content, profile, violations, suggestions
        )
        _validate_skills(str(artifact_path), artifact_content, profile, violations, suggestions)
        _validate_dates_and_titles(
            str(artifact_path), artifact_content, profile, violations, suggestions
        )

    passed = len(violations) == 0
    return ValidationResult(passed, violations, suggestions)


def _validate_evidence_tracing(
    artifact: str,
    content: str,
    profile: dict[str, Any],
    violations: list[Violation],
    suggestions: list[str],
) -> None:
    """Validate that every bullet/paragraph has evidence tracing to profile."""
    lines = content.split("\n")

    # Track substantive content lines (bullets, paragraphs with impact keywords)
    substantive_lines: list[tuple[int, str]] = []

    for i, line in enumerate(lines, start=1):
        line_stripped = line.strip()

        # Check for bullets (li tags) or paragraphs with impact keywords
        if "<li>" in line_stripped or (
            "<p>" in line_stripped
            and any(
                keyword in line_stripped.lower()
                for keyword in [
                    "led",
                    "achieved",
                    "reduced",
                    "enabled",
                    "implemented",
                    "developed",
                    "managed",
                    "created",
                    "experience",
                    "skill",
                ]
            )
        ):
            substantive_lines.append((i, line_stripped))

    # Check each substantive line for evidence comment
    for line_num, line_content in substantive_lines:
        # Look for evidence comment on the same line or previous line
        has_evidence = False

        # Check current line
        if "<!-- evidence:" in line_content:
            has_evidence = True
        # Check previous line if exists
        elif line_num > 1 and "<!-- evidence:" in lines[line_num - 2]:
            has_evidence = True

        if not has_evidence:
            # Extract text content for reporting
            text_match = re.search(r"<(?:li|p)>(.*?)</(?:li|p)>", line_content)
            text_preview = text_match.group(1)[:50] if text_match else line_content[:50]

            violations.append(
                Violation(
                    artifact,
                    line_num,
                    f"Missing evidence comment for substantive content: '{text_preview}...'",
                )
            )

    # Validate that evidence comments reference valid profile entries
    evidence_pattern = re.compile(r"<!-- evidence:([^>]+) -->")
    for i, line in enumerate(lines, start=1):
        for match in evidence_pattern.finditer(line):
            evidence_ref = match.group(1)

            # Parse evidence reference (e.g., "skills[0]", "roles[1]", "achievements[2]")
            if not _validate_evidence_reference(evidence_ref, profile):
                violations.append(
                    Violation(
                        artifact,
                        i,
                        f"Evidence comment references invalid profile entry: '{evidence_ref}'",
                    )
                )


def _validate_evidence_reference(ref: str, profile: dict[str, Any]) -> bool:
    """Check if an evidence reference points to a valid profile entry."""
    # Parse reference format: "key[index]" or "key"
    match = re.match(r"^([a-z_]+)(?:\[(\d+)\])?$", ref)
    if not match:
        return False

    key = match.group(1)
    index_str = match.group(2)

    # Check if key exists in profile
    if key not in profile:
        return False

    # If no index, just check key exists
    if index_str is None:
        return True

    # If index specified, check it's within bounds
    index = int(index_str)
    profile_value = profile[key]

    if isinstance(profile_value, list):
        return 0 <= index < len(profile_value)
    elif isinstance(profile_value, dict):
        # For dict, index doesn't make sense
        return False

    return True


def _validate_skills(
    artifact: str,
    content: str,
    profile: dict[str, Any],
    violations: list[Violation],
    suggestions: list[str],
) -> None:
    """Ban unverified skills not present in profile."""
    profile_skills = [skill.lower() for skill in profile.get("skills", [])]

    lines = content.split("\n")

    # Common skill-related patterns to check
    skill_indicators = [
        r"(?:experience|proficient|skilled|expertise) (?:in|with) ([A-Z][A-Za-z0-9+\-. ]+)",
        r"(?:using|leveraging|utilizing) ([A-Z][A-Za-z0-9+\-. ]+)",
        r"([A-Z][A-Za-z0-9+\-. ]+) (?:development|engineering|implementation)",
    ]

    for i, line in enumerate(lines, start=1):
        # Skip HTML tags and evidence comments
        if line.strip().startswith("<!--") or line.strip().startswith("<"):
            continue

        for pattern in skill_indicators:
            for match in re.finditer(pattern, line):
                mentioned_skill = match.group(1).strip()

                # Skip very short matches or common words
                if len(mentioned_skill) < 3 or mentioned_skill.lower() in [
                    "the",
                    "and",
                    "with",
                    "for",
                    "from",
                ]:
                    continue

                # Check if this skill (or a close variation) is in profile
                skill_lower = mentioned_skill.lower()
                if not any(
                    skill_lower in profile_skill or profile_skill in skill_lower
                    for profile_skill in profile_skills
                ):
                    violations.append(
                        Violation(
                            artifact,
                            i,
                            f"Unverified skill mentioned: '{mentioned_skill}' not found in profile",
                        )
                    )


def _validate_dates_and_titles(
    artifact: str,
    content: str,
    profile: dict[str, Any],
    violations: list[Violation],
    suggestions: list[str],
) -> None:
    """Ban date/title mismatches with profile roles."""
    roles = profile.get("roles", [])

    # Build a list of valid role titles and companies
    valid_titles = set()
    valid_companies = set()
    role_date_ranges: dict[str, tuple[str, str]] = {}

    for role in roles:
        title = role.get("title", "").lower()
        company = role.get("company", "").lower()
        start = role.get("start", "")
        end = role.get("end", "")

        if title:
            valid_titles.add(title)
            role_date_ranges[title] = (start, end)

        if company:
            valid_companies.add(company)

    lines = content.split("\n")

    # Look for role/title mentions
    for i, line in enumerate(lines, start=1):
        # Skip HTML tags and comments
        if line.strip().startswith("<!--"):
            continue

        line_lower = line.lower()

        # Check for title mentions
        for valid_title in valid_titles:
            if valid_title in line_lower:
                # Found a title mention - check if dates are mentioned nearby
                # Look for date patterns (YYYY, MM/YYYY, Month YYYY)
                date_patterns = [
                    r"\b(20\d{2})\b",  # Year like 2020
                    r"\b(\d{1,2}/20\d{2})\b",  # MM/YYYY
                    r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* 20\d{2})\b",  # Month YYYY
                ]

                for date_pattern in date_patterns:
                    for date_match in re.finditer(date_pattern, line, re.IGNORECASE):
                        mentioned_date = date_match.group(1)

                        # Get expected date range for this title
                        start, end = role_date_ranges.get(valid_title, ("", ""))

                        # Check if mentioned date is within range
                        # Simple check: see if date string appears in start or end
                        if mentioned_date not in start and mentioned_date not in end:
                            # Extract year for comparison
                            year_match = re.search(r"20\d{2}", mentioned_date)
                            if year_match:
                                year = year_match.group(0)
                                if year not in start and year not in end:
                                    violations.append(
                                        Violation(
                                            artifact,
                                            i,
                                            f"Date mismatch: '{mentioned_date}' mentioned for role '{valid_title}', "
                                            f"but profile shows {start} - {end}",
                                        )
                                    )
