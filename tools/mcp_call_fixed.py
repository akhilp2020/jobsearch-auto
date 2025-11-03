"""CLI helper to call MCP tools via stdio servers - FIXED VERSION."""

from __future__ import annotations

import argparse
import json
import os
import sys
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_SRC_ROOT = REPO_ROOT / "mcp"

SERVER_MODULES = {
    "fs": "mcp_fs",
    "pdf": "mcp_pdf",
    "comm": "mcp_comm",
    "mcp_fs": "mcp_fs",
    "mcp_pdf": "mcp_pdf",
    "mcp_comm": "mcp_comm",
}


def _mcp_source_paths() -> list[str]:
    paths: list[str] = []
    if MCP_SRC_ROOT.exists():
        for pkg_dir in MCP_SRC_ROOT.iterdir():
            if pkg_dir.is_dir():
                src = pkg_dir / "src"
                if src.exists():
                    paths.append(str(src))
    return paths


def call_tool_sync(server_key: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool synchronously using subprocess."""
    module = SERVER_MODULES.get(server_key)
    if not module:
        raise ValueError(f"Unknown server '{server_key}'. Available: {', '.join(sorted(SERVER_MODULES))}")

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    src_paths = _mcp_source_paths()
    pythonpath_parts = src_paths + ([existing_pythonpath] if existing_pythonpath else [])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, pythonpath_parts))

    # Start the server process
    proc = subprocess.Popen(
        [sys.executable, "-m", module],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=0,
        cwd=str(REPO_ROOT),
        env=env,
    )

    try:
        # Send initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp_call", "version": "1.0.0"}
            }
        }
        proc.stdin.write(json.dumps(init_request) + "\n")
        proc.stdin.flush()

        # Read initialize response
        init_response = proc.stdout.readline()
        init_result = json.loads(init_response)
        if "error" in init_result:
            raise RuntimeError(f"Initialize failed: {init_result['error']}")

        # Send initialized notification
        initialized_notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        proc.stdin.write(json.dumps(initialized_notif) + "\n")
        proc.stdin.flush()

        # Send tool call request
        tool_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        proc.stdin.write(json.dumps(tool_request) + "\n")
        proc.stdin.flush()

        # Read tool call response
        tool_response = proc.stdout.readline()
        tool_result = json.loads(tool_response)

        if "error" in tool_result:
            raise RuntimeError(f"Tool call failed: {tool_result['error']}")

        return tool_result["result"]

    finally:
        # Clean up
        try:
            proc.stdin.close()
        except:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def format_result(result: dict[str, Any]) -> str:
    """Format the tool result for display."""
    messages: list[str] = []

    if "structuredContent" in result:
        messages.append(json.dumps(result["structuredContent"], indent=2))

    for block in result.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            messages.append(block.get("text", ""))
        else:
            messages.append(json.dumps(block, indent=2))

    return "\n".join(messages)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Call an MCP tool over stdio")
    parser.add_argument("server", help="Server key (fs, pdf, comm, or fully qualified module name)")
    parser.add_argument("tool", help="Tool name to execute, e.g. fs.list")
    parser.add_argument(
        "arguments",
        nargs="?",
        help="JSON object with tool arguments",
        default="{}",
    )
    args = parser.parse_args(argv)

    try:
        arguments = json.loads(args.arguments) if args.arguments else {}
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for arguments: {exc}") from exc

    result = call_tool_sync(args.server, args.tool, arguments)

    if result.get("isError"):
        print("Tool call failed:", file=sys.stderr)
        if result.get("content"):
            for block in result["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    print(block.get("text", ""), file=sys.stderr)
        sys.exit(1)

    output = format_result(result)
    print(output)


if __name__ == "__main__":
    main()
