# Changelog

Phases 1 through 17 of the V2 upgrade are implemented and covered by the local test suite. The installer has not been run on a Raspberry Pi yet, so test it there before treating it as fully proven; the Caddy local certificate and per-device trust flow still need a real Pi and device pass.

All notable changes to this project will be documented in this file.

## [2.1.0] - 2026-11-13

### Fixed
- Automatic non-destructive migration adds `chore_logs.is_extra` to existing databases without dropping or rewriting chore history, streaks, balances or settings
- Kiosk navigation freeze caused by unclosed SSE connections and service-worker interception of `/events/stream`
- Service-worker navigation now falls back to the cached shell after a short timeout instead of hanging indefinitely
- Background scroll is locked while any Bootstrap modal is open, including the Add Custom Milestone dialog
- Top action buttons now scroll horizontally on narrow screens instead of running off-screen

### Added
- Request Extra Chore workflow on the child kiosk, with duplicate prevention and parental approval
- Extra chores are stored as independent records (`chore_logs.is_extra`) so they never reset or interfere with daily, weekly or monthly schedules
- Extra-chore approvals create a separate payment and are labelled in the approval queue
- Chore Gremlin ASCII banner is printed on server startup

## [Unreleased]

### Added
- Security & Vulnerabilities dashboard for administrators, mapping SQL injection, CSRF, XSS, broken authentication, session hijacking and security misconfiguration to live checks, mitigation notes and protected/monitored/vulnerable status
- Security regression coverage for the compliance registry, dashboard access, spoofed proxy headers, unsafe token icons, stored colour injection, user role/status validation and role-targeted account mutations
- Endurance achievement badges for night chores, all-day chore days, consecutive weekend streaks (10/20/30/40/50), and pet cleanings (5/10/25/50/100)
- Special-date achievement badges for New Year's Day, Christmas Day, Halloween, Easter Sunday and each child's birthday, using local dates and the child's saved date of birth
- Category labels in the parent, child-profile and kiosk achievement galleries so chore, endurance, holiday, financial and custom badges are easier to scan
- Phase 17 release construction: portable zip bundles with a generated RELEASE_INFO manifest, SHA-256 checksums, download links and an admin Releases page
- Annotated git tag creation from the Releases page so pushing a tag triggers the existing GitHub release workflow
- Phase 16 security hardening: consistent security headers (CSP, frame denial, referrer and permissions policies, optional HSTS), session cookie hardening and an administrator Security Audit page covering 2FA, HTTPS, CSRF, cookies, secrets, backups, snapshots, failed sign-ins, data-folder permissions, debug mode and update status
- Phase 15 snapshot and rollback tools: manual, pre-update and safety database snapshots with checksums, restore, pruning, storage usage, plus update check/apply actions with an automatic pre-update snapshot
- Phase 14 real-time alerts: an in-process event bus, server-sent events stream, live alerts API, service-worker push handlers and animated toast notifications
- Phase 13 financial reporting: ledger exports, financial summaries and savings, bills and marketplace reports with CSV downloads for the selected date range
- Phase 12 Milestone & Achievement System: a built-in badge catalog covering chore counts, streaks, savings, bills, shopping, levels and XP
- Automatic achievement evaluation after XP awards, earnings, savings deposits, bill payments and marketplace approvals, with idempotent unlocks so badges cannot be earned twice
- Parent-defined custom milestones that can track any achievement metric and award badge-only, bonus XP or bonus-payment rewards
- Badge collection galleries on the parent child-profile page and the kiosk rewards screen, with progress bars, locked states and unlock dates
- Parent broadcast alerts with optional child targeting, expiry dates, icons and colours, plus automatic celebration broadcasts when achievements unlock
- Animated family broadcast banner shown across the app, with per-broadcast dismissal remembered in the browser
- Parent Achievements dashboard for badge progress, custom milestones, recent unlocks, broadcasts and a manual "check now" action
- Phase 12 tests for achievement definitions, custom milestone validation and rewards, automatic triggers, broadcast filtering, route access and page loads
- Phase 11 Bill & Expense Simulation: recurring household bills assigned to children, with weekly, monthly and one-off schedules
- Automated bill scheduling that creates due occurrences, advances recurring due dates and marks one-off bills complete
- Customisable late fees (none, flat amount or percentage) applied once to overdue bills, with overdue tracking and balances
- Automated payroll deduction from approved chore earnings, applied after any active loan repayment, with partial payments when earnings are smaller than the bill
- Parent bills dashboard for creating, pausing, deleting and manually paying bills, plus per-child outstanding and overdue summaries
- Kiosk bills screen where children can see what they owe, pay from spendable balance and review paid bills
- Bill payment ledger entries routed through the existing payments table, plus a bill-payment link table for audit history
- Phase 11 tests for due-date maths, late fees, scheduling idempotency, auto-deduction, partial payments, manual payments, route access and page loads
- Phase 10 Savings Vaults and Automated Goal Engine: goal-oriented savings vaults with target balances, optional target dates, visual progress bars and completion tracking
- Goal locking rules that block withdrawals until the target date or target balance is reached, with parent controls to remove locks or close a goal and return its balance to spendable
- Parent matching rules that automatically add a percentage match to child vault contributions, with a configurable weekly cap and goal-specific rules overriding all-goal rules
- Vault deposit, withdrawal, match and close-refund ledger entries, plus spendable-balance validation and parent/child vault management screens
- Phase 10 tests for vault progress and lock calculations, matching caps and precedence, deposits, refunds, date and target locks, route access and page loads
- Phase 9 Marketplace and Shop: parent-managed inventory of items, privilege passes and screen-time vouchers, with optional stock limits and per-item approval rules
- Child shop checkout that validates spendable balance, reserves finite stock immediately and records every purchase in the existing payment ledger
- Parent order workflow for pending, approved, fulfilled, rejected and cancelled orders, with automatic refunds and stock restoration on rejection or cancellation
- QR redemption verification: each order gets a secure token, children show a QR code at the kiosk, and parents can scan it to approve or fulfill the reward
- Parent marketplace dashboard and kiosk shop screen, plus Shop navigation links for both parent and child views
- Phase 9 tests for inventory CRUD, balance and stock validation, approval/fulfillment, rejection/cancellation refunds, QR generation, route access and page loads
- Phase 8 Gremlin Central Bank: per-child savings accounts with configurable daily or weekly compound interest
- Child savings deposits and withdrawals move money between the spendable balance and the savings vault, with a full bank transaction ledger
- Loan requests, parent approval or rejection, simple-interest repayment terms, installment tracking and principal credit on approval
- Automatic loan repayment from each approved chore earning, with partial repayments when an earning is smaller than an installment
- Parent bank dashboard for savings settings, deposits, withdrawals, pending loan decisions and active loan tracking
- Kiosk bank screen for children to save, withdraw, request loans and track savings and loan history
- Phase 8 tests for compound interest, lazy interest accrual, savings transfers, loan terms, approval/rejection, auto-repayment, route access and page loads
- Phase 7 gamification: approved chores award XP based on their reward value, with an idempotent XP ledger so a chore can only be paid once
- Daily streak tracking with multiplier tiers from 3, 5, 7, 14 and 30 consecutive days, plus level progression every 100 XP
- Unlockable avatar and title-badge store, with automatic unlocks, per-child equipping, a parent rewards overview and a kiosk rewards screen
- Phase 7 tests for XP calculations, streak resets, level progress, idempotent awards, chore approval and drop-chore XP, reward equipping, route access and page loads
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
- Security hardening now sanitises theme and stored accent colours, escapes token logos and emoji, rejects cross-role kid/parent account mutations, validates user roles and statuses, and clears stale kiosk/staff session state on sign-in
- Login and 2FA audit logging now use the socket address by default; forwarded client addresses are trusted only when `CHOREGREMLIN_TRUST_PROXY` is enabled
- The Security page Remote Access checkbox now stays inside its card on narrow screens, with a resettable Bootstrap margin/float and wrapping label text
- Chores now use a direct Complete action: timer displays, start/finish steps and elapsed-time views have been removed
- Shared chores disappear for every assigned child after the first completion, while individual chores disappear for each child as soon as they complete their own copy
- Active drop chores show a live countdown and token count that update without refreshing; expired unclaimed drops are randomly assigned, and linked chores sync into the child's assigned chore list
- Auto-assigned drop chores now render as active cards with a working Complete button, and completing a linked drop chore records the standard pending chore log for parent approval
- Mobile navigation is contained within the viewport and scrolls vertically instead of overflowing, with stronger light-theme menu borders, shadows and text/icon contrast
- Long drop-chore names and metadata wrap inside their cards instead of spilling outside
- Existing in-progress chore logs are converted to completed logs when the database migrates
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
- PWA cache bumped to `choregremlin-v5` so the new theme assets are picked up after an update

### Removed
- Chore timers, countdown elements, elapsed-time dashboard columns and the kiosk timer JavaScript
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
