#!/usr/bin/env python3
"""Test MCP filesystem client directly."""

import asyncio
import sys

from mcp_clients import FsClient


async def main():
    client = FsClient()
    print("Testing MCP fs_list...")
    try:
        result = await asyncio.wait_for(client.list(None), timeout=5.0)
        print(f"Success: {result}")
    except asyncio.TimeoutError:
        print("ERROR: MCP fs_list timed out after 5 seconds")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
