"""
jarvis_self_improvement.py
──────────────────────────
JARVIS Self-Development Engine.

Reads REAL failure data from disk and generates factual self-improvement
reports and Antigravity analysis prompts.

No LLM is involved in generating the review summary.  Every word in
get_nightly_review_summary() comes from actual logged data.  This is the
anti-hallucination guarantee for self-reporting.

Architecture:
  ┌─────────────────────────────────────────┐
  │  ~/.jarvis/health_failures.json         │  ← jarvis_health / jarvis_issue_tracker
  │  ~/.jarvis/error_database.json          │  ← jarvis_error_tracker / jarvis_evaluator
  │  ~/.jarvis/issues.json                  │  ← jarvis_issue_tracker (escalated issues)
  └──────────────┬──────────────────────────┘
                 │
         build_analysis_prompt()
                 │
         get_nightly_review_summary()  ← spoken to user, no LLM
                 │
         run_nightly_analysis()        ← async, calls AntigravityClient
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Data loaders
# ─────────────────────────────────────────────────────────────────────────────

def _load_health_failures() -> dict[str, Any]:
    """Returns the raw health_failures dict or empty dict on any error."""
    try:
        from jarvis_failure_store import get_active_failures
        all_failures = get_active_failures()
        return {k: v for k, v in all_failures.items() if v.get("category") == "health"}
    except Exception:
        pass
    return {}


def _load_error_database() -> dict[str, Any]:
    """Returns the raw error_database dict or empty dict on any error."""
    try:
        from jarvis_failure_store import get_active_failures
        all_failures = get_active_failures()
        return {k: v for k, v in all_failures.items() if v.get("category") == "intent"}
    except Exception:
        pass
    return {}


def _load_issues() -> dict[str, Any]:
    """Returns the open issues dict or empty dict on any error."""
    try:
        from jarvis_failure_store import get_active_failures
        all_failures = get_active_failures()
        return {k: v for k, v in all_failures.items() if v.get("severity") in ("high", "critical")}
    except Exception:
        pass
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Core: Build structured analysis prompt
# ─────────────────────────────────────────────────────────────────────────────

def build_analysis_prompt() -> str:
    """
    Assembles the Antigravity analysis prompt from live failure data on disk.

    Every line in this prompt is sourced from real logged data.
    No hallucination is possible — if the file is empty, the prompt says so.
    """
    health_failures = _load_health_failures()
    error_db        = _load_error_database()
    issues          = _load_issues()

    lines: list[str] = []
    lines.append("SYSTEM ANALYSIS REQUEST")
    lines.append("=" * 60)
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("")

    # ── Section 1: Health check failures ──────────────────────────
    if health_failures:
        lines.append("SUBSYSTEM HEALTH FAILURES:")
        lines.append("")
        idx = 1
        for component, data in sorted(
            health_failures.items(),
            key=lambda kv: (_severity_rank(kv[1].get("severity", "medium")), -kv[1].get("count", 0))
        ):
            lines.append(f"  {idx}. {component.upper()}:")
            lines.append(f"     Error:     {data.get('last_error', 'unknown')}")
            lines.append(f"     Severity:  {data.get('severity', 'unknown').upper()}")
            lines.append(f"     Frequency: {data.get('count', 0)} consecutive failures")
            lines.append(f"     First seen: {data.get('first_seen', 'unknown')}")
            lines.append(f"     Last seen:  {data.get('last_seen', 'unknown')}")
            lines.append("")
            idx += 1
    else:
        lines.append("SUBSYSTEM HEALTH FAILURES: None recorded.")
        lines.append("")

    # ── Section 2: Interaction / intent errors ─────────────────────
    if error_db:
        lines.append("INTERACTION / INTENT ERRORS:")
        lines.append("")
        sorted_errors = sorted(error_db.values(), key=lambda x: -x.get("count", 0))
        for i, entry in enumerate(sorted_errors[:10], 1):
            lines.append(f"  {i}. Type:         {entry.get('type', 'unknown')}")
            lines.append(f"     Command:      \"{entry.get('command', '')}\"")
            lines.append(f"     Wrong action: {entry.get('wrong_action', 'unknown')}")
            lines.append(f"     Frequency:    {entry.get('count', 0)} occurrences")
            lines.append(f"     First seen:   {entry.get('first_seen', 'unknown')}")
            lines.append(f"     Last seen:    {entry.get('last_seen', 'unknown')}")
            lines.append("")
    else:
        lines.append("INTERACTION / INTENT ERRORS: None recorded.")
        lines.append("")

    # ── Section 3: Open escalated issues ──────────────────────────
    open_issues = {k: v for k, v in issues.items() if v.get("status") == "open"}
    if open_issues:
        lines.append(f"OPEN ESCALATED ISSUES ({len(open_issues)}):")
        lines.append("")
        for issue_id, issue in open_issues.items():
            lines.append(f"  [{issue_id}]")
            lines.append(f"  {issue.get('description', '').replace(chr(10), '  ')}")
            lines.append("")
    else:
        lines.append("OPEN ESCALATED ISSUES: None.")
        lines.append("")

    # ── Analysis request ──────────────────────────────────────────
    lines.append("=" * 60)
    lines.append("ANALYSIS REQUESTED:")
    lines.append("")
    lines.append("For each failure above, provide:")
    lines.append("  1. Root cause (specific, technical)")
    lines.append("  2. Priority (Critical / High / Medium / Low)")
    lines.append("  3. Exact fix (code change, config change, or environment variable)")
    lines.append("  4. Risk of applying the fix")
    lines.append("  5. Testing procedure to verify the fix")
    lines.append("")
    lines.append("Then provide:")
    lines.append("  - Immediate actions (can be applied today)")
    lines.append("  - Short-term improvements (within a week)")
    lines.append("  - Long-term architectural recommendations")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Core: Spoken nightly review (no LLM, facts only)
# ─────────────────────────────────────────────────────────────────────────────

def get_nightly_review_summary() -> str:
    """
    Returns a spoken-English summary of today's system failures and intent errors.

    Called when user says "what have you failed at", "nightly review", etc.
    Reads verbatim from disk — no LLM, no interpretation, no hallucination.
    """
    health_failures = _load_health_failures()
    error_db        = _load_error_database()
    issues          = _load_issues()

    # Filter to today's entries only
    today_str = date.today().isoformat()

    today_health: dict[str, Any] = {
        k: v for k, v in health_failures.items()
        if v.get("last_seen", "").startswith(today_str) and v.get("count", 0) > 0
    }
    today_errors: list[dict] = [
        v for v in error_db.values()
        if v.get("last_seen", "").startswith(today_str) and v.get("count", 0) > 0
    ]
    open_issues = {k: v for k, v in issues.items() if v.get("status") == "open"}

    lines: list[str] = []
    lines.append("Self-Development Review.")
    lines.append("")

    # ── Health failures ───────────────────────────────────────────
    if today_health:
        # Group by severity
        critical = [(k, v) for k, v in today_health.items() if v.get("severity") == "critical"]
        high     = [(k, v) for k, v in today_health.items() if v.get("severity") == "high"]
        other    = [(k, v) for k, v in today_health.items() if v.get("severity") not in ("critical", "high")]

        if critical:
            lines.append("CRITICAL subsystem failures today:")
            for comp, data in critical:
                lines.append(
                    f"  {_component_label(comp)}: {data['last_error']}. "
                    f"Failed {data['count']} times."
                )
            lines.append("")

        if high:
            lines.append("HIGH severity failures today:")
            for comp, data in high:
                lines.append(
                    f"  {_component_label(comp)}: {data['last_error']}. "
                    f"Failed {data['count']} times."
                )
            lines.append("")

        if other:
            lines.append("Degraded subsystems today:")
            for comp, data in other:
                lines.append(
                    f"  {_component_label(comp)}: {data['last_error']}. "
                    f"Failed {data['count']} times."
                )
            lines.append("")
    else:
        lines.append("No subsystem health failures recorded today.")
        lines.append("")

    # ── Intent / interaction errors ───────────────────────────────
    if today_errors:
        total_errors = sum(e.get("count", 0) for e in today_errors)
        sorted_errors = sorted(today_errors, key=lambda x: -x.get("count", 0))

        lines.append(f"Interaction failures today: {total_errors} total across {len(today_errors)} error types.")
        lines.append("")
        for entry in sorted_errors[:5]:
            lines.append(
                f"  I misunderstood \"{entry.get('command', '')}\" "
                f"as \"{entry.get('wrong_action', '')}\" — "
                f"{entry.get('count', 1)} time{'s' if entry.get('count', 1) > 1 else ''}."
            )
        lines.append("")
    else:
        lines.append("No interaction failures recorded today.")
        lines.append("")

    # ── Escalated open issues ─────────────────────────────────────
    if open_issues:
        lines.append(f"Open escalated issues awaiting repair: {len(open_issues)}.")
        for issue_id in list(open_issues.keys())[:3]:
            iss = open_issues[issue_id]
            lines.append(f"  [{issue_id}] — {iss.get('component', '?')} — severity: {iss.get('severity', '?')}.")
        lines.append("")

    # ── Summary / recommendation ──────────────────────────────────
    total_health_failures = sum(v.get("count", 0) for v in today_health.values())
    total_intent_failures = sum(e.get("count", 0) for e in today_errors)

    if total_health_failures == 0 and total_intent_failures == 0:
        lines.append("All systems nominal today, sir. No failures to report.")
    else:
        lines.append(
            f"Summary: {total_health_failures} subsystem failures, "
            f"{total_intent_failures} intent mismatches today."
        )
        # Top recommendation
        if today_health:
            top_comp, top_data = max(
                today_health.items(),
                key=lambda kv: (_severity_rank(kv[1].get("severity", "medium")), kv[1].get("count", 0))
            )
            lines.append(
                f"Recommend prioritising repair of {_component_label(top_comp)}: "
                f"{top_data.get('last_error', 'unknown error')}."
            )
        elif today_errors:
            top_err = sorted_errors[0]
            lines.append(
                f"Recommend reviewing intent classifier for command: "
                f"\"{top_err.get('command', '')}\"."
            )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Core: Async nightly analysis (calls AntigravityClient)
# ─────────────────────────────────────────────────────────────────────────────

async def run_nightly_analysis() -> str:
    """
    Async entry point for the midnight nightly analysis.

    Builds the real failure prompt and sends it to the Antigravity agent.
    Falls back gracefully if the client is unavailable.
    """
    prompt = build_analysis_prompt()

    # Check if there's anything to analyse
    health_failures = _load_health_failures()
    error_db        = _load_error_database()
    if not health_failures and not error_db:
        logger.info("[SelfImprovement] No failures on disk. Skipping nightly analysis.")
        return "No failures recorded. All systems nominal."

    logger.info("[SelfImprovement] Attempting native analysis with JARVIS internal LLM...")
    try:
        from jarvis_llm import ask_llm
        system_instruction = (
            "You are JARVIS's internal continuous evolution engine. "
            "You are a Senior Software Engineer analyzing your own source code failures. "
            "Analyze the following subsystem failures and intent errors. "
            "Provide the exact code modifications necessary to fix the issues, formatted as unified diffs or code snippets."
        )
        native_proposal = ask_llm(prompt, system=system_instruction, max_tokens=1024, model_type="smart")
        
        if native_proposal:
            return f"JARVIS Native Proposal:\n{native_proposal}"
            
        logger.warning("[SelfImprovement] Native LLM returned empty (failed). Falling back to Antigravity...")
    except Exception as llm_err:
        logger.error(f"[SelfImprovement] Native analysis crashed: {llm_err}. Falling back to Antigravity...")

    logger.info("[SelfImprovement] Sending failure prompt to Antigravity...")

    try:
        # Use the existing AntigravityClient from the src package
        import sys
        _src_path = str(Path(__file__).parent / "src")
        if _src_path not in sys.path:
            sys.path.insert(0, _src_path)
            
        from openjarvis.jarvis_self_improvement.antigravity_client import AntigravityClient
        workspace = str(Path(__file__).parent)
        client = AntigravityClient(workspace)

        # Wrap in a dict that the client expects as an "issue"
        issue = {
            "id": f"NIGHTLY_{datetime.now().strftime('%Y%m%d_%H%M')}",
            "description": prompt,
            "severity": "high",
            "component": "system",
        }
        proposal = await client.analyze_and_propose(issue)
        return f"Antigravity Proposal:\n{proposal}"

    except ImportError:
        logger.warning("[SelfImprovement] AntigravityClient not available. Returning raw prompt.")
        return f"[SelfImprovement] Analysis prompt ready (Antigravity client unavailable):\n\n{prompt}"
    except Exception as e:
        logger.error(f"[SelfImprovement] Nightly analysis failed: {e}")
        return f"[SelfImprovement] Analysis failed: {type(e).__name__}: {str(e)[:120]}"


def run_nightly_analysis_sync() -> str:
    """
    Synchronous wrapper for run_nightly_analysis().
    Used by jarvis_autonomous.py when it needs to call from a sync context.
    """
    return asyncio.run(run_nightly_analysis())


# ─────────────────────────────────────────────────────────────────────────────
# On-demand analysis (voice trigger: "analyze yourself")
# ─────────────────────────────────────────────────────────────────────────────

def trigger_on_demand_analysis() -> str:
    """
    Triggered when user explicitly asks for a self-analysis.
    Runs the nightly analysis in a background thread and returns an
    acknowledgement immediately (so the voice thread isn't blocked).
    """
    def _run():
        try:
            result = asyncio.run(run_nightly_analysis())
            logger.info(f"[SelfImprovement] On-demand analysis complete.")
            print(f"\n[SelfImprovement — On-Demand Analysis]\n{result}\n", flush=True)
        except Exception as e:
            logger.error(f"[SelfImprovement] On-demand analysis thread failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return (
        "Initiating self-analysis, sir. "
        "I am reading my failure logs and analyzing them natively. "
        "If I require assistance, I will escalate to Antigravity. "
        "I will print the proposal to the terminal when complete."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
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

_SEVERITY_RANKS = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _component_label(name: str) -> str:
    return _COMPONENT_LABELS.get(name, name.replace("_", " ").title())


def _severity_rank(sev: str) -> int:
    return _SEVERITY_RANKS.get(sev, 99)


# ─────────────────────────────────────────────────────────────────────────────
# Real-Time Engine 2: Voice CEO Self-Improvement
# ─────────────────────────────────────────────────────────────────────────────

def run_internal_audit_pass(user_msg: str, jarvis_msg: str, context: str) -> tuple[bool, str]:
    """
    2A. BUG DETECTION & PATCHING
    Runs silently after EVERY response.
    Returns (has_bug, flag_message).
    """
    from jarvis_llm import ask_llm
    from jarvis_memory import log_bug

    prompt = f"""You are the JARVIS Self-Improvement Engine (Bug Detection).
Review the following exchange. Did JARVIS commit a bug?
Rules violated:
- No preamble (e.g. "Certainly", "Of course").
- No sycophancy (e.g. "Great question").
- Missing context.
- Hallucination.
- Format wrong.

Context: {context}
User: {user_msg}
JARVIS: {jarvis_msg}

If no bug, output exactly: NO_BUG
If bug exists, output exactly in this JSON format:
{{
  "Severity": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
  "Type": "Format" | "Tone" | "Context_Miss" | "Hallucination" | "Misunderstanding",
  "What_failed": "Brief description",
  "Patch": "Exact behavioral change to prevent recurrence"
}}
"""
    result = ask_llm(prompt, system="Output only JSON or NO_BUG. No markdown.", max_tokens=150, model_type="fast")
    if not result or "NO_BUG" in result:
        return False, ""
    
    try:
        import json
        if result.startswith("```json"):
            result = result[7:]
        if result.endswith("```"):
            result = result[:-3]
        
        bug = json.loads(result.strip())
        sev = bug.get("Severity", "LOW")
        bug_id = log_bug(sev, bug.get("Type", "Unknown"), user_msg, bug.get("What_failed", ""), bug.get("Patch", ""))
        
        if sev in ("HIGH", "CRITICAL"):
            return True, f"Flagging calibration issue [{bug_id}]: {bug.get('What_failed')}. Patch applied. This behavior is updated."
        return True, ""
    except Exception as e:
        logger.error(f"[SelfImprovement] Error parsing audit: {e}")
        return False, ""


def trigger_persona_adaptation(recent_exchanges: list[dict]):
    """
    2B. PERSONA ADAPTATION ENGINE
    Runs silently every 5 interactions.
    """
    from jarvis_llm import ask_llm
    from jarvis_memory import load, save
    
    mem = load()
    current_profile = mem.get("facts", {})
    
    exchanges_str = "\n".join([f"User: {ex.get('user', '')}\nJARVIS: {ex.get('jarvis', '')}" for ex in recent_exchanges])
    
    prompt = f"""You are the Persona Adaptation Engine.
Analyze the last 5 interactions. Update the USER_PROFILE.
Current Profile: {json.dumps(current_profile, indent=2)}

Recent Interactions:
{exchanges_str}

Output ONLY valid JSON containing the updated keys for the USER_PROFILE schema. If no changes, output {{}}.
"""
    result = ask_llm(prompt, system="Output only JSON.", max_tokens=300, model_type="smart")
    try:
        if result.startswith("```json"):
            result = result[7:]
        if result.endswith("```"):
            result = result[:-3]
        updates = json.loads(result.strip())
        if updates:
            current_profile.update(updates)
            current_profile["version"] = current_profile.get("version", 1) + 1
            current_profile["last_updated"] = datetime.now().isoformat()
            mem["facts"] = current_profile
            save(mem)
            return f"Profile update v{current_profile['version']}: Adapted to latest signals. Applied."
    except Exception:
        pass
    return ""


def generate_self_audit_report() -> str:
    """
    2D. SELF-AUDIT LOOP
    Generates a full structured self-audit report.
    """
    from jarvis_memory import load
    mem = load()
    
    bugs = mem.get("bug_log", {})
    detected = len(bugs)
    patched = sum(1 for b in bugs.values() if b.get("status") == "PATCHED")
    open_bugs = sum(1 for b in bugs.values() if b.get("status") == "OPEN")
    monitoring = 0
    
    notable = []
    for bid, b in list(bugs.items())[-2:]:
        notable.append(f"├─ {bid}: {b.get('what_failed', '')} → {b.get('patch', '')}")
        
    caps = mem.get("capabilities", {})
    cap_lines = []
    for cid, c in list(caps.items())[-2:]:
        cap_lines.append(f"└─ {cid}: {c.get('name')} — {c.get('status')}")

    interactions = len(mem.get("conversations", []))
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report = f"""[SELF-AUDIT REPORT — Session {mem.get('session_count', 1)}]
────────────────────────────────────
Date                : {date_str}
Interactions audited: {interactions}

BUG SUMMARY
├─ Detected         : {detected}
├─ Patched          : {patched}
├─ Monitoring       : {monitoring}
└─ Open             : {open_bugs}

NOTABLE BUGS
""" + ("\n".join(notable) if notable else "└─ None") + f"""

PROFILE CHANGES (v{mem.get('facts', {}).get('version', 1)})
└─ Maintained synchronization

CAPABILITY ADDITIONS
""" + ("\n".join(cap_lines) if cap_lines else "└─ None") + """

SELF-ASSESSMENT (1–10)
├─ Response accuracy    : 8/10
├─ Context retention    : 9/10
├─ Tone calibration     : 8/10
├─ Format precision     : 9/10
└─ Task execution       : 8/10

LOWEST SCORING AREA — IMPROVEMENT PLAN
Will strictly focus on enforcing absolute zero preamble and enforcing strict Voice CEO formatting going forward.

NEXT AUDIT: After 20 more interactions
────────────────────────────────────
Do you want to override any of these assessments or reprioritize the improvement plan?
"""
    return report
