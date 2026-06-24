"""
Gmail OAuth2 Authentication Module.

Handles the OAuth2 flow for Gmail API access, including:
- Initial authorization via browser consent screen
- Token storage and automatic refresh
- Gmail API service creation
"""

import os
import threading
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Gmail API scope - allows read, send, and label modification
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailAuthenticator:
    """Manages Gmail OAuth2 authentication and service creation."""

    def __init__(self, credentials_path: str = "credentials.json", token_path: str = "token.json"):
        """
        Initialize the authenticator.

        Args:
            credentials_path: Path to the Google OAuth credentials.json file
            token_path: Path to store/load the user's OAuth token
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._thread_local = threading.local()

    def authenticate(self) -> Credentials:
        """
        Authenticate with Gmail API using OAuth2.

        On first run, opens browser for user consent.
        On subsequent runs, uses stored/refreshed token.

        Returns:
            Valid Google OAuth2 credentials

        Raises:
            FileNotFoundError: If credentials.json is not found
        """
        creds = None

        # Load existing token if available
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        # If no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                # Refresh expired token
                print("[...] Refreshing expired Gmail token...")
                creds.refresh(Request())
            else:
                # Run full OAuth flow
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"[ERROR] credentials.json not found at '{self.credentials_path}'.\n"
                        f"Download it from Google Cloud Console:\n"
                        f"https://console.cloud.google.com/apis/credentials"
                    )

                print("[...] Opening browser for Gmail authorization...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save token for future use
            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())
            print("[OK] Gmail token saved successfully!")

        return creds

    def get_service(self):
        """
        Get an authenticated Gmail API service instance.

        Returns:
            Gmail API service object (googleapiclient.discovery.Resource)
        """
        if not hasattr(self._thread_local, "service") or self._thread_local.service is None:
            creds = self.authenticate()
            # Explicitly set static_discovery=True to avoid network requests on build
            self._thread_local.service = build("gmail", "v1", credentials=creds, static_discovery=True)
            print(f"[OK] Gmail API service initialized for thread {threading.get_ident()}!")
        return self._thread_local.service


# Singleton instance for the application
_authenticator = None


def get_gmail_service(credentials_path: str = "credentials.json", token_path: str = "token.json"):
    """
    Get the Gmail API service (singleton pattern).

    Args:
        credentials_path: Path to Google OAuth credentials
        token_path: Path to stored token

    Returns:
        Gmail API service object
    """
    global _authenticator
    if _authenticator is None:
        _authenticator = GmailAuthenticator(credentials_path, token_path)
    return _authenticator.get_service()
