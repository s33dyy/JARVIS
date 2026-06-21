import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from jarvis_context import get_raw

MEMORY_FILE = Path.home() / ".jarvis_memory.json"

def load_memory() -> dict:
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text())
        except Exception:
            return {"sessions": {}, "last_seen": {}, "events": [], "tasks_auto_added": []}
    return {"sessions": {}, "last_seen": {}, "events": [], "tasks_auto_added": []}

def save_memory(mem: dict):
    MEMORY_FILE.write_text(json.dumps(mem, indent=2))

def update_patterns():
    """Called periodically to sample user activity and learn patterns."""
    raw = get_raw()
    if not raw:
        return
        
    mem = load_memory()
    if "tasks_auto_added" not in mem:
        mem["tasks_auto_added"] = []
        
    now = datetime.now()
    now_str = now.isoformat()
    
    # 1. Check Git Repos for active work
    repos = raw.get("git", [])
    for r in repos:
        # A repo is active if it's dirty or recently committed
        is_active = r.get("dirty", 0) > 0
        
        last = r.get("last", "")
        if "minute" in last or "second" in last:
            is_active = True
            
        if is_active:
            name = r["name"]
            if name not in mem["sessions"]:
                mem["sessions"][name] = {"start": now_str, "last_active": now_str, "duration_minutes": 0}
            else:
                last_active = datetime.fromisoformat(mem["sessions"][name]["last_active"])
                if (now - last_active).total_seconds() < 3600:
                    # Continue session
                    mem["sessions"][name]["duration_minutes"] += (now - last_active).total_seconds() / 60.0
                    mem["sessions"][name]["last_active"] = now_str
                else:
                    # New session
                    mem["sessions"][name] = {"start": now_str, "last_active": now_str, "duration_minutes": 0}
                    
    save_memory(mem)

def get_current_session() -> Optional[dict]:
    mem = load_memory()
    now = datetime.now()
    
    active_sessions = []
    for name, data in mem.get("sessions", {}).items():
        last_active = datetime.fromisoformat(data["last_active"])
        if (now - last_active).total_seconds() < 1800: # Active in last 30 min
            active_sessions.append({"name": name, "duration": data["duration_minutes"]})
            
    if active_sessions:
        # Sort by duration
        active_sessions.sort(key=lambda x: x["duration"], reverse=True)
        return active_sessions[0]
    return None

def format_duration(minutes: float) -> str:
    if minutes < 60:
        return f"{int(minutes)}m"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours}h {mins}m"
