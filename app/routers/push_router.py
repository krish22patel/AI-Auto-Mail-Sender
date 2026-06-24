"""
Gmail Push Notification Webhook Router.

Exposes POST /webhook/gmail — the endpoint that Google Cloud Pub/Sub calls
(via HTTP push delivery) the moment Gmail detects a new message in the
watched mailbox.

Flow
----
1. Google Pub/Sub POSTs a JSON envelope to this endpoint.
2. We decode the envelope to extract the new historyId.
3. We call Gmail's history.list() to get the actual message IDs that arrived
   since the last processed historyId.
4. We filter messages (whitelist, skip-patterns, already-replied).
5. Qualifying message IDs are placed on the shared asyncio.Queue.
6. The queue consumer worker (worker.py) wakes up and processes them.
7. We return HTTP 200 immediately so Pub/Sub knows delivery succeeded.

Why return 200 fast?
--------------------
If this endpoint takes too long or returns a non-2xx status, Pub/Sub will
re-deliver the notification — causing duplicate processing.  We do all heavy
work asynchronously via the queue, returning 200 in < 1 second.

Security Note
-------------
For production, validate the Google OIDC bearer token in the Authorization
header.  For development (local + ngrok), the token check is optional since
the URL is not publicly discoverable.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Request, Response, HTTPException

from app import db
from app.config import settings
from app.services import gmail_push
from app.worker import (
    SKIP_KEYWORDS,
    is_whitelisted,
    get_email_queue,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])


# ---------------------------------------------------------------------------
# POST /webhook/gmail
# ---------------------------------------------------------------------------

@router.post("/webhook/gmail", status_code=200)
async def gmail_push_webhook(request: Request):
    """
    Receive a Gmail Pub/Sub push notification.

    Called by Google Cloud Pub/Sub when Gmail detects inbox changes.
    Decodes the notification, fetches new message IDs via the History API,
    filters them, and enqueues qualifying messages for async processing.

    Returns HTTP 200 in all cases so Pub/Sub marks delivery as successful.
    Errors are logged internally — we never want Pub/Sub to keep retrying
    with a bad historyId.
    """
    raw_body = await request.body()

    # --- Parse Pub/Sub envelope ---
    notification = gmail_push.parse_push_notification(raw_body)
    if not notification:
        logger.warning("[Webhook] Could not parse Pub/Sub notification — ignoring.")
        # Return 200 so Pub/Sub doesn't retry indefinitely
        return Response(status_code=200)

    new_history_id: int = notification["history_id"]
    logger.info("[Webhook] Received Pub/Sub notification historyId=%s", new_history_id)

    # --- Fetch new message IDs via History API (async, non-blocking) ---
    asyncio.create_task(
        _handle_new_messages(new_history_id)
    )

    # Return 200 immediately — actual processing is async
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Internal async handler (runs as background task)
# ---------------------------------------------------------------------------

async def _handle_new_messages(new_history_id: int) -> None:
    """
    Background task: fetch and enqueue new emails from the Gmail History API.

    Parameters
    ----------
    new_history_id : historyId from the Pub/Sub notification
    """
    try:
        # Retrieve the last processed historyId from DB
        last_history_id = await asyncio.to_thread(db.get_last_history_id)

        if not last_history_id:
            # First-ever notification after watch registration — treat as
            # a signal to do the startup catch-up fetch (already done at boot).
            logger.info(
                "[Webhook] No prior historyId in DB. "
                "Updating checkpoint to %s and skipping fetch.",
                new_history_id,
            )
            await asyncio.to_thread(db.set_last_history_id, new_history_id)
            return

        if new_history_id <= last_history_id:
            logger.info(
                "[Webhook] historyId %s <= last known %s — duplicate or stale, skipping.",
                new_history_id,
                last_history_id,
            )
            return

        # Import here to avoid circular imports at module load time
        from app.services.gmail_service import get_gmail_service_instance
        gmail_service = get_gmail_service_instance(
            credentials_path=settings.GMAIL_CREDENTIALS_PATH,
            token_path=settings.GMAIL_TOKEN_PATH,
        )

        # Fetch new message IDs from the Gmail History API
        new_msg_ids: list[str] = await asyncio.to_thread(
            gmail_push.fetch_new_message_ids,
            gmail_service.service,
            last_history_id,
            new_history_id,
        )

        logger.info(
            "[Webhook] History API returned %d new message(s) for historyId range [%s, %s].",
            len(new_msg_ids),
            last_history_id,
            new_history_id,
        )

        # --- Persist the new historyId checkpoint immediately ---
        # Even if processing fails, we don't want to re-process the same IDs.
        await asyncio.to_thread(db.set_last_history_id, new_history_id)

        if not new_msg_ids:
            return

        # --- Filter, capture, and optionally enqueue ---
        is_on = await asyncio.to_thread(db.is_service_on)
        queue = get_email_queue()
        enqueued = 0
        captured = 0

        for msg_id in new_msg_ids:
            # Fetch minimal metadata for filtering and database capture
            try:
                msg_meta = await asyncio.to_thread(
                    gmail_service.get_email_metadata, msg_id
                )
            except Exception as e:
                logger.warning("[Webhook] Could not fetch metadata for %s: %s", msg_id, e)
                continue

            sender = msg_meta.get("sender", "")
            subject = msg_meta.get("subject", "")

            # Capture in DB inbox_emails immediately so it shows in the dashboard
            try:
                await asyncio.to_thread(
                    db.capture_inbox_email,
                    message_id=msg_id,
                    sender=sender,
                    sender_name=msg_meta.get("sender_name", ""),
                    subject=subject,
                    snippet=msg_meta.get("snippet", ""),
                    date=msg_meta.get("date", ""),
                )
                captured += 1
            except Exception as e:
                logger.error("[Webhook] Failed to capture inbox email %s in DB: %s", msg_id, e)

            # If auto-reply is OFF, skip processing but keep email recorded in DB
            if not is_on:
                logger.info("[Webhook] Auto-reply is OFF — captured %s but skipping enqueue.", msg_id)
                continue

            # Skip automated / newsletter senders
            if any(kw in sender.lower() for kw in SKIP_KEYWORDS):
                logger.debug("[Webhook] Skipping automated sender: %s", sender)
                continue

            # Skip non-whitelisted domains
            if not is_whitelisted(sender, settings.ALLOWED_DOMAINS):
                logger.debug("[Webhook] Skipping non-whitelisted sender: %s", sender)
                continue

            # Skip already-replied emails
            is_replied = await asyncio.to_thread(db.is_already_replied, msg_id)
            if is_replied:
                logger.debug("[Webhook] Already replied to %s — skipping.", msg_id)
                continue

            await queue.put(msg_id)
            enqueued += 1
            logger.info("[Webhook] Enqueued message %s (%s | %s)", msg_id, sender, subject)

        logger.info(
            "[Webhook] Done. Captured %d emails. Enqueued %d/%d for processing (Service is %s).",
            captured,
            enqueued,
            len(new_msg_ids),
            "ON" if is_on else "OFF",
        )

    except Exception as e:
        logger.error("[Webhook] Error handling new messages: %s", e, exc_info=True)
