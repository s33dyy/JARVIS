# JARVIS Feature Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all broken features and integrate missing functionality so JARVIS is a fully functional desktop assistant.

**Architecture:** Fix existing bugs first (hand tracking, settings), then integrate missing features (dependency auto-install, self-improvement audit loop, Ollama auto-provision). All changes are in `ada_v2/`.

**Tech Stack:** React (frontend), Python FastAPI + Socket.IO (backend), PyInstaller (bundling), MediaPipe (hand tracking), Gemini API + Ollama (LLM)

---

## Task 1: Fix Hand Tracking in Production Bundle

**Files:**
- Modify: `ada_v2/src/App.jsx:697,715`

The `new URL('./hand_landmarker.task', import.meta.url)` resolves to `dist/assets/hand_landmarker.task` but the file is at `dist/hand_landmarker.task`. Fix by copying the file into `dist/assets/` during build, or use a simpler path strategy.

- [ ] **Step 1: Fix the URL resolution**

In `ada_v2/src/App.jsx`, replace the `new URL()` approach with a direct path that works in both dev and production:

```javascript
// Line 697 - Replace:
const modelUrl = new URL('./hand_landmarker.task', import.meta.url).href;

// With:
const isElectron = window.navigator.userAgent.includes('Electron');
const modelUrl = isElectron
    ? new URL('/hand_landmarker.task', window.location.href).href
    : new URL('./hand_landmarker.task', import.meta.url).href;
```

