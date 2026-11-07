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
- **Custom Reward Token** — Call your currency whatever you want (Widgets, Stars, Galleons). Set its value in your chosen currency. Upload a logo or pick an emoji.
- **Family Dashboard** — Family logo, current date, notices, recent activity, upcoming events, and children status overview.
- **Payment Tracking** — Record payouts, bonuses, and adjustments. See running balances per child.
- **Family Notices** — Post announcements with optional expiry dates.
- **Calendar Events** — Schedule family events with date, time, and description. Kids can view and add events from the kiosk.
- **Drop Chores** — Post time-sensitive bonus chores with a point value that decays over time. Kids race to claim them before the points drop or the chore expires. Great for getting extra jobs done fast.
- **Storage Management** — Move all data to a USB drive or network share. Detect available drives, verify copy, one-click rollback.
- **Network Settings** — Configurable port (default 8473), QR code for easy device connection, `familyhub.local` via Avahi.
- **Security** — Role guards on every page, mandatory 2FA for administrators, TOTP two-factor authentication, single-use backup codes, remote access toggle (LAN-only by default), login rate limiting, lockout, login audit log, secure cookies.
- **Local HTTPS** — Optional Caddy reverse proxy with a private local certificate and an in-app Trust Page for installing the certificate on your devices.
- **Backup & Restore** — Download and restore the full database from the admin panel.
- **Auto-Update** — Checks for updates hourly, backs up the database first and can be switched off in settings.
- **Auto-Restart** — Systemd service restarts on power loss or crash.
- **Records kept forever** — Nothing is ever deleted automatically.
- **System Info** — CPU temperature, memory, disk usage, service status.
- **Responsive App Shell** — Desktop side rail, phone bottom tabs with a More sheet, consistent page widths and emerald admin styling.
- **PWA Support** — Installable on tablets/phones, works offline.

## Quick Start

### One-Command Install (Recommended)

On your Raspberry Pi:

```bash
curl -sSL https://raw.githubusercontent.com/DataGremlinGH/ChoreGremlin/main/install.sh -o install.sh
sudo bash install.sh
```

The installer walks you through everything with simple yes/no questions and recommended defaults. It takes about 2 minutes. Run it from a terminal because it asks a few questions.

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
4. Scan the QR code with an authenticator app. Administrator accounts must set up 2FA before continuing, and you will be shown eight single-use backup codes.
5. Add your kids (name, photo, optional PIN, date of birth, theme colour, status)
6. Add chores (name, icon, pay amount)
7. Point your tablet to the Pi's IP address to enter kiosk mode

## User Roles

| Role | What they can do |
|------|-----------------|
| **Administrator** | Full control: manage kids, chores, payments, users, settings, storage, network, security, backup, system. Reset passwords and PINs. |
| **Parent** | View kids, chores, payments, history. Approve/reject chores. Add notices and events. Cannot access system settings. |
| **Child** | Kiosk only: tap photo, enter PIN (if set), start/finish chores. Large touch-friendly buttons. |

## Supported Devices

ChoreGremlin is designed for a Raspberry Pi on your home network. It also runs on any Debian or Ubuntu computer with Python 3.

- **Recommended:** Raspberry Pi 4 or 5 with 2 GB RAM or more and a 16 GB+ SD card
- **Also works:** Raspberry Pi 3B+ (slower, but fine for a small family), Raspberry Pi Zero 2 W (minimum, expect slower page loads)
- **Displays:** any tablet, phone or computer with a modern browser; wall-mounted tablets work well for kiosk mode
- **Storage:** SD card by default, or a USB drive / network share for photos and backups
- **Network:** local Wi-Fi or Ethernet; no internet connection is needed after installation

## One-Command Install Options

The installer has a **Beginner** mode (recommended defaults) and an **Advanced** mode. It asks about:

