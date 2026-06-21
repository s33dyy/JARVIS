# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += collect_data_files('certifi')


a = Analysis(
    ['jarvis_ui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['jarvis_todoist', 'jarvis_messaging', 'jarvis_vision', 'jarvis_browser', 'jarvis_apps', 'jarvis_youtube', 'sounddevice', 'numpy', 'openwakeword', 'jarvis_actions', 'jarvis_context', 'jarvis_autonomous', 'jarvis_reminders', 'jarvis_speak', 'jarvis_memory', 'jarvis_agent_monitor', 'jarvis_google', 'jarvis_obsidian', 'jarvis_sync', 'jarvis_patterns', 'jarvis_listen', 'jarvis_llm', 'jarvis_crm', 'customtkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JARVIS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='JARVIS',
)
app = BUNDLE(
    coll,
    name='JARVIS.app',
    icon=None,
    bundle_identifier=None,
)
