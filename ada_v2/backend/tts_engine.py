"""
tts_engine.py — Text-to-Speech using edge-tts (Microsoft Neural TTS, free, no API key).
Used in the local Ollama fallback session when Gemini is unavailable.
"""
import asyncio
import io
import struct
from typing import Optional

# Default female voice — close to Aoede in quality
DEFAULT_VOICE = "en-US-AriaNeural"

# Map of Gemini voice names → edge-tts equivalents
VOICE_MAP = {
    "Aoede":   "en-US-AriaNeural",
    "Puck":    "en-US-GuyNeural",
    "Charon":  "en-US-ChristopherNeural",
    "Kore":    "en-US-JennyNeural",
    "Fenrir":  "en-US-EricNeural",
    "Leda":    "en-US-AnaNeural",
    "Orus":    "en-US-AndrewNeural",
    "Zephyr":  "en-US-BrianNeural",
}

# Output format matching the Gemini audio output (24kHz, 16-bit, mono PCM)
RECEIVE_SAMPLE_RATE = 24000


def get_edge_voice(gemini_voice_name: str = "Aoede") -> str:
    return VOICE_MAP.get(gemini_voice_name, DEFAULT_VOICE)


async def synthesize_to_pcm(text: str, voice: str = None, rate: str = "+0%", volume: str = "+0%") -> Optional[bytes]:
    """
    Synthesize text to raw PCM bytes (16-bit, 24kHz, mono).
    Returns None on failure.
    """
    if not text or not text.strip():
        return None

    try:
        import edge_tts
    except ImportError:
        print("[TTS] edge-tts not installed. Run: pip install edge-tts")
        return None

    voice = voice or DEFAULT_VOICE

    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)

        # edge-tts outputs MP3 by default — collect all audio data
        mp3_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_chunks.append(chunk["data"])

        if not mp3_chunks:
            return None

        mp3_bytes = b"".join(mp3_chunks)

        # Convert MP3 → PCM using pydub (or fallback to raw bytes if unavailable)
        pcm_bytes = _mp3_to_pcm(mp3_bytes, target_sr=RECEIVE_SAMPLE_RATE)
        return pcm_bytes

    except Exception as e:
        print(f"[TTS] Synthesis error: {e}")
        return None


def _mp3_to_pcm(mp3_bytes: bytes, target_sr: int = 24000) -> bytes:
    """Convert MP3 bytes to 16-bit mono PCM at target_sr."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        audio = audio.set_frame_rate(target_sr).set_channels(1).set_sample_width(2)
        return audio.raw_data
    except ImportError:
        # pydub not available — try soundfile via ffmpeg
        try:
            import soundfile as sf
            import subprocess
            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(mp3_bytes)
                mp3_path = f.name
            wav_path = mp3_path.replace(".mp3", ".wav")
            subprocess.run(
                ["ffmpeg", "-y", "-i", mp3_path, "-ar", str(target_sr), "-ac", "1", "-f", "s16le", wav_path],
                check=True, capture_output=True
            )
            with open(wav_path, "rb") as f:
                pcm = f.read()
            os.unlink(mp3_path)
            os.unlink(wav_path)
            return pcm
        except Exception as e2:
            print(f"[TTS] PCM conversion failed ({e2}). Returning raw MP3.")
            return mp3_bytes


def is_available() -> bool:
    """Check if edge-tts is installed."""
    try:
        import edge_tts
        return True
    except ImportError:
        return False
