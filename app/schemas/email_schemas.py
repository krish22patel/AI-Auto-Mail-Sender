"""
Pydantic schemas for email data models.

Defines all request/response models used across the FastAPI endpoints
and MCP tools for type safety and validation.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class EmailSummary(BaseModel):
    """Summary view of an email (used in list views)."""

    id: str = Field(..., description="Gmail message ID")
    thread_id: str = Field(..., description="Gmail thread ID")
    sender: str = Field(..., description="Sender email address")
    sender_name: str = Field(default="", description="Sender display name")
    subject: str = Field(..., description="Email subject line")
    snippet: str = Field(..., description="Short preview of the email body")
    date: str = Field(..., description="Date the email was received")
    is_unread: bool = Field(default=True, description="Whether the email is unread")


class EmailDetail(BaseModel):
    """Full detail view of a single email."""

    id: str = Field(..., description="Gmail message ID")
    thread_id: str = Field(..., description="Gmail thread ID")
    message_id: str = Field(default="", description="RFC 2822 Message-ID header")
    sender: str = Field(..., description="Sender email address")
    sender_name: str = Field(default="", description="Sender display name")
    to: str = Field(default="", description="Recipient email address")
    subject: str = Field(..., description="Email subject line")
    body: str = Field(..., description="Full email body (plain text)")
    html_body: str = Field(default="", description="Full email body (HTML)")
    date: str = Field(..., description="Date the email was received")
    labels: list[str] = Field(default_factory=list, description="Gmail labels")


class ReplyRequest(BaseModel):
    """Request model for replying to an email."""

    custom_reply: Optional[str] = Field(
        default=None,
        description="Custom reply text. If not provided, AI will generate a reply."
    )


class ReplyResult(BaseModel):
    """Result of a single email reply operation."""

    email_id: str = Field(..., description="ID of the email that was replied to")
    sender: str = Field(..., description="Original sender")
    subject: str = Field(..., description="Original subject")
    reply_text: str = Field(..., description="The reply that was sent")
    status: str = Field(..., description="Status: 'sent', 'failed', or 'skipped'")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class AutoReplyResult(BaseModel):
    """Result of auto-replying to all unread emails."""

    total_processed: int = Field(..., description="Total emails processed")
    successful: int = Field(..., description="Emails successfully replied to")
    failed: int = Field(..., description="Emails that failed")
    skipped: int = Field(..., description="Emails skipped (e.g., newsletters)")
    results: list[ReplyResult] = Field(default_factory=list, description="Per-email results")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="healthy")
    gmail_connected: bool = Field(default=False)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class SearchRequest(BaseModel):
    """Request model for searching emails."""

    query: str = Field(..., description="Gmail search query (same syntax as Gmail search bar)")
    max_results: int = Field(default=10, description="Maximum number of results to return")