- **Storage location** — Keep data on the SD card, move it to a USB drive, or keep an existing data folder
- **Token name and currency** — What to call your reward currency (default: Tokens) and one of ten supported currencies
- **Token value** — What one token is worth in that currency
- **Port** — Which port to use (default: 8473, avoids common ports)
- **Remote access** — Whether to allow access from outside your home (default: off)
- **Security updates** — Automatic operating system updates (default: on)
- **Automatic backups** — Daily database backup (default: on)
- **Firewall** — Open the chosen web port in ufw (default: yes)
- **HTTPS** — Optional Caddy reverse proxy with a private local certificate (Advanced mode; default: off)
- **Admin account** — Your name, username and a password of at least 10 characters

## Updating

```bash
# Update manually (takes a database backup first)
sudo bash /opt/choregremlin/update.sh

# Or let the hourly auto-update timer handle it (enabled by default)
```

The updater reads `/etc/choregremlin/choregremlin.env`, backs up the database, pulls only fast-forward changes, updates Python packages and restarts the service. If the service does not come back, check `sudo journalctl -u choregremlin -n 50`.

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

If HTTPS was enabled during install, use `https://<pi-ip-address>` and `https://familyhub.local` on port 443 instead. The app binds to localhost behind Caddy so the plain HTTP port is not exposed.

**Tip:** Reserve your Pi's IP address in your router's DHCP settings so it doesn't change.

## Local HTTPS and Device Trust (Optional)

Choose HTTPS in the Advanced installer to put Caddy in front of the app with a private local certificate. Open the in-app **Trust Page** (`https://familyhub.local/trust`) and install the trust certificate on each phone, tablet or computer. The page includes instructions for iPhone/iPad, Android, Windows and Mac.

- The certificate is issued by a local certificate authority created on your Pi; nothing is sent to a public certificate authority.
- The installer saves the certificate to your data folder and the Trust Page offers it as a download.
- If you reinstall the hub, download and trust the new certificate.
- If Caddy cannot start, the installer falls back to plain HTTP and keeps the app reachable.

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
- **qrcode** for QR codes, including server-side 2FA setup QR codes
- **Caddy** (optional) for local HTTPS with a private certificate authority
- **PWA** manifest + service worker

## Project Structure

```
app.py              Flask application with all routes
db.py               SQLite database module (schema + helpers)
clock.py            UTC storage and local-time display helpers
registry.py         Currencies, settings fields and navigation in one place
uploads.py          Photo helper (resize, strip location data)
events.py           Event publishing helper
requirements.txt    Python dependencies
config.example      Example environment configuration
VERSION             Current version
install.sh          Installer (Beginner and Advanced modes)
update.sh           Update script (also run by the systemd timer)
uninstall.sh        Uninstall script
scripts/            Maintenance scripts (set_admin_password.py)
tests/              Smoke test and regression tests
deploy/
  choregremlin.service          systemd service
  choregremlin-update.service   systemd auto-update service
  choregremlin-update.timer     systemd auto-update timer
static/
  css/               Bootstrap + custom theme + design tokens
  js/                Bootstrap + custom JS + service worker
  icons/             PWA icons
  uploads/           Photos and logos (gitignored)
templates/           Jinja2 HTML templates
release.yml         GitHub Actions release workflow
```

## Where Your Data Lives

The database, photos and backups live outside the app folder so updates never touch them. The default is `/var/lib/choregremlin/`.

```
/var/lib/choregremlin/choregremlin.db     SQLite database
/var/lib/choregremlin/backups/            Automatic and pre-update backups
/opt/choregremlin/static/uploads/         Uploaded photos and logos
```

The data folder can be changed with `CHOREGREMLIN_DATA_DIR` in `/etc/choregremlin/choregremlin.env`. The app refuses to use a folder inside the project itself, so a bad setting cannot overwrite your code.

## Backup

The database is a single file. You can:

- Download a backup from the app's **Backup** page
- Use automatic daily backups (enabled by the installer)
- Copy the file manually: `sudo cp /var/lib/choregremlin/choregremlin.db backup.db`

## License

MIT License — see [LICENSE](LICENSE).

## Contributing

This project is designed for families. If you'd like to contribute, please open an issue or pull request at [github.com/DataGremlinGH/ChoreGremlin](https://github.com/DataGremlinGH/ChoreGremlin).
