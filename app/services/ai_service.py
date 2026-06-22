"""
AI Reply Service Module.

Uses Ollama (local LLM) to generate intelligent, context-aware email replies.
Supports configurable tone (professional, casual, friendly) and handles
edge cases like newsletters, no-reply addresses, and forwarded emails.

100% FREE — runs entirely on your local machine via Ollama.
"""

import json
import requests
from typing import Optional


class AIService:
    """Service for generating AI-powered email replies using Ollama (local LLM)."""

    # Email addresses/patterns to skip (no-reply, newsletters, etc.)
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

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        tone: str = "professional",
        ollama_url: str = "http://localhost:11434",
        user_name: str = "Kishan Vadsola",
        user_email: str = "vadsolakishan1310@gmail.com"
    ):
        """
        Initialize the AI service with Ollama.

        Args:
            model: Ollama model name (e.g., 'qwen2.5:7b', 'llama3.2', 'mistral')
            tone: Reply tone - 'professional', 'casual', or 'friendly'
            ollama_url: Ollama server URL (default: http://localhost:11434)
            user_name: User's name for email signatures
            user_email: User's email address
        """
        self.model = model
        self.tone = tone
        self.ollama_url = ollama_url.rstrip("/")
        self.user_name = user_name
        self.user_email = user_email

    def _get_system_prompt(self) -> str:
        """Get the system prompt based on configured tone."""
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

        return f"""You are an intelligent email assistant that generates replies on behalf of the user, {self.user_name} ({self.user_email}).

{tone_desc}

IMPORTANT RULES:
1. Read the original email carefully and generate an appropriate reply.
2. Address the sender by their name if available.
3. Respond to all questions or points raised in the original email.
4. Do NOT include the subject line in your reply — only the body text.
5. Do NOT include "Subject:" or "From:" headers.
6. Keep replies concise — usually 2-4 paragraphs max.
7. If the email is a notification or automated message, acknowledge it briefly.
8. If the email requires specific information you don't have, politely indicate you'll follow up.
9. Sign off with:
Best regards,
{self.user_name}
{self.user_email}
10. Do NOT use placeholder names, templates, or bracketed variables (like "[Your Name]", "[Your Email]", "[First Name] [Last Name]", etc.) in the signature or anywhere in the email.
11. Do NOT hallucinate or make up specific details, dates, or commitments."""

    def _call_ollama(self, system_prompt: str, user_prompt: str) -> str:
        """
        Call the Ollama API to generate a response.

        Args:
            system_prompt: System instructions for the model
            user_prompt: User message to respond to

        Returns:
            Generated text response

        Raises:
            Exception: If Ollama is not running or request fails
        """
        url = f"{self.ollama_url}/api/chat"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 1024,
            }
        }

        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            return result["message"]["content"].strip()

        except requests.ConnectionError:
            raise Exception(
                "❌ Ollama is not running! Start it with: ollama serve\n"
                "Then make sure your model is pulled: ollama pull qwen2.5:7b"
            )
        except requests.Timeout:
            raise Exception("❌ Ollama request timed out. The model may be loading.")
        except Exception as e:
            raise Exception(f"❌ Ollama error: {e}")

    def should_skip_email(self, sender_email: str, subject: str) -> tuple[bool, str]:
        """
        Check if an email should be skipped (no-reply, newsletters, etc.).

        Args:
            sender_email: Sender's email address
            subject: Email subject line

        Returns:
            Tuple of (should_skip, reason)
        """
        sender_lower = sender_email.lower()

        # Check no-reply patterns
        for pattern in self.SKIP_PATTERNS:
            if pattern in sender_lower:
                return True, f"Skipped: sender matches '{pattern}' pattern"

        # Check for common newsletter/automated subjects
        skip_subjects = [
            "unsubscribe",
            "your receipt",
            "order confirmation",
            "shipping notification",
            "password reset",
            "verify your email",
            "verification code",
        ]
        subject_lower = subject.lower()
        for skip_word in skip_subjects:
            if skip_word in subject_lower:
                return True, f"Skipped: subject contains '{skip_word}'"

        return False, ""

    def generate_reply(
        self,
        sender: str,
        sender_name: str,
        subject: str,
        body: str,
        custom_instructions: Optional[str] = None
    ) -> str:
        """
        Generate an AI reply to an email using Ollama (local LLM).

        Args:
            sender: Sender's email address
            sender_name: Sender's display name
            subject: Email subject
            body: Email body text
            custom_instructions: Optional additional instructions for the reply

        Returns:
            Generated reply text
        """
        # Build the user prompt
        user_prompt = f"""Please generate a reply to the following email:

**From:** {sender_name} <{sender}>
**Subject:** {subject}

**Email Body:**
{body[:3000]}
"""
        # Truncate very long emails to stay within context

        if custom_instructions:
            user_prompt += f"\n**Additional Instructions:** {custom_instructions}"

        reply_text = self._call_ollama(self._get_system_prompt(), user_prompt)
        return self._clean_placeholders(reply_text)

    def _clean_placeholders(self, text: str) -> str:
        """Replace common bracketed or tagged placeholders with actual user details."""
        import re
        
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

    def is_connected(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])
            model_names = [m["name"] for m in models]
            # Check if our model (or a prefix match) is available
            return any(self.model in name for name in model_names)
        except Exception:
            return False


# Singleton instance
_ai_service = None


def get_ai_service(model: str = "qwen2.5:7b", tone: str = "professional", ollama_url: str = "http://localhost:11434") -> AIService:
    """Get singleton AIService instance."""
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService(model=model, tone=tone, ollama_url=ollama_url)
    return _ai_service
