"""Filesystem MCP server implementation using FastMCP."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

mcp = FastMCP("mcp-fs")


def _base_dir() -> Path:
    locator = os.getenv("JOBSEARCH_HOME")
    if not locator:
        raise RuntimeError("JOBSEARCH_HOME environment variable is required for mcp_fs")
    base = Path(locator).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _resolve_path(raw_path: str | None) -> Path:
    base = _base_dir()
    if not raw_path:
        target = base
    else:
        candidate = Path(raw_path)
        target = (base / candidate).resolve() if not candidate.is_absolute() else candidate.expanduser().resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise RuntimeError(f"Path escapes JOBSEARCH_HOME: {raw_path}") from exc
    return target


@mcp.tool()
def fs_list(path: str = "") -> dict[str, Any]:
    """List directory entries within JOBSEARCH_HOME.

    Args:
        path: Path relative to JOBSEARCH_HOME. Absolute paths must reside within it. Defaults to JOBSEARCH_HOME root if not provided.

    Returns:
        Dictionary with 'entries' list containing file/directory information.
    """
    target = _resolve_path(path if path else None)

    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not target.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")

    base = _base_dir()
    entries: list[dict[str, Any]] = []
    for child in sorted(target.iterdir()):
        info = child.stat()
        entries.append(
            {
                "name": child.name,
                "path": str(child.relative_to(base)),
                "is_dir": child.is_dir(),
                "size": info.st_size,
                "modified": info.st_mtime,
            }
        )
    return {"entries": entries}


@mcp.tool()
def fs_read(path: str) -> dict[str, str]:
    """Read a UTF-8 text file within JOBSEARCH_HOME.

    Args:
        path: Path relative to JOBSEARCH_HOME. Absolute paths must reside within it.

    Returns:
        Dictionary with 'content' containing the file text.
    """
    target = _resolve_path(path)

    if not target.exists():
        raise FileNotFoundError(f"File does not exist: {path}")
    if target.is_dir():
        raise IsADirectoryError(f"Path is a directory: {path}")

    content = target.read_text(encoding="utf-8")
    return {"content": content}


@mcp.tool()
def fs_write(path: str, content: str, kind: str = "text") -> dict[str, Any]:
    """Write a UTF-8 text or binary file within JOBSEARCH_HOME.

    Args:
        path: Path relative to JOBSEARCH_HOME. Absolute paths must reside within it.
        content: The file content to write. For binary files, should be base64-encoded.
        kind: Either 'text' (default) or 'binary'.

    Returns:
        Dictionary with file metadata (path, size, modified timestamp).
    """
    target = _resolve_path(path)
    base = _base_dir()

    if target.is_dir():
        raise IsADirectoryError(f"Cannot write file over directory: {path}")

    target.parent.mkdir(parents=True, exist_ok=True)

    if kind == "text":
        target.write_text(content, encoding="utf-8")
    elif kind == "binary":
        data = base64.b64decode(content)
        target.write_bytes(data)
    else:
        raise ValueError("kind must be 'text' or 'binary'")

    info = target.stat()
    return {
        "path": str(target.relative_to(base)),
        "size": info.st_size,
        "modified": info.st_mtime,
    }
