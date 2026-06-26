import sys
import asyncio

# Fix for asyncio subprocess support on Windows
# MUST BE SET BEFORE OTHER IMPORTS
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import socketio
import uvicorn
from fastapi import FastAPI
import asyncio
import threading
import sys
import os
import json
from datetime import datetime
from pathlib import Path



# Ensure we can import ada
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import ada
from authenticator import FaceAuthenticator
from kasa_agent import KasaAgent
from engine_router import EngineRouter
from dependency_manager import DependencyManager

# Create a Socket.IO server
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
app_socketio = socketio.ASGIApp(sio, app)

import signal

# --- SHUTDOWN HANDLER ---
def signal_handler(sig, frame):
    print(f"\n[SERVER] Caught signal {sig}. Exiting gracefully...")
    # Clean up audio loop
    if audio_loop:
        try:
            print("[SERVER] Stopping Audio Loop...")
            audio_loop.stop() 
        except:
            pass
    # Force kill
    print("[SERVER] Force exiting...")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Global state
audio_loop = None
loop_task = None
authenticator = None
kasa_agent = KasaAgent()

# Settings file: writable user-data dir in prod, next to server.py in dev
_here = os.path.dirname(os.path.abspath(__file__))
_userdata = os.environ.get("JARVIS_USERDATA", "")
if _userdata and os.path.isdir(_userdata):
    SETTINGS_FILE = os.path.join(_userdata, "settings.json")
    # Seed from bundled default on first run
    _bundled_settings = os.path.join(_here, "settings.json")
    if not os.path.exists(SETTINGS_FILE) and os.path.exists(_bundled_settings):
        import shutil
        shutil.copy(_bundled_settings, SETTINGS_FILE)
        print(f"[JARVIS] Seeded settings to: {SETTINGS_FILE}")
else:
    SETTINGS_FILE = os.path.join(_here, "settings.json")

print(f"[JARVIS] Settings file: {SETTINGS_FILE}")

DEFAULT_SETTINGS = {
    "gemini_api_key": "",
    "openrouter_api_key": "",
    "nvidia_api_key": "",
    "local_model_path": "",
    "preferred_engine": "auto",
    "ollama_model": "auto",
    "voice": "Aoede",
    "face_auth_enabled": False,
    "camera_flipped": False,
    "cursor_sensitivity": 2.0,
    "tool_permissions": {
        "generate_cad": True,
        "run_web_agent": True,
        "write_file": True,
        "read_directory": True,
        "read_file": True,
        "create_project": True,
        "switch_project": True,
        "list_projects": True,
        "self_improve": True,
        "run_terminal": True,
        "run_python_code": True,
        "install_package": True,
    },
    "self_improvement": {
        "enabled": True,
        "audit_every_n": 20,
        "auto_apply_patches": False,
        "opencode_model": "nvidia/llama-3.1-nemotron-ultra-253b-v1"
    },
    "printers": [],
    "kasa_devices": []
}

def _get_gemini_api_key():
    """Get Gemini API key from the active settings (handles user-data dir)."""
    return SETTINGS.get('gemini_api_key', '').strip()

SETTINGS = DEFAULT_SETTINGS.copy()

def load_settings():
    global SETTINGS
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                for k, v in loaded.items():
                    if k == "tool_permissions" and isinstance(v, dict):
                         SETTINGS["tool_permissions"].update(v)
                         if "update_persona" in v and "self_improve" not in v:
                             SETTINGS["tool_permissions"]["self_improve"] = v["update_persona"]
                    else:
                        SETTINGS[k] = v
            print(f"[JARVIS] Loaded settings from {SETTINGS_FILE}")
        except Exception as e:
            print(f"[JARVIS] Error loading settings: {e}")

    # Merge any non-empty values from root backend/settings.json (first-run seeding)
    _bundled = os.path.join(_here, "settings.json")
    if os.path.exists(_bundled):
        try:
            with open(_bundled, 'r') as f:
                bundled = json.load(f)
            changed = False
            for k, v in bundled.items():
                if k == "tool_permissions" and isinstance(v, dict):
                    continue
                if isinstance(v, dict) and k in SETTINGS and isinstance(SETTINGS[k], dict):
                    for sk, sv in v.items():
                        if sk not in SETTINGS[k] or SETTINGS[k][sk] is None:
                            SETTINGS[k][sk] = sv
                            changed = True
                elif k in SETTINGS and SETTINGS[k] is None and v:
                    SETTINGS[k] = v
                    changed = True
            if changed:
                save_settings()
                print(f"[JARVIS] Merged missing keys from root settings.json")
        except Exception:
            pass

def save_settings():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(SETTINGS, f, indent=4)
        print(f"[JARVIS] Settings saved to: {SETTINGS_FILE}")
    except Exception as e:
        print(f"[JARVIS] Error saving settings: {e}")

def apply_settings_to_env():
    """Set all API keys and config from settings.json into os.environ."""
    env_map = {
        "gemini_api_key": "GEMINI_API_KEY",
        "openrouter_api_key": "OPENROUTER_API_KEY",
        "nvidia_api_key": "NVIDIA_API_KEY",
        "local_model_path": "LOCAL_MODEL_PATH",
    }
    for key, env_var in env_map.items():
        val = SETTINGS.get(key, "").strip()
        if val:
            os.environ[env_var] = val
        else:
            os.environ.pop(env_var, None)
    print(f"[JARVIS] Applied settings to environment variables.")

# Load on startup BEFORE any agent init
load_settings()
apply_settings_to_env()

authenticator = None
kasa_agent = KasaAgent(known_devices=SETTINGS.get("kasa_devices"))
engine_router = EngineRouter(SETTINGS)
dep_manager = DependencyManager(SETTINGS)
# tool_permissions is now SETTINGS["tool_permissions"]

