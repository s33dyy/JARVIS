import os
import json
import httpx
import certifi
from dotenv import load_dotenv

# Fix SSL paths for PyInstaller bundle
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
_attempted_start = False

def ask_llm(prompt: str, system: str = "", max_tokens: int = 200, temperature: float = 0.2, model_type: str = "smart") -> str:
    """
    3-tier fallback LLM engine compatible with Mac and Windows.
    model_type can be 'smart' (qwen3.5:4b) or 'fast' (qwen3.5:0.8b).
    Tier 1: Local Ollama (cross-platform, fast)
    Tier 2: Local MLX (Apple Silicon only)
    Tier 3: Gemini (Cloud fallback)
    """
    global _attempted_start
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Tier 1 & 2 Removed per user request. ONLY GEMINI.
    key = os.environ.get("JARVIS_GEMINI_KEY", "AQ.Ab8RN6IbZKii5rOlU1ZR1Ib8w6uQddQ0BJibwPlIG5Z35MEOIg")
    
    if key:
        # print("  ☁️  Using Gemini API...", flush=True) # Silenced so it doesn't spam
        try:
            g_resp = httpx.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": f"{system}\n\n{prompt}"}]}]},
                timeout=60.0,
            )
            g_resp.raise_for_status()
            return g_resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            print(f"  ❌ Gemini API Error: {e}", flush=True)
            pass

    return ""

    return ""
