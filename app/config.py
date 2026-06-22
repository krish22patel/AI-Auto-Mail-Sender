"""
Application configuration loaded from environment variables.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    # Ollama (Local LLM - 100% Free)
    OLLAMA_MODEL: str = Field(
        default="qwen2.5:7b",
        description="Ollama model name to use for generating replies"
    )
    OLLAMA_URL: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL"
    )

    # Gmail OAuth Paths
    GMAIL_CREDENTIALS_PATH: str = Field(
        default="credentials.json",
        description="Path to Google OAuth credentials.json"
    )
    GMAIL_TOKEN_PATH: str = Field(
        default="token.json",
        description="Path to stored OAuth token"
    )

    # User Details
    USER_NAME: str = Field(
        default="Kishan Vadsola",
        description="The sender's name in outgoing replies"
    )
    USER_EMAIL: str = Field(
        default="vadsolakishan1310@gmail.com",
        description="The sender's email address"
    )

    # Agent Configuration
    AUTO_REPLY_LABEL: str = Field(
        default="auto-replied",
        description="Gmail label to mark auto-replied emails"
    )
    POLL_INTERVAL_SECONDS: int = Field(
        default=300,
        description="Polling interval in seconds (default 5 minutes)"
    )
    REPLY_TONE: str = Field(
        default="professional",
        description="Tone for AI replies: professional, casual, or friendly"
    )
    ALLOWED_DOMAINS: str = Field(
        default="gmail.com,charusat.edu.in",
        description="Comma-separated list of allowed domains or email addresses for auto-reply"
    )
    MAX_WORKERS: int = Field(
        default=3,
        description="Maximum number of parallel auto-reply worker tasks"
    )

    # FastAPI
    API_HOST: str = Field(default="0.0.0.0", description="API host")
    API_PORT: int = Field(default=8000, description="API port")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()
