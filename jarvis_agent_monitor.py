"""
jarvis_agent_monitor.py
-----------------------
Monitor and interact with Antigravity / Codex background agents.
Parses transcripts, reads tasks, tracks state, and sends inbox messages.
"""

import os
import re
import json
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union, Any

# Default path to the Antigravity brain
BRAIN_DIR = Path.home() / ".gemini" / "antigravity" / "brain"

def get_active_conversations(limit: int = 5) -> list[dict]:
    """
    Scan the brain directory for UUID-like conversation folders containing
    active transcripts. Returns metadata sorted by modification time (newest first).
    """
    if not BRAIN_DIR.exists():
        return []

    conversations = []
    try:
        for entry in BRAIN_DIR.iterdir():
            if not entry.is_dir():
                continue
            
            # Match UUID folder names (standard format for agent conversation IDs)
            if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", entry.name, re.IGNORECASE):
                continue

            transcript_path = entry / ".system_generated" / "logs" / "transcript.jsonl"
            if not transcript_path.exists():
                continue

            try:
                mtime = os.path.getmtime(transcript_path)
                mtime_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
                conversations.append({
                    "conv_id": entry.name,
                    "path": entry,
                    "mtime": mtime,
                    "mtime_dt": mtime_dt
                })
            except OSError:
                pass
    except Exception as exc:
        print(f"[agent_monitor] Error scanning brain directory: {exc}")

    # Sort newest first
    conversations.sort(key=lambda x: x["mtime"], reverse=True)
    return conversations[:limit]

