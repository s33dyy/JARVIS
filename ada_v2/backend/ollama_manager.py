"""
ollama_manager.py — Auto-installs Ollama, pulls models based on RAM, provides API access.
Used as fallback when Gemini API quota is exhausted.
"""
import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Optional

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

OLLAMA_BASE_URL = "http://localhost:11434"

# ── Model selection based on available RAM ─────────────────────────────────────
# Chat models (tool-calling support via Ollama /api/chat endpoint)
CHAT_MODELS = [
    (32, "qwen2.5:14b"),   # 32GB+ RAM
    (16, "qwen2.5:7b"),    # 16GB+ RAM
    (8,  "qwen2.5:3b"),    # 8GB+ RAM
    (6,  "qwen2.5:1.5b"),  # 6GB+ RAM
    (0,  None),            # < 6GB: cannot run local
]

# Code/CAD generation models
CODE_MODELS = [
    (32, "qwen2.5-coder:14b"),
    (16, "qwen2.5-coder:7b"),
    (8,  "qwen2.5-coder:3b"),
    (6,  "qwen2.5-coder:1.5b"),
    (0,  None),
]

# STT models (whisper via faster-whisper)
STT_MODELS = [
    (16, "small"),
    (8,  "base"),
    (0,  "tiny"),
]


def get_ram_gb() -> float:
    """Returns total system RAM in GB."""
    if _HAS_PSUTIL:
        return psutil.virtual_memory().total / (1024 ** 3)
    # Fallback
    if platform.system() == "Darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"]).decode().strip()
            return int(out) / (1024 ** 3)
        except Exception:
            pass
    elif platform.system() == "Windows":
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                             ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                             ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                             ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                             ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)
        except Exception:
            pass
    return 8.0  # Safe default


def select_model(model_table: list, ram_gb: float) -> Optional[str]:
    for threshold, model in model_table:
        if ram_gb >= threshold:
            return model
    return None


def get_chat_model() -> Optional[str]:
    return select_model(CHAT_MODELS, get_ram_gb())


def get_code_model() -> Optional[str]:
    return select_model(CODE_MODELS, get_ram_gb())


def get_stt_model() -> str:
    ram = get_ram_gb()
    for threshold, model in STT_MODELS:
        if ram >= threshold:
            return model
    return "tiny"


# ── Ollama Installation ────────────────────────────────────────────────────────

def is_ollama_installed() -> bool:
    return shutil.which("ollama") is not None


def is_ollama_running() -> bool:
    try:
        req = urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return req.status == 200
    except Exception:
        return False


async def start_ollama_service():
    """Starts the Ollama server in background if not running."""
    if is_ollama_running():
        print("[OLLAMA] Server already running.")
        return True
    print("[OLLAMA] Starting server...")
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["ollama", "serve"], creationflags=subprocess.CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Wait up to 10 seconds
        for _ in range(20):
            await asyncio.sleep(0.5)
            if is_ollama_running():
                print("[OLLAMA] Server started.")
                return True
        print("[OLLAMA] Server failed to start in time.")
        return False
    except Exception as e:
        print(f"[OLLAMA] Failed to start server: {e}")
        return False


