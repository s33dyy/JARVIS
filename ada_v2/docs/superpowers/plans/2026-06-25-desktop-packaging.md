# Desktop Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package J.A.R.V.I.S as a standalone desktop app for macOS (arm64) and Windows (x64) with bundled Python backend and Playwright Chromium.

**Architecture:** PyInstaller bundles the Python backend into a self-contained binary. Playwright Chromium browsers are bundled alongside the binary. Electron wraps the React frontend and spawns the backend on startup. electron-builder produces `.dmg` (macOS) and `.nsis` (Windows) installers.

**Tech Stack:** Electron 28, electron-builder 24, PyInstaller 6, Playwright, Vite 5

---

## Key Technical Decisions

1. **Playwright Chromium bundling:** Copy browser binaries from `~/Library/Caches/ms-playwright/` into `dist-py/playwright-browsers/`, then set `PLAYWRIGHT_BROWSERS_PATH` env var in `electron/main.js` to point to `resources/playwright-browsers/`.
2. **DYLD_LIBRARY_PATH:** Only needed on macOS for Homebrew's libexpat. In production, the PyInstaller binary bundles its own libexpat — remove this env var for production builds.
3. **macOS entitlements:** Already properly configured for unsigned distribution (hardened runtime + entitlements allow unsigned executables).
4. **Windows:** No special GPU flags needed beyond what's already in `main.js`. NSIS installer handles PATH and shortcuts.

---

## File Structure

### Files to Create
- `scripts/build-win.ps1` — Windows build script (PowerShell)
- `scripts/bundle-playwright.sh` — Copies Playwright browsers into dist-py
- `scripts/bundle-playwright.ps1` — Windows equivalent
- `build/entitlements.mac.plist` — Already exists, may need minor updates

### Files to Modify
- `electron/main.js` — Set `PLAYWRIGHT_BROWSERS_PATH` for production, fix `DYLD_LIBRARY_PATH` for production
- `backend/jarvis.spec` — Add Playwright browsers to datas, add console icon suppression for Windows
- `package.json` — Fix `dist:all` script, add Playwright bundling step, update build config
- `scripts/build-mac.sh` — Add Playwright bundling step
- `backend/web_agent.py` — Set `PLAYWRIGHT_BROWSERS_PATH` if env var is set (fallback to default)

---

## Task 1: Bundle Playwright Chromium into PyInstaller Output

**Files:**
- Create: `scripts/bundle-playwright.sh`
- Create: `scripts/bundle-playwright.ps1`
- Modify: `scripts/build-mac.sh`
- Modify: `backend/jarvis.spec`

- [ ] **Step 1: Create macOS Playwright bundling script**

```bash
#!/usr/bin/env bash
# bundle-playwright.sh — Copy Playwright Chromium browsers into dist-py for bundling
# Usage: bash scripts/bundle-playwright.sh
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_PY="$PROJECT_ROOT/dist-py/jarvis_server"
PLAYWRIGHT_CACHE="$HOME/Library/Caches/ms-playwright"

echo "Bundling Playwright Chromium browsers..."

# Create target directory
mkdir -p "$DIST_PY/_internal/playwright-browsers"

# Copy Chromium (headless shell + full browser) and ffmpeg
for dir in chromium-1223 chromium_headless_shell-1223 ffmpeg-1011; do
    src="$PLAYWRIGHT_CACHE/$dir"
    if [ -d "$src" ]; then
        echo "  Copying $dir..."
        cp -R "$src" "$DIST_PY/_internal/playwright-browsers/"
    else
        echo "  WARNING: $dir not found in Playwright cache"
    fi
done

# Copy .links directory (Playwright's manifest)
if [ -d "$PLAYWRIGHT_CACHE/.links" ]; then
    cp -R "$PLAYWRIGHT_CACHE/.links" "$DIST_PY/_internal/playwright-browsers/"
fi

SIZE=$(du -sh "$DIST_PY/_internal/playwright-browsers" | cut -f1)
echo "Playwright browsers bundled: $SIZE"
```

