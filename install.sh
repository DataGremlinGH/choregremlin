#!/bin/bash
# Family Hub - Raspberry Pi Installation Script
# Run this on a fresh Raspberry Pi to install and configure Family Hub.
# Usage: sudo bash deploy/install.sh

set -e

APP_DIR="/opt/family-hub"
SERVICE_USER="familyhub"

echo "========================================="
echo "  Family Hub - Raspberry Pi Installer"
echo "========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash deploy/install.sh"
    exit 1
fi

# Create service user if it doesn't exist
if ! id "$SERVICE_USER" &>/dev/null; then
    echo "Creating service user '$SERVICE_USER'..."
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# Install system dependencies
echo "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git

# Create app directory
echo "Setting up application directory..."
mkdir -p "$APP_DIR/instance"
mkdir -p "$APP_DIR/static/uploads"

# Copy files (if running from within the repo)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

if [ "$PARENT_DIR" != "$APP_DIR" ]; then
    echo "Copying application files to $APP_DIR..."
    cp -r "$PARENT_DIR"/* "$APP_DIR/" 2>/dev/null || true
    cp -r "$PARENT_DIR"/.bolt "$APP_DIR/" 2>/dev/null || true
fi

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install --break-system-packages -r "$APP_DIR/requirements.txt" -q

# Set ownership
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# Make scripts executable
chmod +x "$APP_DIR/deploy/auto-update.sh"
chmod +x "$APP_DIR/deploy/cleanup.py"

# Install systemd services
echo "Installing systemd services..."
cp "$APP_DIR/deploy/family-hub.service" /etc/systemd/system/
cp "$APP_DIR/deploy/family-hub-update.service" /etc/systemd/system/
cp "$APP_DIR/deploy/family-hub-update.timer" /etc/systemd/system/
cp "$APP_DIR/deploy/family-hub-cleanup.service" /etc/systemd/system/
cp "$APP_DIR/deploy/family-hub-cleanup.timer" /etc/systemd/system/

# Enable and start services
systemctl daemon-reload
systemctl enable family-hub.service
systemctl enable family-hub-update.timer
systemctl enable family-hub-cleanup.timer

systemctl start family-hub.service
systemctl start family-hub-update.timer
systemctl start family-hub-cleanup.timer

echo ""
echo "========================================="
echo "  Installation Complete!"
echo "========================================="
echo ""
echo "Family Hub is now running on port 5000."
echo ""
echo "To access:"
echo "  - On the Pi:     http://localhost:5000"
echo "  - On your network: http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "Service commands:"
echo "  Check status:  sudo systemctl status family-hub"
echo "  View logs:      sudo journalctl -u family-hub -f"
echo "  Restart:        sudo systemctl restart family-hub"
echo "  Stop:           sudo systemctl stop family-hub"
echo ""
echo "Auto-update:  Enabled (checks every hour)"
echo "Cleanup:      Enabled (runs daily, keeps 1 year of records)"
echo ""
echo "To disable auto-update, go to Settings in the app."
