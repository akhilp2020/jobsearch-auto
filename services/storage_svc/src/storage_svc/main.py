from __future__ import annotations

import copy
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from llm_driver.driver import LLMDriver, load_driver_from_env
from mcp_clients import DirectFsClient, MCPClientError

from .ingest import (
    canonicalize_profile,
    extract_text_from_bytes,
    merge_profiles,
    parse_llm_json,
    redact_pii,
    rule_based_profile,
)

ALLOWED_TOP_LEVEL = {"profile", "jobs", "logs", "exports"}
CANONICAL_PROFILE_PATH = "profile/canonical_profile.json"
PROFILE_HISTORY_PATH = "profile/profile_history.jsonl"
MAX_CLARIFY_QUESTIONS = 20

CLARIFY_QUESTION_SPECS = [
    {
        "id": "salary_target",
        "topic": "compensation",
        "question": "What annual base salary (USD) are you targeting for your next role?",
        "suggested_format": "Example: 180000",
        "path": ("preferences", "salary_target"),
    },
    {
        "id": "relocation",
        "topic": "location",
        "question": "Are you open to relocating? If yes, list preferred cities or regions.",
        "suggested_format": "Example: Yes, open to NYC or Seattle.",
        "path": ("preferences", "relocation"),
    },
    {
        "id": "visa",
        "topic": "eligibility",
        "question": "Do you require visa sponsorship now or in the near future?",
        "suggested_format": "Example: No sponsorship needed (US citizen).",
        "path": ("preferences", "visa"),
    },
    {
        "id": "remote_percentage",
        "topic": "work_style",
        "question": "What percentage of your workweek do you want to be remote?",
        "suggested_format": "Example: 80",
        "path": ("preferences", "remote_percentage"),
    },
    {
        "id": "industries",
        "topic": "focus",
        "question": "Which industries are you most interested in targeting?",
        "suggested_format": "Example: AI, Fintech, Developer Tools",
        "path": ("preferences", "target_industries"),
    },
    {
        "id": "seniority",
        "topic": "seniority",
        "question": "What seniority level are you targeting (e.g., Senior IC, Staff, Manager)?",
        "suggested_format": "Example: Staff Engineer or Engineering Manager",
        "path": ("preferences", "seniority"),
    },
    {
        "id": "target_titles",
        "topic": "titles",
        "question": "List the job titles you most want to pursue next.",
        "suggested_format": "Example: Staff Software Engineer, Head of AI",
        "path": ("preferences", "target_titles"),
    },
]
CLARIFY_PATHS = {spec["id"]: tuple(spec["path"]) for spec in CLARIFY_QUESTION_SPECS}
logger = logging.getLogger(__name__)


class DirectoryEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    modified: float


class ListResponse(BaseModel):
    entries: list[DirectoryEntry]


class WriteRequest(BaseModel):
    path: str
    content: str
    kind: Literal["text", "binary"] = "text"


class WriteResponse(BaseModel):
    path: str
    size: int
    modified: float


class CanonicalProfile(BaseModel):
    contact: dict[str, Any] = Field(default_factory=dict)
    roles: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)


class IngestProfileResponse(BaseModel):
    path: str
    profile: CanonicalProfile


class ClarifyQuestion(BaseModel):
    id: str
    topic: str
    question: str
    suggested_format: str | None = None


class ClarifyResponse(BaseModel):
    questions: list[ClarifyQuestion]


class ClarifyAnswer(BaseModel):
    id: str
    answer: str


class ClarifyAnswersRequest(BaseModel):
    answers: list[ClarifyAnswer]


class ClarifyAnswersResponse(BaseModel):
    path: str
    profile: CanonicalProfile


app = FastAPI(title="Storage Service")
fs_client = DirectFsClient()
_llm_driver: LLMDriver | None = None


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


def _jobsearch_home() -> Path:
    raw = os.getenv("JOBSEARCH_HOME")
    if not raw:
        raise RuntimeError("JOBSEARCH_HOME environment variable is required")
    base = Path(raw).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ensure_default_structure() -> None:
    base = _jobsearch_home()
    for folder in ALLOWED_TOP_LEVEL:
        (base / folder).mkdir(parents=True, exist_ok=True)


