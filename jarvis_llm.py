import os
import json
import httpx
import certifi
from dotenv import load_dotenv
load_dotenv()

# Fix SSL paths for PyInstaller bundle
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
_attempted_start = False

def _fallback_ollama(system: str, prompt: str) -> str:
    """Attempts to use a local Ollama model if Gemini fails."""
    try:
        # Discover available models
        resp = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        if not models:
            raise Exception("Ollama is running but no models are downloaded.")
            
        # Pick the best small model for fallback
        model_name = models[0]["name"]
        for m in models:
            name = m["name"].lower()
            if "llama3.2" in name or "qwen" in name or "gemma" in name or "phi" in name:
                model_name = m["name"]
                break
                
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }
        gen_resp = httpx.post("http://localhost:11434/api/chat", json=payload, timeout=120.0)
        gen_resp.raise_for_status()
        result = gen_resp.json()["message"]["content"].strip()
        try:
            from jarvis_failure_store import record_success
            record_success("ollama")
        except Exception:
            pass
        return result
    except Exception as e:
        print(f"  ❌ Ollama Fallback Error: {e}", flush=True)
        try:
            from jarvis_failure_store import record_failure
            record_failure("ollama", str(e)[:120], severity="high")
        except Exception:
            pass
        return ""

def ask_llm(prompt: str, system: str = "", max_tokens: int = 200, temperature: float = 0.2, model_type: str = "smart") -> str:
    """
    Attempts Gemini API first. On failure, falls back to Ollama.
    Returns an empty string if all fail.
    """
    global _attempted_start
    key = os.environ.get("JARVIS_GEMINI_KEY", "")
    
    if key:
        try:
            g_resp = httpx.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": f"{system}\n\n{prompt}"}]}]},
                timeout=60.0,
            )
            g_resp.raise_for_status()
            result = g_resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            try:
                from jarvis_failure_store import record_success
                record_success("gemini")
            except Exception:
                pass
            return result
        except Exception as e:
            print(f"  ❌ Gemini API Error: {e}. Falling back to Ollama...", flush=True)
            try:
                from jarvis_failure_store import record_failure
                record_failure("gemini", str(e)[:120], severity="critical")
            except Exception:
                pass
            return _fallback_ollama(system, prompt)

    # If no key is set, go straight to fallback
    return _fallback_ollama(system, prompt)
