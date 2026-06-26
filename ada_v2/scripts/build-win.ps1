# build-win.ps1 — Build J.A.R.V.I.S installer for Windows
# Usage: .\scripts\build-win.ps1
# Output: release/J.A.R.V.I.S Setup 1.0.0.exe
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $ProjectRoot ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Pip = Join-Path $Venv "Scripts\pip.exe"

Write-Host ""
Write-Host "============================================"
Write-Host "   J.A.R.V.I.S  Windows Build Script       "
Write-Host "============================================"
Write-Host ""

# Step 1: Ensure venv exists
if (-not (Test-Path $Python)) {
    Write-Host "[1/7] Creating virtual environment..."
    python -m venv $Venv
}

# Step 2: Install/upgrade Python deps
Write-Host "[2/7] Installing Python dependencies..."
& $Pip install --upgrade pip -q
& $Pip install pyinstaller -q
& $Pip install `
    fastapi uvicorn python-socketio aiohttp httpx `
    google-genai pyaudio mediapipe opencv-python-headless `
    python-dotenv pillow psutil numpy `
    edge-tts faster-whisper `
    build123d `
    playwright kasa `
    -q 2>&1 | Select-Object -Last 5

# Step 3: Install Playwright browsers
Write-Host "[3/7] Installing Playwright browsers..."
& "$Venv\Scripts\playwright.exe" install chromium --with-deps 2>$null

# Step 4: Build Python backend with PyInstaller
Write-Host "[4/7] Building Python backend (PyInstaller)..."
Push-Location (Join-Path $ProjectRoot "backend")
& "$Venv\Scripts\pyinstaller.exe" jarvis.spec `
    --distpath "$ProjectRoot\dist-py" `
    --workpath "$ProjectRoot\.pyibuild" `
    --noconfirm `
    --clean
Pop-Location
Write-Host "       Backend binary: dist-py\jarvis_server\jarvis_server.exe"

# Step 5: Bundle Playwright browsers
Write-Host "[5/7] Bundling Playwright Chromium browsers..."
& (Join-Path $PSScriptRoot "bundle-playwright.ps1")

# Step 6: Build React frontend
Write-Host "[6/7] Building React frontend..."
Push-Location $ProjectRoot
npm run build
Pop-Location
Write-Host "       Frontend: dist\"

# Step 7: Package with electron-builder
Write-Host "[7/7] Packaging with electron-builder..."
Push-Location $ProjectRoot
npx electron-builder --win --publish never
Pop-Location

Write-Host ""
Write-Host "Build complete! Installer is in: release\"
Get-ChildItem "$ProjectRoot\release\*.exe" -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $($_.Name)" }
