import json
from pathlib import Path
from datetime import datetime

_ERROR_FILE = Path.home() / ".jarvis" / "error_database.json"
_ESCALATION_THRESHOLD = 5

def _load() -> dict:
    if not _ERROR_FILE.exists():
        return {}
    try:
        return json.loads(_ERROR_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save(data: dict) -> None:
    _ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ERROR_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def record_error(error_type: str, command: str, wrong_action: str) -> None:
    """
    Records an interaction error. Grouped by the wrong action/intent.
    """
    data = _load()
    
    key = f"{error_type}_{wrong_action}"
    
    if key not in data:
        data[key] = {
            "type": error_type,
            "command": command,
            "wrong_action": wrong_action,
            "count": 0,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat()
        }
    
    data[key]["count"] += 1
    data[key]["command"] = command
    data[key]["last_seen"] = datetime.now().isoformat()
    
    _save(data)
    
    # Check for escalation to the main issue tracker
    if data[key]["count"] >= _ESCALATION_THRESHOLD:
        try:
            from jarvis_issue_tracker import record_failure
            desc = f"Repeated {error_type} failure. User said '{command}', system did '{wrong_action}'."
            record_failure(f"evaluator_{key}", desc, "high")
        except Exception as e:
            print(f"[ErrorTracker] Failed to escalate issue: {e}")

def get_top_errors(limit: int = 5) -> list[dict]:
    data = _load()
    sorted_errors = sorted(data.values(), key=lambda x: x["count"], reverse=True)
    return sorted_errors[:limit]
