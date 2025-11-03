"""Filesystem MCP server implementation."""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

logger = logging.getLogger(__name__)

server = Server("mcp-fs", version="0.1.0")


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


def _list_directory(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")
    base = _base_dir()
    entries: list[dict[str, Any]] = []
    for child in sorted(path.iterdir()):
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
    return entries


def _read_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File does not exist: {path}")
    if path.is_dir():
        raise IsADirectoryError(f"Path is a directory: {path}")
    return path.read_text(encoding="utf-8")


def _write_file(path: Path, content: str, kind: str) -> dict[str, Any]:
    base = _base_dir()
    if path.is_dir():
        raise IsADirectoryError(f"Cannot write file over directory: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "text":
        path.write_text(content, encoding="utf-8")
    elif kind == "binary":
        data = base64.b64decode(content)
        path.write_bytes(data)
    else:
        raise ValueError("kind must be 'text' or 'binary'")
    info = path.stat()
    return {
        "path": str(path.relative_to(base)),
        "size": info.st_size,
        "modified": info.st_mtime,
    }


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    base_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to JOBSEARCH_HOME. Absolute paths must reside within it.",
            }
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    return [
        types.Tool(
            name="fs.list",
            description="List directory entries within JOBSEARCH_HOME",
            inputSchema=base_schema,
            outputSchema={
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "path": {"type": "string"},
                                "is_dir": {"type": "boolean"},
                                "size": {"type": "number"},
                                "modified": {"type": "number"},
                            },
                            "required": ["name", "path", "is_dir", "size", "modified"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["entries"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="fs.read",
            description="Read a UTF-8 text file within JOBSEARCH_HOME",
            inputSchema=base_schema,
            outputSchema={
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="fs.write",
            description="Write a UTF-8 text or binary file within JOBSEARCH_HOME",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": base_schema["properties"]["path"],
                    "content": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["text", "binary"],
                        "default": "text",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "size": {"type": "number"},
                    "modified": {"type": "number"},
                },
                "required": ["path", "size", "modified"],
                "additionalProperties": False,
            },
        ),
    ]


@server.call_tool()
async def invoke_tool(name: str, arguments: dict[str, Any]) -> tuple[list[types.TextContent], dict[str, Any]]:
    if name == "fs.list":
        target = _resolve_path(arguments.get("path"))
        entries = _list_directory(target)
        structured = {"entries": entries}
        text = json.dumps(structured, indent=2)
        return [types.TextContent(type="text", text=text)], structured

    if name == "fs.read":
        target = _resolve_path(arguments.get("path"))
        content = _read_file(target)
        structured = {"content": content}
        return [types.TextContent(type="text", text=content)], structured

    if name == "fs.write":
        target = _resolve_path(arguments.get("path"))
        kind = arguments.get("kind", "text")
        content = arguments.get("content", "")
        metadata = _write_file(target, content, kind)
        structured = metadata
        text = json.dumps(structured, indent=2)
        return [types.TextContent(type="text", text=text)], structured

    raise RuntimeError(f"Unknown tool: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
