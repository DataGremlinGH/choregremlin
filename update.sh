#!/bin/bash
# ChoreGremlin - Update Script
# Pulls the latest code, backs up the database, updates dependencies and restarts.
# Usage: sudo bash update.sh
# The systemd timer runs this automatically with CHOREGREMLIN_UPDATE_TRIGGER=auto.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${CHOREGREMLIN_APP_DIR:-$SCRIPT_DIR}"
VENV_DIR="$APP_DIR/venv"
SERVICE_NAME="choregremlin"
SERVICE_USER="${CHOREGREMLIN_SERVICE_USER:-choregremlin}"
ENV_FILE="/etc/choregremlin/choregremlin.env"

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run this script with sudo."
    exit 1
fi

if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
fi

DATA_DIR="${CHOREGREMLIN_DATA_DIR:-/var/lib/choregremlin}"
if [ ! -d "$DATA_DIR" ] && [ -d "$APP_DIR/data" ]; then
    DATA_DIR="$APP_DIR/data"
fi
DB_PATH="$DATA_DIR/choregremlin.db"

cd "$APP_DIR"

echo "[$(date)] Checking for ChoreGremlin updates..."

if [ ! -d "$APP_DIR/.git" ]; then
    echo "[$(date)] Not a git repo. Cannot update."
    exit 0
fi

if [ "${CHOREGREMLIN_UPDATE_TRIGGER:-manual}" = "auto" ] && [ -x "$VENV_DIR/bin/python3" ] && [ -f "$DB_PATH" ]; then
    AUTO_UPDATE=$("$VENV_DIR/bin/python3" - "$DB_PATH" <<'PY'
import sqlite3, sys
try:
    conn = sqlite3.connect(sys.argv[1])
    row = conn.execute("SELECT value FROM settings WHERE key='auto_update_enabled'").fetchone()
    print(row[0] if row else '1')
    conn.close()
except Exception:
    print('1')
PY
)
    if [ "$AUTO_UPDATE" != "1" ]; then
        echo "[$(date)] Auto-update is disabled in settings. Skipping."
        exit 0
    fi
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
git fetch origin "$BRANCH"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "[$(date)] Already up to date."
    exit 0
fi

echo "[$(date)] New version found. Backing up the database..."
if [ -f "$DB_PATH" ] && [ -x "$VENV_DIR/bin/python3" ]; then
    mkdir -p "$DATA_DIR/backups"
    chown "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/backups" 2>/dev/null || true
    BACKUP="$DATA_DIR/backups/pre-update-$(date +%Y%m%d-%H%M%S).db"
    "$VENV_DIR/bin/python3" - "$DB_PATH" "$BACKUP" <<'PY'
import sqlite3, sys
source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
source.close()
target.close()
PY
    chown "$SERVICE_USER:$SERVICE_USER" "$BACKUP" 2>/dev/null || true
    echo "[$(date)] Database backed up to $BACKUP"
fi

echo "[$(date)] Pulling the latest code..."
git pull --ff-only origin "$BRANCH"

echo "[$(date)] Updating dependencies..."
if [ -x "$VENV_DIR/bin/pip" ]; then
    "$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

echo "[$(date)] Restarting service..."
systemctl restart "$SERVICE_NAME"

if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "[$(date)] Update complete. Service is running."
else
    echo "[$(date)] ERROR: $SERVICE_NAME did not start. Check: journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi
