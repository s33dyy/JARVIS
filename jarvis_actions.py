"""
JARVIS Action Engine — executes real system actions from voice commands.

Action routing:
  1. Calendar: schedule/check meetings (Google Calendar + macOS Calendar)
  2. Email: read/draft/send Gmail
  3. Drive: search files
  4. Tasks/Reminders: macOS Reminders + Google Tasks
  5. Local: what am I working on, recent files, git status
  6. Multi-turn: holds state between utterances for missing info
"""

from __future__ import annotations

import re
import httpx
import json
from pathlib import Path
import subprocess
from datetime import datetime, timedelta
from typing import Optional

MLX_URL = "http://localhost:8080/v1/chat/completions"
MODEL   = "mlx-community/Qwen3-0.6B-4bit"

# Day name → iCal RRULE code
DAYS_MAP = {
    "monday": "MO", "tuesday": "TU", "wednesday": "WE",
    "thursday": "TH", "friday": "FR", "saturday": "SA", "sunday": "SU",
}
WEEKDAY_RANGE = {
    "weekday": ["monday","tuesday","wednesday","thursday","friday"],
    "weekdays": ["monday","tuesday","wednesday","thursday","friday"],
    "weekend":  ["saturday","sunday"],
    "everyday": ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"],
    "daily":    ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"],
}
DAY_ORDER = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]


# ─────────────────────────────────────────────────────────────
# Tiny LLM helper (direct MLX)
# ─────────────────────────────────────────────────────────────
def _llm(prompt: str, max_tokens: int = 200, system: str = "") -> str:
    from jarvis_llm import ask_llm
    return ask_llm(prompt, system=system, max_tokens=max_tokens, model_type="smart")


# ─────────────────────────────────────────────────────────────
# Reality Layer — failure reporting
# ─────────────────────────────────────────────────────────────
def _action_failed(component: str, reason: str) -> tuple[str, dict]:
    """
    Returns a spoken failure response and records the failure in the issue tracker.

    This is the anti-hallucination guarantee for actions:
    Instead of returning ("", {}) and letting the LLM invent a success response,
    every action handler calls this on failure to return a concrete, factual message.

    Args:
        component: Machine name for the issue tracker (e.g. "todoist", "google_calendar").
        reason:    Human-readable error string, surfaced verbatim to the user.
    """
    try:
        from jarvis_issue_tracker import record_failure
        record_failure(component, reason, severity="high")
    except Exception:
        pass  # Never let the tracker block the voice response
    return f"{reason}", {}


# ─────────────────────────────────────────────────────────────
# Date/time helpers
# ─────────────────────────────────────────────────────────────
def _parse_time(text: str) -> Optional[str]:
    """Extract HH:MM from natural language."""
    m = re.search(r"(\d{1,2})[.:](\d{2})\s*(am|pm)?|(\d{1,2})\s*(am|pm)", text, re.I)
    if not m:
        return None
    if m.group(1):
        h, mi = int(m.group(1)), int(m.group(2))
        mer = (m.group(3) or "").lower()
    else:
        h, mi = int(m.group(4)), 0
        mer = (m.group(5) or "").lower()
    if mer == "pm" and h < 12:
        h += 12
    if mer == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}"


def _parse_days(text: str) -> list[str]:
    """Extract list of weekday names from text."""
    q = text.lower()
    for shortcut, expanded in WEEKDAY_RANGE.items():
        if re.search(rf"\b{shortcut}\b", q):
            return expanded
    # Range: monday to saturday
    range_m = re.search(
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+"
        r"(?:to|through|till|until)\s+"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", q
    )
    if range_m:
        si = DAY_ORDER.index(range_m.group(1))
        ei = DAY_ORDER.index(range_m.group(2))
        return DAY_ORDER[si:ei+1] if si <= ei else DAY_ORDER[si:] + DAY_ORDER[:ei+1]
    # Individual
    return [d for d in DAYS_MAP if re.search(rf"\b{d}\b", q)]