@app.on_event("startup")
async def startup_event():
    import sys
    print(f"[SERVER DEBUG] Startup Event Triggered")
    print(f"[SERVER DEBUG] Python Version: {sys.version}")
    try:
        loop = asyncio.get_running_loop()
        print(f"[SERVER DEBUG] Running Loop: {type(loop)}")
        policy = asyncio.get_event_loop_policy()
        print(f"[SERVER DEBUG] Current Policy: {type(policy)}")
    except Exception as e:
        print(f"[SERVER DEBUG] Error checking loop: {e}")

    print("[SERVER] Startup: Initializing Kasa Agent...")
    await kasa_agent.initialize()

    # Probe engine availability and emit status to frontend
    print("[SERVER] Startup: Probing AI engines...")
    try:
        status = await engine_router.probe_engines()
        print(f"[SERVER] Engine status: MLX={status.mlx['available']}, "
              f"Ollama={status.ollama['available']}, "
              f"Gemini={status.gemini['available']}, "
              f"OpenRouter={status.openrouter['available']}")
    except Exception as e:
        print(f"[SERVER] Engine probe failed: {e}")

    # Check dependencies and API keys
    print("[SERVER] Startup: Checking dependencies...")
    try:
        dep_status = await dep_manager.check_all()
        if not dep_status['packages_ok']:
            print(f"[SERVER] Missing packages: {dep_status['missing_packages']}")
            try:
                result = await dep_manager.install_missing()
                if result['success']:
                    print("[SERVER] Successfully installed missing packages")
                else:
                    failed_names = [f['package'] for f in result.get('failed', [])]
                    print(f"[SERVER] Some packages failed to install: {failed_names}")
            except Exception as e:
                print(f"[SERVER] Auto-install failed: {e}")
        if not dep_status['keys_ok']:
            print(f"[SERVER] Missing API keys: {list(dep_status['missing_keys'].keys())}")
    except Exception as e:
        print(f"[SERVER] Dependency check failed: {e}")

    # Auto-provision Ollama if preferred engine is local
    preferred = SETTINGS.get("preferred_engine", "auto")
    if preferred in ("local", "auto"):
        try:
            await dep_manager.ensure_ollama()
        except Exception as e:
            print(f"[SERVER] Ollama auto-provision failed: {e}")

@app.get("/status")
async def status():
    return {"status": "running", "service": "J.A.R.V.I.S Backend"}

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")
    await sio.emit('status', {'msg': 'Connected to J.A.R.V.I.S Backend'}, room=sid)

    global authenticator
    
    # Callback for Auth Status
    async def on_auth_status(is_auth):
        print(f"[SERVER] Auth status change: {is_auth}")
        await sio.emit('auth_status', {'authenticated': is_auth})

    # Callback for Auth Camera Frames
    async def on_auth_frame(frame_b64):
        await sio.emit('auth_frame', {'image': frame_b64})

    # Initialize Authenticator if not already done
    if authenticator is None:
        authenticator = FaceAuthenticator(
            reference_image_path="reference.jpg",
            on_status_change=on_auth_status,
            on_frame=on_auth_frame
        )
    
    # Check if already authenticated or needs to start
    if authenticator.authenticated:
        await sio.emit('auth_status', {'authenticated': True})
    else:
        if SETTINGS.get("face_auth_enabled", False):
            # Can only do face auth if we have a reference image enrolled
            if authenticator.reference_landmarks is None:
                # No face enrolled — warn user and auto-authenticate
                print("[AUTH] Face auth enabled but no reference image found. Auto-authenticating.")
                await sio.emit('auth_status', {'authenticated': True})
                await sio.emit('status', {
                    'msg': '[WARN] Face auth is ON but no face is enrolled. Go to Settings > Security to enroll.'
                })
            else:
                await sio.emit('auth_status', {'authenticated': False})
                asyncio.create_task(authenticator.start_authentication_loop())
        else:
            # Face Auth Disabled — bypass
            print("Face Auth Disabled. Auto-authenticating.")
            await sio.emit('auth_status', {'authenticated': True})

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")

@sio.event
async def enroll_face(sid, data):
    """Receive a base64 JPEG from frontend, save as reference.jpg, reload landmarks."""
    global authenticator
    import base64, cv2, numpy as np

    if not data or 'image' not in data:
        await sio.emit('error', {'msg': 'enroll_face: no image data'}, room=sid)
        return

    try:
        img_bytes = base64.b64decode(data['image'])
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            await sio.emit('error', {'msg': 'enroll_face: could not decode image'}, room=sid)
            return

        ref_path = os.path.join(os.path.dirname(__file__), 'reference.jpg')
        cv2.imwrite(ref_path, frame)
        print(f"[AUTH] Reference image saved to {ref_path}")

        # Reload landmarks
        if authenticator:
            authenticator.reference_image_path = ref_path
            authenticator._load_reference()
            if authenticator.reference_landmarks is not None:
                print("[AUTH] Enrollment successful — face landmarks extracted.")
                authenticator.authenticated = True
                await sio.emit('auth_status', {'authenticated': True})
                await sio.emit('status', {'msg': 'Face enrolled successfully! Access Granted.'})
            else:
                await sio.emit('error', {'msg': 'No face detected in captured image. Try better lighting.'})
    except Exception as e:
        print(f"[AUTH] Enroll error: {e}")
        await sio.emit('error', {'msg': f'Enroll failed: {str(e)}'})

