"""
JARVIS Google API layer — Calendar, Gmail, Drive, Contacts.

All functions use the shared OAuth token stored by `jarvis connect`.
Token auto-refreshes on 401. Every function returns (result, error_str).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

HOME        = Path.home()
CREDS_PATH  = str(HOME / ".openjarvis" / "connectors" / "google.json")
CALENDAR_ID = "primary"


# ─────────────────────────────────────────────────────────────
# Token management
# ─────────────────────────────────────────────────────────────
def _get_token() -> Optional[str]:
    """Return a valid access token, refreshing if stored one is expired."""
    try:
        from openjarvis.connectors.oauth import load_tokens, refresh_google_token
        tokens = load_tokens(CREDS_PATH)
        if not tokens:
            return None
        token = tokens.get("access_token") or tokens.get("token", "")
        return token or refresh_google_token(CREDS_PATH)
    except Exception:
        return None


def _auth_get(url: str, **kwargs) -> httpx.Response:
    token = _get_token()
    if not token:
        raise RuntimeError("Not connected to Google. Run: jarvis connect gdrive")
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    resp = httpx.get(url, headers=headers, timeout=15, **kwargs)
    if resp.status_code == 401:
        from openjarvis.connectors.oauth import refresh_google_token
        token = refresh_google_token(CREDS_PATH)
        headers["Authorization"] = f"Bearer {token}"
        resp = httpx.get(url, headers=headers, timeout=15, **kwargs)
    return resp


def _auth_post(url: str, **kwargs) -> httpx.Response:
    token = _get_token()
    if not token:
        raise RuntimeError("Not connected to Google. Run: jarvis connect gdrive")
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    resp = httpx.post(url, headers=headers, timeout=15, **kwargs)
    if resp.status_code == 401:
        from openjarvis.connectors.oauth import refresh_google_token
        token = refresh_google_token(CREDS_PATH)
        headers["Authorization"] = f"Bearer {token}"
        resp = httpx.post(url, headers=headers, timeout=15, **kwargs)
    return resp


def is_connected() -> bool:
    """Check if Google OAuth tokens are present."""
    try:
        from openjarvis.connectors.oauth import load_tokens
        tokens = load_tokens(CREDS_PATH)
        return bool(tokens and tokens.get("access_token"))
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# Google Calendar
# ─────────────────────────────────────────────────────────────
def get_events(days_offset: int = 0) -> tuple[list[dict], str]:
    """Return calendar events for a specific day as list of dicts."""
    try:
        now = datetime.now(timezone.utc) + timedelta(days=days_offset)
        time_min = now.replace(hour=0, minute=0, second=0).isoformat()
        time_max = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0).isoformat()
        resp = _auth_get(
            f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events",
            params={
                "timeMin": time_min, "timeMax": time_max,
                "singleEvents": "true", "orderBy": "startTime", "maxResults": 20,
            },
        )
        if resp.status_code != 200:
            return [], f"Calendar API error: {resp.status_code}"
        events = []
        for item in resp.json().get("items", []):
            start_raw = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
            try:
                dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                start_str = dt.astimezone().strftime("%I:%M %p")
            except Exception:
                start_str = start_raw or "All day"
            events.append({
                "id":       item.get("id"),
                "title":    item.get("summary", "Untitled"),
                "start":    start_str,
                "location": item.get("location", ""),
                "attendees": [a.get("email") for a in item.get("attendees", [])],
            })
        return events, ""
    except Exception as e:
        return [], str(e)


def create_calendar_event(
    title: str,
    start_dt: datetime,
    end_dt: Optional[datetime] = None,
    attendees: Optional[list[str]] = None,
    location: str = "",
    description: str = "",
    recurrence: Optional[str] = None,  # RRULE string e.g. "FREQ=WEEKLY;BYDAY=MO,TU"
) -> tuple[str, str]:
    """
    Create a Google Calendar event.
    Returns (event_url, error_str).
    """
    if end_dt is None:
        end_dt = start_dt + timedelta(hours=1)

    body: dict = {
        "summary": title,
        "start":   {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Kolkata"},
        "end":     {"dateTime": end_dt.isoformat(),   "timeZone": "Asia/Kolkata"},
    }
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]
    if recurrence:
        body["recurrence"] = [f"RRULE:{recurrence}"]

    try:
        resp = _auth_post(
            f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events",
            headers={"Content-Type": "application/json"},
            content=json.dumps(body),
        )
        if resp.status_code not in (200, 201):
            return "", f"Calendar API error {resp.status_code}: {resp.text[:200]}"
        event = resp.json()
        link = event.get("htmlLink", "")
        return link, ""
    except Exception as e:
        return "", str(e)


def find_free_slots(duration_minutes: int = 60, days_ahead: int = 3) -> list[str]:
    """Find free time slots in the next N days (simple gap-finding)."""
    try:
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days_ahead)).isoformat()
        resp = _auth_get(
            f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events",
            params={
                "timeMin": time_min, "timeMax": time_max,
                "singleEvents": "true", "orderBy": "startTime", "maxResults": 50,
            },
        )
        if resp.status_code != 200:
            return []
        busy_slots = []
        for item in resp.json().get("items", []):
            s = item.get("start", {}).get("dateTime")
            e = item.get("end", {}).get("dateTime")
            if s and e:
                busy_slots.append((
                    datetime.fromisoformat(s.replace("Z", "+00:00")),
                    datetime.fromisoformat(e.replace("Z", "+00:00")),
                ))
        busy_slots.sort()

        # Find gaps ≥ duration during working hours (9am–6pm IST)
        free_slots = []
        tz_offset = timedelta(hours=5, minutes=30)
        current = now + timedelta(hours=1)  # start 1 hour from now
        end_search = now + timedelta(days=days_ahead)
        while current < end_search and len(free_slots) < 5:
            local = current + tz_offset
            # Only working hours
            if 9 <= local.hour < 18:
                slot_end = current + timedelta(minutes=duration_minutes)
                clash = any(s < slot_end and e > current for s, e in busy_slots)
                if not clash:
                    free_slots.append((current + tz_offset).strftime("%a %d %b, %I:%M %p IST"))
            current += timedelta(minutes=30)
        return free_slots
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# Gmail
# ─────────────────────────────────────────────────────────────
def get_unread_emails(max_results: int = 5) -> tuple[list[dict], str]:
    """Return up to N unread emails with subject, sender, snippet."""
    try:
        resp = _auth_get(
            "https://www.googleapis.com/gmail/v1/users/me/messages",
            params={"q": "is:unread", "maxResults": max_results},
        )
        if resp.status_code != 200:
            return [], f"Gmail API error: {resp.status_code}"
        messages = resp.json().get("messages", [])
        emails = []
        for msg in messages:
            msg_resp = _auth_get(
                f"https://www.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
            )
            if msg_resp.status_code != 200:
                continue
            data = msg_resp.json()
            headers = {h["name"]: h["value"]
                       for h in data.get("payload", {}).get("headers", [])}
            emails.append({
                "id":      msg["id"],
                "subject": headers.get("Subject", "(no subject)"),
                "from":    headers.get("From", "?"),
                "date":    headers.get("Date", ""),
                "snippet": data.get("snippet", "")[:200],
                "thread_id": data.get("threadId", ""),
            })
        return emails, ""
    except Exception as e:
        return [], str(e)


def get_email_thread(thread_id: str) -> tuple[str, str]:
    """Get the full text of an email thread."""
    try:
        import base64
        resp = _auth_get(
            f"https://www.googleapis.com/gmail/v1/users/me/threads/{thread_id}",
            params={"format": "full"},
        )
        if resp.status_code != 200:
            return "", f"Gmail API error: {resp.status_code}"
        messages = resp.json().get("messages", [])
        parts = []
        for msg in messages[-3:]:  # last 3 messages in thread
            headers = {h["name"]: h["value"]
                       for h in msg.get("payload", {}).get("headers", [])}
            body_parts = msg.get("payload", {}).get("parts", [])
            body_text = ""
            for part in body_parts:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        body_text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
                        break
            if not body_text:
                data = msg.get("payload", {}).get("body", {}).get("data", "")
                if data:
                    body_text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            parts.append(
                f"From: {headers.get('From','?')}\n"
                f"Subject: {headers.get('Subject','?')}\n"
                f"{body_text[:800]}"
            )
        return "\n---\n".join(parts), ""
    except Exception as e:
        return "", str(e)


def send_email(to: str, subject: str, body: str) -> tuple[bool, str]:
    """Send an email via Gmail API."""
    import base64
    from email.mime.text import MIMEText
    try:
        msg = MIMEText(body)
        msg["to"]      = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        resp = _auth_post(
            "https://www.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Content-Type": "application/json"},
            content=json.dumps({"raw": raw}),
        )
        if resp.status_code not in (200, 201):
            return False, f"Gmail send error {resp.status_code}: {resp.text[:200]}"
        return True, ""
    except Exception as e:
        return False, str(e)


def draft_email(to: str, subject: str, body: str) -> tuple[str, str]:
    """Save an email as a Gmail draft. Returns (draft_id, error)."""
    import base64
    from email.mime.text import MIMEText
    try:
        msg = MIMEText(body)
        msg["to"]      = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        resp = _auth_post(
            "https://www.googleapis.com/gmail/v1/users/me/drafts",
            headers={"Content-Type": "application/json"},
            content=json.dumps({"message": {"raw": raw}}),
        )
        if resp.status_code not in (200, 201):
            return "", f"Draft error {resp.status_code}: {resp.text[:200]}"
        return resp.json().get("id", ""), ""
    except Exception as e:
        return "", str(e)


# ─────────────────────────────────────────────────────────────
# Google Drive
# ─────────────────────────────────────────────────────────────
def search_drive(query: str, max_results: int = 5) -> tuple[list[dict], str]:
    """Search Google Drive for files matching query."""
    try:
        resp = _auth_get(
            "https://www.googleapis.com/drive/v3/files",
            params={
                "q": f"name contains '{query}' and trashed=false",
                "pageSize": max_results,
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
                "orderBy": "modifiedTime desc",
            },
        )
        if resp.status_code != 200:
            return [], f"Drive API error: {resp.status_code}"
        files = []
        for f in resp.json().get("files", []):
            files.append({
                "name":     f.get("name", "?"),
                "type":     f.get("mimeType", "").split(".")[-1],
                "modified": f.get("modifiedTime", "")[:10],
                "link":     f.get("webViewLink", ""),
            })
        return files, ""
    except Exception as e:
        return [], str(e)


def get_recent_drive_files(max_results: int = 5) -> tuple[list[dict], str]:
    """Get most recently modified Drive files."""
    try:
        resp = _auth_get(
            "https://www.googleapis.com/drive/v3/files",
            params={
                "q": "trashed=false",
                "pageSize": max_results,
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
                "orderBy": "modifiedTime desc",
            },
        )
        if resp.status_code != 200:
            return [], f"Drive API error: {resp.status_code}"
        files = []
        for f in resp.json().get("files", []):
            files.append({
                "name":     f.get("name", "?"),
                "modified": f.get("modifiedTime", "")[:10],
                "link":     f.get("webViewLink", ""),
            })
        return files, ""
    except Exception as e:
        return [], str(e)


# ─────────────────────────────────────────────────────────────
# Google Contacts (for meeting scheduling — find email by name)
# ─────────────────────────────────────────────────────────────
def find_contact_email(name: str) -> Optional[str]:
    """Look up a contact's email by name."""
    try:
        resp = _auth_get(
            "https://people.googleapis.com/v1/people:searchContacts",
            params={"query": name, "readMask": "names,emailAddresses", "pageSize": 5},
        )
        if resp.status_code != 200:
            return None
        results = resp.json().get("results", [])
        for r in results:
            emails = r.get("person", {}).get("emailAddresses", [])
            if emails:
                return emails[0].get("value")
        return None
    except Exception:
        return None
