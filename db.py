"""
ChoreGremlin - SQLite Database Module
Handles schema initialization and all data access.
"""

import hashlib
import json
import sqlite3
import os
import secrets
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import clock
import events
import gamification
import banking
import billing
import achievements
import reporting
from hardware import normalize_tag

_REPO_DIR = os.path.dirname(os.path.abspath(__file__))


def _choose_data_dir():
    """Keep live data outside the project. Fall back to the user's data folder on a laptop."""
    configured = os.environ.get('CHOREGREMLIN_DATA_DIR')
    if configured:
        return os.path.abspath(configured)
    system_dir = '/var/lib/choregremlin'
    try:
        os.makedirs(system_dir, exist_ok=True)
        if os.access(system_dir, os.W_OK):
            return system_dir
    except OSError:
        pass
    return os.path.abspath(os.path.join(os.path.expanduser('~'), '.local', 'share', 'choregremlin'))


DATA_DIR = _choose_data_dir()
DB_PATH = os.path.join(DATA_DIR, 'choregremlin.db')
PIN_MAX_FAILURES = 5
PIN_LOCKOUT_MINUTES = 5
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
USER_ROLES = {'admin', 'parent', 'child'}
USER_STATUSES = {'active', 'holiday', 'sick', 'grounded', 'excused', 'custom', 'inactive'}

if os.path.realpath(DATA_DIR) == os.path.realpath(_REPO_DIR) or \
        os.path.realpath(DATA_DIR).startswith(os.path.realpath(_REPO_DIR) + os.sep):
    raise RuntimeError('CHOREGREMLIN_DATA_DIR must be outside the project folder.')

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    surname TEXT,
    nickname TEXT,
    username TEXT UNIQUE,
    email TEXT UNIQUE,
    password_hash TEXT,
    role TEXT NOT NULL DEFAULT 'parent',
    pin TEXT,
    photo_path TEXT,
    color TEXT NOT NULL DEFAULT '#10b981',
    date_of_birth TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    icon TEXT NOT NULL DEFAULT 'bi-list-check',
    chore_emoji TEXT DEFAULT '',
    chore_image TEXT DEFAULT '',
    pay_amount REAL NOT NULL DEFAULT 0,
    repeat_frequency TEXT NOT NULL DEFAULT 'daily',
    due_days TEXT DEFAULT '0,1,2,3,4,5,6',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chore_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chore_id INTEGER NOT NULL REFERENCES chores(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day_of_week INTEGER,
    UNIQUE(chore_id, user_id, day_of_week)
);

CREATE TABLE IF NOT EXISTS chore_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chore_id INTEGER NOT NULL REFERENCES chores(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'completed',
    finished_at TEXT,
    earned_amount REAL NOT NULL DEFAULT 0,
    approved_by INTEGER REFERENCES users(id),
    approved_at TEXT
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount REAL NOT NULL,
    type TEXT NOT NULL DEFAULT 'payout',
    description TEXT DEFAULT '',
    log_id INTEGER REFERENCES chore_logs(id),
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS family_notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT DEFAULT '',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    event_date TEXT NOT NULL,
    event_time TEXT,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    detail TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS login_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    ip_address TEXT,
    success INTEGER NOT NULL DEFAULT 0,
    failure_reason TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS totp_secrets (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    secret TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS backup_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS login_lockout (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    failed_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    last_attempt TEXT,
    UNIQUE(email, ip_address)
);

CREATE TABLE IF NOT EXISTS drop_chores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chore_id INTEGER REFERENCES chores(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    chore_emoji TEXT DEFAULT '',
    chore_image TEXT DEFAULT '',
    initial_points REAL NOT NULL DEFAULT 0,
    current_points REAL NOT NULL DEFAULT 0,
    decay_per_minute REAL NOT NULL DEFAULT 0,
    posted_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'available',
    claimed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    assigned_to INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS rfid_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_uid TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS user_gamification (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    total_xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    current_streak INTEGER NOT NULL DEFAULT 0,
    longest_streak INTEGER NOT NULL DEFAULT 0,
    last_completed_date TEXT,
    equipped_avatar TEXT NOT NULL DEFAULT 'default',
    equipped_badge TEXT NOT NULL DEFAULT '',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS xp_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL DEFAULT 'chore',
    source_id INTEGER,
    reward_amount REAL NOT NULL DEFAULT 0,
    base_xp INTEGER NOT NULL DEFAULT 0,
    streak_days INTEGER NOT NULL DEFAULT 1,
    multiplier REAL NOT NULL DEFAULT 1.0,
    xp_awarded INTEGER NOT NULL DEFAULT 0,
    completed_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_type, source_id)
);

CREATE TABLE IF NOT EXISTS gamification_unlocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    item_key TEXT NOT NULL,
    unlocked_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, item_type, item_key)
);

CREATE TABLE IF NOT EXISTS savings_accounts (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    balance REAL NOT NULL DEFAULT 0,
    annual_interest_rate REAL NOT NULL DEFAULT 5.0,
    compounding TEXT NOT NULL DEFAULT 'weekly',
    last_interest_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS bank_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    balance_after REAL NOT NULL DEFAULT 0,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount_requested REAL NOT NULL DEFAULT 0,
    purpose TEXT DEFAULT '',
    term_weeks INTEGER NOT NULL DEFAULT 1,
    interest_rate REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    principal REAL,
    total_repayable REAL,
    installment_amount REAL,
    amount_repaid REAL NOT NULL DEFAULT 0,
    remaining_balance REAL,
    start_date TEXT,
    next_due_date TEXT,
    approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_at TEXT,
    rejected_reason TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS loan_repayments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
    amount REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'earning',
    paid_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS marketplace_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    category TEXT NOT NULL DEFAULT 'item',
    price REAL NOT NULL DEFAULT 0,
    currency_type TEXT NOT NULL DEFAULT 'token',
    token_price REAL,
    cash_price REAL,
    stock_quantity INTEGER,
    icon TEXT NOT NULL DEFAULT 'bi-bag-fill',
    color TEXT NOT NULL DEFAULT '#10b981',
    is_active INTEGER NOT NULL DEFAULT 1,
    requires_approval INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS marketplace_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id INTEGER REFERENCES marketplace_items(id) ON DELETE SET NULL,
    item_name TEXT NOT NULL,
    item_category TEXT NOT NULL DEFAULT 'item',
    unit_price REAL NOT NULL DEFAULT 0,
    currency_type TEXT NOT NULL DEFAULT 'token',
    token_amount REAL NOT NULL DEFAULT 0,
    cash_amount REAL NOT NULL DEFAULT 0,
    quantity INTEGER NOT NULL DEFAULT 1,
    total_amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    qr_token TEXT NOT NULL UNIQUE,
    notes TEXT DEFAULT '',
    rejection_reason TEXT DEFAULT '',
    requested_at TEXT NOT NULL DEFAULT (datetime('now')),
    approved_at TEXT,
    approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    fulfilled_at TEXT,
    fulfilled_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS cash_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount REAL NOT NULL DEFAULT 0,
    description TEXT DEFAULT '',
    reference_type TEXT DEFAULT '',
    reference_id INTEGER,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS savings_vaults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    target_amount REAL NOT NULL DEFAULT 0,
    target_date TEXT,
    lock_until_date INTEGER NOT NULL DEFAULT 0,
    lock_until_target INTEGER NOT NULL DEFAULT 0,
    balance REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    icon TEXT NOT NULL DEFAULT 'bi-bullseye',
    color TEXT NOT NULL DEFAULT '#10b981',
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS savings_vault_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_id INTEGER NOT NULL REFERENCES savings_vaults(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    balance_after REAL NOT NULL DEFAULT 0,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS savings_match_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vault_id INTEGER REFERENCES savings_vaults(id) ON DELETE CASCADE,
    match_percent REAL NOT NULL DEFAULT 50,
    weekly_cap REAL NOT NULL DEFAULT 10,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS household_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    amount REAL NOT NULL DEFAULT 0,
    frequency TEXT NOT NULL DEFAULT 'weekly',
    next_due_date TEXT NOT NULL,
    auto_deduct INTEGER NOT NULL DEFAULT 1,
    late_fee_type TEXT NOT NULL DEFAULT 'none',
    late_fee_value REAL NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS bill_occurrences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL REFERENCES household_bills(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    amount REAL NOT NULL DEFAULT 0,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'due',
    amount_paid REAL NOT NULL DEFAULT 0,
    late_fee_amount REAL NOT NULL DEFAULT 0,
    late_fee_applied_at TEXT,
    paid_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    UNIQUE(bill_id, due_date)
);

CREATE TABLE IF NOT EXISTS bill_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurrence_id INTEGER NOT NULL REFERENCES bill_occurrences(id) ON DELETE CASCADE,
    payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
    amount REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'earning',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS broadcast_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'general',
    child_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    achievement_key TEXT,
    icon TEXT NOT NULL DEFAULT 'bi-megaphone-fill',
    color TEXT NOT NULL DEFAULT '#10b981',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS custom_milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    icon TEXT NOT NULL DEFAULT 'bi-award-fill',
    color TEXT NOT NULL DEFAULT '#10b981',
    metric TEXT NOT NULL,
    threshold REAL NOT NULL DEFAULT 1,
    reward_type TEXT NOT NULL DEFAULT 'none',
    reward_value REAL NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS achievement_unlocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    achievement_key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    icon TEXT NOT NULL DEFAULT 'bi-award-fill',
    color TEXT NOT NULL DEFAULT '#10b981',
    metric TEXT NOT NULL DEFAULT '',
    threshold REAL NOT NULL DEFAULT 0,
    reward_type TEXT NOT NULL DEFAULT 'none',
    reward_value REAL NOT NULL DEFAULT 0,
    reward_payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
    broadcast_id INTEGER REFERENCES broadcast_alerts(id) ON DELETE SET NULL,
    unlocked_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, achievement_key)
);

CREATE TABLE IF NOT EXISTS live_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL DEFAULT 'message',
    title TEXT DEFAULT '',
    body TEXT DEFAULT '',
    payload TEXT DEFAULT '{}',
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    child_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS system_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    filename TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'manual',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    checksum TEXT DEFAULT '',
    note TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ready',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_db():
    """Get a database connection for the Flask app context."""
    from flask import g
    if 'db' not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(e=None):
    """Close the database connection at request end."""
    from flask import g
    db = g.pop('db', None)
    if db is not None:
        db.close()


def _drop_started_at_column(conn):
    conn.execute(
        "UPDATE chore_logs SET finished_at=datetime('now') "
        "WHERE status='completed' AND finished_at IS NULL"
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(chore_logs)").fetchall()}
    if 'started_at' in columns:
        conn.execute("ALTER TABLE chore_logs DROP COLUMN started_at")


MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN surname TEXT",
    "ALTER TABLE users ADD COLUMN nickname TEXT",
    "ALTER TABLE users ADD COLUMN date_of_birth TEXT",
    "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
    "ALTER TABLE users ADD COLUMN username TEXT",
    "ALTER TABLE chores ADD COLUMN chore_emoji TEXT DEFAULT ''",
    "ALTER TABLE chores ADD COLUMN chore_image TEXT DEFAULT ''",
    "ALTER TABLE chores ADD COLUMN repeat_frequency TEXT NOT NULL DEFAULT 'daily'",
    "ALTER TABLE chores ADD COLUMN due_days TEXT DEFAULT '0,1,2,3,4,5,6'",
    "ALTER TABLE chores ADD COLUMN single_child_only INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE payments ADD COLUMN payout_method TEXT DEFAULT ''",
    "ALTER TABLE payments ADD COLUMN token_amount REAL DEFAULT 0",
    "ALTER TABLE payments ADD COLUMN gbp_amount REAL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN wallpaper TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN can_do_hard_chores INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE chores ADD COLUMN requires_hard_chores INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN pin_failures INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN pin_locked_until TEXT",
    """CREATE TABLE IF NOT EXISTS rfid_tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tag_uid TEXT NOT NULL UNIQUE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        label TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS user_gamification (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        total_xp INTEGER NOT NULL DEFAULT 0,
        level INTEGER NOT NULL DEFAULT 1,
        current_streak INTEGER NOT NULL DEFAULT 0,
        longest_streak INTEGER NOT NULL DEFAULT 0,
        last_completed_date TEXT,
        equipped_avatar TEXT NOT NULL DEFAULT 'default',
        equipped_badge TEXT NOT NULL DEFAULT '',
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS xp_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source_type TEXT NOT NULL DEFAULT 'chore',
        source_id INTEGER,
        reward_amount REAL NOT NULL DEFAULT 0,
        base_xp INTEGER NOT NULL DEFAULT 0,
        streak_days INTEGER NOT NULL DEFAULT 1,
        multiplier REAL NOT NULL DEFAULT 1.0,
        xp_awarded INTEGER NOT NULL DEFAULT 0,
        completed_date TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(source_type, source_id)
    )""",
    """CREATE TABLE IF NOT EXISTS gamification_unlocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        item_type TEXT NOT NULL,
        item_key TEXT NOT NULL,
        unlocked_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(user_id, item_type, item_key)
    )""",
    """CREATE TABLE IF NOT EXISTS savings_accounts (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        balance REAL NOT NULL DEFAULT 0,
        annual_interest_rate REAL NOT NULL DEFAULT 5.0,
        compounding TEXT NOT NULL DEFAULT 'weekly',
        last_interest_at TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS bank_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        type TEXT NOT NULL,
        amount REAL NOT NULL DEFAULT 0,
        balance_after REAL NOT NULL DEFAULT 0,
        description TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        amount_requested REAL NOT NULL DEFAULT 0,
        purpose TEXT DEFAULT '',
        term_weeks INTEGER NOT NULL DEFAULT 1,
        interest_rate REAL,
        status TEXT NOT NULL DEFAULT 'pending',
        principal REAL,
        total_repayable REAL,
        installment_amount REAL,
        amount_repaid REAL NOT NULL DEFAULT 0,
        remaining_balance REAL,
        start_date TEXT,
        next_due_date TEXT,
        approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        approved_at TEXT,
        rejected_reason TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS loan_repayments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
        payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
        amount REAL NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT 'earning',
        paid_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS marketplace_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        category TEXT NOT NULL DEFAULT 'item',
        price REAL NOT NULL DEFAULT 0,
        stock_quantity INTEGER,
        icon TEXT NOT NULL DEFAULT 'bi-bag-fill',
        color TEXT NOT NULL DEFAULT '#10b981',
        is_active INTEGER NOT NULL DEFAULT 1,
        requires_approval INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS marketplace_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        item_id INTEGER REFERENCES marketplace_items(id) ON DELETE SET NULL,
        item_name TEXT NOT NULL,
        item_category TEXT NOT NULL DEFAULT 'item',
        unit_price REAL NOT NULL DEFAULT 0,
        quantity INTEGER NOT NULL DEFAULT 1,
        total_amount REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        qr_token TEXT NOT NULL UNIQUE,
        notes TEXT DEFAULT '',
        rejection_reason TEXT DEFAULT '',
        requested_at TEXT NOT NULL DEFAULT (datetime('now')),
        approved_at TEXT,
        approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        fulfilled_at TEXT,
        fulfilled_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS savings_vaults (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        target_amount REAL NOT NULL DEFAULT 0,
        target_date TEXT,
        lock_until_date INTEGER NOT NULL DEFAULT 0,
        lock_until_target INTEGER NOT NULL DEFAULT 0,
        balance REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',
        icon TEXT NOT NULL DEFAULT 'bi-bullseye',
        color TEXT NOT NULL DEFAULT '#10b981',
        completed_at TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS savings_vault_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vault_id INTEGER NOT NULL REFERENCES savings_vaults(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
        type TEXT NOT NULL,
        amount REAL NOT NULL DEFAULT 0,
        balance_after REAL NOT NULL DEFAULT 0,
        description TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS savings_match_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        vault_id INTEGER REFERENCES savings_vaults(id) ON DELETE CASCADE,
        match_percent REAL NOT NULL DEFAULT 50,
        weekly_cap REAL NOT NULL DEFAULT 10,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS household_bills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'other',
        amount REAL NOT NULL DEFAULT 0,
        frequency TEXT NOT NULL DEFAULT 'weekly',
        next_due_date TEXT NOT NULL,
        auto_deduct INTEGER NOT NULL DEFAULT 1,
        late_fee_type TEXT NOT NULL DEFAULT 'none',
        late_fee_value REAL NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS bill_occurrences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id INTEGER NOT NULL REFERENCES household_bills(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'other',
        amount REAL NOT NULL DEFAULT 0,
        due_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'due',
        amount_paid REAL NOT NULL DEFAULT 0,
        late_fee_amount REAL NOT NULL DEFAULT 0,
        late_fee_applied_at TEXT,
        paid_at TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT,
        UNIQUE(bill_id, due_date)
    )""",
    """CREATE TABLE IF NOT EXISTS bill_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        occurrence_id INTEGER NOT NULL REFERENCES bill_occurrences(id) ON DELETE CASCADE,
        payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
        amount REAL NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT 'earning',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS broadcast_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'general',
        child_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        achievement_key TEXT,
        icon TEXT NOT NULL DEFAULT 'bi-megaphone-fill',
        color TEXT NOT NULL DEFAULT '#10b981',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        expires_at TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS custom_milestones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        icon TEXT NOT NULL DEFAULT 'bi-award-fill',
        color TEXT NOT NULL DEFAULT '#10b981',
        metric TEXT NOT NULL,
        threshold REAL NOT NULL DEFAULT 1,
        reward_type TEXT NOT NULL DEFAULT 'none',
        reward_value REAL NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS achievement_unlocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        achievement_key TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        icon TEXT NOT NULL DEFAULT 'bi-award-fill',
        color TEXT NOT NULL DEFAULT '#10b981',
        metric TEXT NOT NULL DEFAULT '',
        threshold REAL NOT NULL DEFAULT 0,
        reward_type TEXT NOT NULL DEFAULT 'none',
        reward_value REAL NOT NULL DEFAULT 0,
        reward_payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
        broadcast_id INTEGER REFERENCES broadcast_alerts(id) ON DELETE SET NULL,
        unlocked_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(user_id, achievement_key)
    )""",
    """CREATE TABLE IF NOT EXISTS live_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL DEFAULT 'message',
        title TEXT DEFAULT '',
        body TEXT DEFAULT '',
        payload TEXT DEFAULT '{}',
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        child_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS system_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        filename TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL DEFAULT 'manual',
        size_bytes INTEGER NOT NULL DEFAULT 0,
        checksum TEXT DEFAULT '',
        note TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'ready',
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "ALTER TABLE marketplace_items ADD COLUMN currency_type TEXT NOT NULL DEFAULT 'token'",
    "ALTER TABLE marketplace_items ADD COLUMN token_price REAL",
    "ALTER TABLE marketplace_items ADD COLUMN cash_price REAL",
    "ALTER TABLE marketplace_orders ADD COLUMN currency_type TEXT NOT NULL DEFAULT 'token'",
    "ALTER TABLE marketplace_orders ADD COLUMN token_amount REAL NOT NULL DEFAULT 0",
    "ALTER TABLE marketplace_orders ADD COLUMN cash_amount REAL NOT NULL DEFAULT 0",
    """CREATE TABLE IF NOT EXISTS cash_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        amount REAL NOT NULL DEFAULT 0,
        description TEXT DEFAULT '',
        reference_type TEXT DEFAULT '',
        reference_id INTEGER,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "UPDATE chore_logs SET status='completed', finished_at=COALESCE(finished_at, datetime('now')) WHERE status='in_progress'",
    _drop_started_at_column,
]


COLOR_TABLES = (
    'users', 'marketplace_items', 'savings_vaults', 'broadcast_alerts',
    'custom_milestones', 'achievement_unlocks',
)


