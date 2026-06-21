"""
JARVIS Context Engine — builds a live "situational awareness" snapshot.

Aggregates:
  - Local filesystem: git repos, recent files, open projects, external drives
  - macOS Calendar: today + tomorrow events (via AppleScript)
  - macOS Reminders: pending items
  - Google Calendar: today's events (if connected)
  - Google Gmail: unread email count + summaries (if connected)

Output: a concise plain-text block injected into every JARVIS query so
the model always knows what YOU are doing right now.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────
HOME = Path.home()

# Directories to scan for projects and recent files
# "whole fs from root" — we scan HOME deeply + /Volumes for external drives
SCAN_ROOTS = [HOME, Path("/Volumes")]

# Directories to completely skip (noise/system)
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".cache", "Library", ".Trash", "Applications", "System", "private",
    ".local", ".npm", ".cargo", "build", "dist", ".DS_Store",
}

MAX_RECENT_FILES = 10   # files modified in last 24h to surface
MAX_GIT_REPOS    = 8    # git repos to summarise
MAX_PROJECTS     = 8    # non-git project dirs

# File extensions that indicate an active project
PROJECT_MARKERS = {
    "pyproject.toml": "Python",
    "package.json":   "Node/JS",
    "Cargo.toml":     "Rust",
    "go.mod":         "Go",
    "*.xcodeproj":    "Xcode/Swift",
    "*.xcworkspace":  "Xcode/Swift",
    "Makefile":       "C/C++",
    "CMakeLists.txt": "C/C++",
    "pom.xml":        "Java/Maven",
    "build.gradle":   "Java/Gradle",
}


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _run(cmd: list[str], cwd: Optional[str] = None, timeout: int = 5) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
        return r.stdout.strip()
    except Exception:
        return ""


def _osascript(script: str) -> str:
    return _run(["osascript", "-e", script], timeout=8)


# ─────────────────────────────────────────────────────────────
# Local filesystem scanner
# ─────────────────────────────────────────────────────────────
def _find_git_repos() -> list[dict]:
    """Walk HOME for git repos, grab branch + last commit summary."""
    if os.environ.get("JARVIS_USE_CASE", "Developer") != "Developer":
        return []
    repos = []
    visited = set()

    def _walk(root: Path, depth: int = 0) -> None:
        if depth > 6 or len(repos) >= MAX_GIT_REPOS:
            return
        try:
            for entry in root.iterdir():
                if not entry.is_dir() or entry.name.startswith(".") and entry.name != ".":
                    continue
                if entry.name in SKIP_DIRS:
                    continue
                git_dir = entry / ".git"
                if git_dir.exists() and str(entry) not in visited:
                    visited.add(str(entry))
                    branch  = _run(["git", "branch", "--show-current"], cwd=str(entry))
                    log     = _run(["git", "log", "-1", "--format=%s (%cr)"], cwd=str(entry))
                    status  = _run(["git", "status", "--short"], cwd=str(entry))
                    changed = len(status.splitlines()) if status else 0
                    repos.append({
                        "path":    str(entry),
                        "name":    entry.name,
                        "branch":  branch or "?",
                        "last":    log or "no commits",
                        "dirty":   changed,
                    })
                elif depth < 4:
                    _walk(entry, depth + 1)
        except PermissionError:
            pass

    _walk(HOME)
    return repos


def _find_recent_files(hours: int = 48) -> list[dict]:
    """Find files modified in the last N hours across HOME."""
    cutoff = datetime.now() - timedelta(hours=hours)
    results = []

    skip_exts = {".pyc", ".o", ".class", ".log", ".lock", ".cache"}
    skip_names = {"DS_Store", "Thumbs.db", ".gitignore"}

    def _walk(root: Path, depth: int = 0) -> None:
        if depth > 5 or len(results) >= MAX_RECENT_FILES * 3:
            return
        try:
            for entry in root.iterdir():
                if entry.name in skip_names or entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    if entry.name in SKIP_DIRS:
                        continue
                    _walk(entry, depth + 1)
                elif entry.is_file():
                    if entry.suffix in skip_exts:
                        continue
                    try:
                        mtime = datetime.fromtimestamp(entry.stat().st_mtime)
                        if mtime > cutoff:
                            results.append({
                                "path": str(entry),
                                "name": entry.name,
                                "mtime": mtime,
                                "size_kb": round(entry.stat().st_size / 1024, 1),
                            })
                    except OSError:
                        pass
        except OSError:
            pass

    _walk(HOME)
    # Sort newest first
    results.sort(key=lambda x: x["mtime"], reverse=True)
    return results[:MAX_RECENT_FILES]


def _find_projects() -> list[dict]:
    """Detect active projects by looking for marker files."""
    use_case = os.environ.get("JARVIS_USE_CASE", "Developer")
    if use_case == "Personal":
        return []

    projects = []
    visited_repos = set()

    # Determine markers dynamically based on use case
    if use_case == "Creator":
        markers = {
            ".obsidian":      "Obsidian Vault",
            "metadata.yaml":  "Creative Draft",
            "chapters":       "Book Project",
            "scripts":        "Screenplay Project",
            "assets":         "Media Project",
        }
    elif use_case == "Manager":
        markers = {
            "roadmap.md":     "Product Roadmap",
            "planning":       "Planning Folder",
            "budget.xlsx":    "Financial Project",
            "okrs.md":        "Strategy Vault",
        }
    else:  # Developer
        markers = PROJECT_MARKERS

    def _walk(root: Path, depth: int = 0) -> None:
        if depth > 5 or len(projects) >= MAX_PROJECTS:
            return
        try:
            entries = list(root.iterdir())
        except OSError:
            return

        names = {e.name for e in entries}

        for marker, lang in markers.items():
            # Handle glob markers
            if "*" in marker:
                ext = marker.lstrip("*")
                matched = [e for e in entries if e.name.endswith(ext)]
                if matched and str(root) not in visited_repos:
                    visited_repos.add(str(root))
                    projects.append({"path": str(root), "name": root.name, "type": lang})
                    return
            elif marker in names:
                if str(root) not in visited_repos:
                    visited_repos.add(str(root))
                    projects.append({"path": str(root), "name": root.name, "type": lang})
                    return

        for entry in entries:
            if entry.is_dir() and entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                _walk(entry, depth + 1)

    _walk(HOME)
    return projects


def _find_external_drives() -> list[str]:
    volumes = []
    try:
        for v in Path("/Volumes").iterdir():
            if v.name != "Macintosh HD" and v.is_dir():
                volumes.append(v.name)
    except Exception:
        pass
    return volumes


# ─────────────────────────────────────────────────────────────
# macOS Calendar (no API key needed)
# ─────────────────────────────────────────────────────────────
def _get_macos_calendar_events() -> list[str]:
    """Fetch today's and tomorrow's calendar events via AppleScript."""
    script = """
