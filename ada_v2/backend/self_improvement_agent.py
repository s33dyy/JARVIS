"""
SelfImprovementAgent — repo-scoped coding agent for J.A.R.V.I.S self-modification.
Supports persona updates, source edits, shell commands, and pip installs.
"""
import os
import re
import sys
import asyncio
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

_backend_dir = os.path.dirname(os.path.abspath(__file__))

# In PyInstaller bundle, use JARVIS_USERDATA as the writable root
_userdata_dir = os.environ.get("JARVIS_USERDATA", "")
if _userdata_dir and os.path.isdir(_userdata_dir):
    _repo_root = _userdata_dir
else:
    _repo_root = os.path.dirname(_backend_dir)

load_dotenv(os.path.join(_backend_dir, ".env"))

REPO_ROOT = Path(_repo_root).resolve()
PERSONA_FILE = REPO_ROOT / "jarvis_persona.txt"
MAX_READ_CHARS = 8000
MAX_TURNS = 15
COMMAND_TIMEOUT = 120

BLOCKED_PATH_PARTS = ("dist-py", ".git", "node_modules")
BLOCKED_PATH_FILES = (".env",)

COMMAND_BLOCKLIST = [
    re.compile(r"\bsudo\b", re.I),
    re.compile(r"rm\s+-rf\s+/", re.I),
    re.compile(r"\|\s*sh\b", re.I),
    re.compile(r"curl\s+.*\|\s*(ba)?sh", re.I),
    re.compile(r"wget\s+.*\|\s*(ba)?sh", re.I),
]

ROOT_CONFIG_FILES = ("package.json", "requirements.txt", "pyproject.toml", "setup.py")


def _get_api_key() -> str:
    try:
        import json as _json
        # Check JARVIS_USERDATA first (PyInstaller bundle), then backend dir (dev)
        sf = Path(_backend_dir) / "settings.json"
        if not sf.exists() and _userdata_dir and os.path.isdir(_userdata_dir):
            sf = Path(_userdata_dir) / "settings.json"
        if sf.exists():
            with open(sf, encoding="utf-8") as f:
                key = _json.load(f).get("gemini_api_key", "").strip()
                if key:
                    return key
    except Exception:
        pass
    return os.getenv("GEMINI_API_KEY", "")


def _is_blocked_path(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    for part in parts:
        if part in BLOCKED_PATH_PARTS:
            return True
    basename = Path(rel_path).name
    if basename in BLOCKED_PATH_FILES:
        return True
    return False


def _resolve_repo_path(path: str) -> Path:
    if os.path.isabs(path):
        candidate = Path(path).resolve()
    else:
        candidate = (REPO_ROOT / path).resolve()
    repo = str(REPO_ROOT)
    resolved = str(candidate)
    if not resolved.startswith(repo):
        raise ValueError(f"Path outside repo: {path}")
    rel = candidate.relative_to(REPO_ROOT).as_posix()
    if _is_blocked_path(rel):
        raise ValueError(f"Path blocked by policy: {path}")
    return candidate


def _is_command_blocked(command: str) -> Optional[str]:
    for pattern in COMMAND_BLOCKLIST:
        if pattern.search(command):
            return f"Command blocked by safety policy: matches {pattern.pattern}"
    return None


def _needs_restart(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    if norm.startswith("backend/"):
        return True
    if norm in ROOT_CONFIG_FILES:
        return True
    return False


# ── Internal tool declarations for Gemini ─────────────────────────────────────

_READ_FILE = {
    "name": "read_file",
    "description": "Read a text file from the JARVIS repo (relative path from repo root).",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {"type": "STRING", "description": "Relative path, e.g. backend/server.py"}
        },
        "required": ["path"],
    },
}

_WRITE_FILE = {
    "name": "write_file",
    "description": "Overwrite a file in the JARVIS repo with new content.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {"type": "STRING", "description": "Relative path from repo root"},
            "content": {"type": "STRING", "description": "Full file content"},
        },
        "required": ["path", "content"],
    },
}

_PATCH_FILE = {
    "name": "patch_file",
    "description": "Replace old_string with new_string in a repo file (must match exactly once).",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {"type": "STRING"},
            "old_string": {"type": "STRING"},
            "new_string": {"type": "STRING"},
        },
        "required": ["path", "old_string", "new_string"],
    },
}

_RUN_COMMAND = {
    "name": "run_command",
    "description": "Run a shell command in the repo root. Use for tests, builds, scripts. No sudo.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "command": {"type": "STRING", "description": "Shell command to execute"},
        },
        "required": ["command"],
    },
}

_INSTALL_PACKAGE = {
    "name": "install_package",
    "description": "Install Python package(s) via pip into the current environment.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "package": {
                "type": "STRING",
                "description": "Package name, or '-r requirements.txt' for requirements file",
            },
        },
        "required": ["package"],
    },
}

