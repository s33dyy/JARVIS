"""
jarvis_reminders.py
-------------------
Proactive meeting reminder engine for JARVIS.

Runs as a background daemon thread that polls calendar events every 60 seconds
and speaks reminders at the 10-minute and 5-minute marks before each event.
"""

import json
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_reminded: set[str] = set()   # keys: "<event_title>@<reminder_mark>" e.g. "Standup@10"
_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


# ---------------------------------------------------------------------------
# Speech helper
# ---------------------------------------------------------------------------

def speak(text: str) -> None:
    """Speak *text* using macOS text-to-speech (non-blocking)."""
    try:
        import jarvis_speak
        jarvis_speak.speak(text)
    except Exception as exc:
        print(f"[reminders] Speech error: {exc}")


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------

def _get_events_google() -> list[dict]:
    """
    Return today's calendar events via jarvis_google.get_today_events().
    Each item is expected to be a dict with at least:
        - 'title' (str)  — event summary / name
        - 'start' (datetime or ISO-8601 str) — start time
    Returns an empty list on any error.
    """
    try:
        import jarvis_google  # type: ignore

        if not jarvis_google.is_connected():
            return []

        raw_events, err = jarvis_google.get_events()
        events: list[dict] = []

        for ev in raw_events:
            # Normalise the start field to a datetime object
            start = ev.get("start")
            if isinstance(start, str):
                # Try both ISO formats: with/without fractional seconds
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                            "%Y-%m-%d %H:%M:%S"):
                    try:
                        start = datetime.strptime(start[:19], fmt[:len(fmt)])
                        break
                    except ValueError:
                        continue

            if isinstance(start, datetime):
                events.append({
                    "title": ev.get("title") or ev.get("summary") or "Untitled",
                    "start": start,
                })

        return events

    except Exception as exc:  # noqa: BLE001
        print(f"[reminders] Google Calendar error: {exc}")
        return []





def _get_upcoming_events() -> list[dict]:
    """
    Try Google Calendar first; fall back to macOS Calendar.
    Returns a list of dicts: [{'title': str, 'start': datetime}, ...]
    """
    events = _get_events_google()
    return events


_agent_notified_file = Path.home() / ".jarvis" / "agent_notified.json"

