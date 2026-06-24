import sys
from pathlib import Path

# Add the project root directory to sys.path to enable app module imports
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from fastmcp import FastMCP
from app.services.gmail_service import get_gmail_service_instance
from app.services.ai_service import get_ai_service
from app.config import settings
from app import db

# Initialize the MCP server
mcp = FastMCP("AI Email Agent")


@mcp.tool()
def list_unread_emails(max_results: int = 10) -> str:
    """
    List unread emails from the inbox.

    Args:
        max_results: Maximum number of unread emails to retrieve.
    """
    try:
        gmail_service = get_gmail_service_instance(
            credentials_path=settings.GMAIL_CREDENTIALS_PATH,
            token_path=settings.GMAIL_TOKEN_PATH
        )
        # Check Gmail connection
        if not gmail_service.is_connected():
            return "❌ Gmail API is not authenticated. Please complete the OAuth flow by starting the FastAPI server first."

        emails = gmail_service.list_unread_emails(max_results=max_results, exclude_auto_replied=True)
        if not emails:
            return "No unread emails found."

        result = []
        for email in emails:
            result.append(
                f"ID: {email.id}\n"
                f"From: {email.sender_name} <{email.sender}>\n"
                f"Subject: {email.subject}\n"
                f"Snippet: {email.snippet}\n"
                f"---"
            )
        return "\n".join(result)
    except Exception as e:
        return f"Error listing unread emails: {str(e)}"


@mcp.tool()
def get_email_details(email_id: str) -> str:
    """
    Retrieve full body content and headers of a specific email.

    Args:
        email_id: The Gmail message ID.
    """
    try:
        gmail_service = get_gmail_service_instance(
            credentials_path=settings.GMAIL_CREDENTIALS_PATH,
            token_path=settings.GMAIL_TOKEN_PATH
        )
        if not gmail_service.is_connected():
            return "❌ Gmail API is not authenticated."

        details = gmail_service.get_email_details(email_id)
        return (
            f"ID: {details.id}\n"
            f"Thread ID: {details.thread_id}\n"
            f"From: {details.sender_name} <{details.sender}>\n"
            f"To: {details.to}\n"
            f"Subject: {details.subject}\n"
            f"Date: {details.date}\n\n"
            f"Body:\n{details.body}"
        )
    except Exception as e:
        return f"Error retrieving email details: {str(e)}"


@mcp.tool()
def reply_to_email(email_id: str, reply_text: str) -> str:
    """
    Send a reply to a specific email by thread ID.

    Args:
        email_id: The Gmail message ID to reply to.
        reply_text: The plain text body of the reply message.
    """
    try:
        gmail_service = get_gmail_service_instance(
            credentials_path=settings.GMAIL_CREDENTIALS_PATH,
            token_path=settings.GMAIL_TOKEN_PATH
        )
        if not gmail_service.is_connected():
            return "❌ Gmail API is not authenticated."

        gmail_service.send_reply(email_id, reply_text)
        return f"✅ Successfully sent reply to email ID: {email_id}"
    except Exception as e:
        return f"Error sending email reply: {str(e)}"


@mcp.tool()
def search_emails(query: str, max_results: int = 10) -> str:
    """
    Search Gmail using standard Gmail query syntax (e.g. 'from:boss newer_than:2d').

    Args:
        query: Gmail search query string.
        max_results: Maximum matching emails to retrieve.
    """
    try:
        gmail_service = get_gmail_service_instance(
            credentials_path=settings.GMAIL_CREDENTIALS_PATH,
            token_path=settings.GMAIL_TOKEN_PATH
        )
        if not gmail_service.is_connected():
            return "❌ Gmail API is not authenticated."

        emails = gmail_service.search_emails(query, max_results=max_results)
        if not emails:
            return f"No emails found matching query: '{query}'."

        result = []
        for email in emails:
            result.append(
                f"ID: {email.id}\n"
                f"From: {email.sender_name} <{email.sender}>\n"
                f"Subject: {email.subject}\n"
                f"Snippet: {email.snippet}\n"
                f"---"
            )
        return "\n".join(result)
    except Exception as e:
        return f"Error searching emails: {str(e)}"


@mcp.tool()
def auto_reply_all() -> str:
    """
    Process all unread emails, filter automated senders, and automatically reply using Claude or Ollama.
    """
    try:
        db.init_db()
        gmail_service = get_gmail_service_instance(
            credentials_path=settings.GMAIL_CREDENTIALS_PATH,
            token_path=settings.GMAIL_TOKEN_PATH
        )
        if not gmail_service.is_connected():
            return "❌ Gmail API is not authenticated. Please complete the OAuth flow first."

        ai_service = get_ai_service(
            provider=settings.AI_PROVIDER,
            model=settings.CLAUDE_MODEL if settings.AI_PROVIDER == "claude" else settings.OLLAMA_MODEL,
            tone=settings.REPLY_TONE,
            ollama_url=settings.OLLAMA_URL,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            user_name=settings.USER_NAME,
            user_email=settings.USER_EMAIL
        )

        unread_emails = gmail_service.list_unread_emails(200, exclude_auto_replied=True)
        if not unread_emails:
            return "No pending unread emails to reply to."

        from app.worker import SKIP_KEYWORDS, is_whitelisted

        replied_count = 0
        skipped_count = 0

        for email in unread_emails:
            sender_lower = email.sender.lower()

            # Skip automated senders
            if any(kw in sender_lower for kw in SKIP_KEYWORDS):
                skipped_count += 1
                continue

            # Check whitelist
            if not is_whitelisted(email.sender, settings.ALLOWED_DOMAINS):
                skipped_count += 1
                continue

            # Check if already replied
            if db.is_already_replied(email.id):
                continue

            # Fetch details and generate reply
            email_detail = gmail_service.get_email_details(email.id)
            body_text = email_detail.body or email.snippet or "(No body)"

            reply_body = ai_service.generate_reply(
                sender=email.sender,
                sender_name=email.sender_name or email.sender,
                subject=email.subject,
                body=body_text
            )

            # Send reply
            gmail_service.send_reply(email.id, reply_body)

            # Log to DB
            db.log_email(
                message_id=email.id,
                sender=email.sender,
                subject=email.subject,
                reply_body=reply_body
            )
            db.mark_inbox_email_replied(email.id)
            replied_count += 1

        return f"✅ Auto-reply scan complete. Processed {len(unread_emails)} emails. Sent {replied_count} replies, skipped {skipped_count}."
    except Exception as e:
        return f"Error executing auto_reply_all: {str(e)}"


if __name__ == "__main__":
    mcp.run()
