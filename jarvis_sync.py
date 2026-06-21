"""
jarvis_sync.py
--------------
Multi-device sync module for JARVIS using iCloud Drive.

JARVIS state is stored in:
  ~/Library/Mobile Documents/com~apple~CloudDocs/JARVIS/

This folder is automatically synced across all Macs signed into the same
Apple ID, giving JARVIS memory continuity without any third-party service.

If iCloud Drive is unavailable, the module falls back to ~/.jarvis/.
"""

import shutil
import threading
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Directory resolution
# ---------------------------------------------------------------------------

_ICLOUD_BASE = (
    Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
)
_ICLOUD_JARVIS = _ICLOUD_BASE / "JARVIS"
_LOCAL_FALLBACK = Path.home() / ".jarvis"


def get_sync_dir() -> Path:
    """
    Return the JARVIS sync directory, creating it if necessary.

    Tries iCloud Drive first; falls back to ~/.jarvis/ when iCloud is not
    available on this system.

    Returns
    -------
    Path
        Absolute path to the sync directory (guaranteed to exist).
    """
    # Prefer iCloud if the base path already exists (iCloud Drive is mounted).
    if _ICLOUD_BASE.exists():
        try:
            _ICLOUD_JARVIS.mkdir(parents=True, exist_ok=True)
            return _ICLOUD_JARVIS
        except OSError:
            pass  # Fall through to local fallback

    # iCloud Drive is not available — use local directory.
    _LOCAL_FALLBACK.mkdir(parents=True, exist_ok=True)
    return _LOCAL_FALLBACK


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------

def _local_memory_path() -> Path:
    """Return the canonical path to the local JARVIS memory file."""
    return Path.home() / ".jarvis" / "memory.json"


def sync_memory() -> str:
    """
    Copy ~/.jarvis/memory.json into the iCloud sync directory.

    Returns
    -------
    str
        Confirmation or error message.
    """
    src = _local_memory_path()

    if not src.exists():
        return "No memory file found at ~/.jarvis/memory.json — nothing to sync, sir."

    try:
        dest_dir = get_sync_dir()
        dest = dest_dir / "memory.json"
        shutil.copy2(src, dest)
        return "Memory synced to iCloud, sir."
    except Exception as exc:
        return f"Failed to sync memory: {exc}"


def sync_obsidian_tasks() -> str:
    """
    Report whether the Obsidian vault is already inside iCloud Drive.

    The vault is expected at ~/Documents/Obsidian Vault/.  On Macs with
    iCloud Desktop & Documents enabled, ~/Documents/ maps to
    ~/Library/Mobile Documents/com~apple~CloudDocs/Documents/ and syncs
    automatically.

    Returns
    -------
    str
        Human-readable sync status.
    """
    # Common vault locations
    candidate_paths = [
        Path.home() / "Documents" / "Obsidian Vault",
        _ICLOUD_BASE / "Documents" / "Obsidian Vault",
    ]

    for path in candidate_paths:
        if path.exists():
            # Determine whether it is inside iCloud Drive
            try:
                path.relative_to(_ICLOUD_BASE)
                return (
                    f"Obsidian Vault is inside iCloud Drive and syncing automatically, sir. "
                    f"({path})"
                )
            except ValueError:
                pass  # Not under iCloud — check next candidate

    # Vault found locally but outside iCloud
    local_vault = Path.home() / "Documents" / "Obsidian Vault"
    if local_vault.exists():
        return (
            "Obsidian Vault exists locally but is NOT inside iCloud Drive. "
            "Enable 'iCloud Drive → Desktop & Documents Folders' in System Settings "
            "to sync it automatically, sir."
        )

    return (
        "Obsidian Vault not found at ~/Documents/Obsidian Vault/. "
        "Please verify the vault location, sir."
    )


def get_sync_status() -> str:
    """
    Return a one-line status summary of the JARVIS sync directory.

    Returns
    -------
    str
        Status string in the format:
        "Sync dir: {path} | Memory: {size}KB | Last sync: {time}"
    """
    sync_dir = get_sync_dir()
    memory_file = sync_dir / "memory.json"

    if memory_file.exists():
        size_kb = round(memory_file.stat().st_size / 1024, 2)
        mtime = datetime.fromtimestamp(memory_file.stat().st_mtime)
        last_sync = mtime.strftime("%Y-%m-%d %H:%M:%S")
    else:
        size_kb = 0.0
        last_sync = "never"

    return (
        f"Sync dir: {sync_dir} | "
        f"Memory: {size_kb}KB | "
        f"Last sync: {last_sync}"
    )


# ---------------------------------------------------------------------------
# Background sync loop
# ---------------------------------------------------------------------------

_sync_thread: threading.Thread | None = None
_stop_event = threading.Event()


def start_sync_loop(interval_seconds: int = 300) -> None:
    """
    Start a background daemon thread that syncs memory every *interval_seconds*.

    Safe to call multiple times — if a sync thread is already running it will
    not start a second one.

    Parameters
    ----------
    interval_seconds : int
        Seconds between each sync cycle (default 300 = 5 minutes).
    """
    global _sync_thread

    if _sync_thread is not None and _sync_thread.is_alive():
        # Already running; nothing to do.
        return

    _stop_event.clear()

    def _loop() -> None:
        while not _stop_event.wait(timeout=interval_seconds):
            result = sync_memory()
            print(f"[Sync] {result}")

    _sync_thread = threading.Thread(target=_loop, name="jarvis-sync", daemon=True)
    _sync_thread.start()


def stop_sync_loop() -> None:
    """Signal the background sync thread to stop after the current sleep."""
    _stop_event.set()


def start() -> None:
    """
    Entry point: start the background iCloud sync loop with the default interval.

    Called automatically when JARVIS boots.
    """
    start_sync_loop()


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Sync dir :", get_sync_dir())
    print(sync_obsidian_tasks())
    print(get_sync_status())
    print("Starting sync loop (5-second interval for demo)…")
    start_sync_loop(interval_seconds=5)
    time.sleep(12)
    stop_sync_loop()
    print("Sync loop stopped.")