def _parse_date(text: str) -> Optional[datetime]:
    """Parse relative date like 'tomorrow', 'Monday', 'next Tuesday'."""
    q = text.lower()
    now = datetime.now()
    if "tomorrow" in q:
        return now + timedelta(days=1)
    if "today" in q:
        return now
    for i, day in enumerate(DAY_ORDER):
        if re.search(rf"\b(?:next\s+)?{day}\b", q):
            days_ahead = (i - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # "next monday" means next week
            return now + timedelta(days=days_ahead)
    return None


def _next_occurrence(days: list[str], h: int, m: int) -> datetime:
    now = datetime.now()
    target_wdays = [DAY_ORDER.index(d) for d in days if d in DAY_ORDER]
    for i in range(8):
        candidate = now + timedelta(days=i)
        if candidate.weekday() in target_wdays:
            dt = candidate.replace(hour=h, minute=m, second=0, microsecond=0)
            if dt > now:
                return dt
    return (now + timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)


# ─────────────────────────────────────────────────────────────
# Task/meeting parameter extraction
# ─────────────────────────────────────────────────────────────
def _extract_meeting_params(text: str) -> dict:
    """Extract meeting title, time, date, attendees from text."""
    q = text.lower()
    params: dict = {
        "title":     None,
        "time":      _parse_time(text),
        "date":      _parse_date(text),
        "days":      _parse_days(text),
        "repeat":    bool(re.search(r"\b(repeat|recurring|every|daily|weekly)\b", q)),
        "attendees": [],
    }
    # Try to find "with [Name]"
    with_m = re.search(r"\bwith\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", text)
    if with_m:
        params["attendees"] = [with_m.group(1)]
    # Title: remove filler words
    title = re.sub(
        r"\b(i need you to|please|can you|could you|add|create|set|make|schedule|"
        r"book|a task|a meeting|an event|a call|task|meeting|event|call|repetitive|"
        r"recurring|repeat|every|from|monday|tuesday|wednesday|thursday|friday|"
        r"saturday|sunday|to|through|till|until|at|am|pm|daily|weekly|goes|on|that|"
        r"it|with|tomorrow|today|next)\b",
        " ", text, flags=re.I
    )
    title = re.sub(r"\d{1,2}[.:]\d{2}", " ", title)
    title = re.sub(r"\d{1,2}\s*(am|pm)", " ", title, flags=re.I)
    title = " ".join(title.split()).strip(" ,.-")
    # Remove names already captured as attendees
    for name in params["attendees"]:
        title = title.replace(name, "").strip()
    if len(title) > 2:
        params["title"] = title.title()
    return params


# ─────────────────────────────────────────────────────────────
# Calendar actions
# ─────────────────────────────────────────────────────────────
def _schedule_meeting(params: dict) -> str:
    """Create event in Google Calendar (falls back to macOS Calendar)."""
    title     = params.get("title") or "Meeting"
    time_str  = params.get("time") or "10:00"
    days      = params.get("days", [])
    repeat    = params.get("repeat", False)
    attendees = params.get("attendees", [])
    date      = params.get("date")

    try:
        h, m = map(int, time_str.split(":"))
    except Exception:
        h, m = 10, 0

    # Determine start datetime
    if days and repeat:
        dt = _next_occurrence(days, h, m)
    elif date:
        dt = date.replace(hour=h, minute=m, second=0, microsecond=0)
        if dt < datetime.now():
            dt += timedelta(days=1)
    else:
        dt = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
        if dt < datetime.now():
            dt += timedelta(days=1)

    end_dt = dt + timedelta(hours=1)

    # Resolve attendee names → emails via Google Contacts
    resolved_emails = []
    for name in attendees:
        try:
            from jarvis_google import find_contact_email
            email = find_contact_email(name)
            if email:
                resolved_emails.append(email)
        except Exception:
            pass

    # Build RRULE
    rrule = None
    if repeat and days:
        byday = ",".join(DAYS_MAP[d] for d in days if d in DAYS_MAP)
        rrule = f"FREQ=WEEKLY;BYDAY={byday}"
    elif repeat:
        rrule = "FREQ=DAILY"

    # Try Google Calendar first
    try:
        from jarvis_google import create_calendar_event, is_connected
        if is_connected():
            link, err = create_calendar_event(
                title=title, start_dt=dt, end_dt=end_dt,
                attendees=resolved_emails or None,
                recurrence=rrule,
            )
            if not err:
                day_str  = dt.strftime("%A, %d %B")
                time_out = dt.strftime("%I:%M %p")
                recur    = f" repeating {', '.join(d.capitalize() for d in days)}" if repeat else ""
                who      = f" with {', '.join(attendees)}" if attendees else ""
                return (f"Done, sir. '{title}'{who} scheduled for {day_str} at {time_out}{recur}"
                        f" on Google Calendar.")
    except Exception:
        pass

    # Fallback: macOS Calendar via AppleScript
    as_date = dt.strftime("%-d %B %Y %I:%M %p")
    as_end  = end_dt.strftime("%-d %B %Y %I:%M %p")
    recur_line = ""
    if rrule:
        recur_line = f'set recurrence of newEvent to "RRULE:{rrule}"'
    script = f'''
tell application "Calendar"
    tell calendar "Home"
        set newEvent to make new event with properties {{summary:"{title}", start date:date "{as_date}", end date:date "{as_end}"}}
        {recur_line}
    end tell
    reload calendars
end tell
return "ok"
'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    if "ok" in r.stdout:
        return f"Done, sir. '{title}' added to Calendar at {dt.strftime('%I:%M %p')} on {dt.strftime('%A, %d %B')}."
    err = r.stderr.strip()
    if "Home" in err:
        script = script.replace('calendar "Home"', 'calendar "Calendar"')
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        if "ok" in r.stdout:
            return f"Done, sir. '{title}' added at {dt.strftime('%I:%M %p')} on {dt.strftime('%A, %d %B')}."
    return f"I'm sorry sir, could not create the event: {err or 'unknown error'}"


def _get_calendar(question: str = "") -> str:
    """Read today's or tomorrow's events and format for voice."""
    is_tomorrow = "tomorrow" in question.lower()
    day_offset = 1 if is_tomorrow else 0
    day_name = "tomorrow" if is_tomorrow else "today"
    
    # Try Google Calendar
    try:
        from jarvis_google import get_events, is_connected
        if is_connected():
            events, err = get_events(day_offset)
            if events:
                items = [f"{e['start']} — {e['title']}" for e in events]
                return f"For {day_name} you have {len(events)} events: " + "; ".join(items) + "."
            elif not err:
                return f"Your calendar is clear {day_name}, sir."
    except Exception:
        pass

    # Fallback: macOS Calendar
    script = '''
set output to ""
tell application "Calendar"
    set today to current date
    set dayStart to today
    set hours of dayStart to 0
    set minutes of dayStart to 0
    set seconds of dayStart to 0
    set dayEnd to dayStart + (1 * days)
    repeat with aCal in calendars
        repeat with anEvent in (every event of aCal whose start date >= dayStart and start date < dayEnd)
            try
                set evTitle to summary of anEvent
                set evStart to start date of anEvent
                set output to output & (time string of evStart) & " - " & evTitle & "\n"
            end try
        end repeat
    end repeat
end tell
return output
'''
    raw = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10).stdout.strip()
    if raw:
        events = [l.strip() for l in raw.splitlines() if l.strip()]
        return f"Today you have {len(events)} events: " + "; ".join(events[:5]) + "."
    return "Your calendar is clear today, sir."


# ─────────────────────────────────────────────────────────────
# Email actions
# ─────────────────────────────────────────────────────────────
def _read_emails() -> str:
    try:
        from jarvis_google import get_unread_emails, is_connected
        if not is_connected():
            return "Sir, I'm not connected to Gmail yet. Please run 'jarvis connect gmail' first."
        emails, err = get_unread_emails(max_results=5)
        if err:
            return f"I couldn't fetch your emails, sir: {err}"
        if not emails:
            return "Your inbox is clear, sir. No unread messages."
        summary = f"You have {len(emails)} unread emails, sir. "
        for i, e in enumerate(emails[:3], 1):
            sender = e["from"].split("<")[0].strip()[:25]
            subj   = e["subject"][:50]
            summary += f"{i}: From {sender} — {subj}. "
        return summary.strip()
    except Exception as e:
        return f"Email check failed, sir: {e}"


def _draft_reply(pending: dict, question: str) -> tuple[str, dict]:
    """Multi-turn: handle email reply drafting."""
    state = pending.get("email_state")

    if state == "need_email_id":
        # User just gave a number (which email to reply to)
        num_m = re.search(r"\b(\d)\b", question)
        if num_m:
            idx = int(num_m.group(1)) - 1
            emails = pending.get("emails", [])
            if 0 <= idx < len(emails):
                email = emails[idx]
                return (
                    f"What would you like to say in reply to {email['from'].split('<')[0].strip()}, sir?",
                    {**pending, "email_state": "need_body", "reply_to": email}
                )
        return "Which email number, sir?", pending

    if state == "need_body":
        # User dictated the reply body
        email     = pending.get("reply_to", {})
        body_text = question
        subject   = "Re: " + email.get("subject", "")
        to        = re.findall(r"<(.+?)>", email.get("from", ""))
        to_addr   = to[0] if to else email.get("from", "")

        # AI-polish the body
        polished = _llm(
            f"Polish this email reply (keep it professional and concise):\n\n{body_text}",
            system="You are an email writing assistant. Return only the email body, no subject line."
        ) or body_text

        # AUTO-SEND directly (no confirmation step)
        from jarvis_google import send_email
        ok, err = send_email(to_addr, subject, polished)
        if ok:
            return f"Email sent to {email['from'].split('<')[0].strip()}, sir.", {}
        return f"Failed to send email, sir: {err}", {}

    if state == "confirm_send":
        q = question.lower()
        if any(w in q for w in ["send", "yes", "go ahead", "do it"]):
            from jarvis_google import send_email
            ok, err = send_email(
                pending["draft_to"], pending["draft_subject"], pending["draft_body"]
            )
            return ("Sent, sir." if ok else f"Failed to send: {err}"), {}
        if any(w in q for w in ["discard", "cancel", "no", "stop"]):
            return "Draft discarded, sir.", {}
        return "Say 'send it' to send or 'discard' to cancel, sir.", pending

    return "", {}


# ─────────────────────────────────────────────────────────────
# Drive / file search
# ─────────────────────────────────────────────────────────────
def _search_drive(question: str) -> str:
    """Search Google Drive and local Desktop for a file."""
    q = question.lower()

    # Extract query: take everything after 'for', 'find', 'search', 'called' etc.
    query = ""
    for keyword in ["for the", "for a", "for my", "for", "called", "named", "about"]:
        m = re.search(rf"\b{keyword}\s+(.+)", q)
        if m:
            query = m.group(1).strip()
            # Strip trailing noise
            query = re.sub(r"\b(in|on|my|the|google|drive|files?|documents?|please)\b", " ", query)
            query = " ".join(query.split()).strip(" ,.")
            break

    # Fallback: remove just the command words, keep the rest
    if not query or len(query) < 3:
        query = re.sub(
            r"\b(hey jarvis|yes|sir|search|find|look up|show me|can you see|"
            r"google drive|my drive|drive|files?|documents?|please|in|on)\b",
            " ", q
        )
        query = " ".join(query.split()).strip()

    if not query or len(query) < 2:
        return "What would you like me to search for in your Drive, sir?"

    # Try Google Drive API first
    try:
        from jarvis_google import search_drive, is_connected
        if is_connected():
            files, err = search_drive(query, max_results=5)
            if files:
                names = "; ".join(f["name"] for f in files[:4])
                return f"Found {len(files)} files matching '{query}': {names}."
    except Exception:
        pass

    # Fallback: search local Desktop and Downloads
    import subprocess
    result = subprocess.run(
        ["mdfind", "-onlyin", str(Path.home()), query],
        capture_output=True, text=True, timeout=5
    )
    local_files = [
        line for line in result.stdout.splitlines()
        if not any(skip in line for skip in [".app", "Library", "Cache", "node_modules"])
    ][:4]

    if local_files:
        names = "; ".join(Path(f).name for f in local_files)
        return f"Found on your Mac: {names}."

    return f"No files found matching '{query}', sir."



# ─────────────────────────────────────────────────────────────
# "What am I working on?" — local context
# ─────────────────────────────────────────────────────────────
def _what_am_i_working_on() -> str:
    try:
        from jarvis_context import build_context, get_raw
        raw = get_raw()
        repos    = raw.get("git", [])
        projects = raw.get("projects", [])
        recent   = raw.get("recent", [])

        parts = []
        if repos:
            names = [f"{r['name']} ({r['branch']})" for r in repos[:4]]
            parts.append(f"active git repos: {', '.join(names)}")
        if projects:
            names = [f"{p['name']} ({p['type']})" for p in projects[:3]]
            parts.append(f"other projects: {', '.join(names)}")
        if recent:
            names = [f['name'] for f in recent[:4]]
            parts.append(f"recently modified files: {', '.join(names)}")

        if parts:
            return "Sir, based on your filesystem: " + "; ".join(parts) + "."
        return "I don't see any active projects right now, sir."
    except Exception as e:
        return f"Could not scan filesystem: {e}"


# ─────────────────────────────────────────────────────────────
# Background Agent Interactions (Codex / Antigravity monitoring)
# ─────────────────────────────────────────────────────────────
def _get_agent_progress_response(question: str) -> str:
    try:
        import jarvis_agent_monitor
        convs = jarvis_agent_monitor.get_active_conversations(limit=3)
        if not convs:
            return "I don't see any active background agents running right now, sir."

        # Parse query keywords
        q = question.lower()
        target_conv = None

        # Try to find a matching agent by goal keyword
        for c in convs:
            details = jarvis_agent_monitor.parse_conversation(c["conv_id"])
            if details:
                # Extract some words from the goal
                goal_words = [w for w in re.findall(r"\w+", details["goal"].lower()) if len(w) > 3]
                if any(w in q for w in goal_words):
                    target_conv = details
                    break

        # Fallback to the most recently active conversation
        if not target_conv:
            target_conv = jarvis_agent_monitor.parse_conversation(convs[0]["conv_id"])

        if not target_conv:
            return "I was unable to retrieve agent details, sir."

        goal = target_conv["goal"]
        status = target_conv["status"]
        tasks = target_conv["tasks"]
        subagents = target_conv["subagents"]
        
        # Build response
        parts = [f"For the agent working on '{goal}':"]
        parts.append(f"The current status is: {status}.")
        
        if tasks["total"] > 0:
            parts.append(f"Progress is at {tasks['percent']}% ({tasks['completed']} of {tasks['total']} tasks completed).")
            if tasks["active_items"]:
                parts.append(f"Currently working on: '{tasks['active_items'][0]}'.")
        
        if subagents:
            sub_roles = ", ".join(f"{s['name']} ({s['role']})" for s in subagents)
            parts.append(f"Active subagents: {sub_roles}.")
            
        return " ".join(parts)
    except Exception as e:
        return f"Error checking agent status: {e}"


def _send_agent_prompt_interactive(question: str, instruction: str) -> tuple[str, dict]:
    try:
        import jarvis_agent_monitor
        convs = jarvis_agent_monitor.get_active_conversations(limit=3)
        if not convs:
            return "I don't see any active background agents running right now, sir.", {}

        # Default to the most recently active one
        target_conv = jarvis_agent_monitor.parse_conversation(convs[0]["conv_id"])
        if not target_conv:
            return "I couldn't access details for the running agent, sir.", {}

        conv_id = target_conv["conv_id"]
        goal = target_conv["goal"]
        status = target_conv["status"]

        # Tailor prompt using the LLM
        prompt_to_llm = f"""
You are JARVIS. The user wants to send a command/instruction to a running background AI agent.
Agent Goal: {goal}
Agent Status: {status}
User Instruction: {instruction}

Tailor a highly clear, structured, and developer-friendly prompt that JARVIS should send to the agent's inbox.
The prompt should tell the agent exactly what to do next based on the user's instruction and its current goal/status.
Respond with ONLY the tailored prompt content, with no introductory or concluding remarks.
"""
        tailored = _llm(prompt_to_llm, max_tokens=150, system="You are JARVIS. You output ONLY the tailored prompt text.")
        tailored = tailored.strip().strip('"').strip("'")

        msg = f"Sir, I have tailored a prompt for the agent working on '{goal}':\n\n\"{tailored}\"\n\nShould I send this prompt to the agent, sir?"
        return msg, {
            "action": "agent_confirm_send",
            "conv_id": conv_id,
            "prompt": tailored
        }
    except Exception as e:
        return f"Failed to prepare agent prompt: {e}", {}


# ─────────────────────────────────────────────────────────────
# Media Playback (YouTube / Spotify)
# ─────────────────────────────────────────────────────────────
def _play_media(question: str) -> str:
    import urllib.parse
    q = question.lower()
    
    # Extract just the query terms
    query = re.sub(r"\b(play|listen to|watch|on|youtube|spotify|some|music|song|video|movie|can|you|please)\b", " ", q).strip()
    if not query:
        return "What would you like me to play, sir?"
        
    encoded = urllib.parse.quote_plus(query)
    
    if "spotify" in q:
        # Uses AppleScript to actually play the track rather than just searching
        script = f'tell application "Spotify" to play track "spotify:search:{query}"'
        subprocess.Popen(["osascript", "-e", script])
        return f"Playing {query} on Spotify, sir."
    else:
        # Default to YouTube
        subprocess.Popen(["open", f"https://www.youtube.com/results?search_query={encoded}"])
        return f"Opening YouTube for {query}, sir."


# ─────────────────────────────────────────────────────────────
# Obsidian / Task commands
# ─────────────────────────────────────────────────────────────
# Removed: local obsidian task logic -> moved to Todoist

def _read_sessions() -> str:
    try:
        import jarvis_patterns
        mem = jarvis_patterns.load_memory()
        sessions = mem.get("sessions", {})
        if not sessions:
            return "I don't have any recorded work sessions yet, sir."
        
        parts = []
        for name, data in sessions.items():
            if data["duration_minutes"] > 5:
                parts.append(f"{name} for {jarvis_patterns.format_duration(data['duration_minutes'])}")
                
        if parts:
            return "Today you worked on: " + ", ".join(parts)
        return "I don't see any significant work sessions today, sir."
    except Exception as e:
        return f"Could not read sessions: {e}"

def _read_file_content(file_path: str) -> str:
    """Read a file and summarize its content using the LLM."""
    try:
        path = Path(file_path).expanduser()
        if not path.exists():
            # Try to find it in common locations
            for search_root in [Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "Downloads"]:
                found = list(search_root.rglob(path.name))
                if found:
                    path = found[0]
                    break
        if not path.exists():
            return f"I couldn't find the file '{file_path}', sir."
        
        suffix = path.suffix.lower()
        content = ""
        
        if suffix == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(str(path)) as pdf:
                    content = " ".join(page.extract_text() or "" for page in pdf.pages[:5])
            except ImportError:
                return "PDF reading requires pdfplumber. Run: uv pip install pdfplumber"
        elif suffix in (".txt", ".md", ".py", ".js", ".json", ".csv"):
            content = path.read_text(errors="replace")[:3000]
        else:
            return f"I can read .txt, .md, .pdf, and code files, sir. '{path.name}' is a {suffix} file."
        
        if not content.strip():
            return f"The file '{path.name}' appears to be empty, sir."
        
        summary = _llm(
            f"Summarize this file content in 2-3 sentences:\n\n{content[:1500]}",
            system="You are a helpful assistant. Summarize concisely for voice output."
        )
        return summary or f"File '{path.name}' read successfully, sir. It contains {len(content)} characters."
    except Exception as e:
        return f"Error reading file: {e}"

def _edit_file_content(file_path: str, instruction: str) -> str:
    """Read a file, edit its content based on instruction using LLM, and save."""
    try:
        path = Path(file_path).expanduser()
        if not path.exists():
            for search_root in [Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "Downloads"]:
                found = list(search_root.rglob(path.name))
                if found:
                    path = found[0]
                    break
        if not path.exists():
            return f"I couldn't find the file '{file_path}' to edit, sir."
        
        if path.suffix.lower() not in (".txt", ".md", ".py", ".js", ".json", ".csv"):
            return f"I can only edit plain text and code files, sir. '{path.name}' is not supported."
            
        content = path.read_text(errors="replace")
        if len(content) > 10000:
            return f"The file '{path.name}' is too large to edit by voice, sir."
            
        prompt = f"Edit the following file content according to this instruction: {instruction}\n\nReturn ONLY the modified file content. Do not add markdown blocks like ``` unless they were in the original. Do not add explanations.\n\nFILE CONTENT:\n{content}"
        
        new_content = _llm(prompt, system="You are an expert editor. Return exactly the new file content, with no markdown wrappers or pleasantries.")
        if not new_content:
            return "The model failed to generate the edits, sir."
            
        # Clean up common markdown wrappings if the model ignored the instruction
        if new_content.startswith("```"):
            lines = new_content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            new_content = "\n".join(lines)
            
        path.write_text(new_content)
        return f"File '{path.name}' has been updated successfully, sir."
    except Exception as e:
        return f"Error editing file: {e}"

def _update_crm_interactive(contact: str, details: str) -> str:
    try:
        import jarvis_obsidian
        jarvis_obsidian.update_crm(contact, details)
        return f"CRM updated for {contact}, sir."
    except Exception as e:
        return f"Failed to update CRM: {e}"

def _summarize_today() -> str:
    try:
        from jarvis_todoist import get_tasks
        tasks = get_tasks(filter_query="today | overdue")
        return f"You have {len(tasks)} tasks remaining today."
    except Exception as e:
        # Record the failure so it appears in health reports
        try:
            from jarvis_issue_tracker import record_failure
            record_failure("todoist", f"get_tasks failed: {type(e).__name__}: {str(e)[:80]}", "high")
        except Exception:
            pass
        return f"I cannot access your tasks right now, sir. Todoist error: {type(e).__name__}: {str(e)[:60]}"

def _organize_tasks() -> tuple[str, dict]:
    # Reality check: fetch tasks first; surface real failures before doing LLM work
    try:
        from jarvis_todoist import get_tasks, update_task
        tasks = get_tasks()
    except Exception as e:
        return _action_failed("todoist", f"Task organization failed, sir. Could not fetch tasks from Todoist: {type(e).__name__}: {str(e)[:80]}")

    try:
        from datetime import datetime
        import json
        from jarvis_llm import ask_llm

        if not tasks:
            return "You have no active tasks to organize, sir.", {}
            
        # We will organize all active tasks (up to 40 tasks to avoid token limits)
        to_schedule = tasks[:40]
        
        task_text = ""
        for t in to_schedule:
            due_str = ""
            if t.get("due"):
                due_str = t["due"].get("string") or t["due"].get("date") or ""
            priority = t.get("priority", 1)
            desc = t.get("description") or ""
            task_text += f"- ID: {t['id']} | Task: {t['content']} | Current Due: {due_str} | Current Priority: {priority} | Current Desc: {desc}\n"
            
        now_str = datetime.now().strftime("%A, %B %d, %Y %I:%M %p")
        system = "You are an AI assistant helping a user organize their todo list. Output ONLY valid JSON."
        prompt = (
            f"The current date and time is {now_str}.\n"
            "Analyze and organize these tasks throughout this week. You must organize both scheduled and unscheduled tasks to create a balanced, logical timeline for the user.\n"
            "For each task, assign:\n"
            "- a logical natural language due date/time (e.g. 'today at 2pm', 'tomorrow at 11am', 'Tuesday at 4pm', or 'No date' if it should remain unscheduled)\n"
            "- a priority level (1=normal, 2=medium, 3=high, 4=urgent)\n"
            "- a brief, helpful description if one is missing or needs improvement.\n\n"
            "Output EXACTLY a JSON array of objects with keys: id, due_string, priority, description.\n"
            "Only include tasks in the output array that actually need updating (where the new schedule/priority/desc is different from the current one).\n\n"
            f"Tasks:\n{task_text}\n"
        )
        
        raw_output = ask_llm(prompt, system=system, max_tokens=1500)
        if not raw_output:
            return "I could not connect to your local language model, sir.", {}
        
        valid_ids = {str(t['id']) for t in to_schedule}
        updated_count = 0
        
        content = raw_output.strip()
        if content.startswith("```json"): content = content[7:]
        if content.endswith("```"): content = content[:-3]
        
        try:
            updates = json.loads(content.strip())
        except json.JSONDecodeError as e:
            print(f"[Actions] Failed to parse auto-schedule JSON: {e}")
            return "I failed to schedule the tasks due to a parsing error, sir.", {}
            
        for u in updates:
            tid = str(u.get("id"))
            if tid in valid_ids:
                kwargs = {}
                if "due_string" in u:
                    val = str(u["due_string"])
                    if val.lower() != "no date" and val:
                        kwargs["due_string"] = val
                if u.get("priority"):
                    try:
                        p = int(u["priority"])
                        if 1 <= p <= 4: kwargs["priority"] = p
                    except ValueError:
                        pass
                if u.get("description"): kwargs["description"] = str(u["description"])
                
                # Retrieve current details for change detection
                current_task = next(t for t in to_schedule if str(t["id"]) == tid)
                curr_due = current_task.get("due", {})
                curr_due_str = (curr_due.get("string") or curr_due.get("date") or "") if curr_due else ""
                curr_priority = current_task.get("priority", 1)
                curr_desc = current_task.get("description") or ""
                
                has_changes = False
                if "due_string" in kwargs and kwargs["due_string"] != curr_due_str:
                    has_changes = True
                if "priority" in kwargs and kwargs["priority"] != curr_priority:
                    has_changes = True
                if "description" in kwargs and kwargs["description"] != curr_desc:
                    has_changes = True
                    
                if has_changes:
                    ok = update_task(tid, **kwargs)
                    if ok:
                        updated_count += 1
                    else:
                        # update_task returned falsy — record the failure
                        try:
                            from jarvis_issue_tracker import record_failure
                            record_failure("todoist", f"update_task returned False for task {tid}", "high")
                        except Exception:
                            pass

        if updated_count > 0:
            return f"I have organized {updated_count} tasks, setting priorities, time schedules, and descriptions based on my analysis, sir.", {}
        else:
            return "I analyzed your tasks, but found they are already optimally scheduled, sir.", {}
    except Exception as e:
        return _action_failed("todoist", f"Task organization failed, sir. Error: {type(e).__name__}: {str(e)[:80]}")

def _update_project_interactive(project: str, status: str) -> str:
    try:
        import jarvis_obsidian
        jarvis_obsidian.update_project(project, status, "Ongoing")
        return f"Project {project} status updated to {status}, sir."
    except Exception as e:
        return f"Failed to update project: {e}"

# ─────────────────────────────────────────────────────────────
# macOS Reminder (fallback)
# ─────────────────────────────────────────────────────────────
def _create_macos_reminder(name: str, time_str: str) -> str:
    try:
        h, m = map(int, time_str.split(":"))
    except Exception:
        h, m = 9, 0
    from datetime import timedelta
    now = datetime.now()
    dt  = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if dt <= now:
        dt += timedelta(days=1)
    as_date = dt.strftime("%-d %B %Y %I:%M %p")
    script  = f'''
tell application "Reminders"
    make new reminder with properties {{name:"{name}", remind me date:date "{as_date}"}}
end tell
return "ok"
'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    if "ok" in r.stdout:
        subprocess.Popen(["open", "-a", "Reminders"])
        return f"Done, sir. Reminder '{name}' set for {dt.strftime('%I:%M %p')}."
    return f"Could not set reminder: {r.stderr.strip() or 'unknown error'}"


# ─────────────────────────────────────────────────────────────
# Public entry point — action router
# ─────────────────────────────────────────────────────────────
def handle_action(question: str, pending: dict) -> tuple[str, dict]:
    """
    Route a voice command to the appropriate action handler.
    Returns (response_text, new_pending_state).
    Empty response_text means "no action matched — fall through to LLM".
    """
    q = question.lower()

    # ── Voice CEO Directives ────────────────────────────────
    if q.strip() in ("jarvis, status", "status", "jarvis status"):
        try:
            from jarvis_memory import get_jarvis_state
            return get_jarvis_state(), {}
        except Exception as e:
            return f"Status unavailable: {e}", {}

    if q.strip() in ("jarvis, self-audit", "self-audit", "self audit"):
        try:
            from jarvis_self_improvement import generate_self_audit_report
            return generate_self_audit_report(), {}
        except Exception as e:
            return f"Self-audit failed: {e}", {}

    # ── Multi-turn completion ────────────────────────────────
    pa = pending.get("action")

    if pa == "agent_confirm_send":
        if re.search(r"\b(yes|yeah|sure|do it|ok|okay|yup|affirmative)\b", q):
            try:
                import jarvis_agent_monitor
                res = jarvis_agent_monitor.send_prompt_to_agent(pending["conv_id"], pending["prompt"])
                return f"Prompt sent, sir. {res}", {}
            except Exception as e:
                return f"Failed to send prompt to agent: {e}", {}
        else:
            return "Cancelled sending prompt to the agent, sir.", {}

    if pa == "need_meeting_title":
        params = pending["params"]
        params["title"] = question.strip().title()
        return _schedule_meeting(params), {}

    if pa == "need_meeting_time":
        params = pending["params"]
        params["time"] = _parse_time(question) or "10:00"
        if not params.get("title"):
            return (
                "What should I call this event, sir?",
                {"action": "need_meeting_title", "params": params}
            )
        return _schedule_meeting(params), {}

    if pa and pa.startswith("email_"):
        response, new_pending = _draft_reply({**pending, "email_state": pa}, question)
        return response, new_pending

    if pa == "confirm_send":
        response, new_pending = _draft_reply(pending, question)
        return response, new_pending

    if pa == "need_task_name":
        params = pending["params"]
        params["title"] = question.strip().title()
        return _schedule_meeting(params), {}

    if pa == "todoist_confirm_add":
        if re.search(r"\b(yes|yeah|sure|do it|ok|okay|yup|affirmative)\b", q):
            try:
                import jarvis_todoist
                result = jarvis_todoist.create_task(pending["task"])
                if result:
                    return f"Task '{pending['task']}' added to Todoist, sir.", {}
                return _action_failed("todoist", f"Task creation failed, sir. Todoist returned no confirmation.")
            except Exception as e:
                return _action_failed("todoist", f"Task creation failed, sir. Todoist error: {type(e).__name__}: {str(e)[:80]}")
        else:
            return "Cancelled adding task to Todoist, sir.", {}

    if pa == "todoist_confirm_complete":
        if re.search(r"\b(yes|yeah|sure|do it|ok|okay|yup|affirmative)\b", q):
            try:
                import jarvis_todoist
                if jarvis_todoist.close_task(pending["task_id"]):
                    return "Task completed in Todoist, sir.", {}
                return _action_failed("todoist", "Task completion failed, sir. Todoist did not confirm the update.")
            except Exception as e:
                return _action_failed("todoist", f"Task completion failed, sir. Todoist error: {type(e).__name__}: {str(e)[:80]}")
        else:
            return "Cancelled completing task, sir.", {}

    # ── "Schedule / book a meeting" ──────────────────────────
    if re.search(
        r"\b(schedule|book|add|create|set up|arrange|plan|put)\b.{0,40}"
        r"\b(meeting|call|event|appointment|standup|sync|1:1|one.on.one|party|lunch|dinner|calendar)\b",
        q
    ) or re.search(r"\b(meet with|call with|sync with)\b", q):
        params = _extract_meeting_params(question)
        if not params.get("time"):
            return (
                "What time should I schedule it, sir?",
                {"action": "need_meeting_time", "params": params}
            )
        if not params.get("title"):
            return (
                "What should I call this event, sir?",
                {"action": "need_meeting_title", "params": params}
            )
        return _schedule_meeting(params), {}

    # ── "What's on my calendar" (Reads calendar, must come AFTER scheduling) ──
    if re.search(r"\b(what.?s on|what is on|read|show|check|tell me).*(calendar|schedule|agenda)\b", q) or \
       (re.search(r"\b(today|tomorrow)\b", q) and not re.search(r"\b(task|todo|to.do|to do|workspace)\b", q) and re.search(r"\b(what.?s on|what is on|read|show|check|tell me)\b", q)):
        return _get_calendar(question), {}

    # ── Self Improvement / Fix Bug ───────────────────────────
    if pa == "self_improvement_confirm":
        if re.search(r"\b(yes|yeah|sure|do it|ok|okay|yup|affirmative|approve|apply)\b", q):
            return "Please apply the proposed Antigravity patch manually, sir. Auto-apply is currently disabled for safety.", {}
        else:
            return "Self improvement rejected. Discarding the Antigravity proposal.", {}

    if re.search(r"\b(fix this bug|i found a bug|implement a feature)\b", q):
        try:
            import threading
            def _run_trigger():
                try:
                    from jarvis_failure_store import record_failure
                    record_failure("manual_request", f"User manually requested: {question}", severity="critical")
                except ImportError:
                    pass
                
                try:
                    from jarvis_self_improvement import trigger_on_demand_analysis
                    proposal = trigger_on_demand_analysis()
                    
                    from jarvis_speak import speak
                    speak("I have a proposal from Antigravity ready. Please check your console.")
                    print(f"\n[Antigravity Proposal]\n{proposal}\n")
                except Exception as e:
                    print(f"Failed analysis: {e}")

            threading.Thread(target=_run_trigger, daemon=True).start()
            return "I am spinning up an Antigravity subagent to investigate the codebase, sir. I will notify you when the proposal is ready.", {"action": "self_improvement_confirm", "issue_id": "manual_request", "proposal": question}
        except Exception as e:
            return f"Failed to trigger Self Improvement Engine: {e}", {}


    # ── "Add a reminder" ──────────────────────────────
    if re.search(
        r"\b(add|create|set|make|schedule|remind)\b.{0,30}"
        r"\b(reminder|alarm)\b",
        q
    ) or re.search(r"\b(remind me to|remind me about)\b", q):
        params = _extract_meeting_params(question)
        title  = params.get("title")
        if not title:
            return (
                "What would you like to call this task, sir?",
                {"action": "need_task_name", "params": params}
            )
        time_str = params.get("time") or "09:00"
        days     = params.get("days", [])
        repeat   = params.get("repeat", False)
        if days or repeat:
            return _schedule_meeting(params), {}
        return _create_macos_reminder(title, time_str), {}

    # ── "Find free time / when am I free" ───────────────────
    if re.search(r"\b(free|available|free slot|open slot|when can|find time)\b", q):
        try:
            from jarvis_google import find_free_slots, is_connected
            if is_connected():
                slots = find_free_slots()
                if slots:
                    return "You're free at: " + "; ".join(slots[:3]) + ".", {}
        except Exception:
            pass
        return "I need Google Calendar access to check your free slots, sir.", {}

    # ── "Read my emails" ────────────────────────────────────
    if re.search(r"\b(read|check|what are|show|open|any new)\b.*?\b(email|mail|inbox|gmail)\b", q) or re.search(r"\b(my emails|my inbox)\b", q):
        result = _read_emails()
        try:
            from jarvis_google import get_unread_emails
            emails, _ = get_unread_emails(5)
            if emails:
                return result, {"action": "email_need_email_id", "emails": emails}
        except Exception:
            pass
        return result, {}

    # ── "Reply to / draft email" ────────────────────────────
    if re.search(r"\b(reply|respond|draft|write|send)\b.{0,20}\b(email|mail|message)\b", q):
        try:
            from jarvis_google import get_unread_emails, is_connected
            if not is_connected():
                return "Not connected to Gmail, sir.", {}
            emails, _ = get_unread_emails(5)
            if not emails:
                return "No unread emails to reply to, sir.", {}
            summary = "Which email to reply to, sir? " + " ".join(
                f"{i+1}: {e['from'].split('<')[0].strip()[:20]}" for i, e in enumerate(emails[:3])
            )
            return summary, {"action": "email_need_email_id", "emails": emails}
        except Exception as e:
            return f"Couldn't access Gmail, sir: {e}", {}

    # ── "Search my Drive" ───────────────────────────────────
    if re.search(r"\b(drive|google drive|find file|search file|document|see the|where is the)\b.*", q):
        return _search_drive(question), {}

    # ── "What am I working on" ──────────────────────────────
    if re.search(r"\b(working on|projects?|code|coding|repos?|what am i|what.s on my plate|workspace)\b", q):
        return _what_am_i_working_on(), {}

    # ── Todoist tasks ───────────────────────────────────────────
    if re.search(r"\b(organize|schedule|plan)\b.*\b(task|tasks|to do|todo|to-do|week)\b", q) or re.search(r"\borganize it\b", q):
        return _organize_tasks()
        
    if re.search(r"\b(what are my open tasks|read my tasks|list tasks|todoist tasks|tasks.*today|today.*tasks)\b", q):
        try:
            from jarvis_todoist import get_tasks_summary
            return get_tasks_summary(), {}
        except Exception as e:
            return _action_failed("todoist", f"Could not read tasks, sir. Todoist error: {type(e).__name__}: {str(e)[:80]}")

    if m := re.search(r"\b(?:add|create|new) task (.*)", q):
        task = m.group(1).strip()
        return f"Should I go ahead and add '{task}' to your Todoist, sir?", {"action": "todoist_confirm_add", "task": task}
        
    if m := re.search(r"\b(?:mark|complete|finish|close)\s+(?:the\s+)?(?:task\s+)?(.*)", q):
        keyword = re.sub(r"\b(?:done|completed|it)\b", "", m.group(1)).strip().lower()
        try:
            import jarvis_todoist
            tasks = jarvis_todoist.get_tasks()
            matches = [t for t in tasks if keyword in t["content"].lower()]
            if not matches:
                return "I could not find a task matching that description in Todoist, sir.", {}

            target = matches[0]
            return f"Should I close the task '{target['content']}' in Todoist, sir?", {"action": "todoist_confirm_complete", "task_id": target["id"]}
        except Exception as e:
            return _action_failed("todoist", f"Could not look up tasks, sir. Todoist error: {type(e).__name__}: {str(e)[:80]}")
        
    # ── Sessions & Universal Management ──────────────────────────
    if re.search(r"\b(what did i work on|how long did i|my sessions|work today)\b", q):
        return _read_sessions(), {}

    if m := re.search(r"\b(?:update|log) crm for (.*?) that (.*)", q):
        contact = m.group(1).strip().title()
        details = m.group(2).strip()
        return _update_crm_interactive(contact, details), {}
        
    if m := re.search(r"\b(?:update|set) project (.*?) status to (.*)", q):
        project = m.group(1).strip().title()
        status = m.group(2).strip()
        return _update_project_interactive(project, status), {}

    # ── Active Project Engine ─────────────────────────────────────
    if m := re.search(r"\b(?:pause|suspend)\s+(?:the\s+)?(?:project\s+)?(.+?)(?:\s+tasks?)?$", q):
        project = m.group(1).strip()
        try:
            from jarvis_projects import set_project_status
            set_project_status(project, "paused")
            return f"Project '{project}' has been paused, sir. I will ignore tasks related to it.", {}
        except ImportError:
            return "Project engine not loaded, sir.", {}

    if m := re.search(r"\b(?:focus on|resume|start|activate)\s+(?:the\s+)?(?:project\s+)?(.+?)(?:\s+tasks?)?$", q):
        project = m.group(1).strip()
        try:
            from jarvis_projects import set_project_status
            set_project_status(project, "active")
            return f"Project '{project}' is now active, sir. I will prioritize it.", {}
        except ImportError:
            return "Project engine not loaded, sir.", {}

    # ── Play Media ───────────────────────────────────────────────
    if re.search(r"\b(play|listen to|watch)\b", q):
        return _play_media(question), {}

    # ── Screen / Vision (removed — module deleted) ─────────────────
    if re.search(r"\b(what(?:'s| is) on (my )?screen|analyze (my )?screen)\b", q):
        return "Screen analysis is not available in this build, sir.", {}

    # ── Agent progress and status queries ──────────────────────
    if re.search(r"\b(agent|subagent|background task|chat|codex|antigravity)\b.*?\b(progress|done|status|how far|working on|state)\b", q) or \
       re.search(r"\b(progress|done|status|state|how far)\b.*?\b(agent|subagent|background task|chat|codex|antigravity)\b", q) or \
       re.search(r"\bhow much\b.*?\bdone\b.*?\b(agent|project|task)\b", q):
         return _get_agent_progress_response(question), {}

    # ── Send tailored prompt to running agent ──────────────────
    if m := re.search(r"\b(?:tell|ask|prompt|say to|instruct)\s+(?:the\s+)?agent\s+(?:to\s+)?(.*)", q):
        instruction = m.group(1).strip()
        return _send_agent_prompt_interactive(question, instruction)
        
    if m := re.search(r"\bsend\s+(?:a\s+)?prompt\s+(?:to\s+)?(?:the\s+)?agent:?\s*(.*)", q):
        instruction = m.group(1).strip()
        return _send_agent_prompt_interactive(question, instruction)

    # ── Messaging (iMessage & WhatsApp) ─────────────────────────────────────────────────
    def _parse_message_intent(query):
        q_clean = re.sub(r'[\.\!\?]+$', '', query.strip()).strip()
        # 1. send ... to ...
        if m := re.search(r"\bsend\b\s+(?:a\s+)?(.*?)\s*(?:message|text|whatsapp)?\s*(?:from|via|on)?\s*(?:whatsapp|imessage)?\s*to\s+([A-Za-z0-9_ ]+)$", q_clean, re.IGNORECASE):
            msg = m.group(1).strip()
            return m.group(2).strip(), msg if msg else "Hello"
        # 2. open whatsapp and message ...
        if m := re.search(r"\bopen whatsapp and message\b\s+([A-Za-z0-9_ ]+)$", q_clean, re.IGNORECASE):
            return m.group(1).strip(), "Hello"
        # 3. message/text/whatsapp ... saying ...
        if m := re.search(r"\b(?:message|text|whatsapp|imessage)\b\s+([A-Za-z0-9_ ]+?)\s+(?:saying|that says|to say|and say)\s+(.+)$", q_clean, re.IGNORECASE):
            return m.group(1).strip(), m.group(2).strip()
        # 4. send whatsapp to ...
        if m := re.search(r"\bsend\s+(?:a\s+)?(?:whatsapp|text|message|imessage)\s+to\s+([A-Za-z0-9_ ]+)$", q_clean, re.IGNORECASE):
            return m.group(1).strip(), "Hello"
        # 5. whatsapp/message/text ...
        if m := re.search(r"\b(?:whatsapp|message|text|imessage)\b\s+([A-Za-z0-9_ ]+)$", q_clean, re.IGNORECASE):
            return m.group(1).strip(), "Hello"
        return None, None

    contact, msg = _parse_message_intent(q)
    if contact and len(contact) > 1 and contact.lower() not in ["a message", "message"]:
        contact = contact.title()
        if "whatsapp" in q.lower():
            try:
                from jarvis_messaging import send_whatsapp
                return send_whatsapp(contact, msg), {}
            except ImportError:
                return "Messaging module not loaded, sir.", {}
        else:
            try:
                from jarvis_messaging import send_imessage
                return send_imessage(contact, msg), {}
            except ImportError:
                return "Messaging module not loaded, sir.", {}

    # ── Browser (opens URLs natively, Playwright removed) ──────────────
    if m := re.search(r"\b(?:open|go to|navigate to|browse to)\s+(https?://\S+|\S+\.(?:com|org|io|ai|co|net|app)\S*)", q):
        import webbrowser, subprocess
        url = m.group(1).strip()
        if not url.startswith("http"):
            url = "https://" + url
        subprocess.Popen(["open", url])
        return f"Opening {url} in your browser, sir.", {}

    if m := re.search(r"\b(?:search (the web|google|online) for|look up online)\s+(.+)", q):
        import subprocess
        query = m.group(2).strip().replace(" ", "+")
        subprocess.Popen(["open", f"https://www.google.com/search?q={query}"])
        return f"Searching Google for {m.group(2).strip()}, sir.", {}

    # ── File Reading & Editing ───────────────────────────────────
    if m := re.search(r"\b(?:edit|modify|change|update)\b.{0,30}(?:file|document|note)?\s+(?:called\s+|named\s+)?(.+?)\s+(?:to|and|by)\s+(.+)", q):
        fname = m.group(1).strip().strip("\"'")
        instruction = m.group(2).strip()
        return _edit_file_content(fname, instruction), {}
        
    # More strict file reading regex so it doesn't catch "open whatsapp"
    if m := re.search(r"\b(?:read|summarize|open|what(?:'s| is) in)\b\s+(?:the\s+)?(?:file|document|pdf|note)\s+(?:called\s+|named\s+)?(.+)", q) or \
       (m := re.search(r"\b(?:read|summarize|open|what(?:'s| is) in)\b\s+(?:the\s+)?([\w\-\./]+\.[a-zA-Z0-9]+)", q)):
        fname = m.group(1).strip().strip("\"'")
        return _read_file_content(fname), {}

    # ── Roadmap / Explicit Planning ──────────────────────────────────
    if re.search(r"\b(roadmap|plan my week|plan my day|create a plan|create tasks for me|plan out|plan this week)\b", q):
        import threading
        try:
            import jarvis_autonomous
            threading.Thread(target=jarvis_autonomous.force_plan, args=(question,), daemon=True).start()
            return "I am drafting a comprehensive plan for you now, sir. I will open Tasks.md when it is ready.", {}
        except Exception as e:
            return f"Failed to start planner, sir: {e}", {}

    # ── Screen / Vision ──────────────────────────────────────────
    if re.search(r"\b(what(?:'s| is) on (my )?screen|what am i (looking at|seeing)|analyze (my )?screen|describe (my )?screen)\b", q):
        try:
            from jarvis_vision import analyze_screen
            backend = "gemini" if re.search(r"\bgemini\b", q) else "mlx" if re.search(r"\bmlx\b", q) else "auto"
            return analyze_screen(backend=backend), {}
        except ImportError:
            return "Vision module not loaded, sir.", {}

    if m := re.search(r"\b(?:analyze|describe|read text in)\s+(?:the\s+)?(?:image|photo|screenshot|picture)\s+(.+)", q):
        try:
            from jarvis_vision import analyze_image_file
            return analyze_image_file(m.group(1).strip()), {}
        except ImportError:
            return "Vision module not loaded, sir.", {}

    if re.search(r"\b(read my (messages|texts)|any new (messages|texts))\b", q):
        try:
            from jarvis_messaging import read_unread_messages
            return read_unread_messages(), {}
        except ImportError:
            return "Messaging module not loaded, sir.", {}

    # ── CRM queries ──────────────────────────────────────────────
    if m := re.search(r"\b(?:what do (?:i|you) know about|tell me about|crm for|relationship with)\s+(.+)", q):
        try:
            from jarvis_crm import get_crm_summary
            return get_crm_summary(m.group(1).strip()), {}
        except ImportError:
            return "CRM module not loaded, sir.", {}

    if re.search(r"\b(my contacts|who(?:'ve| have) i (been talking|spoken|messaged)|recent contacts)\b", q):
        try:
            from jarvis_crm import get_crm_summary
            return get_crm_summary(), {}
        except ImportError:
            return "CRM module not loaded, sir.", {}

    # ── Browser ──────────────────────────────────────────────────
    if m := re.search(r"\b(?:open|go to|navigate to|browse to)\s+(.+)", q):
        if re.search(r"\b(browser|website|chrome|url|http|\.com|\.org|\.io)\b", q) or re.search(r"\b(?:open|go to)\s+\S+\.\S+", q):
            try:
                from jarvis_browser import open_url
                url = m.group(1).strip()
                if not url.startswith("http"):
                    url = "https://" + url
                return open_url(url), {}
            except ImportError:
                return "Browser module not loaded, sir.", {}

    if m := re.search(r"\b(?:search (the web|google|online) for|look up online)\s+(.+)", q):
        try:
            from jarvis_browser import search_web
            return search_web(m.group(2).strip()), {}
        except ImportError:
            return "Browser module not loaded, sir.", {}

    # ── YouTube ──────────────────────────────────────────────────
    if m := re.search(r"\b(?:play|search for)\s+(.+?)\s+(?:on|in)\s+youtube\b", q):
        try:
            from jarvis_youtube import play_on_youtube
            return play_on_youtube(m.group(1).strip()), {}
        except ImportError:
            return "YouTube module not loaded, sir.", {}
            
    # ── App Management ───────────────────────────────────────────
    if m := re.search(r"\b(?:open|launch|start)\s+(.+)", q):
        # We only catch 'open X' if it didn't match Browser URL, File, or WhatsApp above.
        # It's a fallback app opener.
        app_name = m.group(1).strip().title()
        if app_name.lower() not in ["browser", "website", "chrome", "url", "whatsapp"]:
            try:
                from jarvis_apps import open_app
                return open_app(app_name), {}
            except ImportError:
                return "App Management module not loaded, sir.", {}
                
    if m := re.search(r"\b(?:install|download)\s+([a-zA-Z0-9_\- ]+)\b", q):
        app_name = m.group(1).strip().title()
        try:
            from jarvis_apps import install_app
            return install_app(app_name), {}
        except ImportError:
            return "App Management module not loaded, sir.", {}

    # ── No action matched ────────────────────────────────────

    return "", {}
