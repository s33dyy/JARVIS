@echo off
:: ============================================================
::  build-win.bat — Build J.A.R.V.I.S .exe installer for Windows
::  Usage: build-win.bat
::  Output: release\J.A.R.V.I.S Setup 1.0.0.exe
:: ============================================================
setlocal EnableDelayedExpansion

:: Resolve project root
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%..\package.json" (
    set "PROJECT_ROOT=%SCRIPT_DIR%.."
) else if exist "%SCRIPT_DIR%package.json" (
    set "PROJECT_ROOT=%SCRIPT_DIR%"
) else (
    echo [ERROR] Cannot find package.json. Run from ada_v2\scripts\ or ada_v2\
    exit /b 1
)

set "VENV=%PROJECT_ROOT%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set "PYINSTALLER=%VENV%\Scripts\pyinstaller.exe"
set "LOGFILE=%PROJECT_ROOT%\build.log"

:: Clear previous log
echo. > "%LOGFILE%"

echo.
echo  ========================================
echo    J.A.R.V.I.S  Windows Build Script
echo  ========================================
echo.
echo  Project root: %PROJECT_ROOT%
echo  Log file: %LOGFILE%
echo.

:: ── Step 1: Check Python + Node ──────────────────────────────
echo [1/6] Checking prerequisites...

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.11+ from https://python.org/downloads
    echo         Make sure to check "Add Python to PATH" during installation.
    exit /b 1
)
set "PYVER="
for /f "usebackq delims=" %%i in (`python --version 2^>^&1`) do if not defined PYVER set "PYVER=%%i"
echo        Python: %PYVER%

:: Check Node.js
where node >nul 2>&1
if not errorlevel 1 goto :node_ok

echo        Node.js not found. Installing automatically...

:: Try winget first
where winget >nul 2>&1
if errorlevel 1 goto :node_winget_fail

echo        [1a] Installing via winget...
winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo        WARNING: winget failed, trying manual download...
    goto :node_winget_fail
)
goto :node_refresh

:node_winget_fail
echo        [1b] Downloading Node.js v20 LTS...
powershell -Command "& {$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://nodejs.org/dist/v20.18.0/node-v20.18.0-x64.msi' -OutFile \"$env:TEMP\nodejs.msi\"}" 2>nul
if errorlevel 1 (
    echo [ERROR] Could not download Node.js. Install manually from https://nodejs.org
    exit /b 1
)
echo        [1c] Installing Node.js (may request admin access)...
start /wait msiexec /i "%TEMP%\nodejs.msi" /qn
del "%TEMP%\nodejs.msi" 2>nul

:node_refresh
:: Refresh PATH
set "PATH=%PATH%;C:\Program Files\nodejs;C:\Program Files (x86)\nodejs"

:: Verify
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js installed but not in PATH.
    echo         Close this window, open a NEW terminal, and run: scripts\build-win.bat
    exit /b 1
)
echo        Node.js installed successfully!

:node_ok
set "NODEVER="
for /f "usebackq delims=" %%i in (`node --version 2^>^&1`) do if not defined NODEVER set "NODEVER=%%i"
echo        Node.js: %NODEVER%
echo.

:: ── Step 2: Create venv ─────────────────────────────────────
echo [2/6] Setting up virtual environment...
if not exist "%PYTHON%" (
    echo        Creating new venv...
    python -m venv "%VENV%" >> "%LOGFILE%" 2>&1
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        type "%LOGFILE%" | findstr /i "error"
        exit /b 1
    )
    echo        Venv created at: %VENV%
) else (
    echo        Venv already exists.
)

:: ── Step 3: Install Python deps ─────────────────────────────
echo [3/6] Installing Python dependencies...
echo        This may take a few minutes on first run...
echo.

:: Upgrade pip
echo        [3a] Upgrading pip...
"%PIP%" install --upgrade pip >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo        WARNING: pip upgrade failed, continuing anyway...
) else (
    echo        pip upgraded.
)

:: PyInstaller
echo        [3b] Installing pyinstaller...
"%PIP%" install pyinstaller >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] pyinstaller install failed. Check %LOGFILE%
    exit /b 1
)
echo        pyinstaller OK.

:: Core framework
echo        [3c] Installing core framework (fastapi, uvicorn, socketio)...
"%PIP%" install fastapi uvicorn python-socketio aiohttp httpx >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] Core framework install failed. Check %LOGFILE%
    exit /b 1
)
echo        Core framework OK.

:: Config / utils
echo        [3d] Installing config and utilities...
"%PIP%" install python-dotenv pillow psutil numpy >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] Utils install failed. Check %LOGFILE%
    exit /b 1
)
echo        Config/utils OK.

