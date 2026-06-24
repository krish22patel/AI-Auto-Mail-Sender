"""
FastAPI Application Entry Point.

AI Email Agent — Interrupt-Driven Edition
  - AI Backend : HuggingFace Inference Router (open-source models)
  - Email Events: Gmail Push Notifications via Google Cloud Pub/Sub
"""

import sys
import io
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.routers.email_router import router as email_router
from app.routers.push_router import router as push_router
from app.worker import auto_reply_worker
from app import db

# Fix Windows console encoding for emoji / unicode output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Configure logging (structured, timestamped)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and graceful shutdown."""
    logger.info("=" * 60)
    logger.info("[AI Email Agent] Starting …")
    logger.info("[AI Email Agent] AI provider  : %s", settings.AI_PROVIDER)
    logger.info("[AI Email Agent] HF model     : %s", settings.HF_MODEL)
    logger.info(
        "[AI Email Agent] Email events : %s",
        "Gmail Push (interrupt)" if settings.PUBSUB_TOPIC else "Startup catch-up only (set PUBSUB_TOPIC for push)",
    )
    logger.info("[AI Email Agent] Webhook URL  : %s/webhook/gmail", settings.WEBHOOK_BASE_URL or "<not set>")
    logger.info("=" * 60)

    # Initialise SQLite database
    db.init_db()

    # Launch the background worker (queue consumer + watch renewal + status check)
    worker_task = asyncio.create_task(auto_reply_worker())

    yield

    # Graceful shutdown
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    logger.info("[AI Email Agent] Shutdown complete.")


# Create FastAPI application
app = FastAPI(
    title="AI Email Agent",
    description=(
        "Automated AI Email Agent. "
        "Uses HuggingFace open-source models and Gmail Push Notifications."
    ),
    version="2.0.0",
    docs_url=None,   # Hide Swagger UI from /docs
    redoc_url=None,  # Hide ReDoc
    lifespan=lifespan,
)

# CORS — allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
app.include_router(email_router)
app.include_router(push_router)   # POST /webhook/gmail  ← Pub/Sub push endpoint

# Static files (frontend UI)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def root():
    """Serve the main dashboard UI."""
    return FileResponse("app/static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,   # Disable reload in production; use reload=True only for dev
    )