@sio.event
async def start_audio(sid, data=None):
    global audio_loop, loop_task
    
    # Optional: Block if not authenticated
    # Only block if auth is ENABLED and not authenticated
    if SETTINGS.get("face_auth_enabled", False):
        if authenticator and not authenticator.authenticated:
            print("Blocked start_audio: Not authenticated.")
            await sio.emit('error', {'msg': 'Authentication Required'})
            return

    print("Starting Audio Loop...")
    
    device_index = None
    device_name = None
    if data:
        if 'device_index' in data:
            device_index = data['device_index']
        if 'device_name' in data:
            device_name = data['device_name']
            
    print(f"Using input device: Name='{device_name}', Index={device_index}")
    
    if audio_loop:
        if loop_task and (loop_task.done() or loop_task.cancelled()):
             print("Audio loop task appeared finished/cancelled. Clearing and restarting...")
             audio_loop = None
             loop_task = None
        else:
             print("Audio loop already running. Re-connecting client to session.")
             await sio.emit('status', {'msg': 'J.A.R.V.I.S Already Running'})
             return


    # Callback to send audio data to frontend
    def on_audio_data(data_bytes):
        # We need to schedule this on the event loop
        # This is high frequency, so we might want to downsample or batch if it's too much
        asyncio.create_task(sio.emit('audio_data', {'data': list(data_bytes)}))

    # Callback to send CAL data to frontend
    def on_cad_data(data):
        info = f"{len(data.get('vertices', []))} vertices" if 'vertices' in data else f"{len(data.get('data', ''))} bytes (STL)"
        print(f"Sending CAD data to frontend: {info}")
        asyncio.create_task(sio.emit('cad_data', data))

    # Callback to send Browser data to frontend
    def on_web_data(data):
        print(f"Sending Browser data to frontend: {len(data.get('log', ''))} chars logs")
        asyncio.create_task(sio.emit('browser_frame', data))
        
    # Callback to send Transcription data to frontend
    def on_transcription(data):
        # data = {"sender": "User"|"ADA", "text": "..."}
        asyncio.create_task(sio.emit('transcription', data))

    # Callback to send Confirmation Request to frontend
    def on_tool_confirmation(data):
        # data = {"id": "uuid", "tool": "tool_name", "args": {...}}
        print(f"Requesting confirmation for tool: {data.get('tool')}")
        asyncio.create_task(sio.emit('tool_confirmation_request', data))

    # Callback to send CAD status to frontend
    def on_cad_status(status):
        # status can be: 
        # - a string like "generating" (from ada.py handle_cad_request)
        # - a dict with {status, attempt, max_attempts, error} (from CadAgent)
        if isinstance(status, dict):
            print(f"Sending CAD Status: {status.get('status')} (attempt {status.get('attempt')}/{status.get('max_attempts')})")
            asyncio.create_task(sio.emit('cad_status', status))
        else:
            # Legacy: simple string
            print(f"Sending CAD Status: {status}")
            asyncio.create_task(sio.emit('cad_status', {'status': status}))

    # Callback to send CAD thoughts to frontend (streaming)
    def on_cad_thought(thought_text):
        asyncio.create_task(sio.emit('cad_thought', {'text': thought_text}))

    def on_self_improve_status(status):
        if isinstance(status, dict):
            asyncio.create_task(sio.emit('self_improve_status', status))
        else:
            asyncio.create_task(sio.emit('self_improve_status', {'status': status}))

    def on_self_improve_log(text):
        asyncio.create_task(sio.emit('self_improve_log', {'text': text}))

    # Callback to send Project Update to frontend
    def on_project_update(project_name):
        print(f"Sending Project Update: {project_name}")
        asyncio.create_task(sio.emit('project_update', {'project': project_name}))

    # Callback to send Device Update to frontend
    def on_device_update(devices):
        # devices is a list of dicts
        print(f"Sending Kasa Device Update: {len(devices)} devices")
        asyncio.create_task(sio.emit('kasa_devices', devices))

    # Callback to send Error to frontend
    def on_error(msg):
        print(f"Sending Error to frontend: {msg}")
        asyncio.create_task(sio.emit('error', {'msg': msg}))

    # Initialize ADA
    try:
        print(f"Initializing AudioLoop with device_index={device_index}")
        audio_loop = ada.AudioLoop(
            video_mode="none", 
            on_audio_data=on_audio_data,
            on_cad_data=on_cad_data,
            on_web_data=on_web_data,
            on_transcription=on_transcription,
            on_tool_confirmation=on_tool_confirmation,
            on_cad_status=on_cad_status,
            on_cad_thought=on_cad_thought,
            on_self_improve_status=on_self_improve_status,
            on_self_improve_log=on_self_improve_log,
            on_project_update=on_project_update,
            on_device_update=on_device_update,
            on_error=on_error,

            input_device_index=device_index,
            input_device_name=device_name,
            kasa_agent=kasa_agent,
            engine_router=engine_router,
        )
        print("AudioLoop initialized successfully.")

        # Apply current permissions
        audio_loop.update_permissions(SETTINGS["tool_permissions"])
        
        # Check initial mute state
        if data and data.get('muted', False):
            print("Starting with Audio Paused")
            audio_loop.set_paused(True)

        print("Creating asyncio task for AudioLoop.run()")
        loop_task = asyncio.create_task(audio_loop.run())
        
        # Add a done callback to detect crashes and clear state for reconnect
        def handle_loop_exit(task):
            global audio_loop, loop_task
            try:
                task.result()
                print("[JARVIS] Audio loop exited cleanly.")
            except asyncio.CancelledError:
                print("[JARVIS] Audio loop cancelled.")
            except Exception as e:
                print(f"[JARVIS] Audio loop crashed: {e}")
            finally:
                # Always clear so start_audio can re-launch
                audio_loop = None
                loop_task = None
                # Notify frontend — it will show a reconnect button
                asyncio.create_task(sio.emit('status', {
                    'msg': 'J.A.R.V.I.S Disconnected',
                    'reconnect': True
                }))
        
        loop_task.add_done_callback(handle_loop_exit)
        
        print("Emitting 'J.A.R.V.I.S Started'")
        await sio.emit('status', {'msg': 'J.A.R.V.I.S Started'})

        # Load saved printers
        saved_printers = SETTINGS.get("printers", [])
        if saved_printers and audio_loop.printer_agent:
            print(f"[SERVER] Loading {len(saved_printers)} saved printers...")
            for p in saved_printers:
                audio_loop.printer_agent.add_printer_manually(
                    name=p.get("name", p["host"]),
                    host=p["host"],
                    port=p.get("port", 80),
                    printer_type=p.get("type", "moonraker"),
                    camera_url=p.get("camera_url")
                )
        
        # Start Printer Monitor
        asyncio.create_task(monitor_printers_loop())
        
    except Exception as e:
        print(f"[JARVIS] CRITICAL ERROR STARTING: {e}")
        import traceback
        traceback.print_exc()
        await sio.emit('error', {'msg': f"Failed to start: {str(e)}"})
        audio_loop = None  # Ensure we can try again


