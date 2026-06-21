import os
import sys
import httpx

key = os.environ.get("JARVIS_GEMINI_KEY", "")
print("Key:", key[:5])
try:
    g_resp = httpx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": "Hello"}]}]},
        timeout=15.0,
    )
    print("Status:", g_resp.status_code)
    print("Text:", g_resp.text)
except Exception as e:
    print("Error:", e)
