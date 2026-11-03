#!/bin/bash
# ─────────────────────────────────────────────────────────────
# R&D Proposal Monitor — Start Script
# Launches both the scraper and the API server in the background
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$SCRIPT_DIR/backend"
LOG_DIR="$SCRIPT_DIR/data"

mkdir -p "$LOG_DIR"

echo "================================================="
echo " R&D Proposal Monitor"
echo "================================================="

# Ensure virtual environment and dependencies exist
VENV_DIR="$BACKEND/venv"
PYTHON_BIN="$VENV_DIR/bin/python3"

if [ ! -f "$PYTHON_BIN" ]; then
    echo "[0/2] Creating virtual environment and installing dependencies..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -r "$BACKEND/requirements.txt"
fi

# Kill existing processes if any
pkill -f "scraper.py" 2>/dev/null
pkill -f "api_server.py" 2>/dev/null
sleep 1

# Start scraper
echo "[1/2] Starting scraper (5-minute scan interval)..."
setsid nohup "$PYTHON_BIN" "$BACKEND/scraper.py" >> "$LOG_DIR/scraper.log" 2>&1 &
SCRAPER_PID=$!
echo "      Scraper PID: $SCRAPER_PID"

# Start API server
echo "[2/2] Starting API server on http://localhost:5050..."
setsid nohup "$PYTHON_BIN" "$BACKEND/api_server.py" >> "$LOG_DIR/api.log" 2>&1 &
API_PID=$!
echo "      API PID: $API_PID"

sleep 2

echo ""
echo "Both services running."
echo "Open frontend/dashboard.html in your browser."
echo ""
echo "To stop: ./stop.sh"
echo "Logs:    data/scraper.log | data/api.log"
echo "================================================="
