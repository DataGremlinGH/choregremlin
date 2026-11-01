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
    echo -e "  ${BOLD}Token Name:${NC}   $TOKEN_PLURAL"
    echo -e "  ${BOLD}Security Updates:${NC} $AUTO_UPDATE_LABEL"
    echo -e "  ${BOLD}Daily Backup:${NC} $AUTO_BACKUP_LABEL"
    echo -e "  ${BOLD}Remote Access:${NC} $REMOTE_LABEL"
    echo ""
    echo -e "  ${BOLD}Open in your browser:${NC}"
    echo -e "  ${CYAN}http://$PI_IP:$CHOSEN_PORT${NC}"
    echo -e "  ${BOLD}Admin username:${NC} $ADMIN_USERNAME"
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
    printf -v "$var_name" '%s' "$answer"
    echo ""
}

# Must run as root
if [ "$EUID" -ne 0 ] && [ "${DRY_RUN:-0}" != "1" ]; then
    echo -e "${RED}Please run as root: sudo bash install.sh${NC}"
    exit 1
fi

print_header

printf '\033[1;32m'
cat << 'BANNER'
   ________                       ______                    ___
  / ____/ /_  ____  ________     / ____/_______  ____ ___  / (_)___
 / /   / __ \/ __ \/ ___/ _ \   / / __/ ___/ _ \/ __ `__ \/ / / __ \
/ /___/ / / / /_/ / /  /  __/  / /_/ / /  /  __/ / / / / / / / / / /
\____/_/ /_/\____/_/   \___/   \____/_/   \___/_/ /_/ /_/_/_/_/ /_/
BANNER
printf '\033[0m'

SETTINGS_DIR="/etc/choregremlin"
SETTINGS_FILE="$SETTINGS_DIR/choregremlin.env"
UNIT_FILE="/etc/systemd/system/choregremlin.service"
CURRENCY_CODES=(GBP EUR USD CAD AUD NZD ZAR INR SGD NGN)

yes_label() {
    if [ "$1" = "y" ]; then echo "On"; else echo "Off"; fi
}

port_in_use() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

ask_until() {
    local prompt="$1" default="$2" var_name="$3" pattern="$4" error="$5" hint="$6" answer
    while true; do
        if [ -n "$default" ]; then
            echo -e "${BOLD}$prompt${NC} ${CYAN}[$default]${NC}"
        else
            echo -e "${BOLD}$prompt${NC}"
        fi
        if [ -n "$hint" ]; then
            echo -e "  ${YELLOW}$hint${NC}"
        fi
        read -r answer
        answer=${answer:-$default}
        if [[ "$answer" =~ $pattern ]]; then
            printf -v "$var_name" '%s' "$answer"
            echo ""
            return 0
        fi
        echo -e "  ${RED}$error${NC}"
    done
}

ask_password() {
    local first second
    while true; do
        echo -e "${BOLD}Choose a password (at least 10 characters)${NC}"
        read -rs first
        echo ""
        if [ "${#first}" -lt 10 ]; then
            echo -e "  ${RED}That password is too short.${NC}"
            continue
        fi
        echo -e "${BOLD}Type the password again${NC}"
        read -rs second
        echo ""
        if [ "$first" = "$second" ]; then
            ADMIN_PASSWORD=$first
            echo ""
            return 0
        fi
        echo -e "  ${RED}The passwords did not match. Try again.${NC}"
    done
}

echo -e "${BOLD}Checking system...${NC}"
IS_PI=0
if [ -f /proc/device-tree/model ] && grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
    IS_PI=1
    echo -e "  ${GREEN}Raspberry Pi detected${NC}"
    echo -e "  Model: $(tr -d '\0' < /proc/device-tree/model)"
fi
echo ""

EXISTING_INSTALL=0
EXISTING_PORT=""
EXISTING_DATA=""
if [ -f "$SETTINGS_FILE" ] || [ -d "$APP_DIR" ]; then
    EXISTING_INSTALL=1
fi
if [ -f "$SETTINGS_FILE" ]; then
    EXISTING_PORT=$(grep -E '^PORT=' "$SETTINGS_FILE" | tail -n 1 | cut -d= -f2-)
    EXISTING_DATA=$(grep -E '^CHOREGREMLIN_DATA_DIR=' "$SETTINGS_FILE" | tail -n 1 | cut -d= -f2-)
fi
if [ -z "$EXISTING_PORT" ] && [ -f "$UNIT_FILE" ]; then
    EXISTING_PORT=$(grep -oP 'Environment=PORT=\K[0-9]+' "$UNIT_FILE" || true)
fi
CURRENT_DATA=${EXISTING_DATA:-/var/lib/choregremlin}

FREE_PORT=""
for candidate in $(seq "$DEFAULT_PORT" $((DEFAULT_PORT + 10))); do
    if ! port_in_use "$candidate"; then
        FREE_PORT=$candidate
        break
    fi
done
if [ -z "$EXISTING_PORT" ] && [ -z "$FREE_PORT" ]; then
    echo -e "${RED}Ports $DEFAULT_PORT to $((DEFAULT_PORT + 10)) are all in use. Free one up and run the installer again.${NC}"
    exit 1
fi

ask_until "How would you like to install? Enter 1 for Beginner or 2 for Advanced." "1" INSTALL_MODE '^[12]$' "Please enter 1 or 2." ""

if [ "$IS_PI" -eq 0 ]; then
    ask_yes_no "This does not look like a Raspberry Pi. Install on this computer anyway?" "n" RUN_ANYWAY ""
    if [ "$RUN_ANYWAY" != "y" ]; then
        echo "Installation cancelled. Nothing was changed."
        exit 0
    fi
fi

ask_until "Your name" "" ADMIN_NAME '[^[:space:]]' "Please enter your name." ""
ask_until "Choose a username (letters, numbers and _, at least 3 characters)" "" ADMIN_USERNAME '^[A-Za-z0-9_]{3,}$' "Use at least 3 letters, numbers or underscores." ""
ask_password

TOKEN_PLURAL="Tokens"
TOKEN_VALUE="0.10"
CURRENCY_CODE="GBP"
REMOTE_ACCESS="n"
AUTO_UPDATES="y"
DAILY_BACKUP="y"
OPEN_FIREWALL="y"
HTTPS_WANTED="n"
REPO_SOURCE="$REPO_URL"
BRANCH="main"
DATA_DIR="$CURRENT_DATA"
CHOSEN_PORT=${EXISTING_PORT:-$FREE_PORT}

if [ "$INSTALL_MODE" = "2" ]; then
    ask_until "What do you call your reward tokens? (plural)" "Tokens" TOKEN_PLURAL '^[A-Za-z][A-Za-z ]{0,29}$' "Use letters only, up to 30 characters." ""

    echo -e "${BOLD}Currencies${NC}"
    for i in "${!CURRENCY_CODES[@]}"; do
        echo "  $((i + 1))) ${CURRENCY_CODES[$i]}"
    done
    ask_until "Which currency should the app use?" "1" CURRENCY_CHOICE '^([1-9]|10)$' "Enter a number from 1 to 10." ""
    CURRENCY_CODE=${CURRENCY_CODES[$((CURRENCY_CHOICE - 1))]}

    ask_until "How much is one token worth in that currency?" "0.10" TOKEN_VALUE '^(0?\.0[1-9]|0?\.[1-9][0-9]?|[1-9][0-9]*(\.[0-9]{1,2})?)$' "Enter a positive amount such as 0.10." ""

    KEEP_DATA="n"
    if [ "$EXISTING_INSTALL" -eq 1 ]; then
        ask_yes_no "Keep your family data in $CURRENT_DATA? (recommended)" "y" KEEP_DATA ""
    fi
    if [ "$KEEP_DATA" = "y" ]; then
        DATA_DIR="$CURRENT_DATA"
    else
        if [ "$EXISTING_INSTALL" -eq 1 ]; then
            echo -e "  ${YELLOW}Your existing family data stays in $CURRENT_DATA and will not be used by the new install.${NC}"
            echo ""
        fi
        ask_yes_no "Store family data on a USB drive instead of the Pi's SD card?" "n" USE_USB ""
        DATA_DIR="/var/lib/choregremlin"
        if [ "$USE_USB" = "y" ]; then
            while true; do
                ask_until "Where is the USB drive mounted?" "" USB_MOUNT '^/[^[:space:]]+$' "Enter a full folder path such as /media/pi/FAMILY." ""
                if mountpoint -q "$USB_MOUNT"; then
                    break
                fi
                echo -e "  ${RED}Nothing is mounted at $USB_MOUNT. Check the drive and try again.${NC}"
                echo ""
            done
            DATA_DIR="$USB_MOUNT/choregremlin"
        fi
    fi

    ask_until "Which port should the app use?" "$CHOSEN_PORT" CHOSEN_PORT '^(102[4-9]|10[3-9][0-9]|1[1-9][0-9]{2}|[2-9][0-9]{3}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5])$' "Enter a port between 1024 and 65535." ""
    ask_yes_no "Allow access from outside your home Wi-Fi?" "n" REMOTE_ACCESS ""
    ask_yes_no "Install security updates for the Pi automatically?" "y" AUTO_UPDATES ""
    ask_yes_no "Make a backup of the database every day?" "y" DAILY_BACKUP ""
    ask_yes_no "Open the app's port in the firewall?" "y" OPEN_FIREWALL ""
    ask_input "Where should the app be downloaded from?" "$REPO_URL" REPO_SOURCE ""
    ask_until "Which branch?" "main" BRANCH '^[A-Za-z0-9._/-]+$' "Use letters, numbers, dots, dashes, slashes or underscores." ""
    ask_yes_no "Turn on HTTPS (secure connection) for your home network?" "y" HTTPS_WANTED ""
fi

TOKEN_SINGULAR=$TOKEN_PLURAL
if [[ "$TOKEN_PLURAL" == *s ]] && [ "${#TOKEN_PLURAL}" -gt 1 ]; then
    TOKEN_SINGULAR=${TOKEN_PLURAL%s}
fi

AUTO_UPDATE_LABEL=$(yes_label "$AUTO_UPDATES")
AUTO_BACKUP_LABEL=$(yes_label "$DAILY_BACKUP")
if [ "$REMOTE_ACCESS" = "y" ]; then
    REMOTE_LABEL="Allowed from outside home Wi-Fi"
else
    REMOTE_LABEL="Home Wi-Fi only"
fi

ask_yes_no "Start the installation now?" "y" START_NOW ""
if [ "$START_NOW" != "y" ]; then
    echo "Installation cancelled. Nothing was changed."
    exit 0
fi

if [ "${DRY_RUN:-0}" = "1" ]; then
    echo -e "${GREEN}DRY RUN: every question was asked and nothing was changed.${NC}"
    exit 0
fi

echo -e "${BOLD}Installing packages...${NC}"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv git curl ufw unattended-upgrades

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo -e "${BOLD}Downloading the app...${NC}"
ASIDE_DIR=""
if [ -d "$APP_DIR" ] && [ ! -d "$APP_DIR/.git" ]; then
    ASIDE_DIR="${APP_DIR}-before-$(date +%Y%m%d-%H%M%S)"
    mv "$APP_DIR" "$ASIDE_DIR"
    echo "  Moved the old app folder to $ASIDE_DIR"
fi
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch origin "$BRANCH"
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
    git clone --branch "$BRANCH" "$REPO_SOURCE" "$APP_DIR"
fi

echo -e "${BOLD}Setting up the data folder...${NC}"
mkdir -p "$DATA_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"

echo -e "${BOLD}Installing Python packages...${NC}"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo -e "${BOLD}Writing the settings file...${NC}"
SECRET_KEY_VALUE=""
if [ -f "$SETTINGS_FILE" ]; then
    SECRET_KEY_VALUE=$(grep -E '^SECRET_KEY=' "$SETTINGS_FILE" | tail -n 1 | cut -d= -f2-)
fi
if [ -z "$SECRET_KEY_VALUE" ]; then
    SECRET_KEY_VALUE=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
fi
mkdir -p "$SETTINGS_DIR"
(
    umask 077
    cat > "$SETTINGS_FILE" <<EOF
PORT=$CHOSEN_PORT
CHOREGREMLIN_DATA_DIR=$DATA_DIR
SECRET_KEY=$SECRET_KEY_VALUE
EOF
)
chown root:root "$SETTINGS_FILE"
chmod 640 "$SETTINGS_FILE"

echo -e "${BOLD}Creating the database and admin account...${NC}"
runuser -u "$SERVICE_USER" -- env \
    CHOREGREMLIN_DATA_DIR="$DATA_DIR" \
    SECRET_KEY="$SECRET_KEY_VALUE" \
    APP_PATH="$APP_DIR" \
    ADMIN_NAME="$ADMIN_NAME" \
    ADMIN_USERNAME="$ADMIN_USERNAME" \
    ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    TOKEN_PLURAL="$TOKEN_PLURAL" \
    TOKEN_SINGULAR="$TOKEN_SINGULAR" \
    TOKEN_VALUE="$TOKEN_VALUE" \
    CURRENCY_CODE="$CURRENCY_CODE" \
    "$VENV_DIR/bin/python3" - <<'PY'
import os
import sys

sys.path.insert(0, os.environ['APP_PATH'])
from app import app
import db

with app.app_context():
    db.init_db()
    if db.is_setup_complete():
        admin = db.get_all_users('admin')[0]
        db.set_password(admin['id'], os.environ['ADMIN_PASSWORD'])
        db.update_user(admin['id'], username=os.environ['ADMIN_USERNAME'])
        print('Admin password updated. Other accounts were left unchanged.')
    else:
        db.create_user(os.environ['ADMIN_NAME'], None, os.environ['ADMIN_PASSWORD'], 'admin',
                       username=os.environ['ADMIN_USERNAME'])
        db.save_currency_settings(os.environ['TOKEN_PLURAL'], os.environ['TOKEN_SINGULAR'],
                                  os.environ['TOKEN_PLURAL'], os.environ['TOKEN_VALUE'])
        db.set_setting('currency_code', os.environ['CURRENCY_CODE'])
        print('Admin account created.')
PY

echo -e "${BOLD}Setting up services...${NC}"
cat > /etc/systemd/system/choregremlin.service <<'UNIT'
[Unit]
Description=ChoreGremlin - The little gremlin that gets the chores done
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=choregremlin
Group=choregremlin
WorkingDirectory=/opt/choregremlin
EnvironmentFile=/etc/choregremlin/choregremlin.env
ExecStart=/opt/choregremlin/venv/bin/python3 /opt/choregremlin/app.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=choregremlin
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

if [ "$DAILY_BACKUP" = "y" ]; then
    cat > /usr/local/sbin/choregremlin-backup <<'SCRIPT'
#!/bin/sh
set -e
DB="$CHOREGREMLIN_DATA_DIR/choregremlin.db"
BACKUP_DIR="$CHOREGREMLIN_DATA_DIR/backups"
[ -f "$DB" ] || exit 0
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
python3 -c 'import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
src.close()' "$DB" "$BACKUP_DIR/auto-$STAMP.db"
ls -1t "$BACKUP_DIR"/auto-*.db 2>/dev/null | tail -n +21 | while read -r old; do rm -f "$old"; done
SCRIPT
    chmod 755 /usr/local/sbin/choregremlin-backup
    cat > /etc/systemd/system/choregremlin-backup.service <<'UNIT'
[Unit]
Description=ChoreGremlin daily database backup

[Service]
Type=oneshot
User=choregremlin
Group=choregremlin
EnvironmentFile=/etc/choregremlin/choregremlin.env
ExecStart=/usr/local/sbin/choregremlin-backup
UNIT
    cat > /etc/systemd/system/choregremlin-backup.timer <<'UNIT'
[Unit]
Description=Daily ChoreGremlin database backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
UNIT
else
    systemctl disable --now choregremlin-backup.timer >/dev/null 2>&1 || true
fi

if [ "$AUTO_UPDATES" = "y" ]; then
    cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
    cat > /etc/apt/apt.conf.d/52choregremlin-no-reboot <<'CONF'
Unattended-Upgrade::Automatic-Reboot "false";
CONF
    systemctl enable --now unattended-upgrades >/dev/null
fi

SSH_PORT=$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')
SSH_PORT=${SSH_PORT:-22}
ufw allow "${SSH_PORT}/tcp" >/dev/null
if [ "$OPEN_FIREWALL" = "y" ]; then
    if [ "$REMOTE_ACCESS" = "y" ]; then
        ufw allow "$CHOSEN_PORT/tcp" >/dev/null
    else
        for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
            ufw allow from "$net" to any port "$CHOSEN_PORT" proto tcp >/dev/null
        done
    fi
fi
ufw --force enable >/dev/null

systemctl daemon-reload
systemctl enable choregremlin >/dev/null
systemctl restart choregremlin

echo -e "${BOLD}Checking the app answers...${NC}"
LOGIN_OK=0
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$CHOSEN_PORT/login"; then
        LOGIN_OK=1
        break
    fi
    sleep 1
done
if [ "$LOGIN_OK" -ne 1 ]; then
    echo -e "${RED}The app did not answer on port $CHOSEN_PORT. Check the logs with: sudo journalctl -u choregremlin -n 50${NC}"
    exit 1
fi

PI_IP=$(hostname -I | awk '{print $1}')
print_summary

echo -e "${BOLD}Next steps${NC}"
echo "  1. Open http://$PI_IP:$CHOSEN_PORT on a device on your home Wi-Fi and sign in as $ADMIN_USERNAME."
echo "  2. Add your children and parents in the app."
echo "  Your data folder: $DATA_DIR"
if [ "$HTTPS_WANTED" = "y" ]; then
    echo -e "  ${YELLOW}HTTPS is not set up by this installer yet. The app is served over plain http.${NC}"
fi
if [ "$OPEN_FIREWALL" != "y" ]; then
    echo -e "  ${YELLOW}The app's port is closed in the firewall, so other devices cannot reach it yet.${NC}"
fi
echo ""
