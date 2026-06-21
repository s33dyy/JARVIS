import time
import json
import httpx
import os
import threading
import subprocess
from datetime import datetime

from jarvis_context import get_raw, build_context
from jarvis_patterns import update_patterns, load_memory, save_memory
import jarvis_obsidian
import jarvis_google

def speak(text: str):
    import jarvis_speak
    jarvis_speak.speak(text)


# ── 1. INGEST ─────────────────────────────────────────────
def ingest_context() -> dict:
    """Gathers messy context: emails, calendar, existing tasks."""
    print("[Agentic OS] 1. INGEST: Gathering context...")
    # Force context rebuild to get fresh emails/calendar
    build_context(force=True)
    raw = get_raw()
    
    # Removed Obsidian task fetching per user request
        
    return {
        "raw_context": raw,
        "todoist_tasks": raw.get("todoist_tasks", "")
    }

# ── 2. DECIDE ─────────────────────────────────────────────
def decide_actions(context: dict, override_instruction: str = "") -> list[dict]:
    """Generate execution plan from context."""
    print("[Agentic OS] 2. DECIDE: Reasoning over workflow...")
    
    raw = context.get("raw_context", {})
    gmail = raw.get("gmail", [])
    git = raw.get("git", [])
    crm = raw.get("obsidian_crm", [])
    projects = raw.get("obsidian_projects", [])
    
    if not override_instruction:
        now = datetime.now()
        if not (9 <= now.hour < 17):
            print("[Agentic OS] Outside working hours (9-5). Skipping heavy planning.")
            return []
        
        if not gmail and not git:
            print("[Agentic OS] No new emails or git activity. Skipping LLM decision.")
            return []
        
    # -- Inject Behavioral Profile & Stats --
    try:
        from jarvis_memory import load, update_behavioral_profile
        import jarvis_todoist
        # Update behavior stats
        overdue_tasks = jarvis_todoist.get_tasks(filter_query="overdue")
        today_tasks = jarvis_todoist.get_tasks(filter_query="today")
        overdue_count = len(overdue_tasks)
        today_count = len(today_tasks)
        
        # Estimate "completed" vaguely for the profile update
        update_behavioral_profile(today_count, overdue_count)
        
        mem = load()
        # Read behavioral profile & CRM
        profile = mem.get("behavioral_profile", {})
        crm_data = mem.get("crm", [])
        
        tone_instruction = ""
        if profile:
            todo_score = profile.get("todoist_completion_rate", 1.0)
            if todo_score < 0.5:
                tone_instruction = "The user is procrastinating (Todoist completion < 50%). Be extremely strict, pushy, and use tough-love coaching."
            elif todo_score > 0.8:
                tone_instruction = "The user is highly productive. Mirror their efficiency. Be encouraging, concise, and supportive."

        behavior = mem["facts"].get("behavioral_profile", {})
        style = behavior.get("coaching_style", "Supportive")
        tone = behavior.get("tone", "Formal and concise.")
    except Exception as e:
        print(f"[Agentic OS] Error loading behavior profile: {e}")
        style = "Supportive"
        tone = "Formal and concise."
        tone_instruction = ""
        crm_data = []
        
    use_case = os.environ.get("JARVIS_USE_CASE", "Developer")
    
    use_case_guidance = ""
    if use_case == "Developer":
        use_case_guidance = "The user is a software developer. Focus on code reviews, repo status, task breakdowns, and technical progress."
    elif use_case == "Creator":
        use_case_guidance = "The user is a writer/creative content creator. Focus on writing sprints, draft progress, publishing schedules, and obsidian notes."
    elif use_case == "Manager":
        use_case_guidance = "The user is a manager/marketer. Focus on meeting schedules, communications, planning roadmaps, CRM updates, and strategic tasks."
    elif use_case == "Personal":
        use_case_guidance = "The user is using JARVIS for personal life. Focus on everyday habits, hydration, calendar events, personal chores, and family syncs."

    # Build context dynamically based on use case
    context_lines = [f"Unread Emails: {gmail}"]
    if use_case == "Developer" and git:
        context_lines.append(f"Recent Git Activity: {git[:2]}")
    context_lines.append(f"Current CRM Summaries: {crm}")
    if use_case != "Personal" and projects:
        context_lines.append(f"Current Project Statuses: {projects}")
        
    try:
        from jarvis_projects import get_active_projects_context
        proj_ctx = get_active_projects_context()
        if proj_ctx:
            context_lines.append(proj_ctx)
    except ImportError:
        pass
        
    context_lines.append(f"Existing Tasks in Todoist: {context.get('todoist_tasks', '')[:300]}")
    context_str = "\n".join(context_lines)

    prompt = f"""
You are JARVIS, an advanced AI Operating System and personalized ADHD coach.
Your job is to track projects, manage tasks, and propose actions based on the user's messy context.
{use_case_guidance}

JARVIS plans, the user executes. Do not execute actions directly.

CRITICAL: As you interact, you must 'become like your owner'. Adopt their pacing, anticipate their needs, and mirror their communication style over time.
{tone_instruction}

Auto-CRM Data available: {json.dumps(crm_data[-5:])}

Current Coaching Persona: {style}
Current Tone: {tone}
With time, you are becoming a reflection of the user. Use this persona to provide constructive positive or negative feedback when analyzing their workload.
If they have too many overdue tasks, be firm and strict. If they are on top of things, be encouraging.

The user has ADHD. You MUST break tasks down into micro-chunks (15-20 min max). 
If a task does not require the user's explicit expertise, prepend `[DELEGATE]` to the task name.

Context:
{context_str}

Available Actions:
1. {{"action": "propose_task", "params": {{"task": "..."}}}}
2. {{"action": "coach_user", "params": {{"feedback": "..."}}}}

IMPORTANT RULES FOR TASK CREATION:
1. NEVER create generic junk tasks like "Review unread emails" or "Check uncommitted changes in OpenJarvis".
2. Only `propose_task` if there is a HIGHLY URGENT, EXPLICIT action required (e.g. "Fix production crash", "Reply to CEO by 5pm").
3. DO NOT create tasks just because there are unread emails or git changes. Ignore them unless they contain an urgent directive.
4. If there is nothing critical to do, DO NOT output any `propose_task` actions. Just output `coach_user` or an empty list.
5. Do not duplicate existing tasks.

Generate an execution plan (list of tasks) and provide coaching feedback.
Return ONLY valid JSON. E.g. 
[
  {{"action": "coach_user", "params": {{"feedback": "Sir, you have 5 overdue tasks. We need to focus. Stop procrastinating and clear the inbox."}}}}
]
"""
    if override_instruction:
        prompt += f"\n\nCRITICAL USER INSTRUCTION:\n{override_instruction}\nYou MUST prioritize answering this instruction in your task plan."
        
    system = "You are a universal planning AI. You output only valid JSON arrays."
    
    try:
        from jarvis_llm import ask_llm
        content = ask_llm(prompt, system=system, max_tokens=150, temperature=0.3, model_type="smart")
        
        if not content or not content.strip():
            print("[Agentic OS] LLM returned empty response. Skipping decision cycle.")
            return []

        # Strip markdown json block if present
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
            
        actions = json.loads(content.strip())
        if isinstance(actions, list):
            return actions
        return []
    except json.JSONDecodeError as e:
        print(f"[Agentic OS] LLM returned non-JSON: {e}")
        try:
            from jarvis_failure_store import record_failure
            record_failure("autonomous_llm_parse", str(e)[:80], severity="medium", category="crash")
        except Exception:
            pass
        return []
    except Exception as e:
        print(f"[Agentic OS] LLM Decision Error: {e}")
        return []

