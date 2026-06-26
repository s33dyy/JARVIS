@echo off
:: ============================================================
::  build-win.bat — Build J.A.R.V.I.S .exe installer for Windows
::  Usage: build-win.bat   (run from ada_v2\scripts\ or ada_v2\)
::  Output: release\J.A.R.V.I.S Setup 1.0.0.exe
:: ============================================================
setlocal EnableDelayedExpansion

:: Resolve project root (scripts\ is one level below ada_v2)
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%..\package.json" (
    set "PROJECT_ROOT=%SCRIPT_DIR%.."
) else if exist "%SCRIPT_DIR%package.json" (
    set "PROJECT_ROOT=%SCRIPT_DIR%"
) else (
    echo ERROR: Cannot find package.json. Run from ada_v2\scripts\ or ada_v2\
    exit /b 1
)

set "VENV=%PROJECT_ROOT%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set "PYINSTALLER=%VENV%\Scripts\pyinstaller.exe"

echo.
echo  ========================================
echo    J.A.R.V.I.S  Windows Build Script
echo  ========================================
echo.

:: ── Step 1: Ensure venv ─────────────────────────────────────
if not exist "%PYTHON%" (
    echo [1/6] Creating virtual environment...
    python -m venv "%VENV%"
    if errorlevel 1 ( echo ERROR: python not found. Install Python 3.11+ from python.org & exit /b 1 )
) else (
    echo [1/6] Virtual environment found.
)

:: ── Step 2: Install Python deps ─────────────────────────────
echo [2/6] Installing Python dependencies...
"%PIP%" install --upgrade pip -q 2>nul

:: Core deps first (these always install cleanly)
"%PIP%" install pyinstaller -q
"%PIP%" install ^
    fastapi uvicorn python-socketio aiohttp httpx ^
    python-dotenv pillow psutil numpy ^
    google-genai ^
    -q
if errorlevel 1 ( echo ERROR: Core pip install failed & exit /b 1 )

:: Audio deps (pyaudio may fail without C++ Build Tools)
"%PIP%" install sounddevice -q 2>nul
"%PIP%" install pyaudio -q 2>nul
if errorlevel 1 (
    echo WARNING: pyaudio failed to install (needs C++ Build Tools^).
    echo          Audio capture may not work. Install from:
    echo          https://visualstudio.microsoft.com/visual-cpp-build-tools/
    echo          Or run: pip install pipwin ^&^& pipwin install pyaudio
)

:: ML / AI deps
"%PIP%" install mediapipe opencv-python-headless -q 2>nul
"%PIP%" install edge-tts faster-whisper -q 2>nul

:: CAD
"%PIP%" install build123d -q 2>nul
if errorlevel 1 (
    echo WARNING: build123d install had issues. CAD generation may not work.
)

:: Web agent
"%PIP%" install playwright -q 2>nul
"%PIP%" install kasa -q 2>nul

echo        Python dependencies installed.

:: ── Step 3: Playwright browsers ─────────────────────────────
echo [3/6] Installing Playwright browsers...
"%VENV%\Scripts\playwright.exe" install chromium --with-deps 2>nul
if errorlevel 1 (
    echo WARNING: Playwright browser install failed.
    echo          Web agent may not work. Try: pip install playwright ^&^& playwright install
)

:: ── Step 4: PyInstaller backend ─────────────────────────────
echo [4/6] Building Python backend (PyInstaller^)...
cd /d "%PROJECT_ROOT%\backend"
"%PYINSTALLER%" jarvis.spec ^
    --distpath "%PROJECT_ROOT%\dist-py" ^
    --workpath "%PROJECT_ROOT%\.pyibuild" ^
    --noconfirm ^
    --clean
if errorlevel 1 ( echo ERROR: PyInstaller failed & exit /b 1 )
echo        Backend binary: dist-py\jarvis_server\ OK

:: ── Step 5: Bundle Playwright browsers ──────────────────────
echo [5/6] Bundling Playwright browsers...
powershell -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\bundle-playwright.ps1"

:: ── Step 6: React frontend + electron-builder ───────────────
echo [6/6] Building frontend and packaging...
cd /d "%PROJECT_ROOT%"
call npm install
if errorlevel 1 ( echo ERROR: npm install failed & exit /b 1 )
call npm run build
if errorlevel 1 ( echo ERROR: vite build failed & exit /b 1 )
call npx electron-builder --win --publish never
if errorlevel 1 ( echo ERROR: electron-builder failed & exit /b 1 )

echo.
echo  ========================================
echo    Build complete!
echo  ========================================
echo.
dir "%PROJECT_ROOT%\release\*.exe" 2>nul
echo.
echo  NOTE: Windows SmartScreen may warn on first run.
echo  Click "More info" then "Run anyway".
echo.
