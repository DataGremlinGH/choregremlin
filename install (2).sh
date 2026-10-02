#!/bin/bash
# ChoreGremlin - One-Command Installer for Raspberry Pi
# Usage: curl -sSL https://raw.githubusercontent.com/DataGremlinGH/ChoreGremlin/main/install.sh | bash
# Or:  sudo bash install.sh
#
# "The little gremlin that gets the chores done"

set -e

APP_NAME="ChoreGremlin"
APP_DIR="/opt/choregremlin"
SERVICE_USER="choregremlin"
DEFAULT_PORT=8473
REPO_URL="https://github.com/DataGremlinGH/ChoreGremlin.git"
VENV_DIR="$APP_DIR/venv"

BOLD='\033[1m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${CYAN}=========================================${NC}"
    echo -e "${CYAN}  $APP_NAME Installer${NC}"
    echo -e "${CYAN}  The little gremlin that gets the chores done${NC}"
    echo -e "${CYAN}=========================================${NC}"
    echo ""
}

print_summary() {
    echo ""
    echo -e "${GREEN}=========================================${NC}"
    echo -e "${GREEN}  Installation Complete!${NC}"
    echo -e "${GREEN}=========================================${NC}"
    echo ""
    echo -e "  ${BOLD}App Name:${NC}     $APP_NAME"
    echo -e "  ${BOLD}Port:${NC}         $CHOSEN_PORT"
    echo -e "  ${BOLD}Data Dir:${NC}     $DATA_DIR"
    echo -e "  ${BOLD}Token Name:${NC}   $TOKEN_NAME"
    echo -e "  ${BOLD}Auto-Update:${NC}  $AUTO_UPDATE_LABEL"
    echo -e "  ${BOLD}Auto-Backup:${NC}  $AUTO_BACKUP_LABEL"
    echo -e "  ${BOLD}Remote Access:${NC} $REMOTE_LABEL"
    echo ""
    echo -e "  ${BOLD}Open in your browser:${NC}"
    echo -e "  ${CYAN}http://$PI_IP:$CHOSEN_PORT${NC}"
    echo -e "  ${CYAN}http://familyhub.local:$CHOSEN_PORT${NC}"
    echo ""
    echo -e "  ${BOLD}Service commands:${NC}"
    echo "    Check status:  sudo systemctl status choregremlin"
    echo "    View logs:      sudo journalctl -u choregremlin -f"
    echo "    Restart:        sudo systemctl restart choregremlin"
    echo ""
}

ask_yes_no() {
    local prompt="$1"
    local default="$2"
    local var_name="$3"
    local hint="$4"

    if [ "$default" = "y" ]; then
        local display="[Y/n]"
    else
        local display="[y/N]"
    fi

    echo -e "${BOLD}$prompt${NC} ${CYAN}$display${NC}"
    if [ -n "$hint" ]; then
        echo -e "  ${YELLOW}$hint${NC}"
    fi
    read -r answer
    answer=${answer:-$default}

    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
        eval "$var_name='y'"
    else
        eval "$var_name='n'"
    fi
    echo ""
}

ask_input() {
    local prompt="$1"
    local default="$2"
    local var_name="$3"
    local hint="$4"

    echo -e "${BOLD}$prompt${NC} ${CYAN}[$default]${NC}"
    if [ -n "$hint" ]; then
        echo -e "  ${YELLOW}$hint${NC}"
    fi
    read -r answer
    answer=${answer:-$default}
    eval "$var_name='$answer'"
    echo ""
}

# Must run as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root: sudo bash install.sh${NC}"
    exit 1
fi

print_header

# Check if on a Raspberry Pi
echo -e "${BOLD}Checking system...${NC}"
if [ -f /proc/device-tree/model ] && grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
    echo -e "  ${GREEN}Raspberry Pi detected${NC}"
    PI_MODEL=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0')
    echo -e "  Model: $PI_MODEL"
else
    echo -e "  ${YELLOW}This doesn't appear to be a Raspberry Pi. Install anyway?${NC}"
    ask_yes_no "Continue?" "y" "CONTINUE" "This will work on most Linux systems but is designed for Pi."
    if [ "$CONTINUE" != "y" ]; then
        echo "Aborted."
        exit 0
    fi
fi

# Check Python
echo -e "${BOLD}Checking Python...${NC}"
if ! command -v python3 &>/dev/null; then
    echo -e "  ${YELLOW}Installing Python 3...${NC}"
    apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-venv
fi
PY_VERSION=$(python3 --version 2>&1)
echo -e "  ${GREEN}$PY_VERSION${NC}"

# Check disk space
echo -e "${BOLD}Checking disk space...${NC}"
FREE_SPACE=$(df -m / | awk 'NR==2 {print $4}')
if [ "$FREE_SPACE" -lt 500 ]; then
    echo -e "  ${RED}Not enough disk space. Need at least 500MB, have ${FREE_SPACE}MB.${NC}"
    exit 1
fi
echo -e "  ${GREEN}${FREE_SPACE}MB free${NC}"

