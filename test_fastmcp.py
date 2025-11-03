#!/usr/bin/env python3
"""Simple test to verify FastMCP server works."""

import sys
import os

# Set environment
os.environ["JOBSEARCH_HOME"] = os.path.expanduser("~/JobSearch")

# Import the mcp instance
sys.path.insert(0, "mcp/mcp_fs/src")
from mcp_fs.server_v2 import mcp

print(f"MCP server name: {mcp.name}")
print("\nServer configured successfully!")
print(f"To run: JOBSEARCH_HOME=$HOME/JobSearch python -m mcp_fs")

# Test that we can call the tools directly
print("\nTesting fs_list tool directly...")
from mcp_fs.server_v2 import fs_list
result = fs_list(path="profile")
print(f"Result: {result}")