- [ ] **Step 2: Create Windows Playwright bundling script**

```powershell
# bundle-playwright.ps1 — Copy Playwright Chromium browsers into dist-py for bundling
# Usage: .\scripts\bundle-playwright.ps1
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DistPy = Join-Path $ProjectRoot "dist-py\jarvis_server\_internal\playwright-browsers"
$PlaywrightCache = Join-Path $env:LOCALAPPDATA "ms-playwright"

Write-Host "Bundling Playwright Chromium browsers..."

# Create target directory
New-Item -ItemType Directory -Force -Path $DistPy | Out-Null

# Copy Chromium and ffmpeg directories
$dirs = @("chromium-1223", "chromium_headless_shell-1223", "ffmpeg-1011")
foreach ($dir in $dirs) {
    $src = Join-Path $PlaywrightCache $dir
    if (Test-Path $src) {
        Write-Host "  Copying $dir..."
        Copy-Item -Recurse -Force $src (Join-Path $DistPy $dir)
    } else {
        Write-Host "  WARNING: $dir not found in Playwright cache"
    }
}

# Copy .links directory
$linksSrc = Join-Path $PlaywrightCache ".links"
if (Test-Path $linksSrc) {
    Copy-Item -Recurse -Force $linksSrc (Join-Path $DistPy ".links")
}

Write-Host "Playwright browsers bundled successfully."
```

- [ ] **Step 3: Add Playwright bundling step to build-mac.sh**

In `scripts/build-mac.sh`, add a new step between Step 4 (PyInstaller) and Step 5 (Vite build):

```bash
# ── Step 4.5: Bundle Playwright browsers ────────────────────
echo "[4.5/7] Bundling Playwright Chromium browsers..."
bash "$PROJECT_ROOT/scripts/bundle-playwright.sh"
```

Also update the step count in all echo messages from `/6` to `/7`.

- [ ] **Step 4: Update PyInstaller spec to exclude Playwright browser binaries from zip**

In `backend/jarvis.spec`, the Playwright browsers are large binary files. They should NOT be zipped inside the PYZ archive. Add them to `excludes` in the COLLECT step or handle via datas. Actually, since we're putting them in `_internal/playwright-browsers/` (inside the COLLECT output), they'll be copied automatically. But we need to make sure PyInstaller doesn't try to analyze them. The current spec already puts everything in `datas` which goes to COLLECT, so this should work. No change needed to the spec for this — the bundle script handles it post-PyInstaller.

- [ ] **Step 5: Commit**

```bash
git add scripts/bundle-playwright.sh scripts/bundle-playwright.ps1 scripts/build-mac.sh
git commit -m "feat: add Playwright browser bundling for desktop builds"
```

---

## Task 2: Fix electron/main.js for Production Playwright and DYLD_LIBRARY_PATH

**Files:**
- Modify: `electron/main.js`

- [ ] **Step 1: Update startPythonBackend to set PLAYWRIGHT_BROWSERS_PATH and fix DYLD_LIBRARY_PATH**

Replace the `startPythonBackend()` function in `electron/main.js`. The key changes:
1. In production mode, set `PLAYWRIGHT_BROWSERS_PATH` to `resources/playwright-browsers/`
2. In production mode, do NOT set `DYLD_LIBRARY_PATH` (PyInstaller bundles its own libexpat)
3. Only set `DYLD_LIBRARY_PATH` in dev mode

