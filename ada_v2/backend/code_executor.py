"""
code_executor.py — Secure code execution for J.A.R.V.I.S

Provides:
  - run_shell(command)      : Execute shell commands with safety checks
  - run_python(code)        : Execute Python code in isolated process
  - install_package(name)   : Install pip packages silently

Security:
  - Blocks sudo, rm -rf /, piping to sh, etc.
  - Timeout enforcement (120s default)
  - Streaming output support
"""

import asyncio
import os
import re
import sys
import tempfile
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Callable, Dict, Any

# ── Security ──────────────────────────────────────────────────────────────────

BLOCKED_COMMANDS = [
    re.compile(r"\bsudo\b", re.I),
    re.compile(r"rm\s+-rf\s+/", re.I),
    re.compile(r"\|\s*sh\b", re.I),
    re.compile(r"curl\s+.*\|\s*(ba)?sh", re.I),
    re.compile(r"wget\s+.*\|\s*(ba)?sh", re.I),
    re.compile(r"mkfs\b", re.I),
    re.compile(r":(){ :\|:& };:", re.I),  # fork bomb
    re.compile(r"dd\s+.*of=/dev/", re.I),
]

# Dangerous paths that should never be modified
PROTECTED_PATHS = [
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/System",
    "/Library",
    "~/.ssh",
]

DEFAULT_TIMEOUT = 120
PYTHON_TIMEOUT = 60


def _is_command_safe(command: str) -> tuple:
    """Check if a command passes security checks. Returns (safe, reason)."""
    for pattern in BLOCKED_COMMANDS:
        if pattern.search(command):
            return False, f"Blocked: command matches dangerous pattern '{pattern.pattern}'"
    return True, ""


def _get_python_executable() -> str:
    """Get the current Python executable path."""
    return sys.executable


# ── Shell Execution ───────────────────────────────────────────────────────────

async def run_shell(
    command: str,
    timeout: int = DEFAULT_TIMEOUT,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    on_output: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """
    Execute a shell command with security checks.

    Args:
        command: Shell command to execute
        timeout: Max execution time in seconds
        cwd: Working directory (defaults to current dir)
        env: Additional environment variables
        on_output: Callback(stdout_line, stderr_line) for streaming

    Returns:
        dict with: stdout, stderr, returncode, timed_out, blocked, error
    """
    # Security check
    safe, reason = _is_command_safe(command)
    if not safe:
        return {
            "stdout": "",
            "stderr": reason,
            "returncode": -1,
            "timed_out": False,
            "blocked": True,
            "error": reason,
        }

    # Prepare environment
    exec_env = os.environ.copy()
    if env:
        exec_env.update(env)

    # Default working directory
    if cwd is None:
        cwd = os.getcwd()

    print(f"[CodeExec] Running shell: {command[:100]}...")
    stdout_lines = []
    stderr_lines = []
    timed_out = False

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=exec_env,
        )

        async def _read_stream(stream, buffer, prefix):
            async for line in stream:
                text = line.decode("utf-8", errors="replace")
                buffer.append(text)
                if on_output:
                    on_output(prefix, text)

        stdout_task = asyncio.create_task(_read_stream(process.stdout, stdout_lines, "stdout"))
        stderr_task = asyncio.create_task(_read_stream(process.stderr, stderr_lines, "stderr"))

        try:
            await asyncio.wait_for(
                asyncio.gather(stdout_task, stderr_task),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout_task.cancel()
            stderr_task.cancel()

        # Ensure process has fully exited and returncode is set
        await process.wait()
        returncode = process.returncode if process.returncode is not None else -1

        return {
            "stdout": "".join(stdout_lines),
            "stderr": "".join(stderr_lines),
            "returncode": returncode,
            "timed_out": timed_out,
            "blocked": False,
            "error": None,
        }

    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
            "timed_out": False,
            "blocked": False,
            "error": str(e),
        }


# ── Python Execution ──────────────────────────────────────────────────────────

async def run_python(
    code: str,
    timeout: int = PYTHON_TIMEOUT,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    on_output: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """
    Execute Python code in an isolated subprocess.

    Args:
        code: Python source code to execute
        timeout: Max execution time in seconds
        cwd: Working directory
        env: Additional environment variables
        on_output: Callback for streaming output

    Returns:
        dict with: stdout, stderr, returncode, timed_out, error
    """
    # Write code to a temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        python_exe = _get_python_executable()
        result = await run_shell(
            command=f'"{python_exe}" "{script_path}"',
            timeout=timeout,
            cwd=cwd,
            env=env,
            on_output=on_output,
        )
        result["script_path"] = script_path
        return result
    finally:
        # Clean up temp file
        try:
            os.unlink(script_path)
        except OSError:
            pass


# ── Package Installation ──────────────────────────────────────────────────────

async def install_package(
    package_name: str,
    pip_args: Optional[list] = None,
    timeout: int = 120,
    on_output: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """
    Install a Python package silently.

    Args:
        package_name: Package name (e.g., 'requests' or 'requests>=2.28')
        pip_args: Additional pip arguments
        timeout: Max execution time
        on_output: Callback for streaming output

    Returns:
        dict with: stdout, stderr, returncode, success, error
    """
    python_exe = _get_python_executable()
    cmd_parts = [f'"{python_exe}"', "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
    if pip_args:
        cmd_parts.extend(pip_args)
    cmd_parts.append(f'"{package_name}"')
    command = " ".join(cmd_parts)

    print(f"[CodeExec] Installing package: {package_name}")
    result = await run_shell(command, timeout=timeout, on_output=on_output)

    result["success"] = result["returncode"] == 0
    if result["success"]:
        print(f"[CodeExec] Package '{package_name}' installed successfully.")
    else:
        print(f"[CodeExec] Package '{package_name}' install failed: {result['stderr'][:200]}")

    return result


# ── Convenience: Run in project context ──────────────────────────────────────

async def run_in_project(
    command: str,
    project_path: str,
    timeout: int = DEFAULT_TIMEOUT,
    on_output: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """Run a command scoped to a project directory."""
    return await run_shell(
        command=command,
        timeout=timeout,
        cwd=project_path,
        on_output=on_output,
    )


# ── Module test ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def test():
        print("=== Testing run_shell ===")
        result = await run_shell("echo hello world", timeout=5)
        print(f"Result: {result}")

        print("\n=== Testing run_python ===")
        result = await run_python("print('Hello from Python!')", timeout=5)
        print(f"Result: {result}")

        print("\n=== Testing security block ===")
        result = await run_shell("sudo rm -rf /", timeout=5)
        print(f"Result: {result}")

    asyncio.run(test())