def _normalise_stored_colors(conn):
    """Defuse legacy CSS-injection payloads stored in colour columns."""
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for table in COLOR_TABLES:
        if table not in tables:
            continue
        columns = {
            row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if 'color' not in columns:
            continue
        rows = conn.execute(f"SELECT id, color FROM {table}").fetchall()
        for row_id, color in rows:
            clean = achievements.clean_color(color)
            if clean != color:
                conn.execute(
                    f"UPDATE {table} SET color=? WHERE id=?", (clean, row_id)
                )


def _backup_database():
    """Write a dated copy of the database into backups/ before migrations change it."""
    backup_dir = os.path.join(os.path.dirname(DB_PATH), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    dest = os.path.join(backup_dir, f'choregremlin-{stamp}-pre-migration.db')
    src_conn = sqlite3.connect(DB_PATH)
    dst_conn = sqlite3.connect(dest)
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    print(f'Database backed up to {dest} before migrations.')


def init_db():
    """Create the schema, then apply numbered migrations that are not yet recorded."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    had_tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 0
    conn.executescript(SCHEMA)
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
    pending = [(number, sql) for number, sql in enumerate(MIGRATIONS, start=1) if number > current]
    conn.commit()
    conn.close()
    if pending and had_tables:
        _backup_database()
    conn = sqlite3.connect(DB_PATH)
    for number, migration in pending:
        try:
            if callable(migration):
                migration(conn)
            else:
                conn.execute(migration)
        except sqlite3.OperationalError as e:
            if 'duplicate column' not in str(e):
                raise
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (number,))
    plain_pins = conn.execute(
        "SELECT id, pin FROM users WHERE pin IS NOT NULL AND pin NOT LIKE 'scrypt:%' AND pin NOT LIKE 'pbkdf2:%'"
    ).fetchall()
    for user_id, plain_pin in plain_pins:
        conn.execute("UPDATE users SET pin=? WHERE id=?", (generate_password_hash(plain_pin), user_id))
    for key, spec in UI_LAYOUT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, spec['default'])
        )
    _normalise_stored_colors(conn)
    conn.commit()
    conn.close()


def is_setup_complete():
    """Check if initial setup has been done (admin account exists)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    user = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    conn.close()
    return user is not None


# --- User helpers ---

PIN_MAX_LENGTH = 64


def validate_password(password, minimum=10):
    """Validate staff/admin passwords while allowing any character content."""
    password = password or ''
    if len(password) < minimum:
        raise ValueError(f'Password must be at least {minimum} characters.')
    return password


def validate_pin(pin):
    """Normalise and validate a child kiosk PIN of any practical length."""
    if pin is None:
        return None
    pin = str(pin).strip()
    if not pin:
        return None
    if not pin.isdigit():
        raise ValueError('PIN must contain digits only.')
    if len(pin) > PIN_MAX_LENGTH:
        raise ValueError(f'PIN must be {PIN_MAX_LENGTH} digits or fewer.')
    return pin


def _hash_pin(pin):
    pin = validate_pin(pin)
    return generate_password_hash(pin) if pin else None


def _clean_user_status(status):
    text = str(status or '').strip().lower()
    return text if text in USER_STATUSES else 'active'


def create_user(name, email, password, role='parent', pin=None, photo_path=None,
                   surname=None, nickname=None, date_of_birth=None, color='#10b981', status='active',
                   username=None):
    role = str(role or '').strip().lower()
    if role not in USER_ROLES:
        raise ValueError('Invalid user role.')
    db = get_db()
    pw_hash = generate_password_hash(validate_password(password)) if password else None
    pin_hash = _hash_pin(pin)
    cursor = db.execute(
        """INSERT INTO users (name, surname, nickname, username, email, password_hash, role, pin, photo_path, color, date_of_birth, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, surname, nickname, username, email, pw_hash, role, pin_hash, photo_path,
         achievements.clean_color(color), date_of_birth, _clean_user_status(status))
    )
    db.commit()
    return cursor.lastrowid


def get_user(user_id):
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def get_user_by_email(email):
    db = get_db()
    return db.execute("SELECT * FROM users WHERE email=? AND email IS NOT NULL", (email,)).fetchone()


def get_user_by_username(username):
    db = get_db()
    return db.execute("SELECT * FROM users WHERE username=? AND username IS NOT NULL", (username,)).fetchone()


def get_user_by_login(login):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username=? AND username IS NOT NULL", (login,)).fetchone()
    if row:
        return row
    return db.execute("SELECT * FROM users WHERE email=? AND email IS NOT NULL", (login,)).fetchone()


def get_all_users(role=None):
    db = get_db()
    if role:
        return db.execute("SELECT * FROM users WHERE role=? AND is_active=1 ORDER BY name", (role,)).fetchall()
    return db.execute("SELECT * FROM users WHERE is_active=1 ORDER BY name").fetchall()


def get_children():
    db = get_db()
    return db.execute("SELECT * FROM users WHERE role='child' AND is_active=1 ORDER BY name").fetchall()


def update_user(user_id, **fields):
    db = get_db()
    allowed = {'name', 'surname', 'nickname', 'username', 'email', 'password_hash', 'role', 'pin',
               'photo_path', 'is_active', 'color', 'date_of_birth', 'status', 'wallpaper', 'can_do_hard_chores'}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            if k == 'pin':
                v = _hash_pin(v)
            elif k == 'role':
                v = str(v or '').strip().lower()
                if v not in USER_ROLES:
                    raise ValueError('Invalid user role.')
            elif k == 'status':
                v = _clean_user_status(v)
            elif k == 'color':
                v = achievements.clean_color(v)
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(user_id)
    db.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", vals)
    db.commit()


def delete_user(user_id):
    db = get_db()
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()


def verify_password(user, password):
    if not user or not user['password_hash']:
        return False
    return check_password_hash(user['password_hash'], password)


def set_password(user_id, password):
    password = validate_password(password)
    db = get_db()
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(password), user_id))
    db.commit()


def set_pin(user_id, pin):
    pin = validate_pin(pin)
    db = get_db()
    db.execute("UPDATE users SET pin=?, pin_failures=0, pin_locked_until=NULL WHERE id=?", (_hash_pin(pin), user_id))
    db.commit()


def check_kiosk_pin(user, entered_pin):
    """Return 'ok', 'wrong' or 'locked' and record the attempt."""
    db = get_db()
    entered_pin = str(entered_pin or '').strip()
    if not entered_pin.isdigit() or len(entered_pin) > PIN_MAX_LENGTH:
        entered_pin = ''
    fresh = db.execute("SELECT * FROM users WHERE id=?", (user['id'],)).fetchone()
    if fresh is not None:
        user = fresh
    if user['pin_locked_until'] and clock.parse_utc(user['pin_locked_until']) > clock.utc_now():
        return 'locked'
    if check_password_hash(user['pin'], entered_pin):
        db.execute("UPDATE users SET pin_failures=0, pin_locked_until=NULL WHERE id=?", (user['id'],))
        db.commit()
        return 'ok'
    failures = user['pin_failures'] + 1
    locked_until = None
    if failures >= PIN_MAX_FAILURES:
        locked_until = clock.to_utc_text(clock.utc_now() + timedelta(minutes=PIN_LOCKOUT_MINUTES))
        failures = 0
    db.execute("UPDATE users SET pin_failures=?, pin_locked_until=? WHERE id=?", (failures, locked_until, user['id']))
    db.commit()
    return 'locked' if locked_until else 'wrong'


# --- Login audit helpers ---

def parameterized_query_probe():
    """Run a harmless live binding check for the SQL-injection compliance indicator."""
    payload = "' OR 1=1 --"
    try:
        row = get_db().execute('SELECT ? AS value', (payload,)).fetchone()
        return bool(row and row['value'] == payload)
    except sqlite3.Error:
        return False


def log_login_attempt(email, ip_address, success, failure_reason=''):
    db = get_db()
    db.execute(
        "INSERT INTO login_audit (email, ip_address, success, failure_reason) VALUES (?, ?, ?, ?)",
        (email, ip_address, 1 if success else 0, failure_reason)
    )
    db.commit()


def get_recent_login_attempts(limit=20):
    db = get_db()
    return db.execute(
        "SELECT * FROM login_audit ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()


# --- Login lockout helpers ---

def check_lockout(email, ip_address, max_attempts=LOGIN_MAX_ATTEMPTS, lockout_minutes=LOGIN_LOCKOUT_MINUTES):
    db = get_db()
    row = db.execute(
        "SELECT * FROM login_lockout WHERE email=? AND ip_address=?",
        (email, ip_address)
    ).fetchone()
    if row and row['locked_until']:
        from datetime import datetime as dt
        try:
            locked_until = dt.fromisoformat(row['locked_until'])
            if dt.now() < locked_until:
                return True, int((locked_until - dt.now()).total_seconds() // 60) + 1
        except Exception:
            pass
    return False, 0


def record_failed_attempt(email, ip_address, max_attempts=LOGIN_MAX_ATTEMPTS, lockout_minutes=LOGIN_LOCKOUT_MINUTES):
    db = get_db()
    from datetime import datetime as dt, timedelta
    row = db.execute(
        "SELECT * FROM login_lockout WHERE email=? AND ip_address=?",
        (email, ip_address)
    ).fetchone()
    now = dt.now().isoformat()
    if row:
        new_count = row['failed_count'] + 1
        if new_count >= max_attempts:
            locked_until = (dt.now() + timedelta(minutes=lockout_minutes)).isoformat()
            db.execute(
                "UPDATE login_lockout SET failed_count=?, last_attempt=?, locked_until=? WHERE email=? AND ip_address=?",
                (new_count, now, locked_until, email, ip_address)
            )
        else:
            db.execute(
                "UPDATE login_lockout SET failed_count=?, last_attempt=? WHERE email=? AND ip_address=?",
                (new_count, now, email, ip_address)
            )
    else:
        db.execute(
            "INSERT INTO login_lockout (email, ip_address, failed_count, last_attempt) VALUES (?, ?, 1, ?)",
            (email, ip_address, now)
        )
    db.commit()


def clear_lockout(email, ip_address):
    db = get_db()
    db.execute(
        "DELETE FROM login_lockout WHERE email=? AND ip_address=?",
        (email, ip_address)
    )
    db.commit()


# --- TOTP 2FA helpers ---

def set_totp_secret(user_id, secret):
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO totp_secrets (user_id, secret, enabled, created_at) VALUES (?, ?, 0, datetime('now'))",
        (user_id, secret)
    )
    db.commit()


def enable_totp(user_id):
    db = get_db()
    db.execute("UPDATE totp_secrets SET enabled=1 WHERE user_id=?", (user_id,))
    db.commit()


def disable_totp(user_id):
    db = get_db()
    db.execute("DELETE FROM totp_secrets WHERE user_id=?", (user_id,))
    db.commit()


def get_totp_secret(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM totp_secrets WHERE user_id=? AND enabled=1", (user_id,)).fetchone()
    return row if row else None


def get_totp_secret_unchecked(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM totp_secrets WHERE user_id=?", (user_id,)).fetchone()
    return row if row else None


# --- Backup codes helpers ---

def add_backup_code(user_id, code_hash):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO backup_codes (user_id, code_hash) VALUES (?, ?)",
        (user_id, code_hash)
    )
    db.commit()
    return cursor.lastrowid


def verify_backup_code(user_id, code_hash):
    db = get_db()
    row = db.execute(
        "SELECT id FROM backup_codes WHERE user_id=? AND code_hash=? AND used=0",
        (user_id, code_hash)
    ).fetchone()
    if row:
        db.execute("UPDATE backup_codes SET used=1 WHERE id=?", (row['id'],))
        db.commit()
        return True
    return False


def clear_backup_codes(user_id):
    db = get_db()
    db.execute("DELETE FROM backup_codes WHERE user_id=?", (user_id,))
    db.commit()


def get_backup_code_count(user_id):
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM backup_codes WHERE user_id=? AND used=0",
        (user_id,)
    ).fetchone()
    return row['cnt'] if row else 0


# --- RFID tag helpers ---

def get_rfid_tag(tag_uid, active_only=True):
    db = get_db()
    normalized = normalize_tag(tag_uid)
    if not normalized:
        return None
    query = """SELECT rt.*, u.name as user_name, u.nickname as user_nickname,
               u.photo_path as user_photo, u.color as user_color
               FROM rfid_tags rt
               JOIN users u ON rt.user_id = u.id
               WHERE rt.tag_uid=?"""
    if active_only:
        query += " AND rt.is_active=1"
    return db.execute(query, (normalized,)).fetchone()


def get_rfid_tags(user_id=None, active_only=False):
    db = get_db()
    params = []
    query = """SELECT rt.*, u.name as user_name, u.nickname as user_nickname,
               u.photo_path as user_photo, u.color as user_color
               FROM rfid_tags rt
               JOIN users u ON rt.user_id = u.id
               WHERE 1=1"""
    if user_id:
        query += " AND rt.user_id=?"
        params.append(user_id)
    if active_only:
        query += " AND rt.is_active=1"
    query += " ORDER BY rt.created_at DESC, rt.id DESC"
    return db.execute(query, params).fetchall()


def assign_rfid_tag(tag_uid, user_id, label=''):
    normalized = normalize_tag(tag_uid)
    if not normalized:
        raise ValueError('RFID tag UID is required.')
    db = get_db()
    user = db.execute("SELECT id, role FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or user['role'] != 'child':
        raise ValueError('RFID tags can only be assigned to child accounts.')
    db.execute(
        """INSERT INTO rfid_tags (tag_uid, user_id, label, is_active)
           VALUES (?, ?, ?, 1)
           ON CONFLICT(tag_uid) DO UPDATE SET
               user_id=excluded.user_id,
               label=excluded.label,
               is_active=1,
               updated_at=datetime('now')""",
        (normalized, user_id, str(label or '').strip())
    )
    db.commit()
    row = db.execute("SELECT id FROM rfid_tags WHERE tag_uid=?", (normalized,)).fetchone()
    return row['id'] if row else None


def remove_rfid_tag(tag_uid):
    normalized = normalize_tag(tag_uid)
    if not normalized:
        return False
    db = get_db()
    cursor = db.execute("DELETE FROM rfid_tags WHERE tag_uid=?", (normalized,))
    db.commit()
    return cursor.rowcount > 0


# --- Gamification helpers ---

def _normalise_completion_date(value):
    try:
        return clock.local_date_text(value)
    except (TypeError, ValueError, AttributeError):
        return clock.local_date_text()


def _sync_gamification_unlocks(user_id, level, total_xp, longest_streak, current_streak):
    db = get_db()
    existing = {
        (row['item_type'], row['item_key'])
        for row in db.execute(
            "SELECT item_type, item_key FROM gamification_unlocks WHERE user_id=?",
            (user_id,)
        ).fetchall()
    }
    added = []
    for item_type, catalog in gamification.CATALOGS.items():
        for item in catalog:
            key = (item_type, item['key'])
            if key in existing:
                continue
            if gamification.item_unlocked(
                item, level=level, total_xp=total_xp,
                longest_streak=longest_streak, current_streak=current_streak
            ):
                db.execute(
                    """INSERT OR IGNORE INTO gamification_unlocks
                       (user_id, item_type, item_key) VALUES (?, ?, ?)""",
                    (user_id, item_type, item['key'])
                )
                added.append({
                    'item_type': item_type,
                    'item_key': item['key'],
                    'name': item['name'],
                    'icon': item['icon'],
                })
    if added:
        db.commit()
    return added


def _ensure_gamification(user_id):
    db = get_db()
    user = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        return None
    row = db.execute(
        "SELECT * FROM user_gamification WHERE user_id=?", (user_id,)
    ).fetchone()
    if row is None:
        db.execute(
            "INSERT OR IGNORE INTO user_gamification (user_id, updated_at) VALUES (?, datetime('now'))",
            (user_id,)
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM user_gamification WHERE user_id=?", (user_id,)
        ).fetchone()
    if row:
        _sync_gamification_unlocks(
            user_id, row['level'], row['total_xp'],
            row['longest_streak'], row['current_streak']
        )
        row = db.execute(
            "SELECT * FROM user_gamification WHERE user_id=?", (user_id,)
        ).fetchone()
    return row


def get_gamification(user_id):
    return _ensure_gamification(user_id)


def get_gamification_overview():
    db = get_db()
    return db.execute(
        """SELECT u.id as user_id, u.name, u.photo_path, u.color, u.nickname,
                  g.total_xp, g.level, g.current_streak, g.longest_streak,
                  g.last_completed_date, g.equipped_avatar, g.equipped_badge
           FROM users u
           LEFT JOIN user_gamification g ON g.user_id = u.id
           WHERE u.role='child' AND u.is_active=1
           ORDER BY COALESCE(g.total_xp, 0) DESC, u.name ASC"""
    ).fetchall()


def get_unlocked_items(user_id):
    if not _ensure_gamification(user_id):
        return []
    db = get_db()
    return db.execute(
        """SELECT * FROM gamification_unlocks
           WHERE user_id=? ORDER BY item_type, unlocked_at, id""",
        (user_id,)
    ).fetchall()


def get_xp_events(user_id=None, limit=50):
    db = get_db()
    params = []
    query = """SELECT e.*, u.name as user_name
               FROM xp_events e
               JOIN users u ON e.user_id = u.id
               WHERE 1=1"""
    if user_id:
        query += " AND e.user_id=?"
        params.append(user_id)
    query += " ORDER BY e.created_at DESC, e.id DESC LIMIT ?"
    params.append(limit)
    return db.execute(query, params).fetchall()


def record_xp(user_id, reward_amount, completed_date=None,
              source_type='chore', source_id=None):
    db = get_db()
    user = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        return None
    if source_id is not None:
        existing = db.execute(
            "SELECT * FROM xp_events WHERE source_type=? AND source_id=?",
            (source_type, source_id)
        ).fetchone()
        if existing:
            return {
                'awarded': False,
                'event': existing,
                'stats': _ensure_gamification(user_id),
                'unlocked': [],
            }

    stats = _ensure_gamification(user_id)
    date_text = _normalise_completion_date(completed_date)
    streak = gamification.next_completion_streak(
        stats['last_completed_date'], stats['current_streak'], date_text
    )
    calc = gamification.calculate_xp(reward_amount, streak)
    new_total = stats['total_xp'] + calc['xp_awarded']
    new_level = gamification.level_for_xp(new_total)
    new_longest = max(stats['longest_streak'], streak)
    try:
        reward = float(reward_amount or 0)
    except (TypeError, ValueError):
        reward = 0
    db.execute(
        """UPDATE user_gamification
           SET total_xp=?, level=?, current_streak=?, longest_streak=?,
               last_completed_date=?, updated_at=datetime('now')
           WHERE user_id=?""",
        (new_total, new_level, streak, new_longest, date_text, user_id)
    )
    cursor = db.execute(
        """INSERT INTO xp_events
           (user_id, source_type, source_id, reward_amount, base_xp,
            streak_days, multiplier, xp_awarded, completed_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, source_type, source_id, reward, calc['base_xp'],
         calc['streak_days'], calc['multiplier'], calc['xp_awarded'], date_text)
    )
    db.commit()
    unlocked = _sync_gamification_unlocks(
        user_id, new_level, new_total, new_longest, streak
    )
    event = db.execute(
        "SELECT * FROM xp_events WHERE id=?", (cursor.lastrowid,)
    ).fetchone()
    achievement_unlocks = evaluate_achievements(user_id)
    stats = db.execute(
        "SELECT * FROM user_gamification WHERE user_id=?", (user_id,)
    ).fetchone()
    return {
        'awarded': True, 'event': event, 'stats': stats,
        'unlocked': unlocked, 'achievements': achievement_unlocks,
    }


def award_chore_xp(log):
    if not log:
        return None
    return record_xp(
        log['user_id'], log['earned_amount'],
        completed_date=log['finished_at'],
        source_type='chore', source_id=log['id']
    )


def award_drop_xp(user_id, drop):
    if not drop:
        return None
    return record_xp(
        user_id, drop['current_points'],
        source_type='drop', source_id=drop['id']
    )


def equip_gamification_item(user_id, item_type, item_key):
    db = get_db()
    if item_type not in gamification.CATALOGS:
        raise ValueError('Unknown reward type.')
    user = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or user['role'] != 'child':
        raise ValueError('Rewards can only be equipped by child accounts.')
    stats = _ensure_gamification(user_id)
    if not stats:
        raise ValueError('Child not found.')
    if item_type == 'badge' and item_key in ('', 'none'):
        db.execute(
            "UPDATE user_gamification SET equipped_badge='', updated_at=datetime('now') WHERE user_id=?",
            (user_id,)
        )
        db.commit()
        return _ensure_gamification(user_id)
    item = gamification.get_item(item_type, item_key)
    if not item:
        raise ValueError('Unknown reward.')
    unlocked = db.execute(
        """SELECT 1 FROM gamification_unlocks
           WHERE user_id=? AND item_type=? AND item_key=?""",
        (user_id, item_type, item_key)
    ).fetchone()
    if not unlocked:
        raise ValueError('That reward is still locked.')
    column = 'equipped_avatar' if item_type == 'avatar' else 'equipped_badge'
    db.execute(
        f"UPDATE user_gamification SET {column}=?, updated_at=datetime('now') WHERE user_id=?",
        (item_key, user_id)
    )
    db.commit()
    return _ensure_gamification(user_id)


# --- Chore helpers ---

def create_chore(name, icon, pay_amount, description='', is_active=1,
               chore_emoji='', chore_image='', repeat_frequency='daily', due_days='0,1,2,3,4,5,6',
               single_child_only=0, requires_hard_chores=0):
    db = get_db()
    cursor = db.execute(
        """INSERT INTO chores (name, icon, pay_amount, description, is_active, chore_emoji, chore_image, repeat_frequency, due_days, single_child_only, requires_hard_chores)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, icon, pay_amount, description, is_active, chore_emoji, chore_image, repeat_frequency, due_days, single_child_only, requires_hard_chores)
    )
    db.commit()
    return cursor.lastrowid


def get_all_chores(active_only=False):
    db = get_db()
    if active_only:
        return db.execute("SELECT * FROM chores WHERE is_active=1 ORDER BY name").fetchall()
    return db.execute("SELECT * FROM chores ORDER BY is_active DESC, name").fetchall()


def get_chore(chore_id):
    db = get_db()
    return db.execute("SELECT * FROM chores WHERE id=?", (chore_id,)).fetchone()


def update_chore(chore_id, **fields):
    db = get_db()
    allowed = {'name', 'icon', 'pay_amount', 'description', 'is_active', 'chore_emoji', 'chore_image', 'repeat_frequency', 'due_days', 'single_child_only', 'requires_hard_chores'}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(chore_id)
    db.execute(f"UPDATE chores SET {', '.join(sets)} WHERE id=?", vals)
    db.commit()


def delete_chore(chore_id):
    db = get_db()
    db.execute("DELETE FROM chores WHERE id=?", (chore_id,))
    db.commit()


def assign_chore(chore_id, user_id, day_of_week=None):
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO chore_assignments (chore_id, user_id, day_of_week) VALUES (?, ?, ?)",
        (chore_id, user_id, day_of_week)
    )
    db.commit()


def unassign_chore(chore_id, user_id):
    db = get_db()
    db.execute("DELETE FROM chore_assignments WHERE chore_id=? AND user_id=?", (chore_id, user_id))
    db.commit()


def get_assignments_for_chore(chore_id):
    db = get_db()
    return db.execute(
        "SELECT user_id FROM chore_assignments WHERE chore_id=?", (chore_id,)
    ).fetchall()


def get_assigned_chore_ids(user_id):
    db = get_db()
    rows = db.execute(
        "SELECT chore_id FROM chore_assignments WHERE user_id=?", (user_id,)
    ).fetchall()
    return [r['chore_id'] for r in rows]


# --- Chore log helpers ---

def _completion_is_current(repeat_frequency, completed_at):
    try:
        moment = clock.parse_utc(completed_at)
    except (TypeError, ValueError):
        return False
    now = clock.utc_now()
    if repeat_frequency == 'once':
        return True
    if repeat_frequency == 'monthly':
        return (moment.year, moment.month) == (now.year, now.month)
    if repeat_frequency == 'weekly':
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return moment >= week_start
    return clock.local_date(moment) == clock.local_date(now)


def get_completed_chore_ids(user_id=None):
    db = get_db()
    params = []
    query = """SELECT cl.chore_id, c.repeat_frequency,
               MAX(cl.finished_at) AS completed_at
               FROM chore_logs cl
               JOIN chores c ON cl.chore_id = c.id
               WHERE cl.status='completed'"""
    if user_id is not None:
        query += " AND cl.user_id=?"
        params.append(user_id)
    query += " GROUP BY cl.chore_id, c.repeat_frequency"
    return {
        row['chore_id'] for row in db.execute(query, params).fetchall()
        if _completion_is_current(row['repeat_frequency'], row['completed_at'])
    }


def is_chore_completed_by_child(user_id, chore_id):
    return chore_id in get_completed_chore_ids(user_id)


def is_chore_completed(chore_id):
    return chore_id in get_completed_chore_ids()


def get_chore_assignee_ids(chore_id):
    db = get_db()
    assigned = [row['user_id'] for row in get_assignments_for_chore(chore_id)]
    if assigned:
        return assigned
    return [row['id'] for row in db.execute(
        "SELECT id FROM users WHERE role='child' AND is_active=1 ORDER BY id"
    ).fetchall()]


def is_chore_fully_completed(chore_id):
    chore = get_chore(chore_id)
    if not chore:
        return False
    if chore['single_child_only']:
        return is_chore_completed(chore_id)
    assignees = set(get_chore_assignee_ids(chore_id))
    if not assignees:
        return False
    db = get_db()
    rows = db.execute(
        """SELECT cl.user_id, c.repeat_frequency,
           MAX(cl.finished_at) AS completed_at
           FROM chore_logs cl
           JOIN chores c ON cl.chore_id = c.id
           WHERE cl.chore_id=? AND cl.status='completed'
           GROUP BY cl.user_id, c.repeat_frequency""",
        (chore_id,)
    ).fetchall()
    completed = {
        row['user_id'] for row in rows
        if _completion_is_current(row['repeat_frequency'], row['completed_at'])
    }
    return assignees.issubset(completed)


def get_chores_for_child(user_id, can_do_hard_chores=False):
    assigned_ids = get_assigned_chore_ids(user_id)
    if assigned_ids:
        chores = [c for c in get_all_chores(active_only=True) if c['id'] in assigned_ids]
    else:
        chores = get_all_chores(active_only=True)
    completed_for_child = get_completed_chore_ids(user_id)
    completed_by_anyone = get_completed_chore_ids()
    visible = []
    for chore in chores:
        if chore['id'] in completed_for_child:
            continue
        if chore['single_child_only'] and chore['id'] in completed_by_anyone:
            continue
        if not can_do_hard_chores and chore['requires_hard_chores']:
            continue
        visible.append(chore)
    return visible


def complete_chore(user_id, chore_id):
    db = get_db()
    chore = db.execute("SELECT * FROM chores WHERE id=? AND is_active=1", (chore_id,)).fetchone()
    if not chore:
        raise ValueError('Chore not available.')
    assigned_ids = get_assigned_chore_ids(user_id)
    if assigned_ids and chore_id not in assigned_ids:
        raise ValueError('This chore is not assigned to you.')
    if chore['requires_hard_chores']:
        user = get_user(user_id)
        if not user or not user['can_do_hard_chores']:
            raise ValueError('This chore is for older kids only.')
    if is_chore_completed_by_child(user_id, chore_id):
        raise ValueError('You have already completed this chore.')
    if chore['single_child_only'] and is_chore_completed(chore_id):
        raise ValueError('This shared chore has already been completed.')
    cursor = db.execute(
        """INSERT INTO chore_logs
           (user_id, chore_id, status, finished_at, earned_amount)
           VALUES (?, ?, 'completed', datetime('now'), ?)""",
        (user_id, chore_id, chore['pay_amount'])
    )
    db.execute(
        """UPDATE drop_chores
           SET status='completed', claimed_by=COALESCE(claimed_by, ?)
           WHERE chore_id=? AND assigned_to=? AND status='assigned'""",
        (user_id, chore_id, user_id)
    )
    db.commit()
    return db.execute("SELECT * FROM chore_logs WHERE id=?", (cursor.lastrowid,)).fetchone()


def start_chore(user_id, chore_id):
    return complete_chore(user_id, chore_id)['id']


def finish_chore(log_id):
    db = get_db()
    log = db.execute("SELECT * FROM chore_logs WHERE id=?", (log_id,)).fetchone()
    if not log:
        return None
    if log['status'] == 'completed':
        return log
    if log['status'] != 'in_progress':
        return None
    db.execute(
        "UPDATE chore_logs SET status='completed', finished_at=datetime('now') WHERE id=?",
        (log_id,)
    )
    db.commit()
    return db.execute("SELECT * FROM chore_logs WHERE id=?", (log_id,)).fetchone()


def cancel_chore_log(log_id):
    db = get_db()
    db.execute("DELETE FROM chore_logs WHERE id=? AND status='in_progress'", (log_id,))
    db.commit()


def get_active_logs(user_id=None):
    db = get_db()
    if user_id:
        return db.execute(
            """SELECT cl.*, c.name as chore_name, c.icon as chore_icon, c.pay_amount,
               u.name as user_name, u.photo_path as user_photo
               FROM chore_logs cl
               JOIN chores c ON cl.chore_id = c.id
               JOIN users u ON cl.user_id = u.id
               WHERE cl.status='in_progress' AND cl.user_id=?
               ORDER BY cl.id DESC""",
            (user_id,)
        ).fetchall()
    return db.execute(
        """SELECT cl.*, c.name as chore_name, c.icon as chore_icon, c.pay_amount,
           u.name as user_name, u.photo_path as user_photo
           FROM chore_logs cl
           JOIN chores c ON cl.chore_id = c.id
           JOIN users u ON cl.user_id = u.id
           WHERE cl.status='in_progress'
           ORDER BY cl.id DESC"""
    ).fetchall()


def get_completed_logs(user_id=None, month=None, limit=200):
    db = get_db()
    params = []
    query = """SELECT cl.*, c.name as chore_name, c.icon as chore_icon,
               u.name as user_name, u.photo_path as user_photo, u.color as user_color
               FROM chore_logs cl
               JOIN chores c ON cl.chore_id = c.id
               JOIN users u ON cl.user_id = u.id
               WHERE cl.status='completed'"""
    if user_id:
        query += " AND cl.user_id=?"
        params.append(user_id)
    if month:
        query += " AND strftime('%Y-%m', cl.finished_at)=?"
        params.append(month)
    query += " ORDER BY cl.finished_at DESC LIMIT ?"
    params.append(limit)
    return db.execute(query, params).fetchall()


def get_monthly_earnings(user_id=None, month=None):
    db = get_db()
    if month is None:
        month = datetime.now().strftime('%Y-%m')
    params = [month]
    query = """SELECT u.id, u.name, u.photo_path, u.color,
               COUNT(cl.id) as chore_count,
               COALESCE(SUM(cl.earned_amount), 0) as total_earned
               FROM users u
               LEFT JOIN chore_logs cl ON u.id = cl.user_id AND cl.status='completed'
                    AND strftime('%Y-%m', cl.finished_at)=?
               WHERE u.role='child' AND u.is_active=1"""
    if user_id:
        query += " AND u.id=?"
        params.append(user_id)
    query += " GROUP BY u.id ORDER BY total_earned DESC"
    return db.execute(query, params).fetchall()


def get_total_earned(month=None):
    db = get_db()
    if month is None:
        month = datetime.now().strftime('%Y-%m')
    row = db.execute(
        "SELECT COALESCE(SUM(earned_amount), 0) as total FROM chore_logs WHERE status='completed' AND strftime('%Y-%m', finished_at)=?",
        (month,)
    ).fetchone()
    return row['total'] if row else 0


def get_chore_count(month=None):
    db = get_db()
    if month is None:
        month = datetime.now().strftime('%Y-%m')
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM chore_logs WHERE status='completed' AND strftime('%Y-%m', finished_at)=?",
        (month,)
    ).fetchone()
    return row['cnt'] if row else 0


# --- Payment helpers ---

def create_payment(user_id, amount, ptype='payout', description='', log_id=None, created_by=None,
                    payout_method='', token_amount=0, gbp_amount=0, auto_repay=True, commit=True):
    db = get_db()
    cursor = db.execute(
        """INSERT INTO payments (user_id, amount, type, description, log_id, created_by, payout_method, token_amount, gbp_amount)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, amount, ptype, description, log_id, created_by, payout_method, token_amount, gbp_amount)
    )
    if not commit:
        return cursor.lastrowid
    db.commit()
    payment_id = cursor.lastrowid
    if auto_repay and ptype == 'earning' and amount > 0:
        repayment = apply_loan_repayment(user_id, amount, source='earning')
        remaining = round(float(amount) - float(repayment.get('total', 0) or 0), 2)
        if remaining > 0:
            apply_bill_deductions(user_id, remaining, source='earning')
        evaluate_achievements(user_id)
    return payment_id


def get_payments(user_id=None, month=None):
    db = get_db()
    params = []
    query = """SELECT p.*, u.name as user_name,
               pu.name as payer_name
               FROM payments p
               JOIN users u ON p.user_id=u.id
               LEFT JOIN users pu ON p.created_by=pu.id
               WHERE 1=1"""
    if user_id:
        query += " AND p.user_id=?"
        params.append(user_id)
    if month:
        query += " AND strftime('%Y-%m', p.created_at)=?"
        params.append(month)
    query += " ORDER BY p.created_at DESC"
    return db.execute(query, params).fetchall()


def get_balance(user_id):
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(amount), 0) as balance FROM payments WHERE user_id=?",
        (user_id,)
    ).fetchone()
    return row['balance'] if row else 0


