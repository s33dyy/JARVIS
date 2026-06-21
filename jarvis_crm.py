"""
jarvis_crm.py
─────────────
Auto-CRM: reads iMessage (chat.db), WhatsApp (native app notifications
via NSUserNotificationCenter fallback), and any other messaging app's
notification to build a lightweight CRM in memory.json.

Architecture:
  1. _read_imessage_db()       — reads ~/Library/Messages/chat.db
  2. _read_whatsapp_recent()   — reads WhatsApp macOS export folder if exists
  3. background_crm_processor() — batches all raw messages, calls local LLM,
                                  writes structured insights to memory.json
  4. start_auto_crm()          — launches the daemon thread

CRM schema (inside memory.json["crm"]):
  {
    "contact":   "John",
    "app":       "iMessage",
    "last_seen": "2026-06-19T22:30:00",
    "mood":      "positive",
    "topics":    ["project deadline", "lunch"],
    "action_items": ["Send report by Friday"],
    "messages_analyzed": 3
  }
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ── Memory helpers ────────────────────────────────────────────────────────────
from jarvis_memory import load, save

# ── Config ────────────────────────────────────────────────────────────────────
CHAT_DB       = Path.home() / "Library" / "Messages" / "chat.db"
WA_EXPORT_DIR = Path.home() / "Library" / "Containers" / \
                "net.whatsapp.WhatsApp" / "Data" / "Documents"
POLL_INTERVAL = 300          # seconds between CRM sweeps
LOOKBACK_MINS = 60           # how many minutes of history to analyze per sweep
MAX_MSGS      = 50           # max messages to process per contact per sweep


# ─────────────────────────────────────────────────────────────────────────────
# 1. iMessage reader (reads chat.db)
# ─────────────────────────────────────────────────────────────────────────────
def _read_imessage_db(since_minutes: int = LOOKBACK_MINS) -> list[dict]:
    """
    Returns a list of recent iMessage messages.
    Requires Full Disk Access for the terminal / app in System Preferences.
    """
    if not CHAT_DB.exists():
        return []
    try:
        cutoff_ts = int((datetime.now() - timedelta(minutes=since_minutes)).timestamp())
        # iMessage stores timestamps as nanoseconds since 2001-01-01
        apple_epoch_offset = 978307200
        cutoff_apple = (cutoff_ts - apple_epoch_offset) * 1_000_000_000

        conn = sqlite3.connect(str(CHAT_DB), timeout=5)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT
                m.text,
                m.is_from_me,
                m.date,
                h.id AS contact_id,
                COALESCE(h.uncanonicalized_id, h.id) AS display_name
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.text IS NOT NULL
              AND m.text != ''
              AND m.date > ?
            ORDER BY m.date DESC
            LIMIT ?
        """, (cutoff_apple, MAX_MSGS))
        rows = cur.fetchall()
        conn.close()

        messages = []
        for row in rows:
            ts_apple = row["date"]
            ts_unix  = (ts_apple / 1_000_000_000) + apple_epoch_offset
            messages.append({
                "app":       "iMessage",
                "sender":    "Me" if row["is_from_me"] else (row["display_name"] or "Unknown"),
                "content":   (row["text"] or "").strip(),
                "timestamp": datetime.fromtimestamp(ts_unix).isoformat(),
                "is_from_me": bool(row["is_from_me"]),
            })
        return messages
    except Exception as e:
        print(f"[Auto-CRM] iMessage read failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 2. WhatsApp reader (macOS .txt export or fallback Notification center)
# ─────────────────────────────────────────────────────────────────────────────
def _read_whatsapp_exports() -> list[dict]:
    """
    Reads any WhatsApp chat exports (.txt) the user has placed in ~/Documents/WhatsApp.
    Also checks the macOS WhatsApp container for any exported chats.
    """
    results = []
    search_dirs = [
        Path.home() / "Documents" / "WhatsApp",
        WA_EXPORT_DIR,
    ]
    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.rglob("*.txt"):
            try:
                text = f.read_text(errors="ignore")
                for line in text.splitlines()[-100:]:   # last 100 lines
                    # WhatsApp format: [DD/MM/YY, HH:MM:SS] Name: Message
                    m = re.match(r"\[(.+?)\] (.+?): (.+)", line)
                    if m:
                        results.append({
                            "app":       "WhatsApp",
                            "sender":    m.group(2).strip(),
                            "content":   m.group(3).strip(),
                            "timestamp": m.group(1).strip(),
                            "is_from_me": False,
                        })
            except Exception:
                pass
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 3. Lightweight local rule-based extraction (no LLM needed for basics)
# ─────────────────────────────────────────────────────────────────────────────
_POSITIVE = re.compile(r"\b(great|awesome|yes|sure|sounds good|love it|perfect|thanks|thank you|appreciate|happy|excited|brilliant)\b", re.I)
_NEGATIVE = re.compile(r"\b(no|can't|cannot|won't|busy|not now|later|sorry|unfortunately|disappointed|bad|problem|issue|urgent|asap)\b", re.I)
_ACTION   = re.compile(r"\b(send|call me|let'?s (meet|chat|talk|do)|please|can you|could you|by (monday|tuesday|wednesday|thursday|friday|eod|tomorrow|end of day)|by \d+)\b", re.I)
_TOPICS   = re.compile(r"\b(meeting|project|deadline|budget|payment|invoice|contract|proposal|launch|release|review|interview|report|presentation|demo|feedback)\b", re.I)

def _extract_crm_facts(messages: list[dict]) -> dict:
    """Rule-based CRM extraction — fast, no LLM, works offline."""
    if not messages:
        return {}

    # Group by sender (excluding self)
    by_contact: dict[str, list[dict]] = {}
    for msg in messages:
        if msg["is_from_me"]:
            continue
        name = msg["sender"]
        by_contact.setdefault(name, []).append(msg)

    crm_updates = {}
    for contact, msgs in by_contact.items():
        combined = " ".join(m["content"] for m in msgs)
        pos = len(_POSITIVE.findall(combined))
        neg = len(_NEGATIVE.findall(combined))
        mood = "positive" if pos > neg else ("negative" if neg > pos else "neutral")
        topics = list({t.lower() for t in _TOPICS.findall(combined)})
        actions = []
        for m in msgs:
            if _ACTION.search(m["content"]):
                actions.append(m["content"][:120])

        crm_updates[contact] = {
            "contact":          contact,
            "app":              msgs[0]["app"],
            "last_seen":        msgs[0]["timestamp"],
            "mood":             mood,
            "topics":           topics[:5],
            "action_items":     actions[:3],
            "messages_analyzed": len(msgs),
            "updated_at":       datetime.now().isoformat(),
        }
    return crm_updates


def _try_llm_enrich(contact: str, text: str) -> Optional[str]:
    """
    Optional: run local MLX LLM to generate a 1-sentence CRM insight.
    Silently skipped if MLX is not running.
    """
    try:
        from jarvis_actions import _llm
        prompt = (
            f"In one sentence, summarize the relationship context or next steps "
            f"based on this recent conversation with {contact}: \"{text[:400]}\""
        )
        return _llm(prompt, max_tokens=80)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Background daemon
# ─────────────────────────────────────────────────────────────────────────────
def background_crm_processor():
    """Periodic sweep: reads messages → extracts CRM facts → writes to memory."""
    print("[Auto-CRM] Started background processor")
    while True:
        try:
            # Collect messages from all sources
            all_messages: list[dict] = []

            # iMessage
            im_msgs = _read_imessage_db()
            all_messages.extend(im_msgs)
            if im_msgs:
                print(f"[Auto-CRM] Read {len(im_msgs)} iMessages")

            # WhatsApp exports
            wa_msgs = _read_whatsapp_exports()
            all_messages.extend(wa_msgs)
            if wa_msgs:
                print(f"[Auto-CRM] Read {len(wa_msgs)} WhatsApp messages")

            # Also drain any raw_messages from the queue (other modules may push here)
            mem = load()
            raw_queue = mem.pop("raw_messages_queue", [])
            all_messages.extend(raw_queue)

            if all_messages:
                # Rule-based extraction (always runs)
                crm_updates = _extract_crm_facts(all_messages)

                # Optional LLM enrichment for most recent contact
                for contact, facts in list(crm_updates.items())[:3]:
                    recent_text = " ".join(
                        m["content"] for m in all_messages
                        if m["sender"] == contact
                    )[:400]
                    llm_insight = _try_llm_enrich(contact, recent_text)
                    if llm_insight:
                        facts["llm_insight"] = llm_insight

                # Merge into memory
                crm = mem.get("crm", {})
                crm.update(crm_updates)
                mem["crm"] = crm
                save(mem)
                print(f"[Auto-CRM] Updated CRM for {len(crm_updates)} contact(s): {list(crm_updates.keys())}")

        except Exception as e:
            print(f"[Auto-CRM] Error in sweep: {e}")

        time.sleep(POLL_INTERVAL)


def start_auto_crm():
    """Launch the Auto-CRM daemon thread."""
    t = threading.Thread(target=background_crm_processor, daemon=True, name="auto-crm")
    t.start()
    return t


# ─────────────────────────────────────────────────────────────────────────────
# 5. CRM query helpers (called from action router)
# ─────────────────────────────────────────────────────────────────────────────
def get_crm_summary(contact: Optional[str] = None) -> str:
    """Return a human-readable CRM summary for a specific contact or all contacts."""
    try:
        mem = load()
        crm = mem.get("crm", {})
        if not crm:
            return "No CRM data yet. I'll start building it from your messages."

        if contact:
            # Fuzzy match
            key = next((k for k in crm if contact.lower() in k.lower()), None)
            if not key:
                return f"No CRM data for {contact} yet."
            d = crm[key]
            items = ", ".join(d.get("action_items", [])) or "none"
            topics = ", ".join(d.get("topics", [])) or "general"
            insight = d.get("llm_insight", "")
            return (
                f"{key} via {d.get('app','?')} — mood: {d.get('mood','?')}, "
                f"topics: {topics}. Action items: {items}."
                + (f" {insight}" if insight else "")
            )
        else:
            lines = []
            for k, d in list(crm.items())[:5]:
                lines.append(f"• {k} ({d.get('app','?')}): {d.get('mood','?')} mood, {d.get('last_seen','')[:10]}")
            return "Recent contacts:\n" + "\n".join(lines)
    except Exception as e:
        return f"CRM lookup error: {e}"