def parse_conversation(conv_id: str) -> Optional[dict]:
    """
    Parse the transcript and task list of a specific conversation ID.
    Returns structured data detailing the agent's progress and current state.
    """
    conv_dir = BRAIN_DIR / conv_id
    transcript_path = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
    if not transcript_path.exists():
        return None

    goal = "Unknown task"
    status = "In progress"
    last_step = {}
    pending_tool_calls = []

    # 1. Parse transcript JSONL
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        
        # Extract the initial goal (from the first USER_INPUT step)
        for line in lines:
            try:
                step = json.loads(line)
                if step.get("type") == "USER_INPUT":
                    content = step.get("content", "")
                    # Extract content inside <USER_REQUEST> if present
                    req_match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
                    if req_match:
                        raw_goal = req_match.group(1).strip()
                    else:
                        raw_goal = content.strip()
                    # Clean up long goals
                    goal_lines = [l.strip() for l in raw_goal.splitlines() if l.strip()]
                    goal = goal_lines[0] if goal_lines else "Unknown task"
                    if len(goal) > 80:
                        goal = goal[:77] + "..."
                    break
            except Exception:
                pass

        # Parse the last step
        if lines:
            try:
                last_step = json.loads(lines[-1])
            except Exception:
                pass

    except Exception as exc:
        print(f"[agent_monitor] Error reading transcript for {conv_id}: {exc}")

    # 2. Parse Task List (task.md)
    task_file = conv_dir / "task.md"
    tasks_summary = {
        "completed": 0,
        "in_progress": 0,
        "pending": 0,
        "total": 0,
        "percent": 0,
        "active_items": []
    }
    
    if task_file.exists():
        try:
            content = task_file.read_text(encoding="utf-8")
            completed = len(re.findall(r"-\s*\[[xX]\]", content))
            in_progress = len(re.findall(r"-\s*\[/\]", content))
            pending = len(re.findall(r"-\s*\[\s\]", content))
            total = completed + in_progress + pending
            percent = int(100 * completed / total) if total > 0 else 0

            # Find active items (pending or in-progress)
            active_items = []
            for line in content.splitlines():
                if "[-]" in line or "[/]" in line or "[ ]" in line:
                    item_text = re.sub(r"-\s*\[.*?\]\s*", "", line).strip()
                    if item_text:
                        active_items.append(item_text)

            tasks_summary = {
                "completed": completed,
                "in_progress": in_progress,
                "pending": pending,
                "total": total,
                "percent": percent,
                "active_items": active_items[:3]  # Keep first 3
            }
        except Exception as exc:
            print(f"[agent_monitor] Error parsing task.md for {conv_id}: {exc}")

    # 3. Determine Agent Status
    walkthrough_file = conv_dir / "walkthrough.md"
    
    # If a walkthrough was written and there are no pending tasks, or tasks are 100% done, mark Completed
    has_pending_tasks = tasks_summary["total"] > 0 and tasks_summary["percent"] < 100
    if (walkthrough_file.exists() and not has_pending_tasks) or (tasks_summary["total"] > 0 and tasks_summary["percent"] == 100):
        status = "Completed"
    elif last_step:
        # Check if model made tool calls in the final step that haven't received answers yet
        source = last_step.get("source")
        step_type = last_step.get("type")
        tool_calls = last_step.get("tool_calls", [])
        
        if source == "MODEL" and step_type == "PLANNER_RESPONSE" and tool_calls:
            pending_tool_calls = tool_calls
            # Check if it writes implementation_plan with feedback requested
            is_plan_feedback = False
            for tc in tool_calls:
                args = tc.get("args", {})
                # Normalize arguments (can be parsed as string/json or nested dict)
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                
                metadata = args.get("ArtifactMetadata") or {}
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except Exception:
                        pass

                if metadata.get("RequestFeedback") is True:
                    is_plan_feedback = True
                    break
            
            if is_plan_feedback:
                status = "Waiting for plan approval"
            else:
                status = "Waiting for permission"
        elif source == "MODEL" and not tool_calls:
            # Idle and waiting for the user's next response
            status = "Waiting for user input"
        else:
            status = "In progress"

    # Try to extract the subagent names from recent tool calls
    subagents = []
    if last_step:
        tool_calls = last_step.get("tool_calls", [])
        for tc in tool_calls:
            if tc.get("name") in ("invoke_subagent", "invoke_subagents"):
                args = tc.get("args", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                sub_list = args.get("Subagents") or []
                if isinstance(sub_list, str):
                    try:
                        sub_list = json.loads(sub_list)
                    except Exception:
                        pass
                for s in sub_list:
                    subagents.append({
                        "name": s.get("TypeName") or s.get("TypeName", "subagent"),
                        "role": s.get("Role") or "assistant"
                    })

    return {
        "conv_id": conv_id,
        "goal": goal,
        "status": status,
        "tasks": tasks_summary,
        "pending_tools": pending_tool_calls,
        "subagents": subagents,
        "last_step_type": last_step.get("type", "Unknown"),
        "last_step_time": last_step.get("created_at")
    }

def send_prompt_to_agent(conv_id: str, prompt: str) -> str:
    """
    Send a tailored prompt/message to a running agent by writing a JSON message
    into its .system_generated/messages/ folder.
    """
    conv_dir = BRAIN_DIR / conv_id
    if not conv_dir.exists():
        return f"Conversation directory for {conv_id} does not exist."

    messages_dir = conv_dir / ".system_generated" / "messages"
    try:
        messages_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return f"Failed to create messages directory: {exc}"

    msg_id = str(uuid.uuid4())
    msg_path = messages_dir / f"{msg_id}.json"

    # Construct the standard message schema
    timestamp_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    message_data = {
        "id": msg_id,
        "recipient": conv_id,
        "sender": "USER",
        "priority": "MESSAGE_PRIORITY_HIGH",
        "timestamp": timestamp_utc,
        "content": prompt
    }

    try:
        with open(msg_path, "w", encoding="utf-8") as f:
            json.dump(message_data, f, indent=2)
        return f"Successfully sent prompt to agent '{conv_id[:8]}'."
    except Exception as exc:
        return f"Failed to write message JSON: {exc}"

if __name__ == "__main__":
    import sys
    print("Scanning active agent conversations...")
    convs = get_active_conversations()
    for c in convs:
        details = parse_conversation(c["conv_id"])
        if details:
            print(f"\nConversation: {details['conv_id']}")
            print(f"  Goal:   {details['goal']}")
            print(f"  Status: {details['status']}")
            print(f"  Tasks:  {details['tasks']['percent']}% done ({details['tasks']['completed']}/{details['tasks']['total']})")
            if details["tasks"]["active_items"]:
                print(f"  Next:   {details['tasks']['active_items'][0]}")
