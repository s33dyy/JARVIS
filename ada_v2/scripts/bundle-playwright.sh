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