```javascript
function startPythonBackend() {
    const fs = require('fs');
    const projectRoot = path.join(__dirname, '..');
    const isDev = process.env.NODE_ENV !== 'production';

    let pythonExe, args, cwd;

    // Build environment variables
    const env = { ...process.env };

    if (!isDev) {
        // Production: PyInstaller COLLECT output is a folder named 'jarvis_server'
        const resourcesPath = process.resourcesPath;
        const binaryName = process.platform === 'win32' ? 'jarvis_server.exe' : 'jarvis_server';
        const bundledBin = path.join(resourcesPath, 'backend', 'jarvis_server', binaryName);

        if (fs.existsSync(bundledBin)) {
            pythonExe = bundledBin;
            args = [];
            cwd = path.join(resourcesPath, 'backend', 'jarvis_server');
            console.log(`[JARVIS] Starting bundled backend: ${bundledBin}`);
        } else {
            console.warn(`[JARVIS] Bundled binary not found at: ${bundledBin}. Falling back to script.`);
            const scriptPath = path.join(resourcesPath, 'backend', 'server.py');
            pythonExe = process.platform === 'win32' ? 'python' : 'python3';
            args = [scriptPath];
            cwd = path.join(resourcesPath, 'backend');
        }

        // Production: set Playwright browsers path to bundled location
        const playwrightBrowsersPath = path.join(resourcesPath, 'backend', 'jarvis_server', '_internal', 'playwright-browsers');
        if (fs.existsSync(playwrightBrowsersPath)) {
            env.PLAYWRIGHT_BROWSERS_PATH = playwrightBrowsersPath;
            console.log(`[JARVIS] Playwright browsers: ${playwrightBrowsersPath}`);
        }

        // Production: do NOT set DYLD_LIBRARY_PATH — PyInstaller bundles its own libs
    } else {
        // Dev: use venv python
        const scriptPath = path.join(projectRoot, 'backend', 'server.py');
        const venvPython = path.join(projectRoot, '.venv', 'bin', 'python3');
        pythonExe = fs.existsSync(venvPython)
            ? venvPython
            : (process.platform === 'win32' ? 'python' : 'python3');
        args = [scriptPath];
        cwd = path.join(projectRoot, 'backend');
        console.log(`[JARVIS] Dev mode: ${pythonExe} ${scriptPath}`);

        // Dev: macOS libexpat fix for Homebrew Python
        if (process.platform === 'darwin') {
            env.DYLD_LIBRARY_PATH = '/opt/homebrew/opt/expat/lib';
        }
    }

    // userData dir is always writable (outside the .app bundle on macOS)
    const { app: electronApp } = require('electron');
    const userDataPath = electronApp.getPath('userData');
    env.JARVIS_USERDATA = userDataPath;

    pythonProcess = spawn(pythonExe, args, { cwd, env });

    pythonProcess.stdout.on('data', (data) => {
        process.stdout.write(`[JARVIS Backend] ${data}`);
    });

    pythonProcess.stderr.on('data', (data) => {
        process.stderr.write(`[JARVIS Backend ERR] ${data}`);
    });

    pythonProcess.on('exit', (code, signal) => {
        console.log(`[JARVIS] Backend exited: code=${code} signal=${signal}`);
    });
}
```

- [ ] **Step 2: Verify the change is correct**

Read the file back and verify:
- `PLAYWRIGHT_BROWSERS_PATH` is set in production mode
- `DYLD_LIBRARY_PATH` is only set in dev mode on macOS
- `JARVIS_USERDATA` is always set
- All other behavior is preserved

- [ ] **Step 3: Commit**

```bash
git add electron/main.js
git commit -m "fix: set PLAYWRIGHT_BROWSERS_PATH in prod, only DYLD_LIBRARY_PATH in dev"
```

---

## Task 3: Fix package.json Build Config

**Files:**
- Modify: `package.json`

- [ ] **Step 1: Fix dist:all script to include PyInstaller steps**

The current `dist:all` script skips PyInstaller, which means the backend binary won't be included. Fix it:

```json
"dist:all": "npm run build && npm run build:backend:mac && electron-builder --mac --win --publish never"
```

Note: Cross-compiling PyInstaller from macOS to Windows isn't possible. The `dist:all` script should only build for the current platform's backend. For true cross-platform builds, you need CI/CD (GitHub Actions). For now, `dist:all` builds the current platform's backend + packages for both targets (but Windows NSIS on macOS will include the macOS backend binary — this is a known limitation).

