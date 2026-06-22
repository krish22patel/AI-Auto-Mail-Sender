from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Any
from app import db
from app.config import settings
from app.worker import processing_queue, worker_status

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
    }

@router.post("/toggle")
async def toggle_service(req: ToggleRequest):
    """Turn the auto-reply service ON or OFF."""
    db.set_service_state(req.service_on)
    return {"status": "success", "service_on": req.service_on}

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
