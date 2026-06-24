from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Any
from app import db
from app.config import settings
from app.worker import processing_queue, worker_status, system_status
from app.schemas.email_schemas import HealthResponse, ReplyRequest, ReplyResult
from fastapi import BackgroundTasks, HTTPException

router = APIRouter(prefix="/api", tags=["Web App"])

class ToggleRequest(BaseModel):
    service_on: bool

@router.get("/status")
async def get_status():
    """Get the current status of the agent (ON/OFF, pending count, sent count)."""
    return {
        "service_on": db.is_service_on(),
        "pending_emails": db.get_pending_count(),
        "sent_emails": db.get_sent_count(),
        "captured_emails": db.get_inbox_count(),
        "user_name": settings.USER_NAME,
        "user_email": settings.USER_EMAIL,
        "queue": processing_queue,
        "workers": worker_status,
        "system_status": system_status,
    }

@router.post("/toggle")
async def toggle_service(req: ToggleRequest, background_tasks: BackgroundTasks):
    """Turn the auto-reply service ON or OFF."""
    db.set_service_state(req.service_on)
    if req.service_on:
        from app.worker import trigger_catchup_task
        background_tasks.add_task(trigger_catchup_task)
    else:
        from app.worker import clear_email_queue, reset_worker_status
        clear_email_queue()
        reset_worker_status()
        db.set_pending_count(0)
    return {"status": "success", "service_on": req.service_on}

@router.post("/settings/toggle")
async def toggle_service_alias(req: ToggleRequest, background_tasks: BackgroundTasks):
    """Alias route for settings/toggle as documented in internship report."""
    return await toggle_service(req, background_tasks)

@router.get("/logs")
async def get_logs():
    """Get the history of sent emails."""
    logs = db.get_logs(limit=50)
    return {"logs": logs}

