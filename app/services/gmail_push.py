"""
Gmail Push Notification Service.

Replaces the polling loop with an interrupt-driven Gmail Push architecture:

  Gmail → Google Cloud Pub/Sub → POST /webhook/gmail → asyncio.Queue

Key responsibilities
--------------------
1. register_gmail_watch()       — Tell Gmail to push events to our Pub/Sub topic.
2. parse_push_notification()    — Decode the base64 Pub/Sub envelope.
3. fetch_new_emails_from_history() — Use Gmail History API to get the actual
                                     new message IDs since the last known historyId.

Why History API?
----------------
A Pub/Sub notification only carries a historyId (opaque checkpoint), not the
full message.  We call history.list() from the last stored historyId to the
new one — this gives us *exactly* which messages arrived, even if multiple
notifications were batched or missed (e.g. during a restart).  This ensures
ZERO data loss.

Gmail watch expiry
------------------
Gmail push subscriptions expire after exactly 7 days.  The worker calls
register_gmail_watch() on startup and the watch-renewal background task
(in worker.py) renews it every GMAIL_WATCH_RENEWAL_HOURS (default 23 h).
"""

import base64
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Watch Registration
# ---------------------------------------------------------------------------

def register_gmail_watch(gmail_api_service, pubsub_topic: str) -> dict:
    """
    Register (or renew) a Gmail push-notification watch.

    Tells Gmail to POST Pub/Sub messages to *pubsub_topic* whenever the
    user's inbox changes (new message, label change, etc.).

    Parameters
    ----------
    gmail_api_service : Authenticated Gmail API resource object
                        (returned by googleapiclient.discovery.build)
    pubsub_topic      : Full Pub/Sub topic resource name, e.g.
                        'projects/my-project/topics/gmail-push'

    Returns
    -------
    dict : Gmail watch response containing 'historyId' and 'expiration' (ms).

    Raises
    ------
    Exception : If the Pub/Sub topic is empty or the Gmail API call fails.
    """
    if not pubsub_topic:
        raise Exception(
            "PUBSUB_TOPIC is not configured! "
            "See PUSH_SETUP.md for one-time GCP setup steps."
        )

    watch_request = {
        "labelIds": ["INBOX"],          # Only watch the INBOX label
        "topicName": pubsub_topic,
        "labelFilterBehavior": "INCLUDE",
    }

    from app.services.gmail_service import execute_with_retry
    response = execute_with_retry(
        gmail_api_service.users()
        .watch(userId="me", body=watch_request)
    )

    history_id = response.get("historyId")
    expiration_ms = response.get("expiration", 0)
    expiration_s = int(expiration_ms) // 1000 if expiration_ms else 0

    logger.info(
        "[GmailPush] Watch registered. historyId=%s  expires_at_unix=%s",
        history_id,
        expiration_s,
    )
    return response


# ---------------------------------------------------------------------------
# Pub/Sub Notification Parsing
# ---------------------------------------------------------------------------

def parse_push_notification(raw_body: bytes) -> Optional[dict]:
    """
    Decode a Google Cloud Pub/Sub push notification envelope.

    Pub/Sub wraps the Gmail notification in a JSON envelope:
    {
      "message": {
        "data": "<base64-encoded JSON>",
        "messageId": "...",
        "publishTime": "..."
      },
      "subscription": "projects/.../subscriptions/..."
    }

    The inner JSON (after base64 decode) looks like:
    { "emailAddress": "user@gmail.com", "historyId": 12345 }

    Parameters
    ----------
    raw_body : Raw HTTP request body bytes from the Pub/Sub push.

    Returns
    -------
    dict with keys 'email_address' and 'history_id', or None on parse error.
    """
    try:
        envelope = json.loads(raw_body.decode("utf-8"))
        message = envelope.get("message", {})
        data_b64 = message.get("data", "")
        if not data_b64:
            logger.warning("[GmailPush] Pub/Sub message has no 'data' field.")
            return None

        # Add padding in case base64 string is not a multiple of 4
        padded = data_b64 + "==" * (4 - len(data_b64) % 4)
        inner = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))

        email_address = inner.get("emailAddress", "")
        history_id = inner.get("historyId")

        if not history_id:
            logger.warning("[GmailPush] Parsed notification has no historyId.")
            return None

        logger.debug(
            "[GmailPush] Notification: email=%s historyId=%s",
            email_address,
            history_id,
        )
        return {"email_address": email_address, "history_id": int(history_id)}

    except (json.JSONDecodeError, UnicodeDecodeError, Exception) as e:
        logger.error("[GmailPush] Failed to parse Pub/Sub notification: %s", e)
        return None


# ---------------------------------------------------------------------------
# History-based new-message fetch
# ---------------------------------------------------------------------------

def fetch_new_message_ids(
    gmail_api_service,
    start_history_id: int,
    end_history_id: int,
) -> list[str]:
    """
    Retrieve message IDs for emails that arrived between two historyIds.

    Uses the Gmail History API (history.list) which is guaranteed to return
    every MESSAGES_ADDED event since *start_history_id*, even if multiple
    Pub/Sub notifications were merged or missed during a server restart.

    Parameters
    ----------
    gmail_api_service : Authenticated Gmail API resource object
    start_history_id  : Last processed historyId (exclusive lower bound)
    end_history_id    : New historyId from the Pub/Sub notification (unused
                        by the API directly; kept for logging / idempotency)

    Returns
    -------
    list[str] : Deduplicated list of Gmail message IDs for new messages.

    Notes
    -----
    - Only INBOX messages are returned (labelId filter).
    - If start_history_id is 0 or None the caller should do a full unread
      fetch instead (startup catch-up path).
    """
    if not start_history_id:
        logger.info("[GmailPush] No start historyId — skipping history fetch.")
        return []

    message_ids: list[str] = []
    page_token = None

    try:
        while True:
            kwargs: dict = {
                "userId": "me",
                "startHistoryId": str(start_history_id),
                "historyTypes": ["messageAdded"],
                "labelId": "INBOX",
            }
            if page_token:
                kwargs["pageToken"] = page_token

            from app.services.gmail_service import execute_with_retry
            result = execute_with_retry(
                gmail_api_service.users().history().list(**kwargs)
            )
            history_records = result.get("history", [])

            for record in history_records:
                for msg_added in record.get("messagesAdded", []):
                    msg = msg_added.get("message", {})
                    msg_id = msg.get("id")
                    labels = msg.get("labelIds", [])
                    # Only INBOX + UNREAD messages need auto-reply
                    if msg_id and "INBOX" in labels and "UNREAD" in labels:
                        if msg_id not in message_ids:
                            message_ids.append(msg_id)

            page_token = result.get("nextPageToken")
            if not page_token:
                break

    except Exception as e:
        # historyId too old (410 Gone) means the watch was re-registered
        # or the server was offline too long.  Fall back to full unread fetch.
        if "historyId is too old" in str(e) or "404" in str(e) or "410" in str(e):
            logger.warning(
                "[GmailPush] historyId %s is too old or invalid (%s). "
                "Caller should do a full unread fetch.",
                start_history_id,
                e,
            )
            return []
        logger.error("[GmailPush] history.list() error: %s", e)
        raise

    logger.info(
        "[GmailPush] History %s→%s yielded %d new INBOX+UNREAD message IDs.",
        start_history_id,
        end_history_id,
        len(message_ids),
    )
    return message_ids