def _validate_job_folder(name: str) -> None:
    segments = [segment for segment in name.split("_") if segment]
    if len(segments) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job directories must follow jobs/{company}_{title}_{jobId}/ structure.",
        )
    job_id = segments[-1]
    if not job_id.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job directory suffix must be a numeric jobId.",
        )


def _normalize_path(raw: str, *, for_listing: bool) -> str:
    try:
        candidate = PurePosixPath(raw)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path format.") from exc

    if candidate.is_absolute():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path must be relative.")

    parts = candidate.parts
    if not parts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path is required.")

    if any(part in ("", ".", "..") for part in parts):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path contains invalid segments.")

    top_level = parts[0]
    if top_level not in ALLOWED_TOP_LEVEL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Top-level directory '{top_level}' is not allowed.",
        )

    if top_level == "jobs":
        if len(parts) == 1 and not for_listing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Write paths under jobs/ must target a specific job directory.",
            )
        if len(parts) >= 2:
            _validate_job_folder(parts[1])
        if not for_listing and len(parts) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Write paths under jobs/ must include a file inside a job directory.",
            )
    else:
        if not for_listing and len(parts) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Write paths under {top_level}/ must include a file name.",
            )

    return "/".join(parts)


def _get_llm_driver() -> LLMDriver:
    global _llm_driver
    if _llm_driver is None:
        try:
            _llm_driver = load_driver_from_env()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LLM provider not configured.",
            ) from exc
    return _llm_driver


def _build_extraction_prompt(text: str) -> str:
    truncated = text.strip()
    if len(truncated) > 6000:
        truncated = truncated[:6000]
    schema_description = """
You are a resume parser. Extract structured information from the resume text and return ONLY a valid JSON object.

CRITICAL: Your response must be ONLY JSON. Do not include any explanatory text, markdown formatting, or commentary.

Return a JSON object with exactly these keys:
{
  "contact": {"name": "string", "email": "string", "phone": "string"},
  "roles": [{"title": "string", "company": "string", "start": "string", "end": "string"}],
  "skills": ["string"],
  "education": ["string"],
  "achievements": ["string"],
  "preferences": {"location": "string", "remote": "yes|partial|no", "visa": "boolean or string"}
}

Rules:
- All fields are optional - use empty object/array if not found
- Do not invent information not present in the resume
- Keep skills concise (2-5 words each)
- Include achievements that mention metrics or measurable impact
- Return ONLY the JSON object, nothing else

Resume text:
"""
    prompt = f"{schema_description.strip()}\n\n{truncated}"
    return prompt


async def _read_canonical_profile() -> dict[str, Any]:
    try:
        payload = await fs_client.read(CANONICAL_PROFILE_PATH)
    except (MCPClientError, FileNotFoundError) as exc:
        message = str(exc)
        if "does not exist" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Canonical profile not found.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MCP fs.read failed: {exc}",
        ) from exc

    content = payload.get("content")
    if not isinstance(content, str):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Profile file missing text content.",
        )
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored canonical profile contains invalid JSON.",
        ) from exc
    return canonicalize_profile(data)


async def _load_or_default_profile() -> dict[str, Any]:
    try:
        return await _read_canonical_profile()
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return canonicalize_profile({})
        raise


def _value_present(profile: dict[str, Any], path: tuple[str, ...]) -> bool:
    current: Any = profile
    for key in path:
        if not isinstance(current, dict):
            return False
        current = current.get(key)
    if current is None:
        return False
    if isinstance(current, str):
        return current.strip() != ""
    if isinstance(current, (list, tuple, set)):
        return len(current) > 0
    return True


def _generate_clarify_questions(profile: dict[str, Any]) -> list[ClarifyQuestion]:
    questions: list[ClarifyQuestion] = []
    for spec in CLARIFY_QUESTION_SPECS:
        if len(questions) >= MAX_CLARIFY_QUESTIONS:
            break
        path = CLARIFY_PATHS[spec["id"]]
        if _value_present(profile, path):
            continue
        questions.append(
            ClarifyQuestion(
                id=spec["id"],
                topic=spec["topic"],
                question=spec["question"],
                suggested_format=spec.get("suggested_format"),
            )
        )
    return questions


