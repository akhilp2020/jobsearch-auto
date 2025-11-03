"""Direct filesystem access - bypasses MCP for reliability."""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any
from datetime import datetime


def _get_jobsearch_home() -> Path:
    """Get the JOBSEARCH_HOME directory."""
    home_str = os.environ.get("JOBSEARCH_HOME")
    if not home_str:
        raise RuntimeError("JOBSEARCH_HOME environment variable is required")
    home = Path(home_str).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    return home


class DirectFsClient:
    """Direct filesystem client that doesn't use MCP."""

    def __init__(self) -> None:
        self._home = _get_jobsearch_home()

    async def read(self, path: str) -> dict[str, Any]:
        """Read a file from the filesystem."""
        full_path = self._home / path
        if not full_path.exists():
            raise FileNotFoundError(f"File does not exist: {path}")

        content = full_path.read_text(encoding="utf-8")
        return {"content": content}

    async def list(self, path: str | None = None) -> dict[str, Any]:
        """List directory entries."""
        if path:
            target = self._home / path
        else:
            target = self._home

        if not target.exists():
            raise FileNotFoundError(f"Directory does not exist: {path or '.'}")

        entries = []
        for item in target.iterdir():
            stat = item.stat()
            entries.append({
                "name": item.name,
                "path": str(item.relative_to(self._home)),
                "is_dir": item.is_dir(),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })

        return {"entries": entries}

    async def write(self, path: str, content: str, kind: str = "text") -> dict[str, Any]:
        """Write a file to the filesystem."""
        full_path = self._home / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if kind == "text":
            full_path.write_text(content, encoding="utf-8")
        else:
            full_path.write_bytes(content.encode("utf-8"))

        stat = full_path.stat()
        return {
            "path": path,
            "size": stat.st_size,
            "modified": stat.st_mtime,
        }
