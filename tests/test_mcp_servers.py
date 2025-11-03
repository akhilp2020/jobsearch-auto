from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
import pytest

# Ensure MCP packages are importable in test context.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = PROJECT_ROOT / "mcp"
for pkg_dir in MCP_ROOT.iterdir():
    if pkg_dir.is_dir():
        src = pkg_dir / "src"
        if src.exists() and str(src) not in sys.path:
            sys.path.insert(0, str(src))


def test_fs_write_and_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBSEARCH_HOME", str(tmp_path))

    from mcp_fs.server import invoke_tool  # noqa: WPS433 (import inside test)

    async def _run() -> None:
        content = "Hello MCP"
        _, metadata = await invoke_tool(
            "fs.write",
            {"path": "notes/test.txt", "content": content, "kind": "text"},
        )
        written_path = tmp_path / "notes" / "test.txt"
        assert written_path.exists()
        assert metadata["path"] == "notes/test.txt"

        _, structured = await invoke_tool("fs.read", {"path": "notes/test.txt"})
        assert structured["content"] == content

        _, structured = await invoke_tool("fs.list", {"path": "notes"})
        entries = structured["entries"]
        assert any(entry["name"] == "test.txt" for entry in entries)

    anyio.run(_run)


def test_fs_path_escape_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBSEARCH_HOME", str(tmp_path))

    from mcp_fs.server import invoke_tool  # noqa: WPS433

    async def _run() -> None:
        with pytest.raises(RuntimeError):
            await invoke_tool("fs.read", {"path": "../outside.txt"})

    anyio.run(_run)


def test_pdf_render_creates_file() -> None:
    export_root = Path.home() / "JobSearch" / "exports"
    if export_root.exists():
        for file in export_root.glob("export_*.pdf"):
            try:
                file.unlink()
            except OSError:
                pass

    from mcp_pdf.server import invoke_tool  # noqa: WPS433

    async def _run() -> None:
        _, structured = await invoke_tool("pdf.render", {"markup": "Test"})
        pdf_path = Path(structured["path"])
        assert pdf_path.exists()
        assert pdf_path.suffix == ".pdf"
        try:
            pdf_path.unlink()
        except OSError:
            pass

    anyio.run(_run)


def test_comm_tools_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "TELEGRAM_BOT_TOKEN",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
    ]:
        monkeypatch.delenv(key, raising=False)

    from mcp_comm.server import invoke_tool  # noqa: WPS433

    async def _run() -> None:
        _, email_struct = await invoke_tool(
            "email.send",
            {"to": "user@example.com", "subject": "Hi", "html": "<p>Test</p>"},
        )
        assert "Dry-run" in email_struct["status"]

        _, telegram_struct = await invoke_tool(
            "telegram.send",
            {"chat_id": "12345", "text": "Hello"},
        )
        assert "Dry-run" in telegram_struct["status"]

        _, sms_struct = await invoke_tool(
            "sms.send",
            {"to": "+15551234567", "text": "Ping"},
        )
        assert "Dry-run" in sms_struct["status"]

    anyio.run(_run)