def _coerce_yes_no(value: str) -> bool | None:
    lowered = value.strip().lower()
    positives = {"yes", "y", "true", "open", "willing", "sure"}
    negatives = {"no", "n", "false", "nope", "not", "never"}
    if lowered in positives:
        return True
    if lowered in negatives:
        return False
    return None


def _split_to_list(value: str) -> list[str]:
    tokens = [item.strip() for item in re.split(r"[,;/]", value) if item.strip()]
    if not tokens and value.strip():
        tokens = [value.strip()]
    return tokens


def _normalize_answer_value(answer_id: str, raw: str) -> Any:
    text = raw.strip()
    if not text:
        return None

    if answer_id == "salary_target":
        digits = re.sub(r"[^\d]", "", text)
        if digits:
            return int(digits)
        return text

    if answer_id == "relocation":
        coerced = _coerce_yes_no(text)
        if coerced is not None:
            return coerced
        return text

    if answer_id == "visa":
        coerced = _coerce_yes_no(text)
        if coerced is not None:
            return coerced
        return text

    if answer_id == "remote_percentage":
        match = re.search(r"\d+", text)
        if match:
            value = int(match.group())
            return max(0, min(value, 100))
        return text

    if answer_id == "industries":
        return _split_to_list(text)

    if answer_id == "target_titles":
        return _split_to_list(text)

    if answer_id == "seniority":
        return text

    return text


def _apply_clarify_answers(profile: dict[str, Any], answers: ClarifyAnswersRequest) -> dict[str, Any]:
    updated = copy.deepcopy(profile)

    def _set_nested_value(container: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
        current = container
        for key in path[:-1]:
            next_value = current.get(key)
            if not isinstance(next_value, dict):
                next_value = {}
            current[key] = next_value
            current = next_value
        current[path[-1]] = value

    for answer in answers.answers:
        path = CLARIFY_PATHS.get(answer.id)
        if not path:
            continue
        normalized = _normalize_answer_value(answer.id, answer.answer)
        if normalized is None:
            continue

        _set_nested_value(updated, path, normalized)

    return canonicalize_profile(updated)


def _diff_profiles(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    def _walk(path: list[str], left: Any, right: Any) -> None:
        if left == right:
            return
        if isinstance(left, dict) and isinstance(right, dict):
            keys = set(left) | set(right)
            for key in sorted(keys):
                _walk(path + [key], left.get(key), right.get(key))
            return
        if isinstance(left, list) and isinstance(right, list):
            if left != right:
                changes.append(
                    {"path": ".".join(path), "before": left, "after": right}
                )
            return
        changes.append({"path": ".".join(path), "before": left, "after": right})

    _walk([], before, after)
    return changes


async def _append_profile_history(changes: list[dict[str, Any]]) -> None:
    if not changes:
        return

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "changes": changes,
        "source": "clarify_answers",
    }

    line = json.dumps(entry)

    existing_content = ""
    try:
        payload = await fs_client.read(PROFILE_HISTORY_PATH)
    except FileNotFoundError:
        existing_content = ""
    except MCPClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MCP fs.read failed for history: {exc}",
        ) from exc
    else:
        content = payload.get("content")
        if isinstance(content, str):
            existing_content = content

    if existing_content:
        if not existing_content.endswith("\n"):
            existing_content = existing_content + "\n"
        new_content = existing_content + line + "\n"
    else:
        new_content = line + "\n"

    try:
        await fs_client.write(PROFILE_HISTORY_PATH, new_content, "text")
    except MCPClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MCP fs.write failed for history: {exc}",
        ) from exc


@app.on_event("startup")
async def startup() -> None:
    """Ensure directory scaffolding is present before serving traffic."""
    _ensure_default_structure()


