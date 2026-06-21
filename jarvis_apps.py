"""
jarvis_apps.py
--------------
App Management module for opening and installing applications via macOS/Homebrew.
"""

import subprocess
import os

def open_app(app_name: str) -> str:
    """
    Attempt to open an application on macOS using 'open -a'.
    Returns a success message, or a prompt suggesting installation via Homebrew.
    """
    try:
        # Check if we are on macOS
        if os.name != 'posix':
            return f"I can only open apps on macOS at this time, sir."
            
        result = subprocess.run(
            ["open", "-a", app_name],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return f"Opening {app_name}, sir."
        else:
            return f"I couldn't find {app_name} on your system, sir. Shall I attempt to install it using Homebrew?"
    except Exception as e:
        return f"Failed to open {app_name}: {e}"

def install_app(app_name: str) -> str:
    """
    Attempts to install the application using Homebrew Cask.
    """
    try:
        # Check if brew is installed
        brew_check = subprocess.run(["which", "brew"], capture_output=True)
        if brew_check.returncode != 0:
            return "Homebrew is not installed on your Mac, sir. I cannot automatically install apps without it."
            
        # Clean up app name for brew (e.g. "Google Chrome" -> "google-chrome")
        cask_name = app_name.lower().replace(" ", "-")
        
        subprocess.Popen(["brew", "install", "--cask", cask_name])
        return f"I have started the Homebrew installation for {app_name} in the background, sir."
    except Exception as e:
        return f"Failed to initiate installation for {app_name}: {e}"
