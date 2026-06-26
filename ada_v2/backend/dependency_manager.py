"""
dependency_manager.py — Auto-installs missing Python deps + prompts for API keys.

Runs on startup. Checks all required packages. Silently pip-installs what's missing.
If API keys are empty, emits events to frontend to prompt user.
"""

import asyncio
import importlib
import os
import sys
from typing import Optional, Callable, Dict, List, Tuple

# Required packages: pip_name -> import_name
REQUIRED_PACKAGES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "python-socketio": "socketio",
    "python-multipart": "multipart",
    "google-genai": "google.genai",
    "opencv-python": "cv2",
    "pyaudio": "pyaudio",
    "pillow": "PIL",
    "mss": "mss",
    "playwright": "playwright",
    "python-kasa": "kasa",
    "python-dotenv": "dotenv",
    "mediapipe": "mediapipe",
    "build123d": "build123d",
    "aiohttp": "aiohttp",
    "psutil": "psutil",
}

# API keys that the system needs
REQUIRED_API_KEYS = {
    "gemini_api_key": {
        "env_var": "GEMINI_API_KEY",
        "description": "Google Gemini API key (required for voice + CAD)",
        "critical": True,
    },
    "openrouter_api_key": {
        "env_var": "OPENROUTER_API_KEY",
        "description": "OpenRouter API key (optional, cloud fallback)",
        "critical": False,
    },
}


class DependencyManager:
    """Checks and installs missing dependencies, validates API keys."""

    def __init__(self, settings: dict, emit_fn: Optional[Callable] = None):
        self.settings = settings
        self.emit = emit_fn
        self._missing_packages: List[str] = []
        self._missing_keys: Dict[str, str] = {}

    async def check_all(self) -> Dict:
        """
        Run full dependency check.
        Returns: {packages_ok, missing_packages, keys_ok, missing_keys}
        """
        self._missing_packages = self._check_packages()
        self._missing_keys = self._check_api_keys()

        result = {
            "packages_ok": len(self._missing_packages) == 0,
            "missing_packages": self._missing_packages,
            "keys_ok": len(self._missing_keys) == 0,
            "missing_keys": self._missing_keys,
        }

        if self.emit:
            self.emit("dependency_status", result)

        return result

    async def install_missing(self, on_progress: Optional[Callable] = None) -> Dict:
        """Install all missing packages silently in background."""
        if not self._missing_packages:
            self._missing_packages = self._check_packages()

        if not self._missing_packages:
            return {"success": True, "installed": [], "failed": []}

        installed = []
        failed = []

        for package in self._missing_packages:
            if on_progress:
                on_progress({"package": package, "status": "installing"})

            try:
                from code_executor import install_package
                result = await install_package(package, timeout=120)

                if result.get("success"):
                    installed.append(package)
                    if on_progress:
                        on_progress({"package": package, "status": "done"})
                else:
                    failed.append({"package": package, "error": result.get("stderr", "unknown")})
                    if on_progress:
                        on_progress({"package": package, "status": "failed"})
            except Exception as e:
                failed.append({"package": package, "error": str(e)})
                if on_progress:
                    on_progress({"package": package, "status": "failed"})

        return {
            "success": len(failed) == 0,
            "installed": installed,
            "failed": failed,
        }

    def _check_packages(self) -> List[str]:
        """Return list of pip package names that aren't importable."""
        missing = []
        for pip_name, import_name in REQUIRED_PACKAGES.items():
            try:
                importlib.import_module(import_name)
            except ImportError:
                missing.append(pip_name)
        return missing

    def _check_api_keys(self) -> Dict[str, str]:
        """Return dict of missing API keys with descriptions."""
        missing = {}
        for key_name, info in REQUIRED_API_KEYS.items():
            value = self.settings.get(key_name, "").strip()
            # Also check env var
            if not value:
                value = os.environ.get(info["env_var"], "").strip()
            if not value:
                missing[key_name] = info["description"]
        return missing

    def check_ollama(self) -> bool:
        """Check if Ollama is installed and running."""
        import subprocess
        try:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    async def ensure_ollama(self) -> bool:
        """Install and start Ollama if not available."""
        if self.check_ollama():
            print("[JARVIS] Ollama is already available")
            return True
        try:
            from ollama_manager import ensure_ready
            model = await ensure_ready()
            return model is not None
        except Exception as e:
            print(f"[JARVIS] Ollama auto-setup failed: {e}")
            return False

    def get_missing_keys_for_frontend(self) -> List[Dict]:
        """Return structured missing key info for frontend display."""
        keys = []
        for key_name, info in REQUIRED_API_KEYS.items():
            value = self.settings.get(key_name, "").strip()
            if not value:
                value = os.environ.get(info["env_var"], "").strip()
            keys.append({
                "key": key_name,
                "description": info["description"],
                "critical": info["critical"],
                "present": bool(value),
            })
        return keys


# Module-level singleton (initialized by server.py on startup)
_manager: Optional[DependencyManager] = None


def get_dependency_manager(settings: dict = None, emit_fn: Callable = None) -> DependencyManager:
    """Get or create the singleton DependencyManager."""
    global _manager
    if _manager is None:
        _manager = DependencyManager(settings or {}, emit_fn)
    return _manager


if __name__ == "__main__":
    async def test():
        dm = DependencyManager({})
        status = await dm.check_all()
        print(f"Packages OK: {status['packages_ok']}")
        print(f"Missing: {status['missing_packages']}")
        print(f"Keys OK: {status['keys_ok']}")
        print(f"Missing keys: {status['missing_keys']}")

    asyncio.run(test())
