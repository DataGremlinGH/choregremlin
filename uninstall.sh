#!/bin/bash
# ChoreGremlin - Uninstall Script
# Removes the app, service, timers, and optionally data.
# Usage: sudo bash uninstall.sh

set -e

APP_DIR="/opt/choregremlin"
SERVICE_USER="choregremlin"
ENV_FILE="/etc/choregremlin/choregremlin.env"
CADDYFILE="/etc/caddy/Caddyfile"
CADDY_BACKUP="$CADDYFILE.before-choregremlin"

BOLD='\033[1m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root: sudo bash uninstall.sh${NC}"
    exit 1
fi

PORT="8473"
DATA_DIR="/var/lib/choregremlin"
HTTPS_ENABLED="0"
if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
    PORT="${PORT:-8473}"
    DATA_DIR="${CHOREGREMLIN_DATA_DIR:-$DATA_DIR}"
    HTTPS_ENABLED="${CHOREGREMLIN_HTTPS:-0}"
fi

echo -e "${BOLD}Uninstall ChoreGremlin${NC}"
echo ""

echo -e "${YELLOW}Do you want to keep your data (database, photos, backups)?${NC}"
echo -e "  y = keep data (you can reinstall later and it will be there)"
echo -e "  n = remove everything"
read -p "Keep data? [Y/n] " KEEP_DATA
KEEP_DATA=${KEEP_DATA:-y}

echo "Stopping services..."
systemctl stop choregremlin.service 2>/dev/null || true
systemctl stop choregremlin-update.timer 2>/dev/null || true
systemctl stop choregremlin-backup.timer 2>/dev/null || true

systemctl disable choregremlin.service 2>/dev/null || true
systemctl disable choregremlin-update.timer 2>/dev/null || true
systemctl disable choregremlin-backup.timer 2>/dev/null || true

rm -f /etc/systemd/system/choregremlin.service
rm -f /etc/systemd/system/choregremlin-update.service
rm -f /etc/systemd/system/choregremlin-update.timer
rm -f /etc/systemd/system/choregremlin-backup.service
rm -f /etc/systemd/system/choregremlin-backup.timer
systemctl daemon-reload

rm -f /etc/avahi/services/choregremlin.service
ufw delete allow "$PORT/tcp" 2>/dev/null || true
if [ "$HTTPS_ENABLED" = "1" ]; then
    ufw delete allow "443/tcp" 2>/dev/null || true
    ufw delete allow "80/tcp" 2>/dev/null || true
    for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
        ufw delete allow from "$net" to any port 443 proto tcp 2>/dev/null || true
        ufw delete allow from "$net" to any port 80 proto tcp 2>/dev/null || true
    done
fi

if [ -f "$CADDYFILE" ] && grep -q 'ChoreGremlin managed' "$CADDYFILE"; then
    if [ -f "$CADDY_BACKUP" ]; then
        mv -f "$CADDY_BACKUP" "$CADDYFILE"
        systemctl restart caddy 2>/dev/null || true
    else
        rm -f "$CADDYFILE"
        systemctl disable --now caddy 2>/dev/null || true
    fi
fi

if [ "$KEEP_DATA" = "n" ] || [ "$KEEP_DATA" = "N" ]; then
    echo "Removing the app and all data..."
    rm -rf "$APP_DIR"
    case "$DATA_DIR" in
        "$APP_DIR"/*) ;;
        *) rm -rf "$DATA_DIR" ;;
    esac
    rm -rf /etc/choregremlin
    userdel "$SERVICE_USER" 2>/dev/null || true
    echo -e "${RED}ChoreGremlin and all data removed.${NC}"
else
    echo "Keeping your data, removing the app code..."
    case "$DATA_DIR" in
        "$APP_DIR"/*)
            echo -e "${YELLOW}Your data lives inside $APP_DIR, so the whole folder was kept.${NC}"
            rm -rf "$APP_DIR/venv" "$APP_DIR/__pycache__"
            ;;
        *)
            if [ -d "$APP_DIR/static/uploads" ]; then
                mkdir -p "$DATA_DIR/uploads"
                cp -a "$APP_DIR/static/uploads/." "$DATA_DIR/uploads/" 2>/dev/null || true
            fi
            rm -rf "$APP_DIR"
            echo -e "${YELLOW}Data kept at $DATA_DIR (including photos in $DATA_DIR/uploads).${NC}"
            ;;
    esac
fi

echo ""
echo "Uninstall complete."
