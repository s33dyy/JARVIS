"""
jarvis_speak.py
---------------
Centralized thread-safe speech engine for JARVIS.
Queues speech requests and processes them sequentially to prevent overlaps.
"""

import subprocess
import threading
import queue
import time

_speech_queue: queue.Queue = queue.Queue()
_speak_thread: threading.Thread = None
_lock = threading.Lock()

_say_lock = threading.Lock()

def _speak_loop():
    """Background loop that processes speech sequentially."""
    while True:
        try:
            text = _speech_queue.get()
            if text is None:
                break
            
            clean = text.replace('"', "'").strip()
            if clean:
                try:
                    # subprocess.run blocks this worker thread until speaking is complete,
                    # ensuring sequential playback without overlays.
                    with _say_lock:
                        subprocess.run(["say", clean], check=False)
                except FileNotFoundError:
                    # Fallback for non-macOS or missing 'say' command
                    print(f"[speak] (say unavailable) Spoken: {clean}")
            _speech_queue.task_done()
        except Exception as exc:
            print(f"[speak] Speech engine error: {exc}")

def start_speech_engine():
    """Start the background speech daemon if not already running."""
    global _speak_thread
    with _lock:
        if _speak_thread is not None and _speak_thread.is_alive():
            return
        
        _speak_thread = threading.Thread(target=_speak_loop, name="JARVISSpeechEngine", daemon=True)
        _speak_thread.start()

def speak(text: str, interrupt: bool = False) -> None:
    """
    Queue text to be spoken sequentially by the background speech engine.
    If interrupt is True, it clears the current queue to prioritize this message.
    """
    start_speech_engine()
    
    if interrupt:
        # Drain the current queue
        try:
            while True:
                _speech_queue.get_nowait()
                _speech_queue.task_done()
        except queue.Empty:
            pass
            
    _speech_queue.put(text)

def speak_block(text: str) -> None:
    """Speak text synchronously (blocks calling thread)."""
    clean = text.replace('"', "'").strip()
    if clean:
        try:
            with _say_lock:
                subprocess.run(["say", clean], check=False)
        except FileNotFoundError:
            print(f"[speak_block] (say unavailable) Spoken: {clean}")

# Auto-start speech engine on import
start_speech_engine()
