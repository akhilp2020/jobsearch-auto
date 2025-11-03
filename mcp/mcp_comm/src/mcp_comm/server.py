"""Communications MCP server with email, Telegram, and SMS tools."""

from __future__ import annotations

import logging
import os
from email.message import EmailMessage
from typing import Any

import anyio
import httpx
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

logger = logging.getLogger(__name__)

server = Server("mcp-comm", version="0.1.0")


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _dry_run(message: str) -> tuple[str, bool]:
    return message, True


def _email_config() -> dict[str, Any] | None:
    host = os.getenv("SMTP_HOST")
    port = os.getenv("SMTP_PORT")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() != "false"

    if not host or not port or not sender:
        return None

    try:
        port_value = int(port)
    except ValueError:
        raise ValueError("SMTP_PORT must be an integer")

    return {
        "host": host,
        "port": port_value,
        "username": username,
        "password": password,
        "sender": sender,
        "use_tls": use_tls,
    }


def _telegram_token() -> str | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    return token


def _twilio_config() -> dict[str, str] | None:
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")
    if not sid or not token or not from_number:
        return None
    return {"sid": sid, "token": token, "from": from_number}


async def _send_email(to_addr: str, subject: str, html: str) -> str:
    config = _email_config()
    if not config:
        message, _ = _dry_run(f"Dry-run email to {to_addr}: {subject}")
        return message

    def _send() -> None:
        from smtplib import SMTP

        msg = EmailMessage()
        msg["From"] = config["sender"]
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content("HTML version attached")
        msg.add_alternative(html, subtype="html")

        with SMTP(config["host"], config["port"]) as smtp:
            if config["use_tls"]:
                smtp.starttls()
            if config["username"] and config["password"]:
                smtp.login(config["username"], config["password"])
            smtp.send_message(msg)

    await anyio.to_thread.run_sync(_send)
    return f"Email sent to {to_addr}"


async def _send_telegram(chat_id: str, text: str) -> str:
    token = _telegram_token()
    if not token:
        message, _ = _dry_run(f"Dry-run Telegram message to {chat_id}: {text}")
        return message

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    def _send() -> None:
        response = httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        response.raise_for_status()

    await anyio.to_thread.run_sync(_send)
    return f"Telegram message delivered to chat {chat_id}"


async def _send_sms(to_number: str, text: str) -> str:
    config = _twilio_config()
    if not config:
        message, _ = _dry_run(f"Dry-run SMS to {to_number}: {text}")
        return message

    url = f"https://api.twilio.com/2010-04-01/Accounts/{config['sid']}/Messages.json"

    def _send() -> None:
        response = httpx.post(
            url,
            data={"To": to_number, "From": config["from"], "Body": text},
            auth=(config["sid"], config["token"]),
            timeout=10,
        )
        response.raise_for_status()

    await anyio.to_thread.run_sync(_send)
    return f"SMS sent to {to_number}"


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="email.send",
            description="Send an email via SMTP (dry-run when credentials missing)",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "html": {"type": "string"},
                },
                "required": ["to", "subject", "html"],
                "additionalProperties": False,
            },
            outputSchema={
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="telegram.send",
            description="Send a Telegram message (dry-run when bot token missing)",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["chat_id", "text"],
                "additionalProperties": False,
            },
            outputSchema={
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="sms.send",
            description="Send an SMS using Twilio (dry-run when credentials missing)",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["to", "text"],
                "additionalProperties": False,
            },
            outputSchema={
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
                "additionalProperties": False,
            },
        ),
    ]


@server.call_tool()
async def invoke_tool(name: str, arguments: dict[str, Any]):
    if name == "email.send":
        status = await _send_email(arguments["to"], arguments["subject"], arguments["html"])
    elif name == "telegram.send":
        status = await _send_telegram(arguments["chat_id"], arguments["text"])
    elif name == "sms.send":
        status = await _send_sms(arguments["to"], arguments["text"])
    else:
        raise RuntimeError(f"Unknown tool: {name}")

    structured = {"status": status}
    return [types.TextContent(type="text", text=status)], structured


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