set output to ""
tell application "Calendar"
    set today to current date
    set todayStart to today
    set hours of todayStart to 0
    set minutes of todayStart to 0
    set seconds of todayStart to 0
    set tomorrowEnd to todayStart + (2 * days)
    repeat with aCal in calendars
        repeat with anEvent in (every event of aCal whose start date >= todayStart and start date < tomorrowEnd)
            try
                set evTitle to summary of anEvent
                set evStart to start date of anEvent
                set evEnd to end date of anEvent
                set output to output & evStart & " | " & evTitle & "\n"
            end try
        end repeat
    end repeat
end tell
return output
"""
    raw = _osascript(script)
    if not raw:
        return []
    events = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if "|" in line:
            parts = line.split("|", 1)
            events.append(f"{parts[0].strip()} — {parts[1].strip()}")
    return sorted(events)


# ─────────────────────────────────────────────────────────────
# macOS Reminders
# ─────────────────────────────────────────────────────────────
def _get_macos_reminders() -> list[str]:
    script = """
set output to ""
tell application "Reminders"
    repeat with aList in lists
        repeat with aReminder in (reminders of aList whose completed is false)
            try
                set output to output & name of aReminder & "\n"
            end try
        end repeat
    end repeat
end tell
return output
"""
    raw = _osascript(script)
    if not raw:
        return []
    items = [r.strip() for r in raw.strip().splitlines() if r.strip()]
    return items[:10]


# ─────────────────────────────────────────────────────────────
# Google Calendar (via stored OAuth tokens)
# ─────────────────────────────────────────────────────────────
GOOGLE_CREDS = str(HOME / ".openjarvis" / "connectors" / "google.json")


def _google_token() -> Optional[str]:
    """Return a valid Google access token, refreshing if needed."""
    try:
        from openjarvis.connectors.oauth import load_tokens, refresh_google_token
        creds_path = str(HOME / ".openjarvis" / "connectors" / "google.json")
        tokens = load_tokens(creds_path)
        if not tokens:
            return None
        token = tokens.get("access_token") or tokens.get("token")
        if token:
            return token
        return refresh_google_token(creds_path)
    except Exception:
        return None


def _get_google_calendar_events() -> list[str]:
    """Fetch today's Google Calendar events via API."""
    import httpx
    token = _google_token()
    if not token:
        return []
    try:
        now = datetime.utcnow()
        time_min = now.strftime("%Y-%m-%dT00:00:00Z")
        time_max = (now + timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")
        resp = httpx.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 15,
            },
            timeout=10,
        )
        if resp.status_code == 401:
            # Refresh and retry once
            from openjarvis.connectors.oauth import refresh_google_token
            token = refresh_google_token(GOOGLE_CREDS)
            if not token:
                return []
            resp = httpx.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "timeMin": time_min, "timeMax": time_max,
                    "singleEvents": "true", "orderBy": "startTime", "maxResults": 15,
                },
                timeout=10,
            )
        events = []
        for item in resp.json().get("items", []):
            title = item.get("summary", "Untitled")
            start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", "")
            if start:
                try:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    start_str = dt.strftime("%a %I:%M %p")
                except Exception:
                    start_str = start[:10]
                events.append(f"{start_str} — {title}")
        return events
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# Gmail unread summary
# ─────────────────────────────────────────────────────────────
def _get_gmail_unread() -> list[str]:
    """Return the last 5 unread email subjects + senders."""
    import httpx
    token = _google_token()
    if not token:
        return []
    try:
        resp = httpx.get(
            "https://www.googleapis.com/gmail/v1/users/me/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": "is:unread", "maxResults": 5},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        messages = resp.json().get("messages", [])
        summaries = []
        for msg in messages:
            msg_resp = httpx.get(
                f"https://www.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "metadata", "metadataHeaders": ["Subject", "From"]},
                timeout=10,
            )
            if msg_resp.status_code != 200:
                continue
            headers = {h["name"]: h["value"] for h in
                       msg_resp.json().get("payload", {}).get("headers", [])}
            subject = headers.get("Subject", "(no subject)")[:60]
            sender  = headers.get("From", "?").split("<")[0].strip()[:30]
            summaries.append(f"From {sender}: {subject}")
        return summaries
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# Desktop files (PDFs, docs, task reports)
# ─────────────────────────────────────────────────────────────
def _get_desktop_files() -> list[str]:
    """Return top 15 recently modified files on Desktop."""
    try:
        desktop = HOME / "Desktop"
        files = []
        for f in desktop.iterdir():
            if f.is_file() and not f.name.startswith("."):
                files.append((f, f.stat().st_mtime))
        files.sort(key=lambda x: x[1], reverse=True)
        return [f[0].name for f in files[:15]]
    except Exception:
        return []


