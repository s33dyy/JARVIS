import os
import sys
import httpx
sys.path.append("/Users/pratikchoudhuri/Documents/antigravity/goofy-bose/OpenJarvis")
from jarvis_todoist import get_tasks
from jarvis_llm import ask_llm

print("Checking key:", os.environ.get("JARVIS_GEMINI_KEY", "NOT SET"))
try:
    key = os.environ.get("JARVIS_GEMINI_KEY", "")
    if key:
        g_resp = httpx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": "Hello"}]}]},
            timeout=15.0,
        )
        print("Status:", g_resp.status_code)
        print("Text:", g_resp.text)
    else:
        print("No key set in environment.")
except Exception as e:
    print("Error:", e)
