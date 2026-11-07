# Changelog

Phases 1, 2 and 3 of the V2 upgrade are implemented. The installer has not been run on a Raspberry Pi yet, so test it there before treating it as fully proven. Phase 3 has been exercised with local Flask tests and a dry-run installer; the Caddy local certificate and per-device trust flow still need a real Pi and device pass.

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Phase 3 access control: every route now has an explicit public, kiosk, admin or parent rule, with a fail-closed fallback for unregistered endpoints
- Mandatory administrator 2FA: admins are sent to enrollment after signing in, TOTP QR codes are generated locally by the server, and setup no longer trusts a client-supplied secret
- Single-use emergency backup codes are regenerated at 2FA setup, old codes are cleared, and administrators cannot disable 2FA
- Optional Caddy local HTTPS: private local certificate, HTTP-to-HTTPS redirects, localhost-only app binding, and automatic fallback to HTTP if Caddy cannot start
- In-app Trust Page with certificate download and installation guidance for iPhone/iPad, Android, Windows and Mac
- Phase 3 tests for forced admin enrollment, single-use backup codes, disabled admins, fail-closed pages and the public Trust Page
- Phase 2 design system: emerald accent palette, updated design tokens and emerald-tinted dark admin surfaces
- Responsive app shell: a fixed side rail on desktop and a phone top bar with a bottom tab bar and "More" sheet, all generated from the existing navigation registry
- Shared template components for the Chore Gremlin brand mark, icon-and-label buttons, consistent page widths and a transparent SVG progress donut
- New installer with Beginner and Advanced questions, a protected settings file, admin account creation, daily backups, automatic security updates, firewall rules, mDNS (`familyhub.local`) and a login check
- Kiosk PINs are stored hashed, with a 5-minute lockout after 5 wrong attempts
- CSRF protection on all forms and form-style requests, with a friendly "session expired" message
- Friendly error pages for upload, CSRF and unexpected errors
- Fixed the app failing to start: rebuilt the registry (ten currencies with codes, one settings list, one navigation list) and imported the navigation list and settings fields into the app
- Added a command-line tool to change a user's password, with a backup taken first and a 10-character minimum; a new install now starts with an empty database
- Data folder defaults to /var/lib/choregremlin and refuses locations inside the project; the installer no longer copies the repo database
- Currency list (ten currencies, GBP default) in the settings registry
- Clock helper: times stored in UTC and shown in local time
- One upload helper for photos: converts to JPEG, resizes the longest side (400 px for profile photos), strips location data
- Token display macro and a design token stylesheet (colours, spacing, radius, shadows, type scale)
- Verified cleanup removal and rename; removed leftover cleanup timer lines from uninstall and renamed the offline cache to ChoreGremlin
- Single settings list and single navigation list, so settings fields and menu links are defined in one place
- Smoke test (tests/smoke_test.py) that loads every page as admin and fails on server errors
- Schema version tracking and numbered migrations, with a backup before pending migrations
- Stable session secret kept beside the database, so restarts no longer log people out
- Chore icon dropdown on the add and edit chore forms, listing Chore_Images by name, with a browse option for your own image (an upload takes priority)
- Events helper (events.py) with a publish call, ready for later phases
- Git ignore rules for databases, caches, backups, uploads and secrets, with existing databases and `.pyc` files untracked
- "Your data" panel on the Settings page showing the data folder and record counts
- Supported devices section in the README
- Update script that reads the protected settings file, backs up the database before pulling, uses `git pull --ff-only`, updates dependencies and checks that the service restarted
- Installer moves a legacy database out of the app folder, fixes app-folder ownership and only changes the firewall when asked

### Changed
- Administrator accounts always require 2FA; parent accounts can still opt in, and remote access still requires a code from accounts that have 2FA configured
- Login now shows the authentication-code field again after an invalid TOTP or backup code instead of silently returning to the password-only form
- Network and installer output use the HTTPS web port (443) when Caddy is enabled, while the Flask app stays on localhost
- Installer preserves an existing HTTPS choice during reinstall, opens the correct firewall ports, and advertises `_https._tcp` via Avahi when HTTPS is on
- Uninstall restores a previous Caddyfile or removes the Chore Gremlin-managed one, and only removes HTTPS firewall rules when they were enabled
- Default brand name is now "Chore Gremlin" and the default accent colour is emerald (`#10b981`)
- Every full page now uses a shared maximum-width container, with form, narrow, standard and kiosk widths
- Page action headers wrap cleanly on small screens, and tables keep their horizontal scroll containers
- Minimum password length raised to 10 characters
- Mobile zoom re-enabled (viewport no longer blocks pinch zoom)
- Systemd unit files renamed to choregremlin-*, single copy in deploy/, and the installer now installs the auto-update timer
- Currency amounts display with the selected currency symbol instead of a hard-coded pound sign
- PWA cache bumped to `choregremlin-v3` so the new theme assets are picked up after an update

### Removed
- Automatic one-year data deletion: cleanup script, timer, manual cleanup button and related wording
- Duplicate deploy installer (root installer is the only one)
- Package manifest, lock file, editor prompt file and npm build step (the project is plain Flask with no build step)
- Stale duplicate HTML, CSS and JavaScript copies from the repo root; templates/ and static/ are the real files

## [1.0.0] - 2026-10-01

### Added
- Initial release of ChoreGremlin
- Child profiles with first name, surname, nickname, date of birth, theme colour, status, and photo
- Kiosk mode with touch-friendly interface and optional PIN
- Family dashboard with notices, events, and activity feed
- Chore management with assignment and approval workflow
- Payment tracking with monthly earnings and balances
- Customisable reward token (name, logo, GBP value)
- Storage management with drive detection and rollback
- Network settings with QR code and configurable port (default 8473)
- Security: remote access toggle, TOTP 2FA, login rate limiting, audit log
- Backup and restore
- System info page (CPU temp, memory, disk, service status)
- 1-year data retention with automatic cleanup
- Auto-update via systemd timer
- Auto-restart on power loss via systemd
- PWA support (installable, offline-capable)
- One-command installer for Raspberry Pi
- Update and uninstall scripts
- GitHub Actions release workflow
