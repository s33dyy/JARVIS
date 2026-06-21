"""
jarvis_failure_store.py
───────────────────────
Unified failure tracking for ALL JARVIS subsystems.
"""

import json, threading, logging
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_JARVIS_DIR = Path.home() / ".jarvis"
_FAILURES_FILE = _JARVIS_DIR / "failures.json"
_lock = threading.Lock()

ESCALATION_THRESHOLD = 3

def _load() -> dict[str, Any]:
    with _lock:
        try:
            if _FAILURES_FILE.exists():
                return json.loads(_FAILURES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

def _save(data: dict[str, Any]) -> None:
    with _lock:
        try:
            _JARVIS_DIR.mkdir(parents=True, exist_ok=True)
            _FAILURES_FILE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as e:
            logger.error(f"[FailureStore] Could not save: {e}")

def record_failure(
    component: str,
    error: str,
    severity: str = "medium",
    category: str = "subsystem",
    command: str = "",
    wrong_action: str = "",
) -> dict:
    data = _load()
    now = datetime.now().isoformat()

    if component not in data:
        data[component] = {
            "category": category,
            "count": 0,
            "severity": severity,
            "first_seen": now,
            "last_seen": now,
            "last_error": error,
            "escalated": False,
            "resolved": False,
        }

    entry = data[component]
    entry["count"] += 1
    entry["last_seen"] = now
    entry["last_error"] = error
    entry["severity"] = severity
    entry["resolved"] = False

    if command:
        entry["command"] = command
    if wrong_action:
        entry["wrong_action"] = wrong_action

    _save(data)

    if entry["count"] >= ESCALATION_THRESHOLD and not entry.get("escalated"):
        entry["escalated"] = True
        _save(data)
        logger.warning(f"[FailureStore] ESCALATED: {component} ({entry['count']} failures)")

    return entry

def record_success(component: str) -> None:
    data = _load()
    if component in data:
        data[component]["resolved"] = True
        _save(data)

def get_active_failures() -> dict[str, Any]:
    data = _load()
    return {k: v for k, v in data.items() if not v.get("resolved", False)}

def get_today_failures() -> dict[str, Any]:
    data = _load()
    today = date.today().isoformat()
    return {
        k: v for k, v in data.items()
        if v.get("last_seen", "").startswith(today) and v.get("count", 0) > 0
    }

def get_escalated_failures() -> list[dict]:
    data = _load()
    SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    escalated = [
        {**v, "component": k}
        for k, v in data.items()
        if v.get("escalated") and not v.get("resolved")
    ]
    escalated.sort(key=lambda x: (SEVERITY_RANK.get(x["severity"], 99), -x["count"]))
    return escalated

def get_health_summary_for_llm() -> str:
    active = get_active_failures()
    if not active:
        return ""

    lines = ["CURRENT SYSTEM FAILURES (real, verified):"]
    for comp, data in sorted(active.items(),
                              key=lambda kv: kv[1].get("count", 0), reverse=True):
        lines.append(
            f"  - {comp}: {data['last_error']} "
            f"(severity={data['severity']}, count={data['count']})"
        )
    lines.append("DO NOT claim these subsystems are working. Report failures honestly.")
    return "\n".join(lines)
