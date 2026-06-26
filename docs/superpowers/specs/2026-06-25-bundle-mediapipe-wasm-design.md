# Bundle MediaPipe WASM Locally

**Date:** 2026-06-25

## Problem

Hand tracking loads WASM files from CDN (`cdn.jsdelivr.net`). In Electron production builds, this prevents offline use.

## Solution

Download WASM files to `ada_v2/public/mediapipe-wasm/` and update `App.jsx` to use local paths in Electron/production.

## Changes

### 1. Download WASM Files
- Download `vision_wasm_internal.wasm` and `vision_wasm_internal.js` from MediaPipe tasks-vision@0.10.0
- Place in `ada_v2/public/mediapipe-wasm/`
- Vite copies public files to `dist/` on build

### 2. Update App.jsx (line 716-718)
```javascript
const vision = await FilesetResolver.forVisionTasks(
    isElectron
        ? './mediapipe-wasm'
        : "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0/wasm"
);
```

## Verification

1. Build app (`npm run build`)
2. Verify `dist/mediapipe-wasm/` contains WASM files
3. Disconnect from internet → launch app → enable hand tracking → should work
