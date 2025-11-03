"""Wrappers around Model Context Protocol clients."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from mcp import types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

__all__ = ["MCPClientError", "StdIOClient", "FsClient"]


class MCPClientError(RuntimeError):
    """Raised when an MCP tool invocation reports an error."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _mcp_source_paths() -> list[str]:
    """Collect source directories for in-repo MCP servers."""
    root = _repo_root() / "mcp"
    paths: list[str] = []
    if root.exists():
        for pkg_dir in root.iterdir():
            if pkg_dir.is_dir():
                src = pkg_dir / "src"
                if src.exists():
                    paths.append(str(src))
    return paths


def _structured_content(result: types.CallToolResult) -> Any:
    structured = result.structuredContent
    if structured is None:
        return None
    if hasattr(structured, "model_dump"):  # For pydantic models
        return structured.model_dump()
    return structured


def _format_error(result: types.CallToolResult) -> str:
    pieces: list[str] = []
    structured = _structured_content(result)
    if structured is not None:
        pieces.append(str(structured))
    for block in result.content or []:
        if isinstance(block, types.TextContent):
            pieces.append(block.text)
        else:
            if hasattr(block, "model_dump_json"):
                pieces.append(block.model_dump_json())
            else:
                pieces.append(str(block))
    message = "\n".join(piece for piece in pieces if piece)
    return message or "MCP tool call failed"


class StdIOClient:
    """Lightweight wrapper to call an MCP stdio server."""

    def __init__(self, module: str) -> None:
        self._module = module
        self._repo_root = _repo_root()
        self._src_paths = _mcp_source_paths()

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        """Invoke a tool on the configured server."""
        env = os.environ.copy()
        existing = env.get("PYTHONPATH")
        pythonpath_parts = list(self._src_paths)
        if existing:
            pythonpath_parts.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, pythonpath_parts))

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", self._module],
            cwd=str(self._repo_root),
            env=env,
        )

        async with stdio_client(params) as (read_stream, write_stream):
            session = ClientSession(read_stream, write_stream)
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

        if result.isError:
            raise MCPClientError(_format_error(result))

        return result


class FsClient:
    """Client focused on the filesystem MCP server."""

    def __init__(self, stdio_client: StdIOClient | None = None) -> None:
        self._stdio_client = stdio_client or StdIOClient("mcp_fs")

    async def list(self, path: str | None = None) -> dict[str, Any]:
        """List directory entries."""
        arguments: dict[str, Any] = {}
        if path:
            arguments["path"] = path
        result = await self._stdio_client.call_tool("fs.list", arguments)
        structured = _structured_content(result)
        if not isinstance(structured, dict):
            raise MCPClientError("Unexpected fs.list response payload")
        return structured

    async def write(self, path: str, content: str, kind: str = "text") -> dict[str, Any]:
        """Write a file to the MCP-managed filesystem."""
        payload = {"path": path, "content": content, "kind": kind}
        result = await self._stdio_client.call_tool("fs.write", payload)
        structured = _structured_content(result)
        if not isinstance(structured, dict):
            raise MCPClientError("Unexpected fs.write response payload")
        return structured