async def monitor_printers_loop():
    """Background task to query printer status periodically."""
    print("[SERVER] Starting Printer Monitor Loop")
    while audio_loop and audio_loop.printer_agent:
        try:
            agent = audio_loop.printer_agent
            if not agent.printers:
                await asyncio.sleep(5)
                continue
                
            tasks = []
            for host, printer in agent.printers.items():
                if printer.printer_type.value != "unknown":
                    tasks.append(agent.get_print_status(host))
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        pass # Ignore errors for now
                    elif res:
                        # res is PrintStatus object
                        await sio.emit('print_status_update', res.to_dict())
                        
        except asyncio.CancelledError:
            print("[SERVER] Printer Monitor Cancelled")
            break
        except Exception as e:
            print(f"[SERVER] Monitor Loop Error: {e}")
            
        await asyncio.sleep(2) # Update every 2 seconds for responsiveness

@sio.event
async def stop_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.stop() 
        print("Stopping Audio Loop")
        audio_loop = None
        await sio.emit('status', {'msg': 'J.A.R.V.I.S Stopped'})

@sio.event
async def pause_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.set_paused(True)
        print("Pausing Audio")
        await sio.emit('status', {'msg': 'Audio Paused'})

@sio.event
async def resume_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.set_paused(False)
        print("Resuming Audio")
        await sio.emit('status', {'msg': 'Audio Resumed'})

@sio.event
async def confirm_tool(sid, data):
    # data: { "id": "...", "confirmed": True/False }
    request_id = data.get('id')
    confirmed = data.get('confirmed', False)
    
    print(f"[SERVER DEBUG] Received confirmation response for {request_id}: {confirmed}")
    
    if audio_loop:
        audio_loop.resolve_tool_confirmation(request_id, confirmed)
    else:
        print("Audio loop not active, cannot resolve confirmation.")

@sio.event
async def shutdown(sid, data=None):
    """Gracefully shutdown the server when the application closes."""
    global audio_loop, loop_task, authenticator
    
    print("[SERVER] ========================================")
    print("[SERVER] SHUTDOWN SIGNAL RECEIVED FROM FRONTEND")
    print("[SERVER] ========================================")
    
    # Stop audio loop
    if audio_loop:
        print("[SERVER] Stopping Audio Loop...")
        audio_loop.stop()
        audio_loop = None
    
    # Cancel the loop task if running
    if loop_task and not loop_task.done():
        print("[SERVER] Cancelling loop task...")
        loop_task.cancel()
        loop_task = None
    
    # Stop authenticator if running
    if authenticator:
        print("[SERVER] Stopping Authenticator...")
        authenticator.stop()
    
    print("[SERVER] Graceful shutdown complete. Terminating process...")
    
    # Force exit immediately - os._exit bypasses cleanup but ensures termination
    os._exit(0)

@sio.event
async def user_input(sid, data):
    global audio_loop, loop_task
    text = data.get('text')
    print(f"[SERVER DEBUG] User input received: '{text}'")

    if not text:
        return

    if not audio_loop or not audio_loop.session:
        print("[SERVER DEBUG] Audio loop not running. Auto-starting for text input...")
        await sio.emit('status', {'msg': 'Starting J.A.R.V.I.S for text chat...'})
        await start_audio(sid, {'device_index': None})
        if not audio_loop or not audio_loop.session:
            print("[SERVER DEBUG] [Error] Failed to start audio loop. Cannot send text.")
            await sio.emit('error', {'msg': 'Failed to initialize J.A.R.V.I.S. Check API keys in Settings.'})
            return

    print(f"[SERVER DEBUG] Sending message to model: '{text}'")
    
    if audio_loop and audio_loop.project_manager:
        audio_loop.project_manager.log_chat("User", text)
        
    if audio_loop and audio_loop._latest_image_payload:
        print(f"[SERVER DEBUG] Piggybacking video frame with text input.")
        try:
            await audio_loop.session.send(input=audio_loop._latest_image_payload, end_of_turn=False)
        except Exception as e:
            print(f"[SERVER DEBUG] Failed to send piggyback frame: {e}")
            
    await audio_loop.session.send(input=text, end_of_turn=True)
    print(f"[SERVER DEBUG] Message sent to model successfully.")

import json
from datetime import datetime
from pathlib import Path

# ... (imports)

@sio.event
async def video_frame(sid, data):
    # data should contain 'image' which is binary (blob) or base64 encoded
    image_data = data.get('image')
    if image_data and audio_loop:
        # We don't await this because we don't want to block the socket handler
        # But send_frame is async, so we create a task
        asyncio.create_task(audio_loop.send_frame(image_data))

