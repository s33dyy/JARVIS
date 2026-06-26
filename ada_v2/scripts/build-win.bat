@echo off
:: ============================================================
::  build-win.bat — Build J.A.R.V.I.S .exe installer for Windows
::  Usage: scripts\build-win.bat
::  Output: release\J.A.R.V.I.S Setup 1.0.0.exe
:: ============================================================
setlocal EnableDelayedExpansion

set "PROJECT_ROOT=%~dp0.."
set "VENV=%PROJECT_ROOT%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set "PYINSTALLER=%VENV%\Scripts\pyinstaller.exe"

echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║   J.A.R.V.I.S  Windows Build Script         ║
echo  ╚══════════════════════════════════════════════╝
echo.

:: ── Step 1: Ensure venv ─────────────────────────────────────
if not exist "%PYTHON%" (
    echo [1/6] Creating virtual environment...
    python -m venv "%VENV%"
    if errorlevel 1 ( echo ERROR: python not found. Install Python 3.11+ & exit /b 1 )
) else (
    echo [1/6] Virtual environment found.
)

:: ── Step 2: Install Python deps ─────────────────────────────
echo [2/6] Installing Python dependencies...
"%PIP%" install --upgrade pip -q
"%PIP%" install pyinstaller ^
    fastapi uvicorn python-socketio aiohttp httpx ^
    google-genai pyaudio mediapipe opencv-python-headless ^
    python-dotenv pillow psutil numpy ^
    edge-tts faster-whisper ^
    build123d ^
    playwright kasa ^
    -q
if errorlevel 1 ( echo ERROR: pip install failed & exit /b 1 )

:: ── Step 3: Playwright browsers ─────────────────────────────
echo [3/6] Installing Playwright browsers...
"%VENV%\Scripts\playwright.exe" install chromium --with-deps 2>nul || echo (playwright install skipped)

:: ── Step 4: PyInstaller backend ─────────────────────────────
echo [4/6] Building Python backend (PyInstaller)...
cd /d "%PROJECT_ROOT%\backend"
"%PYINSTALLER%" jarvis.spec ^
    --distpath "%PROJECT_ROOT%\dist-py" ^
    --workpath "%PROJECT_ROOT%\.pyibuild" ^
    --noconfirm ^
    --clean
if errorlevel 1 ( echo ERROR: PyInstaller failed & exit /b 1 )
echo        Backend binary: dist-py\jarvis_server\jarvis_server.exe OK

:: ── Step 5: React frontend ───────────────────────────────────
echo [5/6] Building React frontend...
cd /d "%PROJECT_ROOT%"
call npm run build
if errorlevel 1 ( echo ERROR: vite build failed & exit /b 1 )
echo        Frontend: dist\ OK

:: ── Step 6: electron-builder ─────────────────────────────────
echo [6/6] Packaging with electron-builder...
call npx electron-builder --win --publish never
if errorlevel 1 ( echo ERROR: electron-builder failed & exit /b 1 )

echo.
echo  Build complete! Installer is in: release\
dir "%PROJECT_ROOT%\release\*.exe" 2>nul
echo.
echo  NOTE: Windows will show SmartScreen warning on first run.
echo  Users should click "More info" then "Run anyway".
echo.