def _get_todoist_tasks() -> str:
    try:
        import jarvis_todoist
        return jarvis_todoist.get_all_tasks_summary()
    except Exception:
        return ""

def _get_obsidian_crm() -> list[str]:
    try:
        import jarvis_obsidian
        vault, jarvis_dir, daily_dir, crm_dir, projects_dir = jarvis_obsidian._init_jarvis_dirs()
        summaries = []
        for f in crm_dir.glob("*.md"):
            content = f.read_text().splitlines()
            last_log = next((line for line in reversed(content) if line.startswith("- **")), "")
            summaries.append(f"{f.stem}: {last_log}")
        return summaries
    except Exception:
        return []

def _get_obsidian_projects() -> list[str]:
    try:
        import jarvis_obsidian
        vault, jarvis_dir, daily_dir, crm_dir, projects_dir = jarvis_obsidian._init_jarvis_dirs()
        summaries = []
        for f in projects_dir.glob("*.md"):
            content = f.read_text()
            import re
            status = re.search(r"## 📊 Status\n(.*?)(?=\n\n##|$)", content, flags=re.DOTALL)
            status_text = status.group(1).strip() if status else "No status"
            summaries.append(f"{f.stem}: {status_text}")
        return summaries
    except Exception:
        return []


def _get_agent_context_data() -> list[dict]:
    """Retrieve metadata of the most recent active agents."""
    try:
        import jarvis_agent_monitor
        convs = jarvis_agent_monitor.get_active_conversations(limit=3)
        agent_data = []
        for c in convs:
            details = jarvis_agent_monitor.parse_conversation(c["conv_id"])
            if details:
                agent_data.append(details)
        return agent_data
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# Builder / Orchestrator
# ─────────────────────────────────────────────────────────────
_CACHE = {}
_CACHE_TIME = datetime.min
perf_mode = os.environ.get("JARVIS_PERFORMANCE_MODE", "Balanced")
if perf_mode == "M3 Air 8GB (Low Power)":
    _CACHE_TTL_SECONDS = 1800  # 30 mins