@sio.event
async def save_memory(sid, data):
    try:
        messages = data.get('messages', [])
        if not messages:
            print("No messages to save.")
            return

        # Ensure directory exists
        memory_dir = Path("long_term_memory")
        memory_dir.mkdir(exist_ok=True)

        # Generate filename
        # Use provided filename if available, else timestamp
        provided_name = data.get('filename')
        
        if provided_name:
            # Simple sanitization
            if not provided_name.endswith('.txt'):
                provided_name += '.txt'
            # Prevent directory traversal
            filename = memory_dir / Path(provided_name).name 
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = memory_dir / f"memory_{timestamp}.txt"

        # Write to file
        with open(filename, 'w', encoding='utf-8') as f:
            for msg in messages:
                sender = msg.get('sender', 'Unknown')
                text = msg.get('text', '')
        print(f"Conversation saved to {filename}")
        await sio.emit('status', {'msg': 'Memory Saved Successfully'})

    except Exception as e:
        print(f"Error saving memory: {e}")
        await sio.emit('error', {'msg': f"Failed to save memory: {str(e)}"})

@sio.event
async def upload_memory(sid, data):
    print(f"Received memory upload request")
    try:
        memory_text = data.get('memory', '')
        if not memory_text:
            print("No memory data provided.")
            return

        if not audio_loop:
             print("[SERVER DEBUG] [Error] Audio loop is None. Cannot load memory.")
             await sio.emit('error', {'msg': "System not ready (Audio Loop inactive)"})
             return
        
        if not audio_loop.session:
             print("[SERVER DEBUG] [Error] Session is None. Cannot load memory.")
             await sio.emit('error', {'msg': "System not ready (No active session)"})
             return

        # Send to model
        print("Sending memory context to model...")
        context_msg = f"System Notification: The user has uploaded a long-term memory file. Please load the following context into your understanding. The format is a text log of previous conversations:\n\n{memory_text}"
        
        await audio_loop.session.send(input=context_msg, end_of_turn=True)
        print("Memory context sent successfully.")
        await sio.emit('status', {'msg': 'Memory Loaded into Context'})

    except Exception as e:
        print(f"Error uploading memory: {e}")
        await sio.emit('error', {'msg': f"Failed to upload memory: {str(e)}"})

@sio.event
async def discover_kasa(sid):
    print(f"Received discover_kasa request")
    try:
        devices = await kasa_agent.discover_devices()
        await sio.emit('kasa_devices', devices)
        await sio.emit('status', {'msg': f"Found {len(devices)} Kasa devices"})
        
        # Save to settings
        # devices is a list of full device info dicts. minimizing for storage.
        saved_devices = []
        for d in devices:
            saved_devices.append({
                "ip": d["ip"],
                "alias": d["alias"],
                "model": d["model"]
            })
        
        # Merge with existing to preserve any manual overrides? 
        # For now, just overwrite with latest scan result + previously known if we want to be fancy,
        # but user asked for "Any new devices that are scanned are added there".
        # A simple full persistence of current state is safest.
        SETTINGS["kasa_devices"] = saved_devices
        save_settings()
        print(f"[SERVER] Saved {len(saved_devices)} Kasa devices to settings.")
        
    except Exception as e:
        print(f"Error discovering kasa: {e}")
        await sio.emit('error', {'msg': f"Kasa Discovery Failed: {str(e)}"})

@sio.event
async def iterate_cad(sid, data):
    # data: { prompt: "make it bigger" }
    prompt = data.get('prompt')
    print(f"Received iterate_cad request: '{prompt}'")
    
    if not audio_loop or not audio_loop.cad_agent:
        await sio.emit('error', {'msg': "CAD Agent not available"})
        return

    try:
        # Notify user work has started
        await sio.emit('status', {'msg': 'Iterating design...'})
        await sio.emit('cad_status', {'status': 'generating'})
        
        # Call the agent with project path
        cad_output_dir = str(audio_loop.project_manager.get_current_project_path() / "cad")
        result = await audio_loop.cad_agent.iterate_prototype(prompt, output_dir=cad_output_dir)
        
        if result:
            info = f"{len(result.get('data', ''))} bytes (STL)"
            print(f"Sending updated CAD data: {info}")
            await sio.emit('cad_data', result)
            # Save to Project
            if 'file_path' in result:
                saved_path = audio_loop.project_manager.save_cad_artifact(result['file_path'], prompt)
                if saved_path:
                    print(f"[SERVER] Saved iterated CAD to {saved_path}")

            await sio.emit('status', {'msg': 'Design updated'})
        else:
            await sio.emit('error', {'msg': 'Failed to update design'})
            
    except Exception as e:
        print(f"Error iterating CAD: {e}")
        await sio.emit('error', {'msg': f"Iteration Error: {str(e)}"})

@sio.event
async def generate_cad(sid, data):
    # data: { prompt: "make a cube" }
    prompt = data.get('prompt')
    print(f"Received generate_cad request: '{prompt}'")
    
    if not audio_loop or not audio_loop.cad_agent:
        await sio.emit('error', {'msg': "CAD Agent not available"})
        return

    try:
        await sio.emit('status', {'msg': 'Generating new design...'})
        await sio.emit('cad_status', {'status': 'generating'})
        
        # Use generate_prototype based on prompt with project path
        cad_output_dir = str(audio_loop.project_manager.get_current_project_path() / "cad")
        result = await audio_loop.cad_agent.generate_prototype(prompt, output_dir=cad_output_dir)
        
        if result:
            info = f"{len(result.get('data', ''))} bytes (STL)"
            print(f"Sending newly generated CAD data: {info}")
            await sio.emit('cad_data', result)


            # Save to Project
            if 'file_path' in result:
                saved_path = audio_loop.project_manager.save_cad_artifact(result['file_path'], prompt)
                if saved_path:
                    print(f"[SERVER] Saved generated CAD to {saved_path}")

            await sio.emit('status', {'msg': 'Design generated'})
        else:
            await sio.emit('error', {'msg': 'Failed to generate design'})
            
    except Exception as e:
        print(f"Error generating CAD: {e}")
        await sio.emit('error', {'msg': f"Generation Error: {str(e)}"})

