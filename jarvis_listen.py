#!/usr/bin/env python3
"""
JARVIS Always-On Voice Listener
────────────────────────────────
Runs 24/7. Say "Hey JARVIS" → it listens → transcribes → runs the full
OpenJarvis orchestrator (with tools: web search, code, shell) → speaks back.

Usage:
  uv run python jarvis_listen.py
  uv run python jarvis_listen.py --sensitivity 0.6
  uv run python jarvis_listen.py --whisper-model small
"""

import argparse
import collections
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
import os
from pathlib import Path

import httpx
import numpy as np
import sounddevice as sd

# Action engine (calendar, reminders, Google, filesystem)
try:
    from jarvis_actions import handle_action
except ImportError:
    def handle_action(q, p): return "", {}

# Context engine (local FS + Google Calendar/Gmail snapshot)
try:
    from jarvis_context import build_context, warm_up
    _context_available = True
except ImportError:
    _context_available = False
    def build_context(**kw): return ""
    def warm_up(): pass

# ── Optional imports ──────────────────────────────────────────
try:
    from faster_whisper import WhisperModel
except ImportError:
    print("❌  Run: uv pip install faster-whisper")
    sys.exit(1)

try:
    import openwakeword
    from openwakeword.model import Model as WakeWordModel
except ImportError:
    print("❌  Run: uv pip install openwakeword")
    sys.exit(1)

# ── Audio constants ───────────────────────────────────────────
SAMPLE_RATE       = 16000
CHUNK_MS          = 80
CHUNK_SIZE        = int(SAMPLE_RATE * CHUNK_MS / 1000)
RECORD_SECONDS    = 10
SILENCE_THRESHOLD = 250    # RMS; lower = more sensitive to quiet speech
SILENCE_CHUNKS    = 10     # ~0.8s silence → stop recording
WAKE_WORDS        = ["hey_jarvis"]

# ── JARVIS persona ───────────────────────────────────────────
JARVIS_SYSTEM = (
    "You are JARVIS — Just A Rather Very Intelligent System — Tony Stark's AI. "
    "You are witty, precise, British-accented, and always address your user as 'sir'. "
    "You have full access to the user's Google Calendar, Gmail, Google Drive, "
    "local filesystem, and can schedule meetings, read/send emails, search files. "
    "When context is provided, USE IT — the user expects you to know what's on their "
    "calendar, what emails they have, and what they're working on. "
    "Keep voice responses concise (2-4 sentences max). Never say you cannot do something."
)


# ─────────────────────────────────────────────────────────────
# TTS
# ─────────────────────────────────────────────────────────────
def speak(text: str, block: bool = False) -> None:
    import jarvis_speak
    if block:
        jarvis_speak.speak_block(text)
    else:
        jarvis_speak.speak(text)



# ─────────────────────────────────────────────────────────────
# Ask JARVIS — routes through the full OpenJarvis CLI
# (orchestrator agent with web_search, shell_exec, file_read, etc.)
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# Data fetchers — get REAL data before calling the model
# ─────────────────────────────────────────────────────────────

def _get_datetime() -> str:
    try:
        return subprocess.check_output(
            ["date", "+%A, %d %B %Y — %I:%M %p %Z"], text=True
        ).strip()
    except Exception:
        return ""


def _web_search(query: str, max_results: int = 4) -> str:
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(f"- {r.get('title','')}: {r.get('body','')[:200]}")
        return "\n".join(results) if results else ""
    except Exception:
        return ""


def _derepeat(text: str) -> str:
    """Cut off output at the first sign of word/phrase repetition."""
    if not text:
        return text
    words = text.split()
    # Detect 4-word phrase repeated 2+ times
    for window in (4, 3, 2):
        for i in range(len(words) - window * 2 + 1):
            phrase = " ".join(words[i:i+window])
            rest   = " ".join(words[i+window:])
            if rest.startswith(phrase):
                # Cut here — return everything up to the first repeat
                return " ".join(words[:i+window]).rstrip(".,;: ")
    # Detect single word repeated 4+ times in a row
    for i in range(len(words) - 3):
        if words[i] == words[i+1] == words[i+2] == words[i+3]:
            return " ".join(words[:i]).rstrip(".,;: ")
    return text