- [ ] **Step 2: Copy hand_landmarker.task to dist/assets/**

Add to `ada_v2/package.json` build script or create a post-build hook:

```bash
# After vite build, copy the model file to assets/
cp ada_v2/public/hand_landmarker.task ada_v2/dist/assets/
```

- [ ] **Step 3: Test in dev mode**

Run: `cd ada_v2 && npm run dev`
Open browser, enable hand tracking → should work (no change from before)

- [ ] **Step 4: Build and test in production**

Run: `cd ada_v2 && npm run build`
Verify `dist/assets/hand_landmarker.task` exists.

---

## Task 2: Fix Settings Not Persisting

**Files:**
- Modify: `ada_v2/src/components/SettingsWindow.jsx:466-468`

The cursor sensitivity slider only updates React state, never saves to backend.

- [ ] **Step 1: Fix cursor sensitivity save**

In `SettingsWindow.jsx`, find the cursor sensitivity slider (around line 466). Change the `onChange` handler to also emit to the backend:

```jsx
// Line ~466 - Replace:
onChange={(e) => setCursorSensitivity(parseFloat(e.target.value))}

// With:
onChange={(e) => {
    const val = parseFloat(e.target.value);
    setCursorSensitivity(val);
    socket.emit('update_settings', { cursor_sensitivity: val });
}}
```

- [ ] **Step 2: Add cursor_sensitivity to DEFAULT_SETTINGS**

In `ada_v2/backend/server.py`, find `DEFAULT_SETTINGS` (around line 77). Add:

```python
"cursor_sensitivity": 2.0,
```

- [ ] **Step 3: Add settings_saved confirmation toast**

In `ada_v2/src/App.jsx`, find where socket events are registered (around line 389). Add a listener:

```javascript
socket.on('settings_saved', (data) => {
    console.log('[Settings] Saved successfully');
    // Optional: show a brief toast notification
});
```

- [ ] **Step 4: Test**

Launch app → Settings → change cursor sensitivity → restart app → verify value persists.

---

## Task 3: Auto-Install Missing Packages on Startup

**Files:**
- Modify: `ada_v2/backend/server.py:220-228`

Currently only logs missing packages. Should auto-install.

- [ ] **Step 1: Add auto-install to startup event**

In `server.py`, find the startup event (around line 220). Replace the log-only block:

```python
@app.on_event("startup")
async def startup_event():
    global authenticator
    # ... existing code ...

    # Check dependencies
    missing = dep_manager.check_all()
    if missing.get("packages"):
        print(f"[JARVIS] Missing packages: {missing['packages']}")
        # Auto-install missing packages
        try:
            success = dep_manager.install_missing(missing["packages"])
            if success:
                print(f"[JARVIS] Successfully installed missing packages")
            else:
                print(f"[JARVIS] Some packages failed to install")
        except Exception as e:
            print(f"[JARVIS] Auto-install failed: {e}")
    if missing.get("keys"):
        print(f"[JARVIS] Missing API keys: {missing['keys']}")
```

- [ ] **Step 2: Add missing packages banner to frontend**

In `App.jsx`, find the existing missing keys banner (around line 1533). Add a similar banner for missing packages:

```jsx
{missingPackages.length > 0 && (
    <div className="missing-packages-banner">
        <span>Missing packages: {missingPackages.join(', ')}</span>
        <button onClick={() => socket.emit('install_dependencies')}>
            Install Now
        </button>
    </div>
)}
```

- [ ] **Step 3: Test**

Remove a pip package temporarily → restart backend → verify it auto-installs.

---

## Task 4: Implement Self-Improvement Audit Loop

**Files:**
- Modify: `ada_v2/backend/ada.py` (add interaction counter)
- Modify: `ada_v2/backend/self_improvement_agent.py` (read auto_apply_patches setting)

The `audit_every_n` setting exists but no code counts interactions or triggers audits.

- [ ] **Step 1: Add interaction counter to AudioLoop**

In `ada.py`, find `AudioLoop.__init__` (around line 340). Add:

```python
self._interaction_count = 0
self._audit_every_n = SETTINGS.get("self_improvement", {}).get("audit_every_n", 20)
self._self_improve_enabled = SETTINGS.get("self_improvement", {}).get("enabled", True)
```

- [ ] **Step 2: Increment counter and trigger audit**

In `ada.py`, find where user messages are processed (in the `receive_audio` or main loop). Add after processing each user message:

```python
self._interaction_count += 1
if (self._self_improve_enabled and
    self._interaction_count % self._audit_every_n == 0 and
    self.self_improve_agent):
    asyncio.create_task(self.handle_self_improve(
        f"Auto-audit: Review recent interactions and suggest improvements. "
        f"This was triggered after {self._interaction_count} interactions."
    ))
```

- [ ] **Step 3: Implement auto-apply patches**

In `self_improvement_agent.py`, find the `improve()` method (around line 386). Add auto-apply logic:

```python
# At the start of improve(), check auto_apply_patches setting
auto_apply = SETTINGS.get("self_improvement", {}).get("auto_apply_patches", False)
if auto_apply:
    # Skip confirmation for file writes
    self._auto_apply = True
else:
    self._auto_apply = False
```

Then in the tool execution section, when processing `write_file` or `patch_file` calls, check `self._auto_apply` to skip confirmation.

- [ ] **Step 4: Test**

Set `audit_every_n: 5` in settings → send 5 messages → verify self-improvement triggers automatically.

---

## Task 5: Ollama Auto-Provision on Startup

**Files:**
- Modify: `ada_v2/backend/server.py` (startup event)
- Modify: `ada_v2/backend/dependency_manager.py` (add Ollama check)

Ollama exists but is never auto-installed. Should check on startup and install if needed.

- [ ] **Step 1: Add Ollama check to DependencyManager**

In `dependency_manager.py`, add a method:

```python
def check_ollama(self) -> bool:
    """Check if Ollama is installed and running."""
    import subprocess
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

def ensure_ollama(self) -> bool:
    """Install and start Ollama if not available."""
    if self.check_ollama():
        return True
    try:
        from ollama_manager import OllamaManager
        manager = OllamaManager()
        return manager.ensure_ready()
    except Exception as e:
        print(f"[JARVIS] Ollama auto-setup failed: {e}")
        return False
```

- [ ] **Step 2: Call from startup event**

In `server.py`, after dependency check:

```python
# Auto-provision Ollama if preferred engine is local
preferred = SETTINGS.get("preferred_engine", "auto")
if preferred in ("local", "auto"):
    dep_manager.ensure_ollama()
```

- [ ] **Step 3: Test**

Uninstall Ollama → restart backend → verify it auto-installs.

---

## Task 6: Bundle MediaPipe WASM Locally

**Files:**
- Modify: `ada_v2/vite.config.js`
- Modify: `ada_v2/src/App.jsx:707`

Hand tracking loads WASM from CDN. Should be bundled for offline use.

- [ ] **Step 1: Download WASM files**

```bash
cd ada_v2/public
mkdir -p mediapipe-wasm
curl -L "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0/wasm/vision_wasm_internal.wasm" -o mediapipe-wasm/vision_wasm_internal.wasm
curl -L "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0/wasm/vision_wasm_internal.js" -o mediapipe-wasm/vision_wasm_internal.js
# Download other required WASM files as needed
```

- [ ] **Step 2: Update App.jsx to use local WASM**

```javascript
// Line 707 - Replace CDN URL with local path:
const vision = await FilesetResolver.forVisionTasks(
    isElectron
        ? './mediapipe-wasm'  // Local path in production
        : "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0/wasm"  // CDN in dev
);
```

- [ ] **Step 3: Test offline**

Disconnect from internet → launch app → enable hand tracking → should work.

---

## Task 7: Fix Settings Merge Override Bug

**Files:**
- Modify: `ada_v2/backend/server.py:149`

Bundled defaults can override user preferences during merge.

- [ ] **Step 1: Fix the merge logic**

In `server.py`, find `load_settings()` (around line 134). Fix line 149:

```python
# Line 149 - Replace:
elif k in SETTINGS and not SETTINGS[k] and v

# With:
elif k in SETTINGS and SETTINGS[k] is None and v
```

This ensures only `None` values are overridden by defaults, not `False` or `0`.

- [ ] **Step 2: Test**

Set `face_auth_enabled: false` in settings → restart → verify it stays `false`.

---

## Task 8: Clean Up Dead Code

**Files:**
- Modify: `ada_v2/backend/ada.py:1074-1084`

Duplicate confirmation block.

- [ ] **Step 1: Remove duplicate**

In `ada.py`, find the duplicate `if not confirmed:` block (around line 1074-1084). Delete the entire duplicate block.

- [ ] **Step 2: Verify no regressions**

Test that tool confirmation still works correctly.

---

## Execution Order

1. Task 1 (Hand tracking) - Quick fix, high impact
2. Task 2 (Settings) - Quick fix, high impact
3. Task 7 (Settings merge) - Quick fix, high impact
4. Task 8 (Dead code) - Quick cleanup
5. Task 3 (Auto-install) - Medium effort, high impact
6. Task 5 (Ollama auto-provision) - Medium effort, high impact
7. Task 4 (Self-improvement audit) - Medium effort, high impact
8. Task 6 (Bundle WASM) - Medium effort, medium impact

## Testing Strategy

After each task:
1. Run lint/typecheck if available
2. Build frontend: `cd ada_v2 && npm run build`
3. Rebuild backend: `cd ada_v2/backend && DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib ../.venv/bin/python3 -m PyInstaller jarvis.spec --distpath ../dist-py -y`
4. Copy to app: `cp dist-py/jarvis_server/jarvis_server /Applications/J.A.R.V.I.S.app/Contents/Resources/backend/jarvis_server/`
5. Copy frontend: `cp -R dist/* /Applications/J.A.R.V.I.S.app/Contents/Resources/app.asar.unpacked/` (or rebuild asar)
6. Launch and test manually