@sio.event
async def prompt_web_agent(sid, data):
    # data: { prompt: "find xyz" }
    prompt = data.get('prompt')
    print(f"Received web agent prompt: '{prompt}'")
    
    if not audio_loop or not audio_loop.web_agent:
        await sio.emit('error', {'msg': "Web Agent not available"})
        return

    try:
        await sio.emit('status', {'msg': 'Web Agent running...'})
        
        # We assume web_agent has a run method or similar.
        # This might block the loop if not strictly async or offloaded.
        # Ideally web_agent.run is async.
        # And it should emit 'browser_snap' and logs automatically via hooks if setup.
        
        # We might need to launch this as a task if it's long running?
        # asyncio.create_task(audio_loop.web_agent.run(prompt))
        # But we want to catch errors here.
        
        # Based on typical agent design, run() is the entry point.
        await audio_loop.web_agent.run(prompt)
        
        await sio.emit('status', {'msg': 'Web Agent finished'})
        
    except Exception as e:
        print(f"Error running Web Agent: {e}")
        await sio.emit('error', {'msg': f"Web Agent Error: {str(e)}"})

@sio.event
async def discover_printers(sid):
    print("Received discover_printers request")
    
    # If audio_loop isn't ready yet, return saved printers from settings
    if not audio_loop or not audio_loop.printer_agent:
        saved_printers = SETTINGS.get("printers", [])
        if saved_printers:
            # Convert saved printers to the expected format
            printer_list = []
            for p in saved_printers:
                printer_list.append({
                    "name": p.get("name", p["host"]),
                    "host": p["host"],
                    "port": p.get("port", 80),
                    "printer_type": p.get("type", "unknown"),
                    "camera_url": p.get("camera_url")
                })
            print(f"[SERVER] Returning {len(printer_list)} saved printers (audio_loop not ready)")
            await sio.emit('printer_list', printer_list)
            return
        else:
            await sio.emit('printer_list', [])
            await sio.emit('status', {'msg': "Connect to J.A.R.V.I.S to enable printer discovery"})
            return
        
    try:
        printers = await audio_loop.printer_agent.discover_printers()
        await sio.emit('printer_list', printers)
        await sio.emit('status', {'msg': f"Found {len(printers)} printers"})
    except Exception as e:
        print(f"Error discovering printers: {e}")
        await sio.emit('error', {'msg': f"Printer Discovery Failed: {str(e)}"})

@sio.event
async def add_printer(sid, data):
    # data: { host: "192.168.1.50", name: "My Printer", type: "moonraker" }
    raw_host = data.get('host')
    name = data.get('name') or raw_host
    ptype = data.get('type', "moonraker")
    
    # Parse port if present
    if ":" in raw_host:
        host, port_str = raw_host.split(":")
        port = int(port_str)
    else:
        host = raw_host
        port = 80
    
    print(f"Received add_printer request: {host}:{port} ({ptype})")
    
    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return
        
    try:
        # Add manually
        camera_url = data.get('camera_url')
        printer = audio_loop.printer_agent.add_printer_manually(name, host, port=port, printer_type=ptype, camera_url=camera_url)
        
        # Save to settings
        new_printer_config = {
            "name": name,
            "host": host,
            "port": port,
            "type": ptype,
            "camera_url": camera_url
        }
        
        # Check if already exists to avoid duplicates
        exists = False
        for p in SETTINGS.get("printers", []):
            if p["host"] == host and p["port"] == port:
                exists = True
                break
        
        if not exists:
            if "printers" not in SETTINGS:
                SETTINGS["printers"] = []
            SETTINGS["printers"].append(new_printer_config)
            save_settings()
            print(f"[SERVER] Saved printer {name} to settings.")
        
        # Probe to confirm/correct type
        print(f"Probing {host} to confirm type...")
        # Try port 7125 (Moonraker) and 4408 (Fluidd/K1) 
        ports_to_try = [80, 7125, 4408]
        
        actual_type = "unknown"
        for port in ports_to_try:
             found_type = await audio_loop.printer_agent._probe_printer_type(host, port)
             if found_type.value != "unknown":
                 actual_type = found_type
                 # Update port if different
                 if port != 80:
                     printer.port = port
                 break
        
        if actual_type != "unknown" and actual_type != printer.printer_type:
             printer.printer_type = actual_type
             print(f"Corrected type to {actual_type.value} on port {printer.port}")
             
        # Refresh list for everyone
        printers = [p.to_dict() for p in audio_loop.printer_agent.printers.values()]
        await sio.emit('printer_list', printers)
        await sio.emit('status', {'msg': f"Added printer: {name}"})
        
    except Exception as e:
        print(f"Error adding printer: {e}")
        await sio.emit('error', {'msg': f"Failed to add printer: {str(e)}"})

@sio.event
async def print_stl(sid, data):
    print(f"Received print_stl request: {data}")
    # data: { stl_path: "path/to.stl" | "current", printer: "name_or_ip", profile: "optional" }
    
    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return
        
    try:
        stl_path = data.get('stl_path', 'current')
        printer_name = data.get('printer')
        profile = data.get('profile')
        
        if not printer_name:
             await sio.emit('error', {'msg': "No printer specified"})
             return
             
        await sio.emit('status', {'msg': f"Preparing print for {printer_name}..."})
        
        # Get current project path for resolution
        current_project_path = None
        if audio_loop and audio_loop.project_manager:
            current_project_path = str(audio_loop.project_manager.get_current_project_path())
            print(f"[SERVER DEBUG] Using project path: {current_project_path}")

        # Resolve STL path before slicing so we can preview it
        resolved_stl = audio_loop.printer_agent._resolve_file_path(stl_path, current_project_path)
        
        if resolved_stl and os.path.exists(resolved_stl):
            # Open the STL in the CAD module for preview
            try:
                import base64
                with open(resolved_stl, 'rb') as f:
                    stl_data = f.read()
                stl_b64 = base64.b64encode(stl_data).decode('utf-8')
                stl_filename = os.path.basename(resolved_stl)
                
                print(f"[SERVER] Opening STL in CAD module: {stl_filename}")
                await sio.emit('cad_data', {
                    'format': 'stl',
                    'data': stl_b64,
                    'filename': stl_filename
                })
            except Exception as e:
                print(f"[SERVER] Warning: Could not preview STL: {e}")
        
        # Progress Callback
        async def on_slicing_progress(percent, message):
            await sio.emit('slicing_progress', {
                'printer': printer_name,
                'percent': percent,
                'message': message
            })
            if percent < 100:
                 await sio.emit('status', {'msg': f"Slicing: {percent}%"})

        result = await audio_loop.printer_agent.print_stl(
            stl_path, 
            printer_name, 
            profile,
            progress_callback=on_slicing_progress,
            root_path=current_project_path
        )
        
        await sio.emit('print_result', result)
        await sio.emit('status', {'msg': f"Print Job: {result.get('status', 'unknown')}"})
        
    except Exception as e:
        print(f"Error printing STL: {e}")
        await sio.emit('error', {'msg': f"Print Failed: {str(e)}"})