# Detect Pi IP
PI_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$PI_IP" ]; then
    PI_IP="127.0.0.1"
fi

echo ""
echo -e "${CYAN}--- Interactive Setup ---${NC}"
echo -e "${YELLOW}Each question has a recommended default in [brackets]. Press Enter to accept it.${NC}"
echo ""

# Storage location
ask_yes_no \
    "Store data on a USB drive or external disk?" \
    "n" \
    "USE_USB" \
    "USB drives are slower but won't wear out your Pi's SD card. Good if you have lots of photos."

if [ "$USE_USB" = "y" ]; then
    echo -e "${BOLD}Enter the path for the USB drive mount point:${NC}"
    echo -e "  ${YELLOW}e.g. /mnt/usb/choregremlin. The installer will create it.${NC}"
    read -r USB_PATH
    USB_PATH=${USB_PATH:-/mnt/usb/choregremlin}
    DATA_DIR="$USB_PATH"
else
    DATA_DIR="$APP_DIR/data"
fi
echo ""

# Token name
ask_input \
    "What would you like to call your reward tokens?" \
    "Widgets" \
    "TOKEN_NAME" \
    "This is the currency kids earn by doing chores. You can change it later in the app."
echo ""

# Port
ask_input \
    "Which port should the app use?" \
    "$DEFAULT_PORT" \
    "PORT_INPUT" \
    "Default 8473 avoids common ports. Don't use 80, 443, 8080 or 5000."
CHOSEN_PORT=${PORT_INPUT:-$DEFAULT_PORT}
echo ""

# Check port is free
if ss -tlnp | grep -q ":$CHOSEN_PORT " 2>/dev/null; then
    echo -e "${RED}Port $CHOSEN_PORT is already in use. Using default $DEFAULT_PORT instead.${NC}"
    CHOSEN_PORT=$DEFAULT_PORT
fi

# Remote access
ask_yes_no \
    "Enable remote access (outside your home Wi-Fi)?" \
    "n" \
    "REMOTE_ACCESS" \
    "Off by default for safety. You can enable it later after setting up HTTPS and 2FA."
if [ "$REMOTE_ACCESS" = "y" ]; then
    REMOTE_LABEL="Enabled (make sure to set up HTTPS and 2FA!)"
else
    REMOTE_LABEL="Disabled (LAN only)"
fi
echo ""

# 2FA
ask_yes_no \
    "Set up two-factor authentication (2FA) now?" \
    "n" \
    "SETUP_2FA" \
    "Only needed if you enabled remote access. On your home Wi-Fi, a password alone is enough. You can always set it up later."
echo ""

# Auto-update
ask_yes_no \
    "Enable automatic updates?" \
    "y" \
    "AUTO_UPDATE" \
    "Checks for new versions every hour and installs them. Keeps your app up to date."
if [ "$AUTO_UPDATE" = "y" ]; then
    AUTO_UPDATE_LABEL="Enabled"
else
    AUTO_UPDATE_LABEL="Disabled"
fi
echo ""

# Auto-backup
ask_yes_no \
    "Enable automatic daily backups?" \
    "y" \
    "AUTO_BACKUP" \
    "Creates a copy of your database every day. Good insurance against SD card failure."
if [ "$AUTO_BACKUP" = "y" ]; then
    AUTO_BACKUP_LABEL="Enabled (daily)"
else
    AUTO_BACKUP_LABEL="Disabled"
fi
echo ""

# Firewall
ask_yes_no \
    "Open the port in the firewall (ufw)?" \
    "y" \
    "USE_FIREWALL" \
    "Only opens the app port. Other ports stay blocked."
echo ""

# Confirm
echo -e "${CYAN}--- Summary ---${NC}"
echo -e "  App:         $APP_NAME"
echo -e "  Port:        $CHOSEN_PORT"
echo -e "  Data Dir:    $DATA_DIR"
echo -e "  Token:       $TOKEN_NAME"
echo -e "  Remote:      $REMOTE_LABEL"
echo -e "  2FA:         $([ "$SETUP_2FA" = "y" ] && echo 'Will set up' || echo 'Skip for now')"
echo -e "  Auto-Update: $AUTO_UPDATE_LABEL"
echo -e "  Auto-Backup: $AUTO_BACKUP_LABEL"
echo -e "  Firewall:    $([ "$USE_FIREWALL" = "y" ] && echo "Open port $CHOSEN_PORT" || echo 'Skip')"
echo ""
ask_yes_no "Proceed with installation?" "y" "PROCEED" ""
if [ "$PROCEED" != "y" ]; then
    echo "Aborted."
    exit 0
fi

# --- Installation ---

echo ""
echo -e "${BOLD}Installing system dependencies...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git avahi-daemon 2>/dev/null || true

# Create service user
if ! id "$SERVICE_USER" &>/dev/null; then
    echo -e "${BOLD}Creating service user '$SERVICE_USER'...${NC}"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# Clone or update repo
if [ -d "$APP_DIR/.git" ]; then
    echo -e "${BOLD}Updating existing installation...${NC}"
    cd "$APP_DIR"
    git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || true
