# J.A.R.V.I.S — Desktop AI Assistant

## Quick Start

### Windows
1. Download and extract the zip
2. Run `scripts\build-win.bat`
3. Installer will be in `release\`

### macOS
1. Download and extract the zip
2. Run `bash scripts/build-mac.sh`
3. DMG will be in `release/`

## Requirements

- **Python 3.11+** ([python.org](https://python.org/downloads))
- **Node.js 20+** ([nodejs.org](https://nodejs.org))
- **Gemini API Key** (free tier works, get one at [aistudio.google.com](https://aistudio.google.com/apikey))

## Optional
- **Ollama** — local fallback when Gemini quota is exceeded ([ollama.com](https://ollama.com))

## Features

- Voice conversation with Gemini Live
- Web agent (browse the web via voice commands)
- CAD/3D model generation (build123d)
- Hand tracking (MediaPipe)
- Smart home control (TP-Link Kasa)
- Self-improvement agent
- Local Ollama fallback

## Configuration

Settings are saved to:
- **Windows**: `%APPDATA%\J.A.R.V.I.S\settings.json`
- **macOS**: `~/Library/Application Support/J.A.R.V.I.S/settings.json`

## License

ISC
