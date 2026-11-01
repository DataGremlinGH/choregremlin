# Changelog

NEXT: Phase 1 (installer written but not yet run; test on a Raspberry Pi before marking Phase 1 done)

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- New installer with Beginner and Advanced questions, a protected settings file, admin account creation, daily backups, automatic security updates, firewall rules and a login check
- Kiosk PINs are stored hashed, with a 5-minute lockout after 5 wrong attempts
- CSRF protection on all forms and form-style requests
- Fixed the app failing to start: rebuilt the registry (ten currencies with codes, one settings list, one navigation list) and imported the navigation list and settings fields into the app
- Data folder defaults to /var/lib/choregremlin, refuses locations inside the project, and copies an existing database once without overwriting
- Currency list (ten currencies, GBP default) in the settings registry
- Clock helper: times stored in UTC and shown in local time
- One upload helper for photos: converts to JPEG, resizes the longest side (400 px for profile photos), strips location data
- Token display macro and a design token stylesheet (colours, spacing, radius, shadows, type scale)
- Verified cleanup removal and rename; removed leftover cleanup timer lines from uninstall and renamed the offline cache to ChoreGremlin
- Single settings list and single navigation list, so settings fields and menu links are defined in one place
- Smoke test (tests/smoke_test.py) that loads every page as admin and fails on server errors
- Schema version tracking and numbered migrations, with a backup before pending migrations
- Stable session secret kept beside the database, so restarts no longer log people out
- Secure session cookie when HTTPS is enabled (CHOREGREMLIN_HTTPS=1)
- Events helper (events.py) with a publish call, ready for later phases
- Git ignore rules for databases, caches, backups, uploads and secrets

### Changed
- Minimum password length raised to 10 characters
- Mobile zoom re-enabled (viewport no longer blocks pinch zoom)
- Systemd unit files renamed to choregremlin-*, single copy in deploy/

### Removed
- Automatic one-year data deletion: cleanup script, timer, manual cleanup button and related wording
- Duplicate deploy installer (root installer is the only one)
- Package manifest, lock file, editor prompt file and npm build step (the project is plain Flask with no build step)

### Still to do in Phase 1
- Settings registry, navigation config, token display macro used everywhere
- Login CSRF protection, hashed kiosk PINs, friendly error messages
- Data folder outside the repo, update safety, "Your data" panel
- Installer rewrite (Beginner and Advanced modes)
- Supported devices section, currency list, clock helper
- Owner step: stop tracking databases with git rm --cached (live data stays on the Pi)

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
