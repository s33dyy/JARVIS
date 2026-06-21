"""
jarvis_memory.py
----------------
Persistent conversational memory module for JARVIS.

Stores conversation history and extracted facts in ~/.jarvis/memory.json.
Provides helpers for LLM prompt injection and lightweight regex-based
fact extraction — no external dependencies required.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Storage path
# ---------------------------------------------------------------------------

_MEMORY_DIR = Path.home() / ".jarvis"
_MEMORY_FILE = _MEMORY_DIR / "memory.json"
_MAX_CONVERSATIONS = 50


# ---------------------------------------------------------------------------
# Default schema
# ---------------------------------------------------------------------------

def _default_data() -> dict:
    return {
        "conversations": [],
        "facts": {
            "user_name": "",
            "preferred_name": "sir",
            "projects": [],
            "preferences": {},
            "behavioral_profile": {
                "tone": "Formal and concise.",
                "coaching_style": "Supportive",
                "task_completion_rate": 1.0,
                "completed_count": 0,
                "overdue_count": 0
            }
        },
    }


# ---------------------------------------------------------------------------
# Low-level helpers: load / save
# ---------------------------------------------------------------------------

def load() -> dict:
    """
    Load memory from disk.  Returns the default schema if the file does not
    exist or is corrupted.
    """
    try:
        if not _MEMORY_FILE.exists():
            return _default_data()
        with _MEMORY_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Ensure all top-level keys exist (forward-compatible)
        default = _default_data()
        for key, default_val in default.items():
            data.setdefault(key, default_val)
        # Ensure all fact keys exist
        for key, default_val in default["facts"].items():
            data["facts"].setdefault(key, default_val)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[memory] Warning: could not load memory file ({exc}). Starting fresh.")
        return _default_data()


def save(data: dict) -> None:
    """
    Persist *data* to disk, creating ~/.jarvis/ if needed.
    """
    try:
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        with _MEMORY_FILE.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except OSError as exc:
        print(f"[memory] Warning: could not save memory file ({exc}).")


# ---------------------------------------------------------------------------
# Conversation management
# ---------------------------------------------------------------------------

def add_exchange(user_msg: str, jarvis_msg: str) -> None:
    """
    Append a user/JARVIS exchange to conversation history.
    Keeps only the most recent _MAX_CONVERSATIONS entries.
    Also triggers lightweight fact extraction.
    """
    data = load()

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user_msg,
        "jarvis": jarvis_msg,
    }
    data["conversations"].append(entry)

    # Trim to the last N conversations
    if len(data["conversations"]) > _MAX_CONVERSATIONS:
        data["conversations"] = data["conversations"][-_MAX_CONVERSATIONS:]

    save(data)

    # Side-effect: try to extract facts from this exchange
    extract_and_save_facts(user_msg, jarvis_msg)


def get_recent_exchanges(n: int = 5) -> list[dict]:
    """
    Return the last *n* conversation entries (oldest first).
    Each entry has keys: 'ts', 'user', 'jarvis'.
    """
    data = load()
    conversations = data.get("conversations", [])
    return conversations[-n:] if conversations else []


# ---------------------------------------------------------------------------
# Context string for LLM injection
# ---------------------------------------------------------------------------

def get_memory_context() -> str:
    """
    Return a compact single-line string summarising recent conversations and
    known facts, suitable for prepending to an LLM system prompt.

    Example output:
        "Recent: User asked about OpenJarvis. JARVIS replied about git status. |
         Known facts: user_name=Pratik, preferred_name=sir, projects=[OpenJarvis]"
    """
    data = load()
    facts = data.get("facts", {})
    conversations = data.get("conversations", [])

    # --- Recent conversation summary ---
    recent = conversations[-3:] if conversations else []
    convo_parts: list[str] = []
    for ex in recent:
        u = _truncate(ex.get("user", ""), 60)
        j = _truncate(ex.get("jarvis", ""), 60)
        if u:
            convo_parts.append(f"User: {u}")
        if j:
            convo_parts.append(f"JARVIS: {j}")

    convo_str = " | ".join(convo_parts) if convo_parts else "None"

    # --- Facts summary ---
    fact_parts: list[str] = []
    if facts.get("user_name"):
        fact_parts.append(f"user_name={facts['user_name']}")
    if facts.get("preferred_name"):
        fact_parts.append(f"preferred_name={facts['preferred_name']}")
    projects = facts.get("projects", [])
    if projects:
        fact_parts.append(f"projects={projects}")
    prefs = facts.get("preferences", {})
    if prefs:
        prefs_str = ", ".join(f"{k}={v}" for k, v in list(prefs.items())[:5])
        fact_parts.append(f"preferences={{{prefs_str}}}")

    facts_str = ", ".join(fact_parts) if fact_parts else "none"

    return f"Recent: {convo_str} | Known facts: {facts_str}"


def update_behavioral_profile(completed: int, overdue: int) -> None:
    """
    Evolve JARVIS's persona based on the user's task completion stats.
    Called periodically by the autonomous planner.
    """
    data = load()
    profile = data["facts"].setdefault("behavioral_profile", {
        "tone": "Formal and concise.",
        "coaching_style": "Supportive",
        "task_completion_rate": 1.0,
        "completed_count": 0,
        "overdue_count": 0
    })
    
    # Update stats
    profile["completed_count"] = completed
    profile["overdue_count"] = overdue
    total = completed + overdue
    
    if total > 0:
        rate = completed / total
        profile["task_completion_rate"] = rate
        
        # Evolve coaching style based on rate
        if rate < 0.3:
            profile["coaching_style"] = "Strict, firm, and demanding. You act as an accountability coach who does not accept excuses."
            profile["tone"] = "Direct and slightly disappointed. High urgency."
        elif rate < 0.6:
            profile["coaching_style"] = "Encouraging but firm. Pushing the user to focus."
            profile["tone"] = "Motivating."
        elif rate >= 0.8:
            profile["coaching_style"] = "Highly supportive and relaxed. You mirror the user's success."
            profile["tone"] = "Warm, colloquial, mirroring the user."
            
    save(data)


# ---------------------------------------------------------------------------
# Lightweight fact extraction (regex-based, no LLM)
# ---------------------------------------------------------------------------

# Patterns for name extraction
_NAME_PATTERNS = [
    re.compile(r"\bmy name is\s+([A-Z][a-zA-Z\-']+)", re.IGNORECASE),
    re.compile(r"\bcall me\s+([A-Z][a-zA-Z\-']+)", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am)\s+([A-Z][a-zA-Z\-']+)", re.IGNORECASE),
    re.compile(r"\bthe name(?:'s| is)\s+([A-Z][a-zA-Z\-']+)", re.IGNORECASE),
]

# Pattern for preferred salutation
_PREFERRED_NAME_PATTERNS = [
    re.compile(r"\bcall me\s+(sir|boss|buddy|mate|chief|captain|doc)\b", re.IGNORECASE),
    re.compile(r"\bprefer(?:red)?\s+(?:to be called|name)\s+([A-Za-z]+)", re.IGNORECASE),
]

# Pattern for project mentions
_PROJECT_PATTERNS = [
    re.compile(r"\bproject(?:s)?\s+(?:called\s+|named\s+)?([A-Z][A-Za-z0-9_\-]+)", re.IGNORECASE),
    re.compile(r"\bworking on\s+([A-Z][A-Za-z0-9_\-]+)", re.IGNORECASE),
    re.compile(r"\brepo(?:sitory)?\s+(?:called\s+|named\s+)?([A-Z][A-Za-z0-9_\-]+)", re.IGNORECASE),
    re.compile(r"\bapp(?:lication)?\s+(?:called\s+|named\s+)?([A-Z][A-Za-z0-9_\-]+)", re.IGNORECASE),
]

# Pattern for simple preferences  ("I prefer dark mode", "I like Python")
_PREFERENCE_PATTERNS = [
    re.compile(r"\bi (?:prefer|like|love|use|want)\s+([a-zA-Z][a-zA-Z0-9 _\-]+?)(?:\.|,|$)", re.IGNORECASE),
    re.compile(r"\bmy (?:favourite|favorite|preferred)\s+\w+\s+is\s+([a-zA-Z][a-zA-Z0-9 _\-]+?)(?:\.|,|$)", re.IGNORECASE),
]

# Words to exclude from project/preference extraction (too generic)
_STOP_WORDS = {
    "the", "a", "an", "this", "that", "it", "i", "you", "we", "they",
    "is", "are", "was", "be", "to", "of", "and", "or", "in", "on",
    "with", "for", "at", "by", "from", "up", "out", "also", "just",
    "more", "some", "much", "many", "so", "my", "your",
}


def extract_and_save_facts(user_msg: str, jarvis_msg: str) -> None:
    """
    Parse *user_msg* (and optionally *jarvis_msg*) with regex to detect and
    persist factual tidbits about the user.

    Recognised patterns (case-insensitive):
      - "my name is X" / "call me X" / "I'm X"  → facts.user_name
      - "call me sir/boss/…"                      → facts.preferred_name
      - "project X" / "working on X" / "repo X"  → facts.projects (deduplicated)
      - "I prefer/like/love X"                    → facts.preferences
    """
    data = load()
    facts: dict[str, Any] = data["facts"]
    changed = False

    combined = f"{user_msg} {jarvis_msg}"

    # -- User name --
    for pat in _NAME_PATTERNS:
        m = pat.search(user_msg)
        if m:
            name = m.group(1).strip().title()
            if name.lower() not in _STOP_WORDS and len(name) > 1:
                facts["user_name"] = name
                changed = True
                break

    # -- Preferred salutation --
    for pat in _PREFERRED_NAME_PATTERNS:
        m = pat.search(user_msg)
        if m:
            pref = m.group(1).strip().lower()
            if pref:
                facts["preferred_name"] = pref
                changed = True
                break

    # -- Projects --
    projects: list[str] = facts.get("projects", [])
    for pat in _PROJECT_PATTERNS:
        for m in pat.finditer(combined):
            proj = m.group(1).strip()
            if proj.lower() not in _STOP_WORDS and len(proj) > 2 and proj not in projects:
                projects.append(proj)
                changed = True
    facts["projects"] = projects

    # -- Preferences --
    prefs: dict[str, str] = facts.get("preferences", {})
    for pat in _PREFERENCE_PATTERNS:
        for m in pat.finditer(user_msg):
            raw = m.group(1).strip()
            words = raw.split()
            if not words:
                continue
            key_word = words[0].lower()
            if key_word in _STOP_WORDS or len(key_word) < 2:
                continue
            # Use first non-stopword as the preference key
            value = raw
            if key_word not in prefs:
                prefs[key_word] = value
                changed = True
    facts["preferences"] = prefs

    if changed:
        data["facts"] = facts
        save(data)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int) -> str:
    """Truncate *text* to *max_len* characters, appending '…' if needed."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


