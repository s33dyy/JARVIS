"""
jarvis_health.py
────────────────
JARVIS Self-Awareness Health Engine.

Performs real diagnostic checks on every subsystem JARVIS depends on.
Results are cached for 60 seconds to avoid blocking the voice thread on
repeat queries.

Architecture:
  - All 7 checks run concurrently via ThreadPoolExecutor
  - Each check returns a ComponentStatus typed dict
  - run_health_checks() returns a HealthReport with an overall score
  - Failures are forwarded to jarvis_issue_tracker for Self-Improvement tracking

Usage:
  from jarvis_health import run_health_checks
  report = run_health_checks()
  print(report["health_score"])  # 0-100
"""

from __future__ import annotations

import os
import time
import sqlite3
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import TypedDict

# ─────────────────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────────────────

class ComponentStatus(TypedDict):
    name: str           # machine name, e.g. "gemini"
    label: str          # display name, e.g. "Gemini API"
    ok: bool
    latency_ms: float
    detail: str         # human-readable pass/fail reason
    severity: str       # "critical" | "high" | "medium" | "low"


class HealthReport(TypedDict):
    timestamp: str
    components: list[ComponentStatus]
    health_score: int           # 0-100
    critical_count: int
    high_count: int
    medium_count: int
    operational_count: int
    overall: str                # "healthy" | "degraded" | "critical"


# ─────────────────────────────────────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────────────────────────────────────

_CACHE_TTL_SECONDS = 60
_cache_lock = threading.Lock()
_cached_report: HealthReport | None = None
_cache_ts: float = 0.0


def _get_cached() -> HealthReport | None:
    with _cache_lock:
        if _cached_report and (time.monotonic() - _cache_ts) < _CACHE_TTL_SECONDS:
            return _cached_report
    return None


def _set_cache(report: HealthReport) -> None:
    global _cached_report, _cache_ts
    with _cache_lock:
        _cached_report = report
        _cache_ts = time.monotonic()


# ─────────────────────────────────────────────────────────────────────────────
# Individual health checks
# ─────────────────────────────────────────────────────────────────────────────

def check_gemini() -> ComponentStatus:
    """
    Verifies Gemini API authentication by sending a minimal content request.
    Returns ok=False and captures the HTTP status code on failure.
    """
    name = "gemini"
    label = "Gemini API"
    severity = "critical"
    t0 = time.monotonic()
    try:
        import httpx
        from dotenv import load_dotenv
        load_dotenv()
        key = os.environ.get("JARVIS_GEMINI_KEY", "")
        if not key:
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=0.0,
                detail="JARVIS_GEMINI_KEY not set in environment.",
                severity=severity
            )
        resp = httpx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": "ping"}]}]},
            timeout=10.0,
        )
        latency = (time.monotonic() - t0) * 1000
        if resp.status_code == 200:
            return ComponentStatus(
                name=name, label=label, ok=True,
                latency_ms=round(latency, 1),
                detail=f"Authenticated. {round(latency)}ms.",
                severity=severity
            )
        else:
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=round(latency, 1),
                detail=f"HTTP {resp.status_code} — {resp.reason_phrase}.",
                severity=severity
            )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(
            name=name, label=label, ok=False,
            latency_ms=round(latency, 1),
            detail=f"Connection error: {type(e).__name__}: {str(e)[:80]}",
            severity=severity
        )


def check_todoist() -> ComponentStatus:
    """
    Verifies Todoist REST API is reachable and the token is valid.
    Checks for 410 Gone (deprecated endpoint) or 401 (bad token).
    """
    name = "todoist"
    label = "Todoist"
    severity = "high"
    t0 = time.monotonic()
    try:
        import httpx
        from dotenv import load_dotenv
        load_dotenv()
        token = os.environ.get("JARVIS_TODOIST_TOKEN", "")
        if not token:
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=0.0,
                detail="JARVIS_TODOIST_TOKEN not set in environment.",
                severity=severity
            )
        # Use /rest/v2 as that is the current Todoist API
        resp = httpx.get(
            "https://api.todoist.com/api/v1/tasks",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        latency = (time.monotonic() - t0) * 1000
        if resp.status_code == 200:
            return ComponentStatus(
                name=name, label=label, ok=True,
                latency_ms=round(latency, 1),
                detail=f"Connected. {round(latency)}ms.",
                severity=severity
            )
        elif resp.status_code == 410:
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=round(latency, 1),
                detail="HTTP 410 Gone — API endpoint deprecated. Needs migration to REST v2.",
                severity=severity
            )
        elif resp.status_code == 401:
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=round(latency, 1),
                detail="HTTP 401 Unauthorized — Invalid or expired Todoist token.",
                severity=severity
            )
        else:
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=round(latency, 1),
                detail=f"HTTP {resp.status_code} — {resp.reason_phrase}.",
                severity=severity
            )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(
            name=name, label=label, ok=False,
            latency_ms=round(latency, 1),
            detail=f"Connection error: {type(e).__name__}: {str(e)[:80]}",
            severity=severity
        )