Actually, a better approach: make `dist:all` just build for the current platform:

```json
"dist:mac": "npm run build && npm run build:backend:mac && electron-builder --mac --publish never",
"dist:win": "npm run build && npm run build:backend:win && electron-builder --win --publish never",
"dist": "npm run build && electron-builder --publish never"
```

The `dist` script builds for the current platform only (auto-detects mac/win/linux).

- [ ] **Step 2: Add Playwright bundling to the build:backend scripts**

Update the `build:backend:mac` script to include Playwright bundling:

```json
"build:backend:mac": "cd backend && ../.venv/bin/pyinstaller jarvis.spec --distpath ../dist-py && bash ../scripts/bundle-playwright.sh"
```

For Windows:
```json
"build:backend:win": "cd backend && ..\\.venv\\Scripts\\pyinstaller jarvis.spec --distpath ..\\dist-py && powershell ..\\scripts\\bundle-playwright.ps1"
```

- [ ] **Step 3: Verify the full config**

Read package.json and verify all scripts and build config are correct.

- [ ] **Step 4: Commit**

```bash
git add package.json
git commit -m "fix: add Playwright bundling to build scripts, fix dist:all"
```

---

## Task 4: Update PyInstaller Spec for Windows and Playwright

**Files:**
- Modify: `backend/jarvis.spec`

- [ ] **Step 1: Update the spec to handle Windows console window**

