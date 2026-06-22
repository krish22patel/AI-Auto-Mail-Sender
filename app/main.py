"""
FastAPI Application Entry Point.

AI Email Agent — Web App
"""

import sys
import io
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.routers.email_router import router as email_router
from app.worker import auto_reply_worker
from app import db

# Fix Windows console encoding for emoji/unicode
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — runs on startup and shutdown."""
    print("=" * 60)
    print("[AI Email Agent] Starting Web App...")
    print("=" * 60)
    
    # Initialize SQLite Database
    db.init_db()
    
    # Start the background worker
    worker_task = asyncio.create_task(auto_reply_worker())
    
    yield
    
    # Shutdown
    worker_task.cancel()
    print("[AI Email Agent] Shutting Down")


# Create FastAPI application
app = FastAPI(
    title="AI Email Agent",
    description="Automated AI Email Agent",
    version="1.0.0",
    docs_url=None,  # Hide swagger from /docs
    redoc_url=None, # Hide redoc
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(email_router)

# Mount static files for the frontend
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
async def root():
    """Serve the main UI."""
    return FileResponse("app/static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True
    )
