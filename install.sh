#!/bin/bash
# ChoreGremlin - One-Command Installer for Raspberry Pi
# Usage: curl -sSL https://raw.githubusercontent.com/DataGremlinGH/ChoreGremlin/main/install.sh -o install.sh
#        sudo bash install.sh
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
    if [ "$HTTPS_WANTED" = "y" ]; then
        echo -e "  ${BOLD}Web Port:${NC}     443 (HTTPS)"
        echo -e "  ${BOLD}App Port:${NC}     $CHOSEN_PORT (localhost only)"
    else
        echo -e "  ${BOLD}Port:${NC}         $CHOSEN_PORT"
    fi
    echo -e "  ${BOLD}Data Dir:${NC}     $DATA_DIR"
    echo -e "  ${BOLD}Token Name:${NC}   $TOKEN_PLURAL"
    echo -e "  ${BOLD}Security Updates:${NC} $AUTO_UPDATE_LABEL"
    echo -e "  ${BOLD}Daily Backup:${NC} $AUTO_BACKUP_LABEL"
    echo -e "  ${BOLD}Remote Access:${NC} $REMOTE_LABEL"
    if [ "$HTTPS_WANTED" = "y" ]; then
        echo -e "  ${BOLD}HTTPS:${NC}        Enabled with Caddy local certificate"
    else
        echo -e "  ${BOLD}HTTPS:${NC}        Off"
    fi
    echo ""
    echo -e "  ${BOLD}Open in your browser:${NC}"
    if [ "$HTTPS_WANTED" = "y" ]; then
        echo -e "  ${CYAN}https://$PI_IP${NC}"
        echo -e "  ${CYAN}https://familyhub.local${NC}"
    else
        echo -e "  ${CYAN}http://$PI_IP:$CHOSEN_PORT${NC}"
        echo -e "  ${CYAN}http://familyhub.local:$CHOSEN_PORT${NC}"
    fi
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

if [ ! -t 0 ] && [ "${DRY_RUN:-0}" != "1" ]; then
    echo -e "${RED}This installer asks a few questions, so it needs a terminal.${NC}"
    echo "Download it first, then run it:"
    echo "  curl -sSL https://raw.githubusercontent.com/DataGremlinGH/ChoreGremlin/main/install.sh -o install.sh"
    echo "  sudo bash install.sh"
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
CADDYFILE="/etc/caddy/Caddyfile"
CADDY_BACKUP="$CADDYFILE.before-choregremlin"
CURRENCY_CODES=(GBP EUR USD CAD AUD NZD ZAR INR SGD NGN)

yes_label() {
    if [ "$1" = "y" ]; then echo "On"; else echo "Off"; fi
}

port_in_use() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