def _load_agent_notified() -> dict:
    if not _agent_notified_file.exists():
        return {}
    try:
        return json.loads(_agent_notified_file.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_agent_notified(data: dict) -> None:
    try:
        _agent_notified_file.parent.mkdir(parents=True, exist_ok=True)
        _agent_notified_file.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass

def _check_agent_notifications() -> None:
    """
    Scan active agents and issue verbal/printed notifications when:
      1. An agent is waiting for plan approval (feedback requested).
      2. An agent is waiting for permission (command needs approval).
      3. An agent has completed a task.
    """
    try:
        import jarvis_agent_monitor
        convs = jarvis_agent_monitor.get_active_conversations(limit=5)
        if not convs:
            return

        notified = _load_agent_notified()
        changed = False

        now_ts = time.time()
        for c in convs:
            conv_id = c["conv_id"]
            mtime = c["mtime"]
            
            details = jarvis_agent_monitor.parse_conversation(conv_id)
            if not details:
                continue

            status = details["status"]
            goal = details["goal"]
            
            # Prevent notification storms for historical conversations at startup
            is_recent = (now_ts - mtime) < 300
            if not is_recent:
                state = notified.get(conv_id, {})
                if state.get("last_status") != status or state.get("last_step_time") != details.get("last_step_time"):
                    notified[conv_id] = {
                        "last_status": status,
                        "last_step_time": details.get("last_step_time")
                    }
                    changed = True
                continue

            state = notified.get(conv_id, {})
            last_status = state.get("last_status")
            last_step_time = state.get("last_step_time")
            current_step_time = details.get("last_step_time")

            should_notify = False
            msg = ""

            if status != last_status or current_step_time != last_step_time:
                if status == "Waiting for plan approval":
                    msg = f"Sir, the agent working on '{goal}' has proposed an implementation plan and is waiting for your feedback."
                    should_notify = True
                elif status == "Waiting for permission":
                    pending_desc = "a command"
                    if details["pending_tools"]:
                        tool_name = details["pending_tools"][0].get("name", "command")
                        pending_desc = f"tool {tool_name}"
                        args = details["pending_tools"][0].get("args", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                pass
                        cmd = args.get("CommandLine")
                        if cmd:
                            pending_desc = f"command: {cmd}"
                    msg = f"Sir, the agent working on '{goal}' is waiting for permission to execute {pending_desc}."
                    should_notify = True
                elif status == "Completed" and last_status != "Completed":
                    msg = f"Sir, the agent has successfully completed the task: '{goal}'."
                    should_notify = True

            if should_notify and msg:
                print(f"\n  🤖  AGENT NOTICE: {msg}\n")
                speak(msg)
                
                notified[conv_id] = {
                    "last_status": status,
                    "last_step_time": current_step_time
                }
                changed = True

        if changed:
            _save_agent_notified(notified)

    except Exception as exc:
        print(f"[reminders] Agent notification check failed: {exc}")


# ---------------------------------------------------------------------------
# Reminder logic
# ---------------------------------------------------------------------------

def _check_and_remind() -> None:
    """
    Inspect upcoming events and issue spoken + printed reminders at the
    10-minute and 5-minute marks (if not already reminded).
    """
    now = datetime.now()
    events = _get_upcoming_events()

    for ev in events:
        title: str = ev["title"]
        start: datetime = ev["start"]

        minutes_away = (start - now).total_seconds() / 60.0

        for mark in (10, 5):
            # Fire the reminder when we're within [mark-1, mark+1) minutes away
            if mark - 1 < minutes_away <= mark + 1:
                key = f"{title}@{mark}"
                if key not in _reminded:
                    _reminded.add(key)
                    _fire_reminder(title, round(minutes_away), mark)


def _fire_reminder(title: str, minutes_away: int, mark: int) -> None:
    """Speak and print a reminder for *title*."""
    label = f"{minutes_away} minute{'s' if minutes_away != 1 else ''}"
    print(f"\n  \U0001f514  REMINDER: {title} starts in {label}\n")
    speak(f"Heads up, {title} starts in {label}.")


# ---------------------------------------------------------------------------
# Background daemon thread
# ---------------------------------------------------------------------------

def _run_loop(interval: int = 60) -> None:
    """Main loop executed in the daemon thread."""
    print("[reminders] Reminder engine started.")
    _last_adhd_checkin = time.time()
    
    while not _stop_event.is_set():
        try:
            _check_and_remind()
            _check_agent_notifications()
            
            # ADHD Focus Check-in every 90 minutes (5400 seconds)
            now = datetime.now()
            if 9 <= now.hour < 17:
                if time.time() - _last_adhd_checkin > 5400:
                    speak("Sir, quick check-in. Are you hydrated, and are we still focusing on the primary task?")
                    _last_adhd_checkin = time.time()
                    
        except Exception as exc:  # noqa: BLE001
            print(f"[reminders] Unexpected error: {exc}")
        # Wait for *interval* seconds, but check the stop flag every second
        # so the thread can be killed quickly.
        for _ in range(interval):
            if _stop_event.is_set():
                break
            time.sleep(1)
    print("[reminders] Reminder engine stopped.")


def start(interval: int = 60) -> threading.Thread:
    """
    Launch the reminder engine as a background daemon thread.

    Parameters
    ----------
    interval : int
        How often (in seconds) to poll the calendar. Default: 60.

    Returns
    -------
    threading.Thread
        The running daemon thread (for reference; you don't need to join it).
    """
    global _thread

    if _thread is not None and _thread.is_alive():
        print("[reminders] Reminder engine is already running.")
        return _thread

    _stop_event.clear()
    _thread = threading.Thread(
        target=_run_loop,
        args=(interval,),
        name="JARVISReminderDaemon",
        daemon=True,       # dies automatically when the main process exits
    )
    _thread.start()
    return _thread


def stop() -> None:
    """Signal the reminder engine to stop cleanly."""
    _stop_event.set()


# ---------------------------------------------------------------------------
# Quick self-test (run this file directly)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Running reminder engine for 10 seconds as a self-test...")
    start(interval=5)   # poll every 5 s for the test
    time.sleep(10)
    stop()
    time.sleep(2)
    print("Done.")