else
    echo -e "${BOLD}Downloading $APP_NAME...${NC}"
    rm -rf "$APP_DIR"
    git clone --depth 1 "$REPO_URL" "$APP_DIR" 2>/dev/null || {
        # If not a git repo yet, copy from current directory
        mkdir -p "$APP_DIR"
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        cp -r "$SCRIPT_DIR"/* "$APP_DIR/" 2>/dev/null || cp -r ./* "$APP_DIR/" 2>/dev/null || true
    }
fi

# Create data directory
mkdir -p "$DATA_DIR"
mkdir -p "$APP_DIR/static/uploads"

# Create virtual environment
echo -e "${BOLD}Creating virtual environment...${NC}"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# Set ownership
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"

# Make scripts executable
chmod +x "$APP_DIR/deploy/auto-update.sh" 2>/dev/null || true
chmod +x "$APP_DIR/deploy/cleanup.py" 2>/dev/null || true

# Configure avahi for familyhub.local
echo -e "${BOLD}Configuring familyhub.local (Avahi)...${NC}"
AVAHI_FILE="/etc/avahi/services/choregremlin.service"
cat > "$AVAHI_FILE" <<EOF
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">ChoreGremlin on %h</name>
  <service>
    <type>_http._tcp</type>
    <port>$CHOSEN_PORT</port>
  </service>
</service-group>
EOF
systemctl restart avahi-daemon 2>/dev/null || true

# Create systemd service
echo -e "${BOLD}Setting up systemd service...${NC}"
cat > /etc/systemd/system/choregremlin.service <<EOF
[Unit]
Description=ChoreGremlin - The little gremlin that gets the chores done
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
Environment=PORT=$CHOSEN_PORT
Environment=CHOREGREMLIN_DATA_DIR=$DATA_DIR
ExecStart=$VENV_DIR/bin/python3 $APP_DIR/app.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=choregremlin

[Install]
WantedBy=multi-user.target
EOF

# Auto-update timer
if [ "$AUTO_UPDATE" = "y" ]; then
    cat > /etc/systemd/system/choregremlin-update.service <<EOF
[Unit]
Description=ChoreGremlin Auto-Update
After=network-online.target

[Service]
Type=oneshot
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/deploy/auto-update.sh
EOF
    cat > /etc/systemd/system/choregremlin-update.timer <<EOF
[Unit]
Description=ChoreGremlin Auto-Update Timer

[Timer]
OnBootSec=2min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF
fi

# Cleanup timer (daily, 1-year retention)
cat > /etc/systemd/system/choregremlin-cleanup.service <<EOF
[Unit]
Description=ChoreGremlin Data Retention Cleanup
After=network.target

[Service]
Type=oneshot
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/python3 $APP_DIR/deploy/cleanup.py
EOF
cat > /etc/systemd/system/choregremlin-cleanup.timer <<EOF
[Unit]
Description=ChoreGremlin Cleanup Timer

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Auto-backup timer
if [ "$AUTO_BACKUP" = "y" ]; then
    cat > /etc/systemd/system/choregremlin-backup.service <<EOF
[Unit]
Description=ChoreGremlin Daily Backup
After=network.target

[Service]
Type=oneshot
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=/bin/bash -c 'cp $DATA_DIR/choregremlin.db $DATA_DIR/backup_$(date +\%Y\%m\%d).db && find $DATA_DIR -name "backup_*.db" -mtime +30 -delete'
EOF
    cat > /etc/systemd/system/choregremlin-backup.timer <<EOF
[Unit]
Description=ChoreGremlin Daily Backup Timer

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF
fi

# Firewall
if [ "$USE_FIREWALL" = "y" ]; then
    echo -e "${BOLD}Configuring firewall...${NC}"
    if command -v ufw &>/dev/null; then
        ufw allow $CHOSEN_PORT/tcp 2>/dev/null || true
    else
        apt-get install -y -qq ufw 2>/dev/null
        ufw allow $CHOSEN_PORT/tcp 2>/dev/null || true
    fi
fi

# Enable and start services
echo -e "${BOLD}Starting services...${NC}"
systemctl daemon-reload
systemctl enable choregremlin.service
systemctl enable choregremlin-cleanup.timer
systemctl enable choregremlin-cleanup.timer 2>/dev/null || true

if [ "$AUTO_UPDATE" = "y" ]; then
    systemctl enable choregremlin-update.timer 2>/dev/null || true
    systemctl start choregremlin-update.timer 2>/dev/null || true
fi

if [ "$AUTO_BACKUP" = "y" ]; then
    systemctl enable choregremlin-backup.timer 2>/dev/null || true
    systemctl start choregremlin-backup.timer 2>/dev/null || true
fi

systemctl start choregremlin.service

print_summary

if [ "$SETUP_2FA" = "y" ]; then
    echo -e "${YELLOW}After creating your admin account, go to Security > Set Up 2FA in the app.${NC}"
fi

echo -e "${YELLOW}Open ${CYAN}http://$PI_IP:$CHOSEN_PORT${YELLOW} to get started.${NC}"
