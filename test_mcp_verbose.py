#!/usr/bin/env python3
"""Test MCP filesystem client with verbose logging."""

import asyncio
import logging
import sys

from mcp_clients import FsClient

# Enable verbose logging
logging.basicConfig(level=logging.DEBUG)


async def main():
    client = FsClient()
    print("Testing MCP fs.list with path='profile'...")
    try:
        result = await asyncio.wait_for(client.list("profile"), timeout=10.0)
        print(f"Success: {result}")
    except asyncio.TimeoutError:
        print("ERROR: MCP fs.list timed out after 10 seconds")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