def ask_jarvis(question: str, jarvis_dir: str) -> str:
    """
    Build a tight prompt with compact personal context, send to MLX,
    detect repetition in output and truncate cleanly.
    3-tier fallback: MLX → Gemini Flash → cached response.
    """
    q       = question.lower()
    now_str = _get_datetime()

    # ── Compact context (safe for 0.6B) ──────────────────────
    try:
        from jarvis_context import build_short_context
        short_ctx = build_short_context()
    except Exception:
        short_ctx = f"Now: {now_str}"

    # ── Persistent memory context ─────────────────────────────
    mem_ctx = ""
    try:
        from jarvis_memory import get_memory_context
        mem_ctx = get_memory_context()
    except Exception:
        pass

    intent = "general"

    # ── Intent routing with minimal augmentation ──────────────
    if re.search(r"\b(morning brief|briefing|digest|news|headline)\b", q):
        intent = "brief"
        news = _web_search("top news today 2026", max_results=2)
        news_snippet = news[:300] if news else "no news fetched"
        prompt = (
            f"{short_ctx}\n"
            f"News: {news_snippet}\n\n"
            f"Give a 3-point spoken morning brief. Be sharp and short. Sir."
        )

    elif re.search(r"\b(time|date|day|today|what day|what time|clock)\b", q):
        intent = "datetime"
        prompt = f"{short_ctx}\n\nUser: {question}\nAnswer in one sentence."

    elif re.search(r"\b(weather|temperature|forecast|rain|sunny)\b", q):
        intent = "weather"
        results = _web_search(f"weather today {question}")[:200]
        prompt = f"{short_ctx}\nWeather: {results}\n\nUser: {question}\nAnswer in one sentence."

    elif re.search(r"\b(who is|what is|latest|search|look up|tell me about|when did)\b", q):
        intent = "search"
        results = _web_search(question)[:300]
        prompt = f"Facts: {results}\n\nUser: {question}\nAnswer in 1-2 sentences."

    else:
        prompt = f"{short_ctx}\n{mem_ctx}\n\nUser: {question}\nReply in 1-2 sentences, address as sir."

    if intent != "general":
        print(f"  🔧  {intent}", flush=True)

    # ── Behavioral Mirroring (Persona Injection) ──
    try:
        from jarvis_crm import get_crm_summary
        crm_state = get_crm_summary()
    except Exception:
        crm_state = ""

    try:
        from jarvis_todoist import get_tasks
        overdue_tasks = len(get_tasks(filter_query="overdue"))
        open_today = len(get_tasks(filter_query="today"))
        if overdue_tasks > 3:
            todoist_mood = "The user is currently behind schedule and potentially overwhelmed. Be extra concise, encouraging, and break things down."
        elif open_today > 5:
            todoist_mood = "The user has a busy day ahead. Keep responses snappy."
        elif open_today == 0:
            todoist_mood = "The user has cleared their tasks for today! Be relaxed and cheerful."
        else:
            todoist_mood = "The user is on track."
    except Exception:
        todoist_mood = ""

    system = (
        "You are JARVIS, Tony Stark's AI, acting as an ADHD coach for the user. British, witty, concise. "
        "Always address user as 'sir'. Break tasks into tiny 15-minute micro-steps to prevent overwhelm. "
        "IMPORTANT: If the user asks for heavy work after 5 PM, gently suggest doing it tomorrow. "
        "Max 2 sentences. Never repeat words. Do NOT hallucinate.\n\n"
        "User's current state based on recent CRM/Messages:\n"
        f"{crm_state}\n\n"
        "User's current task load:\n"
        f"{todoist_mood}"
    )

    def _clean(txt: str) -> str:
        txt = re.sub(r"\*\*(.+?)\*\*", r"\1", txt)
        txt = re.sub(r"\*(.+?)\*",     r"\1", txt)
        txt = re.sub(r"#+\s*",         "",    txt)
        txt = re.sub(r"\n+",           " ",   txt)
        return _derepeat(txt)

    from jarvis_llm import ask_llm
    answer = ask_llm(prompt[:600], system=system, max_tokens=80, temperature=0.5, model_type="fast")
    if answer:
        answer = _clean(answer)
    # Tier 3: Offline canned response
    if not answer:
        print("  ⚠️  All LLMs offline — using offline response.", flush=True)
        answer = "I'm currently offline, sir. My language model is unreachable."

    # Save to persistent memory
    try:
        from jarvis_memory import add_exchange, extract_and_save_facts
        add_exchange(question, answer)
        extract_and_save_facts(question, answer)
    except Exception:
        pass

    return answer or "Ready and standing by, sir."




