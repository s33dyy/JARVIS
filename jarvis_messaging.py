"""
jarvis_messaging.py
-------------------
iMessage integration for JARVIS using macOS AppleScript and the Messages SQLite database.

Requirements:
  - macOS with Messages app signed in to iMessage.
  - Full Disk Access granted to the terminal / process that runs JARVIS
    (System Settings → Privacy & Security → Full Disk Access) for DB reads.
"""

import sqlite3
import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_applescript(script: str) -> str:
    """Execute an AppleScript snippet and return its stdout."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def _messages_db() -> Path:
    """Return the path to the macOS Messages chat database."""
    return Path.home() / "Library" / "Messages" / "chat.db"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_imessage(contact: str, message: str) -> str:
    """
    Send an iMessage to *contact* using AppleScript.

    Parameters
    ----------
    contact : str
        Phone number, email address, or name recognised by the Messages app.
    message : str
        The body text to send.

    Returns
    -------
    str
        Confirmation or error description.
    """
    # Escape any double-quotes in user-supplied strings so the AppleScript
    # fragment stays valid.
    safe_contact = contact.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')

    script = f'''tell application "Messages"
    set targetService to 1st service whose service type = iMessage
    set targetBuddy to buddy "{safe_contact}" of targetService
    send "{safe_message}" to targetBuddy
end tell'''

    try:
        _run_applescript(script)
        return f"Message sent to {contact}, sir."
    except Exception as error:
        return f"Failed to send message to {contact}: {error}"

def send_whatsapp(contact: str, message: str) -> str:
    """
    Send a WhatsApp message (text or file) by looking up the contact in macOS Contacts,
    opening the whatsapp:// send URL, and sending the content via System Events.
    """
    import urllib.parse
    import time
    import os
    import re
    
    # 1. Resolve if message is a file path
    file_path = None
    cleaned_path = message.strip().strip("'\"").replace("\\", "/")
    
    possible_paths = [
        cleaned_path,
        os.path.join(os.getcwd(), cleaned_path),
    ]
    if cleaned_path.endswith(".exe"):
        no_exe = cleaned_path[:-4]
        possible_paths.extend([
            no_exe,
            os.path.join(os.getcwd(), no_exe)
        ])
        
    for p in possible_paths:
        if os.path.isfile(p):
            file_path = os.path.abspath(p)
            break

    safe_contact = contact.replace('"', '\\"')
    
    # 2. AppleScript to find the phone number
    contact_script = f'''tell application "Contacts"
        try
            set thePerson to first person whose name contains "{safe_contact}"
            set theNumber to value of first phone of thePerson
            return theNumber
        on error
            return ""
        end try
    end tell'''
    
    try:
        phone = _run_applescript(contact_script).strip()
        if not phone:
            return f"I couldn't find a phone number for {contact} in your macOS Contacts, sir."
            
        clean_phone = re.sub(r'\D', '', phone)
        if not clean_phone.startswith('91') and not clean_phone.startswith('1') and len(clean_phone) == 10:
            clean_phone = f"91{clean_phone}"
            
        if file_path:
            # Copy file to clipboard
            clip_script = f'set the clipboard to (POSIX file "{file_path}")'
            _run_applescript(clip_script)
            
            # Open WhatsApp, focus window, paste attachment, and send
            url = f"whatsapp://send?phone={clean_phone}"
            send_script = f'''do shell script "open '{url}'"
            delay 3.0
            tell application "System Events"
                tell process "WhatsApp"
                    set frontmost to true
                end tell
                delay 0.5
                -- Cmd+V to paste the attachment
                key code 9 using command down
                delay 1.5
                -- Enter to send
                keystroke return
            end tell'''
            _run_applescript(send_script)
            return f"WhatsApp file {os.path.basename(file_path)} sent to {contact}, sir."
        else:
            # Send normal text message
            safe_message = urllib.parse.quote(message)
            url = f"whatsapp://send?phone={clean_phone}&text={safe_message}"
            
            send_script = f'''do shell script "open '{url}'"
            delay 2.5
            tell application "System Events"
                tell process "WhatsApp"
                    set frontmost to true
                end tell
                delay 0.5
                keystroke return
            end tell'''
            _run_applescript(send_script)
            return f"WhatsApp message sent to {contact}, sir."
            
    except Exception as error:
        return f"Failed to send WhatsApp to {contact}: {error}"

def get_recent_messages(contact: str = "", limit: int = 5) -> str:
    """
    Retrieve the most recent iMessages from the local Messages database.

    Parameters
    ----------
    contact : str, optional
        If provided, filter results to messages whose chat handle contains
        this name/number (case-insensitive substring match).
    limit : int
        Maximum number of messages to return (default 5).

    Returns
    -------
    str
        A formatted summary of the messages, or an error description.
    """
    db_path = _messages_db()

    if not db_path.exists():
        return (
            "Messages database not found. "
            "Ensure iMessage is set up on this Mac, sir."
        )

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if contact:
            # Join with handle table to filter by contact
            sql = """
                SELECT
                    m.text,
                    m.is_from_me,
                    datetime((m.date / 1000000000) + 978307200,
                             'unixepoch', 'localtime') AS ts,
                    h.id AS handle_id
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.rowid
                WHERE h.id LIKE ?
                ORDER BY m.date DESC
                LIMIT ?
            """
            rows = cursor.execute(sql, (f"%{contact}%", limit)).fetchall()
        else:
            sql = """
                SELECT
                    text,
                    is_from_me,
                    datetime((date / 1000000000) + 978307200,
                             'unixepoch', 'localtime') AS ts
                FROM message
                ORDER BY date DESC
                LIMIT ?
            """
            rows = cursor.execute(sql, (limit,)).fetchall()

        conn.close()

        if not rows:
            return "No messages found, sir."

        parts = []
        for row in rows:
            text = row["text"] or "(media/attachment)"
            ts = row["ts"] or "unknown time"
            # Show only HH:MM from the timestamp
            time_str = ts.split(" ")[-1][:5] if " " in ts else ts
            sender = "You" if row["is_from_me"] else (
                row["handle_id"] if "handle_id" in row.keys() else "Them"
            )
            parts.append(f"[{sender}: {text} ({time_str})]")

        return "Latest messages: " + ", ".join(parts)

    except sqlite3.OperationalError as exc:
        if "unable to open" in str(exc) or "permission" in str(exc).lower():
            return (
                "Permission denied reading Messages database. "
                "Please grant Full Disk Access to this terminal in "
                "System Settings → Privacy & Security → Full Disk Access, sir."
            )
        return f"Database error while reading messages: {exc}"
    except Exception as exc:
        return f"Unexpected error reading messages: {exc}"


def read_unread_messages() -> str:
    """
    Return a summary of all unread iMessages from the local database.

    Returns
    -------
    str
        Count and preview of unread messages, or a status string.
    """
    db_path = _messages_db()

    if not db_path.exists():
        return (
            "Messages database not found. "
            "Ensure iMessage is set up on this Mac, sir."
        )

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        sql = """
            SELECT
                m.text,
                m.is_from_me,
                datetime((m.date / 1000000000) + 978307200,
                         'unixepoch', 'localtime') AS ts,
                h.id AS handle_id
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.rowid
            WHERE m.is_read = 0
              AND m.is_from_me = 0
            ORDER BY m.date DESC
        """
        rows = cursor.execute(sql).fetchall()
        conn.close()

        if not rows:
            return "No unread messages, sir."

        parts = []
        for row in rows:
            text = row["text"] or "(media/attachment)"
            ts = row["ts"] or "unknown time"
            time_str = ts.split(" ")[-1][:5] if " " in ts else ts
            sender = row["handle_id"] or "Unknown"
            parts.append(f"[{sender}: {text} ({time_str})]")

        n = len(parts)
        return f"You have {n} unread message{'s' if n != 1 else ''}: " + ", ".join(parts)

    except sqlite3.OperationalError as exc:
        if "unable to open" in str(exc) or "permission" in str(exc).lower():
            return (
                "Permission denied reading Messages database. "
                "Please grant Full Disk Access to this terminal in "
                "System Settings → Privacy & Security → Full Disk Access, sir."
            )
        return f"Database error while reading unread messages: {exc}"
    except Exception as exc:
        return f"Unexpected error reading unread messages: {exc}"


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(get_recent_messages(limit=3))
    print(read_unread_messages())