def clear_conversations() -> None:
    """Erase all conversation history (facts are preserved)."""
    data = load()
    data["conversations"] = []
    save(data)
    print("[memory] Conversation history cleared.")


def clear_all() -> None:
    """Reset memory entirely to defaults."""
    save(_default_data())
    print("[memory] All memory cleared.")


# ---------------------------------------------------------------------------
# Quick self-test (run this file directly)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== jarvis_memory self-test ===\n")

    clear_all()

    add_exchange("My name is Pratik.", "Nice to meet you, Pratik!")
    add_exchange("I'm working on project OpenJarvis.", "Great, I'll keep that in mind.")
    add_exchange("What's the git status?", "You have 3 uncommitted changes.")
    add_exchange("I prefer dark mode.", "Noted, I'll remember that.")

    print("Recent exchanges:")
    for ex in get_recent_exchanges(n=3):
        print(f"  [{ex['ts']}] User: {ex['user']!r} | JARVIS: {ex['jarvis']!r}")

    print("\nMemory context string:")
    print(" ", get_memory_context())

    data = load()
    print("\nExtracted facts:")
    print(json.dumps(data["facts"], indent=2))

def analyze_and_update_crm(app_name: str, sender: str, message: str) -> None:
    """Auto CRM: Analyzes an incoming message to build the user's CRM profile."""
    # Since we removed MLX, we use Gemini API (or the LLM router) to extract data
    from jarvis_actions import ask_jarvis
    prompt = f"Analyze this {app_name} message from {sender}: '{message}'. Extract any CRM info (action items, relationship context, mood) and output JSON."
    # In a real scenario, we parse the JSON and save to facts
    # For now, we just append to recent events
    data = load()
    data.setdefault("crm", []).append({"time": "now", "app": app_name, "sender": sender, "message": message})
    save(data)
