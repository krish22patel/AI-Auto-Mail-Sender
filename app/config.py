"""
Application configuration loaded from environment variables.

AI Provider : HuggingFace Inference Router  (OpenAI-compatible REST API)
Email events: Gmail Push Notifications via Google Cloud Pub/Sub  (interrupt-driven)
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    # -----------------------------------------------------------------------
    # AI Provider selection
    # -----------------------------------------------------------------------
    AI_PROVIDER: str = Field(
        default="huggingface",
        description="AI provider to use: 'huggingface' or 'claude'"
    )

    # -----------------------------------------------------------------------
    # HuggingFace Inference Router  (primary / default provider)
    # Docs: https://huggingface.co/docs/inference-providers
    # -----------------------------------------------------------------------
    HF_TOKEN: Optional[str] = Field(
        default=None,
        description="HuggingFace API token (https://huggingface.co/settings/tokens)"
    )
    HF_MODEL: str = Field(
        default="Qwen/Qwen2.5-7B-Instruct:together",
        description=(
            "HuggingFace model + backend. Format: 'owner/model:backend'. "
            "Examples: 'Qwen/Qwen2.5-7B-Instruct:together', "
            "'meta-llama/Meta-Llama-3.1-8B-Instruct:together', "
            "'mistralai/Mistral-7B-Instruct-v0.3:nebius'"
        )
    )
    HF_API_URL: str = Field(
        default="https://router.huggingface.co/v1/chat/completions",
        description="HuggingFace Router API endpoint (OpenAI-compatible)"
    )
    HF_MAX_RETRIES: int = Field(
        default=3,
        description="Max retries on 429 rate-limit from HuggingFace Router"
    )
    HF_RETRY_DELAY: float = Field(
        default=10.0,
        description="Base delay (seconds) for exponential back-off on HF 429 errors"
    )
    HF_TIMEOUT: int = Field(
        default=120,
        description="HTTP timeout (seconds) for HuggingFace API calls"
    )

    # -----------------------------------------------------------------------
    # Anthropic Claude  (optional fallback / alternative provider)
    # -----------------------------------------------------------------------
    ANTHROPIC_API_KEY: Optional[str] = Field(
        default=None,
        description="Anthropic Claude API Key (only needed if AI_PROVIDER=claude)"
    )
    CLAUDE_MODEL: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="Claude model to use when AI_PROVIDER=claude"
    )

    # -----------------------------------------------------------------------
    # Gmail OAuth Paths
    # -----------------------------------------------------------------------
    GMAIL_CREDENTIALS_PATH: str = Field(
        default="credentials.json",
        description="Path to Google OAuth credentials.json"
    )
    GMAIL_TOKEN_PATH: str = Field(
        default="token.json",
        description="Path to stored OAuth token"
    )

    # -----------------------------------------------------------------------
    # Gmail Push Notifications  (interrupt-driven, replaces polling)
    # -----------------------------------------------------------------------
    PUBSUB_TOPIC: str = Field(
        default="",
        description=(
            "Full Google Cloud Pub/Sub topic resource name. "
            "Format: 'projects/<project-id>/topics/<topic-name>'. "
            "See PUSH_SETUP.md for one-time GCP setup steps."
        )
    )
    WEBHOOK_BASE_URL: str = Field(
        default="",
        description=(
            "Publicly reachable HTTPS base URL for this server. "
            "Example: 'https://abc123.ngrok-free.app' (dev) or "
            "'https://yourdomain.com' (prod). "
            "Gmail will POST to <WEBHOOK_BASE_URL>/webhook/gmail"
        )
    )
    GMAIL_WATCH_RENEWAL_HOURS: int = Field(
        default=23,
        description=(
            "How often (hours) to renew the Gmail watch subscription. "
            "Gmail push subscriptions expire after 7 days; we renew every 23 h by default."
        )
    )

    # -----------------------------------------------------------------------
    # User Details
    # -----------------------------------------------------------------------
    USER_NAME: str = Field(
        default="Krish Patel",
        description="The sender's name used in outgoing reply signatures"
    )
    USER_EMAIL: str = Field(
        default="krish22patel07@gmail.com",
        description="The sender's email address used in outgoing replies"
    )

    # -----------------------------------------------------------------------
    # Agent / Reply Configuration
    # -----------------------------------------------------------------------
    AUTO_REPLY_LABEL: str = Field(
        default="auto-replied",
        description="Gmail label applied to emails after auto-reply (prevents re-processing)"
    )
    REPLY_TONE: str = Field(
        default="professional",
        description="Tone for AI replies: 'professional', 'casual', or 'friendly'"
    )
    ALLOWED_DOMAINS: str = Field(
        default="gmail.com,charusat.edu.in",
        description=(
            "Comma-separated whitelist of domains or exact addresses for auto-reply. "
            "Prefix with '@' for domain match (e.g. '@gmail.com') or use full address."
        )
    )
    MAX_WORKERS: int = Field(
        default=3,
        description="Maximum number of concurrent email-processing tasks"
    )
    STARTUP_CATCHUP_LIMIT: int = Field(
        default=50,
        description=(
            "Max unread emails to process on startup (catch-up fetch). "
            "Emails that arrived while the agent was offline are fetched once at boot."
        )
    )

    # -----------------------------------------------------------------------
    # FastAPI Server
    # -----------------------------------------------------------------------
    API_HOST: str = Field(default="0.0.0.0", description="API host")
    API_PORT: int = Field(default=8000, description="API port")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()
