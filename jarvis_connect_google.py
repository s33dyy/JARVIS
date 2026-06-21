#!/usr/bin/env python3
"""
JARVIS Google Connect — one-shot OAuth setup for Gmail + Calendar + Drive + Contacts.

Usage:
    cd ~/Documents/antigravity/goofy-bose/OpenJarvis
    uv run python jarvis_connect_google.py

You'll need:
    - client_id     from Google Cloud Console (OAuth 2.0 → Desktop App)
    - client_secret from the same credentials

The browser will open for consent. Once approved, tokens are saved to
~/.openjarvis/connectors/google.json and reused forever (auto-refreshed).
"""

import sys
import json
from pathlib import Path

CREDS_DIR  = Path.home() / ".openjarvis" / "connectors"
CREDS_FILE = CREDS_DIR / "google.json"

BANNER = """
  ╔══════════════════════════════════════════════════╗
  ║   JARVIS  —  Google Account Setup               ║
  ╚══════════════════════════════════════════════════╝

  This will connect JARVIS to your Google account:
    ✓ Gmail (read, draft, send)
    ✓ Google Calendar (read + create events)
    ✓ Google Drive (search files)
    ✓ Google Contacts (look up emails)

  Your browser will open for Google's consent screen.
  No data is sent anywhere — tokens stored locally at:
  ~/.openjarvis/connectors/google.json
"""

def main():
    print(BANNER)

    # Check if already connected
    if CREDS_FILE.exists():
        try:
            from openjarvis.connectors.oauth import load_tokens
            tokens = load_tokens(str(CREDS_FILE))
            if tokens and tokens.get("access_token"):
                print("  ✅  Already connected to Google!")
                print(f"     Token file: {CREDS_FILE}")
                choice = input("\n  Re-authenticate? (y/N): ").strip().lower()
                if choice != "y":
                    print("  Keeping existing credentials. Goodbye, sir.")
                    return
        except Exception:
            pass

    # Get credentials from Google Cloud Console
    print("  Step 1: Get your OAuth credentials")
    print("  ─────────────────────────────────────────────────────")
    print("  1. Go to: https://console.cloud.google.com/apis/credentials")
    print("  2. Click '+ CREATE CREDENTIALS' → 'OAuth client ID'")
    print("  3. Application type: Desktop app")
    print("  4. Name it 'JARVIS' and click Create")
    print("  5. Copy the Client ID and Client Secret below")
    print()
    print("  Also enable these APIs at:")
    print("  https://console.cloud.google.com/apis/library")
    print("    - Gmail API")
    print("    - Google Calendar API")
    print("    - Google Drive API")
    print("    - People API (contacts)")
    print()

    client_id     = input("  Paste your Client ID:     ").strip()
    client_secret = input("  Paste your Client Secret: ").strip()

    if not client_id or not client_secret:
        print("\n  ❌  No credentials provided. Exiting.")
        sys.exit(1)

    print("\n  Step 2: Browser consent")
    print("  ─────────────────────────────────────────────────────")
    print("  Opening your browser... Log in and click 'Allow' for all permissions.")
    print("  (The page may warn 'unverified app' — click 'Advanced' → 'Go to JARVIS')")
    print()

    try:
        from openjarvis.connectors.oauth import run_connector_oauth, save_tokens, _CONNECTORS_DIR

        # Save client credentials first so run_connector_oauth can find them
        cred_payload = {
            "client_id":     client_id,
            "client_secret": client_secret,
        }
        CREDS_DIR.mkdir(parents=True, exist_ok=True)
        for fname in ["google.json", "gmail.json", "gcalendar.json", "gdrive.json", "gcontacts.json"]:
            path = CREDS_DIR / fname
            existing = {}
            if path.exists():
                try:
                    existing = json.loads(path.read_text())
                except Exception:
                    pass
            existing.update(cred_payload)
            path.write_text(json.dumps(existing, indent=2))

        # Run the full OAuth flow (opens browser, catches callback, saves tokens)
        tokens = run_connector_oauth("gmail", client_id=client_id, client_secret=client_secret)

        print()
        print("  ✅  Successfully connected to Google!")
        print(f"     Tokens saved to: {CREDS_DIR}")
        print()
        print("  You can now use:")
        print("    - 'Hey JARVIS, what's on my calendar today?'")
        print("    - 'Hey JARVIS, read my emails'")
        print("    - 'Hey JARVIS, schedule a meeting with Rahul on Monday at 3pm'")
        print("    - 'Hey JARVIS, search my Drive for the task report'")
        print()

    except Exception as e:
        print(f"\n  ❌  Connection failed: {e}")
        print("\n  Try again or check that:")
        print("    - The APIs are enabled in Google Cloud Console")
        print("    - Port 8789 is not in use (the OAuth callback port)")
        sys.exit(1)


if __name__ == "__main__":
    main()