:: Google Gemini
echo        [3e] Installing Google Gemini SDK...
"%PIP%" install google-genai >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] google-genai install failed. Check %LOGFILE%
    exit /b 1
)
echo        Google Gemini SDK OK.

:: Audio - sounddevice (always works)
echo        [3f] Installing audio backends...
"%PIP%" install sounddevice >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo        WARNING: sounddevice install failed.
) else (
    echo        sounddevice OK.
)

:: Audio - pyaudio (may need C++ Build Tools)
echo        [3g] Installing pyaudio...
"%PIP%" install pyaudio >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo        -------------------------------------------------------
    echo        WARNING: pyaudio FAILED to install.
    echo.
    echo        This is expected if you don't have C++ Build Tools.
    echo        The app will still work, but microphone input may not.
    echo.
    echo        To fix: Install Microsoft C++ Build Tools from:
    echo        https://visualstudio.microsoft.com/visual-cpp-build-tools/
    echo.
    echo        Then run: pip install pyaudio
    echo        -------------------------------------------------------
) else (
    echo        pyaudio OK.
)

:: MediaPipe + OpenCV
echo        [3h] Installing MediaPipe and OpenCV...
"%PIP%" install mediapipe opencv-python-headless >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo        WARNING: mediapipe install failed. Hand tracking may not work.
) else (
    echo        MediaPipe + OpenCV OK.
)

:: TTS / STT
echo        [3i] Installing TTS and STT engines...
"%PIP%" install edge-tts faster-whisper >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo        WARNING: TTS/STT install failed. Voice features may not work.
) else (
    echo        TTS/STT OK.
)

:: CAD - build123d
echo        [3j] Installing build123d (CAD engine)...
"%PIP%" install build123d >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo        WARNING: build123d install failed. 3D model generation may not work.
) else (
    echo        build123d OK.
)

:: Web agent
echo        [3k] Installing Playwright and Kasa...
"%PIP%" install playwright kasa >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo        WARNING: playwright/kasa install failed. Web agent may not work.
) else (
    echo        Playwright + Kasa OK.
)

echo.
echo        Python dependencies complete.
echo.

:: ── Step 4: Playwright browsers ─────────────────────────────
echo [4/6] Installing Playwright Chromium browser...
echo        This downloads ~150MB on first run...
"%VENV%\Scripts\playwright.exe" install chromium --with-deps >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo        WARNING: Playwright browser install failed.
    echo        Web agent may not work. Try manually: playwright install chromium
) else (
    echo        Playwright Chromium installed.
)

:: ── Step 5: PyInstaller backend ─────────────────────────────
echo [5/6] Building Python backend with PyInstaller...
echo        This may take 2-5 minutes...
cd /d "%PROJECT_ROOT%\backend"
"%PYINSTALLER%" jarvis.spec ^
    --distpath "%PROJECT_ROOT%\dist-py" ^
    --workpath "%PROJECT_ROOT%\.pyibuild" ^
    --noconfirm ^
    --clean >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed. Check %LOGFILE%
    exit /b 1
)
echo        Backend binary built successfully.

:: ── Step 6: Bundle Playwright + Build frontend ──────────────
echo [6/6] Building frontend and packaging...
cd /d "%PROJECT_ROOT%"

:: Bundle Playwright browsers into dist-py
echo        [6a] Bundling Playwright browsers...
powershell -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\bundle-playwright.ps1" >> "%LOGFILE%" 2>&1

:: npm install
echo        [6b] Installing Node.js dependencies...
call npm install 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] npm install failed. Common fixes:
    echo         1. Delete node_modules and try again: rmdir /s /q node_modules
    echo         2. Clear npm cache: npm cache clean --force
    echo         3. Check if Node.js is in PATH: node --version
    echo         4. Full log: %LOGFILE%
    exit /b 1
)
echo        Node.js dependencies installed.

:: Vite build
echo        [6c] Building React frontend...
call npm run build 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Vite build failed. Check the error above.
    echo         Full log: %LOGFILE%
    exit /b 1
)
echo        Frontend built.

:: electron-builder
echo        [6d] Packaging with electron-builder...
call npx electron-builder --win --publish never >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] electron-builder failed. Check %LOGFILE%
    exit /b 1
)

echo.
echo  ========================================
echo    BUILD COMPLETE!
echo  ========================================
echo.
echo  Installer location:
dir "%PROJECT_ROOT%\release\*.exe" 2>nul
echo.
echo  Full build log: %LOGFILE%
echo.
echo  NOTE: Windows SmartScreen may warn on first run.
echo  Click "More info" then "Run anyway".
echo.