disable_https_fallback() {
    HTTPS_WANTED="n"
    if [ -f "$SETTINGS_FILE" ]; then
        sed -i 's/^CHOREGREMLIN_HTTPS=.*/CHOREGREMLIN_HTTPS=0/; s/^CHOREGREMLIN_BIND=.*/CHOREGREMLIN_BIND=0.0.0.0/' "$SETTINGS_FILE"
    fi
    rm -f "$CADDYFILE"
    systemctl disable --now caddy >/dev/null 2>&1 || true
    if [ -f "${AVAHI_FILE:-}" ]; then
        sed -i "s#_https\._tcp#_http._tcp#; s#<port>443</port>#<port>$CHOSEN_PORT</port>#" "$AVAHI_FILE"
        systemctl restart avahi-daemon >/dev/null 2>&1 || true
    fi
    systemctl restart choregremlin >/dev/null 2>&1 || true
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
EXISTING_HTTPS="n"
if [ -f "$SETTINGS_FILE" ] || [ -d "$APP_DIR" ]; then
    EXISTING_INSTALL=1
fi
if [ -f "$SETTINGS_FILE" ]; then
    EXISTING_PORT=$(grep -E '^PORT=' "$SETTINGS_FILE" | tail -n 1 | cut -d= -f2-)
    EXISTING_DATA=$(grep -E '^CHOREGREMLIN_DATA_DIR=' "$SETTINGS_FILE" | tail -n 1 | cut -d= -f2-)
    if grep -qE '^CHOREGREMLIN_HTTPS=1' "$SETTINGS_FILE"; then
        EXISTING_HTTPS="y"
    fi
fi
if [ -z "$EXISTING_PORT" ] && [ -f "$UNIT_FILE" ]; then
    EXISTING_PORT=$(grep -oP 'Environment=PORT=\K[0-9]+' "$UNIT_FILE" || true)
fi
CURRENT_DATA=${EXISTING_DATA:-/var/lib/choregremlin}
LEGACY_DATA_SOURCE=""
if [ -n "$EXISTING_DATA" ]; then
    case "$EXISTING_DATA" in
        "$APP_DIR"/*) LEGACY_DATA_SOURCE="$EXISTING_DATA"; CURRENT_DATA="/var/lib/choregremlin" ;;
    esac
else
    for legacy in "$APP_DIR/data" "$APP_DIR/instance"; do
        if [ -f "$legacy/choregremlin.db" ]; then
            LEGACY_DATA_SOURCE="$legacy"
            EXISTING_INSTALL=1
            CURRENT_DATA="/var/lib/choregremlin"
        fi
    done
fi

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
HTTPS_WANTED="$EXISTING_HTTPS"
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
    ask_yes_no "Turn on HTTPS (secure connection) for your home network?" "$EXISTING_HTTPS" HTTPS_WANTED "Uses Caddy with a private local certificate. You will install the trust certificate on each device from the in-app Trust Page."
fi

KEEP_LEGACY_DATA=1
if [ "$INSTALL_MODE" = "2" ] && [ "$KEEP_DATA" != "y" ]; then
    KEEP_LEGACY_DATA=0
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

if [ -n "$LEGACY_DATA_SOURCE" ] && [ "$DATA_DIR" != "$LEGACY_DATA_SOURCE" ] && [ "$KEEP_LEGACY_DATA" -eq 1 ]; then
    echo -e "${BOLD}Moving your existing database out of the app folder...${NC}"
    mkdir -p "$DATA_DIR"
    if [ ! -f "$DATA_DIR/choregremlin.db" ]; then
        cp -a "$LEGACY_DATA_SOURCE/choregremlin.db" "$DATA_DIR/choregremlin.db"
        echo "  Copied the database to $DATA_DIR"
    else
        echo -e "  ${YELLOW}A database already exists in $DATA_DIR, so the old copy was left in place.${NC}"
    fi
fi

echo -e "${BOLD}Installing packages...${NC}"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv git curl ufw avahi-daemon unattended-upgrades

if [ "$HTTPS_WANTED" = "y" ]; then
    echo -e "${BOLD}Installing Caddy for local HTTPS...${NC}"
    DEBIAN_FRONTEND=noninteractive apt-get install -y debian-keyring debian-archive-keyring apt-transport-https gpg
    if ! curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' -o /tmp/choregremlin-caddy.key || \
       ! gpg --dearmor < /tmp/choregremlin-caddy.key > /usr/share/keyrings/caddy-stable-archive-keyring.gpg || \
       ! curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' -o /etc/apt/sources.list.d/caddy-stable.list || \
       ! apt-get update || \
       ! DEBIAN_FRONTEND=noninteractive apt-get install -y caddy; then
        echo -e "${YELLOW}Caddy could not be installed, so HTTPS will be skipped. The hub will stay on plain HTTP.${NC}"
        HTTPS_WANTED="n"
    fi
    rm -f /tmp/choregremlin-caddy.key
fi

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
mkdir -p "$APP_DIR/static/uploads"
if [ -d "$DATA_DIR/uploads" ]; then
    cp -a "$DATA_DIR/uploads/." "$APP_DIR/static/uploads/" 2>/dev/null || true
fi
chmod +x "$APP_DIR/install.sh" "$APP_DIR/update.sh" "$APP_DIR/uninstall.sh" 2>/dev/null || true
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

echo -e "${BOLD}Configuring familyhub.local (Avahi)...${NC}"
AVAHI_FILE="/etc/avahi/services/choregremlin.service"
AVAHI_TYPE="_http._tcp"
AVAHI_PORT="$CHOSEN_PORT"
if [ "$HTTPS_WANTED" = "y" ]; then
    AVAHI_TYPE="_https._tcp"
    AVAHI_PORT="443"
fi
cat > "$AVAHI_FILE" <<'AVAHI'
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">ChoreGremlin on %h</name>
  <service>
    <type>__TYPE__</type>
    <port>__PORT__</port>
  </service>
</service-group>
AVAHI
sed -i "s/__TYPE__/$AVAHI_TYPE/; s/__PORT__/$AVAHI_PORT/" "$AVAHI_FILE"
systemctl restart avahi-daemon >/dev/null 2>&1 || true

echo -e "${BOLD}Writing the settings file...${NC}"
SECRET_KEY_VALUE=""
if [ -f "$SETTINGS_FILE" ]; then
    SECRET_KEY_VALUE=$(grep -E '^SECRET_KEY=' "$SETTINGS_FILE" | tail -n 1 | cut -d= -f2-)
fi
if [ -z "$SECRET_KEY_VALUE" ]; then
    SECRET_KEY_VALUE=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
fi
HTTPS_SETTING="0"
BIND_SETTING="0.0.0.0"
CA_SETTING=""
if [ "$HTTPS_WANTED" = "y" ]; then
    HTTPS_SETTING="1"
    BIND_SETTING="127.0.0.1"
    CA_SETTING="$DATA_DIR/caddy-root.crt"
fi
mkdir -p "$SETTINGS_DIR"
(
    umask 077
    cat > "$SETTINGS_FILE" <<EOF
PORT=$CHOSEN_PORT
CHOREGREMLIN_DATA_DIR=$DATA_DIR
SECRET_KEY=$SECRET_KEY_VALUE
CHOREGREMLIN_HTTPS=$HTTPS_SETTING
CHOREGREMLIN_BIND=$BIND_SETTING
CHOREGREMLIN_CA_CERT=$CA_SETTING
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
EnvironmentFile=-/etc/choregremlin/choregremlin.env
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
DATA_DIR="${CHOREGREMLIN_DATA_DIR:-/var/lib/choregremlin}"
DB="$DATA_DIR/choregremlin.db"
BACKUP_DIR="$DATA_DIR/backups"
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
EnvironmentFile=-/etc/choregremlin/choregremlin.env
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

cat > /etc/systemd/system/choregremlin-update.service <<'UNIT'
[Unit]
Description=ChoreGremlin Auto-Update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/choregremlin
Environment=CHOREGREMLIN_UPDATE_TRIGGER=auto
ExecStart=/opt/choregremlin/update.sh
StandardOutput=journal
StandardError=journal
SyslogIdentifier=choregremlin-update
UNIT

cat > /etc/systemd/system/choregremlin-update.timer <<'UNIT'
[Unit]
Description=ChoreGremlin Auto-Update Timer
Requires=choregremlin-update.service

[Timer]
OnBootSec=2min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
UNIT

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

systemctl daemon-reload
systemctl enable choregremlin >/dev/null
systemctl enable --now choregremlin-update.timer >/dev/null 2>&1 || true
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
PI_IP=${PI_IP:-127.0.0.1}

if [ "$HTTPS_WANTED" = "y" ]; then
    echo -e "${BOLD}Configuring Caddy local HTTPS...${NC}"
    mkdir -p /etc/caddy
    if [ -f "$CADDYFILE" ] && ! grep -q 'ChoreGremlin managed' "$CADDYFILE"; then
        cp -a "$CADDYFILE" "$CADDY_BACKUP"
        echo -e "  ${YELLOW}Saved the existing Caddyfile to $CADDY_BACKUP${NC}"
    fi
    cat > "$CADDYFILE" <<'CADDY'
# ChoreGremlin managed - local HTTPS
{
    auto_https disable_redirects
}

https://familyhub.local {
    tls internal
    reverse_proxy 127.0.0.1:__APP_PORT__
}

https://__PI_IP__ {
    tls internal
    reverse_proxy 127.0.0.1:__APP_PORT__
}

http://familyhub.local {
    redir https://familyhub.local{uri} permanent
}

http://__PI_IP__ {
    redir https://__PI_IP__{uri} permanent
}
CADDY
    sed -i "s/__APP_PORT__/$CHOSEN_PORT/g; s/__PI_IP__/$PI_IP/g" "$CADDYFILE"
    systemctl enable caddy >/dev/null 2>&1 || true
    systemctl restart caddy

    echo -e "${BOLD}Checking HTTPS answers...${NC}"
    CADDY_OK=0
    for _ in $(seq 1 20); do
        if curl -kfsS -H 'Host: familyhub.local' -o /dev/null "https://127.0.0.1/login"; then
            CADDY_OK=1
            break
        fi
        sleep 1
    done
    if [ "$CADDY_OK" -ne 1 ]; then
        echo -e "${YELLOW}Caddy did not answer, so HTTPS will be turned off and the hub will stay on plain HTTP.${NC}"
        echo -e "  Check: sudo journalctl -u caddy -n 50"
        disable_https_fallback
    else
        CA_CERT=""
        for _ in $(seq 1 10); do
            CA_CERT=$(find /var/lib/caddy /root/.local/share/caddy -path '*/pki/authorities/local/root.crt' -print -quit 2>/dev/null || true)
            if [ -n "$CA_CERT" ]; then
                break
            fi
            sleep 1
        done
        if [ -n "$CA_CERT" ]; then
            cp -f "$CA_CERT" "$DATA_DIR/caddy-root.crt"
            chown "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/caddy-root.crt"
            chmod 644 "$DATA_DIR/caddy-root.crt"
            echo -e "  ${GREEN}Trust certificate saved for the in-app Trust Page${NC}"
        else
            echo -e "  ${YELLOW}The Caddy trust certificate was not found yet. Restart Caddy, then refresh the Trust Page.${NC}"
        fi
    fi
elif [ -f "$CADDYFILE" ] && grep -q 'ChoreGremlin managed' "$CADDYFILE"; then
    if [ -f "$CADDY_BACKUP" ]; then
        mv -f "$CADDY_BACKUP" "$CADDYFILE"
        systemctl restart caddy >/dev/null 2>&1 || true
    else
        rm -f "$CADDYFILE"
        systemctl disable --now caddy >/dev/null 2>&1 || true
    fi
fi

if [ "$OPEN_FIREWALL" = "y" ]; then
    echo -e "${BOLD}Configuring the firewall...${NC}"
    SSH_PORT=$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')
    SSH_PORT=${SSH_PORT:-22}
    ufw allow "${SSH_PORT}/tcp" >/dev/null
    WEB_PORTS=("$CHOSEN_PORT")
    if [ "$HTTPS_WANTED" = "y" ]; then
        WEB_PORTS=(443 80)
    fi
    for web_port in "${WEB_PORTS[@]}"; do
        if [ "$REMOTE_ACCESS" = "y" ]; then
            ufw allow "$web_port/tcp" >/dev/null
        else
            for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
                ufw allow from "$net" to any port "$web_port" proto tcp >/dev/null
            done
        fi
    done
    ufw --force enable >/dev/null
fi

print_summary

echo -e "${BOLD}Next steps${NC}"
if [ "$HTTPS_WANTED" = "y" ]; then
    echo "  1. Open https://$PI_IP on a device on your home Wi-Fi."
    echo "     If the browser warns about the certificate, open https://familyhub.local/trust and install the trust certificate."
else
    echo "  1. Open http://$PI_IP:$CHOSEN_PORT on a device on your home Wi-Fi and sign in as $ADMIN_USERNAME."
fi
echo "  2. Sign in as $ADMIN_USERNAME and set up 2FA when prompted."
echo "  3. Add your children and parents in the app."
echo "  Your data folder: $DATA_DIR"
if [ "$OPEN_FIREWALL" != "y" ]; then
    echo -e "  ${YELLOW}The app's web port is closed in the firewall, so other devices cannot reach it yet.${NC}"
fi
echo ""
