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
