#!/usr/bin/env bash
# ============================================================
#  build-mac.sh — Build J.A.R.V.I.S .dmg for macOS
#  Usage: bash scripts/build-mac.sh
#  Output: release/J.A.R.V.I.S-1.0.0-arm64.dmg (and x64)
# ============================================================
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$PROJECT_ROOT/.venv"
PYTHON="$VENV/bin/python3"
PIP="$VENV/bin/pip"

export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib:${DYLD_LIBRARY_PATH:-}"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   J.A.R.V.I.S  macOS Build Script           ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Step 1: Ensure venv exists ─────────────────────────────
if [ ! -f "$PYTHON" ]; then
    echo "[1/7] Creating virtual environment..."
    python3 -m venv "$VENV"
fi

# ── Step 2: Install / upgrade Python deps ──────────────────
echo "[2/7] Installing Python dependencies..."
$PIP install --upgrade pip -q
$PIP install pyinstaller -q
$PIP install \
    fastapi uvicorn python-socketio aiohttp httpx \
    google-genai pyaudio mediapipe opencv-python-headless \
    python-dotenv pillow psutil numpy \
    edge-tts faster-whisper \
    build123d \
    playwright kasa \
    -q 2>&1 | tail -5

# ── Step 3: Install playwright browsers (needed for web agent) ─
echo "[3/7] Installing Playwright browsers..."
$VENV/bin/playwright install chromium --with-deps 2>/dev/null || true

# ── Step 4: Build Python backend with PyInstaller ──────────
echo "[4/7] Building Python backend (PyInstaller)..."
cd "$PROJECT_ROOT/backend"
"$VENV/bin/pyinstaller" jarvis.spec \
    --distpath "$PROJECT_ROOT/dist-py" \
    --workpath "$PROJECT_ROOT/.pyibuild" \
    --noconfirm \
    --clean
echo "       Backend binary: dist-py/jarvis_server/jarvis_server ✓"

# ── Step 5: Bundle Playwright browsers ──────────────────────
echo "[5/7] Bundling Playwright Chromium browsers..."
bash "$PROJECT_ROOT/scripts/bundle-playwright.sh"

# ── Step 6: Build React frontend ───────────────────────────
echo "[6/7] Building React frontend..."
cd "$PROJECT_ROOT"
npm run build
echo "       Frontend: dist/ ✓"

# ── Step 7: Package with electron-builder ──────────────────
echo "[7/7] Packaging with electron-builder..."
npx electron-builder --mac --publish never

echo ""
echo "✅ Build complete! DMG is in: release/"
ls "$PROJECT_ROOT/release/"*.dmg 2>/dev/null || true
echo ""
echo "⚠️  First launch on macOS: Right-click → Open (for unsigned app)"
