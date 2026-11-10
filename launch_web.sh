#!/bin/bash
cd ~/dev-projects/chores-app

if [ ! -d "venv" ]; then
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt --quiet 2>/dev/null || true
else
    source venv/bin/activate
fi

echo "=== Starting Chore Gremlin Web App ==="
echo "Local URL: http://127.0.0.1:8473"
echo "Closing this terminal window or pressing Ctrl+C will stop the app."
echo "------------------------------------------------------------------"

# Run python in the foreground so closing the window kills the process
python3 app.py
