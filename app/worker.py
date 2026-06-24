"""
Background Worker — Interrupt-Driven Queue Consumer.

Architecture: NO POLLING.  Emails are enqueued by two sources:
  1. Gmail Push Webhook (push_router.py) — near-real-time (~1 s latency)
  2. Startup catch-up fetch                — processes any emails that arrived
                                             while the server was offline

Processing pipeline
-------------------
email_id (str)  →  asyncio.Queue
                         ↓
               consume_worker() picks up IDs
                         ↓
        get_email_details()  (Gmail API, thread pool)
                         ↓
        generate_reply()     (HuggingFace Router, thread pool)
                         ↓
        send_reply()         (Gmail API, thread pool)
                         ↓
        log_email() + mark_replied() (SQLite, thread pool)

Why asyncio.Queue?
------------------
- The queue consumer blocks on `await queue.get()` — zero CPU usage when idle.
- MAX_WORKERS concurrent tasks are allowed via asyncio.Semaphore.
- Duplicate-safe: `is_already_replied()` check before processing.
- Restart-safe: historyId is persisted in DB; startup catch-up covers gaps.

Watch renewal
-------------
Gmail Push subscriptions expire every 7 days.  `_watch_renewal_loop()` renews
them every GMAIL_WATCH_RENEWAL_HOURS (default 23 h) so the watch never lapses.
"""

import asyncio
import logging
import traceback
import datetime

from app import db
from app.config import settings
from app.services.gmail_service import get_gmail_service_instance
from app.services.ai_service import AIService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skip-sender keywords (automated / bulk senders that should never get replies)
# ---------------------------------------------------------------------------
SKIP_KEYWORDS = [
    "noreply", "no-reply", "newsletter", "updates@",
    "notification", "donotreply", "mailer-daemon",
    "alerts@", "alert@",
]

# ---------------------------------------------------------------------------
# Global state (read by email_router.py for the dashboard)
# ---------------------------------------------------------------------------

# Task-level activity log (shown on dashboard)
processing_queue: list[dict] = []

# Per-worker slot status (shown on dashboard)
worker_status: list[dict] = []

# Semaphore limiting concurrent email tasks
worker_semaphore: asyncio.Semaphore | None = None

# System connection status
system_status: dict = {
    "gmail_connected": False,
    "ai_connected": False,
    "last_check": None,
    "error_message": None,
}

# The shared email-ID queue (interrupt-driven)
_email_queue: asyncio.Queue | None = None


def get_email_queue() -> asyncio.Queue:
    """
    Return the global email-ID queue.

    Created lazily on first call so it belongs to the running event loop.
    Used by push_router.py to enqueue new message IDs, and consumed here.
    """
    global _email_queue
    if _email_queue is None:
        _email_queue = asyncio.Queue()
    return _email_queue


# ---------------------------------------------------------------------------
# Domain / whitelist helper
# ---------------------------------------------------------------------------

def is_whitelisted(email: str, allowed_str: str) -> bool:
    """
    Check whether *email* matches any entry in the comma-separated *allowed_str*.

    Matching rules
    --------------
    - '@domain.com' → any address ending in '@domain.com'
    - 'domain.com'  → same as above (adds '@' prefix automatically)
    - 'user@domain' → exact full-address match
    """
    email_lower = email.lower().strip()
    allowed_items = [item.strip().lower() for item in allowed_str.split(",") if item.strip()]

    for item in allowed_items:
        if not item:
            continue
        if item.startswith("@"):
            if email_lower.endswith(item):
                return True
        elif "@" in item:
            if email_lower == item:
                return True
        else:
            if email_lower.endswith("@" + item) or email_lower.endswith("." + item):
                return True
    return False


# ---------------------------------------------------------------------------
# Single-email processing task
# ---------------------------------------------------------------------------

