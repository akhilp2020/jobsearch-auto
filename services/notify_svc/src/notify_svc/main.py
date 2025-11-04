from __future__ import annotations

import logging
import os
from email.message import EmailMessage
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib
from fastapi import FastAPI, HTTPException
from telegram import Bot
from telegram.error import TelegramError

from .models import NotificationChannel, NotifyRequest, NotifyResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Notify Service")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


async def _send_email(
    to: str,
    subject: str,
    message: str,
    attachments: list[str],
    links: list[dict],
) -> NotifyResponse:
    """Send email via SMTP.

    Args:
        to: Recipient email address
        subject: Email subject
        message: Email body
        attachments: List of file paths to attach
        links: List of dicts with 'label' and 'url' keys

    Returns:
        NotifyResponse with status
    """
    # Get SMTP configuration from environment
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    from_email = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_user or not smtp_password:
        raise HTTPException(
            status_code=500,
            detail="SMTP credentials not configured. Set SMTP_USER and SMTP_PASSWORD env vars.",
        )

    try:
        # Create message
        msg = MIMEMultipart()
        msg["From"] = from_email
        msg["To"] = to
        msg["Subject"] = subject or "Notification"

        # Build email body with links
        body_text = message
        if links:
            body_text += "\n\n"
            for link in links:
                label = link.get("label", "Link")
                url = link.get("url", "")
                body_text += f"\n{label}: {url}"

        msg.attach(MIMEText(body_text, "plain"))

        # Attach files
        for attachment_path in attachments:
            path = Path(attachment_path)
            if path.exists():
                with open(path, "rb") as f:
                    part = MIMEApplication(f.read(), Name=path.name)
                    part["Content-Disposition"] = f'attachment; filename="{path.name}"'
                    msg.attach(part)
            else:
                logger.warning(f"Attachment not found: {attachment_path}")

        # Send email
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            start_tls=True,
        )

        logger.info(f"Email sent to {to}")
        return NotifyResponse(
            status="SUCCESS",
            channel="email",
            to=to,
            message_id=msg.get("Message-ID", ""),
        )

    except Exception as exc:
        logger.error(f"Email send failed: {exc}")
        return NotifyResponse(
            status="FAILED",
            channel="email",
            to=to,
            error=str(exc),
        )


async def _send_telegram(
    to: str,
    message: str,
    links: list[dict],
) -> NotifyResponse:
    """Send Telegram message.

    Args:
        to: Telegram chat ID
        message: Message text
        links: List of dicts with 'label' and 'url' keys

    Returns:
        NotifyResponse with status
    """
    # Get Telegram bot token from environment
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    if not bot_token:
        raise HTTPException(
            status_code=500,
            detail="Telegram bot token not configured. Set TELEGRAM_BOT_TOKEN env var.",
        )

    try:
        bot = Bot(token=bot_token)

        # Build message with links
        full_message = message
        if links:
            full_message += "\n\n"
            for link in links:
                label = link.get("label", "Link")
                url = link.get("url", "")
                full_message += f"\n{label}: {url}"

        # Send message
        telegram_message = await bot.send_message(
            chat_id=to,
            text=full_message,
            disable_web_page_preview=False,
        )

        logger.info(f"Telegram message sent to {to}")
        return NotifyResponse(
            status="SUCCESS",
            channel="telegram",
            to=to,
            message_id=str(telegram_message.message_id),
        )

    except TelegramError as exc:
        logger.error(f"Telegram send failed: {exc}")
        return NotifyResponse(
            status="FAILED",
            channel="telegram",
            to=to,
            error=str(exc),
        )
    except Exception as exc:
        logger.error(f"Telegram send failed: {exc}")
        return NotifyResponse(
            status="FAILED",
            channel="telegram",
            to=to,
            error=str(exc),
        )


@app.post("/notify", response_model=NotifyResponse)
async def send_notification(request: NotifyRequest) -> NotifyResponse:
    """Send a notification via the specified channel.

    Args:
        request: Notification request with channel, recipient, message, etc.

    Returns:
        NotifyResponse with status and details
    """
    logger.info(f"Sending notification via {request.channel} to {request.to}")

    if request.channel == NotificationChannel.EMAIL:
        return await _send_email(
            to=request.to,
            subject=request.subject,
            message=request.message,
            attachments=request.attachments,
            links=request.links,
        )
    elif request.channel == NotificationChannel.TELEGRAM:
        return await _send_telegram(
            to=request.to,
            message=request.message,
            links=request.links,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported channel: {request.channel}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