def get_cash_balance(user_id):
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(amount), 0) as balance FROM cash_ledger WHERE user_id=?",
        (user_id,)
    ).fetchone()
    return round(float(row['balance'] if row else 0), 2)


def create_cash_entry(user_id, amount, description='', created_by=None,
                      reference_type='', reference_id=None, commit=True):
    _validate_child_user(user_id)
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError('Cash amount must be a number.') from exc
    if amount == 0:
        raise ValueError('Cash amount cannot be zero.')
    if amount < 0 and get_cash_balance(user_id) + amount < -0.005:
        raise ValueError('Not enough cash balance for that purchase.')
    db = get_db()
    cursor = db.execute(
        """INSERT INTO cash_ledger
           (user_id, amount, description, reference_type, reference_id, created_by)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, amount, (description or '').strip()[:500],
         (reference_type or '').strip()[:60], reference_id, created_by)
    )
    if commit:
        db.commit()
    return cursor.lastrowid


def adjust_cash_balance(user_id, amount, description='', created_by=None):
    return create_cash_entry(
        user_id, amount, description=description, created_by=created_by,
        reference_type='manual_adjustment'
    )


def delete_payment(payment_id):
    db = get_db()
    db.execute("DELETE FROM payments WHERE id=?", (payment_id,))
    db.commit()


# --- Banking helpers ---

def _validate_child_user(user_id):
    db = get_db()
    user = db.execute(
        "SELECT id, role, is_active FROM users WHERE id=?",
        (user_id,)
    ).fetchone()
    if not user or user['role'] != 'child' or not user['is_active']:
        raise ValueError('Savings and loans are only available to active child accounts.')
    return user


def _savings_account_row(user_id):
    return get_db().execute(
        "SELECT * FROM savings_accounts WHERE user_id=?",
        (user_id,)
    ).fetchone()


def _ensure_savings_account(user_id):
    _validate_child_user(user_id)
    row = _savings_account_row(user_id)
    if row:
        return row
    db = get_db()
    now = clock.to_utc_text(clock.utc_now())
    db.execute(
        """INSERT OR IGNORE INTO savings_accounts (user_id, last_interest_at, updated_at)
           VALUES (?, ?, ?)""",
        (user_id, now, now)
    )
    db.commit()
    return _savings_account_row(user_id)


def get_savings_account(user_id):
    _ensure_savings_account(user_id)
    return get_db().execute(
        """SELECT sa.*, u.name as user_name, u.photo_path
           FROM savings_accounts sa
           JOIN users u ON sa.user_id=u.id
           WHERE sa.user_id=?""",
        (user_id,)
    ).fetchone()


def get_savings_accounts():
    db = get_db()
    children = db.execute(
        "SELECT id FROM users WHERE role='child' AND is_active=1 ORDER BY name"
    ).fetchall()
    return [get_savings_account(child['id']) for child in children]


def update_savings_settings(user_id, annual_rate, compounding):
    _ensure_savings_account(user_id)
    try:
        rate = float(annual_rate)
    except (TypeError, ValueError) as exc:
        raise ValueError('Interest rate must be a number.') from exc
    if rate < 0 or rate > 100:
        raise ValueError('Interest rate must be between 0 and 100.')
    if compounding not in banking.PERIODS_PER_YEAR:
        raise ValueError('Compounding must be daily or weekly.')
    db = get_db()
    db.execute(
        """UPDATE savings_accounts
           SET annual_interest_rate=?, compounding=?, updated_at=datetime('now')
           WHERE user_id=?""",
        (rate, compounding, user_id)
    )
    db.commit()
    return get_savings_account(user_id)


def apply_savings_interest(now=None):
    db = get_db()
    if now is None:
        now = clock.utc_now()
    elif now.tzinfo is None:
        now = clock.parse_utc(now.isoformat())
    results = []
    accounts = db.execute(
        "SELECT * FROM savings_accounts WHERE is_active=1"
    ).fetchall()
    for account in accounts:
        last_at = clock.parse_utc(account['last_interest_at'] or account['created_at'])
        periods = banking.elapsed_periods(last_at, now, account['compounding'])
        if periods <= 0:
            continue
        opening = round(float(account['balance'] or 0), 2)
        new_balance = banking.compound_balance(
            opening, account['annual_interest_rate'], periods, account['compounding']
        )
        interest = round(new_balance - opening, 2)
        next_at = banking.next_interest_at(last_at, periods, account['compounding'])
        db.execute(
            """UPDATE savings_accounts
               SET balance=?, last_interest_at=?, updated_at=datetime('now')
               WHERE user_id=?""",
            (new_balance, clock.to_utc_text(next_at), account['user_id'])
        )
        if interest > 0:
            db.execute(
                """INSERT INTO bank_transactions
                   (user_id, type, amount, balance_after, description)
                   VALUES (?, 'interest', ?, ?, ?)""",
                (account['user_id'], interest, new_balance,
                 f'{periods} {account["compounding"]} interest period(s)')
            )
        results.append({
            'user_id': account['user_id'],
            'periods': periods,
            'interest': interest,
            'balance': new_balance,
            'next_interest_at': clock.to_utc_text(next_at),
        })
    db.commit()
    return results


def deposit_to_savings(user_id, amount):
    _validate_child_user(user_id)
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError('Deposit must be a number.') from exc
    if amount <= 0:
        raise ValueError('Deposit must be greater than zero.')
    apply_savings_interest()
    account = _ensure_savings_account(user_id)
    available = round(float(get_balance(user_id)), 2)
    if amount > available + 0.005:
        raise ValueError(f'Not enough spendable balance. Available: {available:.2f}.')
    new_balance = round(float(account['balance'] or 0) + amount, 2)
    db = get_db()
    db.execute(
        "UPDATE savings_accounts SET balance=?, updated_at=datetime('now') WHERE user_id=?",
        (new_balance, user_id)
    )
    create_payment(
        user_id, -amount, ptype='savings_deposit',
        description='Moved to savings', auto_repay=False
    )
    db.execute(
        """INSERT INTO bank_transactions
           (user_id, type, amount, balance_after, description)
           VALUES (?, 'deposit', ?, ?, ?)""",
        (user_id, amount, new_balance, 'Deposit from spendable balance')
    )
    db.commit()
    evaluate_achievements(user_id)
    return get_savings_account(user_id)


def withdraw_from_savings(user_id, amount):
    _validate_child_user(user_id)
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError('Withdrawal must be a number.') from exc
    if amount <= 0:
        raise ValueError('Withdrawal must be greater than zero.')
    apply_savings_interest()
    account = _ensure_savings_account(user_id)
    balance = round(float(account['balance'] or 0), 2)
    if amount > balance + 0.005:
        raise ValueError(f'Not enough savings balance. Available: {balance:.2f}.')
    new_balance = round(balance - amount, 2)
    db = get_db()
    db.execute(
        "UPDATE savings_accounts SET balance=?, updated_at=datetime('now') WHERE user_id=?",
        (new_balance, user_id)
    )
    create_payment(
        user_id, amount, ptype='savings_withdrawal',
        description='Moved from savings', auto_repay=False
    )
    db.execute(
        """INSERT INTO bank_transactions
           (user_id, type, amount, balance_after, description)
           VALUES (?, 'withdrawal', ?, ?, ?)""",
        (user_id, amount, new_balance, 'Withdrawal to spendable balance')
    )
    db.commit()
    return get_savings_account(user_id)


def _truthy(value):
    return str(value).strip().lower() in {'1', 'true', 'on', 'yes'}


def _positive_amount(value, label):
    try:
        amount = round(float(value), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be a number.') from exc
    if amount <= 0:
        raise ValueError(f'{label} must be greater than zero.')
    return amount


def _parse_vault_target_date(value):
    text = (value or '').strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ValueError('Target date must be a valid date.') from exc


def _clean_vault_icon(value):
    icon = (value or '').strip()
    return icon if icon.startswith('bi-') and len(icon) <= 60 else 'bi-bullseye'


def _clean_vault_color(value):
    return achievements.clean_color(value)


def _vault_row(vault_id):
    return get_db().execute(
        """SELECT sv.*, u.name as user_name, u.photo_path, u.color as user_color
           FROM savings_vaults sv
           JOIN users u ON sv.user_id=u.id
           WHERE sv.id=?""",
        (vault_id,)
    ).fetchone()


def _vault_progress(vault):
    if not vault:
        return {}
    return banking.vault_progress(
        vault['balance'], vault['target_amount'], vault['target_date'],
        bool(vault['lock_until_date']), bool(vault['lock_until_target']),
        vault['status']
    )


def _mark_vault_completed_if_reached(vault_id, db=None):
    db = db or get_db()
    row = db.execute(
        "SELECT balance, target_amount, completed_at, status FROM savings_vaults WHERE id=?",
        (vault_id,)
    ).fetchone()
    if (row and row['status'] != 'closed' and row['completed_at'] is None
            and round(float(row['balance'] or 0), 2) + 0.005 >= round(float(row['target_amount'] or 0), 2)):
        db.execute(
            "UPDATE savings_vaults SET completed_at=datetime('now'), updated_at=datetime('now') WHERE id=?",
            (vault_id,)
        )


def get_savings_vault(vault_id):
    return _vault_row(vault_id)


def get_savings_vaults(user_id=None, include_closed=False):
    db = get_db()
    params = []
    query = """SELECT sv.*, u.name as user_name, u.photo_path, u.color as user_color
               FROM savings_vaults sv
               JOIN users u ON sv.user_id=u.id
               WHERE 1=1"""
    if user_id is not None:
        query += " AND sv.user_id=?"
        params.append(int(user_id))
    if not include_closed:
        query += " AND sv.status != 'closed'"
    query += " ORDER BY CASE WHEN sv.status='active' THEN 0 ELSE 1 END, sv.created_at DESC, sv.id DESC"
    return db.execute(query, params).fetchall()


def get_savings_vaults_with_progress(user_id=None, include_closed=False, include_match_rules=False):
    vaults = []
    for row in get_savings_vaults(user_id, include_closed=include_closed):
        vault = dict(row)
        vault['progress'] = _vault_progress(row)
        if include_match_rules:
            vault['match_rule'] = get_effective_savings_match_rule(row['user_id'], row['id'])
        vaults.append(vault)
    return vaults


def get_savings_vault_total(user_id=None):
    db = get_db()
    params = []
    query = "SELECT COALESCE(SUM(balance), 0) AS total FROM savings_vaults WHERE status='active'"
    if user_id is not None:
        query += " AND user_id=?"
        params.append(int(user_id))
    return round(float(db.execute(query, params).fetchone()['total'] or 0), 2)


def create_savings_vault(user_id, name, target_amount, target_date=None,
                         lock_until_date=False, lock_until_target=False,
                         description='', icon='bi-bullseye', color='#10b981'):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError('Choose a child for this savings goal.') from exc
    _validate_child_user(user_id)
    name = (name or '').strip()
    if not name:
        raise ValueError('Goal name is required.')
    if len(name) > 100:
        raise ValueError('Goal name must be 100 characters or fewer.')
    target = _positive_amount(target_amount, 'Target amount')
    target_date = _parse_vault_target_date(target_date)
    lock_until_date = _truthy(lock_until_date)
    lock_until_target = _truthy(lock_until_target)
    if lock_until_date and not target_date:
        raise ValueError('Choose a target date when locking until a date.')

    db = get_db()
    cursor = db.execute(
        """INSERT INTO savings_vaults
           (user_id, name, description, target_amount, target_date,
            lock_until_date, lock_until_target, icon, color, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (user_id, name, (description or '').strip()[:500], target, target_date,
         1 if lock_until_date else 0, 1 if lock_until_target else 0,
         _clean_vault_icon(icon), _clean_vault_color(color))
    )
    db.commit()
    return _vault_row(cursor.lastrowid)


def update_savings_vault(vault_id, name, target_amount, target_date=None,
                         lock_until_date=False, lock_until_target=False,
                         description='', icon='bi-bullseye', color='#10b981'):
    vault = _vault_row(vault_id)
    if not vault:
        raise ValueError('Savings goal not found.')
    if vault['status'] == 'closed':
        raise ValueError('Closed savings goals cannot be edited.')
    name = (name or '').strip()
    if not name:
        raise ValueError('Goal name is required.')
    if len(name) > 100:
        raise ValueError('Goal name must be 100 characters or fewer.')
    target = _positive_amount(target_amount, 'Target amount')
    target_date = _parse_vault_target_date(target_date)
    lock_until_date = _truthy(lock_until_date)
    lock_until_target = _truthy(lock_until_target)
    if lock_until_date and not target_date:
        raise ValueError('Choose a target date when locking until a date.')
    db = get_db()
    db.execute(
        """UPDATE savings_vaults
           SET name=?, description=?, target_amount=?, target_date=?,
               lock_until_date=?, lock_until_target=?, icon=?, color=?,
               updated_at=datetime('now')
           WHERE id=?""",
        (name, (description or '').strip()[:500], target, target_date,
         1 if lock_until_date else 0, 1 if lock_until_target else 0,
         _clean_vault_icon(icon), _clean_vault_color(color), vault_id)
    )
    _mark_vault_completed_if_reached(vault_id, db)
    db.commit()
    return _vault_row(vault_id)


def unlock_savings_vault(vault_id):
    vault = _vault_row(vault_id)
    if not vault:
        raise ValueError('Savings goal not found.')
    if vault['status'] == 'closed':
        raise ValueError('This savings goal is already closed.')
    db = get_db()
    db.execute(
        """UPDATE savings_vaults
           SET lock_until_date=0, lock_until_target=0, updated_at=datetime('now')
           WHERE id=?""",
        (vault_id,)
    )
    db.commit()
    return _vault_row(vault_id)


def close_savings_vault(vault_id):
    vault = _vault_row(vault_id)
    if not vault:
        raise ValueError('Savings goal not found.')
    if vault['status'] == 'closed':
        raise ValueError('This savings goal is already closed.')
    db = get_db()
    balance = round(float(vault['balance'] or 0), 2)
    try:
        if balance > 0:
            payment_id = create_payment(
                vault['user_id'], balance, ptype='vault_close_refund',
                description=f'Closed goal: {vault["name"]}',
                auto_repay=False, commit=False
            )
            db.execute(
                """INSERT INTO savings_vault_transactions
                   (vault_id, user_id, payment_id, type, amount, balance_after, description)
                   VALUES (?, ?, ?, 'close_refund', ?, 0, ?)""",
                (vault_id, vault['user_id'], payment_id, -balance,
                 'Goal closed; balance returned to spendable')
            )
        db.execute(
            """UPDATE savings_vaults
               SET balance=0, status='closed', updated_at=datetime('now')
               WHERE id=?""",
            (vault_id,)
        )
        db.execute(
            """UPDATE savings_match_rules
               SET is_active=0, updated_at=datetime('now')
               WHERE vault_id=?""",
            (vault_id,)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _vault_row(vault_id)


def get_savings_match_rule(rule_id):
    return get_db().execute(
        """SELECT r.*, u.name as user_name, sv.name as vault_name
           FROM savings_match_rules r
           JOIN users u ON r.user_id=u.id
           LEFT JOIN savings_vaults sv ON r.vault_id=sv.id
           WHERE r.id=?""",
        (rule_id,)
    ).fetchone()


def get_savings_match_rules(user_id=None):
    db = get_db()
    params = []
    query = """SELECT r.*, u.name as user_name, sv.name as vault_name
               FROM savings_match_rules r
               JOIN users u ON r.user_id=u.id
               LEFT JOIN savings_vaults sv ON r.vault_id=sv.id
               WHERE 1=1"""
    if user_id is not None:
        query += " AND r.user_id=?"
        params.append(int(user_id))
    query += " ORDER BY r.is_active DESC, u.name, r.id"
    return db.execute(query, params).fetchall()


def get_effective_savings_match_rule(user_id, vault_id):
    return get_db().execute(
        """SELECT * FROM savings_match_rules
           WHERE user_id=? AND is_active=1 AND (vault_id=? OR vault_id IS NULL)
           ORDER BY CASE WHEN vault_id IS NULL THEN 1 ELSE 0 END
           LIMIT 1""",
        (int(user_id), int(vault_id))
    ).fetchone()


def set_savings_match_rule(user_id, vault_id, match_percent, weekly_cap, is_active=True):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError('Choose a child for this matching rule.') from exc
    _validate_child_user(user_id)
    vault_id = int(vault_id) if vault_id not in (None, '', '0', 0) else None
    if vault_id is not None:
        vault = _vault_row(vault_id)
        if not vault or vault['user_id'] != user_id:
            raise ValueError('Savings goal not found for that child.')
        if vault['status'] == 'closed':
            raise ValueError('Cannot add a matching rule to a closed goal.')
    try:
        percent = round(float(match_percent), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError('Match percentage must be a number.') from exc
    if percent < 0 or percent > 100:
        raise ValueError('Match percentage must be between 0 and 100.')
    try:
        cap = round(float(weekly_cap), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError('Weekly cap must be a number.') from exc
    if cap < 0:
        raise ValueError('Weekly cap cannot be negative.')
    is_active = _truthy(is_active)
    db = get_db()
    db.execute(
        "DELETE FROM savings_match_rules WHERE user_id=? AND vault_id IS ?",
        (user_id, vault_id)
    )
    cursor = db.execute(
        """INSERT INTO savings_match_rules
           (user_id, vault_id, match_percent, weekly_cap, is_active, updated_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))""",
        (user_id, vault_id, percent, cap, 1 if is_active else 0)
    )
    db.commit()
    return get_savings_match_rule(cursor.lastrowid)


def delete_savings_match_rule(rule_id):
    rule = get_savings_match_rule(rule_id)
    if not rule:
        raise ValueError('Matching rule not found.')
    db = get_db()
    db.execute("DELETE FROM savings_match_rules WHERE id=?", (rule_id,))
    db.commit()
    return rule


def _savings_week_start_text(now=None):
    return banking.week_start(now).strftime('%Y-%m-%d %H:%M:%S')


def _apply_savings_vault_match(user_id, vault_id, contribution_amount, now=None, db=None):
    db = db or get_db()
    rule = get_effective_savings_match_rule(user_id, vault_id)
    if not rule or not rule['is_active'] or float(rule['match_percent'] or 0) <= 0 or float(rule['weekly_cap'] or 0) <= 0:
        return 0.0
    week_start = _savings_week_start_text(now)
    if rule['vault_id']:
        matched_this_week = db.execute(
            """SELECT COALESCE(SUM(amount), 0) AS total
               FROM savings_vault_transactions
               WHERE vault_id=? AND type='match' AND created_at >= ?""",
            (vault_id, week_start)
        ).fetchone()['total']
    else:
        matched_this_week = db.execute(
            """SELECT COALESCE(SUM(amount), 0) AS total
               FROM savings_vault_transactions
               WHERE user_id=? AND type='match' AND created_at >= ?""",
            (int(user_id), week_start)
        ).fetchone()['total']
    match = banking.match_amount(
        contribution_amount, rule['match_percent'], rule['weekly_cap'], matched_this_week
    )
    if match <= 0:
        return 0.0
    vault = _vault_row(vault_id)
    if not vault or vault['status'] != 'active':
        return 0.0
    new_balance = round(float(vault['balance'] or 0) + match, 2)
    db.execute(
        "UPDATE savings_vaults SET balance=?, updated_at=datetime('now') WHERE id=?",
        (new_balance, vault_id)
    )
    db.execute(
        """INSERT INTO savings_vault_transactions
           (vault_id, user_id, type, amount, balance_after, description)
           VALUES (?, ?, 'match', ?, ?, ?)""",
        (vault_id, int(user_id), match, new_balance,
         f'{float(rule["match_percent"]):g}% parent match (weekly cap {float(rule["weekly_cap"]):g})')
    )
    _mark_vault_completed_if_reached(vault_id, db)
    return match


def deposit_to_savings_vault(vault_id, user_id, amount, now=None):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError('Savings goal not found.') from exc
    vault = _vault_row(vault_id)
    if not vault or vault['user_id'] != user_id:
        raise ValueError('Savings goal not found.')
    if vault['status'] != 'active':
        raise ValueError('This savings goal is closed.')
    amount = _positive_amount(amount, 'Deposit')
    available = round(float(get_balance(user_id)), 2)
    if amount > available + 0.005:
        raise ValueError(f'Not enough spendable balance. Available: {available:.2f}.')

    db = get_db()
    try:
        payment_id = create_payment(
            user_id, -amount, ptype='vault_deposit',
            description=f'Vault: {vault["name"]}', auto_repay=False, commit=False
        )
        new_balance = round(float(vault['balance'] or 0) + amount, 2)
        db.execute(
            "UPDATE savings_vaults SET balance=?, updated_at=datetime('now') WHERE id=?",
            (new_balance, vault_id)
        )
        db.execute(
            """INSERT INTO savings_vault_transactions
               (vault_id, user_id, payment_id, type, amount, balance_after, description)
               VALUES (?, ?, ?, 'deposit', ?, ?, ?)""",
            (vault_id, user_id, payment_id, amount, new_balance, 'Added to goal')
        )
        _mark_vault_completed_if_reached(vault_id, db)
        matched = _apply_savings_vault_match(user_id, vault_id, amount, now=now, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    evaluate_achievements(user_id)
    return {'vault': _vault_row(vault_id), 'matched': matched}


def withdraw_from_savings_vault(vault_id, user_id, amount):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError('Savings goal not found.') from exc
    vault = _vault_row(vault_id)
    if not vault or vault['user_id'] != user_id:
        raise ValueError('Savings goal not found.')
    if vault['status'] != 'active':
        raise ValueError('This savings goal is closed.')
    amount = _positive_amount(amount, 'Withdrawal')
    balance = round(float(vault['balance'] or 0), 2)
    if amount > balance + 0.005:
        raise ValueError(f'Not enough in this goal. Available: {balance:.2f}.')
    progress = _vault_progress(vault)
    if not progress['unlocked']:
        raise ValueError(progress['lock_reason'] or 'This goal is locked until its target is reached.')

    new_balance = round(balance - amount, 2)
    db = get_db()
    try:
        payment_id = create_payment(
            user_id, amount, ptype='vault_withdrawal',
            description=f'Vault: {vault["name"]}', auto_repay=False, commit=False
        )
        db.execute(
            "UPDATE savings_vaults SET balance=?, updated_at=datetime('now') WHERE id=?",
            (new_balance, vault_id)
        )
        db.execute(
            """INSERT INTO savings_vault_transactions
               (vault_id, user_id, payment_id, type, amount, balance_after, description)
               VALUES (?, ?, ?, 'withdrawal', ?, ?, ?)""",
            (vault_id, user_id, payment_id, -amount, new_balance, 'Withdrawn to spendable')
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _vault_row(vault_id)


def get_savings_vault_transactions(vault_id=None, user_id=None, limit=100):
    db = get_db()
    params = []
    query = """SELECT svt.*, u.name as user_name, sv.name as vault_name
               FROM savings_vault_transactions svt
               JOIN users u ON svt.user_id=u.id
               JOIN savings_vaults sv ON svt.vault_id=sv.id
               WHERE 1=1"""
    if vault_id is not None:
        query += " AND svt.vault_id=?"
        params.append(int(vault_id))
    if user_id is not None:
        query += " AND svt.user_id=?"
        params.append(int(user_id))
    query += " ORDER BY svt.created_at DESC, svt.id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    return db.execute(query, params).fetchall()


def get_bank_transactions(user_id=None, limit=100):
    db = get_db()
    params = []
    query = """SELECT bt.*, u.name as user_name
               FROM bank_transactions bt
               JOIN users u ON bt.user_id=u.id
               WHERE 1=1"""
    if user_id:
        query += " AND bt.user_id=?"
        params.append(user_id)
    query += " ORDER BY bt.created_at DESC, bt.id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    return db.execute(query, params).fetchall()


def apply_for_loan(user_id, amount, term_weeks, purpose=''):
    _validate_child_user(user_id)
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError('Loan amount must be a number.') from exc
    try:
        term_weeks = int(term_weeks)
    except (TypeError, ValueError) as exc:
        raise ValueError('Loan term must be a whole number of weeks.') from exc
    if amount <= 0:
        raise ValueError('Loan amount must be greater than zero.')
    if term_weeks < 1 or term_weeks > 104:
        raise ValueError('Loan term must be between 1 and 104 weeks.')
    db = get_db()
    existing = db.execute(
        "SELECT id FROM loans WHERE user_id=? AND status IN ('pending', 'active')",
        (user_id,)
    ).fetchone()
    if existing:
        raise ValueError('You already have a pending or active loan.')
    cursor = db.execute(
        """INSERT INTO loans (user_id, amount_requested, purpose, term_weeks, status)
           VALUES (?, ?, ?, ?, 'pending')""",
        (user_id, amount, (purpose or '').strip()[:500], term_weeks)
    )
    db.commit()
    return cursor.lastrowid


def get_loan(loan_id):
    return get_db().execute(
        """SELECT l.*, u.name as user_name, u.photo_path,
                  a.name as approver_name
           FROM loans l
           JOIN users u ON l.user_id=u.id
           LEFT JOIN users a ON l.approved_by=a.id
           WHERE l.id=?""",
        (loan_id,)
    ).fetchone()


def get_loans(user_id=None, status=None, limit=200):
    db = get_db()
    params = []
    query = """SELECT l.*, u.name as user_name, u.photo_path,
                      a.name as approver_name
               FROM loans l
               JOIN users u ON l.user_id=u.id
               LEFT JOIN users a ON l.approved_by=a.id
               WHERE 1=1"""
    if user_id:
        query += " AND l.user_id=?"
        params.append(user_id)
    if status:
        statuses = status if isinstance(status, (list, tuple, set)) else [status]
        placeholders = ','.join('?' for _ in statuses)
        query += f" AND l.status IN ({placeholders})"
        params.extend(statuses)
    query += """ ORDER BY CASE l.status
                    WHEN 'pending' THEN 0
                    WHEN 'active' THEN 1
                    ELSE 2 END, l.created_at DESC, l.id DESC
                 LIMIT ?"""
    params.append(max(1, int(limit)))
    return db.execute(query, params).fetchall()


def approve_loan(loan_id, approver_id, annual_rate=0, term_weeks=None, principal=None):
    db = get_db()
    loan = db.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
    if not loan or loan['status'] != 'pending':
        raise ValueError('Only pending loans can be approved.')
    try:
        rate = max(0.0, float(annual_rate or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError('Interest rate must be a number.') from exc
    amount = loan['amount_requested'] if principal is None else principal
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError('Loan principal must be a number.') from exc
    if amount <= 0:
        raise ValueError('Loan principal must be greater than zero.')
    term = loan['term_weeks'] if term_weeks is None else term_weeks
    try:
        term = int(term)
    except (TypeError, ValueError) as exc:
        raise ValueError('Loan term must be a whole number of weeks.') from exc
    if term < 1 or term > 104:
        raise ValueError('Loan term must be between 1 and 104 weeks.')
    terms = banking.loan_terms(amount, rate, term)
    start_date = clock.local_date_text()
    next_due_date = banking.add_weeks(start_date, 1)
    db.execute(
        """UPDATE loans
           SET status='active', principal=?, interest_rate=?, term_weeks=?,
               total_repayable=?, installment_amount=?, amount_repaid=0,
               remaining_balance=?, start_date=?, next_due_date=?,
               approved_by=?, approved_at=datetime('now'), updated_at=datetime('now')
           WHERE id=?""",
        (terms['principal'], terms['annual_interest_rate'], terms['term_weeks'],
         terms['total_repayable'], terms['installment_amount'],
         terms['total_repayable'], start_date, next_due_date,
         approver_id, loan_id)
    )
    db.commit()
    create_payment(
        loan['user_id'], terms['principal'], ptype='loan',
        description=f'Loan #{loan_id} approved',
        created_by=approver_id, auto_repay=False
    )
    return get_loan(loan_id)


def reject_loan(loan_id, reason=''):
    db = get_db()
    loan = db.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
    if not loan or loan['status'] != 'pending':
        raise ValueError('Only pending loans can be rejected.')
    db.execute(
        """UPDATE loans
           SET status='rejected', rejected_reason=?, updated_at=datetime('now')
           WHERE id=?""",
        ((reason or '').strip()[:500], loan_id)
    )
    db.commit()
    return get_loan(loan_id)


def apply_loan_repayment(user_id, available_amount, source='earning'):
    try:
        available = round(float(available_amount or 0), 2)
    except (TypeError, ValueError):
        return {'total': 0.0, 'repayments': []}
    if available <= 0:
        return {'total': 0.0, 'repayments': []}
    db = get_db()
    loans = db.execute(
        """SELECT * FROM loans
           WHERE user_id=? AND status='active'
           ORDER BY COALESCE(next_due_date, start_date, '9999-12-31') ASC, id ASC""",
        (user_id,)
    ).fetchall()
    total = 0.0
    repayments = []
    for loan in loans:
        if available <= 0:
            break
        remaining = round(float(loan['remaining_balance'] or 0), 2)
        if remaining <= 0:
            db.execute(
                "UPDATE loans SET status='repaid', remaining_balance=0 WHERE id=?",
                (loan['id'],)
            )
            continue
        installment = round(float(loan['installment_amount'] or 0), 2)
        due = remaining if installment <= 0 else min(remaining, installment, available)
        due = round(due, 2)
        if due <= 0:
            continue
        payment_id = create_payment(
            user_id, -due, ptype='loan_repayment',
            description=f"Loan #{loan['id']} repayment",
            auto_repay=False
        )
        new_remaining = round(remaining - due, 2)
        new_repaid = round(float(loan['amount_repaid'] or 0) + due, 2)
        if new_remaining <= 0.005:
            new_remaining = 0
            status = 'repaid'
            next_due_date = None
        else:
            status = 'active'
            if installment > 0 and due + 0.005 >= installment:
                next_due_date = banking.add_weeks(
                    loan['next_due_date'] or loan['start_date'], 1
                )
            else:
                next_due_date = loan['next_due_date']
        db.execute(
            """UPDATE loans
               SET amount_repaid=?, remaining_balance=?, status=?,
                   next_due_date=?, updated_at=datetime('now')
               WHERE id=?""",
            (new_repaid, new_remaining, status, next_due_date, loan['id'])
        )
        db.execute(
            """INSERT INTO loan_repayments (loan_id, payment_id, amount, source)
               VALUES (?, ?, ?, ?)""",
            (loan['id'], payment_id, due, source)
        )
        total = round(total + due, 2)
        available = round(available - due, 2)
        repayments.append({
            'loan_id': loan['id'],
            'amount': due,
            'payment_id': payment_id,
            'status': status,
        })
    db.commit()
    return {'total': total, 'repayments': repayments}


# --- Household bill helpers ---

def _validate_bill_child(user_id):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError('Choose a child for this bill.') from exc
    db = get_db()
    user = db.execute(
        "SELECT id, role, is_active FROM users WHERE id=?",
        (user_id,)
    ).fetchone()
    if not user or user['role'] != 'child' or not user['is_active']:
        raise ValueError('Bills are only available to active child accounts.')
    return user_id


def _bill_money(value, label='Amount'):
    try:
        amount = round(float(value), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be a number.') from exc
    if amount <= 0:
        raise ValueError(f'{label} must be greater than zero.')
    return amount


def _bill_fee_value(value):
    try:
        fee = round(float(value or 0), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError('Late fee value must be a number.') from exc
    if fee < 0:
        raise ValueError('Late fee value cannot be negative.')
    return fee


def _bill_name(value):
    name = (value or '').strip()
    if not name:
        raise ValueError('Bill name is required.')
    if len(name) > 80:
        raise ValueError('Bill name must be 80 characters or fewer.')
    return name


def create_household_bill(user_id, name, category, amount, frequency, next_due_date,
                          auto_deduct=True, late_fee_type='none', late_fee_value=0):
    user_id = _validate_bill_child(user_id)
    name = _bill_name(name)
    category = billing.normalize_category(category)
    amount = _bill_money(amount)
    frequency = billing.normalize_frequency(frequency)
    due = billing.parse_date(next_due_date)
    if due is None:
        raise ValueError('Due date is required.')
    due_date = due.isoformat()
    late_fee_type = billing.normalize_late_fee_type(late_fee_type)
    fee_value = _bill_fee_value(late_fee_value)
    if late_fee_type == 'none':
        fee_value = 0
    db = get_db()
    cursor = db.execute(
        """INSERT INTO household_bills
           (user_id, name, category, amount, frequency, next_due_date,
            auto_deduct, late_fee_type, late_fee_value)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, name, category, amount, frequency, due_date,
         1 if auto_deduct else 0, late_fee_type, fee_value)
    )
    db.commit()
    return get_household_bill(cursor.lastrowid)


def get_household_bill(bill_id):
    return get_db().execute(
        """SELECT b.*, u.name as user_name, u.color as user_color,
                  u.photo_path as user_photo
           FROM household_bills b
           JOIN users u ON b.user_id=u.id
           WHERE b.id=?""",
        (bill_id,)
    ).fetchone()


def get_household_bills(user_id=None, active_only=False):
    params = []
    query = """SELECT b.*, u.name as user_name, u.color as user_color,
                      u.photo_path as user_photo
               FROM household_bills b
               JOIN users u ON b.user_id=u.id
               WHERE 1=1"""
    if user_id is not None:
        query += " AND b.user_id=?"
        params.append(user_id)
    if active_only:
        query += " AND b.is_active=1"
    query += " ORDER BY b.is_active DESC, b.next_due_date ASC, b.name ASC"
    return get_db().execute(query, params).fetchall()


def update_household_bill(bill_id, user_id, name, category, amount, frequency,
                          next_due_date, auto_deduct=True,
                          late_fee_type='none', late_fee_value=0):
    existing = get_household_bill(bill_id)
    if not existing:
        raise ValueError('Bill not found.')
    user_id = _validate_bill_child(user_id)
    name = _bill_name(name)
    category = billing.normalize_category(category)
    amount = _bill_money(amount)
    frequency = billing.normalize_frequency(frequency)
    due = billing.parse_date(next_due_date)
    if due is None:
        raise ValueError('Due date is required.')
    due_date = due.isoformat()
    late_fee_type = billing.normalize_late_fee_type(late_fee_type)
    fee_value = _bill_fee_value(late_fee_value)
    if late_fee_type == 'none':
        fee_value = 0
    db = get_db()
    db.execute(
        """UPDATE household_bills
           SET user_id=?, name=?, category=?, amount=?, frequency=?,
               next_due_date=?, auto_deduct=?, late_fee_type=?,
               late_fee_value=?, updated_at=datetime('now')
           WHERE id=?""",
        (user_id, name, category, amount, frequency, due_date,
         1 if auto_deduct else 0, late_fee_type, fee_value, bill_id)
    )
    db.commit()
    return get_household_bill(bill_id)


def set_household_bill_active(bill_id, is_active):
    bill = get_household_bill(bill_id)
    if not bill:
        raise ValueError('Bill not found.')
    db = get_db()
    db.execute(
        "UPDATE household_bills SET is_active=?, updated_at=datetime('now') WHERE id=?",
        (1 if is_active else 0, bill_id)
    )
    db.commit()
    return get_household_bill(bill_id)


def delete_household_bill(bill_id):
    bill = get_household_bill(bill_id)
    if not bill:
        raise ValueError('Bill not found.')
    db = get_db()
    db.execute("DELETE FROM household_bills WHERE id=?", (bill_id,))
    db.commit()
    return bill


def schedule_due_bills(now=None):
    today = billing.parse_date(now).isoformat() if now is not None else clock.local_date_text()
    db = get_db()
    bills = db.execute(
        """SELECT * FROM household_bills
           WHERE is_active=1 AND next_due_date <= ?
           ORDER BY next_due_date ASC, id ASC""",
        (today,)
    ).fetchall()
    created = 0
    for bill in bills:
        due = bill['next_due_date']
        for _ in range(60):
            cursor = db.execute(
                """INSERT OR IGNORE INTO bill_occurrences
                   (bill_id, user_id, name, category, amount, due_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (bill['id'], bill['user_id'], bill['name'], bill['category'],
                 bill['amount'], due)
            )
            if cursor.rowcount:
                created += 1
            if bill['frequency'] == 'one_off':
                db.execute(
                    "UPDATE household_bills SET is_active=0, updated_at=datetime('now') WHERE id=?",
                    (bill['id'],)
                )
                break
            next_due = billing.advance_due_date(due, bill['frequency'])
            if next_due and next_due <= today:
                due = next_due
                continue
            db.execute(
                "UPDATE household_bills SET next_due_date=?, updated_at=datetime('now') WHERE id=?",
                (next_due, bill['id'])
            )
            break
        else:
            next_due = billing.advance_due_date(due, bill['frequency'])
            db.execute(
                "UPDATE household_bills SET next_due_date=?, updated_at=datetime('now') WHERE id=?",
                (next_due, bill['id'])
            )
    db.commit()
    return created


def apply_overdue_late_fees(now=None):
    today = billing.parse_date(now) if now is not None else clock.local_date()
    db = get_db()
    rows = db.execute(
        """SELECT o.*, b.late_fee_type, b.late_fee_value
           FROM bill_occurrences o
           JOIN household_bills b ON o.bill_id=b.id
           WHERE o.status IN ('due', 'overdue') AND o.due_date < ?
           ORDER BY o.due_date ASC, o.id ASC""",
        (today.isoformat(),)
    ).fetchall()
    fees_applied = 0
    marked_overdue = 0
    for occurrence in rows:
        if occurrence['late_fee_applied_at'] is None:
            fee = billing.late_fee_amount(
                occurrence['amount'], occurrence['late_fee_type'],
                occurrence['late_fee_value']
            )
            if fee > 0:
                db.execute(
                    """UPDATE bill_occurrences
                       SET late_fee_amount=late_fee_amount+?,
                           late_fee_applied_at=datetime('now'),
                           status='overdue', updated_at=datetime('now')
                       WHERE id=?""",
                    (fee, occurrence['id'])
                )
                fees_applied += 1
                marked_overdue += 1
                continue
        if occurrence['status'] != 'overdue':
            db.execute(
                """UPDATE bill_occurrences
                   SET status='overdue', updated_at=datetime('now')
                   WHERE id=?""",
                (occurrence['id'],)
            )
            marked_overdue += 1
    db.commit()
    return {'fees_applied': fees_applied, 'marked_overdue': marked_overdue}


def get_bill_occurrence(occurrence_id):
    return get_db().execute(
        """SELECT o.*, u.name as user_name, u.color as user_color,
                  u.photo_path as user_photo, b.frequency,
                  b.late_fee_type, b.late_fee_value, b.auto_deduct,
                  b.is_active as bill_active
           FROM bill_occurrences o
           JOIN users u ON o.user_id=u.id
           JOIN household_bills b ON o.bill_id=b.id
           WHERE o.id=?""",
        (occurrence_id,)
    ).fetchone()


def get_bill_occurrences(user_id=None, status=None, include_paid=True, limit=200):
    params = []
    query = """SELECT o.*, u.name as user_name, u.color as user_color,
                      u.photo_path as user_photo, b.frequency,
                      b.late_fee_type, b.late_fee_value, b.auto_deduct,
                      b.is_active as bill_active
               FROM bill_occurrences o
               JOIN users u ON o.user_id=u.id
               JOIN household_bills b ON o.bill_id=b.id
               WHERE 1=1"""
    if user_id is not None:
        query += " AND o.user_id=?"
        params.append(user_id)
    if status:
        if isinstance(status, (list, tuple, set)):
            placeholders = ','.join('?' for _ in status)
            query += f" AND o.status IN ({placeholders})"
            params.extend(status)
        else:
            query += " AND o.status=?"
            params.append(status)
    if not include_paid:
        query += " AND o.status NOT IN ('paid', 'waived')"
    query += " ORDER BY o.due_date ASC, o.id ASC"
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 200
    query += " LIMIT ?"
    params.append(limit)
    return get_db().execute(query, params).fetchall()


def get_bill_summary(user_id=None):
    occurrences = get_bill_occurrences(
        user_id=user_id, include_paid=False, limit=1000
    )
    total = 0.0
    overdue = 0
    for occurrence in occurrences:
        total += billing.total_due(
            occurrence['amount'], occurrence['amount_paid'],
            occurrence['late_fee_amount']
        )
        if occurrence['status'] == 'overdue' or billing.is_overdue(
                occurrence['due_date'], occurrence['status']):
            overdue += 1
    return {
        'total_due': round(total, 2),
        'overdue_count': overdue,
        'open_count': len(occurrences),
    }


def pay_bill_occurrence(occurrence_id, amount=None, source='manual',
                        created_by=None, user_id=None, now=None):
    schedule_due_bills(now)
    apply_overdue_late_fees(now)
    occurrence = get_bill_occurrence(occurrence_id)
    if not occurrence:
        raise ValueError('Bill not found.')
    if user_id is not None and occurrence['user_id'] != int(user_id):
        raise ValueError('Bill not found.')
    if occurrence['status'] in ('paid', 'waived'):
        raise ValueError('This bill is already settled.')
    balance_due = billing.total_due(
        occurrence['amount'], occurrence['amount_paid'],
        occurrence['late_fee_amount']
    )
    if balance_due <= 0:
        db = get_db()
        db.execute(
            """UPDATE bill_occurrences
               SET status='paid', paid_at=COALESCE(paid_at, datetime('now')),
                   updated_at=datetime('now')
               WHERE id=?""",
            (occurrence_id,)
        )
        db.commit()
        evaluate_achievements(occurrence['user_id'])
        return {'occurrence': get_bill_occurrence(occurrence_id), 'paid': 0.0}
    if amount is None or amount == '':
        amount = balance_due
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError('Payment amount must be a number.') from exc
    if amount <= 0:
        raise ValueError('Payment amount must be greater than zero.')
    if amount > balance_due + 0.005:
        raise ValueError('Payment is more than the balance due.')
    if amount > round(float(get_balance(occurrence['user_id']) or 0), 2) + 0.005:
        raise ValueError('Not enough spendable balance to pay this bill.')
    payment_id = create_payment(
        occurrence['user_id'], -amount, ptype='bill_payment',
        description=f"Bill: {occurrence['name']} due {occurrence['due_date']}",
        created_by=created_by, auto_repay=False, commit=False
    )
    new_paid = round(float(occurrence['amount_paid'] or 0) + amount, 2)
    settled = new_paid + 0.005 >= balance_due
    status = 'paid' if settled else (
        'overdue' if billing.is_overdue(occurrence['due_date'], 'due', now) else 'due'
    )
    db = get_db()
    db.execute(
        """UPDATE bill_occurrences
           SET amount_paid=?, status=?,
               paid_at=CASE WHEN ? THEN datetime('now') ELSE paid_at END,
               updated_at=datetime('now')
           WHERE id=?""",
        (new_paid, status, 1 if settled else 0, occurrence_id)
    )
    db.execute(
        """INSERT INTO bill_payments (occurrence_id, payment_id, amount, source)
           VALUES (?, ?, ?, ?)""",
        (occurrence_id, payment_id, amount, source)
    )
    db.commit()
    evaluate_achievements(occurrence['user_id'])
    return {
        'occurrence': get_bill_occurrence(occurrence_id),
        'paid': amount,
        'payment_id': payment_id,
    }


def apply_bill_deductions(user_id, available_amount, source='earning', now=None):
    try:
        available = round(float(available_amount or 0), 2)
    except (TypeError, ValueError):
        return {'total': 0.0, 'payments': []}
    if available <= 0:
        return {'total': 0.0, 'payments': []}
    schedule_due_bills(now)
    apply_overdue_late_fees(now)
    db = get_db()
    occurrences = db.execute(
        """SELECT o.*, b.frequency, b.late_fee_type, b.late_fee_value
           FROM bill_occurrences o
           JOIN household_bills b ON o.bill_id=b.id
           WHERE o.user_id=? AND o.status IN ('due', 'overdue')
             AND b.auto_deduct=1
           ORDER BY o.due_date ASC, o.id ASC""",
        (user_id,)
    ).fetchall()
    total = 0.0
    payments = []
    for occurrence in occurrences:
        if available <= 0:
            break
        balance_due = billing.total_due(
            occurrence['amount'], occurrence['amount_paid'],
            occurrence['late_fee_amount']
        )
        if balance_due <= 0:
            continue
        due = round(min(balance_due, available), 2)
        if due <= 0:
            continue
        payment_id = create_payment(
            user_id, -due, ptype='bill_payment',
            description=f"Bill: {occurrence['name']} due {occurrence['due_date']}",
            auto_repay=False, commit=False
        )
        new_paid = round(float(occurrence['amount_paid'] or 0) + due, 2)
        settled = new_paid + 0.005 >= balance_due
        status = 'paid' if settled else (
            'overdue' if billing.is_overdue(occurrence['due_date'], 'due', now) else 'due'
        )
        db.execute(
            """UPDATE bill_occurrences
               SET amount_paid=?, status=?,
                   paid_at=CASE WHEN ? THEN datetime('now') ELSE paid_at END,
                   updated_at=datetime('now')
               WHERE id=?""",
            (new_paid, status, 1 if settled else 0, occurrence['id'])
        )
        db.execute(
            """INSERT INTO bill_payments (occurrence_id, payment_id, amount, source)
               VALUES (?, ?, ?, ?)""",
            (occurrence['id'], payment_id, due, source)
        )
        total = round(total + due, 2)
        available = round(available - due, 2)
        payments.append({
            'occurrence_id': occurrence['id'],
            'bill': occurrence['name'],
            'amount': due,
            'payment_id': payment_id,
        })
    db.commit()
    evaluate_achievements(user_id)
    return {'total': total, 'payments': payments}


# --- Achievement and broadcast helpers ---

BROADCAST_KINDS = {'general', 'achievement', 'milestone', 'celebration'}


def _normalise_broadcast_expiry(value):
    text = (value or '').strip()
    if not text:
        return None
    text = text.replace('T', ' ')
    if len(text) == 16:
        text += ':00'
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError('Expiry must be a valid date and time.') from exc
    return text


def _clean_broadcast_kind(value):
    kind = (value or 'general').strip().lower()
    if kind not in BROADCAST_KINDS:
        raise ValueError('Choose a valid broadcast type.')
    return kind


def get_custom_milestone(milestone_id):
    row = get_db().execute(
        "SELECT * FROM custom_milestones WHERE id=?", (milestone_id,)
    ).fetchone()
    return achievements.custom_definition(row) if row else None


def get_custom_milestones(active_only=False):
    query = "SELECT * FROM custom_milestones"
    if active_only:
        query += " WHERE is_active=1"
    query += " ORDER BY created_at ASC, id ASC"
    return [
        achievements.custom_definition(row)
        for row in get_db().execute(query).fetchall()
    ]


def create_custom_milestone(name, description='', icon='bi-award-fill',
                            color='#10b981', metric='chores_completed',
                            threshold=1, reward_type='none', reward_value=0,
                            created_by=None):
    name = (name or '').strip()
    if not name:
        raise ValueError('Milestone name is required.')
    if len(name) > 100:
        raise ValueError('Milestone name must be 100 characters or fewer.')
    description = (description or '').strip()[:500]
    metric = achievements.normalize_metric(metric)
    threshold = achievements.normalize_threshold(threshold)
    reward_type = achievements.normalize_reward_type(reward_type)
    reward_value = achievements.normalize_reward_value(reward_value, reward_type)
    icon = achievements.clean_icon(icon)
    color = achievements.clean_color(color)
    db = get_db()
    cursor = db.execute(
        """INSERT INTO custom_milestones
           (name, description, icon, color, metric, threshold, reward_type,
            reward_value, created_by, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (name, description, icon, color, metric, threshold, reward_type,
         reward_value, created_by)
    )
    db.commit()
    return get_custom_milestone(cursor.lastrowid)


def set_custom_milestone_active(milestone_id, active):
    milestone = get_custom_milestone(milestone_id)
    if not milestone:
        raise ValueError('Milestone not found.')
    db = get_db()
    db.execute(
        "UPDATE custom_milestones SET is_active=?, updated_at=datetime('now') WHERE id=?",
        (1 if active else 0, milestone_id)
    )
    db.commit()
    return get_custom_milestone(milestone_id)


def delete_custom_milestone(milestone_id):
    milestone = get_custom_milestone(milestone_id)
    if not milestone:
        raise ValueError('Milestone not found.')
    db = get_db()
    db.execute("DELETE FROM custom_milestones WHERE id=?", (milestone_id,))
    db.commit()
    return milestone


def get_achievement_definitions(include_inactive=False):
    definitions = achievements.builtin_definitions()
    definitions.extend(get_custom_milestones(active_only=not include_inactive))
    return definitions


def get_achievement_metrics(user_id):
    stats = _ensure_gamification(user_id)
    if not stats:
        return None
    db = get_db()
    chores = db.execute(
        """SELECT COUNT(*) AS cnt FROM chore_logs
           WHERE user_id=? AND status='completed' AND approved_by IS NOT NULL""",
        (user_id,)
    ).fetchone()['cnt']
    total_earned = db.execute(
        """SELECT COALESCE(SUM(amount), 0) AS total FROM payments
           WHERE user_id=? AND type='earning' AND amount>0""",
        (user_id,)
    ).fetchone()['total']
    savings = db.execute(
        "SELECT COALESCE(balance, 0) AS balance FROM savings_accounts WHERE user_id=?",
        (user_id,)
    ).fetchone()
    vaults_completed = db.execute(
        """SELECT COUNT(*) AS cnt FROM savings_vaults
           WHERE user_id=? AND completed_at IS NOT NULL""",
        (user_id,)
    ).fetchone()['cnt']
    bills_paid = db.execute(
        """SELECT COUNT(*) AS cnt FROM bill_occurrences
           WHERE user_id=? AND status='paid'""",
        (user_id,)
    ).fetchone()['cnt']
    marketplace_orders = db.execute(
        """SELECT COUNT(*) AS cnt FROM marketplace_orders
           WHERE user_id=? AND status IN ('approved', 'fulfilled')""",
        (user_id,)
    ).fetchone()['cnt']

    activity_logs = db.execute(
        """SELECT cl.finished_at, c.name AS chore_name, c.description AS chore_description
           FROM chore_logs cl
           JOIN chores c ON c.id = cl.chore_id
           WHERE cl.user_id=? AND cl.status='completed'
             AND cl.finished_at IS NOT NULL""",
        (user_id,)
    ).fetchall()
    user = get_user(user_id)
    birthday = None
    if user and user['date_of_birth']:
        try:
            born = datetime.strptime(str(user['date_of_birth'])[:10], '%Y-%m-%d').date()
            birthday = (born.month, born.day)
        except (TypeError, ValueError):
            birthday = None

    night_chores = 0
    pet_cleanings = 0
    weekend_days = []
    periods_by_date = {}
    date_counts = {
        'new_year_chores': 0, 'christmas_chores': 0, 'halloween_chores': 0,
        'easter_chores': 0, 'birthday_chores': 0,
    }
    for log in activity_logs:
        try:
            local = clock.parse_utc(log['finished_at']).astimezone()
        except (TypeError, ValueError):
            continue
        local_date = local.date()
        if achievements.is_night_hour(local.hour):
            night_chores += 1
        periods_by_date.setdefault(local_date, set()).add(
            achievements.time_period(local.hour)
        )
        if local_date.weekday() >= 5:
            weekend_days.append(local_date)
        if achievements.is_pet_cleaning_chore(
            log['chore_name'], log['chore_description']
        ):
            pet_cleanings += 1
        if (local_date.month, local_date.day) == (1, 1):
            date_counts['new_year_chores'] += 1
        if (local_date.month, local_date.day) == (12, 25):
            date_counts['christmas_chores'] += 1
        if (local_date.month, local_date.day) == (10, 31):
            date_counts['halloween_chores'] += 1
        if birthday == (local_date.month, local_date.day):
            date_counts['birthday_chores'] += 1
        try:
            if achievements.easter_date(local_date.year) == local_date:
                date_counts['easter_chores'] += 1
        except ValueError:
            pass

    all_day_chore_days = sum(
        1 for periods in periods_by_date.values()
        if {'morning', 'afternoon', 'evening'}.issubset(periods)
    )
    return {
        'chores_completed': chores,
        'current_streak': stats['current_streak'],
        'longest_streak': stats['longest_streak'],
        'level': stats['level'],
        'total_xp': stats['total_xp'],
        'total_earned': round(float(total_earned or 0), 2),
        'savings_balance': round(float(savings['balance'] if savings else 0), 2),
        'vaults_completed': vaults_completed,
        'bills_paid': bills_paid,
        'marketplace_orders': marketplace_orders,
        'night_chores': night_chores,
        'all_day_chore_days': all_day_chore_days,
        'consecutive_weekends': achievements.longest_consecutive_weekends(weekend_days),
        'pet_cleanings': pet_cleanings,
        **date_counts,
    }


def get_achievement_unlocks(user_id=None, limit=100):
    db = get_db()
    params = []
    query = """SELECT a.*, u.name AS user_name, u.photo_path, u.color AS user_color
               FROM achievement_unlocks a
               JOIN users u ON a.user_id=u.id
               WHERE 1=1"""
    if user_id is not None:
        query += " AND a.user_id=?"
        params.append(user_id)
    query += " ORDER BY a.unlocked_at DESC, a.id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    return db.execute(query, params).fetchall()


def get_child_achievements(user_id, include_inactive=False):
    metrics = get_achievement_metrics(user_id)
    if metrics is None:
        return []
    db = get_db()
    unlocks = {
        row['achievement_key']: row for row in db.execute(
            "SELECT * FROM achievement_unlocks WHERE user_id=?", (user_id,)
        ).fetchall()
    }
    items = []
    for definition in get_achievement_definitions(include_inactive=include_inactive):
        entry = dict(definition)
        value = float(metrics.get(entry['metric'], 0) or 0)
        unlock = unlocks.get(entry['key'])
        entry.update({
            'value': value,
            'value_text': achievements.format_value(entry['metric'], value),
            'progress_percent': achievements.progress_percent(value, entry['threshold']),
            'remaining': achievements.remaining(value, entry['threshold']),
            'unlocked': unlock is not None,
            'unlocked_at': unlock['unlocked_at'] if unlock else None,
            'reward_payment_id': unlock['reward_payment_id'] if unlock else None,
            'broadcast_id': unlock['broadcast_id'] if unlock else None,
        })
        entry['remaining_text'] = achievements.format_value(
            entry['metric'], entry['remaining']
        )
        items.append(entry)
    items.sort(key=lambda item: (
        0 if item['unlocked'] else 1,
        achievements.category_sort_key(item.get('category')),
        float(item.get('threshold') or 0),
        item.get('name', ''),
    ))
    return items


def _grant_achievement_xp(user_id, xp_amount, unlock_id):
    stats = _ensure_gamification(user_id)
    if not stats:
        return None
    try:
        amount = max(0, int(round(float(xp_amount or 0))))
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return stats
    db = get_db()
    new_total = stats['total_xp'] + amount
    new_level = gamification.level_for_xp(new_total)
    db.execute(
        """UPDATE user_gamification
           SET total_xp=?, level=?, updated_at=datetime('now')
           WHERE user_id=?""",
        (new_total, new_level, user_id)
    )
    db.execute(
        """INSERT OR IGNORE INTO xp_events
           (user_id, source_type, source_id, reward_amount, base_xp,
            streak_days, multiplier, xp_awarded, completed_date)
           VALUES (?, 'achievement', ?, 0, ?, ?, 1.0, ?, ?)""",
        (user_id, unlock_id, amount, max(1, int(stats['current_streak'] or 1)),
         amount, clock.local_date_text())
    )
    db.commit()
    _sync_gamification_unlocks(
        user_id, new_level, new_total,
        stats['longest_streak'], stats['current_streak']
    )
    return db.execute(
        "SELECT * FROM user_gamification WHERE user_id=?", (user_id,)
    ).fetchone()


def create_broadcast_alert(title, body='', kind='general', child_id=None,
                           achievement_key=None, icon='bi-megaphone-fill',
                           color='#10b981', created_by=None, expires_at=None):
    title = (title or '').strip()
    if not title:
        raise ValueError('Broadcast title is required.')
    if len(title) > 120:
        raise ValueError('Broadcast title must be 120 characters or fewer.')
    body = (body or '').strip()[:500]
    kind = _clean_broadcast_kind(kind)
    icon = achievements.clean_icon(icon, default='bi-megaphone-fill')
    color = achievements.clean_color(color)
    expires_at = _normalise_broadcast_expiry(expires_at)
    if child_id not in (None, ''):
        try:
            child_id = int(child_id)
        except (TypeError, ValueError) as exc:
            raise ValueError('Choose a valid child.') from exc
        child = get_user(child_id)
        if not child or child['role'] != 'child':
            raise ValueError('Choose a valid child.')
    else:
        child_id = None
    db = get_db()
    cursor = db.execute(
        """INSERT INTO broadcast_alerts
           (title, body, kind, child_id, achievement_key, icon, color,
            created_by, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, body, kind, child_id, achievement_key, icon, color,
         created_by, expires_at)
    )
    db.commit()
    broadcast = db.execute(
        "SELECT * FROM broadcast_alerts WHERE id=?", (cursor.lastrowid,)
    ).fetchone()
    record_live_event(
        'broadcast', title=title, body=body,
        payload={
            'id': broadcast['id'], 'kind': kind, 'child_id': child_id,
            'achievement_key': achievement_key, 'icon': icon, 'color': color,
            'expires_at': expires_at,
        },
        user_id=created_by, child_id=child_id,
    )
    return broadcast


def get_active_broadcasts(limit=10):
    return get_db().execute(
        """SELECT b.*, u.name AS child_name, u.color AS child_color
           FROM broadcast_alerts b
           LEFT JOIN users u ON b.child_id=u.id
           WHERE b.is_active=1
             AND (b.expires_at IS NULL OR b.expires_at > datetime('now'))
           ORDER BY b.created_at DESC, b.id DESC LIMIT ?""",
        (max(1, int(limit)),)
    ).fetchall()


def get_latest_active_broadcast():
    rows = get_active_broadcasts(limit=1)
    return rows[0] if rows else None


def get_all_broadcasts(limit=50):
    return get_db().execute(
        """SELECT b.*, u.name AS child_name, u.color AS child_color
           FROM broadcast_alerts b
           LEFT JOIN users u ON b.child_id=u.id
           ORDER BY b.created_at DESC, b.id DESC LIMIT ?""",
        (max(1, int(limit)),)
    ).fetchall()


def deactivate_broadcast_alert(broadcast_id):
    db = get_db()
    cursor = db.execute(
        "UPDATE broadcast_alerts SET is_active=0 WHERE id=?", (broadcast_id,)
    )
    db.commit()
    return cursor.rowcount > 0


def evaluate_achievements(user_id):
    user = get_user(user_id)
    if not user or user['role'] != 'child' or not user['is_active']:
        return []
    db = get_db()
    added = []
    for _ in range(25):
        metrics = get_achievement_metrics(user_id)
        if metrics is None:
            break
        unlocked_keys = {
            row['achievement_key'] for row in db.execute(
                "SELECT achievement_key FROM achievement_unlocks WHERE user_id=?",
                (user_id,)
            ).fetchall()
        }
        ready = achievements.evaluate(
            metrics, unlocked_keys, get_achievement_definitions()
        )
        if not ready:
            break
        ready.sort(key=lambda item: item.get('key') == 'first_chore')
        progressed = False
        for definition in ready:
            cursor = db.execute(
                """INSERT OR IGNORE INTO achievement_unlocks
                   (user_id, achievement_key, name, description, icon, color,
                    metric, threshold, reward_type, reward_value)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, definition['key'], definition['name'],
                 definition.get('description', ''), definition['icon'],
                 definition['color'], definition['metric'], definition['threshold'],
                 definition['reward_type'], definition['reward_value'])
            )
            if cursor.rowcount != 1:
                continue
            unlock_id = cursor.lastrowid
            db.commit()
            payment_id = None
            if definition['reward_type'] == 'bonus' and definition['reward_value'] > 0:
                payment_id = create_payment(
                    user_id, definition['reward_value'], ptype='milestone_reward',
                    description=f"Achievement reward: {definition['name']}",
                    auto_repay=False
                )
                db.execute(
                    "UPDATE achievement_unlocks SET reward_payment_id=? WHERE id=?",
                    (payment_id, unlock_id)
                )
                db.commit()
            elif definition['reward_type'] == 'xp' and definition['reward_value'] > 0:
                _grant_achievement_xp(user_id, definition['reward_value'], unlock_id)
            broadcast_id = create_broadcast_alert(
                title=f"{user['name']} unlocked {definition['name']}",
                body=definition.get('description', ''),
                kind='milestone' if definition.get('is_custom') else 'achievement',
                child_id=user_id,
                achievement_key=definition['key'],
                icon=definition['icon'],
                color=definition['color'],
            )
            db.execute(
                "UPDATE achievement_unlocks SET broadcast_id=? WHERE id=?",
                (broadcast_id['id'], unlock_id)
            )
            db.commit()
            record_live_event(
                'achievement',
                title=f"{user['name']} unlocked {definition['name']}",
                body=definition.get('description', ''),
                payload={
                    'achievement_key': definition['key'],
                    'name': definition['name'],
                    'icon': definition['icon'],
                    'color': definition['color'],
                    'reward_type': definition['reward_type'],
                    'reward_value': definition['reward_value'],
                },
                child_id=user_id,
            )
            added.append(dict(db.execute(
                "SELECT * FROM achievement_unlocks WHERE id=?", (unlock_id,)
            ).fetchone()))
            progressed = True
        if not progressed:
            break
    return added


# --- Marketplace helpers ---

MARKETPLACE_CATEGORIES = {'item', 'privilege', 'screen_time'}
MARKETPLACE_CURRENCIES = {'token', 'cash'}
MARKETPLACE_STATUSES = {'pending', 'approved', 'fulfilled', 'rejected', 'cancelled'}


def _validate_marketplace_category(category):
    if category not in MARKETPLACE_CATEGORIES:
        raise ValueError('Category must be item, privilege or screen_time.')


def _marketplace_currency(value):
    value = (value or 'token').strip().lower()
    aliases = {
        'token': 'token', 'tokens': 'token', 'points': 'token', 'earned': 'token',
        'cash': 'cash', 'money': 'cash', 'currency': 'cash', 'allowance': 'cash',
    }
    currency = aliases.get(value)
    if not currency:
        raise ValueError('Currency must be token or cash.')
    return currency


def _marketplace_money(value, label='Price'):
    try:
        amount = round(float(value), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be a number.') from exc
    if amount <= 0:
        raise ValueError(f'{label} must be greater than zero.')
    return amount


def _marketplace_optional_money(value, label):
    if value is None or str(value).strip() == '':
        return None
    return _marketplace_money(value, label)


def _marketplace_pricing(price, currency_type='token', token_price=None, cash_price=None):
    currency = _marketplace_currency(currency_type)
    token_value = _marketplace_optional_money(token_price, 'Token price')
    cash_value = _marketplace_optional_money(cash_price, 'Cash price')
    if token_value is None and currency == 'token':
        token_value = _marketplace_money(price, 'Token price')
    if cash_value is None and currency == 'cash':
        cash_value = _marketplace_money(price, 'Cash price')
    if currency == 'token' and token_value is None:
        raise ValueError('A token price is required for token items.')
    if currency == 'cash' and cash_value is None:
        raise ValueError('A cash price is required for cash items.')
    legacy_price = token_value if currency == 'token' else cash_value
    return currency, token_value, cash_value, legacy_price


def _marketplace_stock(value):
    if value is None or value == '':
        return None
    try:
        stock = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Stock must be a whole number, or blank for unlimited.') from exc
    if stock < 0:
        raise ValueError('Stock cannot be negative.')
    return stock


def _new_qr_token():
    db = get_db()
    for _ in range(10):
        token = secrets.token_urlsafe(24)
        if not db.execute(
            "SELECT id FROM marketplace_orders WHERE qr_token=?", (token,)
        ).fetchone():
            return token
    raise RuntimeError('Could not generate a unique redemption token.')


def create_marketplace_item(name, price=None, category='item', description='', stock_quantity=None,
                            icon='bi-bag-fill', color='#10b981', requires_approval=1,
                            sort_order=0, currency_type='token', token_price=None,
                            cash_price=None):
    name = (name or '').strip()
    if not name:
        raise ValueError('Item name is required.')
    _validate_marketplace_category(category)
    currency, token_value, cash_value, legacy_price = _marketplace_pricing(
        price, currency_type, token_price, cash_price
    )
    stock = _marketplace_stock(stock_quantity)
    db = get_db()
    cursor = db.execute(
        """INSERT INTO marketplace_items
           (name, description, category, price, currency_type, token_price,
            cash_price, stock_quantity, icon, color, requires_approval, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name[:120], (description or '').strip()[:500], category, legacy_price,
         currency, token_value, cash_value, stock,
         (icon or 'bi-bag-fill').strip(), achievements.clean_color(color),
         1 if requires_approval else 0, int(sort_order or 0))
    )
    db.commit()
    return cursor.lastrowid


def update_marketplace_item(item_id, name, price=None, category='item', description='',
                            stock_quantity=None, icon='bi-bag-fill', color='#10b981',
                            requires_approval=1, sort_order=0, currency_type='token',
                            token_price=None, cash_price=None):
    item = get_marketplace_item(item_id)
    if not item:
        raise ValueError('Marketplace item not found.')
    name = (name or '').strip()
    if not name:
        raise ValueError('Item name is required.')
    _validate_marketplace_category(category)
    currency, token_value, cash_value, legacy_price = _marketplace_pricing(
        price, currency_type, token_price, cash_price
    )
    stock = _marketplace_stock(stock_quantity)
    db = get_db()
    db.execute(
        """UPDATE marketplace_items
           SET name=?, description=?, category=?, price=?, currency_type=?,
               token_price=?, cash_price=?, stock_quantity=?, icon=?, color=?,
               requires_approval=?, sort_order=?, updated_at=datetime('now')
           WHERE id=?""",
        (name[:120], (description or '').strip()[:500], category, legacy_price,
         currency, token_value, cash_value, stock,
         (icon or 'bi-bag-fill').strip(), achievements.clean_color(color),
         1 if requires_approval else 0, int(sort_order or 0), item_id)
    )
    db.commit()
    return get_marketplace_item(item_id)


def set_marketplace_item_active(item_id, is_active):
    db = get_db()
    db.execute(
        "UPDATE marketplace_items SET is_active=?, updated_at=datetime('now') WHERE id=?",
        (1 if is_active else 0, item_id)
    )
    db.commit()


def get_marketplace_item(item_id):
    return get_db().execute(
        "SELECT * FROM marketplace_items WHERE id=?", (item_id,)
    ).fetchone()


def get_marketplace_items(active_only=False):
    query = "SELECT * FROM marketplace_items"
    if active_only:
        query += " WHERE is_active=1"
    query += " ORDER BY sort_order ASC, name ASC, id ASC"
    return get_db().execute(query).fetchall()


def _restore_marketplace_stock(db, item_id, quantity):
    if item_id is None:
        return
    item = db.execute(
        "SELECT stock_quantity FROM marketplace_items WHERE id=?", (item_id,)
    ).fetchone()
    if item and item['stock_quantity'] is not None:
        db.execute(
            """UPDATE marketplace_items
               SET stock_quantity=stock_quantity+?, updated_at=datetime('now')
               WHERE id=?""",
            (quantity, item_id)
        )


def _refund_marketplace_order(db, order, actor_id, status, reason=''):
    _restore_marketplace_stock(db, order['item_id'], order['quantity'])
    description = f"Marketplace refund: {order['item_name']} x{order['quantity']}"
    if order['currency_type'] == 'cash':
        create_cash_entry(
            order['user_id'], order['total_amount'], description=description,
            created_by=actor_id, reference_type='marketplace_refund',
            reference_id=order['id'], commit=False
        )
    else:
        create_payment(
            order['user_id'], order['total_amount'], ptype='marketplace_refund',
            description=description, created_by=actor_id, auto_repay=False, commit=False
        )
    db.execute(
        """UPDATE marketplace_orders
           SET status=?, rejection_reason=?, updated_at=datetime('now')
           WHERE id=?""",
        (status, (reason or '').strip()[:500], order['id'])
    )


def create_marketplace_order(user_id, item_id, quantity=1, notes=''):
    _validate_child_user(user_id)
    item = get_marketplace_item(item_id)
    if not item or not item['is_active']:
        raise ValueError('This marketplace item is not available.')
    try:
        quantity = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError('Quantity must be a whole number.') from exc
    if quantity < 1 or quantity > 10:
        raise ValueError('Quantity must be between 1 and 10.')
    stock = item['stock_quantity']
    if stock is not None and stock < quantity:
        raise ValueError('There is not enough stock for that order.')
    currency = _marketplace_currency(item['currency_type'])
    unit_price = item['cash_price'] if currency == 'cash' else item['token_price']
    if unit_price is None:
        unit_price = item['price']
    unit_price = _marketplace_money(unit_price)
    total = round(float(unit_price) * quantity, 2)
    if currency == 'cash':
        available = get_cash_balance(user_id)
        if total > available + 0.005:
            raise ValueError(f'Not enough cash balance. Available: {available:.2f}.')
    else:
        available = round(float(get_balance(user_id)), 2)
        if total > available + 0.005:
            raise ValueError(f'Not enough spendable balance. Available: {available:.2f}.')
    db = get_db()
    token = _new_qr_token()
    status = 'pending' if item['requires_approval'] else 'approved'
    approved_at = None if status == 'pending' else clock.to_utc_text(clock.utc_now())
    token_amount = total if currency == 'token' else 0
    cash_amount = total if currency == 'cash' else 0
    try:
        cursor = db.execute(
            """INSERT INTO marketplace_orders
               (user_id, item_id, item_name, item_category, unit_price, currency_type,
                token_amount, cash_amount, quantity, total_amount, status, qr_token,
                notes, approved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, item_id, item['name'], item['category'], unit_price, currency,
             token_amount, cash_amount, quantity, total, status, token,
             (notes or '').strip()[:500], approved_at)
        )
        if stock is not None:
            changed = db.execute(
                """UPDATE marketplace_items
                   SET stock_quantity=stock_quantity-?, updated_at=datetime('now')
                   WHERE id=? AND stock_quantity>=?""",
                (quantity, item_id, quantity)
            )
            if changed.rowcount != 1:
                raise ValueError('There is not enough stock for that order.')
        description = f"Marketplace: {item['name']} x{quantity}"
        if currency == 'cash':
            create_cash_entry(
                user_id, -total, description=description,
                reference_type='marketplace_order', reference_id=cursor.lastrowid,
                commit=False
            )
        else:
            create_payment(
                user_id, -total, ptype='marketplace_purchase',
                description=description, auto_repay=False, commit=False
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    if status == 'approved':
        evaluate_achievements(user_id)
    return cursor.lastrowid


def get_marketplace_order(order_id):
    return get_db().execute(
        """SELECT o.*, u.name as user_name, u.photo_path, u.color as user_color,
                  a.name as approver_name, f.name as fulfiller_name
           FROM marketplace_orders o
           JOIN users u ON o.user_id=u.id
           LEFT JOIN users a ON o.approved_by=a.id
           LEFT JOIN users f ON o.fulfilled_by=f.id
           WHERE o.id=?""",
        (order_id,)
    ).fetchone()


def get_marketplace_order_by_token(token):
    return get_db().execute(
        """SELECT o.*, u.name as user_name, u.photo_path, u.color as user_color,
                  a.name as approver_name, f.name as fulfiller_name
           FROM marketplace_orders o
           JOIN users u ON o.user_id=u.id
           LEFT JOIN users a ON o.approved_by=a.id
           LEFT JOIN users f ON o.fulfilled_by=f.id
           WHERE o.qr_token=?""",
        (token,)
    ).fetchone()


def get_marketplace_orders(user_id=None, status=None, limit=200):
    db = get_db()
    params = []
    query = """SELECT o.*, u.name as user_name, u.photo_path, u.color as user_color,
                      a.name as approver_name, f.name as fulfiller_name
               FROM marketplace_orders o
               JOIN users u ON o.user_id=u.id
               LEFT JOIN users a ON o.approved_by=a.id
               LEFT JOIN users f ON o.fulfilled_by=f.id
               WHERE 1=1"""
    if user_id:
        query += " AND o.user_id=?"
        params.append(user_id)
    if status:
        statuses = status if isinstance(status, (list, tuple, set)) else [status]
        placeholders = ','.join('?' for _ in statuses)
        query += f" AND o.status IN ({placeholders})"
        params.extend(statuses)
    query += """ ORDER BY CASE o.status
                    WHEN 'pending' THEN 0
                    WHEN 'approved' THEN 1
                    ELSE 2 END, o.requested_at DESC, o.id DESC
                 LIMIT ?"""
    params.append(max(1, int(limit)))
    return db.execute(query, params).fetchall()


def approve_marketplace_order(order_id, approver_id):
    db = get_db()
    order = db.execute(
        "SELECT * FROM marketplace_orders WHERE id=?", (order_id,)
    ).fetchone()
    if not order or order['status'] != 'pending':
        raise ValueError('Only pending marketplace orders can be approved.')
    db.execute(
        """UPDATE marketplace_orders
           SET status='approved', approved_at=datetime('now'), approved_by=?,
               updated_at=datetime('now')
           WHERE id=?""",
        (approver_id, order_id)
    )
    db.commit()
    evaluate_achievements(order['user_id'])
    return get_marketplace_order(order_id)


def reject_marketplace_order(order_id, approver_id, reason=''):
    db = get_db()
    order = db.execute(
        "SELECT * FROM marketplace_orders WHERE id=?", (order_id,)
    ).fetchone()
    if not order or order['status'] not in ('pending', 'approved'):
        raise ValueError('Only pending or approved orders can be rejected.')
    try:
        _refund_marketplace_order(db, order, approver_id, 'rejected', reason)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_marketplace_order(order_id)


def cancel_marketplace_order(order_id, user_id):
    db = get_db()
    order = db.execute(
        "SELECT * FROM marketplace_orders WHERE id=?", (order_id,)
    ).fetchone()
    if not order or order['user_id'] != user_id:
        raise ValueError('Marketplace order not found.')
    if order['status'] != 'pending':
        raise ValueError('Only pending orders can be cancelled.')
    try:
        _refund_marketplace_order(db, order, user_id, 'cancelled', 'Cancelled by child')
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_marketplace_order(order_id)


def fulfill_marketplace_order(order_id, fulfiller_id):
    db = get_db()
    order = db.execute(
        "SELECT * FROM marketplace_orders WHERE id=?", (order_id,)
    ).fetchone()
    if not order or order['status'] not in ('pending', 'approved'):
        raise ValueError('Only pending or approved orders can be fulfilled.')
    approved_at = order['approved_at'] or clock.to_utc_text(clock.utc_now())
    approved_by = order['approved_by'] or fulfiller_id
    db.execute(
        """UPDATE marketplace_orders
           SET status='fulfilled', approved_at=?, approved_by=?,
               fulfilled_at=datetime('now'), fulfilled_by=?, updated_at=datetime('now')
           WHERE id=?""",
        (approved_at, approved_by, fulfiller_id, order_id)
    )
    db.commit()
    evaluate_achievements(order['user_id'])
    return get_marketplace_order(order_id)


# --- Settings helpers ---

UI_LAYOUT_SETTINGS = {
    'menu_position': {
        'default': 'left',
        'choices': ('left', 'top_left', 'center', 'top_right', 'right'),
        'aliases': {
            'left': 'left', 'left side': 'left', 'sidebar': 'left',
            'top left': 'top_left', 'top_left': 'top_left',
            'center': 'center', 'top center': 'center', 'top_center': 'center',
            'top right': 'top_right', 'top_right': 'top_right',
            'right': 'right', 'right side': 'right',
        },
    },
    'button_theme': {
        'default': 'default',
        'choices': ('default', 'flat', 'neumorphic', 'cyber', 'glossy'),
        'aliases': {
            'default': 'default', 'default/rounded': 'default', 'rounded': 'default',
            'flat': 'flat', 'flat/modern': 'flat', 'modern': 'flat',
            'neumorphic': 'neumorphic', 'neo': 'neumorphic',
            'cyber': 'cyber', 'cyberpunk': 'cyber',
            'glossy': 'glossy', 'glass': 'glossy',
        },
    },
}


def _normalise_ui_layout_choice(key, value):
    spec = UI_LAYOUT_SETTINGS[key]
    text = (value or '').strip().lower().replace('-', '_')
    text = ' '.join(text.split())
    canonical = spec['aliases'].get(text)
    if canonical not in spec['choices']:
        raise ValueError(f'Invalid {key.replace("_", " ")} value.')
    return canonical


def get_ui_layout_settings():
    layout = {}
    for key, spec in UI_LAYOUT_SETTINGS.items():
        raw = get_setting(key, spec['default'])
        try:
            layout[key] = _normalise_ui_layout_choice(key, raw)
        except ValueError:
            layout[key] = spec['default']
    return layout


def set_ui_layout_setting(key, value):
    if key not in UI_LAYOUT_SETTINGS:
        raise ValueError('Unknown UI layout setting.')
    canonical = _normalise_ui_layout_choice(key, value)
    set_setting(key, canonical)
    return canonical


def get_setting(key, default=None):
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row['value'] if row else default


def set_setting(key, value):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    db.commit()


# --- Family notice helpers ---

def create_notice(title, body='', created_by=None, expires_at=None):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO family_notices (title, body, created_by, expires_at) VALUES (?, ?, ?, ?)",
        (title, body, created_by, expires_at)
    )
    db.commit()
    return cursor.lastrowid


def get_active_notices():
    db = get_db()
    return db.execute(
        """SELECT * FROM family_notices WHERE is_active=1
           AND (expires_at IS NULL OR expires_at > datetime('now'))
           ORDER BY created_at DESC"""
    ).fetchall()


def get_all_notices():
    db = get_db()
    return db.execute(
        "SELECT * FROM family_notices ORDER BY created_at DESC"
    ).fetchall()


def delete_notice(notice_id):
    db = get_db()
    db.execute("UPDATE family_notices SET is_active=0 WHERE id=?", (notice_id,))
    db.commit()


# --- Calendar event helpers ---

def create_event(title, event_date, description='', event_time=None, created_by=None):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO calendar_events (title, description, event_date, event_time, created_by) VALUES (?, ?, ?, ?, ?)",
        (title, description, event_date, event_time, created_by)
    )
    db.commit()
    return cursor.lastrowid


def get_upcoming_events(limit=10):
    db = get_db()
    return db.execute(
        """SELECT * FROM calendar_events
           WHERE event_date >= date('now')
           ORDER BY event_date ASC, event_time ASC LIMIT ?""",
        (limit,)
    ).fetchall()


def get_all_events():
    db = get_db()
    return db.execute(
        "SELECT * FROM calendar_events ORDER BY event_date DESC"
    ).fetchall()


def delete_event(event_id):
    db = get_db()
    db.execute("DELETE FROM calendar_events WHERE id=?", (event_id,))
    db.commit()


# --- Activity log helpers ---

def log_activity(user_id, action, detail=''):
    db = get_db()
    db.execute(
        "INSERT INTO activity_log (user_id, action, detail) VALUES (?, ?, ?)",
        (user_id, action, detail)
    )
    db.commit()


def get_recent_activity(limit=10):
    db = get_db()
    return db.execute(
        """SELECT a.*, u.name as user_name, u.photo_path as user_photo, u.color as user_color
           FROM activity_log a
           LEFT JOIN users u ON a.user_id = u.id
           ORDER BY a.created_at DESC LIMIT ?""",
        (limit,)
    ).fetchall()


# --- Child status helpers ---

CHILD_STATUSES = ['active', 'holiday', 'sick', 'grounded', 'excused', 'custom']


def get_children_by_status():
    db = get_db()
    return db.execute(
        """SELECT status, COUNT(*) as cnt FROM users
           WHERE role='child' AND is_active=1
           GROUP BY status"""
    ).fetchall()


# --- Chore approval helpers ---

def get_pending_approvals():
    db = get_db()
    return db.execute(
        """SELECT cl.*, c.name as chore_name, c.icon as chore_icon, c.pay_amount,
           u.name as user_name, u.photo_path as user_photo, u.color as user_color
           FROM chore_logs cl
           JOIN chores c ON cl.chore_id = c.id
           JOIN users u ON cl.user_id = u.id
           WHERE cl.status='completed' AND cl.approved_by IS NULL
           ORDER BY cl.finished_at DESC"""
    ).fetchall()


def approve_chore(log_id, approver_id):
    db = get_db()
    log = db.execute("SELECT * FROM chore_logs WHERE id=?", (log_id,)).fetchone()
    if not log or log['status'] != 'completed' or log['approved_by'] is not None:
        return None
    db.execute(
        "UPDATE chore_logs SET approved_by=?, approved_at=datetime('now') WHERE id=?",
        (approver_id, log_id)
    )
    db.commit()
    award_chore_xp(log)
    return log


def reject_chore(log_id):
    db = get_db()
    log = db.execute("SELECT * FROM chore_logs WHERE id=?", (log_id,)).fetchone()
    if not log or log['status'] != 'completed' or log['approved_by'] is not None:
        return None
    db.execute("DELETE FROM chore_logs WHERE id=?", (log_id,))
    db.execute("DELETE FROM payments WHERE log_id=?", (log_id,))
    db.commit()
    return log


# --- Record counts ---

def get_record_counts():
    """Count stored records for display. Nothing is ever deleted automatically."""
    db = get_db()
    return {
        'total_logs': db.execute("SELECT COUNT(*) as cnt FROM chore_logs").fetchone()['cnt'],
        'total_payments': db.execute("SELECT COUNT(*) as cnt FROM payments").fetchone()['cnt'],
        'total_activity': db.execute("SELECT COUNT(*) as cnt FROM activity_log").fetchone()['cnt'],
    }


# --- Currency helpers ---

def get_currency_settings():
    return {
        'token_name': get_setting('currency_token_name', 'Widgets'),
        'token_singular': get_setting('currency_token_singular', 'Widget'),
        'token_plural': get_setting('currency_token_plural', 'Widgets'),
        'token_logo': get_setting('currency_token_logo', ''),
        'token_logo_type': get_setting('currency_token_logo_type', 'emoji'),
        'token_emoji': get_setting('currency_token_emoji', '\U0001fa9f'),
        'gbp_value': float(get_setting('currency_gbp_value', '0.01') or '0.01'),
        'currency_code': get_setting('currency_code', 'GBP'),
    }


def save_currency_settings(token_name, token_singular, token_plural, gbp_value,
                            logo_path=None, logo_type=None, emoji=None, currency_code=None):
    set_setting('currency_token_name', token_name)
    set_setting('currency_token_singular', token_singular)
    set_setting('currency_token_plural', token_plural)
    set_setting('currency_gbp_value', str(gbp_value))
    if currency_code is not None:
        set_setting('currency_code', currency_code)
    if logo_path is not None:
        set_setting('currency_token_logo', logo_path)
    if logo_type is not None:
        set_setting('currency_token_logo_type', logo_type)
    if emoji is not None:
        set_setting('currency_token_emoji', emoji)


# --- Storage helpers ---

def get_storage_config():
    return {
        'data_dir': get_setting('storage_data_dir', DATA_DIR),
        'previous_dir': get_setting('storage_previous_dir', ''),
        'moved': get_setting('storage_moved', '0') == '1',
    }


def set_storage_config(data_dir, previous_dir=None, moved=False):
    set_setting('storage_data_dir', data_dir)
    if previous_dir is not None:
        set_setting('storage_previous_dir', previous_dir)
    set_setting('storage_moved', '1' if moved else '0')


# --- Drop chore helpers ---

def create_drop_chore(name, initial_points, decay_per_minute, chore_id=None,
                      chore_emoji='', chore_image='', created_by=None, expires_minutes=60):
    db = get_db()
    expires_at = clock.to_utc_text(clock.utc_now() + timedelta(minutes=expires_minutes))
    cursor = db.execute(
        """INSERT INTO drop_chores (chore_id, name, chore_emoji, chore_image, initial_points, current_points,
           decay_per_minute, posted_at, expires_at, status, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, 'available', ?)""",
        (chore_id, name, chore_emoji, chore_image, initial_points, initial_points,
         decay_per_minute, expires_at, created_by)
    )
    db.commit()
    return cursor.lastrowid


def get_active_drop_chores():
    db = get_db()
    return db.execute(
        """SELECT * FROM drop_chores WHERE status='available' ORDER BY posted_at DESC"""
    ).fetchall()


def get_assigned_drop_chores(user_id):
    db = get_db()
    return db.execute(
        """SELECT * FROM drop_chores
           WHERE status='assigned' AND assigned_to=?
           ORDER BY posted_at DESC""",
        (user_id,)
    ).fetchall()


def get_drop_chore(drop_id):
    db = get_db()
    return db.execute("SELECT * FROM drop_chores WHERE id=?", (drop_id,)).fetchone()


def complete_assigned_drop_chore(drop_id, user_id):
    """Complete a drop chore that was auto-assigned to this child."""
    db = get_db()
    drop = db.execute(
        """SELECT * FROM drop_chores
           WHERE id=? AND assigned_to=? AND status='assigned'""",
        (drop_id, user_id)
    ).fetchone()
    if not drop:
        return None

    log = None
    if drop['chore_id']:
        chore = get_chore(drop['chore_id'])
        if chore and chore['is_active']:
            try:
                log = complete_chore(user_id, drop['chore_id'])
            except ValueError as exc:
                if 'already completed' not in str(exc):
                    raise

    db.execute(
        """UPDATE drop_chores
           SET status='completed', claimed_by=COALESCE(claimed_by, ?)
           WHERE id=? AND assigned_to=? AND status='assigned'""",
        (user_id, drop_id, user_id)
    )
    db.commit()
    return {'drop': get_drop_chore(drop_id), 'log': log}


def claim_drop_chore(drop_id, user_id):
    db = get_db()
    drop = db.execute("SELECT * FROM drop_chores WHERE id=? AND status='available'", (drop_id,)).fetchone()
    if not drop:
        return None
    db.execute(
        "UPDATE drop_chores SET status='claimed', claimed_by=?, current_points=? WHERE id=?",
        (user_id, drop['current_points'], drop_id)
    )
    db.commit()
    return drop


def update_drop_chore_points():
    """Decay available drop chores and auto-assign expired/zero-value drops."""
    db = get_db()
    now = clock.utc_now()
    drops = db.execute("SELECT * FROM drop_chores WHERE status='available'").fetchall()
    results = []
    for drop in drops:
        posted = clock.parse_utc(drop['posted_at'])
        elapsed_min = (now - posted).total_seconds() / 60
        new_points = max(0, drop['initial_points'] - (elapsed_min * drop['decay_per_minute']))
        expired = bool(drop['expires_at'] and clock.parse_utc(drop['expires_at']) <= now)
        if new_points > 0 and not expired:
            db.execute(
                "UPDATE drop_chores SET current_points=? WHERE id=?",
                (round(new_points, 2), drop['id'])
            )
            continue
        child = db.execute(
            """SELECT id FROM users
               WHERE role='child' AND is_active=1 AND status='active'
               ORDER BY RANDOM() LIMIT 1"""
        ).fetchone()
        if child:
            db.execute(
                "UPDATE drop_chores SET status='assigned', assigned_to=?, current_points=0 WHERE id=?",
                (child['id'], drop['id'])
            )
            if drop['chore_id']:
                db.execute(
                    """INSERT INTO chore_assignments (chore_id, user_id, day_of_week)
                       SELECT ?, ?, NULL
                       WHERE EXISTS (SELECT 1 FROM chores WHERE id=?)
                         AND NOT EXISTS (
                             SELECT 1 FROM chore_assignments
                             WHERE chore_id=? AND user_id=? AND day_of_week IS NULL
                         )""",
                    (drop['chore_id'], child['id'], drop['chore_id'],
                     drop['chore_id'], child['id'])
                )
            results.append({
                'drop_id': drop['id'], 'assigned_to': child['id'], 'points': 0,
                'name': drop['name'], 'created_by': drop['created_by'],
                'chore_id': drop['chore_id'], 'expired': expired,
            })
        else:
            db.execute(
                "UPDATE drop_chores SET status='expired', current_points=0 WHERE id=?",
                (drop['id'],)
            )
    db.commit()
    for result in results:
        reason = 'expired' if result['expired'] else 'timer reached zero'
        log_activity(
            result['assigned_to'], 'drop_chore_auto_assigned',
            f"Auto-assigned drop chore: {result['name']} ({reason})"
        )
        create_broadcast_alert(
            'Drop chore assigned',
            f"{result['name']} was assigned to you after the {reason}.",
            kind='general', child_id=result['assigned_to'],
            icon='bi-droplet-fill', color='#f59e0b',
            created_by=result['created_by']
        )
    return results


def delete_drop_chore(drop_id):
    db = get_db()
    db.execute("DELETE FROM drop_chores WHERE id=?", (drop_id,))
    db.commit()


# --- Financial reporting helpers (Phase 13) ---

def _report_range(start_date=None, end_date=None):
    return reporting.normalize_range(start_date, end_date)


def get_ledger_entries(user_id=None, start_date=None, end_date=None, types=None,
                       limit=5000):
    start_date, end_date = _report_range(start_date, end_date)
    db = get_db()
    params = []
    query = """SELECT p.*, u.name AS user_name, u.color AS user_color
               FROM payments p
               JOIN users u ON p.user_id=u.id
               WHERE 1=1"""
    if user_id:
        query += " AND p.user_id=?"
        params.append(int(user_id))
    if start_date:
        query += " AND date(p.created_at)>=?"
        params.append(start_date)
    if end_date:
        query += " AND date(p.created_at)<=?"
        params.append(end_date)
    if types:
        type_list = tuple(types)
        placeholders = ','.join('?' for _ in type_list)
        query += f" AND p.type IN ({placeholders})"
        params.extend(type_list)
    query += " ORDER BY p.created_at ASC, p.id ASC LIMIT ?"
    params.append(max(1, int(limit)))
    rows = [dict(row) for row in db.execute(query, params).fetchall()]
    running = {}
    for row in rows:
        balance = round(running.get(row['user_id'], 0.0) + float(row['amount'] or 0), 2)
        running[row['user_id']] = balance
        row['running_balance'] = balance
        row['type_label'] = reporting.type_label(row['type'])
    rows.reverse()
    return rows


def get_financial_summary(start_date=None, end_date=None, user_id=None):
    entries = get_ledger_entries(
        user_id=user_id, start_date=start_date, end_date=end_date, limit=100000
    )
    summary = {
        'income': 0.0,
        'expenses': 0.0,
        'savings_in': 0.0,
        'savings_out': 0.0,
        'net': 0.0,
        'transaction_count': len(entries),
        'by_type': [],
        'by_child': [],
    }
    by_type = {}
    by_child = {}
    for entry in entries:
        ptype = entry['type']
        amount = round(float(entry['amount'] or 0), 2)
        summary['net'] = round(summary['net'] + amount, 2)
        if ptype in reporting.INCOME_TYPES:
            summary['income'] = round(summary['income'] + amount, 2)
        if ptype in reporting.EXPENSE_TYPES:
            summary['expenses'] = round(summary['expenses'] + abs(amount), 2)
        if ptype in reporting.SAVINGS_IN_TYPES:
            summary['savings_in'] = round(summary['savings_in'] + abs(amount), 2)
        if ptype in reporting.SAVINGS_OUT_TYPES:
            summary['savings_out'] = round(summary['savings_out'] + abs(amount), 2)
        type_entry = by_type.setdefault(ptype, {
            'type': ptype,
            'label': reporting.type_label(ptype),
            'total': 0.0,
            'count': 0,
        })
        type_entry['total'] = round(type_entry['total'] + amount, 2)
        type_entry['count'] += 1
        child = by_child.setdefault(entry['user_id'], {
            'user_id': entry['user_id'],
            'name': entry['user_name'],
            'color': entry.get('user_color', ''),
            'income': 0.0,
            'expenses': 0.0,
            'net': 0.0,
            'count': 0,
        })
        child['net'] = round(child['net'] + amount, 2)
        child['count'] += 1
        if ptype in reporting.INCOME_TYPES:
            child['income'] = round(child['income'] + amount, 2)
        if ptype in reporting.EXPENSE_TYPES:
            child['expenses'] = round(child['expenses'] + abs(amount), 2)
    summary['by_type'] = sorted(
        by_type.values(), key=lambda item: abs(item['total']), reverse=True
    )
    summary['by_child'] = sorted(
        by_child.values(), key=lambda item: item['name'].lower()
    )
    return summary


def get_savings_report(user_id=None, start_date=None, end_date=None, limit=5000):
    start_date, end_date = _report_range(start_date, end_date)
    db = get_db()
    params = []
    query = """SELECT t.*, u.name AS user_name, u.color AS user_color,
                      v.name AS vault_name
               FROM savings_vault_transactions t
               JOIN users u ON t.user_id=u.id
               LEFT JOIN savings_vaults v ON t.vault_id=v.id
               WHERE 1=1"""
    if user_id:
        query += " AND t.user_id=?"
        params.append(int(user_id))
    if start_date:
        query += " AND date(t.created_at)>=?"
        params.append(start_date)
    if end_date:
        query += " AND date(t.created_at)<=?"
        params.append(end_date)
    query += " ORDER BY t.created_at DESC, t.id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    return [dict(row) for row in db.execute(query, params).fetchall()]


def get_bills_report(user_id=None, start_date=None, end_date=None, limit=5000):
    start_date, end_date = _report_range(start_date, end_date)
    db = get_db()
    params = []
    query = """SELECT o.*, u.name AS user_name, u.color AS user_color
               FROM bill_occurrences o
               JOIN users u ON o.user_id=u.id
               WHERE 1=1"""
    if user_id:
        query += " AND o.user_id=?"
        params.append(int(user_id))
    if start_date:
        query += " AND date(o.due_date)>=?"
        params.append(start_date)
    if end_date:
        query += " AND date(o.due_date)<=?"
        params.append(end_date)
    query += " ORDER BY o.due_date DESC, o.id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    return [dict(row) for row in db.execute(query, params).fetchall()]


def get_marketplace_report(user_id=None, start_date=None, end_date=None, limit=5000):
    start_date, end_date = _report_range(start_date, end_date)
    db = get_db()
    params = []
    query = """SELECT o.*, u.name AS user_name, u.color AS user_color
               FROM marketplace_orders o
               JOIN users u ON o.user_id=u.id
               WHERE 1=1"""
    if user_id:
        query += " AND o.user_id=?"
        params.append(int(user_id))
    if start_date:
        query += " AND date(o.requested_at)>=?"
        params.append(start_date)
    if end_date:
        query += " AND date(o.requested_at)<=?"
        params.append(end_date)
    query += " ORDER BY o.requested_at DESC, o.id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    return [dict(row) for row in db.execute(query, params).fetchall()]


def get_report_data(kind, user_id=None, start_date=None, end_date=None):
    kind = reporting.normalize_kind(kind)
    if kind == 'ledger':
        return get_ledger_entries(
            user_id=user_id, start_date=start_date, end_date=end_date
        )
    if kind == 'summary':
        return get_financial_summary(
            start_date=start_date, end_date=end_date, user_id=user_id
        )
    if kind == 'savings':
        return get_savings_report(
            user_id=user_id, start_date=start_date, end_date=end_date
        )
    if kind == 'bills':
        return get_bills_report(
            user_id=user_id, start_date=start_date, end_date=end_date
        )
    if kind == 'marketplace':
        return get_marketplace_report(
            user_id=user_id, start_date=start_date, end_date=end_date
        )
    raise ValueError('Choose a valid report type.')


# --- Live event helpers (Phase 14) ---

LIVE_EVENT_RETENTION = 500


def record_live_event(event_type, title='', body='', payload=None,
                      user_id=None, child_id=None):
    db = get_db()
    payload_data = payload or {}
    cursor = db.execute(
        """INSERT INTO live_events
           (event_type, title, body, payload, user_id, child_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            str(event_type or 'message')[:40], (title or '')[:160],
            (body or '')[:500], json.dumps(payload_data, default=str),
            user_id, child_id,
        )
    )
    db.commit()
    event_id = cursor.lastrowid
    db.execute(
        "DELETE FROM live_events WHERE id<?",
        (max(1, event_id - LIVE_EVENT_RETENTION),)
    )
    db.commit()
    row = db.execute(
        "SELECT * FROM live_events WHERE id=?", (event_id,)
    ).fetchone()
    envelope = {
        'id': row['id'],
        'title': row['title'],
        'body': row['body'],
        'payload': payload_data,
        'user_id': row['user_id'],
        'child_id': row['child_id'],
        'created_at': row['created_at'],
    }
    events.publish(str(event_type or 'message'), envelope)
    return row


def _live_event_dict(row):
    data = dict(row)
    try:
        data['payload'] = json.loads(data.get('payload') or '{}')
    except (TypeError, ValueError):
        data['payload'] = {}
    return data


def get_live_events(after_id=0, limit=50):
    rows = get_db().execute(
        """SELECT * FROM live_events WHERE id>?
           ORDER BY id ASC LIMIT ?""",
        (max(0, int(after_id or 0)), max(1, int(limit)))
    ).fetchall()
    return [_live_event_dict(row) for row in rows]


def get_recent_live_events(limit=25):
    rows = get_db().execute(
        "SELECT * FROM live_events ORDER BY id DESC LIMIT ?",
        (max(1, int(limit)),)
    ).fetchall()
    return [_live_event_dict(row) for row in reversed(rows)]


def get_latest_live_event_id():
    row = get_db().execute(
        "SELECT COALESCE(MAX(id), 0) AS latest FROM live_events"
    ).fetchone()
    return int(row['latest'] if row else 0)


# --- Snapshot and rollback helpers (Phase 15) ---

SNAPSHOT_KINDS = ('manual', 'auto', 'pre_update', 'pre_restore')


def _snapshot_dir():
    path = os.path.join(DATA_DIR, 'snapshots')
    os.makedirs(path, exist_ok=True)
    return path


def _normalise_snapshot_kind(kind):
    value = (kind or 'manual').strip().lower()
    if value not in SNAPSHOT_KINDS:
        raise ValueError('Choose a valid snapshot type.')
    return value


def _snapshot_path(filename):
    safe = os.path.basename(filename or '')
    if not safe or safe != filename:
        raise ValueError('Invalid snapshot file.')
    return os.path.join(_snapshot_dir(), safe)


def _file_checksum(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_dict(row):
    data = dict(row)
    try:
        path = _snapshot_path(data['filename'])
        data['path'] = path
        data['file_exists'] = os.path.exists(path)
        data['size_text'] = format_file_size(data.get('size_bytes', 0))
    except ValueError:
        data['path'] = ''
        data['file_exists'] = False
        data['size_text'] = format_file_size(data.get('size_bytes', 0))
    return data


def format_file_size(value):
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        size = 0
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024


def create_system_snapshot(label=None, kind='manual', created_by=None, note=''):
    if not os.path.exists(DB_PATH):
        raise ValueError('There is no database to snapshot yet.')
    kind = _normalise_snapshot_kind(kind)
    label = (label or '').strip()
    if len(label) > 120:
        raise ValueError('Snapshot label must be 120 characters or fewer.')
    if not label:
        label = f"Snapshot {datetime.now().strftime('%d %b %Y, %H:%M')}"
    filename = (
        f"snapshot-{datetime.now().strftime('%Y%m%d-%H%M%S')}-"
        f"{secrets.token_hex(4)}.db"
    )
    path = _snapshot_path(filename)
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    size = os.path.getsize(path)
    checksum = _file_checksum(path)
    db = get_db()
    cursor = db.execute(
        """INSERT INTO system_snapshots
           (label, filename, kind, size_bytes, checksum, note, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (label, filename, kind, size, checksum, (note or '').strip()[:500],
         created_by)
    )
    db.commit()
    return get_system_snapshot(cursor.lastrowid)


def get_system_snapshot(snapshot_id):
    row = get_db().execute(
        "SELECT * FROM system_snapshots WHERE id=?", (snapshot_id,)
    ).fetchone()
    return _snapshot_dict(row) if row else None


def get_system_snapshots(limit=100, kind=None):
    db = get_db()
    params = []
    query = "SELECT * FROM system_snapshots WHERE 1=1"
    if kind:
        query += " AND kind=?"
        params.append(_normalise_snapshot_kind(kind))
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    return [_snapshot_dict(row) for row in db.execute(query, params).fetchall()]


def restore_system_snapshot(snapshot_id, created_by=None, safety=True):
    snapshot = get_system_snapshot(snapshot_id)
    if not snapshot:
        raise ValueError('Snapshot not found.')
    if not snapshot['file_exists']:
        raise ValueError('Snapshot file is missing.')
    if safety:
        create_system_snapshot(
            label=f"Before restore #{snapshot_id}", kind='pre_restore',
            created_by=created_by,
        )
    catalog = [
        dict(row) for row in get_db().execute(
            "SELECT * FROM system_snapshots"
        ).fetchall()
    ]
    from flask import g, has_app_context
    if has_app_context() and 'db' in g:
        g.db.close()
        g.pop('db', None)
    src = sqlite3.connect(snapshot['path'])
    dst = sqlite3.connect(DB_PATH)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    db = get_db()
    try:
        existing = {
            row['id'] for row in db.execute(
                "SELECT id FROM system_snapshots"
            ).fetchall()
        }
        for item in catalog:
            if item['id'] in existing:
                continue
            db.execute(
                """INSERT OR IGNORE INTO system_snapshots
                   (id, label, filename, kind, size_bytes, checksum, note,
                    status, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item['id'], item['label'], item['filename'], item['kind'],
                 item['size_bytes'], item['checksum'], item['note'],
                 item['status'], item['created_by'], item['created_at'])
            )
        db.commit()
    except sqlite3.OperationalError:
        pass
    return get_system_snapshot(snapshot_id) or snapshot


def delete_system_snapshot(snapshot_id):
    snapshot = get_system_snapshot(snapshot_id)
    if not snapshot:
        raise ValueError('Snapshot not found.')
    if snapshot['file_exists']:
        try:
            os.remove(snapshot['path'])
        except OSError:
            pass
    db = get_db()
    db.execute("DELETE FROM system_snapshots WHERE id=?", (snapshot_id,))
    db.commit()
    return snapshot


def prune_system_snapshots(keep=10, kind=None):
    snapshots = get_system_snapshots(limit=10000, kind=kind)
    keep = max(0, int(keep))
    removed = []
    for snapshot in snapshots[keep:]:
        removed.append(delete_system_snapshot(snapshot['id']))
    return removed


def get_snapshot_storage_usage():
    snapshots = get_system_snapshots(limit=10000)
    total = sum(int(item.get('size_bytes') or 0) for item in snapshots)
    return {'count': len(snapshots), 'bytes': total, 'size_text': format_file_size(total)}


# --- Security audit helpers (Phase 16) ---

def get_failed_login_count(hours=24):
    row = get_db().execute(
        """SELECT COUNT(*) AS cnt FROM login_audit
           WHERE success=0 AND created_at>=datetime('now', ?)""",
        (f'-{max(1, int(hours))} hours',)
    ).fetchone()
    return int(row['cnt'] if row else 0)