# ── 3. ACT ────────────────────────────────────────────────
def act_on_decisions(decisions: list[dict]):
    """Execute the actions within other tools."""
    print(f"[Agentic OS] 3. ACT: Executing {len(decisions)} decisions...")
    executed = []
    
    for decision in decisions:
        action = decision.get("action")
        params = decision.get("params", {})
        
        try:
            if action == "coach_user":
                feedback_str = params.get("feedback", "")
                if feedback_str:
                    speak(feedback_str)
                    executed.append(decision)
                    
            elif action == "propose_task":
                task_str = params.get("task", "")
                if task_str:
                    print(f"[Autonomy] Suggested task: {task_str}")
                    import jarvis_todoist
                    jarvis_todoist.create_task(f"[JARVIS] {task_str}")
                    executed.append(decision)
        except Exception as e:
            print(f"[Agentic OS] Action execution failed: {e}")
            
    if executed:
        speak("Sir, I have drafted a new execution plan and pushed the tasks to your Todoist Inbox for review.")
            
    return executed

# ── 4. UPDATE ─────────────────────────────────────────────
def update_system_of_record(executed: list[dict]):
    """Update internal memory/system of record."""
    print("[Agentic OS] 4. UPDATE: Synchronizing system of record...")
    mem = load_memory()
    if "tasks_auto_added" not in mem:
        mem["tasks_auto_added"] = []
        
    for act in executed:
        if act.get("action") == "propose_task":
            mem["tasks_auto_added"].append(act["params"]["task"])
            
    save_memory(mem)

