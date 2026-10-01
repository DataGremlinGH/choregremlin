"""
ChoreGremlin - SQLite Database Module
Handles schema initialization and all data access.
"""

import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

_DATA_DIR = os.environ.get('CHOREGREMLIN_DATA_DIR', '')
if _DATA_DIR:
    DB_PATH = os.path.join(_DATA_DIR, 'choregremlin.db')
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'choregremlin.db')

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
    color TEXT NOT NULL DEFAULT '#00d9ff',
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
    status TEXT NOT NULL DEFAULT 'in_progress',
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
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
]


def init_db():
    """Initialize the database schema and run migrations."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    for sql in MIGRATIONS:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
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

def create_user(name, email, password, role='parent', pin=None, photo_path=None,
                   surname=None, nickname=None, date_of_birth=None, color='#00d9ff', status='active',
                   username=None):
    db = get_db()
    pw_hash = generate_password_hash(password) if password else None
    cursor = db.execute(
        """INSERT INTO users (name, surname, nickname, username, email, password_hash, role, pin, photo_path, color, date_of_birth, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, surname, nickname, username, email, pw_hash, role, pin, photo_path, color, date_of_birth, status)
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
               'photo_path', 'is_active', 'color', 'date_of_birth', 'status'}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
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
    db = get_db()
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(password), user_id))
    db.commit()


def set_pin(user_id, pin):
    db = get_db()
    db.execute("UPDATE users SET pin=? WHERE id=?", (pin if pin else None, user_id))
    db.commit()


# --- Login audit helpers ---

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

def check_lockout(email, ip_address, max_attempts=5, lockout_minutes=15):
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


def record_failed_attempt(email, ip_address, max_attempts=5, lockout_minutes=15):
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


def get_backup_code_count(user_id):
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM backup_codes WHERE user_id=? AND used=0",
        (user_id,)
    ).fetchone()
    return row['cnt'] if row else 0


# --- Chore helpers ---

def create_chore(name, icon, pay_amount, description='', is_active=1,
               chore_emoji='', chore_image='', repeat_frequency='daily', due_days='0,1,2,3,4,5,6',
               single_child_only=0):
    db = get_db()
    cursor = db.execute(
        """INSERT INTO chores (name, icon, pay_amount, description, is_active, chore_emoji, chore_image, repeat_frequency, due_days, single_child_only)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, icon, pay_amount, description, is_active, chore_emoji, chore_image, repeat_frequency, due_days, single_child_only)
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
    allowed = {'name', 'icon', 'pay_amount', 'description', 'is_active', 'chore_emoji', 'chore_image', 'repeat_frequency', 'due_days', 'single_child_only'}
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

def is_chore_in_progress_by_others(chore_id, user_id):
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM chore_logs WHERE chore_id=? AND status='in_progress' AND user_id!=?",
        (chore_id, user_id)
    ).fetchone()
    return row['cnt'] > 0 if row else False


def start_chore(user_id, chore_id):
    db = get_db()
    chore = db.execute("SELECT pay_amount FROM chores WHERE id=?", (chore_id,)).fetchone()
    pay = chore['pay_amount'] if chore else 0
    cursor = db.execute(
        "INSERT INTO chore_logs (user_id, chore_id, status, earned_amount) VALUES (?, ?, 'in_progress', ?)",
        (user_id, chore_id, pay)
    )
    db.commit()
    return cursor.lastrowid


def finish_chore(log_id):
    db = get_db()
    log = db.execute("SELECT * FROM chore_logs WHERE id=?", (log_id,)).fetchone()
    if not log or log['status'] != 'in_progress':
        return None
    db.execute(
        "UPDATE chore_logs SET status='completed', finished_at=datetime('now') WHERE id=?",
        (log_id,)
    )
    db.commit()
    return log


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
               ORDER BY cl.started_at DESC""",
            (user_id,)
        ).fetchall()
    return db.execute(
        """SELECT cl.*, c.name as chore_name, c.icon as chore_icon, c.pay_amount,
           u.name as user_name, u.photo_path as user_photo
           FROM chore_logs cl
           JOIN chores c ON cl.chore_id = c.id
           JOIN users u ON cl.user_id = u.id
           WHERE cl.status='in_progress'
           ORDER BY cl.started_at DESC"""
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

def create_payment(user_id, amount, ptype='payout', description='', log_id=None, created_by=None):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO payments (user_id, amount, type, description, log_id, created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, amount, ptype, description, log_id, created_by)
    )
    db.commit()
    return cursor.lastrowid


def get_payments(user_id=None, month=None):
    db = get_db()
    params = []
    query = "SELECT p.*, u.name as user_name FROM payments p JOIN users u ON p.user_id=u.id WHERE 1=1"
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