@sio.event
async def get_slicer_profiles(sid):
    """Get available OrcaSlicer profiles for manual selection."""
    print("Received get_slicer_profiles request")
    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return
    
    try:
        profiles = audio_loop.printer_agent.get_available_profiles()
        await sio.emit('slicer_profiles', profiles)
    except Exception as e:
        print(f"Error getting slicer profiles: {e}")
        await sio.emit('error', {'msg': f"Failed to get profiles: {str(e)}"})

@sio.event
async def control_kasa(sid, data):
    # data: { ip, action: "on"|"off"|"brightness"|"color", value: ... }
    ip = data.get('ip')
    action = data.get('action')
    print(f"Kasa Control: {ip} -> {action}")
    
    try:
        success = False
        if action == "on":
            success = await kasa_agent.turn_on(ip)
        elif action == "off":
            success = await kasa_agent.turn_off(ip)
        elif action == "brightness":
            val = data.get('value')
            success = await kasa_agent.set_brightness(ip, val)
        elif action == "color":
            # value is {h, s, v} - convert to tuple for set_color
            h = data.get('value', {}).get('h', 0)
            s = data.get('value', {}).get('s', 100)
            v = data.get('value', {}).get('v', 100)
            success = await kasa_agent.set_color(ip, (h, s, v))
        
        if success:
            await sio.emit('kasa_update', {
                'ip': ip,
                'is_on': True if action == "on" else (False if action == "off" else None),
                'brightness': data.get('value') if action == "brightness" else None,
            })
 
        else:
             await sio.emit('error', {'msg': f"Failed to control device {ip}"})

    except Exception as e:
         print(f"Error controlling kasa: {e}")
         await sio.emit('error', {'msg': f"Kasa Control Error: {str(e)}"})

@sio.event
async def check_dependencies(sid):
    """Check for missing packages and API keys."""
    dep_manager.settings = SETTINGS
    status = await dep_manager.check_all()
    await sio.emit('dependency_status', status)

@sio.event
async def install_dependencies(sid):
    """Install missing packages in background."""
    def on_progress(info):
        asyncio.create_task(sio.emit('deps_install_progress', info))

    async def _install():
        result = await dep_manager.install_missing(on_progress=on_progress)
        await sio.emit('deps_install_complete', result)

    asyncio.create_task(_install())

@sio.event
async def get_settings(sid):
    await sio.emit('settings', SETTINGS)

@sio.event
async def update_settings(sid, data):
    # Generic update
    print(f"Updating settings: {data}")
    
    # Handle specific keys if needed
    if "tool_permissions" in data:
        SETTINGS["tool_permissions"].update(data["tool_permissions"])
        if audio_loop:
            audio_loop.update_permissions(SETTINGS["tool_permissions"])
    
    if "face_auth_enabled" in data:
        SETTINGS["face_auth_enabled"] = data["face_auth_enabled"]
        # If turned OFF, maybe emit auth status true?
        if not data["face_auth_enabled"]:
              await sio.emit('auth_status', {'authenticated': True})
              # Stop auth loop if running?
              if authenticator:
                  authenticator.stop() 

    if "camera_flipped" in data:
        SETTINGS["camera_flipped"] = data["camera_flipped"]
        print(f"[SERVER] Camera flip set to: {data['camera_flipped']}")

    if "voice" in data:
        SETTINGS["voice"] = data["voice"]
        print(f"[SERVER] J.A.R.V.I.S voice set to: {data['voice']} (takes effect on next restart)")

    # API Keys - Re-init agents on change
    api_key_fields = [
        "gemini_api_key",
        "openrouter_api_key", 
        "nvidia_api_key",
        "local_model_path"
    ]
    
    for key in api_key_fields:
        if key in data:
            key_value = data[key].strip()
            if key_value:
                SETTINGS[key] = key_value
                # Hot-swap: inject into env so ada.py's _get_api_key() sees it immediately
                env_var_map = {
                    "gemini_api_key": "GEMINI_API_KEY",
                    "openrouter_api_key": "OPENROUTER_API_KEY",
                    "nvidia_api_key": "NVIDIA_API_KEY",
                    "local_model_path": "LOCAL_MODEL_PATH"
                }
                os.environ[env_var_map[key]] = key_value
                print(f"[SERVER] {key.replace('_', ' ').title()} updated ({len(key_value)} chars).")
                
                # Re-init audio_loop with new key if it exists and exists
                if audio_loop:
                    if key == "gemini_api_key":
                        audio_loop.gemini_api_key = key_value
                    # If ada.py uses API key for anything else, it would need similar
                
                # Re-init cad_agent with new key
                if audio_loop and hasattr(audio_loop, 'cad_agent'):
                    if hasattr(audio_loop.cad_agent, '_init_client'):
                        audio_loop.cad_agent._init_client()
                    else:
                        from google import genai as _genai
                        audio_loop.cad_agent.client = _genai.Client(http_options={"api_version": "v1beta"}, api_key=_get_gemini_api_key())
            else:
                SETTINGS[key] = ""
                env_var_map = {
                    "gemini_api_key": "GEMINI_API_KEY",
                    "openrouter_api_key": "OPENROUTER_API_KEY",
                    "nvidia_api_key": "NVIDIA_API_KEY",
                    "local_model_path": "LOCAL_MODEL_PATH"
                }
                os.environ.pop(env_var_map[key], None)
                print(f"[SERVER] {key.replace('_', ' ').title()} cleared.")

    # Preferred engine changes
    if "preferred_engine" in data:
        SETTINGS["preferred_engine"] = data["preferred_engine"]
        print(f"[SERVER] Preferred engine set to: {data['preferred_engine']}")
    
    # Ollama model choice
    if "ollama_model" in data:
        SETTINGS["ollama_model"] = data["ollama_model"]
        print(f"[SERVER] Ollama model set to: {data['ollama_model']}")

    # Self improvement settings
    if "self_improvement" in data:
        SETTINGS["self_improvement"].update(data["self_improvement"])

    save_settings()
    apply_settings_to_env()
    
    # Update engine_router settings
    engine_router.settings = SETTINGS
    
    # Broadcast new full settings (mask the keys before sending to frontend)
    settings_safe = {**SETTINGS}
    for key in ["gemini_api_key", "openrouter_api_key", "nvidia_api_key"]:
        if key in settings_safe and settings_safe[key]:
            settings_safe[key] = "••••"
    await sio.emit('settings', settings_safe)
    await sio.emit('settings_saved', {'ok': True})


