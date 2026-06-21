# scripts/build_windows.ps1
# Builds the Windows .exe executable for JARVIS.
# NOTE: JARVIS currently relies heavily on macOS APIs (AppleScript, screencapture).
# Building this on Windows will result in an executable with limited functionality.

Write-Host "[*] Checking dependencies..."

# Ensure PyInstaller is installed
$pyinstaller = Get-Command pyinstaller -ErrorAction SilentlyContinue
if (-not $pyinstaller) {
    Write-Host "[-] PyInstaller not found. Installing..."
    pip install pyinstaller
}

Write-Host "[*] Cleaning old builds..."
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "JARVIS.exe") { Remove-Item -Force "JARVIS.exe" }

Write-Host "[*] Building JARVIS with PyInstaller..."
# We use --windowed so it doesn't open a terminal shell by default
pyinstaller --name "JARVIS" `
            --windowed `
            --onefile `
            --hidden-import "jarvis_apps" `
            --hidden-import "jarvis_youtube" `
            --hidden-import "sounddevice" `
            --hidden-import "numpy" `
            --hidden-import "jarvis_actions" `
            --hidden-import "jarvis_context" `
            --hidden-import "jarvis_autonomous" `
            --hidden-import "jarvis_reminders" `
            --hidden-import "jarvis_memory" `
            --hidden-import "customtkinter" `
            jarvis_ui.py

if (Test-Path "dist\JARVIS.exe") {
    Copy-Item "dist\JARVIS.exe" "JARVIS.exe"
    Write-Host "[+] Build complete: JARVIS.exe"
} else {
    Write-Host "[-] Build failed: dist\JARVIS.exe not found."
    exit 1
}