def delete_payment(payment_id):
    db = get_db()
    db.execute("DELETE FROM payments WHERE id=?", (payment_id,))
    db.commit()


# --- Settings helpers ---

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


# --- Retention helpers ---

def cleanup_old_records(retention_days=365):
    """Delete chore logs and activity entries older than retention_days.
    Returns a dict with counts of deleted rows."""
    db = get_db()
    from datetime import datetime as dt, timedelta
    cutoff = (dt.now() - timedelta(days=retention_days)).strftime('%Y-%m-%d %H:%M:%S')

    r1 = db.execute(
        "DELETE FROM chore_logs WHERE status='completed' AND finished_at < ?",
        (cutoff,)
    )
    chore_deleted = r1.rowcount

    r2 = db.execute(
        "DELETE FROM chore_logs WHERE status='in_progress' AND started_at < ?",
        (cutoff,)
    )
    stale_deleted = r2.rowcount

    r3 = db.execute(
        "DELETE FROM activity_log WHERE created_at < ?",
        (cutoff,)
    )
    activity_deleted = r3.rowcount

    r4 = db.execute(
        "DELETE FROM payments WHERE log_id IS NOT NULL AND log_id NOT IN (SELECT id FROM chore_logs)"
    )
    orphan_payments = r4.rowcount

    db.commit()
    return {
        'chore_logs': chore_deleted,
        'stale_logs': stale_deleted,
        'activity': activity_deleted,
        'orphan_payments': orphan_payments,
    }


def get_retention_stats():
    """Get counts of records by age for display."""
    db = get_db()
    total_logs = db.execute("SELECT COUNT(*) as cnt FROM chore_logs").fetchone()['cnt']
    total_payments = db.execute("SELECT COUNT(*) as cnt FROM payments").fetchone()['cnt']
    total_activity = db.execute("SELECT COUNT(*) as cnt FROM activity_log").fetchone()['cnt']

    from datetime import datetime as dt, timedelta
    cutoff = (dt.now() - timedelta(days=365)).strftime('%Y-%m-%d %H:%M:%S')
    old_logs = db.execute(
        "SELECT COUNT(*) as cnt FROM chore_logs WHERE finished_at < ?",
        (cutoff,)
    ).fetchone()['cnt']

    return {
        'total_logs': total_logs,
        'total_payments': total_payments,
        'total_activity': total_activity,
        'old_logs': old_logs,
        'retention_days': 365,
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
    }


def save_currency_settings(token_name, token_singular, token_plural, gbp_value,
                            logo_path=None, logo_type=None, emoji=None):
    set_setting('currency_token_name', token_name)
    set_setting('currency_token_singular', token_singular)
    set_setting('currency_token_plural', token_plural)
    set_setting('currency_gbp_value', str(gbp_value))
    if logo_path is not None:
        set_setting('currency_token_logo', logo_path)
    if logo_type is not None:
        set_setting('currency_token_logo_type', logo_type)
    if emoji is not None:
        set_setting('currency_token_emoji', emoji)


# --- Storage helpers ---

def get_storage_config():
    return {
        'data_dir': get_setting('storage_data_dir', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'instance')),
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
    from datetime import datetime as dt, timedelta
    expires_at = (dt.now() + timedelta(minutes=expires_minutes)).isoformat()
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


def get_drop_chore(drop_id):
    db = get_db()
    return db.execute("SELECT * FROM drop_chores WHERE id=?", (drop_id,)).fetchone()


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
    """Decay all available drop chores. Auto-assign any that reach zero."""
    db = get_db()
    from datetime import datetime as dt
    drops = db.execute("SELECT * FROM drop_chores WHERE status='available'").fetchall()
    results = []
    for drop in drops:
        posted = dt.fromisoformat(drop['posted_at'])
        elapsed_min = (dt.now() - posted).total_seconds() / 60
        new_points = max(0, drop['initial_points'] - (elapsed_min * drop['decay_per_minute']))
        if new_points <= 0:
            children = db.execute(
                "SELECT id FROM users WHERE role='child' AND is_active=1 ORDER BY RANDOM() LIMIT 1"
            ).fetchall()
            if children:
                child = children[0]
                db.execute(
                    "UPDATE drop_chores SET status='assigned', assigned_to=?, current_points=0 WHERE id=?",
                    (child['id'], drop['id'])
                )
                results.append({'drop_id': drop['id'], 'assigned_to': child['id'], 'points': 0})
            else:
                db.execute("UPDATE drop_chores SET current_points=0 WHERE id=?", (drop['id'],))
        else:
            db.execute("UPDATE drop_chores SET current_points=? WHERE id=?", (round(new_points, 2), drop['id']))
    db.commit()
    return results


def delete_drop_chore(drop_id):
    db = get_db()
    db.execute("DELETE FROM drop_chores WHERE id=?", (drop_id,))
    db.commit()
