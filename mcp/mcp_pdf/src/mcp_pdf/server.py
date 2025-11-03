"""PDF rendering MCP server."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import anyio
from fpdf import FPDF
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

logger = logging.getLogger(__name__)

server = Server("mcp-pdf", version="0.1.0")


EXPORT_ROOT = Path.home() / "JobSearch" / "exports"


def _ensure_export_root() -> Path:
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    return EXPORT_ROOT


def _render_pdf(markup: str, template: str) -> Path:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    if template == "simple":
        pdf.set_font("Helvetica", size=12)
    elif template == "title":
        pdf.set_font("Helvetica", "B", size=16)
    else:
        pdf.set_font("Helvetica", size=12)

    for line in markup.splitlines() or [markup]:
        pdf.multi_cell(0, 8, text=line if line else "")

    target_dir = _ensure_export_root()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"export_{timestamp}_{uuid4().hex[:8]}.pdf"
    output_path = target_dir / filename
    pdf.output(str(output_path))
    return output_path


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="pdf.render",
            description="Render markup into a PDF saved under ~/JobSearch/exports",
            inputSchema={
                "type": "object",
                "properties": {
                    "markup": {"type": "string"},
                    "format": {
                        "type": "string",
                        "enum": ["pdf"],
                        "default": "pdf",
                    },
                    "template": {
                        "type": "string",
                        "enum": ["simple", "title"],
                        "default": "simple",
                    },
                },
                "required": ["markup"],
                "additionalProperties": False,
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        )
    ]


@server.call_tool()
async def invoke_tool(name: str, arguments: dict[str, Any]):
    if name != "pdf.render":
        raise RuntimeError(f"Unknown tool: {name}")

    markup = arguments.get("markup")
    if not isinstance(markup, str) or not markup.strip():
        raise ValueError("markup must be a non-empty string")

    fmt = arguments.get("format", "pdf")
    if fmt != "pdf":
        raise ValueError("Only PDF format is supported")

    template = arguments.get("template", "simple")
    output_path = _render_pdf(markup, template)
    structured = {"path": str(output_path)}
    message = f"PDF generated at {output_path}"
    return [types.TextContent(type="text", text=message)], structured


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