async def process_email_task(
    msg_id: str,
    ai_service: AIService,
    gmail_service,
) -> None:
    """
    Process one email end-to-end:  fetch → generate reply → send → log.

    Parameters
    ----------
    msg_id        : Gmail message ID string
    ai_service    : Initialised AIService instance
    gmail_service : Initialised GmailService instance
    """
    task_info = {
        "id": msg_id,
        "sender": "loading…",
        "sender_name": "",
        "subject": "loading…",
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    processing_queue.append(task_info)

    slot = None
    try:
        async with worker_semaphore:
            # Check if service was toggled OFF while waiting for semaphore
            if not await asyncio.to_thread(db.is_service_on):
                logger.info("[WORKER] Service is OFF — aborting processing for message %s.", msg_id)
                return

            # Claim a worker slot for dashboard display
            slot = next((s for s in worker_status if s["status"] == "Idle"), None)
            if slot:
                slot["status"] = "Active"
                slot["task"] = {"sender": "…", "subject": "…", "step": "Reading details"}

            # -- 1. Fetch full email details --
            email_detail = await asyncio.to_thread(gmail_service.get_email_details, msg_id)

            # Check if service was toggled OFF while fetching details
            if not await asyncio.to_thread(db.is_service_on):
                logger.info("[WORKER] Service was toggled OFF — aborting processing for message %s.", msg_id)
                return

            task_info["sender"] = email_detail.sender
            task_info["sender_name"] = email_detail.sender_name or email_detail.sender
            task_info["subject"] = email_detail.subject
            if slot:
                slot["task"]["sender"] = email_detail.sender
                slot["task"]["subject"] = email_detail.subject

            body_text = email_detail.body or "(No body)"

            logger.info(
                "[WORKER] Generating reply for: %s | %s",
                email_detail.sender,
                email_detail.subject,
            )

            # -- 2. Generate AI reply --
            if slot:
                slot["task"]["step"] = "AI generating reply"
            reply_body = await asyncio.to_thread(
                ai_service.generate_reply,
                sender=email_detail.sender,
                sender_name=email_detail.sender_name or email_detail.sender,
                subject=email_detail.subject,
                body=body_text,
            )

            # Check if service was toggled OFF while generating reply
            if not await asyncio.to_thread(db.is_service_on):
                logger.info("[WORKER] Service was toggled OFF — aborting reply sending for message %s.", msg_id)
                return

            # -- 3. Send reply --
            if slot:
                slot["task"]["step"] = "Sending email reply"
            await asyncio.to_thread(gmail_service.send_reply, msg_id, reply_body)

            # -- 4. Persist to database --
            if slot:
                slot["task"]["step"] = "Logging to database"
            await asyncio.to_thread(
                db.log_email,
                message_id=msg_id,
                sender=email_detail.sender,
                subject=email_detail.subject,
                reply_body=reply_body,
            )
            await asyncio.to_thread(db.mark_inbox_email_replied, msg_id)

            logger.info(
                "[WORKER] ✅ Auto-replied to %s — %s",
                email_detail.sender,
                email_detail.subject,
            )

    except Exception:
        err = traceback.format_exc()
        logger.error("[WORKER] ❌ Failed to process message %s:\n%s", msg_id, err)
        try:
            with open("worker_crash.txt", "a", encoding="utf-8") as f:
                f.write(f"\n--- {datetime.datetime.now().isoformat()} ---\n{err}")
        except OSError:
            pass

    finally:
        if slot:
            slot["status"] = "Idle"
            slot["task"] = None
        if task_info in processing_queue:
            processing_queue.remove(task_info)


# ---------------------------------------------------------------------------
# Queue consumer  (replaces the old polling while-True loop)
# ---------------------------------------------------------------------------

async def _consume_queue(ai_service: AIService, gmail_service) -> None:
    """
    Continuously consume message IDs from the email queue.

    Blocks on `await queue.get()` — zero CPU when there's nothing to do.
    Spawns `process_email_task` as a fire-and-forget task, gated by the
    semaphore inside `process_email_task`, so MAX_WORKERS tasks run in
    parallel at most.
    """
    queue = get_email_queue()
    logger.info("[WORKER] Queue consumer started — waiting for interrupt-driven events.")

    while True:
        msg_id: str = await queue.get()
        logger.info("[WORKER] Dequeued message ID: %s", msg_id)

        # Double-check: skip if already replied (e.g. duplicate Pub/Sub delivery)
        is_replied = await asyncio.to_thread(db.is_already_replied, msg_id)
        if is_replied:
            logger.info("[WORKER] Message %s already replied — skipping.", msg_id)
            queue.task_done()
            continue

        # Spawn task (does not block the consumer loop)
        asyncio.create_task(
            _process_and_done(msg_id, ai_service, gmail_service, queue)
        )


async def _process_and_done(
    msg_id: str,
    ai_service: AIService,
    gmail_service,
    queue: asyncio.Queue,
) -> None:
    """Wrapper to call task_done() after processing regardless of outcome."""
    try:
        await process_email_task(msg_id, ai_service, gmail_service)
    finally:
        queue.task_done()


# ---------------------------------------------------------------------------
# Startup catch-up fetch
# ---------------------------------------------------------------------------

async def _startup_catchup(ai_service: AIService, gmail_service) -> None:
    """
    On startup or toggle ON, fetch any unread emails that arrived within
    the active service interval, and enqueue them for processing.
    """
    logger.info(
        "[WORKER] Running catch-up fetch (max %d emails)…",
        settings.STARTUP_CATCHUP_LIMIT,
    )

    try:
        is_on = await asyncio.to_thread(db.is_service_on)
        if not is_on:
            logger.info("[WORKER] Service is OFF — skipping catch-up fetch.")
            await asyncio.to_thread(db.set_pending_count, 0)
            return

        start_time_str = await asyncio.to_thread(db.get_service_start_time)
        start_dt = None
        if start_time_str:
            start_dt = datetime.datetime.fromisoformat(start_time_str)

        unread_emails = await asyncio.to_thread(
            gmail_service.list_unread_emails,
            settings.STARTUP_CATCHUP_LIMIT,
        )

        queue = get_email_queue()
        enqueued = 0
        captured = 0

        for email in unread_emails:
            # Check email date. Only allow emails received on or after service_start_time.
            if start_dt and email.date:
                import email.utils
                try:
                    email_dt = email.utils.parsedate_to_datetime(email.date)
                    if email_dt < start_dt:
                        # Skip emails before the start time
                        continue
                except Exception as e:
                    logger.warning("[WORKER] Catch-up failed to parse email date %s: %s", email.date, e)

            sender_lower = email.sender.lower()

            if any(kw in sender_lower for kw in SKIP_KEYWORDS):
                continue
            if not is_whitelisted(email.sender, settings.ALLOWED_DOMAINS):
                continue

            is_replied = await asyncio.to_thread(db.is_already_replied, email.id)
            if is_replied:
                continue

            # Capture in dashboard database immediately
            try:
                await asyncio.to_thread(
                    db.capture_inbox_email,
                    message_id=email.id,
                    sender=email.sender,
                    sender_name=email.sender_name,
                    subject=email.subject,
                    snippet=email.snippet,
                    date=email.date,
                )
                captured += 1
            except Exception as e:
                logger.error("[WORKER] Catch-up failed to capture email %s: %s", email.id, e)

            await queue.put(email.id)
            enqueued += 1

        await asyncio.to_thread(db.set_pending_count, enqueued)

        logger.info(
            "[WORKER] Catch-up complete: %d unread emails found, %d captured in DB, %d enqueued for reply.",
            len(unread_emails),
            captured,
            enqueued,
        )

    except Exception:
        logger.error("[WORKER] Catch-up failed:\n%s", traceback.format_exc())


# ---------------------------------------------------------------------------
# Gmail Watch renewal loop
# ---------------------------------------------------------------------------

async def _watch_renewal_loop(gmail_service) -> None:
    """
    Renew the Gmail push watch subscription periodically.

    Gmail push subscriptions expire after exactly 7 days.  This coroutine
    sleeps for GMAIL_WATCH_RENEWAL_HOURS hours between renewals, ensuring
    the watch never lapses and Pub/Sub push continues uninterrupted.
    """
    from app.services.gmail_push import register_gmail_watch

    renewal_interval = settings.GMAIL_WATCH_RENEWAL_HOURS * 3600  # hours → seconds

    while True:
        await asyncio.sleep(renewal_interval)
        try:
            response = await asyncio.to_thread(
                register_gmail_watch,
                gmail_service.service,
                settings.PUBSUB_TOPIC,
            )
            logger.info(
                "[WORKER] Gmail watch renewed. historyId=%s",
                response.get("historyId"),
            )
        except Exception as e:
            logger.error("[WORKER] Failed to renew Gmail watch: %s", e)


# ---------------------------------------------------------------------------
# Status health check loop
# ---------------------------------------------------------------------------

async def _status_check_loop(ai_service: AIService, gmail_service) -> None:
    """
    Periodically update the system_status dict (used by the dashboard API).
    Runs every 60 seconds — lightweight, no email processing.
    """
    while True:
        try:
            gmail_conn = await asyncio.to_thread(gmail_service.is_connected)
            ai_conn = await asyncio.to_thread(ai_service.is_connected)
            system_status["gmail_connected"] = gmail_conn
            system_status["ai_connected"] = ai_conn
            system_status["last_check"] = datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat()
            if not gmail_conn:
                system_status["error_message"] = "Gmail API is disconnected. Please verify your credentials/token.json."
            elif not ai_conn:
                system_status["error_message"] = getattr(ai_service, "last_error", "AI service is disconnected.")
            else:
                system_status["error_message"] = None
        except Exception as e:
            system_status["error_message"] = str(e)

        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Main entry point  (called by app/main.py lifespan)
# ---------------------------------------------------------------------------

async def auto_reply_worker() -> None:
    """
    Start all background coroutines for the AI email agent.

    Called once at FastAPI startup from the lifespan context manager.
    Spawns three long-running tasks:
      1. _consume_queue()        — interrupt-driven email processing
      2. _watch_renewal_loop()   — keeps Gmail push subscription alive
      3. _status_check_loop()    — updates health-check metrics

    Also performs a one-time startup catch-up fetch before starting consumers.
    """
    global worker_semaphore, worker_status

    logger.info("=" * 60)
    logger.info("[WORKER] AI Email Agent — Background Worker Starting")
    logger.info("[WORKER] Mode: Interrupt-Driven (Gmail Push Notifications)")
    logger.info("[WORKER] AI Provider: %s | Model: %s", settings.AI_PROVIDER, settings.HF_MODEL)
    logger.info("=" * 60)

    db.init_db()

    # Initialise worker slot tracker
    worker_status.clear()
    worker_status.extend(
        [{"id": i + 1, "status": "Idle", "task": None} for i in range(settings.MAX_WORKERS)]
    )

    # Semaphore limits concurrent email tasks
    worker_semaphore = asyncio.Semaphore(settings.MAX_WORKERS)

    # Build AI service from settings
    ai_service = AIService(
        provider=settings.AI_PROVIDER,
        model=(
            settings.HF_MODEL
            if settings.AI_PROVIDER == "huggingface"
            else settings.CLAUDE_MODEL
        ),
        tone=settings.REPLY_TONE,
        hf_token=settings.HF_TOKEN,
        hf_api_url=settings.HF_API_URL,
        hf_max_retries=settings.HF_MAX_RETRIES,
        hf_retry_delay=settings.HF_RETRY_DELAY,
        hf_timeout=settings.HF_TIMEOUT,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        user_name=settings.USER_NAME,
        user_email=settings.USER_EMAIL,
    )

    gmail_service = get_gmail_service_instance(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        token_path=settings.GMAIL_TOKEN_PATH,
    )

    # --- Initial connection checks ---
    try:
        gmail_conn = await asyncio.to_thread(gmail_service.is_connected)
        system_status["gmail_connected"] = gmail_conn
        if not gmail_conn:
            system_status["error_message"] = (
                "Gmail API is not authenticated. "
                "Complete the OAuth flow by opening the app in a browser first."
            )
            logger.warning("[WORKER] Gmail not connected at startup. Continuing anyway.")
    except Exception as e:
        system_status["error_message"] = str(e)
        logger.error("[WORKER] Gmail connection check failed: %s", e)

    # --- Startup catch-up: process emails that arrived while offline ---
    await _startup_catchup(ai_service, gmail_service)

    # --- Register Gmail watch (tells Gmail to push to our Pub/Sub topic) ---
    if settings.PUBSUB_TOPIC and settings.WEBHOOK_BASE_URL:
        try:
            response = await asyncio.to_thread(
                __import__(
                    "app.services.gmail_push", fromlist=["register_gmail_watch"]
                ).register_gmail_watch,
                gmail_service.service,
                settings.PUBSUB_TOPIC,
            )
            initial_history_id = response.get("historyId")
            if initial_history_id:
                last_known = await asyncio.to_thread(db.get_last_history_id)
                if not last_known:
                    await asyncio.to_thread(db.set_last_history_id, int(initial_history_id))
                    logger.info(
                        "[WORKER] Set initial historyId checkpoint: %s", initial_history_id
                    )
            logger.info("[WORKER] ✅ Gmail watch registered successfully.")
        except Exception as e:
            logger.error(
                "[WORKER] ❌ Gmail watch registration failed: %s\n"
                "Push notifications will NOT work. Check PUSH_SETUP.md.",
                e,
            )
    else:
        logger.warning(
            "[WORKER] PUBSUB_TOPIC or WEBHOOK_BASE_URL not set. "
            "Gmail Push is disabled. Set them in .env (see PUSH_SETUP.md)."
        )

    # --- Launch background coroutines ---
    await asyncio.gather(
        _consume_queue(ai_service, gmail_service),
        _watch_renewal_loop(gmail_service),
        _status_check_loop(ai_service, gmail_service),
    )


def clear_email_queue() -> None:
    """Clear all pending tasks from the email queue."""
    queue = get_email_queue()
    size = queue.qsize()
    logger.info("[WORKER] Clearing email queue — discarded %d pending messages.", size)
    while not queue.empty():
        try:
            queue.get_nowait()
            queue.task_done()
        except (asyncio.QueueEmpty, ValueError):
            break


def reset_worker_status() -> None:
    """Reset worker UI slot statuses to Idle."""
    global worker_status
    logger.info("[WORKER] Resetting all worker slot statuses to Idle.")
    for slot in worker_status:
        slot["status"] = "Idle"
        slot["task"] = None


async def trigger_catchup_task() -> None:
    """Run catchup scan to process missed emails when the engine is toggled ON."""
    logger.info("[WORKER] Service toggled ON — triggering catch-up scan...")

    # Check if the service is actually ON first
    is_on = await asyncio.to_thread(db.is_service_on)
    if not is_on:
        logger.info("[WORKER] Service toggled ON signal received but state is OFF — aborting catch-up.")
        return

    # Build services using settings
    from app.services.ai_service import AIService
    from app.services.gmail_service import get_gmail_service_instance
    ai_service = AIService(
        provider=settings.AI_PROVIDER,
        model=(
            settings.HF_MODEL
            if settings.AI_PROVIDER == "huggingface"
            else settings.CLAUDE_MODEL
        ),
        tone=settings.REPLY_TONE,
        hf_token=settings.HF_TOKEN,
        hf_api_url=settings.HF_API_URL,
        hf_max_retries=settings.HF_MAX_RETRIES,
        hf_retry_delay=settings.HF_RETRY_DELAY,
        hf_timeout=settings.HF_TIMEOUT,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        user_name=settings.USER_NAME,
        user_email=settings.USER_EMAIL,
    )
    gmail_service = get_gmail_service_instance(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        token_path=settings.GMAIL_TOKEN_PATH,
    )
    await _startup_catchup(ai_service, gmail_service)

