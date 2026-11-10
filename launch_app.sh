#!/bin/bash
cd ~/dev-projects/chores-app

# Locate opencode binary path
OPENCODE_BIN=$(which opencode 2>/dev/null || echo "$HOME/.opencode/bin/opencode")
if [ ! -x "$OPENCODE_BIN" ]; then
    OPENCODE_BIN="$HOME/.local/bin/opencode"
fi

echo "=== [1/3] Checking OpenCode for Updates ==="
"$OPENCODE_BIN" --update 2>/dev/null || true

echo "=== [2/3] Starting Chore Gremlin Web App ==="
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt --quiet 2>/dev/null || true

# Start Flask app in background
python3 app.py &
APP_PID=$!

echo "=== [3/3] Launching OpenCode AI Workspace ==="
echo "Web interface live at http://127.0.0.1:8473"
echo "------------------------------------------------------------------"

# Run OpenCode using full executable path
"$OPENCODE_BIN"

# Clean up background Flask process when OpenCode exits
kill $APP_PID 2>/dev/null