elif perf_mode == "Balanced":
    _CACHE_TTL_SECONDS = 600   # 10 mins
else:
    _CACHE_TTL_SECONDS = 120   # 2 mins   # refresh context every 2 min


def build_context(force: bool = False) -> str:
    """
    Build a concise plain-text situational awareness block.
    Results are cached for 2 minutes so voice responses stay fast.
    """
    global _CACHE, _CACHE_TIME
    now = datetime.now()
    if not force and (now - _CACHE_TIME).total_seconds() < _CACHE_TTL_SECONDS:
        return _CACHE.get("text", "")

    # Run all collectors in parallel threads
    results: dict = {}
    threads = [
        threading.Thread(target=lambda: results.update({"git":      _find_git_repos()}),      daemon=True),
        threading.Thread(target=lambda: results.update({"recent":   _find_recent_files(48)}), daemon=True),
        threading.Thread(target=lambda: results.update({"projects": _find_projects()}),        daemon=True),
        threading.Thread(target=lambda: results.update({"drives":   _find_external_drives()}), daemon=True),
        threading.Thread(target=lambda: results.update({"mac_cal":  _get_macos_calendar_events()}), daemon=True),
        threading.Thread(target=lambda: results.update({"reminders":_get_macos_reminders()}), daemon=True),
        threading.Thread(target=lambda: results.update({"gcal":     _get_google_calendar_events()}), daemon=True),
        threading.Thread(target=lambda: results.update({"gmail":    _get_gmail_unread()}),    daemon=True),
        threading.Thread(target=lambda: results.update({"desktop":  _get_desktop_files()}),   daemon=True),
        threading.Thread(target=lambda: results.update({"todoist_tasks": _get_todoist_tasks()}), daemon=True),
        threading.Thread(target=lambda: results.update({"obsidian_crm": _get_obsidian_crm()}), daemon=True),
        threading.Thread(target=lambda: results.update({"obsidian_projects": _get_obsidian_projects()}), daemon=True),
        threading.Thread(target=lambda: results.update({"active_agents": _get_agent_context_data()}), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=12)   # max 12s total for all collectors

    lines = []
    dt_now = now.strftime("%A, %d %B %Y — %I:%M %p IST")
    lines.append(f"[JARVIS CONTEXT — {dt_now}]")

    # Calendar events (merge GCal + macOS, deduplicate by title)
    events = results.get("gcal") or results.get("mac_cal") or []
    if not events:
        events = results.get("mac_cal", [])
    if events:
        lines.append(f"\nTODAY'S CALENDAR ({len(events)} events):")
        for e in events[:8]:
            lines.append(f"  • {e}")
    else:
        lines.append("\nTODAY'S CALENDAR: No events found (or Calendar not authorised yet)")

    # Unread emails
    gmail = results.get("gmail", [])
    if gmail:
        lines.append(f"\nUNREAD EMAILS ({len(gmail)}):")
        for e in gmail:
            lines.append(f"  • {e}")

    # Reminders
    reminders = results.get("reminders", [])
    if reminders:
        lines.append(f"\nPENDING REMINDERS:")
        for r in reminders[:5]:
            lines.append(f"  • {r}")

    # Git repos
    repos = results.get("git", [])
    if repos:
        lines.append(f"\nACTIVE GIT REPOS ({len(repos)}):")
        for r in repos:
            dirty = f" [{r['dirty']} changed files]" if r['dirty'] else ""
            lines.append(f"  • {r['name']} [{r['branch']}]{dirty} — {r['last']}")

    # Projects (non-git)
    projects = [p for p in results.get("projects", [])
                if not any(r["name"] == p["name"] for r in repos)]
    if projects:
        lines.append(f"\nOTHER PROJECTS:")
        for p in projects[:5]:
            lines.append(f"  • {p['name']} ({p['type']})")

    # Recent files
    recent = results.get("recent", [])
    if recent:
        lines.append(f"\nRECENTLY MODIFIED FILES:")
        for f in recent[:6]:
            age = now - f["mtime"]
            age_str = f"{int(age.total_seconds()//3600)}h ago" if age.total_seconds() > 3600 else "just now"
            lines.append(f"  • {f['name']} ({age_str})")

    # Desktop notable files
    desktop = results.get("desktop", [])
    if desktop:
        # Only surface PDFs, docs, task reports
        notable = [f for f in desktop if any(
            f.endswith(ext) for ext in (".pdf", ".doc", ".docx", ".txt", ".md")
        ) or "task" in f.lower() or "report" in f.lower()]
        if notable:
            lines.append(f"\nDESKTOP NOTABLE FILES:")
            for f in notable[:5]:
                lines.append(f"  • {f}")

    # External drives
    drives = results.get("drives", [])
    if drives:
        lines.append(f"\nEXTERNAL DRIVES: {', '.join(drives)}")

    # Active Agent Chats
    agents = results.get("active_agents", [])
    if agents:
        lines.append(f"\nACTIVE BACKGROUND AGENT CHATS ({len(agents)}):")
        for a in agents:
            status_desc = f"Goal: {a['goal']} | Status: {a['status']}"
            if a["tasks"]["total"] > 0:
                status_desc += f" ({a['tasks']['percent']}% done)"
            lines.append(f"  • Conv {a['conv_id'][:8]} — {status_desc}")
            if a["tasks"]["active_items"]:
                lines.append(f"    - Current subtask: {a['tasks']['active_items'][0]}")
            if a["subagents"]:
                sub_names = ", ".join(s["name"] for s in a["subagents"])
                lines.append(f"    - Active subagents: {sub_names}")

    text = "\n".join(lines)
    _CACHE = {"text": text, "raw": results}
    _CACHE_TIME = now
    return text


def get_raw() -> dict:
    """Return raw structured data (for actions like scheduling)."""
    if not _CACHE:
        build_context()
    return _CACHE.get("raw", {})


def build_short_context() -> str:
    """
    Ultra-compact context for small LLM prompts (0.6B safe).
    Returns at most ~200 chars — just the key facts.
    """
    raw = get_raw()
    if not raw:
        # Try building if not yet warmed up
        build_context()
        raw = get_raw()

    parts = []
    now = datetime.now().strftime("%a %d %b %Y, %I:%M %p IST")
    parts.append(f"Now: {now}")

    # Calendar: just first 2 events
    events = raw.get("gcal") or raw.get("mac_cal") or []
    if events:
        parts.append(f"Calendar: {'; '.join(events[:2])}")
    else:
        parts.append("Calendar: clear today")

    # Email count
    gmail = raw.get("gmail", [])
    if gmail:
        parts.append(f"Unread emails: {len(gmail)}")

    # Active repo
    repos = raw.get("git", [])
    if repos:
        names = ", ".join(r["name"] for r in repos[:3])
        parts.append(f"Active repos: {names}")

    # Reminders
    reminders = raw.get("reminders", [])
    if reminders:
        parts.append(f"Reminders: {reminders[0]}")

    # Todoist tasks
    todo_tasks = raw.get("todoist_tasks", "")
    if todo_tasks:
        parts.append(f"Todoist tasks: {len(todo_tasks.splitlines())}")

    # Active agent status (compact)
    agents = raw.get("active_agents", [])
    if agents:
        a = agents[0]
        status_desc = a["status"]
        if a["tasks"]["total"] > 0:
            status_desc += f" {a['tasks']['percent']}%"
        parts.append(f"Agent {a['conv_id'][:8]}: {status_desc}")

    return " | ".join(parts)


# ─────────────────────────────────────────────────────────────
# Background warm-up (call once at startup)
# ─────────────────────────────────────────────────────────────
def warm_up() -> None:
    """Start building context in the background immediately at startup."""
    threading.Thread(target=build_context, daemon=True).start()


if __name__ == "__main__":
    print("Building context snapshot...\n")
    print(build_context(force=True))
    print("\n--- Short context (for LLM) ---")
    print(build_short_context())