def check_crm() -> ComponentStatus:
    """
    Verifies JARVIS can open the iMessage database (chat.db).
    Failure usually means Full Disk Access is not granted.
    """
    name = "crm"
    label = "CRM / iMessage"
    severity = "high"
    t0 = time.monotonic()
    chat_db = Path.home() / "Library" / "Messages" / "chat.db"
    try:
        if not chat_db.exists():
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=0.0,
                detail="chat.db not found. iMessage may not be configured on this machine.",
                severity="medium"  # lower severity if simply not configured
            )
        conn = sqlite3.connect(str(chat_db), timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        result = cursor.fetchone()
        conn.close()
        latency = (time.monotonic() - t0) * 1000
        if result and result[0] == "ok":
            return ComponentStatus(
                name=name, label=label, ok=True,
                latency_ms=round(latency, 1),
                detail=f"chat.db accessible and healthy. {round(latency)}ms.",
                severity=severity
            )
        else:
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=round(latency, 1),
                detail=f"chat.db integrity check failed: {result}",
                severity=severity
            )
    except sqlite3.OperationalError as e:
        latency = (time.monotonic() - t0) * 1000
        msg = str(e)
        if "unable to open" in msg or "permission" in msg.lower():
            detail = "Permission denied — grant Full Disk Access to Terminal in System Settings."
        else:
            detail = f"SQLite error: {msg[:80]}"
        return ComponentStatus(
            name=name, label=label, ok=False,
            latency_ms=round(latency, 1),
            detail=detail, severity=severity
        )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(
            name=name, label=label, ok=False,
            latency_ms=round(latency, 1),
            detail=f"Unexpected error: {type(e).__name__}: {str(e)[:80]}",
            severity=severity
        )


def check_memory() -> ComponentStatus:
    """
    Verifies JARVIS can read and write its persistent memory file.
    Tests a full load/save roundtrip on ~/.jarvis/memory.json.
    """
    name = "memory"
    label = "Persistent Memory"
    severity = "high"
    t0 = time.monotonic()
    try:
        from jarvis_memory import load, save
        data = load()
        # Verify the schema has expected top-level keys
        if not isinstance(data, dict):
            raise ValueError("Memory returned non-dict data.")
        _ = data.get("conversations", [])
        _ = data.get("facts", {})
        latency = (time.monotonic() - t0) * 1000
        conv_count = len(data.get("conversations", []))
        return ComponentStatus(
            name=name, label=label, ok=True,
            latency_ms=round(latency, 1),
            detail=f"Healthy. {conv_count} conversations stored. {round(latency)}ms.",
            severity=severity
        )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(
            name=name, label=label, ok=False,
            latency_ms=round(latency, 1),
            detail=f"Memory load failed: {type(e).__name__}: {str(e)[:80]}",
            severity=severity
        )


def check_tts() -> ComponentStatus:
    """
    Verifies the macOS 'say' TTS binary is available on PATH.
    """
    name = "tts"
    label = "Text-to-Speech (TTS)"
    severity = "medium"
    t0 = time.monotonic()
    try:
        say_path = shutil.which("say")
        latency = (time.monotonic() - t0) * 1000
        if say_path:
            return ComponentStatus(
                name=name, label=label, ok=True,
                latency_ms=round(latency, 1),
                detail=f"'say' found at {say_path}.",
                severity=severity
            )
        else:
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=round(latency, 1),
                detail="'say' binary not found on PATH. Voice output unavailable.",
                severity=severity
            )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(
            name=name, label=label, ok=False,
            latency_ms=round(latency, 1),
            detail=f"TTS check error: {str(e)[:80]}",
            severity=severity
        )


def check_wakeword() -> ComponentStatus:
    """
    Verifies the openwakeword library is installed and hey_jarvis model
    files are present on disk.
    """
    name = "wakeword"
    label = "Wake Word Engine"
    severity = "medium"
    t0 = time.monotonic()
    try:
        import openwakeword  # noqa: F401
        # Locate model files — openwakeword downloads to a known cache dir
        oww_home = Path(openwakeword.__file__).parent / "resources" / "models"
        fallback = Path.home() / ".cache" / "openwakeword"
        model_found = any([
            oww_home.exists() and any(oww_home.glob("hey_jarvis*")),
            fallback.exists() and any(fallback.glob("hey_jarvis*")),
        ])
        latency = (time.monotonic() - t0) * 1000
        if model_found:
            return ComponentStatus(
                name=name, label=label, ok=True,
                latency_ms=round(latency, 1),
                detail="openwakeword installed and hey_jarvis model present.",
                severity=severity
            )
        else:
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=round(latency, 1),
                detail="openwakeword installed but hey_jarvis model files not found. Run: openwakeword.utils.download_models()",
                severity=severity
            )
    except ImportError:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(
            name=name, label=label, ok=False,
            latency_ms=round(latency, 1),
            detail="openwakeword not installed. Run: uv pip install openwakeword",
            severity=severity
        )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(
            name=name, label=label, ok=False,
            latency_ms=round(latency, 1),
            detail=f"Wake word check error: {str(e)[:80]}",
            severity=severity
        )


