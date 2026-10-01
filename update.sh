#!/bin/bash
# ChoreGremlin - Update Script
# Pulls the latest code, updates dependencies, and restarts the service.
# Usage: sudo bash update.sh  OR  the systemd timer runs this automatically.

set -e

APP_DIR="/opt/choregremlin"
VENV_DIR="$APP_DIR/venv"
SERVICE_NAME="choregremlin"

cd "$APP_DIR" || exit 1

echo "[$(date)] Checking for ChoreGremlin updates..."

if [ ! -d "$APP_DIR/.git" ]; then
    echo "[$(date)] Not a git repo. Cannot auto-update."
    exit 0
fi

git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "[$(date)] Already up to date."
    exit 0
fi

echo "[$(date)] New version found. Updating..."
git pull origin main 2>/dev/null || git pull origin master

echo "[$(date)] Updating dependencies..."
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q 2>/dev/null || true

echo "[$(date)] Restarting service..."
systemctl restart "$SERVICE_NAME"

echo "[$(date)] Update complete."