@app.get("/list", response_model=ListResponse)
async def list_entries(path: str | None = Query(default=None)) -> ListResponse:
    """List files within the managed storage hierarchy."""
    normalized_path = None
    if path:
        normalized_path = _normalize_path(path, for_listing=True)
    try:
        listing = await fs_client.list(normalized_path)
    except MCPClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MCP fs.list failed: {exc}",
        ) from exc

    entries_raw = listing.get("entries", [])
    entries = [DirectoryEntry.model_validate(entry) for entry in entries_raw]
    return ListResponse(entries=entries)


@app.post("/write", response_model=WriteResponse)
async def write_file(payload: WriteRequest) -> WriteResponse:
    """Write file contents via the MCP FS server."""
    normalized_path = _normalize_path(payload.path, for_listing=False)
    try:
        metadata: dict[str, Any] = await fs_client.write(
            normalized_path,
            payload.content,
            payload.kind,
        )
    except MCPClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MCP fs.write failed: {exc}",
        ) from exc

    return WriteResponse.model_validate(metadata)


@app.post("/clarify", response_model=ClarifyResponse)
async def clarify() -> ClarifyResponse:
    """Return a list of targeted follow-up questions for candidate preferences."""
    profile = await _load_or_default_profile()
    questions = _generate_clarify_questions(profile)
    return ClarifyResponse(questions=questions[:MAX_CLARIFY_QUESTIONS])


@app.post("/clarify/answers", response_model=ClarifyAnswersResponse)
async def clarify_answers(payload: ClarifyAnswersRequest) -> ClarifyAnswersResponse:
    """Merge clarify answers into the canonical profile and log history."""
    if not payload.answers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one answer is required.",
        )

    current_profile = await _load_or_default_profile()
    updated_profile = _apply_clarify_answers(current_profile, payload)

    diffs = _diff_profiles(current_profile, updated_profile)
    serialized = json.dumps(updated_profile, indent=2)

    try:
        await fs_client.write(CANONICAL_PROFILE_PATH, serialized, "text")
    except MCPClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MCP fs.write failed: {exc}",
        ) from exc

    await _append_profile_history(diffs)

    return ClarifyAnswersResponse(
        path=CANONICAL_PROFILE_PATH,
        profile=CanonicalProfile.model_validate(updated_profile),
    )


@app.post("/ingest-cv", response_model=IngestProfileResponse)
async def ingest_cv(file: UploadFile = File(...)) -> IngestProfileResponse:
    """Ingest a CV document, extract structured data, and persist canonical profile JSON."""
    filename = file.filename or "upload"
    data = await file.read()
    text = extract_text_from_bytes(filename, file.content_type, data)

    rule_profile = rule_based_profile(text)
    llm_profile: dict[str, Any] = {}
    try:
        driver = _get_llm_driver()
        prompt = _build_extraction_prompt(text)
        llm_response = driver.complete(prompt, json_mode=True)
        llm_profile = parse_llm_json(llm_response)
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("LLM returned invalid JSON: %s", redact_pii(str(exc)))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("LLM extraction failed: %s", redact_pii(str(exc)))

    combined = merge_profiles(rule_profile, llm_profile)
    canonical = canonicalize_profile(combined)
    serialized = json.dumps(canonical, indent=2)

    try:
        await fs_client.write(CANONICAL_PROFILE_PATH, serialized, "text")
    except MCPClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MCP fs.write failed: {exc}",
        ) from exc

    contact_summary = redact_pii(json.dumps(canonical.get("contact", {})))
    logger.info(
        "CV ingestion complete; contact=%s roles=%d skills=%d",
        contact_summary,
        len(canonical.get("roles", [])),
        len(canonical.get("skills", [])),
    )

    return IngestProfileResponse(
        path=CANONICAL_PROFILE_PATH,
        profile=CanonicalProfile.model_validate(canonical),
    )


@app.get("/profile", response_model=CanonicalProfile)
async def get_profile() -> CanonicalProfile:
    """Return the canonical profile JSON."""
    canonical = await _read_canonical_profile()
    return CanonicalProfile.model_validate(canonical)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
