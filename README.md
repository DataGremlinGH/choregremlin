# ChoreGremlin

### The little gremlin that gets the chores done

A self-hosted family chore and allowance tracker for Raspberry Pi. Runs entirely on your local network — no cloud, no subscriptions, no data leaving your home.

---

## What it does

- **Kids** tap their photo to log in, pick a chore, start a timer, and tap "Done" when finished
- **Parents** approve or reject completed chores, record payments, and see who earned what
- **Admins** manage everything: users, settings, storage, network, security, backups

## Features

- **Kiosk Mode** — Touch-friendly interface with large buttons. Kids tap their face photo to log in. Optional 4-6 digit PIN.
- **Child Profiles** — First name, surname, nickname, date of birth, theme colour, profile photo, and status (active, holiday, sick, grounded, excused, custom).
- **Chore Approval** — Parents approve or reject completed chores before payment is recorded.
- **Custom Reward Token** — Call your currency whatever you want (Widgets, Stars, Galleons). Set its value in pounds. Upload a logo or pick an emoji.
- **Family Dashboard** — Family logo, current date, notices, recent activity, upcoming events, and children status overview.
- **Payment Tracking** — Record payouts, bonuses, and adjustments. See running balances per child.
- **Family Notices** — Post announcements with optional expiry dates.
- **Calendar Events** — Schedule family events with date, time, and description. Kids can view and add events from the kiosk.
- **Drop Chores** — Post time-sensitive bonus chores with a point value that decays over time. Kids race to claim them before the points drop or the chore expires. Great for getting extra jobs done fast.
- **Storage Management** — Move all data to a USB drive or network share. Detect available drives, verify copy, one-click rollback.
- **Network Settings** — Configurable port (default 8473), QR code for easy device connection, `familyhub.local` via Avahi.
- **Security** — Remote access toggle (LAN-only by default), TOTP two-factor authentication, login rate limiting, lockout, login audit log, secure cookies.
- **Backup & Restore** — Download and restore the full database from the admin panel.
- **Auto-Update** — Checks for updates hourly. Enable/disable in settings.
- **Auto-Restart** — Systemd service restarts on power loss or crash.
- **Records kept forever** — Nothing is ever deleted automatically.
- **System Info** — CPU temperature, memory, disk usage, service status.
- **PWA Support** — Installable on tablets/phones, works offline.

## Quick Start

### One-Command Install (Recommended)

On your Raspberry Pi:

```bash
curl -sSL https://raw.githubusercontent.com/DataGremlinGH/ChoreGremlin/main/install.sh | bash
```

The installer walks you through everything with simple yes/no questions and recommended defaults. It takes about 2 minutes.

### Manual Install

```bash
git clone https://github.com/DataGremlinGH/ChoreGremlin.git
cd ChoreGremlin
pip3 install -r requirements.txt
python3 app.py
```

Then open `http://<pi-ip-address>:8473` in your browser.

### First-Time Setup

1. Open the app in your browser
2. You'll be redirected to the setup page — create your admin account
3. Sign in with your admin credentials
4. Add your kids (name, photo, optional PIN, date of birth, theme colour, status)
5. Add chores (name, icon, pay amount)
6. Point your tablet to the Pi's IP address to enter kiosk mode

## User Roles

| Role | What they can do |
|------|-----------------|
| **Administrator** | Full control: manage kids, chores, payments, users, settings, storage, network, security, backup, system. Reset passwords and PINs. |
| **Parent** | View kids, chores, payments, history. Approve/reject chores. Add notices and events. Cannot access system settings. |
| **Child** | Kiosk only: tap photo, enter PIN (if set), start/finish chores. Large touch-friendly buttons. |

## One-Command Install Options

The installer asks about:

- **Storage location** — Keep data on the SD card or move to a USB drive
- **Token name** — What to call your reward currency (default: Widgets)
- **Port** — Which port to use (default: 8473, avoids common ports)
- **Remote access** — Whether to allow access from outside your home (default: off)
- **2FA** — Whether to set up two-factor authentication (recommended if enabling remote access)
- **Automatic backups** — Daily database backup (default: on)
- **Auto-update** — Hourly check for new versions (default: on)
- **Firewall** — Open the chosen port in ufw (default: yes)

## Updating

```bash
# Update manually
sudo bash /opt/choregremlin/update.sh

# Or let auto-update handle it (enabled by default)
```

## Uninstalling

```bash
sudo bash /opt/choregremlin/uninstall.sh
```

Choose whether to keep or delete your data.

## Service Management

```bash
# Check status
sudo systemctl status choregremlin

# View live logs
sudo journalctl -u choregremlin -f

# Restart
sudo systemctl restart choregremlin

# Stop
sudo systemctl stop choregremlin
```

## Network Access

The app is reachable at:

- `http://<pi-ip-address>:8473` — by IP address
- `http://familyhub.local:8473` — by local name (via Avahi)

**Tip:** Reserve your Pi's IP address in your router's DHCP settings so it doesn't change.

## Remote Access (Optional)

By default, the app is only accessible on your local Wi-Fi. To access it from outside your home:

1. **Set up HTTPS** — Use Caddy or Nginx with Let's Encrypt (for a domain) or DuckDNS (for dynamic IP)
2. **Enable 2FA** — Go to Security > Set Up 2FA in the app
3. **Enable Remote Access** — Go to Security and toggle it on
4. **Forward the port** — Forward port 8473 on your router to your Pi

See the in-app Security page for a plain-English guide to safe port forwarding.

## Tech Stack

- **Python 3** + **Flask** web framework
- **SQLite** database
- **Bootstrap 5** UI (bundled locally, no CDN)
- **Pillow** for photo resizing
- **qrcode** for QR codes
- **PWA** manifest + service worker

## Project Structure

```
app.py              Flask application with all routes
db.py               SQLite database module (schema + helpers)
requirements.txt    Python dependencies
config.example      Example environment configuration
VERSION             Current version
install.sh          One-command installer
update.sh           Manual update script
uninstall.sh        Uninstall script
deploy/
  auto-update.sh     Auto-update script (runs via timer)
  choregremlin.service          systemd service
  choregremlin-update.service   systemd auto-update service
  choregremlin-update.timer     systemd auto-update timer
instance/           SQLite database (auto-created, gitignored)
static/
  css/               Bootstrap + custom theme
  js/                Bootstrap + custom JS + service worker
  icons/             PWA icons
  uploads/           Photos and logos (gitignored)
templates/           Jinja2 HTML templates (31 pages)
.github/
  workflows/
    release.yml      GitHub Actions release workflow
```

## Backup

The database is a single file. You can:

- Download a backup from the app's **Backup** page
- Use automatic daily backups (enabled by the installer)
- Copy the file manually: `cp /opt/choregremlin/data/choregremlin.db backup.db`

## License

MIT License — see [LICENSE](LICENSE).

## Contributing

This project is designed for families. If you'd like to contribute, please open an issue or pull request at [github.com/DataGremlinGH/ChoreGremlin](https://github.com/DataGremlinGH/ChoreGremlin).
