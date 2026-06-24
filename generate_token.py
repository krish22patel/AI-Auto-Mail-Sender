"""
Gmail OAuth2 Token Generator
-----------------------------
Run this script ONCE to authorize the application with your Gmail account.
It will open a browser window asking you to log in and grant permissions.
After approval, it saves `token.json` to the project root — the app uses
this file on every subsequent run (no browser needed after that).

Usage:
    python generate_token.py
"""

import json
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Load config from .env (without requiring python-dotenv)
# ---------------------------------------------------------------------------
def load_env(env_path: str = ".env") -> dict:
    env = {}
    if not os.path.exists(env_path):
        return env
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("  Gmail OAuth2 Token Generator")
    print("=" * 60)

    # Change CWD to script location so relative paths resolve correctly
    os.chdir(Path(__file__).parent)

    env = load_env(".env")
    credentials_path = env.get("GMAIL_CREDENTIALS_PATH", "credentials.json")
    token_path = env.get("GMAIL_TOKEN_PATH", "token.json")

    print(f"\n  Credentials file : {credentials_path}")
    print(f"  Token output path: {token_path}\n")

    # ------------------------------------------------------------------
    # Validate credentials.json exists
    # ------------------------------------------------------------------
    if not os.path.exists(credentials_path):
        print(f"[ERROR] '{credentials_path}' not found.")
        print("        Download it from Google Cloud Console:")
        print("        https://console.cloud.google.com/apis/credentials")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Import Google auth libraries (must be installed)
    # ------------------------------------------------------------------
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("[ERROR] Google auth libraries not installed.")
        print("        Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        sys.exit(1)

    SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

    creds = None

    # Check if a valid token already exists
    if os.path.exists(token_path):
        print(f"[INFO] Existing token found at '{token_path}'. Checking validity...")
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if creds and creds.valid:
            print("[OK]  Token is still valid -- no re-authorization needed.")
            print(f"      Token file: {os.path.abspath(token_path)}")
            return

        if creds and creds.expired and creds.refresh_token:
            print("[...] Token expired -- refreshing automatically...")
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
            print(f"[OK]  Token refreshed and saved to '{token_path}'")
            return

        print("[WARN] Existing token is invalid or missing refresh_token.")
        print("       Starting fresh authorization flow...\n")

    # ------------------------------------------------------------------
    # Full OAuth2 browser flow
    # ------------------------------------------------------------------
    print("[...] Opening browser for Gmail authorization...")
    print("      Please log in with the Gmail account you want the agent to use.")
    print("      After granting permission, the browser will redirect and close.\n")

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)

    # ------------------------------------------------------------------
    # Save token
    # ------------------------------------------------------------------
    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print(f"\n[OK]  token.json saved successfully!")
    print(f"      Path : {os.path.abspath(token_path)}")
    print("\n  You can now start the application. The token will be auto-")
    print("  refreshed by the app when it expires -- no manual action needed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
