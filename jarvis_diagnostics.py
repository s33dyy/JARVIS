"""
jarvis_diagnostics.py
──────────────────────
Intent detection + spoken report formatter for JARVIS self-diagnostics.

This module does two things:

1. INTENT DETECTION: is_diagnostic_query(text) — regex-based check that
   intercepts questions about JARVIS's own health before the LLM is called.

2. REPORT FORMATTING: get_diagnostic_response() — runs (or retrieves cached)
   health checks, then formats a spoken English report in the JARVIS persona.

No LLM is involved in generating the diagnostic report. Every word is derived
directly from real health check data. This is the core anti-hallucination guarantee.

Usage (in jarvis_listen.py):
    from jarvis_diagnostics import is_diagnostic_query, get_diagnostic_response
    if is_diagnostic_query(question):
        report_text = get_diagnostic_response()
        speak(report_text, block=True)
        return None
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis_health import HealthReport, ComponentStatus


# ─────────────────────────────────────────────────────────────────────────────
# Intent Detection
# ─────────────────────────────────────────────────────────────────────────────

# Patterns that signal the user is asking about JARVIS's own operational state.
# All patterns are case-insensitive. Order doesn't matter — any match triggers.
_HEALTH_PATTERNS = [
    # Direct self-status questions
    r"\b(what('s| is) wrong with you)\b",
    r"\b(what problems (do you have|do you see|are you having))\b",
    r"\b(what('s| is) (broken|offline|failing|not working|down))\b",
    r"\b(any (issues|errors|failures|problems|bugs))\b",

    # System health commands
    r"\b(system (status|health|report|check|diagnostic))\b",
    r"\b(run (diagnostics|self.diagnos|health check))\b",
    r"\b(diagnose yourself|self.diagnos)\b",

    # Are you okay / how are you
    r"\bare you (ok|okay|fine|working|functioning|broken|operational)\b",
    r"\bhow are you (doing|functioning|running|holding up)\b",

    # Status queries
    r"\b(check (yourself|your status|your health|your systems))\b",
    r"\b(give me (a status|a health report|a system report))\b",
    r"\bwhat('s| is) your status\b",
    r"\bwhat('s| is) (online|offline|working|not working)\b",

    # Error/log queries
    r"\b(show me|tell me|report) (your )?(errors|failures|issues|problems)\b",
]

# Patterns that signal the user wants JARVIS to reflect on its own
# learning, failures, and self-improvement — not just immediate health.
_IMPROVEMENT_PATTERNS = [
    # What have you failed at / learned
    r"\b(what have you (failed at|learned|struggled with))\b",
    r"\b(what did you fail (at|on|with))\b",
    r"\b(what (mistakes|errors) did you make)\b",
    r"\b(what.*fail.*today)\b",

    # Review / summary
    r"\b(nightly review|daily review|daily summary|end.of.day report)\b",
    r"\b(give me (a )?(nightly|daily|today.?s|self).?(review|summary|report))\b",
    r"\b(review (your(self)?|today|this week))\b",

    # Self-analysis / self-improvement
    r"\b(analyze yourself|self.analy)\b",
    r"\b(how can you (improve|get better|do better))\b",
    r"\b(what should you improve)\b",
    r"\b(what (are your|are the) weaknesses)\b",
    r"\b(self improvement|improve yourself)\b",

    # Intent / understanding failures
    r"\b(what (commands|intents|things) did you (misunderstand|get wrong))\b",
    r"\b(when did you misunderstand|your misunderstandings)\b",
]

_COMPILED_HEALTH_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _HEALTH_PATTERNS
]
_COMPILED_IMPROVEMENT_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _IMPROVEMENT_PATTERNS
]

# Backward-compat alias
_COMPILED_PATTERNS = _COMPILED_HEALTH_PATTERNS


def is_health_query(text: str) -> bool:
    """
    Returns True if the user's query is asking about JARVIS's own system health.

    Uses regex matching — no LLM call required. Fast enough for the voice hot-path.

    Examples:
        is_health_query("what problems do you have?")  → True
        is_health_query("are you okay, JARVIS?")        → True
        is_health_query("system status report")         → True
        is_health_query("what time is it?")             → False
        is_health_query("what have you failed at today?") → False  (use is_improvement_query)
    """
    if not text:
        return False
    for pattern in _COMPILED_HEALTH_PATTERNS:
        if pattern.search(text):
            return True
    return False


def is_improvement_query(text: str) -> bool:
    """
    Returns True if the user is asking about JARVIS's self-development,
    past failures, or learning — rather than current health status.

    Examples:
        is_improvement_query("what have you failed at today?") → True
        is_improvement_query("nightly review")                 → True
        is_improvement_query("analyze yourself")               → True
        is_improvement_query("are you okay?")                  → False (use is_health_query)
        is_improvement_query("play some music")                → False
    """
    if not text:
        return False
    for pattern in _COMPILED_IMPROVEMENT_PATTERNS:
        if pattern.search(text):
            return True
    return False


def is_diagnostic_query(text: str) -> bool:
    """
    Backward-compatible alias. Returns True if the query matches EITHER
    a health query or an improvement query.

    Prefer using is_health_query() or is_improvement_query() directly
    so the caller can route to the correct handler.
    """
    return is_health_query(text) or is_improvement_query(text)


# ─────────────────────────────────────────────────────────────────────────────
# Report Formatting
# ─────────────────────────────────────────────────────────────────────────────

_SEVERITY_HEADER = {
    "critical": "CRITICAL",
    "high":     "HIGH",
    "medium":   "MEDIUM",
    "low":      "LOW",
}


def format_spoken_report(report: "HealthReport") -> str:
    """
    Converts a HealthReport into a spoken-English JARVIS status response.

    Designed for voice output:
    - No markdown, no ANSI codes, no raw newlines between sentences.
    - Each section is a sentence ending with a period, separated by a single space.
    - Failures are stated factually and briefly.
    - No LLM. Every sentence is derived directly from check results.
    """
    components: list["ComponentStatus"] = report["components"]
    health_score: int = report["health_score"]
    overall: str = report["overall"]

    # Group failures by severity
    grouped: dict[str, list["ComponentStatus"]] = {
        "critical": [],
        "high": [],
        "medium": [],
    }
    operational: list["ComponentStatus"] = []

    for comp in components:
        if comp["ok"]:
            operational.append(comp)
        elif comp["severity"] in grouped:
            grouped[comp["severity"]].append(comp)
        else:
            grouped["medium"].append(comp)

    sentences: list[str] = []
    sentences.append("System diagnostic report.")

    # Critical failures
    if grouped["critical"]:
        for comp in grouped["critical"]:
            sentences.append(
                f"CRITICAL: {comp['label']} is offline. {comp['detail']}"
            )

    # High severity failures
    if grouped["high"]:
        for comp in grouped["high"]:
            sentences.append(
                f"High severity: {comp['label']} is failing. {comp['detail']}"
            )

    # Medium severity failures
    if grouped["medium"]:
        for comp in grouped["medium"]:
            sentences.append(
                f"Degraded: {comp['label']}. {comp['detail']}"
            )

    # Operational (compact — one sentence listing all)
    if operational:
        op_names = ", ".join(c["label"] for c in operational)
        sentences.append(f"Operational: {op_names}.")

    # Overall score
    sentences.append(f"Overall system health: {health_score} percent. Status: {overall}.")

    # Top recommendation
    recommendation = _top_recommendation(report)
    if recommendation:
        sentences.append(recommendation)

    # Cache freshness
    from jarvis_health import get_cache_age_seconds
    age = get_cache_age_seconds()
    if age is not None and age > 5:
        sentences.append(f"Data is {int(age)} seconds old.")
    else:
        sentences.append("Freshly checked.")

    # Join with a single space — the TTS engine handles natural pausing at periods
    return " ".join(sentences)


def format_console_report(report: "HealthReport") -> str:
    """
    Produces a formatted terminal table for print output.
    Color codes are included (ANSI) for readability in the terminal.
    """
    RESET  = "\033[0m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    GREEN  = "\033[92m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"

    lines: list[str] = []
    lines.append(f"\n{BOLD}{'─' * 60}{RESET}")
    lines.append(f"{BOLD}  JARVIS SYSTEM DIAGNOSTIC{RESET}   "
                 f"Score: {_score_color(report['health_score'])}{report['health_score']}%{RESET}   "
                 f"Status: {report['overall'].upper()}")
    lines.append(f"{'─' * 60}")

    for comp in report["components"]:
        status_icon = f"{GREEN}✅{RESET}" if comp["ok"] else _fail_icon(comp["severity"])
        sev_tag = f"{DIM}[{comp['severity']}]{RESET}" if not comp["ok"] else ""
        lines.append(
            f"  {status_icon}  {comp['label']:<28} {sev_tag}"
        )
        if not comp["ok"]:
            lines.append(f"       {DIM}↳ {comp['detail']}{RESET}")

    lines.append(f"{'─' * 60}")
    ts = datetime.fromisoformat(report["timestamp"]).strftime("%H:%M:%S")
    lines.append(f"  {DIM}Checked at {ts}{RESET}")
    lines.append("")

    return "\n".join(lines)


def _score_color(score: int) -> str:
    RESET  = "\033[0m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    GREEN  = "\033[92m"
    if score >= 80:
        return GREEN
    elif score >= 50:
        return YELLOW
    return RED


def _fail_icon(severity: str) -> str:
    RESET  = "\033[0m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    if severity == "critical":
        return f"{RED}🔴{RESET}"
    elif severity == "high":
        return f"{YELLOW}🟠{RESET}"
    return f"{YELLOW}🟡{RESET}"


def _top_recommendation(report: "HealthReport") -> str:
    """Returns the single most important recommendation as a sentence."""
    components = report["components"]

    # Find highest-severity failure
    for sev in ("critical", "high", "medium"):
        for comp in components:
            if not comp["ok"] and comp["severity"] == sev:
                label = comp["label"]
                if sev == "critical":
                    return f"Recommend repairing {label} immediately, sir."
                elif sev == "high":
                    return f"Priority repair needed: {label}."
                else:
                    return f"Note: {label} is degraded and should be reviewed."
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point (called from jarvis_listen.py)
# ─────────────────────────────────────────────────────────────────────────────

def get_diagnostic_response() -> str:
    """
    The single function called from jarvis_listen.py when a diagnostic intent is detected.

    Runs (or retrieves cached) health checks, prints the console table,
    and returns the spoken English report string.

    This never calls the LLM. It is the anti-hallucination guarantee.
    """
    from jarvis_health import run_health_checks
    report = run_health_checks()

    # Always print console table for visibility in the terminal
    print(format_console_report(report), flush=True)

    return format_spoken_report(report)