# ─────────────────────────────────────────────────────────────
# Recording
# ─────────────────────────────────────────────────────────────
def record_question(continuous: bool = False) -> np.ndarray | None:
    if not continuous:
        print("  🎙️  Listening for your question...", flush=True)
        speak("Yes, sir?", block=True)
    else:
        print("  🎧  Listening... (start speaking)", flush=True)

    frames: list[np.ndarray] = []
    silence_count = 0
    max_chunks = int(RECORD_SECONDS * 1000 / CHUNK_MS)
    got_speech = False
    chunks_processed = 0

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                        dtype="int16", blocksize=CHUNK_SIZE) as stream:
        while True:
            chunk, _ = stream.read(CHUNK_SIZE)
            chunks_processed += 1
            rms = np.sqrt(np.mean(chunk.astype(np.float32) ** 2))
            
            # If we haven't heard anything yet, and we are not in continuous mode, we might time out
            if not got_speech and not continuous and chunks_processed >= max_chunks:
                break
                
            # If we are accumulating speech, check max_chunks length limit so we don't record forever
            if got_speech and len(frames) >= max_chunks * 2: # 20 seconds max recording length
                break

            # Only append to frames once speech starts to avoid saving a giant silence buffer in continuous mode
            if got_speech or rms >= SILENCE_THRESHOLD:
                frames.append(chunk.copy())

            if rms >= SILENCE_THRESHOLD:
                got_speech = True
                silence_count = 0
            else:
                if got_speech:
                    silence_count += 1
                    if silence_count >= SILENCE_CHUNKS:
                        break

    if not frames or not got_speech:
        return None
    return np.concatenate(frames, axis=0).flatten()


