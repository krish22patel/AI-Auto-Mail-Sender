import sqlite3
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_PATH = Path(os.getcwd()) / "data.db"

def init_db():
    """Initialize the SQLite database with required tables."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Settings table (key-value store)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Ensure default service state is OFF and count is 0
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('is_auto_reply_on', 'false')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('pending_count', '0')")
    # Gmail Push: track last processed historyId (0 = not yet known / do full fetch)
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_history_id', '0')")
    
    # Email logs table (auto-replied emails)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            sender TEXT,
            subject TEXT,
            reply_body TEXT,
            timestamp TEXT
        )
    """)

    # Inbox capture table — records ALL incoming emails even if not replied
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inbox_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            sender TEXT,
            sender_name TEXT,
            subject TEXT,
            snippet TEXT,
            date TEXT,
            captured_at TEXT,
            is_replied INTEGER DEFAULT 0
        )
    """)
    
    conn.commit()
    conn.close()

def is_service_on() -> bool:
    """Check if the auto-reply service is turned ON."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'is_auto_reply_on'")
    result = cursor.fetchone()
    conn.close()
    return result[0] == 'true' if result else False

def set_service_state(is_on: bool):
    """Turn the auto-reply service ON or OFF."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    val = 'true' if is_on else 'false'
    cursor.execute("UPDATE settings SET value = ? WHERE key = 'is_auto_reply_on'", (val,))
    if is_on:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('service_start_time', ?)", (now,))
    else:
        cursor.execute("DELETE FROM settings WHERE key = 'service_start_time'")
    conn.commit()
    conn.close()

def get_service_start_time() -> Optional[str]:
    """Retrieve the service start timestamp (UTC)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'service_start_time'")
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def log_email(message_id: str, sender: str, subject: str, reply_body: str):
    """Log an email that was auto-replied to."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        INSERT OR IGNORE INTO email_logs (message_id, sender, subject, reply_body, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (message_id, sender, subject, reply_body, now))
    conn.commit()
    conn.close()

def get_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent auto-reply logs."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT message_id, sender, subject, reply_body, timestamp FROM email_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    logs = []
    for row in rows:
        logs.append({
            "message_id": row[0],
            "sender": row[1],
            "subject": row[2],
            "reply_body": row[3],
            "timestamp": row[4]
        })
    return logs

def get_sent_count() -> int:
    """Get the total number of emails auto-replied to."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM email_logs")
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def set_pending_count(count: int):
    """Set the number of pending unread emails."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = 'pending_count'", (str(count),))
    conn.commit()
    conn.close()

def get_pending_count() -> int:
    """Get the number of pending unread emails."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'pending_count'")
    result = cursor.fetchone()
    conn.close()
    return int(result[0]) if result else 0

# --- Inbox Capture Functions ---

def capture_inbox_email(message_id: str, sender: str, sender_name: str, subject: str, snippet: str, date: str):
    """
    Capture or update an incoming email in the inbox table.
    Uses UPSERT so re-fetched emails get updated snippet/date.
    The is_replied flag is preserved if the email already exists.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO inbox_emails (message_id, sender, sender_name, subject, snippet, date, captured_at, is_replied)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(message_id) DO UPDATE SET
            sender      = excluded.sender,
            sender_name = excluded.sender_name,
            subject     = excluded.subject,
            snippet     = excluded.snippet,
            date        = excluded.date
    """, (message_id, sender, sender_name or "", subject, snippet or "", date or "", now))
    conn.commit()
    conn.close()

def mark_inbox_email_replied(message_id: str):
    """Mark an inbox email as replied."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE inbox_emails SET is_replied = 1 WHERE message_id = ?", (message_id,))
    conn.commit()
    conn.close()

def is_already_replied(message_id: str) -> bool:
    """Check if we have already sent a reply to this email."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM email_logs WHERE message_id = ?", (message_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def get_inbox_emails(limit: int = 200, search: str = "") -> List[Dict[str, Any]]:
    """Get recently captured inbox emails, optionally filtered by search term."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if search:
        search_like = f"%{search}%"
        cursor.execute("""
            SELECT message_id, sender, sender_name, subject, snippet, date, captured_at, is_replied
            FROM inbox_emails
            WHERE sender LIKE ? OR sender_name LIKE ? OR subject LIKE ? OR snippet LIKE ?
            ORDER BY id DESC
            LIMIT ?
        """, (search_like, search_like, search_like, search_like, limit))
    else:
        cursor.execute("""
            SELECT message_id, sender, sender_name, subject, snippet, date, captured_at, is_replied
            FROM inbox_emails
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))

    rows = cursor.fetchall()
    conn.close()

    emails = []
    for row in rows:
        emails.append({
            "message_id": row[0],
            "sender": row[1],
            "sender_name": row[2],
            "subject": row[3],
            "snippet": row[4],
            "date": row[5],
            "captured_at": row[6],
            "is_replied": bool(row[7])
        })
    return emails

def get_inbox_count() -> int:
    """Get the total number of captured inbox emails."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM inbox_emails")
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0


# ---------------------------------------------------------------------------
# Gmail Push Notification: historyId persistence
# ---------------------------------------------------------------------------

def get_last_history_id() -> Optional[int]:
    """
    Retrieve the last Gmail historyId that was successfully processed.

    Returns 0 (or None) when no history has been recorded yet — the caller
    should fall back to a full unread-email fetch in that case.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'last_history_id'")
    result = cursor.fetchone()
    conn.close()
    if result and result[0] and result[0] != '0':
        return int(result[0])
    return None


def set_last_history_id(history_id: int) -> None:
    """
    Persist the latest successfully processed Gmail historyId.

    This is called after every successful webhook notification so that if the
    server restarts, we can resume from exactly where we left off using the
    Gmail History API — guaranteeing zero message loss.

    Parameters
    ----------
    history_id : int  — The new historyId to persist.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE settings SET value = ? WHERE key = 'last_history_id'",
        (str(history_id),)
    )
    conn.commit()
    conn.close()
