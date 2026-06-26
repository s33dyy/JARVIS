# -*- mode: python ; coding: utf-8 -*-
# jarvis.spec — PyInstaller spec for J.A.R.V.I.S backend
# Run from the project root:  pyinstaller backend/jarvis.spec --distpath dist-py
# Or via npm run build:backend:mac / build:backend:win

import sys
import os
from pathlib import Path

HERE = Path(SPECPATH)  # backend/
ROOT = HERE.parent     # project root

block_cipher = None

# ── Hidden imports (packages that PyInstaller misses via introspection) ─────────
hidden_imports = [
    # FastAPI / Starlette / SocketIO
    'uvicorn', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
    'starlette', 'starlette.middleware', 'starlette.routing',
    'fastapi', 'python_socketio', 'socketio', 'socketio.async_server',
    'engineio', 'engineio.async_drivers', 'engineio.async_drivers.aiohttp',
    # Google AI / Gemini
    'google.genai', 'google.auth', 'google.api_core', 'google.protobuf',
    # ML / Audio
    'pyaudio', 'mediapipe', 'cv2', 'PIL', 'PIL.Image',
    'matplotlib', 'matplotlib.pyplot',
    # Build123d / CadQuery for CAD
    'build123d', 'cadquery', 'OCP',
    # Browser / Web agent
    'playwright', 'playwright.async_api',
    # Smart home
    'kasa',
    # HTTP / async
    'aiohttp', 'aiofiles', 'httpx', 'anyio',
    # Utilities
    'dotenv', 'psutil', 'numpy', 'scipy',
    # Ollama / local AI
    'aiohttp',
    # TTS
    'edge_tts',
    # STT
    'faster_whisper',
    # Others
    'json', 'asyncio', 'traceback', 'struct', 'math',
    # Additional imports discovered during testing
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

# ── Data files to bundle (non-Python assets) ────────────────────────────────────
datas = [
    # Include the entire backend folder (settings.json, persona file, etc.)
    (str(HERE / 'settings.json'), 'backend'),
    (str(HERE), 'backend'),
]

# mediapipe model files
try:
    import mediapipe
    mp_dir = Path(mediapipe.__file__).parent
    datas.append((str(mp_dir / 'modules'), 'mediapipe/modules'))
except ImportError:
    pass

# build123d package (PyInstaller misses it via introspection)
try:
    import build123d
    bp = Path(build123d.__file__).parent
    datas.append((str(bp), 'build123d'))
except ImportError:
    pass

# ── Analysis ─────────────────────────────────────────────────────────────────────
a = Analysis(
    [str(HERE / 'server.py')],
    pathex=[str(HERE), str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt5', 'PyQt6', 'wx'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='jarvis_server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,    # Keep console for logging; can flip to False for silent
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'assets' / 'icon.icns') if sys.platform == 'darwin' else str(ROOT / 'assets' / 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='jarvis_server',
)
