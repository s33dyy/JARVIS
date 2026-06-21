import json
from pathlib import Path

_PROJECTS_FILE = Path.home() / ".jarvis" / "projects.json"

def _load() -> dict:
    if not _PROJECTS_FILE.exists():
        return {}
    try:
        return json.loads(_PROJECTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save(data: dict) -> None:
    _PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROJECTS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def set_project_status(project_name: str, status: str) -> None:
    """Sets a project's status (e.g. active, paused)."""
    data = _load()
    project_key = project_name.lower().replace(" ", "_")
    if project_key not in data:
        data[project_key] = {"name": project_name}
    data[project_key]["status"] = status
    _save(data)

def get_projects() -> dict:
    """Returns all project states."""
    return _load()

def get_active_projects_context() -> str:
    """Returns a string suitable for LLM context indicating active/paused projects."""
    projects = _load()
    if not projects:
        return ""
    
    active = [p["name"] for p in projects.values() if p.get("status") == "active"]
    paused = [p["name"] for p in projects.values() if p.get("status") == "paused"]
    
    ctx = []
    if active:
        ctx.append(f"Active Projects (FOCUS ON THESE): {', '.join(active)}")
    if paused:
        ctx.append(f"Paused Projects (IGNORE THESE COMPLETELY): {', '.join(paused)}")
        
    return "\n".join(ctx)
