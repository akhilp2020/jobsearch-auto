from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp_fs.server import invoke_tool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = PROJECT_ROOT / "services" / "storage_svc" / "src"
LIB_SRC = PROJECT_ROOT / "libs" / "mcp_clients" / "src"
LLM_SRC = PROJECT_ROOT / "libs" / "llm_driver" / "src"

for path in [str(LIB_SRC), str(SERVICE_SRC), str(LLM_SRC)]:
    if path not in sys.path:
        sys.path.insert(0, path)


class InProcessFsClient:
    """Use the mcp_fs server implementation directly for tests."""

    async def list(self, path: str | None = None) -> dict[str, object]:
        arguments: dict[str, object] = {}
        if path is not None:
            arguments["path"] = path
        _, structured = await invoke_tool("fs.list", arguments)
        return structured

    async def write(self, path: str, content: str, kind: str = "text") -> dict[str, object]:
        payload = {"path": path, "content": content, "kind": kind}
        _, structured = await invoke_tool("fs.write", payload)
        return structured

    async def read(self, path: str) -> dict[str, object]:
        _, structured = await invoke_tool("fs.read", {"path": path})
        return structured


def _load_app():
    module_name = "storage_svc.main"
    if module_name in sys.modules:
        del sys.modules[module_name]
    module = importlib.import_module(module_name)
    module.fs_client = InProcessFsClient()
    return module.app


def _write(client: TestClient, **payload):
    response = client.post("/write", json=payload)
    return response


def test_write_and_list_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBSEARCH_HOME", str(tmp_path))
    app = _load_app()

    with TestClient(app) as client:
        response = _write(client, path="profile/summary.txt", content="Hello MCP", kind="text")
        assert response.status_code == 200
        data = response.json()
        assert data["path"] == "profile/summary.txt"

        written_file = tmp_path / "profile" / "summary.txt"
        assert written_file.exists()
        assert written_file.read_text() == "Hello MCP"

        list_response = client.get("/list", params={"path": "profile"})
        assert list_response.status_code == 200
        entries = list_response.json()["entries"]
        assert any(entry["name"] == "summary.txt" for entry in entries)


def test_write_and_list_job_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBSEARCH_HOME", str(tmp_path))
    app = _load_app()

    job_folder = "acme_swe_12345"

    with TestClient(app) as client:
        response = _write(client, path=f"jobs/{job_folder}/notes.md", content="Job notes")
        assert response.status_code == 200

        list_response = client.get("/list", params={"path": f"jobs/{job_folder}"})
        assert list_response.status_code == 200
        entries = list_response.json()["entries"]
        assert any(entry["name"] == "notes.md" for entry in entries)

        root_listing = client.get("/list")
        assert root_listing.status_code == 200
        root_names = {entry["name"] for entry in root_listing.json()["entries"]}
        assert {"profile", "jobs", "logs", "exports"}.issubset(root_names)


def test_invalid_paths_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBSEARCH_HOME", str(tmp_path))
    app = _load_app()

    with TestClient(app) as client:
        bad_top_level = _write(client, path="notes/bad.txt", content="oops")
        assert bad_top_level.status_code == 400

        missing_job_folder = _write(client, path="jobs/notes.txt", content="oops")
        assert missing_job_folder.status_code == 400

        invalid_job_folder = _write(client, path="jobs/acme_notes/job.txt", content="oops")
        assert invalid_job_folder.status_code == 400


class StubLLMDriver:
    def __init__(self) -> None:
        self.last_prompt: str | None = None

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        self.last_prompt = prompt
        payload = {
            "contact": {"name": "Alex Candidate", "email": "alex@example.com"},
            "roles": [
                {
                    "title": "Senior Engineer",
                    "company": "Example Corp",
                    "start": "2020",
                    "end": "2024",
                }
            ],
            "skills": ["Python", "FastAPI"],
            "achievements": ["Improved conversion by 35%"],
            "preferences": {"location": "New York", "remote": "hybrid"},
        }
        return json.dumps(payload)


def test_ingest_cv_and_get_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBSEARCH_HOME", str(tmp_path))

    app = _load_app()
    module = sys.modules["storage_svc.main"]
    module.fs_client = InProcessFsClient()
    module._llm_driver = StubLLMDriver()
    module.extract_text_from_bytes = lambda *args, **kwargs: (
        "Alex Candidate\nalex@example.com\n+1 (555) 123-4567\n"
        "Experience\nSenior Engineer - Example Corp (2020 - 2024)\n"
        "Skills: Python; FastAPI; Docker\n"
        "Education\nState University, B.S. Computer Science\n"
        "Achievements\nReduced cost by 15% in cloud migration.\n"
        "Preferences\nBased in New York, open to hybrid roles. Requires no visa sponsorship."
    )

    with TestClient(app) as client:
        files = {"file": ("resume.pdf", b"%PDF-1.4 mock content", "application/pdf")}
        response = client.post("/ingest-cv", files=files)
        assert response.status_code == 200
        payload = response.json()
        assert payload["path"] == "profile/canonical_profile.json"
        profile = payload["profile"]
        assert profile["contact"]["email"] == "alex@example.com"
        assert profile["contact"]["phone"].startswith("+1")
        assert profile["roles"][0]["company"] == "Example Corp"
        assert "Python" in profile["skills"]
        assert profile["preferences"]["remote"] == "hybrid"

        canonical_file = tmp_path / "profile" / "canonical_profile.json"
        assert canonical_file.exists()
        stored = json.loads(canonical_file.read_text())
        assert stored["contact"]["email"] == "alex@example.com"

        get_profile = client.get("/profile")
        assert get_profile.status_code == 200
        fetched = get_profile.json()
        assert fetched["roles"][0]["title"] == "Senior Engineer"


def test_get_profile_missing_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBSEARCH_HOME", str(tmp_path))
    app = _load_app()

    with TestClient(app) as client:
        response = client.get("/profile")
        assert response.status_code == 404