_UPDATE_PERSONA = {
    "name": "update_persona_file",
    "description": "Update jarvis_persona.txt with personality/behaviour instructions for future sessions.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "content": {"type": "STRING", "description": "Persona text to persist"},
            "mode": {
                "type": "STRING",
                "description": "overwrite or append",
                "enum": ["overwrite", "append"],
            },
        },
        "required": ["content"],
    },
}

_INTERNAL_TOOLS = [
    _READ_FILE,
    _WRITE_FILE,
    _PATCH_FILE,
    _RUN_COMMAND,
    _INSTALL_PACKAGE,
    _UPDATE_PERSONA,
]

SYSTEM_INSTRUCTION = """
You are J.A.R.V.I.S Self-Improvement Agent. You modify the JARVIS/ADA desktop assistant codebase
to fulfill improvement goals: persona changes, bug fixes, new capabilities, dependency installs.

Repo layout (relative to root):
- backend/ — Python server (ada.py, server.py, agents)
- src/ — React/Electron frontend
- jarvis_persona.txt — persistent personality amendments
- package.json, requirements.txt — dependencies

Rules:
1. Make minimal, focused changes matching existing code style.
2. Use read_file before editing; prefer patch_file for small edits.
3. Use install_package for pip deps; run_command for tests/verification.
4. Use update_persona_file for behavioural/personality changes only.
5. All paths must be relative to repo root. Never access files outside the repo.
6. When done, respond with a brief summary of what you changed.
"""


