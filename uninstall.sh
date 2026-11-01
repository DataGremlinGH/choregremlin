#!/bin/bash
# ChoreGremlin - Uninstall Script
# Removes the app, service, timers, and optionally data.
# Usage: sudo bash uninstall.sh

set -e

APP_DIR="/opt/choregremlin"
SERVICE_USER="choregremlin"

BOLD='\033[1m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root: sudo bash uninstall.sh${NC}"
    exit 1
fi

echo -e "${BOLD}Uninstall ChoreGremlin${NC}"
echo ""

# Ask about data
echo -e "${YELLOW}Do you want to keep your data (database, photos, backups)?${NC}"
echo -e "  y = keep data (you can reinstall later and it will be there)"
echo -e "  n = remove everything"
read -p "Keep data? [Y/n] " KEEP_DATA
KEEP_DATA=${KEEP_DATA:-y}

# Stop and disable services
echo "Stopping services..."
systemctl stop choregremlin.service 2>/dev/null || true
systemctl stop choregremlin-update.timer 2>/dev/null || true
systemctl stop choregremlin-backup.timer 2>/dev/null || true

systemctl disable choregremlin.service 2>/dev/null || true
systemctl disable choregremlin-update.timer 2>/dev/null || true
systemctl disable choregremlin-backup.timer 2>/dev/null || true

# Remove systemd files
rm -f /etc/systemd/system/choregremlin.service
rm -f /etc/systemd/system/choregremlin-update.service
rm -f /etc/systemd/system/choregremlin-update.timer
rm -f /etc/systemd/system/choregremlin-backup.service
rm -f /etc/systemd/system/choregremlin-backup.timer
systemctl daemon-reload

# Remove avahi service
rm -f /etc/avahi/services/choregremlin.service

# Close firewall port
ufw delete allow 8473/tcp 2>/dev/null || true

# Remove app directory
if [ "$KEEP_DATA" = "n" ] || [ "$KEEP_DATA" = "N" ]; then
    echo "Removing all data..."
    rm -rf "$APP_DIR"
    userdel "$SERVICE_USER" 2>/dev/null || true
    echo -e "${RED}ChoreGremlin and all data removed.${NC}"
else
    # Keep data, remove app code
    echo "Keeping data directory, removing app code..."
    rm -rf "$APP_DIR/venv"
    rm -rf "$APP_DIR/__pycache__"
    # Keep the data dir
    echo -e "${YELLOW}Data kept at $APP_DIR/data. App code removed.${NC}"
fi

echo ""
echo "Uninstall complete."
