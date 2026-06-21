#!/bin/bash
# scripts/build_mac.sh
# Builds the macOS .dmg executable for JARVIS.

echo "[*] Checking dependencies..."
if ! command -v pyinstaller &> /dev/null; then
    echo "[-] PyInstaller not found. Installing..."
    uv pip install pyinstaller
fi

if ! command -v create-dmg &> /dev/null; then
    echo "[-] create-dmg not found. Installing via brew..."
    brew install create-dmg
fi

echo "[*] Cleaning old builds..."
rm -rf build dist JARVIS.dmg

echo "[*] Building JARVIS with PyInstaller..."
# We use --windowed so it doesn't open a terminal, and --name to name the .app
uv run pyinstaller --name "JARVIS" \
            --windowed \
            --onedir \
            --hidden-import "jarvis_todoist" \
            --hidden-import "jarvis_messaging" \
            --hidden-import "jarvis_vision" \
            --hidden-import "jarvis_browser" \
            --hidden-import "jarvis_apps" \
            --hidden-import "jarvis_youtube" \
            --hidden-import "sounddevice" \
            --hidden-import "numpy" \
            --hidden-import "openwakeword" \
            --hidden-import "jarvis_actions" \
            --hidden-import "jarvis_context" \
            --hidden-import "jarvis_autonomous" \
            --hidden-import "jarvis_reminders" \
            --hidden-import "jarvis_speak" \
            --hidden-import "jarvis_memory" \
            --hidden-import "jarvis_agent_monitor" \
            --hidden-import "jarvis_google" \
            --hidden-import "jarvis_obsidian" \
            --hidden-import "jarvis_sync" \
            --hidden-import "jarvis_patterns" \
            --hidden-import "jarvis_listen" \
            --hidden-import "jarvis_llm" \
            --hidden-import "jarvis_crm" \
            --hidden-import "jarvis_failure_store" \
            --hidden-import "customtkinter" \
            --collect-data "certifi" \
            jarvis_ui.py

echo "[*] Packaging JARVIS.app into JARVIS.dmg..."
# Assuming it successfully created dist/JARVIS.app
if [ -d "dist/JARVIS.app" ]; then
    echo "[*] Injecting macOS Permissions into Info.plist..."
    plutil -insert NSMicrophoneUsageDescription -string "JARVIS needs microphone access to hear your voice commands." dist/JARVIS.app/Contents/Info.plist
    plutil -insert NSCameraUsageDescription -string "JARVIS needs camera access for vision capabilities." dist/JARVIS.app/Contents/Info.plist
    
    echo "[*] Re-signing the JARVIS.app bundle..."
    codesign --force --deep --sign - dist/JARVIS.app

    create-dmg \
      --volname "JARVIS Installer" \
      --volicon "dist/JARVIS.app/Contents/Resources/icon-windowed.icns" \
      --window-pos 200 120 \
      --window-size 800 400 \
      --icon-size 100 \
      --icon "JARVIS.app" 200 190 \
      --hide-extension "JARVIS.app" \
      --app-drop-link 600 185 \
      "JARVIS.dmg" \
      "dist/JARVIS.app"
      
    echo "[+] Build complete: JARVIS.dmg"
else
    echo "[-] Build failed: dist/JARVIS.app not found."
    exit 1
fi