# Deprecated/Mapped for compatibility if frontend still uses specific events
@sio.event
async def get_tool_permissions(sid):
    await sio.emit('tool_permissions', SETTINGS["tool_permissions"])

@sio.event
async def update_tool_permissions(sid, data):
    print(f"Updating permissions (legacy event): {data}")
    SETTINGS["tool_permissions"].update(data)
    save_settings()
    
    if audio_loop:
        audio_loop.update_permissions(SETTINGS["tool_permissions"])
    # Broadcast update to all
    await sio.emit('tool_permissions', SETTINGS["tool_permissions"])

@sio.event
async def test_api_key(sid, data):
    """Test an API key by making a lightweight request."""
    provider = data.get('provider', '')
    key = data.get('key', '').strip()
    if not key:
        await sio.emit('api_key_test_result', {'provider': provider, 'ok': False, 'message': 'No key provided'})
        return

    try:
        if provider == 'gemini':
            import aiohttp as _aiohttp
            async with _aiohttp.ClientSession(timeout=_aiohttp.ClientTimeout(total=10)) as session:
                headers = {'Content-Type': 'application/json'}
                payload = {'contents': [{'parts': [{'text': 'Say hi'}]}]}
                async with session.post(
                    f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}',
                    json=payload, headers=headers
                ) as resp:
                    if resp.status == 200:
                        await sio.emit('api_key_test_result', {'provider': provider, 'ok': True, 'message': 'Gemini key is valid'})
                    else:
                        body = await resp.text()
                        await sio.emit('api_key_test_result', {'provider': provider, 'ok': False, 'message': f'HTTP {resp.status}: {body[:200]}'})
        elif provider == 'openrouter':
            import aiohttp as _aiohttp
            async with _aiohttp.ClientSession(timeout=_aiohttp.ClientTimeout(total=10)) as session:
                headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
                payload = {'model': 'mistralai/mistral-7b-instruct:free', 'messages': [{'role': 'user', 'content': 'hi'}], 'max_tokens': 5}
                async with session.post('https://openrouter.ai/api/v1/chat/completions', json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        await sio.emit('api_key_test_result', {'provider': provider, 'ok': True, 'message': 'OpenRouter key is valid'})
                    else:
                        body = await resp.text()
                        await sio.emit('api_key_test_result', {'provider': provider, 'ok': False, 'message': f'HTTP {resp.status}: {body[:200]}'})
        elif provider == 'nvidia':
            # NVIDIA keys can't be easily tested without a full integration, just check length
            if len(key) > 20:
                await sio.emit('api_key_test_result', {'provider': provider, 'ok': True, 'message': 'NVIDIA key format looks valid'})
            else:
                await sio.emit('api_key_test_result', {'provider': provider, 'ok': False, 'message': 'Key too short'})
        else:
            await sio.emit('api_key_test_result', {'provider': provider, 'ok': False, 'message': f'Unknown provider: {provider}'})
    except Exception as e:
        await sio.emit('api_key_test_result', {'provider': provider, 'ok': False, 'message': str(e)[:200]})

@sio.event
async def kill_process(sid, data):
    """Kill a running process by execution ID."""
    exec_id = data.get('id', '')
    if audio_loop and hasattr(audio_loop, 'executor'):
        await audio_loop.executor.kill_process(exec_id)
    await sio.emit('exec_killed', {'id': exec_id})

@sio.event
async def open_settings_panel(sid, data=None):
    """Frontend listens for this to open settings."""
    await sio.emit('open_settings_panel', data or {})

@sio.event
async def get_engine_status(sid):
    """Return current engine availability status."""
    try:
        status = await engine_router.probe_engines()
        await sio.emit('engine_status', status.__dict__)
    except Exception as e:
        print(f"[SERVER] Engine status probe failed: {e}")
        await sio.emit('engine_status', {
            'mlx': {'available': False},
            'ollama': {'available': False},
            'gemini': {'available': False},
            'openrouter': {'available': False},
        })

if __name__ == "__main__":
    uvicorn.run(
        app_socketio, 
        host="127.0.0.1", 
        port=8000, 
        reload=False,
        loop="asyncio",
    )
