#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  JARVIS — Iron Man startup script
#  Usage: ./jarvis-start.sh
#         ./jarvis-start.sh stop
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL="mlx-community/Qwen3-0.6B-4bit"
MLX_PORT=8080
API_PORT=8001
GUI_PORT=5174

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

stop_all() {
  echo -e "${YELLOW}Shutting down JARVIS...${NC}"
  pkill -f "mlx_lm.server"  2>/dev/null || true
  pkill -f "jarvis serve"   2>/dev/null || true
  pkill -f "jarvis start"   2>/dev/null || true
  pkill -f "vite"           2>/dev/null || true
  echo -e "${GREEN}✓ All services stopped.${NC}"
  exit 0
}

[[ "${1:-}" == "stop" ]] && stop_all

echo ""
echo -e "${CYAN}"
cat << 'BANNER'
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
       Personal AI, On Personal Devices
BANNER
echo -e "${NC}"

# ── 1. MLX Inference Engine ──────────────────────────────────
echo -e "${YELLOW}[1/4] Starting MLX inference engine...${NC}"
pkill -f "mlx_lm.server" 2>/dev/null || true; sleep 1
cd "$SCRIPT_DIR"
uv run mlx_lm.server --model "$MODEL" --port $MLX_PORT \
  --chat-template-args '{"enable_thinking":false}' \
  > /tmp/jarvis_mlx.log 2>&1 &
MLX_PID=$!

# Wait for MLX to be ready (up to 30s)
for i in $(seq 1 30); do
  if curl -sf "http://localhost:$MLX_PORT/v1/models" >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ MLX ready — $MODEL${NC}"
    break
  fi
  sleep 1
done

# ── 2. Jarvis API Server ─────────────────────────────────────
echo -e "${YELLOW}[2/4] Starting Jarvis API server...${NC}"
pkill -f "jarvis serve" 2>/dev/null || true; sleep 1
uv run jarvis serve --port $API_PORT > /tmp/jarvis_api.log 2>&1 &
API_PID=$!

for i in $(seq 1 20); do
  if curl -sf "http://localhost:$API_PORT/health" >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ API server ready — http://localhost:$API_PORT${NC}"
    break
  fi
  sleep 1
done

# ── 3. Web GUI ───────────────────────────────────────────────
echo -e "${YELLOW}[3/4] Starting Web GUI...${NC}"
pkill -f "vite" 2>/dev/null || true; sleep 1
cd "$SCRIPT_DIR/frontend"
VITE_API_URL="http://localhost:$API_PORT" npm run dev -- --port $GUI_PORT --open > /tmp/jarvis_gui.log 2>&1 &
GUI_PID=$!
sleep 4
echo -e "${GREEN}  ✓ GUI ready — http://localhost:$GUI_PORT${NC}"

# ── 4. Wake-up greeting ──────────────────────────────────────
echo -e "${YELLOW}[4/4] JARVIS is online...${NC}"
say -v Daniel "Good morning, sir. All systems are operational. JARVIS is online and ready." 2>/dev/null || true

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  JARVIS is fully operational${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  🧠  MLX Engine  →  http://localhost:$MLX_PORT"
echo -e "  ⚙️   API Backend →  http://localhost:$API_PORT"
echo -e "  🖥️   Web GUI     →  http://localhost:$GUI_PORT"
echo -e ""
echo -e "  Quick commands:"
echo -e "  ${CYAN}uv run jarvis ask \"<question>\"${NC}         — ask something"
echo -e "  ${CYAN}uv run jarvis chat${NC}                     — interactive chat"
echo -e "  ${CYAN}uv run jarvis digest --fresh${NC}           — morning briefing"
echo -e "  ${CYAN}./jarvis-start.sh stop${NC}                 — shut everything down"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Keep script alive so logs stream to terminal (Ctrl+C to exit cleanly)
trap stop_all INT TERM
wait $MLX_PID
