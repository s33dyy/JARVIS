"""
jarvis_todoist.py
-----------------
Integrates JARVIS with the Todoist REST API v2.
"""

import httpx
import os
import json
import certifi
from datetime import datetime

# Fix SSL paths for PyInstaller bundle
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

# Token provided by user
TODOIST_TOKEN = os.environ.get("JARVIS_TODOIST_TOKEN", "2339137af383dabd9dc7cbe00a425cce6dea9626")
BASE_URL = "https://api.todoist.com/api/v1"

def _get_headers():
    return {
        "Authorization": f"Bearer {TODOIST_TOKEN}",
        "Content-Type": "application/json"
    }

def get_projects() -> list[dict]:
    """Fetch all active Todoist projects."""
    try:
        resp = httpx.get(f"{BASE_URL}/projects", headers=_get_headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", data) if isinstance(data, dict) else data
    except Exception as e:
        print(f"[Todoist] Error fetching projects: {e}")
        return []

def get_tasks(filter_query: str = "") -> list[dict]:
    """Fetch active Todoist tasks, optionally filtered (e.g. 'today')."""
    try:
        params = {}
        if filter_query:
            params["filter"] = filter_query
        resp = httpx.get(f"{BASE_URL}/tasks", headers=_get_headers(), params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", data) if isinstance(data, dict) else data
    except Exception as e:
        print(f"[Todoist] Error fetching tasks: {e}")
        return []

def create_task(content: str, description: str = "", due_string: str = "") -> dict:
    """Create a new task in Todoist."""
    try:
        data = {"content": content}
        if description:
            data["description"] = description
        if due_string:
            data["due_string"] = due_string
            
        resp = httpx.post(f"{BASE_URL}/tasks", headers=_get_headers(), json=data, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[Todoist] Error creating task: {e}")
        return {}

def update_task(task_id: str, **kwargs) -> bool:
    """Update an existing task in Todoist."""
    try:
        resp = httpx.post(f"{BASE_URL}/tasks/{task_id}", headers=_get_headers(), json=kwargs, timeout=10, verify=False)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[Todoist] Error updating task {task_id}: {e}")
        return False

def close_task(task_id: str) -> bool:
    """Complete a task in Todoist."""
    try:
        resp = httpx.post(f"{BASE_URL}/tasks/{task_id}/close", headers=_get_headers(), timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[Todoist] Error closing task: {e}")
        return False

def get_tasks_summary() -> str:
    """Returns a string summary of today's and overdue tasks for context."""
    tasks = get_tasks(filter_query="today | overdue")
    if not tasks:
        return "No tasks due today in Todoist."
    
    summary = []
    for i, t in enumerate(tasks):
        due = t.get("due", {})
        due_date = due.get("date", "No date") if due else "No date"
        summary.append(f"{i+1}. {t['content']} (Due: {due_date}) [ID: {t['id']}]")
        
    return "\n".join(summary)

def get_all_tasks_summary() -> str:
    """Returns a summary of all active tasks across projects."""
    tasks = get_tasks()
    if not tasks:
        return "No active tasks in Todoist."
        
    summary = []
    for i, t in enumerate(tasks[:50]): # Cap at 50 so we don't blow up context
        summary.append(f"- {t['content']} [ID: {t['id']}]")
        
    return "\n".join(summary)
