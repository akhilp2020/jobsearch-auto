from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class NotificationChannel(str, Enum):
    """Notification channel types."""

    EMAIL = "email"
    TELEGRAM = "telegram"


class NotifyRequest(BaseModel):
    """Request to send a notification."""

    channel: NotificationChannel = Field(..., description="Notification channel")
    to: str = Field(..., description="Recipient (email address or Telegram chat ID)")
    message: str = Field(..., description="Message content")
    subject: str = Field(default="", description="Subject line (email only)")
    attachments: list[str] = Field(
        default_factory=list, description="File paths to attach (email only)"
    )
    links: list[dict] = Field(
        default_factory=list,
        description="Links to include with label and url keys",
    )


class NotifyResponse(BaseModel):
    """Response from notification."""

    status: str = Field(..., description="SUCCESS or FAILED")
    channel: str = Field(..., description="Channel used")
    to: str = Field(..., description="Recipient")
    message_id: str = Field(default="", description="Message ID if available")
    error: str = Field(default="", description="Error message if failed")