# ── 5. AUDIT ──────────────────────────────────────────────
def audit_log(executed: list[dict]):
    """Log to daily notes for human trust/review."""
    if not executed:
        return
        
    print("[Agentic OS] 5. AUDIT: Writing to daily log...")
    try:
        vault, _, daily_dir, _, _ = jarvis_obsidian._init_jarvis_dirs()
        today = datetime.now().strftime("%Y-%m-%d")
        daily_file = daily_dir / f"{today}.md"
        
        content = daily_file.read_text() if daily_file.exists() else f"# JARVIS Audit Log - {today}\n"
        
        content += f"\n## Proposed Plan ({datetime.now().strftime('%H:%M:%S')})\n"
        for act in executed:
            content += f"- **{act['action']}**: {json.dumps(act['params'])}\n"
            
        daily_file.write_text(content)
    except Exception as e:
        print(f"[Agentic OS] Audit logging failed: {e}")

# ── ENGINE MANAGER ──────────────────────────────────────────
import asyncio
from openjarvis.core.events import EventBus
from openjarvis.engines.goal_engine import GoalEngine
from openjarvis.engines.health_engine import HealthEngine
from openjarvis.engines.finance_engine import FinanceEngine
from openjarvis.engines.crm_engine import CRMEngine
from openjarvis.engines.reflection_engine import ReflectionEngine
from openjarvis.engines.purpose_engine import PurposeEngine
from openjarvis.engines.security_engine import SecurityEngine

# Global Event Bus for the OS
os_bus = EventBus()
active_engines = []

def _handle_proactive_trigger(event_data: dict):
    """Handle proactive notifications from engines with DND awareness."""
    message = event_data.get("message", "")
    dnd_override = event_data.get("dnd_override", False)
    engine_name = event_data.get("engine_name", "JARVIS")
    
    # Simple DND check: don't interrupt if VS Code is focused (macOS specific stub)
    # For now, we assume DND is off unless override is needed.
    dnd_active = False 
    
    if dnd_active and not dnd_override:
        print(f"[{engine_name}] Silenced by DND: {message}")
        return
        
    print(f"[PROACTIVE - {engine_name}] {message}")
    try:
        from jarvis_speak import speak
        speak(message)
    except ImportError:
        pass