@router.get("/inbox")
async def get_inbox(search: str = ""):
    """Get all captured inbox emails (both replied and pending). Optional ?search= filter."""
    emails = db.get_inbox_emails(limit=200, search=search)
    return {"emails": emails, "total": len(emails)}

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint checking Gmail status."""
    from app.services.gmail_service import get_gmail_service_instance
    gmail_service = get_gmail_service_instance(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        token_path=settings.GMAIL_TOKEN_PATH
    )
    return HealthResponse(
        status="healthy" if gmail_service.is_connected() else "unhealthy",
        gmail_connected=gmail_service.is_connected()
    )

@router.get("/emails/unread")
async def get_unread_emails(max_results: int = 50):
    """List current unread emails."""
    from app.services.gmail_service import get_gmail_service_instance
    gmail_service = get_gmail_service_instance(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        token_path=settings.GMAIL_TOKEN_PATH
    )
    if not gmail_service.is_connected():
        raise HTTPException(status_code=503, detail="Gmail service is not authenticated.")
    emails = gmail_service.list_unread_emails(max_results=max_results, exclude_auto_replied=True)
    return {"emails": emails, "count": len(emails)}

@router.get("/emails/{id}")
async def get_email_details(id: str):
    """Retrieve full details of a specific email."""
    from app.services.gmail_service import get_gmail_service_instance
    gmail_service = get_gmail_service_instance(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        token_path=settings.GMAIL_TOKEN_PATH
    )
    if not gmail_service.is_connected():
        raise HTTPException(status_code=503, detail="Gmail service is not authenticated.")
    try:
        details = gmail_service.get_email_details(id)
        return details
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Email details not found: {e}")

@router.post("/emails/{id}/reply", response_model=ReplyResult)
async def reply_email(id: str, req: ReplyRequest):
    """Manually reply using custom text or generated AI reply."""
    from app.services.gmail_service import get_gmail_service_instance
    from app.services.ai_service import get_ai_service
    
    gmail_service = get_gmail_service_instance(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        token_path=settings.GMAIL_TOKEN_PATH
    )
    if not gmail_service.is_connected():
        raise HTTPException(status_code=503, detail="Gmail service is not authenticated.")
        
    try:
        details = gmail_service.get_email_details(id)
        if req.custom_reply:
            reply_text = req.custom_reply
        else:
            ai_service = get_ai_service(
                provider=settings.AI_PROVIDER,
                model=settings.CLAUDE_MODEL if settings.AI_PROVIDER == "claude" else settings.HF_MODEL,
                tone=settings.REPLY_TONE,
                hf_token=settings.HF_TOKEN,
                hf_api_url=settings.HF_API_URL,
                hf_max_retries=settings.HF_MAX_RETRIES,
                hf_retry_delay=settings.HF_RETRY_DELAY,
                hf_timeout=settings.HF_TIMEOUT,
                anthropic_api_key=settings.ANTHROPIC_API_KEY,
                user_name=settings.USER_NAME,
                user_email=settings.USER_EMAIL
            )
            reply_text = ai_service.generate_reply(
                sender=details.sender,
                sender_name=details.sender_name or details.sender,
                subject=details.subject,
                body=details.body or details.snippet
            )
            
        gmail_service.send_reply(id, reply_text)
        db.log_email(
            message_id=id,
            sender=details.sender,
            subject=details.subject,
            reply_body=reply_text
        )
        db.mark_inbox_email_replied(id)
        
        return ReplyResult(
            email_id=id,
            sender=details.sender,
            subject=details.subject,
            reply_text=reply_text,
            status="sent"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send reply: {e}")

@router.post("/emails/auto-reply")
async def trigger_auto_reply(background_tasks: BackgroundTasks):
    """Trigger an instant background auto-reply scan."""
    def run_scan():
        try:
            from app.worker import SKIP_KEYWORDS, is_whitelisted
            from app.services.ai_service import get_ai_service
            from app.services.gmail_service import get_gmail_service_instance
            
            db.init_db()
            gmail_service = get_gmail_service_instance(
                credentials_path=settings.GMAIL_CREDENTIALS_PATH,
                token_path=settings.GMAIL_TOKEN_PATH
            )
            ai_service = get_ai_service(
                provider=settings.AI_PROVIDER,
                model=settings.CLAUDE_MODEL if settings.AI_PROVIDER == "claude" else settings.HF_MODEL,
                tone=settings.REPLY_TONE,
                hf_token=settings.HF_TOKEN,
                hf_api_url=settings.HF_API_URL,
                hf_max_retries=settings.HF_MAX_RETRIES,
                hf_retry_delay=settings.HF_RETRY_DELAY,
                hf_timeout=settings.HF_TIMEOUT,
                anthropic_api_key=settings.ANTHROPIC_API_KEY,
                user_name=settings.USER_NAME,
                user_email=settings.USER_EMAIL
            )
            unread_emails = gmail_service.list_unread_emails(200, exclude_auto_replied=True)
            for email in unread_emails:
                sender_lower = email.sender.lower()
                if any(kw in sender_lower for kw in SKIP_KEYWORDS):
                    continue
                if not is_whitelisted(email.sender, settings.ALLOWED_DOMAINS):
                    continue
                if db.is_already_replied(email.id):
                    continue
                
                email_detail = gmail_service.get_email_details(email.id)
                body_text = email_detail.body or email.snippet or "(No body)"
                
                reply_body = ai_service.generate_reply(
                    sender=email.sender,
                    sender_name=email.sender_name or email.sender,
                    subject=email.subject,
                    body=body_text
                )
                
                gmail_service.send_reply(email.id, reply_body)
                db.log_email(
                    message_id=email.id,
                    sender=email.sender,
                    subject=email.subject,
                    reply_body=reply_body
                )
                db.mark_inbox_email_replied(email.id)
        except Exception as e:
            print(f"[AUTO-REPLY SCAN ERROR] {e}")

    background_tasks.add_task(run_scan)
    return {"status": "scan_started"}

@router.get("/emails/search")
async def search_emails(q: str, max_results: int = 10):
    """Query Gmail using standard search syntax."""
    from app.services.gmail_service import get_gmail_service_instance
    gmail_service = get_gmail_service_instance(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        token_path=settings.GMAIL_TOKEN_PATH
    )
    if not gmail_service.is_connected():
        raise HTTPException(status_code=503, detail="Gmail service is not authenticated.")
    try:
        results = gmail_service.search_emails(q, max_results=max_results)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
