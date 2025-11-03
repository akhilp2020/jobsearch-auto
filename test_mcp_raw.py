#!/usr/bin/env python3
"""Test MCP server directly with raw stdio communication."""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def test_mcp_server():
    """Test the MCP filesystem server directly."""

    # Setup environment
    repo_root = Path(__file__).parent
    mcp_src = repo_root / "mcp" / "mcp_fs" / "src"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(mcp_src)
    env["JOBSEARCH_HOME"] = str(Path.home() / "JobSearch")

    print(f"JOBSEARCH_HOME={env['JOBSEARCH_HOME']}")
    print(f"PYTHONPATH={env['PYTHONPATH']}")
    print(f"Python executable: {sys.executable}")
    print("\nStarting MCP server...")

    # Start the MCP server
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_fs"],
        cwd=str(repo_root),
        env=env,
    )

    try:
        async with stdio_client(params) as (read_stream, write_stream):
            print("MCP server started, creating session...")

            session = ClientSession(read_stream, write_stream)

            print("Initializing session...")
            init_result = await asyncio.wait_for(session.initialize(), timeout=5.0)
            print(f"Session initialized: {init_result}")

            print("\nListing tools...")
            tools = await asyncio.wait_for(session.list_tools(), timeout=5.0)
            print(f"Available tools: {[t.name for t in tools.tools]}")

            print("\nCalling fs.list with path='profile'...")
            result = await asyncio.wait_for(
                session.call_tool("fs.list", {"path": "profile"}),
                timeout=5.0
            )

            print(f"Success! Result: {result}")

            if result.isError:
                print(f"ERROR: Tool call reported an error")
                for content in result.content:
                    print(f"  {content}")
            else:
                print("Tool call succeeded!")
                for content in result.content:
                    if hasattr(content, 'text'):
                        print(f"  Text: {content.text[:200]}")

    except asyncio.TimeoutError as e:
        print(f"\nERROR: Operation timed out: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_mcp_server())
