"""CLI helper to call MCP tools via stdio servers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import anyio

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import types


REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_SRC_ROOT = REPO_ROOT / "mcp"


def _mcp_source_paths() -> list[str]:
    paths: list[str] = []
    if MCP_SRC_ROOT.exists():
        for pkg_dir in MCP_SRC_ROOT.iterdir():
            if pkg_dir.is_dir():
                src = pkg_dir / "src"
                if src.exists():
                    paths.append(str(src))
    return paths


def _extend_sys_path() -> None:
    for src in _mcp_source_paths():
        if src not in sys.path:
            sys.path.insert(0, src)


_extend_sys_path()

SERVER_MODULES = {
    "fs": "mcp_fs",
    "pdf": "mcp_pdf",
    "comm": "mcp_comm",
    "mcp_fs": "mcp_fs",
    "mcp_pdf": "mcp_pdf",
    "mcp_comm": "mcp_comm",
}


async def call_tool(server_key: str, tool_name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    module = SERVER_MODULES.get(server_key)
    if not module:
        raise ValueError(f"Unknown server '{server_key}'. Available: {', '.join(sorted(SERVER_MODULES))}")

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    src_paths = _mcp_source_paths()
    pythonpath_parts = src_paths + ([existing_pythonpath] if existing_pythonpath else [])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, pythonpath_parts))

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        cwd=str(REPO_ROOT),
        env=env,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        session = ClientSession(read_stream, write_stream)
        await session.initialize()
        return await session.call_tool(tool_name, arguments)


def format_result(result: types.CallToolResult) -> str:
    messages: list[str] = []
    if result.structuredContent is not None:
        messages.append(json.dumps(result.structuredContent, indent=2))

    for block in result.content or []:
        if isinstance(block, types.TextContent):
            messages.append(block.text)
        else:
            messages.append(block.model_dump_json(indent=2))

    return "\n".join(messages)


async def _async_main(args: argparse.Namespace) -> None:
    try:
        arguments = json.loads(args.arguments) if args.arguments else {}
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for arguments: {exc}") from exc

    result = await call_tool(args.server, args.tool, arguments)
    if result.isError:
        print("Tool call failed:", file=sys.stderr)
        if result.content:
            for block in result.content:
                if isinstance(block, types.TextContent):
                    print(block.text, file=sys.stderr)
        sys.exit(1)

    output = format_result(result)
    print(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call an MCP tool over stdio")
    parser.add_argument("server", help="Server key (fs, pdf, comm, or fully qualified module name)")
    parser.add_argument("tool", help="Tool name to execute, e.g. fs.list")
    parser.add_argument(
        "arguments",
        nargs="?",
        help="JSON object with tool arguments",
        default="{}",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    anyio.run(_async_main, args)


if __name__ == "__main__":
    main()