class SelfImprovementAgent:
    def __init__(
        self,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        api_key = _get_api_key()
        if not api_key:
            raise ValueError("GEMINI_API_KEY required for SelfImprovementAgent")
        self.client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
        self.model = "gemini-2.0-flash"
        self.on_log = on_log
        self.on_status = on_status
        self._files_changed: List[str] = []
        self._commands_run: List[str] = []
        self._restart_required = False

    def _log(self, text: str):
        print(f"[SelfImprove] {text}")
        if self.on_log:
            self.on_log(text)

    def _emit_status(self, status: str, message: str = "", step: int = 0):
        if self.on_status:
            self.on_status({"status": status, "message": message, "step": step})

    def _track_file_change(self, rel_path: str):
        rel = rel_path.replace("\\", "/")
        if rel not in self._files_changed:
            self._files_changed.append(rel)
        if _needs_restart(rel):
            self._restart_required = True

    def _tool_read_file(self, path: str) -> str:
        resolved = _resolve_repo_path(path)
        if not resolved.is_file():
            return f"Error: file not found: {path}"
        try:
            with open(resolved, encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            return f"Error: file appears binary or non-UTF-8: {path}"
        if len(content) > MAX_READ_CHARS:
            content = content[:MAX_READ_CHARS] + f"\n... [truncated, {MAX_READ_CHARS} chars shown]"
        return content

    def _tool_write_file(self, path: str, content: str) -> str:
        resolved = _resolve_repo_path(path)
        os.makedirs(resolved.parent, exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        rel = resolved.relative_to(REPO_ROOT).as_posix()
        self._track_file_change(rel)
        return f"OK: wrote {rel} ({len(content)} bytes)"

    def _tool_patch_file(self, path: str, old_string: str, new_string: str) -> str:
        resolved = _resolve_repo_path(path)
        if not resolved.is_file():
            return f"Error: file not found: {path}"
        with open(resolved, encoding="utf-8") as f:
            original = f.read()
        count = original.count(old_string)
        if count == 0:
            return "Error: old_string not found in file"
        if count > 1:
            return f"Error: old_string found {count} times; must be unique"
        patched = original.replace(old_string, new_string, 1)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(patched)
        rel = resolved.relative_to(REPO_ROOT).as_posix()
        self._track_file_change(rel)
        return f"OK: patched {rel}"

    async def _tool_run_command(self, command: str) -> str:
        blocked = _is_command_blocked(command)
        if blocked:
            return f"Error: {blocked}"
        self._commands_run.append(command)
        self._log(f"$ {command}")
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                command,
                shell=True,
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            if len(out) > 4000:
                out = out[:4000] + "\n... [truncated]"
            status = "OK" if proc.returncode == 0 else f"exit {proc.returncode}"
            return f"{status}\n{out}"
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {COMMAND_TIMEOUT}s"
        except Exception as e:
            return f"Error: {e}"

    async def _tool_install_package(self, package: str) -> str:
        pkg = package.strip()
        if _is_command_blocked(pkg) or "sudo" in pkg.lower():
            return "Error: install blocked by safety policy"
        cmd = f"{sys.executable} -m pip install {pkg}"
        self._commands_run.append(cmd)
        self._log(f"$ {cmd}")
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "pip", "install"] + pkg.split(),
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            if len(out) > 4000:
                out = out[:4000] + "\n... [truncated]"
            status = "OK" if proc.returncode == 0 else f"exit {proc.returncode}"
            return f"{status}\n{out}"
        except subprocess.TimeoutExpired:
            return f"Error: pip timed out after {COMMAND_TIMEOUT}s"
        except Exception as e:
            return f"Error: {e}"

    def _tool_update_persona(self, content: str, mode: str = "overwrite") -> str:
        rel = "jarvis_persona.txt"
        if mode == "append" and PERSONA_FILE.exists():
            with open(PERSONA_FILE, encoding="utf-8") as f:
                existing = f.read()
            new_content = existing.rstrip() + "\n" + content
        else:
            new_content = content
        with open(PERSONA_FILE, "w", encoding="utf-8") as f:
            f.write(new_content)
        self._track_file_change(rel)
        return f"OK: persona file updated ({mode})"

    async def _execute_internal_tool(self, name: str, args: dict) -> str:
        try:
            if name == "read_file":
                return self._tool_read_file(args.get("path", ""))
            if name == "write_file":
                return self._tool_write_file(args.get("path", ""), args.get("content", ""))
            if name == "patch_file":
                return self._tool_patch_file(
                    args.get("path", ""),
                    args.get("old_string", ""),
                    args.get("new_string", ""),
                )
            if name == "run_command":
                return await self._tool_run_command(args.get("command", ""))
            if name == "install_package":
                return await self._tool_install_package(args.get("package", ""))
            if name == "update_persona_file":
                return self._tool_update_persona(
                    args.get("content", ""),
                    args.get("mode", "overwrite"),
                )
            return f"Error: unknown internal tool '{name}'"
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error: {e}"

    async def improve(self, goal: str) -> Dict[str, Any]:
        """Run the self-improvement loop for the given goal."""
        self._files_changed = []
        self._commands_run = []
        self._restart_required = False
        self._emit_status("running", "Starting self-improvement...", 0)
        self._log(f"Goal: {goal}")

        # Check auto_apply_patches setting
        auto_apply = False
        try:
            import json as _json
            sf = Path(_backend_dir) / "settings.json"
            if not sf.exists() and os.environ.get("JARVIS_USERDATA"):
                sf = Path(os.environ["JARVIS_USERDATA"]) / "settings.json"
            if sf.exists():
                with open(sf) as f:
                    auto_apply = _json.load(f).get("self_improvement", {}).get("auto_apply_patches", False)
        except Exception:
            pass
        self._auto_apply = auto_apply

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[types.Tool(function_declarations=_INTERNAL_TOOLS)],
            temperature=0.2,
        )

        chat_history: List[types.Content] = [
            types.Content(role="user", parts=[types.Part(text=f"Self-improvement goal: {goal}")])
        ]

        final_summary = ""
        success = False

        try:
            for turn in range(MAX_TURNS):
                self._emit_status("running", f"Turn {turn + 1}/{MAX_TURNS}", turn + 1)
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=chat_history,
                    config=config,
                )

                if not response.candidates:
                    self._log("Empty response from model")
                    break

                candidate = response.candidates[0]
                model_content = candidate.content
                chat_history.append(model_content)

                function_calls = []
                agent_text = ""
                for part in model_content.parts:
                    if part.text and not part.thought:
                        agent_text = part.text
                        self._log(part.text[:500])
                    if part.function_call:
                        function_calls.append(part.function_call)

                if agent_text:
                    final_summary = agent_text

                if not function_calls:
                    success = True
                    break

                response_parts = []
                for fc in function_calls:
                    fn_name = fc.name
                    fn_args = dict(fc.args) if fc.args else {}
                    self._log(f"Tool: {fn_name}({fn_args})")
                    result = await self._execute_internal_tool(fn_name, fn_args)
                    self._log(f"  -> {result[:200]}")
                    call_id = getattr(fc, "id", None)
                    response_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=call_id,
                                name=fn_name,
                                response={"result": result},
                            )
                        )
                    )

                chat_history.append(types.Content(role="user", parts=response_parts))

            if not final_summary:
                final_summary = "Self-improvement completed."

            result = {
                "success": success,
                "summary": final_summary,
                "files_changed": list(self._files_changed),
                "commands_run": list(self._commands_run),
                "restart_required": self._restart_required,
            }
            self._emit_status("done", final_summary)
            return result

        except Exception as e:
            err = str(e)
            self._log(f"FAILED: {err}")
            self._emit_status("failed", err)
            return {
                "success": False,
                "summary": f"Self-improvement failed: {err}",
                "files_changed": list(self._files_changed),
                "commands_run": list(self._commands_run),
                "restart_required": self._restart_required,
            }