def init_engines():
    """Initialize and start all VFPOS engines."""
    global active_engines
    config = type("Config", (), {"health_ingestion": "manual"})()
    
    os_bus.subscribe("engine.proactive_trigger", _handle_proactive_trigger)
    
    active_engines = [
        GoalEngine("Goals", os_bus, config),
        HealthEngine("Health", os_bus, config),
        FinanceEngine("Finance", os_bus, config),
        CRMEngine("CRM", os_bus, config),
        ReflectionEngine("Reflection", os_bus, config),
        PurposeEngine("Purpose", os_bus, config),
        SecurityEngine("Security", os_bus, config),
    ]

async def run_engines():
    init_engines()
    for engine in active_engines:
        await engine.start()
        
    # The OS event loop
    while True:
        try:
            # The legacy autonomous loop tasks
            update_patterns()
            ctx = ingest_context()
            decisions = decide_actions(ctx)
            
            if decisions:
                executed = act_on_decisions(decisions)
                update_system_of_record(executed)
                audit_log(executed)
        except Exception as e:
            print(f"[Agentic OS] Main Loop Error: {e}")
            try:
                from jarvis_failure_store import record_failure
                record_failure("crash_jarvis_autonomous.main_loop", str(e)[:120], severity="critical", category="crash")
            except Exception:
                pass  # Never let tracker errors break the main loop

            
        # Trigger nightly analysis at next eligible window
        from pathlib import Path
        from datetime import date
        _LAST_NIGHTLY_FILE = Path.home() / ".jarvis" / "last_nightly_run.txt"
        should_run = False
        try:
            if _LAST_NIGHTLY_FILE.exists():
                last_run = _LAST_NIGHTLY_FILE.read_text().strip()
                if last_run != date.today().isoformat():
                    should_run = True
            else:
                should_run = True
        except Exception:
            should_run = True
            
        now = datetime.now()
        if should_run and (now.hour >= 23 or now.hour < 6):
            try:
                # Use the top-level jarvis_self_improvement module
                from jarvis_self_improvement import run_nightly_analysis
                proposal = await run_nightly_analysis()
                
                # Mark done
                _LAST_NIGHTLY_FILE.parent.mkdir(parents=True, exist_ok=True)
                _LAST_NIGHTLY_FILE.write_text(date.today().isoformat())
                
                if proposal and "Antigravity Proposal:" in proposal:
                    os_bus.publish("engine.proactive_trigger", {
                        "message": "Sir, I have completed my nightly self-analysis. I have prepared improvement proposals. Check your logs.",
                        "engine_name": "SelfImprovement"
                    })
                    print(f"\n[SelfImprovement — Nightly Analysis]\n{proposal}\n", flush=True)
                elif proposal:
                    print(f"\n[SelfImprovement — Nightly Analysis]\n{proposal}\n", flush=True)
            except Exception as e:
                print(f"[SelfImprovement] Nightly analysis failed: {e}", flush=True)
            
        import os
        perf_mode = os.environ.get("JARVIS_PERFORMANCE_MODE", "Balanced")
        if perf_mode == "M3 Air 8GB (Low Power)":
            sleep_time = 600  # 10 mins
        elif perf_mode == "Balanced":
            sleep_time = 300  # 5 mins
        else:
            sleep_time = 60   # 1 min
            
        await asyncio.sleep(sleep_time)

def background_loop():
    print("[Agentic OS] Engine Manager starting...")
    asyncio.run(run_engines())

def force_plan(user_instruction: str = ""):
    """Explicitly triggered planning override from voice system."""
    print(f"[Agentic OS] FORCED PLAN TRIGGERED: {user_instruction}")
    try:
        ctx = ingest_context()
        decisions = decide_actions(ctx, override_instruction=user_instruction)
        if decisions:
            executed = act_on_decisions(decisions)
            update_system_of_record(executed)
            audit_log(executed)
    except Exception as e:
        print(f"[Agentic OS] Force plan failed: {e}")

def start():
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