On Windows, PyInstaller creates a console window by default. For a production app, we want `console=False` on Windows. But we need stdout/stderr for debugging. Solution: keep `console=True` for now (it's useful for debugging), but add a comment that it can be flipped to `False` for release.

Actually, the better approach is to keep `console=True` but redirect output to a log file. This is handled by electron/main.js already (it pipes stdout/stderr). So no change needed.

- [ ] **Step 2: Add missing hidden imports**

Based on runtime errors we've seen, add these missing hidden imports:

```python
hidden_imports = [
    # ... existing imports ...
    # Additional imports discovered during testing
    'engineio.async_drivers.aiohttp',
    'multipart',
    'python_multipart',
    'google.auth.transport',
    'google.auth.transport.requests',
    'google.oauth2',
    'google.oauth2.credentials',
    'google.oauth2.service_account',
    'pyaudio._portaudio',
    'sounddevice',
    'av',
    'av.audio',
    'av.video',
    'av.container',
    'av.codec',
    'av.filter',
    'numpy.core._methods',
    'numpy.lib.format',
    'onnxruntime',
    'onnxruntime.capi',
    'tokenizers',
    'tokenizers.models',
    'huggingface_hub',
    'huggingface_hub.file_download',
    'typing_extensions',
]
```

- [ ] **Step 3: Add Playwright browsers to datas (post-bundling)**

Actually, the Playwright browsers are copied by the bundle script AFTER PyInstaller runs. They end up in `dist-py/jarvis_server/_internal/playwright-browsers/`. The electron-builder `extraResources` config copies `dist-py/jarvis_server/` to `resources/backend/jarvis_server/`. So the browsers will be included automatically. No change needed to the spec for this.

- [ ] **Step 4: Commit**

```bash
git add backend/jarvis.spec
git commit -m "fix: add missing hidden imports to PyInstaller spec"
```

---

## Task 5: Create Windows Build Script

**Files:**
- Create: `scripts/build-win.ps1`

- [ ] **Step 1: Create the PowerShell build script**

```powershell
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
```

- [ ] **Step 2: Commit**

```bash
git add scripts/build-win.ps1
git commit -m "feat: add Windows build script"
```

---

## Task 6: Test macOS Build End-to-End

**Files:**
- None (testing only)

- [ ] **Step 1: Run the full macOS build**

```bash
cd /Users/pratikchoudhuri/Documents/antigravity/noble-shannon/ada_v2
bash scripts/build-mac.sh
```

Expected output:
- `dist-py/jarvis_server/` — PyInstaller output with Playwright browsers
- `dist/` — Vite build output
- `release/J.A.R.V.I.S-1.0.0-arm64.dmg` — Final DMG installer

- [ ] **Step 2: Verify the DMG contents**

```bash
hdiutil attach release/J.A.R.V.I.S-1.0.0-arm64.dmg
ls -la /Volumes/J.A.R.V.I.S/
hdiutil detach /Volumes/J.A.R.V.I.S
```

Expected: `J.A.R.V.I.S.app` in the DMG.

- [ ] **Step 3: Test the packaged app**

```bash
# Copy to /Applications and run
cp -R "/Volumes/J.A.R.V.I.S/J.A.R.V.I.S.app" /Applications/
open /Applications/J.A.R.V.I.S.app
```

Verify:
- App launches without errors
- Backend starts (check Console.app or terminal output)
- Settings panel works
- CAD generation works
- Playwright web agent works (browser launches)

- [ ] **Step 4: Fix any issues found**

If the app fails to start, check:
1. Console.app for macOS system logs
2. The bundled binary at `J.A.R.V.I.S.app/Contents/Resources/backend/jarvis_server/jarvis_server`
3. Playwright browsers at `J.A.R.V.I.S.app/Contents/Resources/backend/jarvis_server/_internal/playwright-browsers/`

- [ ] **Step 5: Document the final build size**

```bash
du -sh release/*.dmg
du -sh "/Applications/J.A.R.V.I.S.app"
```

---

## Task 7: Test Windows Build (Cross-Platform Validation)

**Files:**
- None (testing only — requires Windows machine or CI)

- [ ] **Step 1: On a Windows machine, run the build**

```powershell
.\scripts\build-win.ps1
```

Expected output:
- `release/J.A.R.V.I.S Setup 1.0.0.exe` — NSIS installer

- [ ] **Step 2: Test the installer**

Run the NSIS installer on Windows. Verify:
- Installs to chosen directory
- Creates desktop and start menu shortcuts
- App launches without errors
- Backend starts
- All features work

- [ ] **Step 3: Document any Windows-specific issues**

Common Windows issues:
- Path separators (backslash vs forward slash)
- Antivirus flagging PyInstaller binary
- Missing Visual C++ Redistributable
- Playwright browser path issues

---

## Task 8: CI/CD Setup (Optional — for automated builds)

**Files:**
- Create: `.github/workflows/build.yml`

This is optional but recommended for reproducible builds. GitHub Actions can build for both platforms.

- [ ] **Step 1: Create GitHub Actions workflow**

```yaml
name: Build Desktop App

on:
  push:
    tags: ['v*']
  workflow_dispatch:

jobs:
  build-mac:
    runs-on: macos-14  # Apple Silicon
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: npm ci
      - run: bash scripts/build-mac.sh
      - uses: actions/upload-artifact@v4
        with:
          name: mac-dmg
          path: release/*.dmg

  build-win:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: npm ci
      - run: .\scripts\build-win.ps1
      - uses: actions/upload-artifact@v4
        with:
          name: win-installer
          path: release/*.exe
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/build.yml
git commit -m "ci: add GitHub Actions workflow for desktop builds"
```

---

## Verification Checklist

After all tasks are complete, verify:

- [ ] macOS DMG builds successfully
- [ ] macOS app launches and runs without errors
- [ ] Windows NSIS installer builds successfully
- [ ] Windows app launches and runs without errors
- [ ] Playwright web agent works in packaged app (Chromium launches)
- [ ] Settings persist across app restarts
- [ ] CAD generation works in packaged app
- [ ] No console errors in Electron DevTools
- [ ] Backend starts automatically on app launch
- [ ] Backend is killed when app closes
- [ ] App handles missing API keys gracefully (settings panel opens)
- [ ] DMG has proper drag-to-Applications layout
- [ ] NSIS installer creates desktop/start menu shortcuts
