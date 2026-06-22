import asyncio
import traceback
from app import db
from app.config import settings
from app.services.gmail_service import get_gmail_service_instance
from app.services.ai_service import AIService

# Skip keywords for senders we don't want to auto-reply to
SKIP_KEYWORDS = [
    "noreply", "no-reply", "newsletter", "updates@",
    "notification", "donotreply", "mailer-daemon",
    "alerts@", "alert@"
]


# Global active queue for tracking in-progress tasks
processing_queue = []

# Global active worker slots for status tracking
worker_status = []

# Semaphore to control concurrency
worker_semaphore = None


def is_whitelisted(email: str, allowed_str: str) -> bool:
    """Check if the sender's email address is whitelisted by domain or exact match."""
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


async def process_email_task(email, ai_service, gmail_service):
    """Processes a single email: generating AI reply and sending it in parallel."""
    import datetime
    
    task_info = {
        "id": email.id,
        "sender": email.sender,
        "sender_name": email.sender_name or email.sender,
        "subject": email.subject,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    
    processing_queue.append(task_info)
    print(f"[WORKER] Added to active queue: {email.sender} | {email.subject}")
    
    slot = None
    for s in worker_status:
        if s["status"] == "Idle":
            slot = s
            slot["status"] = "Active"
            slot["task"] = {
                "sender": email.sender,
                "subject": email.subject,
                "step": "Acquiring lock..."
            }
            break
            
    try:
        async with worker_semaphore:
            # 1. Fetch details (blocking Gmail API call)
            if slot:
                slot["task"]["step"] = "Reading details"
            email_detail = await asyncio.to_thread(gmail_service.get_email_details, email.id)
            body_text = email_detail.body or email.snippet or "(No body)"
            
            print(f"[WORKER] Generating AI reply for: {email.sender} | {email.subject}")
            
            # 2. Generate AI reply (blocking Ollama request)
            if slot:
                slot["task"]["step"] = "AI generating reply"
            reply_body = await asyncio.to_thread(
                ai_service.generate_reply,
                sender=email.sender,
                sender_name=email.sender_name or email.sender,
                subject=email.subject,
                body=body_text
            )
            
            print(f"[WORKER] Sending reply to: {email.sender} | {email.subject}")
            
            # 3. Send reply (blocking Gmail API send)
            if slot:
                slot["task"]["step"] = "Sending email reply"
            await asyncio.to_thread(gmail_service.send_reply, email.id, reply_body)
            
            # 4. Log to database (blocking SQLite writes)
            if slot:
                slot["task"]["step"] = "Logging to database"
            await asyncio.to_thread(
                db.log_email,
                message_id=email.id,
                sender=email.sender,
                subject=email.subject,
                reply_body=reply_body
            )
            await asyncio.to_thread(db.mark_inbox_email_replied, email.id)
            
            print(f"[OK] Concurrent worker auto-replied to {email.sender} - {email.subject}")
            
    except Exception as e:
        err = traceback.format_exc()
        print(f"[ERROR] Concurrent worker failed to reply to {email.sender}: {e}")
        with open("worker_crash.txt", "w", encoding="utf-8") as f:
            f.write(err)
    finally:
        # Free worker slot
        if slot:
            slot["status"] = "Idle"
            slot["task"] = None
        # Remove from active queue
        if task_info in processing_queue:
            processing_queue.remove(task_info)
            print(f"[WORKER] Removed from active queue: {email.sender}")


async def auto_reply_worker():
    """
    Async background worker. Delegates all blocking I/O to a thread pool
    via asyncio.to_thread() so the event loop is never blocked.
    """
    global worker_semaphore, worker_status
    print("[WORKER] Background Worker Started!")
    db.init_db()

    # Initialize worker status slots dynamically (keep reference intact)
    worker_status.clear()
    worker_status.extend([{"id": i + 1, "status": "Idle", "task": None} for i in range(settings.MAX_WORKERS)])

    ai_service = AIService(
        model=settings.OLLAMA_MODEL,
        tone=settings.REPLY_TONE,
        ollama_url=settings.OLLAMA_URL,
        user_name=settings.USER_NAME,
        user_email=settings.USER_EMAIL
    )

    gmail_service = get_gmail_service_instance(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        token_path=settings.GMAIL_TOKEN_PATH
    )

    poll_interval = max(30, settings.POLL_INTERVAL_SECONDS)
    print(f"[WORKER] Poll interval: {poll_interval}s | Model: {settings.OLLAMA_MODEL}")

    if worker_semaphore is None:
        worker_semaphore = asyncio.Semaphore(settings.MAX_WORKERS)

    while True:
        try:
            # 1. Check Gmail connection
            connected = await asyncio.to_thread(gmail_service.is_connected)
            if not connected:
                print("[WORKER] Gmail not connected, retrying in 30s...")
                await asyncio.sleep(30)
                continue

            is_on = await asyncio.to_thread(db.is_service_on)
            print("[WORKER] Fetching emails...")

            # 2. Fetch UNREAD emails for auto-reply
            unread_emails = await asyncio.to_thread(gmail_service.list_unread_emails, 200)
            await asyncio.to_thread(db.set_pending_count, len(unread_emails))
            print(f"[WORKER] Unread emails found: {len(unread_emails)}")

            # 3. Fetch ALL RECENT emails (read+unread) for inbox display
            recent_emails = await asyncio.to_thread(gmail_service.list_recent_emails, 200, 7)
            print(f"[WORKER] Recent emails (7 days): {len(recent_emails)}")

            # Capture recent emails into DB (for dashboard inbox view)
            def capture_emails():
                for email in recent_emails:
                    db.capture_inbox_email(
                        message_id=email.id,
                        sender=email.sender,
                        sender_name=email.sender_name,
                        subject=email.subject,
                        snippet=email.snippet,
                        date=email.date,
                    )
            await asyncio.to_thread(capture_emails)

            print(f"[WORKER] Auto-reply ON: {is_on}")

            if is_on:
                # 4. Filter emails that need reply
                emails_to_reply = []
                for email in unread_emails:
                    sender_lower = email.sender.lower()

                    # Skip automated/newsletter senders
                    if any(kw in sender_lower for kw in SKIP_KEYWORDS):
                        print(f"[WORKER] Skipping automated sender: {email.sender}")
                        continue

                    # Filter by whitelist
                    if not is_whitelisted(email.sender, settings.ALLOWED_DOMAINS):
                        print(f"[WORKER] Skipping domain (not whitelisted): {email.sender}")
                        continue

                    # Skip already replied emails
                    is_replied = await asyncio.to_thread(db.is_already_replied, email.id)
                    if is_replied:
                        continue

                    emails_to_reply.append(email)

                # 5. Process emails concurrently up to MAX_WORKERS
                if emails_to_reply:
                    print(f"[WORKER] Launching {len(emails_to_reply)} parallel email tasks...")
                    tasks = [
                        process_email_task(email, ai_service, gmail_service)
                        for email in emails_to_reply
                    ]
                    await asyncio.gather(*tasks)

            # Refresh pending count after processing
            remaining = await asyncio.to_thread(gmail_service.list_unread_emails, 200)
            await asyncio.to_thread(db.set_pending_count, len(remaining))

        except Exception as e:
            err = traceback.format_exc()
            print(f"[WORKER ERROR] {e}")
            with open("worker_crash.txt", "w", encoding="utf-8") as f:
                f.write(err)

        print(f"[WORKER] Sleeping {poll_interval}s before next check...")
        await asyncio.sleep(poll_interval)

