import os, httpx
key = os.environ.get("JARVIS_GEMINI_KEY", "")
resp = httpx.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
for m in resp.json().get("models", []):
    print(m["name"])
