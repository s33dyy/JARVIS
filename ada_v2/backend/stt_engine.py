"""
stt_engine.py — Speech-to-Text using faster-whisper.
Used in the local Ollama fallback session when Gemini is unavailable.
"""
import asyncio
import io
import os
import numpy as np
from pathlib import Path
from typing import Optional

# Whisper model cache location
_WHISPER_MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", ".cache", "whisper")

_model = None
_model_size = None


def _get_model_size() -> str:
    """Pick whisper model size based on RAM."""
    try:
        from ollama_manager import get_stt_model
        return get_stt_model()
    except Exception:
        return "tiny"


def _load_model(size: str = None):
    global _model, _model_size
    if _model is not None and _model_size == size:
        return _model
    try:
        from faster_whisper import WhisperModel
        size = size or _get_model_size()
        print(f"[STT] Loading Whisper model: {size}")
        _model = WhisperModel(
            size,
            device="cpu",
            compute_type="int8",
            download_root=_WHISPER_MODEL_DIR
        )
        _model_size = size
        print(f"[STT] Whisper model loaded: {size}")
        return _model
    except ImportError:
        print("[STT] faster-whisper not installed. Run: pip install faster-whisper")
        return None
    except Exception as e:
        print(f"[STT] Failed to load Whisper model: {e}")
        return None


def pcm_to_float32(pcm_bytes: bytes, sample_rate: int = 16000) -> np.ndarray:
    """Convert raw 16-bit PCM bytes to float32 numpy array."""
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    audio = audio / 32768.0
    return audio


async def transcribe(audio_bytes: bytes, sample_rate: int = 16000, language: str = "en") -> str:
    """
    Transcribe raw PCM audio bytes to text.
    audio_bytes: raw 16-bit PCM at sample_rate Hz, mono
    Returns the transcribed string (empty string on failure).
    """
    model = await asyncio.to_thread(_load_model)
    if model is None:
        return ""

    if len(audio_bytes) < 2:
        return ""

    try:
        audio_array = pcm_to_float32(audio_bytes, sample_rate)

        # Run in thread to avoid blocking event loop
        def _run():
            segments, info = model.transcribe(
                audio_array,
                language=language,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            text = " ".join(seg.text.strip() for seg in segments)
            return text.strip()

        text = await asyncio.to_thread(_run)
        return text
    except Exception as e:
        print(f"[STT] Transcription error: {e}")
        return ""


def is_available() -> bool:
    """Check if faster-whisper is installed."""
    try:
        import faster_whisper
        return True
    except ImportError:
        return False
