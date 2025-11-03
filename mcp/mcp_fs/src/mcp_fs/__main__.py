"""Module entrypoint for mcp_fs."""

from .server_v2 import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