# ─────────────────────────────────────────────────────────────
# Transcription
# ─────────────────────────────────────────────────────────────
def transcribe(audio: np.ndarray, model: WhisperModel) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    segments, _ = model.transcribe(path, language="en")
    text = " ".join(seg.text for seg in segments).strip()
    Path(path).unlink(missing_ok=True)
    return text


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS always-on voice listener")
    parser.add_argument("--sensitivity", type=float, default=0.4,
                        help="Wake word sensitivity 0.0-1.0 (default 0.4)")
    parser.add_argument("--whisper-model", default="small.en",
                        help="Whisper model: tiny / base / small.en / medium.en (default small.en)")
    parser.add_argument("--continuous", action="store_true",
                        help="Enable continuous conversation mode (no wake word)")
    # We parse sys.argv, but ignore unknown args so the UI can pass its own flags
    args, _ = parser.parse_known_args()

    jarvis_dir = str(Path(__file__).parent)

    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║   JARVIS  —  Always-On Listener      ║")
    print("  ╚══════════════════════════════════════╝")
    print(f"  Wake word  : {'None (Continuous)' if args.continuous else 'Hey JARVIS'}")
    print(f"  Sensitivity: {args.sensitivity}")
    print(f"  Agent      : orchestrator + Google + local FS")
    print(f"  Whisper    : {args.whisper_model}")
    print()

    # ── Load Whisper ──────────────────────────────────────────
    print(f"  📥  Loading Whisper ({args.whisper_model})...", end=" ", flush=True)
    whisper = WhisperModel(args.whisper_model, device="cpu", compute_type="int8")
    print("✅  ready")

    # ── Load wake word model ──────────────────────────────────
    print("  📥  Loading wake word model...", end=" ", flush=True)
    openwakeword.utils.download_models()
    ww_model = WakeWordModel(wakeword_models=WAKE_WORDS, inference_framework="onnx")
    print("✅  ready")

    # ── Warm up context in background ────────────────────────
    print("  🔍  Building personal context (filesystem + calendar)...", end=" ", flush=True)
    warm_up()
    print("background ✅")

    # ── Google connection status ──────────────────────────────
    try:
        from jarvis_google import is_connected
        google_status = "✅ connected" if is_connected() else "⚠️  not connected (run: jarvis connect gdrive)"
    except Exception:
        google_status = "⚠️  module not loaded"
    print(f"  🔗  Google: {google_status}")

    # ── Start Autonomous Agent ─────────────────────────────────
    print("  🤖  Starting proactive background agent...", end=" ", flush=True)
    try:
        import jarvis_autonomous
        jarvis_autonomous.start()
        print("✅  running")
    except Exception as e:
        print(f"⚠️  failed ({e})")

    # ── Start Proactive Meeting Reminders ──────────────────────
    print("  🔔  Starting meeting reminder engine...", end=" ", flush=True)
    try:
        import jarvis_reminders
        jarvis_reminders.start()
        print("✅  running")
    except Exception as e:
        print(f"⚠️  failed ({e})")

    # ── Load Persistent Memory ─────────────────────────────────
    print("  🧠  Loading persistent memory...", end=" ", flush=True)
    try:
        import jarvis_memory
        facts = jarvis_memory.load().get("facts", {})
        print(f"✅  {len(jarvis_memory.get_recent_exchanges())} exchanges recalled")
    except Exception as e:
        print(f"⚠️  failed ({e})")

    # ── Start iCloud Sync ──────────────────────────────────────
    print("  ☁️   Starting iCloud sync...", end=" ", flush=True)
    try:
        import jarvis_sync
        jarvis_sync.start()
        print("✅  running")
    except Exception as e:
        print(f"⚠️  failed ({e})")

    # ── Start Auto-CRM ─────────────────────────────────────────
    print("  🗂️   Starting Auto-CRM engine...", end=" ", flush=True)
    try:
        import jarvis_crm
        jarvis_crm.start_auto_crm()
        print("✅  running")
    except Exception as e:
        print(f"⚠️  failed ({e})")

    # ── Morning Briefing ───────────────────────────────────────
    def run_morning_briefing():
        from datetime import datetime
        now = datetime.now()
        if 6 <= now.hour <= 11:
            try:
                tasks = []
                task_str = " and ".join(tasks) if tasks else "no immediate tasks"
                
                meeting_str = ""
                try:
                    import jarvis_google
                    if jarvis_google.is_connected():
                        events, _ = jarvis_google.get_events()
                        if events:
                            meeting_str = f" Your first meeting is '{events[0]['title']}'."
                except Exception:
                    pass
                    
                speak(f"Good morning, sir. Today we need to focus on {task_str}.{meeting_str} Let's crush it.", block=False)
            except Exception as e:
                print(f"[Briefing] Error: {e}")
                
    run_morning_briefing()


    # ── Multi-turn state ─────────
    pending_state: dict = {}

    def handle(pending=pending_state, continuous_mode=False):
        nonlocal pending_state
        try:
            audio = record_question(continuous=continuous_mode)
            if audio is None:
                if not continuous_mode:
                    speak("I didn't catch that, sir.", block=True)
                return None

            print("  🔄  Transcribing...", flush=True)
            question = transcribe(audio, whisper)
            
            # Clean punctuation and check for common Whisper hallucinations on silence
            clean_q = re.sub(r'[^a-zA-Z0-9\s]', '', question if question else '').strip().lower()
            hallucinations = {
                "what are you waiting for", "you", "thank you", "thanks for watching", 
                "subscribe to my channel", "thanks", "bye", "okay", "yeah", "subscribe",
                "thank you very much", "please subscribe", "watch this video"
            }
            
            if not clean_q or clean_q in hallucinations:
                print("  [Ignored Background Noise / Silence]", flush=True)
                return None

            print(f"  👤  You: \"{question}\"", flush=True)
            q_lower = question.lower()
            
            # ── System Overrides (Kill / Sleep / Continuous) ──
            if re.search(r"\b(shut down|turn off|kill jarvis|exit|quit|goodbye)\b", q_lower):
                try:
                    import jarvis_todoist
                    pending = len(jarvis_todoist.get_tasks(filter_query="today | overdue"))
                    speak(f"Shutting down, sir. You have {pending} tasks pending for today. Rest well.", block=True)
                except Exception:
                    speak("Shutting down, sir. Rest well.", block=True)
                os._exit(0)
                
            if continuous_mode and re.search(r"\b(go to sleep|stop listening|pause|standby)\b", q_lower):
                speak("Entering standby mode, sir. Say 'Hey Jarvis' to wake me.", block=True)
                return "EXIT_CONTINUOUS"
                
            if not continuous_mode and re.search(r"\b(keep listening|conversation mode|continuous mode|don't stop listening)\b", q_lower):
                speak("Continuous mode activated, sir.", block=True)
                return "ENTER_CONTINUOUS"

            # ── Try action engine first ───────
            action_response, new_pending = handle_action(question, pending)
            if action_response:
                pending_state = new_pending
                print(f"  ✅  Action: \"{action_response}\"", flush=True)
                speak(action_response, block=True)
                return None

            # ── Fall back to LLM for general queries ──
            print("  🤖  Thinking...", flush=True)
            answer = ask_jarvis(question, jarvis_dir)
            print(f"  🤖  JARVIS: \"{answer}\"", flush=True)
            speak(answer, block=True)

        finally:
            if not continuous_mode:
                time.sleep(2)
                cooldown.clear()
                print("\n  ✨  Listening... (say 'Hey JARVIS')\n", flush=True)

        return None

    is_continuous = args.continuous
    
    try:
        print()
        if is_continuous:
            speak("JARVIS continuous conversation mode activated, sir.", block=False)
        else:
            print("  ✨  Say 'Hey JARVIS' to wake me up. Press Ctrl+C to stop.")
            speak("JARVIS is online and listening, sir.", block=False)
        print()

        # ── Mic callback + main loop ──────────────────────────────
        audio_q: collections.deque[np.ndarray] = collections.deque(maxlen=10)
        lock = threading.Lock()
        cooldown = threading.Event()

        def mic_callback(indata, frames, time_info, status):
            with lock:
                audio_q.append(indata[:, 0].copy())

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                            dtype="int16", blocksize=CHUNK_SIZE,
                            callback=mic_callback):
            while True:
                if is_continuous:
                    res = handle(continuous_mode=True)
                    if res == "EXIT_CONTINUOUS":
                        is_continuous = False
                        print("\n  ✨  Say 'Hey JARVIS' to wake me up. Press Ctrl+C to stop.\n")
                    continue

                time.sleep(CHUNK_MS / 1000)

                chunks_to_process = []
                with lock:
                    while audio_q:
                        chunks_to_process.append(audio_q.popleft())

                for chunk in chunks_to_process:
                    predictions = ww_model.predict(chunk)
                    triggered = any(s >= args.sensitivity for s in predictions.values())

                    if triggered and not cooldown.is_set():
                        cooldown.set()
                        print("  🔔  Wake word detected!", flush=True)
                        with lock:
                            audio_q.clear()
                        res = handle(continuous_mode=False)
                        if res == "ENTER_CONTINUOUS":
                            is_continuous = True
                        with lock:
                            audio_q.clear()
                        break


    except KeyboardInterrupt:
        print("\n\n  👋  JARVIS listener stopped. Goodbye, sir.\n")
        try:
            pending = 0
            speak(f"Shutting down, sir. You have {pending} tasks pending for tomorrow. Rest well, you earned it.", block=True)
        except Exception:
            speak("Shutting down, sir. Rest well.", block=True)


if __name__ == "__main__":
    main()
