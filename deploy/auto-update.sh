#!/bin/bash
# ChoreGremlin Auto-Update Script
# Runs periodically via systemd timer to pull latest changes and restart the service.

set -e

APP_DIR="/opt/choregremlin"
VENV_DIR="$APP_DIR/venv"
DB_PATH="${CHOREGREMLIN_DATA_DIR:-$APP_DIR/data}/choregremlin.db"

cd "$APP_DIR" || exit 1

# Check if auto-update is enabled in the database
AUTO_UPDATE=$("$VENV_DIR/bin/python3" -c "
import sqlite3, sys, os
db_path = os.environ.get('CHOREGREMLIN_DATA_DIR', '$APP_DIR/data') + '/choregremlin.db'
try:
    conn = sqlite3.connect(db_path)
    row = conn.execute(\"SELECT value FROM settings WHERE key='auto_update_enabled'\").fetchone()
    print(row[0] if row else '1')
    conn.close()
except Exception:
    print('1')
" 2>/dev/null)

if [ "$AUTO_UPDATE" != "1" ]; then
    echo "Auto-update is disabled. Skipping."
    exit 0
fi

echo "[$(date)] Checking for ChoreGremlin updates..."

if [ -d "$APP_DIR/.git" ]; then
    git fetch origin
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null)

    if [ "$LOCAL" = "$REMOTE" ]; then
        echo "[$(date)] Already up to date."
        exit 0
    fi

    echo "[$(date)] New version found. Updating..."
    git pull origin main 2>/dev/null || git pull origin master
else
    echo "[$(date)] Not a git repo. Skipping git pull."
fi

# Install/update Python dependencies
if [ -f "$APP_DIR/requirements.txt" ]; then
    echo "[$(date)] Installing dependencies..."
    "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q 2>/dev/null || true
fi

# Restart the service
echo "[$(date)] Restarting ChoreGremlin service..."
systemctl restart choregremlin.service

echo "[$(date)] Update complete."