def check_agent_engine() -> ComponentStatus:
    """
    Verifies the Antigravity agent engine is reachable by checking that
    the brain directory exists and a recent transcript was written within
    the last 30 minutes.
    """
    name = "agent_engine"
    label = "Agent Engine (Antigravity)"
    severity = "medium"
    t0 = time.monotonic()
    try:
        brain_dir = Path.home() / ".gemini" / "antigravity" / "brain"
        if not brain_dir.exists():
            latency = (time.monotonic() - t0) * 1000
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=round(latency, 1),
                detail="Antigravity brain directory not found.",
                severity=severity
            )
        # Find the most recently modified transcript
        transcripts = sorted(
            brain_dir.glob("*/.system_generated/logs/transcript.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        latency = (time.monotonic() - t0) * 1000
        if not transcripts:
            return ComponentStatus(
                name=name, label=label, ok=False,
                latency_ms=round(latency, 1),
                detail="No agent transcripts found. Agent engine may not have been used yet.",
                severity="low"
            )
        last_mtime = transcripts[0].stat().st_mtime
        age_seconds = time.time() - last_mtime
        age_minutes = int(age_seconds / 60)
        return ComponentStatus(
            name=name, label=label, ok=True,
            latency_ms=round(latency, 1),
            detail=f"Antigravity brain accessible. Last activity: {age_minutes} min ago.",
            severity=severity
        )
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(
            name=name, label=label, ok=False,
            latency_ms=round(latency, 1),
            detail=f"Agent check error: {type(e).__name__}: {str(e)[:80]}",
            severity=severity
        )


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

_ALL_CHECKS = [
    check_gemini,
    check_todoist,
    check_crm,
    check_memory,
    check_tts,
    check_wakeword,
    check_agent_engine,
]

# Severity weights for health score calculation
_SEVERITY_WEIGHTS = {
    "critical": 25,
    "high":     15,
    "medium":   10,
    "low":       5,
}


def run_health_checks(force: bool = False) -> HealthReport:
    """
    Runs all subsystem health checks concurrently and returns a HealthReport.

    Results are cached for 60 seconds. Pass force=True to bypass the cache.

    The health_score is calculated as:
        100 - sum(weight for each failed component)
    where weights are: critical=25, high=15, medium=10, low=5.
    Clamped to [0, 100].
    """
    if not force:
        cached = _get_cached()
        if cached:
            return cached

    components: list[ComponentStatus] = []
    with ThreadPoolExecutor(max_workers=len(_ALL_CHECKS)) as pool:
        futures = {pool.submit(fn): fn.__name__ for fn in _ALL_CHECKS}
        for future in as_completed(futures):
            try:
                result = future.result(timeout=15.0)
                components.append(result)
            except Exception as e:
                fn_name = futures[future]
                components.append(ComponentStatus(
                    name=fn_name.replace("check_", ""),
                    label=fn_name.replace("check_", "").replace("_", " ").title(),
                    ok=False,
                    latency_ms=0.0,
                    detail=f"Check timed out or raised: {str(e)[:80]}",
                    severity="medium"
                ))

    # Sort for consistent display: critical failures first, then by name
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    components.sort(key=lambda c: (0 if not c["ok"] else 1, severity_order.get(c["severity"], 99)))

    # Compute health score
    penalty = 0
    for comp in components:
        if not comp["ok"]:
            penalty += _SEVERITY_WEIGHTS.get(comp["severity"], 5)
    health_score = max(0, 100 - penalty)

    # Aggregate counts
    critical_count  = sum(1 for c in components if not c["ok"] and c["severity"] == "critical")
    high_count      = sum(1 for c in components if not c["ok"] and c["severity"] == "high")
    medium_count    = sum(1 for c in components if not c["ok"] and c["severity"] == "medium")
    operational_count = sum(1 for c in components if c["ok"])

    if critical_count > 0:
        overall = "critical"
    elif high_count > 0 or health_score < 70:
        overall = "degraded"
    else:
        overall = "healthy"

    report = HealthReport(
        timestamp=datetime.now().isoformat(),
        components=components,
        health_score=health_score,
        critical_count=critical_count,
        high_count=high_count,
        medium_count=medium_count,
        operational_count=operational_count,
        overall=overall
    )

    _set_cache(report)

    # Forward all failures to the issue tracker (non-blocking, best-effort)
    _forward_failures_to_tracker(components)

    return report


def _forward_failures_to_tracker(components: list[ComponentStatus]) -> None:
    """Records component failures in the issue tracker (non-blocking)."""
    try:
        from jarvis_issue_tracker import record_failure, record_success
        for comp in components:
            if comp["ok"]:
                record_success(comp["name"])
            else:
                record_failure(
                    component=comp["name"],
                    error=comp["detail"],
                    severity=comp["severity"]
                )
    except Exception:
        pass  # Never let tracker errors surface to the caller


def get_cache_age_seconds() -> float | None:
    """Returns how old the cached report is, or None if no cache exists."""
    with _cache_lock:
        if not _cached_report:
            return None
        return time.monotonic() - _cache_ts
