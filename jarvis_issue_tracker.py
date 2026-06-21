"""
jarvis_issue_tracker.py
───────────────────────
Health-facing bridge between jarvis_health.py and the Self-Improvement Engine.

Every time a health check fails, record_failure() is called. Once a component
crosses ESCALATION_THRESHOLD failures, a structured issue is created in
~/.jarvis/issues.json — which is picked up by SelfImprovementOrchestrator
during the nightly analysis run.

Schema for ~/.jarvis/health_failures.json:
{
  "gemini": {
    "count": 37,
    "severity": "critical",
    "first_seen": "2026-06-21T08:00:00",
    "last_seen": "2026-06-21T13:00:00",
    "last_error": "401 Unauthorized",
    "escalated": true
  },
  ...
}
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

_JARVIS_DIR = Path.home() / ".jarvis"
_HEALTH_FAILURES_FILE = _JARVIS_DIR / "health_failures.json"
_ISSUES_FILE = _JARVIS_DIR / "issues.json"

# Number of failures before an issue is escalated to the Self-Improvement Engine
ESCALATION_THRESHOLD = 5

_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# Storage helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_failures() -> dict[str, Any]:
    try:
        if _HEALTH_FAILURES_FILE.exists():
            return json.loads(_HEALTH_FAILURES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_failures(data: dict[str, Any]) -> None:
    try:
        _JARVIS_DIR.mkdir(parents=True, exist_ok=True)
        _HEALTH_FAILURES_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except OSError as e:
        logger.error(f"[IssueTracker] Could not save health_failures.json: {e}")


def _load_issues() -> dict[str, Any]:
    try:
        if _ISSUES_FILE.exists():
            return json.loads(_ISSUES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_issues(data: dict[str, Any]) -> None:
    try:
        _JARVIS_DIR.mkdir(parents=True, exist_ok=True)
        _ISSUES_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except OSError as e:
        logger.error(f"[IssueTracker] Could not save issues.json: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def record_failure(component: str, error: str, severity: str = "medium") -> None:
    """
    Records a health check failure for a component.

    If the failure count crosses ESCALATION_THRESHOLD, automatically creates
    an issue in ~/.jarvis/issues.json for the nightly Self-Improvement run.

    Args:
        component: Machine name of the component (e.g. "gemini", "todoist").
        error:     Human-readable error description.
        severity:  "critical" | "high" | "medium" | "low"
    """
    with _lock:
        failures = _load_failures()
        now = datetime.now().isoformat()

        if component not in failures:
            failures[component] = {
                "count": 0,
                "severity": severity,
                "first_seen": now,
                "last_seen": now,
                "last_error": error,
                "escalated": False,
            }

        entry = failures[component]
        entry["count"] += 1
        entry["last_seen"] = now
        entry["last_error"] = error
        entry["severity"] = severity  # update severity in case it changed

        count = entry["count"]
        already_escalated = entry.get("escalated", False)

        _save_failures(failures)
        logger.debug(f"[IssueTracker] {component} failure #{count}: {error[:60]}")

        # Escalate to Self-Improvement Engine once threshold is crossed
        if count >= ESCALATION_THRESHOLD and not already_escalated:
            _escalate_to_self_improvement(component, entry)
            failures[component]["escalated"] = True
            _save_failures(failures)


def record_success(component: str) -> None:
    """
    Records a successful health check.
    Resets the escalation flag so future failures can be re-escalated if
    the component breaks again after being fixed.
    """
    with _lock:
        failures = _load_failures()
        if component in failures and failures[component]["count"] > 0:
            # If the component recovers, reset for fresh tracking
            failures[component]["count"] = 0
            failures[component]["escalated"] = False
            _save_failures(failures)


def get_failure_count(component: str) -> int:
    """Returns the current rolling failure count for a component."""
    with _lock:
        failures = _load_failures()
        return failures.get(component, {}).get("count", 0)


def should_escalate(component: str) -> bool:
    """Returns True if the component has crossed the escalation threshold."""
    return get_failure_count(component) >= ESCALATION_THRESHOLD


def get_all_failures() -> dict[str, Any]:
    """Returns the full health failure state dict."""
    with _lock:
        return _load_failures()


# ─────────────────────────────────────────────────────────────────────────────
# Self-Improvement escalation
# ─────────────────────────────────────────────────────────────────────────────

_COMPONENT_LABELS = {
    "gemini":       "Gemini LLM API",
    "todoist":      "Todoist Task Integration",
    "crm":          "CRM / iMessage Database",
    "memory":       "Persistent Memory Engine",
    "tts":          "Text-to-Speech Engine",
    "wakeword":     "Wake Word Engine",
    "agent_engine": "Antigravity Agent Engine",
}


def _escalate_to_self_improvement(component: str, entry: dict) -> None:
    """
    Writes a structured issue to ~/.jarvis/issues.json.
    This file is read by SelfImprovementOrchestrator during nightly analysis.
    The issue ID format is: HEALTH_{COMPONENT}_{YYYYMMDD}
    """
    try:
        label = _COMPONENT_LABELS.get(component, component.replace("_", " ").title())
        issue_id = f"HEALTH_{component.upper()}_{datetime.now().strftime('%Y%m%d')}"
        description = (
            f"{label} has failed {entry['count']} consecutive times.\n"
            f"First seen: {entry['first_seen']}\n"
            f"Last error: {entry['last_error']}\n\n"
            f"JARVIS requests analysis and fix proposal for:\n"
            f"COMPONENT: {label}\n"
            f"ERROR: {entry['last_error']}\n"
            f"FREQUENCY: {entry['count']} failures\n\n"
            f"Analyze: API changes, authentication, endpoint availability, configuration.\n"
            f"Provide: Root cause, corrected code, environment variable fix."
        )

        issues = _load_issues()
        issues[issue_id] = {
            "id": issue_id,
            "component": component,
            "description": description,
            "severity": entry["severity"],
            "count": entry["count"],
            "first_seen": entry["first_seen"],
            "last_seen": entry["last_seen"],
            "status": "open",
        }
        _save_issues(issues)
        logger.warning(
            f"[IssueTracker] Escalated issue {issue_id} to Self-Improvement Engine "
            f"({entry['count']} failures, severity={entry['severity']})"
        )
    except Exception as e:
        logger.error(f"[IssueTracker] Failed to escalate issue for {component}: {e}")
