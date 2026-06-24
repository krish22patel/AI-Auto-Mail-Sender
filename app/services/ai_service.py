"""
AI Reply Service Module.

Generates intelligent, context-aware email replies using the
HuggingFace Inference Router API (OpenAI-compatible, open-source models).

Provider hierarchy:
  1. HuggingFace Router  — default, uses open-source models (e.g. Qwen, Llama, Mistral)
  2. Anthropic Claude    — optional alternative (requires ANTHROPIC_API_KEY)

Rate-limit handling:
  HuggingFace free accounts enforce per-provider quotas.  All 429 responses
  are retried automatically with exponential back-off so no email is dropped.
"""

import json
import time
import requests
from typing import Optional
import re


# ---------------------------------------------------------------------------
# Email-address patterns that should never receive auto-replies
# ---------------------------------------------------------------------------
SKIP_PATTERNS = [
    "noreply@",
    "no-reply@",
    "donotreply@",
    "mailer-daemon@",
    "notifications@",
    "newsletter@",
    "updates@",
    "alert@",
    "alerts@",
]

SKIP_SUBJECTS = [
    "unsubscribe",
    "your receipt",
    "order confirmation",
    "shipping notification",
    "password reset",
    "verify your email",
    "verification code",
]


# ---------------------------------------------------------------------------
# AIService
# ---------------------------------------------------------------------------
class AIService:
    """
    Generates AI-powered email replies.

    Supported providers
    -------------------
    'huggingface'  — HuggingFace Inference Router (default, open-source models)
    'claude'       — Anthropic Claude (requires ANTHROPIC_API_KEY)
    """

    def __init__(
        self,
        provider: str = "huggingface",
        model: str = "Qwen/Qwen2.5-7B-Instruct:together",
        tone: str = "professional",
        hf_token: Optional[str] = None,
        hf_api_url: str = "https://router.huggingface.co/v1/chat/completions",
        hf_max_retries: int = 3,
        hf_retry_delay: float = 10.0,
        hf_timeout: int = 120,
        anthropic_api_key: Optional[str] = None,
        user_name: str = "Krish Patel",
        user_email: str = "krish22patel07@gmail.com",
    ):
        """
        Initialise the AI service.

        Parameters
        ----------
        provider        : 'huggingface' or 'claude'
        model           : Model identifier.
                          HF format  → 'owner/model:backend'
                          Claude format → 'claude-3-5-sonnet-20241022'
        tone            : Reply tone — 'professional', 'casual', or 'friendly'
        hf_token        : HuggingFace API token (Bearer)
        hf_api_url      : HF Router endpoint (OpenAI-compatible)
        hf_max_retries  : Retry count on 429 / transient errors
        hf_retry_delay  : Base delay (seconds) for exponential back-off
        hf_timeout      : HTTP request timeout (seconds)
        anthropic_api_key : Required only when provider='claude'
        user_name       : User's display name for email signatures
        user_email      : User's email address for signatures
        """
        self.provider = provider.lower()
        self.model = model
        self.tone = tone
        self.hf_token = hf_token
        self.hf_api_url = hf_api_url.rstrip("/")
        self.hf_max_retries = hf_max_retries
        self.hf_retry_delay = hf_retry_delay
        self.hf_timeout = hf_timeout
        self.anthropic_api_key = anthropic_api_key
        self.user_name = user_name
        self.user_email = user_email
        self.last_error = None

        # Guard: ensure the chosen provider has credentials
        if self.provider == "huggingface" and not self.hf_token:
            print(
                "[WARN] HuggingFace provider selected but HF_TOKEN is missing. "
                "Set HF_TOKEN in your .env file."
            )
        elif self.provider == "claude" and not self.anthropic_api_key:
            print(
                "[WARN] Claude provider selected but ANTHROPIC_API_KEY is missing. "
                "Falling back to HuggingFace."
            )
            self.provider = "huggingface"

    # -----------------------------------------------------------------------
    # System prompt
    # -----------------------------------------------------------------------
    def _get_system_prompt(self) -> str:
        """Build the system prompt based on the configured reply tone."""
        tone_instructions = {
            "professional": (
                "You write professional, polished business emails. "
                "Use formal language, proper greetings, and sign off appropriately. "
                "Be concise but thorough."
            ),
            "casual": (
                "You write casual, relaxed emails like talking to a friend. "
                "Use informal language, but remain respectful and clear. "
                "Keep it short and to the point."
            ),
            "friendly": (
                "You write warm, friendly emails that feel personal. "
                "Use a positive tone with appropriate warmth. "
                "Be helpful and approachable while remaining professional."
            ),
        }
        tone_desc = tone_instructions.get(self.tone, tone_instructions["professional"])

        return (
            f"You are an intelligent email assistant that generates replies on behalf of "
            f"the user, {self.user_name} ({self.user_email}).\n\n"
            f"{tone_desc}\n\n"
            "IMPORTANT RULES:\n"
            "1. Read the original email carefully and generate an appropriate reply.\n"
            "2. Address the sender by their name if available.\n"
            "3. Respond to all questions or points raised in the original email.\n"
            "4. Do NOT include the subject line in your reply — only the body text.\n"
            "5. Do NOT include 'Subject:' or 'From:' headers.\n"
            "6. Keep replies concise — usually 2-4 paragraphs max.\n"
            "7. If the email is a notification or automated message, acknowledge it briefly.\n"
            "8. If the email requires specific information you don't have, politely indicate you'll follow up.\n"
            f"9. Sign off with:\nBest regards,\n{self.user_name}\n{self.user_email}\n"
            "10. Do NOT use placeholder names, templates, or bracketed variables "
            "(like '[Your Name]', '[Your Email]', '[First Name] [Last Name]', etc.) "
            "in the signature or anywhere in the email.\n"
            "11. Do NOT hallucinate or make up specific details, dates, or commitments."
        )

    # -----------------------------------------------------------------------
    # HuggingFace Router  (OpenAI-compatible)
    # -----------------------------------------------------------------------
    def _call_huggingface(self, system_prompt: str, user_prompt: str) -> str:
        """
        Call the HuggingFace Inference Router API.

        Uses the OpenAI-compatible `/v1/chat/completions` endpoint so any
        model available on the HF Router can be swapped in via HF_MODEL.

        Retries automatically on 429 (rate-limit) with exponential back-off.

        Parameters
        ----------
        system_prompt : System instructions for the model
        user_prompt   : The email content to reply to

        Returns
        -------
        str : Generated reply text

        Raises
        ------
        Exception : On auth failure, persistent rate-limit, or network error
        """
        if not self.hf_token:
            raise Exception(
                "❌ HF_TOKEN is not set! "
                "Get your token at https://huggingface.co/settings/tokens "
                "and add HF_TOKEN=<token> to your .env file."
            )

        headers = {
            "Authorization": f"Bearer {self.hf_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 1024,
        }

        delay = self.hf_retry_delay
        for attempt in range(1, self.hf_max_retries + 1):
            try:
                response = requests.post(
                    self.hf_api_url,
                    headers=headers,
                    json=payload,
                    timeout=self.hf_timeout,
                )

                # --- Rate limit: back-off and retry ---
                if response.status_code == 429:
                    retry_after = float(
                        response.headers.get("Retry-After", delay)
                    )
                    wait = max(retry_after, delay)
                    print(
                        f"[HF] Rate limited (429). Attempt {attempt}/{self.hf_max_retries}. "
                        f"Waiting {wait:.0f}s before retry..."
                    )
                    if attempt < self.hf_max_retries:
                        time.sleep(wait)
                        delay *= 2  # exponential back-off
                        continue
                    raise Exception(
                        f"❌ HuggingFace Router rate limit exceeded after "
                        f"{self.hf_max_retries} retries. Try again later or "
                        "use a paid HF account for higher quotas."
                    )

                # --- Auth failure ---
                if response.status_code == 401:
                    raise Exception(
                        "❌ HuggingFace authentication failed (401). "
                        "Check that HF_TOKEN in your .env is correct and has 'Inference' permissions."
                    )

                # --- Model not available on this backend ---
                if response.status_code == 404:
                    raise Exception(
                        f"❌ Model '{self.model}' not found on HuggingFace Router (404). "
                        "Verify the model ID and backend suffix (e.g. ':together')."
                    )

                response.raise_for_status()

                result = response.json()
                choices = result.get("choices", [])
                if not choices:
                    raise Exception(
                        f"❌ Unexpected HuggingFace Router response (no 'choices'): {result}"
                    )
                return choices[0]["message"]["content"].strip()

            except requests.Timeout:
                print(
                    f"[HF] Request timed out (attempt {attempt}/{self.hf_max_retries}). "
                    f"Retrying in {delay:.0f}s..."
                )
                if attempt < self.hf_max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise Exception(
                    f"❌ HuggingFace Router timed out after {self.hf_max_retries} attempts."
                )

            except requests.ConnectionError as e:
                print(
                    f"[HF] Connection failed (attempt {attempt}/{self.hf_max_retries}): {e}. "
                    f"Retrying in {delay:.0f}s..."
                )
                if attempt < self.hf_max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise Exception(
                    f"❌ Could not connect to HuggingFace Router at {self.hf_api_url} after {self.hf_max_retries} attempts: {e}"
                )

            except Exception:
                raise

        # Should never reach here
        raise Exception("❌ HuggingFace Router: all retries exhausted.")

    # -----------------------------------------------------------------------
    # Anthropic Claude  (optional alternative provider)
    # -----------------------------------------------------------------------
    def _call_claude(self, system_prompt: str, user_prompt: str) -> str:
        """
        Call the Anthropic Claude API.

        Parameters
        ----------
        system_prompt : System instructions for Claude
        user_prompt   : The email content to reply to

        Returns
        -------
        str : Generated reply text
        """
        if not self.anthropic_api_key:
            raise Exception("❌ ANTHROPIC_API_KEY is not configured!")

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.7,
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            content = result.get("content", [])
            if content and isinstance(content, list) and content[0].get("type") == "text":
                return content[0].get("text", "").strip()
            raise Exception("Unexpected response format from Claude API")
        except requests.exceptions.HTTPError as e:
            try:
                err_msg = response.json().get("error", {}).get("message", str(e))
            except Exception:
                err_msg = str(e)
            raise Exception(f"❌ Anthropic Claude API error: {err_msg}")
        except Exception as e:
            raise Exception(f"❌ Claude connection error: {e}")

    # -----------------------------------------------------------------------
    # Skip-email logic
    # -----------------------------------------------------------------------
    def should_skip_email(self, sender_email: str, subject: str) -> tuple[bool, str]:
        """
        Determine whether an email should be skipped (no-reply, newsletters, etc.).

        Parameters
        ----------
        sender_email : Sender's email address
        subject      : Email subject line

        Returns
        -------
        (should_skip: bool, reason: str)
        """
        sender_lower = sender_email.lower()

        for pattern in SKIP_PATTERNS:
            if pattern in sender_lower:
                return True, f"Skipped: sender matches '{pattern}' pattern"

        subject_lower = subject.lower()
        for skip_word in SKIP_SUBJECTS:
            if skip_word in subject_lower:
                return True, f"Skipped: subject contains '{skip_word}'"

        return False, ""

    # -----------------------------------------------------------------------
    # Public API: generate_reply
    # -----------------------------------------------------------------------
    def generate_reply(
        self,
        sender: str,
        sender_name: str,
        subject: str,
        body: str,
        custom_instructions: Optional[str] = None,
    ) -> str:
        """
        Generate an AI-powered reply to an email.

        Parameters
        ----------
        sender              : Sender's email address
        sender_name         : Sender's display name
        subject             : Email subject
        body                : Email body text (truncated to 3000 chars internally)
        custom_instructions : Optional extra instructions for this specific reply

        Returns
        -------
        str : Generated reply body (placeholders cleaned)
        """
        user_prompt = (
            "Please generate a reply to the following email:\n\n"
            f"**From:** {sender_name} <{sender}>\n"
            f"**Subject:** {subject}\n\n"
            f"**Email Body:**\n{body[:3000]}\n"
        )

        if custom_instructions:
            user_prompt += f"\n**Additional Instructions:** {custom_instructions}"

        system_prompt = self._get_system_prompt()

        if self.provider == "claude":
            reply_text = self._call_claude(system_prompt, user_prompt)
        else:
            # Default: huggingface
            reply_text = self._call_huggingface(system_prompt, user_prompt)

        return self._clean_placeholders(reply_text)

    # -----------------------------------------------------------------------
    # Placeholder cleanup
    # -----------------------------------------------------------------------
    def _clean_placeholders(self, text: str) -> str:
        """
        Replace any bracketed or angle-bracket placeholder variables with the
        real user name / email so no template artefacts appear in sent replies.
        """
        name_parts = self.user_name.split()
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[-1] if len(name_parts) > 1 else ""

        replacements = {
            r"\[Your\s*Name\]": self.user_name,
            r"\[First\s*Name\]\s*\[Last\s*Name\]": self.user_name,
            r"\[First\s*Name\]": first_name,
            r"\[Last\s*Name\]": last_name,
            r"\[Your\s*Email\s*(Address)?\]": self.user_email,
            r"\[Email\s*(Address)?\]": self.user_email,
            r"\[Sender\s*Name\]": self.user_name,
            r"\[My\s*Name\]": self.user_name,
            r"<Your\s*Name>": self.user_name,
            r"<First\s*Name>\s*<Last\s*Name>": self.user_name,
            r"<First\s*Name>": first_name,
            r"<Last\s*Name>": last_name,
            r"<Your\s*Email>": self.user_email,
            r"<Email>": self.user_email,
        }

        cleaned = text
        for pattern, replacement in replacements.items():
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        return cleaned

    # -----------------------------------------------------------------------
    # Health check
    # -----------------------------------------------------------------------
    def is_connected(self) -> bool:
        """
        Check whether the configured AI provider is reachable / authenticated.

        For HuggingFace: validates the token with a lightweight whoami call.
        For Claude: checks that the API key is present (no live ping needed).
        """
        self.last_error = None
        if self.provider == "claude":
            if not self.anthropic_api_key:
                self.last_error = "Anthropic API Key (ANTHROPIC_API_KEY) is missing in .env configuration."
                return False
            return True

        # HuggingFace: quick token validation
        if not self.hf_token:
            self.last_error = "HuggingFace Token (HF_TOKEN) is missing in .env configuration."
            return False
        try:
            r = requests.get(
                "https://huggingface.co/api/whoami",
                headers={"Authorization": f"Bearer {self.hf_token}"},
                timeout=10,
            )
            if r.status_code == 401:
                self.last_error = "HuggingFace token authentication failed (401). Please check if your HF_TOKEN is valid."
                return False
            elif r.status_code != 200:
                self.last_error = f"HuggingFace whoami check returned HTTP {r.status_code}: {r.text}"
                return False
            return True
        except Exception as e:
            self.last_error = f"Failed to connect to HuggingFace: {e}"
            return False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_ai_service: Optional["AIService"] = None


def get_ai_service(
    provider: str = "huggingface",
    model: str = "Qwen/Qwen2.5-7B-Instruct:together",
    tone: str = "professional",
    hf_token: Optional[str] = None,
    hf_api_url: str = "https://router.huggingface.co/v1/chat/completions",
    hf_max_retries: int = 3,
    hf_retry_delay: float = 10.0,
    hf_timeout: int = 120,
    anthropic_api_key: Optional[str] = None,
    user_name: str = "Krish Patel",
    user_email: str = "krish22patel07@gmail.com",
) -> AIService:
    """
    Return the singleton AIService instance.

    On first call the instance is constructed with the supplied arguments.
    Subsequent calls return the same object regardless of arguments, so
    initialise once at startup (e.g. inside auto_reply_worker).
    """
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService(
            provider=provider,
            model=model,
            tone=tone,
            hf_token=hf_token,
            hf_api_url=hf_api_url,
            hf_max_retries=hf_max_retries,
            hf_retry_delay=hf_retry_delay,
            hf_timeout=hf_timeout,
            anthropic_api_key=anthropic_api_key,
            user_name=user_name,
            user_email=user_email,
        )
    return _ai_service