async def install_ollama():
    """Auto-installs Ollama. Shows permission dialog via subprocess on Mac/Win."""
    print("[OLLAMA] Installing Ollama...")
    system = platform.system()

    if system == "Darwin":
        # Try brew first (no sudo needed), else fall back to official install.sh
        if shutil.which("brew"):
            print("[OLLAMA] Installing via Homebrew...")
            proc = await asyncio.create_subprocess_exec(
                "brew", "install", "ollama",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                print("[OLLAMA] Installed via Homebrew.")
                return True
        # Fallback: official install script (requires sudo — opens auth dialog automatically)
        print("[OLLAMA] Trying official install script (may request admin password)...")
        proc = await asyncio.create_subprocess_shell(
            "curl -fsSL https://ollama.com/install.sh | sh",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        stdout, _ = await proc.communicate()
        print(f"[OLLAMA] Install output: {stdout.decode()[-500:]}")
        return proc.returncode == 0

    elif system == "Windows":
        # Download and run OllamaSetup.exe silently
        import tempfile
        installer_url = "https://ollama.com/download/OllamaSetup.exe"
        installer_path = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")
        print(f"[OLLAMA] Downloading installer from {installer_url}...")
        try:
            urllib.request.urlretrieve(installer_url, installer_path)
            print("[OLLAMA] Running installer (UAC dialog may appear)...")
            subprocess.run([installer_path, "/S"], check=True)  # /S = silent mode
            return True
        except Exception as e:
            print(f"[OLLAMA] Windows install failed: {e}")
            return False

    elif system == "Linux":
        proc = await asyncio.create_subprocess_shell(
            "curl -fsSL https://ollama.com/install.sh | sh",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        stdout, _ = await proc.communicate()
        return proc.returncode == 0

    return False


def is_model_pulled(model_name: str) -> bool:
    """Check if a model is already downloaded."""
    try:
        req = urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        data = json.loads(req.read())
        models = [m["name"] for m in data.get("models", [])]
        # Match prefix (e.g. "qwen2.5:7b" matches "qwen2.5:7b")
        return any(m.startswith(model_name.split(":")[0]) and model_name.split(":")[1] in m
                   for m in models) if ":" in model_name else any(m.startswith(model_name) for m in models)
    except Exception:
        return False


async def pull_model(model_name: str, on_progress=None):
    """Pulls a model from Ollama registry with streaming progress."""
    print(f"[OLLAMA] Pulling model: {model_name}")
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_BASE_URL}/api/pull",
                json={"name": model_name, "stream": True},
                timeout=aiohttp.ClientTimeout(total=7200)  # 2hr max
            ) as resp:
                async for line in resp.content:
                    if line:
                        try:
                            data = json.loads(line)
                            status = data.get("status", "")
                            total = data.get("total", 0)
                            completed = data.get("completed", 0)
                            if total > 0:
                                pct = int(completed / total * 100)
                                if on_progress:
                                    on_progress(model_name, status, pct)
                            if status == "success":
                                print(f"[OLLAMA] Model {model_name} pulled successfully.")
                                return True
                        except Exception:
                            pass
    except Exception as e:
        print(f"[OLLAMA] Failed to pull {model_name}: {e}")
    return False


async def ensure_ready(model_type="chat", on_status=None) -> Optional[str]:
    """
    Full setup: installs Ollama if needed, starts server, pulls model.
    Returns the model name if ready, None if setup failed.
    on_status: callback(str) for status messages to show user
    """
    def status(msg):
        print(f"[OLLAMA] {msg}")
        if on_status:
            on_status(msg)

    ram_gb = get_ram_gb()
    status(f"RAM detected: {ram_gb:.1f} GB")

    # 1. Select model
    model = get_chat_model() if model_type == "chat" else get_code_model()
    if not model:
        status(f"Insufficient RAM ({ram_gb:.1f}GB) for any local model. Need at least 6GB.")
        return None

    status(f"Selected model: {model} (for {ram_gb:.1f}GB RAM)")

    # 2. Install Ollama if missing
    if not is_ollama_installed():
        status("Ollama not found. Installing...")
        ok = await install_ollama()
        if not ok or not is_ollama_installed():
            status("Ollama installation failed.")
            return None
        status("Ollama installed.")

    # 3. Start service
    ok = await start_ollama_service()
    if not ok:
        status("Could not start Ollama service.")
        return None

    # 4. Pull model if not present
    if not is_model_pulled(model):
        status(f"Downloading {model} (this may take a while for first run)...")
        ok = await pull_model(model, on_progress=lambda m, s, p: status(f"Pulling {m}: {s} {p}%"))
        if not ok:
            status(f"Failed to pull {model}.")
            return None

    status(f"Local model ready: {model}")
    return model


# ── Ollama API Calls ───────────────────────────────────────────────────────────

async def chat(model: str, messages: list, tools: list = None, stream: bool = False) -> dict:
    """
    Calls Ollama /api/chat. Returns the response message dict.
    Supports tool_calls for models that implement it (qwen2.5, llama3.1, etc.)
    """
    import aiohttp
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.7, "num_ctx": 8192}
    }
    if tools:
        payload["tools"] = tools

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                data = await resp.json()
                return data.get("message", {})
    except Exception as e:
        print(f"[OLLAMA] Chat error: {e}")
        return {}


async def generate_text(model: str, prompt: str, system: str = "") -> str:
    """Simple text generation for code tasks."""
    import aiohttp
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 8192}
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=180)
            ) as resp:
                data = await resp.json()
                return data.get("response", "")
    except Exception as e:
        print(f"[OLLAMA] Generate error: {e}")
        return ""
