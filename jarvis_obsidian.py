import os
import re
from pathlib import Path
from datetime import datetime
import subprocess

# Common vault names/locations
POSSIBLE_VAULTS = [
    Path.home() / "Documents" / "Obsidian Vault",
    Path.home() / "Obsidian",
]

def find_or_create_vault() -> Path:
    # 1. Look for existing vault
    for vault in POSSIBLE_VAULTS:
        if (vault / ".obsidian").is_dir() or vault.is_dir():
            return vault
            
    # 2. Search home for .obsidian
    try:
        res = subprocess.run(["find", str(Path.home()), "-maxdepth", "3", "-name", ".obsidian", "-type", "d"], 
                             capture_output=True, text=True, timeout=3)
        if res.stdout.strip():
            first = res.stdout.strip().splitlines()[0]
            return Path(first).parent
    except Exception:
        pass
        
    # 3. Create default
    default_vault = POSSIBLE_VAULTS[0]
    default_vault.mkdir(parents=True, exist_ok=True)
    (default_vault / ".obsidian").mkdir(exist_ok=True)
    return default_vault

def _init_jarvis_dirs():
    vault = find_or_create_vault()
    jarvis_dir = vault / "JARVIS"
    daily_dir = vault / "Daily Notes"
    crm_dir = jarvis_dir / "CRM"
    projects_dir = jarvis_dir / "Projects"
    
    jarvis_dir.mkdir(exist_ok=True)
    daily_dir.mkdir(exist_ok=True)
    crm_dir.mkdir(exist_ok=True)
    projects_dir.mkdir(exist_ok=True)
    
    # Touch main files if they don't exist
    tasks_file = jarvis_dir / "Tasks.md"
    if not tasks_file.exists():
        tasks_file.write_text("# JARVIS Tasks\n\n## Open Tasks\n\n## Completed Tasks\n")
        
    return vault, jarvis_dir, daily_dir, crm_dir, projects_dir

def add_task(task_text: str):
    vault, jarvis_dir, _, _, _ = _init_jarvis_dirs()
    tasks_file = jarvis_dir / "Tasks.md"
    content = tasks_file.read_text() if tasks_file.exists() else ""
    
    new_task = f"- [ ] {task_text}\n"
    if "## Open Tasks" in content:
        content = content.replace("## Open Tasks\n", f"## Open Tasks\n{new_task}")
    else:
        content += f"\n## Open Tasks\n{new_task}"
        
    tasks_file.write_text(content)

def mark_task_done(task_keyword: str) -> bool:
    vault, jarvis_dir, _, _, _ = _init_jarvis_dirs()
    tasks_file = jarvis_dir / "Tasks.md"
    if not tasks_file.exists():
        return False
        
    lines = tasks_file.read_text().splitlines()
    changed = False
    for i, line in enumerate(lines):
        if "- [ ]" in line and task_keyword.lower() in line.lower():
            lines[i] = line.replace("- [ ]", "- [x]")
            changed = True
    
    if changed:
        tasks_file.write_text("\n".join(lines))
    return changed

def get_open_tasks() -> list[str]:
    vault, jarvis_dir, _, _, _ = _init_jarvis_dirs()
    tasks_file = jarvis_dir / "Tasks.md"
    if not tasks_file.exists():
        return []
        
    tasks = []
    for line in tasks_file.read_text().splitlines():
        if "- [ ]" in line:
            # strip markdown check box
            tasks.append(line.split("- [ ]", 1)[1].strip())
    return tasks

def log_work_session(project: str, duration_str: str, details: str = ""):
    vault, jarvis_dir, daily_dir, _, _ = _init_jarvis_dirs()
    now = datetime.now()
    daily_file = daily_dir / f"{now.strftime('%Y-%m-%d')}.md"
    
    if not daily_file.exists():
        content = f"# {now.strftime('%A, %d %B %Y')}\n\n## 💻 Work Sessions\n"
    else:
        content = daily_file.read_text()
        if "## 💻 Work Sessions" not in content:
            content += "\n## 💻 Work Sessions\n"
            
    session_log = f"- {now.strftime('%H:%M')} -> **{project}** ({duration_str}) {details}\n"
    content = content.replace("## 💻 Work Sessions\n", f"## 💻 Work Sessions\n{session_log}")
    daily_file.write_text(content)

def log_event(category: str, text: str):
    vault, jarvis_dir, daily_dir, _, _ = _init_jarvis_dirs()
    now = datetime.now()
    daily_file = daily_dir / f"{now.strftime('%Y-%m-%d')}.md"
    
    if not daily_file.exists():
        content = f"# {now.strftime('%A, %d %B %Y')}\n\n## 📝 {category}\n"
    else:
        content = daily_file.read_text()
        if f"## 📝 {category}" not in content:
            content += f"\n## 📝 {category}\n"
            
    log_line = f"- {now.strftime('%H:%M')} -> {text}\n"
    content = content.replace(f"## 📝 {category}\n", f"## 📝 {category}\n{log_line}")
    daily_file.write_text(content)

def update_crm(contact_name: str, details: str):
    vault, jarvis_dir, daily_dir, crm_dir, projects_dir = _init_jarvis_dirs()
    crm_file = crm_dir / f"{contact_name}.md"
    now = datetime.now()
    
    if not crm_file.exists():
        content = f"# {contact_name}\n\n## 📋 Details\n- Created: {now.strftime('%Y-%m-%d')}\n\n## 📝 Logs\n"
    else:
        content = crm_file.read_text()
        
    log_line = f"- **{now.strftime('%Y-%m-%d %H:%M')}**: {details}\n"
    if "## 📝 Logs\n" in content:
        content = content.replace("## 📝 Logs\n", f"## 📝 Logs\n{log_line}")
    else:
        content += f"\n## 📝 Logs\n{log_line}"
        
    crm_file.write_text(content)

def update_project(project_name: str, status: str, next_steps: str):
    vault, jarvis_dir, daily_dir, crm_dir, projects_dir = _init_jarvis_dirs()
    project_file = projects_dir / f"{project_name}.md"
    now = datetime.now()
    
    if not project_file.exists():
        content = f"# {project_name}\n\n## 📊 Status\n\n## 🚀 Next Steps\n\n## 📝 Logs\n"
    else:
        content = project_file.read_text()
        
    # Replace status and next steps blocks using regex
    content = re.sub(r"## 📊 Status\n.*?(?=##|$)", f"## 📊 Status\n{status}\n\n", content, flags=re.DOTALL)
    content = re.sub(r"## 🚀 Next Steps\n.*?(?=##|$)", f"## 🚀 Next Steps\n{next_steps}\n\n", content, flags=re.DOTALL)
    
    log_line = f"- **{now.strftime('%Y-%m-%d %H:%M')}**: Status updated to '{status}'\n"
    if "## 📝 Logs\n" in content:
        content = content.replace("## 📝 Logs\n", f"## 📝 Logs\n{log_line}")
    else:
        content += f"\n## 📝 Logs\n{log_line}"
        
    project_file.write_text(content)
