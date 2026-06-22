"""
Gmail Service Module.

Handles all Gmail API interactions including:
- Fetching unread emails
- Reading full email details
- Sending replies within threads
- Managing labels (auto-replied)
- Searching emails
"""

import base64
import re
from email.mime.text import MIMEText
from typing import Optional

from app.auth.gmail_auth import get_gmail_service
from app.schemas.email_schemas import EmailSummary, EmailDetail
from app.config import settings


class GmailService:
    """Service for interacting with the Gmail API."""

    def __init__(self, credentials_path: str = "credentials.json", token_path: str = "token.json"):
        """
        Initialize Gmail service.

        Args:
            credentials_path: Path to Google OAuth credentials
            token_path: Path to stored OAuth token
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._service = None
        self._auto_reply_label_id = None

    @property
    def service(self):
        """Lazy-load the Gmail API service."""
        if self._service is None:
            self._service = get_gmail_service(self.credentials_path, self.token_path)
        return self._service

    def _get_header(self, headers: list[dict], name: str) -> str:
        """Extract a header value from Gmail message headers."""
        for header in headers:
            if header["name"].lower() == name.lower():
                return header["value"]
        return ""

    def _parse_sender(self, sender_raw: str) -> tuple[str, str]:
        """
        Parse sender string into name and email.

        Args:
            sender_raw: Raw sender string like 'John Doe <john@example.com>'

        Returns:
            Tuple of (name, email)
        """
        match = re.match(r"(.+?)\s*<(.+?)>", sender_raw)
        if match:
            return match.group(1).strip().strip('"'), match.group(2).strip()
        return "", sender_raw.strip()

    def _decode_body(self, payload: dict) -> tuple[str, str]:
        """
        Decode email body from Gmail API payload.

        Handles both simple and multipart messages.

        Returns:
            Tuple of (plain_text_body, html_body)
        """
        plain_body = ""
        html_body = ""

        if "parts" in payload:
            for part in payload["parts"]:
                mime_type = part.get("mimeType", "")
                if mime_type == "text/plain" and "data" in part.get("body", {}):
                    plain_body = base64.urlsafe_b64decode(
                        part["body"]["data"]
                    ).decode("utf-8", errors="replace")
                elif mime_type == "text/html" and "data" in part.get("body", {}):
                    html_body = base64.urlsafe_b64decode(
                        part["body"]["data"]
                    ).decode("utf-8", errors="replace")
                elif "parts" in part:
                    # Nested multipart - recurse
                    sub_plain, sub_html = self._decode_body(part)
                    if not plain_body:
                        plain_body = sub_plain
                    if not html_body:
                        html_body = sub_html
        elif "body" in payload and "data" in payload.get("body", {}):
            body_data = base64.urlsafe_b64decode(
                payload["body"]["data"]
            ).decode("utf-8", errors="replace")
            if payload.get("mimeType") == "text/html":
                html_body = body_data
            else:
                plain_body = body_data

        return plain_body, html_body

    def _fetch_messages(self, query: str, max_results: int) -> list[dict]:
        """
        Fetch raw Gmail messages with automatic pagination up to max_results.

        Args:
            query: Gmail search query string
            max_results: Maximum total results (will paginate automatically)

        Returns:
            List of raw message dicts from Gmail API
        """
        messages = []
        page_token = None
        # Fetch in pages of 100 until we have enough or run out
        per_page = min(100, max_results)

        while len(messages) < max_results:
            kwargs = {"userId": "me", "q": query, "maxResults": per_page}
            if page_token:
                kwargs["pageToken"] = page_token

            results = self.service.users().messages().list(**kwargs).execute()
            batch = results.get("messages", [])
            messages.extend(batch)

            page_token = results.get("nextPageToken")
            if not page_token or not batch:
                break

        return messages[:max_results]

    def _msg_refs_to_summaries(self, msg_refs: list[dict]) -> list:
        """Convert a list of message refs [{id, threadId}] to EmailSummary objects."""
        summaries = []
        for msg_ref in msg_refs:
            try:
                msg = self.service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()

                headers = msg.get("payload", {}).get("headers", [])
                sender_raw = self._get_header(headers, "From")
                sender_name, sender_email = self._parse_sender(sender_raw)

                summaries.append(EmailSummary(
                    id=msg["id"],
                    thread_id=msg["threadId"],
                    sender=sender_email,
                    sender_name=sender_name,
                    subject=self._get_header(headers, "Subject") or "(No Subject)",
                    snippet=msg.get("snippet", ""),
                    date=self._get_header(headers, "Date"),
                    is_unread="UNREAD" in msg.get("labelIds", [])
                ))
            except Exception as e:
                print(f"[WARN] Could not fetch message {msg_ref.get('id')}: {e}")
        return summaries

    def list_unread_emails(self, max_results: int = 100, exclude_auto_replied: bool = True) -> list:
        """
        Fetch ALL unread emails across every Gmail tab/category.

        Uses "-in:spam -in:trash" instead of "in:inbox" so that emails
        in Gmail's Promotions, Social, Updates, and Forums tabs are
        also captured — not just the Primary inbox.

        Args:
            max_results: Maximum number of emails to return (paginated)
            exclude_auto_replied: Whether to exclude emails already auto-replied

        Returns:
            List of EmailSummary objects
        """
        # ✅ Broad query — catches Primary, Promotions, Social, Updates, Forums
        # Old query was "is:unread in:inbox" which MISSED category tab emails
        query = "is:unread -in:spam -in:trash -in:sent"

        if exclude_auto_replied:
            label = self._get_or_create_label()
            if label:
                # Quote label name in case it has special chars
                query += f' -label:"{label}"'

        print(f"[Gmail] Query: {query}")
        msg_refs = self._fetch_messages(query, max_results)
        if not msg_refs:
            return []

        return self._msg_refs_to_summaries(msg_refs)

    def list_recent_emails(self, max_results: int = 100, days: int = 7) -> list:
        """
        Fetch recent emails (read OR unread) for inbox display.

        This is used purely for the dashboard inbox view — it shows all
        recently received emails so the user can see what the agent captured,
        even if those emails were already opened (and thus no longer unread).

        Args:
            max_results: Maximum emails to fetch
            days: How many days back to look

        Returns:
            List of EmailSummary objects
        """
        query = f"in:inbox newer_than:{days}d -in:spam -in:trash -in:sent"
        print(f"[Gmail] Recent query: {query}")
        msg_refs = self._fetch_messages(query, max_results)
        if not msg_refs:
            return []
        return self._msg_refs_to_summaries(msg_refs)

    def get_email_details(self, email_id: str) -> EmailDetail:
        """
        Get full details of a specific email.

        Args:
            email_id: Gmail message ID

        Returns:
            EmailDetail object with full body content
        """
        msg = self.service.users().messages().get(
            userId="me",
            id=email_id,
            format="full"
        ).execute()

        headers = msg.get("payload", {}).get("headers", [])
        sender_raw = self._get_header(headers, "From")
        sender_name, sender_email = self._parse_sender(sender_raw)

        plain_body, html_body = self._decode_body(msg.get("payload", {}))

        return EmailDetail(
            id=msg["id"],
            thread_id=msg["threadId"],
            message_id=self._get_header(headers, "Message-ID"),
            sender=sender_email,
            sender_name=sender_name,
            to=self._get_header(headers, "To"),
            subject=self._get_header(headers, "Subject") or "(No Subject)",
            body=plain_body or html_body,
            html_body=html_body,
            date=self._get_header(headers, "Date"),
            labels=msg.get("labelIds", [])
        )

    def send_reply(self, email_id: str, reply_text: str) -> dict:
        """
        Send a reply to a specific email within the same thread.

        Sets proper headers (In-Reply-To, References) so the reply
        appears in the same Gmail conversation thread.

        Args:
            email_id: Gmail message ID to reply to
            reply_text: The reply text to send

        Returns:
            Gmail API response dict
        """
        # Get the original email details
        original = self.get_email_details(email_id)

        # Build the reply message
        message = MIMEText(reply_text)
        message["to"] = original.sender
        message["from"] = f"{settings.USER_NAME} <{settings.USER_EMAIL}>"
        message["subject"] = f"Re: {original.subject}" if not original.subject.startswith("Re:") else original.subject
        message["In-Reply-To"] = original.message_id
        message["References"] = original.message_id

        # Encode the message
        raw_message = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode("utf-8")

        # Send as reply in the same thread
        sent_message = self.service.users().messages().send(
            userId="me",
            body={
                "raw": raw_message,
                "threadId": original.thread_id
            }
        ).execute()

        # Mark original as auto-replied
        self.mark_as_auto_replied(email_id)

        print(f"[OK] Reply sent to {original.sender} (Subject: {original.subject})")
        return sent_message

    def mark_as_auto_replied(self, email_id: str) -> None:
        """
        Apply the 'auto-replied' label to an email to prevent re-processing.

        Args:
            email_id: Gmail message ID
        """
        label_id = self._get_or_create_label()
        if label_id:
            self.service.users().messages().modify(
                userId="me",
                id=email_id,
                body={
                    "addLabelIds": [label_id],
                    "removeLabelIds": ["UNREAD"]
                }
            ).execute()

    def _get_or_create_label(self, label_name: str = "auto-replied") -> Optional[str]:
        """
        Get or create a Gmail label for tracking auto-replied emails.

        Args:
            label_name: Name of the label to find or create

        Returns:
            Label ID string, or None if creation fails
        """
        if self._auto_reply_label_id:
            return self._auto_reply_label_id

        # Check existing labels
        results = self.service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])

        for label in labels:
            if label["name"].lower() == label_name.lower():
                self._auto_reply_label_id = label["id"]
                return self._auto_reply_label_id

        # Create the label if it doesn't exist
        try:
            label_body = {
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
                "color": {
                    "backgroundColor": "#16a765",
                    "textColor": "#ffffff"
                }
            }
            created_label = self.service.users().labels().create(
                userId="me",
                body=label_body
            ).execute()
            self._auto_reply_label_id = created_label["id"]
            print(f"✅ Created Gmail label: '{label_name}'")
            return self._auto_reply_label_id
        except Exception as e:
            print(f"⚠️ Could not create label '{label_name}': {e}")
            return None

    def search_emails(self, query: str, max_results: int = 10) -> list[EmailSummary]:
        """
        Search emails using Gmail query syntax.

        Args:
            query: Gmail search query (same syntax as Gmail search bar)
            max_results: Maximum number of results

        Returns:
            List of EmailSummary objects matching the query
        """
        results = self.service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return []

        email_summaries = []
        for msg_ref in messages:
            msg = self.service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()

            headers = msg.get("payload", {}).get("headers", [])
            sender_raw = self._get_header(headers, "From")
            sender_name, sender_email = self._parse_sender(sender_raw)

            email_summaries.append(EmailSummary(
                id=msg["id"],
                thread_id=msg["threadId"],
                sender=sender_email,
                sender_name=sender_name,
                subject=self._get_header(headers, "Subject") or "(No Subject)",
                snippet=msg.get("snippet", ""),
                date=self._get_header(headers, "Date"),
                is_unread="UNREAD" in msg.get("labelIds", [])
            ))

        return email_summaries

    def is_connected(self) -> bool:
        """Check if Gmail API is connected and authenticated."""
        try:
            self.service.users().getProfile(userId="me").execute()
            return True
        except Exception:
            return False


# Singleton instance
_gmail_service = None


def get_gmail_service_instance(credentials_path: str = "credentials.json", token_path: str = "token.json") -> GmailService:
    """Get singleton GmailService instance."""
    global _gmail_service
    if _gmail_service is None:
        _gmail_service = GmailService(credentials_path, token_path)
    return _gmail_service
