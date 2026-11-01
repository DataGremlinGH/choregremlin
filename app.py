"""
ChoreGremlin - Flask Application
The little gremlin that gets the chores done.
A self-hosted family chore & allowance tracker for Raspberry Pi.
"""

import os
import io
import json
import socket
import sqlite3
import secrets
import hashlib
import base64
import time
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    jsonify, send_from_directory, g, flash, abort, make_response
)
from werkzeug.utils import secure_filename
from PIL import Image

import db as db_module
from uploads import save_image, UploadError
import clock
from flask_wtf.csrf import CSRFProtect
from registry import NAV_ITEMS, SETTINGS

app = Flask(__name__, instance_relative_config=True)
app.jinja_env.globals['NAV_ITEMS'] = NAV_ITEMS
app.jinja_env.filters['localtime'] = clock.format_local
def _load_secret_key():
    """Return a SECRET_KEY that survives restarts (kept beside the database, outside git)."""
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key
    key_path = os.path.join(os.path.dirname(db_module.DB_PATH), 'secret_key')
    if os.path.exists(key_path):
        with open(key_path) as f:
            return f.read().strip()
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    key = secrets.token_hex(32)
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(key)
    return key


app.config['SECRET_KEY'] = _load_secret_key()
CSRFProtect(app)


@app.errorhandler(UploadError)
def handle_upload_error(error):
    flash(str(error), 'danger')
    return redirect(request.referrer or url_for('dashboard'))
app.config['UPLOAD_FOLDER'] = os.path.join(app.static_folder, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8MB
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('CHOREGREMLIN_HTTPS') == '1'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}

DEFAULT_PORT = 8473

app.teardown_appcontext(db_module.close_db)

# Initialize database on import
db_module.init_db()


# --- Decorators ---

def require_role(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not db_module.is_setup_complete():
                return redirect(url_for('setup'))
            uid = session.get('user_id')
            if not uid:
                return redirect(url_for('login'))
            user = db_module.get_user(uid)
            if not user or not user['is_active']:
                session.clear()
                return redirect(url_for('login'))
            if roles and user['role'] not in roles:
                abort(403)
            g.user = user
            return f(*args, **kwargs)
        return wrapper
    return decorator


def kiosk_mode():
    """Decorator for kiosk routes - child must be logged in via session."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not db_module.is_setup_complete():
                return redirect(url_for('setup'))
            child_id = session.get('kiosk_child_id')
            if not child_id:
                return redirect(url_for('kiosk_login'))
            child = db_module.get_user(child_id)
            if not child or child['role'] != 'child' or not child['is_active']:
                session.pop('kiosk_child_id', None)
                return redirect(url_for('kiosk_login'))
            g.child = child
            return f(*args, **kwargs)
        return wrapper
    return decorator


# --- Utilities ---

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def fmt_duration(started, finished=None):
    try:
        s = datetime.fromisoformat(started.replace('Z', '+00:00')) if isinstance(started, str) else started
        if finished:
            f = datetime.fromisoformat(finished.replace('Z', '+00:00')) if isinstance(finished, str) else finished
        else:
            f = datetime.now()
        delta = f - s
        mins = int(delta.total_seconds() // 60)
        secs = int(delta.total_seconds() % 60)
        return f"{mins}m {secs}s"
    except Exception:
        return "—"


def verify_totp(secret, code):
    """Verify a TOTP code against the secret."""
    try:
        import hmac as hmac_mod
        import struct
        import hashlib as hl
        key = base64.b32decode(secret.upper() + '=' * (-len(secret) % 8))
        counter = int(time.time() // 30)
        for offset in [-1, 0, 1]:
            c = counter + offset
            msg = struct.pack('>Q', c)
            h = hmac_mod.new(key, msg, hl.sha1).digest()
            offset_byte = h[-1] & 0x0F
            otp = struct.unpack('>I', h[offset_byte:offset_byte + 4])[0] & 0x7FFFFFFF
            otp_str = str(otp).zfill(6)[-6:]
            if otp_str == code:
                return True
        return False
    except Exception:
        return False


def generate_totp_secret():
    """Generate a random base32 TOTP secret (compatible with authenticator apps)."""
    import base64
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def generate_totp_uri(secret, email, app_name='ChoreGremlin'):
    """Generate the otpauth URI for QR code."""
    label = f"{app_name}:{email}"
    return f"otpauth://totp/{label}?secret={secret}&issuer={app_name}"


def generate_backup_codes(count=8):
    """Generate one-time backup codes."""
    codes = []
    for _ in range(count):
        code = secrets.token_hex(4).upper()
        codes.append('-'.join([code[:4], code[4:]]))
    return codes


# --- Context processor ---

@app.context_processor
def inject_globals():
    currency = db_module.get_currency_settings()
    return {
        'now': datetime.now(),
        'current_month': datetime.now().strftime('%Y-%m'),
        'app_name': db_module.get_setting('app_name', 'ChoreGremlin'),
        'family_logo': db_module.get_setting('family_logo', ''),
        'currency': currency,
        'token_name': currency['token_name'],
        'token_singular': currency['token_singular'],
        'token_plural': currency['token_plural'],
        'token_emoji': currency['token_emoji'],
        'token_logo': currency['token_logo'],
        'token_logo_type': currency['token_logo_type'],
        'token_icon': ('<img src="/static/' + currency['token_logo'] + '" alt="" style="width:16px;height:16px;vertical-align:middle;">') if currency['token_logo_type'] == 'upload' and currency['token_logo'] else currency['token_emoji'],
        'gbp_value': currency['gbp_value'],
        'remote_access': db_module.get_setting('remote_access_enabled', '0') == '1',
        'theme_color': db_module.get_setting('theme_color', '#00d9ff'),
        'brightness_mode': db_module.get_setting('brightness_mode', 'dark'),
        'wallpaper': db_module.get_setting('wallpaper', ''),
    }


# ====================
# SETUP & AUTH ROUTES
# ====================

@app.route('/')
def index():
    if not db_module.is_setup_complete():
        return redirect(url_for('setup'))
    return redirect(url_for('kiosk_login'))


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if db_module.is_setup_complete():
        return redirect(url_for('index'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm', '').strip()
        app_name = request.form.get('app_name', 'ChoreGremlin').strip()

        if not name or not username or not password:
            flash('All fields are required.', 'danger')
            return render_template('setup.html')
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('setup.html')
        if len(password) < 10:
            flash('Password must be at least 10 characters.', 'danger')
            return render_template('setup.html')

        db_module.init_db()
        db_module.set_setting('app_name', app_name)
        db_module.create_user(name, None, password, role='admin', username=username)
        flash('Admin account created! Please sign in.', 'success')
        return redirect(url_for('login'))
    return render_template('setup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if not db_module.is_setup_complete():
        return redirect(url_for('setup'))
    if request.method == 'POST':
        login_id = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        totp_code = request.form.get('totp_code', '').strip()
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')

        # Check lockout
        is_locked, minutes_left = db_module.check_lockout(login_id, ip_address)
        if is_locked:
            flash(f'Too many failed attempts. Try again in {minutes_left} minute(s).', 'danger')
            db_module.log_login_attempt(login_id, ip_address, False, 'locked_out')
            return render_template('login.html')

        user = db_module.get_user_by_login(login_id)
        if user and db_module.verify_password(user, password):
            # 2FA only required when remote access is enabled
            remote_access = db_module.get_setting('remote_access_enabled', '0') == '1'
            if remote_access:
                totp = db_module.get_totp_secret(user['id'])
                if totp:
                    if not totp_code:
                        db_module.log_login_attempt(login_id, ip_address, True, 'totp_required')
                        return render_template('login.html', require_totp=True, username=login_id)
                    # Verify TOTP
                    if not verify_totp(totp['secret'], totp_code):
                        # Check backup codes
                        code_hash = hashlib.sha256(totp_code.encode()).hexdigest()
                        if not db_module.verify_backup_code(user['id'], code_hash):
                            db_module.log_login_attempt(login_id, ip_address, False, 'invalid_totp')
                            db_module.record_failed_attempt(login_id, ip_address)
                            flash('Invalid authentication code.', 'danger')
                            return render_template('login.html')
            session['user_id'] = user['id']
            session['role'] = user['role']
            db_module.clear_lockout(login_id, ip_address)
            db_module.log_login_attempt(login_id, ip_address, True)
            return redirect(url_for('dashboard'))
        else:
            db_module.log_login_attempt(login_id, ip_address, False, 'invalid_credentials')
            db_module.record_failed_attempt(login_id, ip_address)
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('role', None)
    return redirect(url_for('kiosk_login'))


# ====================
# KIOSK ROUTES
# ====================

@app.route('/kiosk')
def kiosk_login():
    if not db_module.is_setup_complete():
        return redirect(url_for('setup'))
    children = db_module.get_children()
    # If a child is already logged in, go to chores
    child_id = session.get('kiosk_child_id')
    if child_id:
        child = db_module.get_user(child_id)
        if child and child['is_active'] and child['role'] == 'child':
            return redirect(url_for('child_chores'))
    return render_template('kiosk_login.html', children=children)


@app.route('/kiosk/select/<int:child_id>', methods=['GET', 'POST'])
def kiosk_select(child_id):
    child = db_module.get_user(child_id)
    if not child or child['role'] != 'child' or not child['is_active']:
        flash('Child not found.', 'danger')
        return redirect(url_for('kiosk_login'))

    if request.method == 'POST':
        if child['pin']:
            result = db_module.check_kiosk_pin(child, request.form.get('pin', ''))
            if result == 'locked':
                flash('Too many wrong PINs. Please wait a few minutes and try again.', 'danger')
                return render_template('kiosk_pin.html', child=child)
            if result == 'wrong':
                flash('Incorrect PIN. Please try again.', 'danger')
                return render_template('kiosk_pin.html', child=child)
        session['kiosk_child_id'] = child_id
        return redirect(url_for('child_chores'))

    if child['pin']:
        return render_template('kiosk_pin.html', child=child)
    session['kiosk_child_id'] = child_id
    return redirect(url_for('child_chores'))


@app.route('/kiosk/chores')
@kiosk_mode()
def child_chores():
    child = g.child
    assigned_ids = db_module.get_assigned_chore_ids(child['id'])
    if assigned_ids:
        all_chores = db_module.get_all_chores(active_only=True)
        chores = [c for c in all_chores if c['id'] in assigned_ids]
    else:
        chores = db_module.get_all_chores(active_only=True)
    active_logs = db_module.get_active_logs(child['id'])
    active_ids = {log['chore_id'] for log in active_logs}
    other_active_ids = {log['chore_id'] for log in db_module.get_active_logs() if log['user_id'] != child['id']}
    chores = [c for c in chores if not (c['single_child_only'] and c['id'] in other_active_ids)]
    if not child['can_do_hard_chores']:
        chores = [c for c in chores if not c['requires_hard_chores']]
    balance = db_module.get_balance(child['id'])
    month_earnings = db_module.get_monthly_earnings(child['id'])
    my_earnings = month_earnings[0] if month_earnings else None
    return render_template('child_chores.html', child=child, chores=chores,
                           active_logs=active_logs, active_ids=active_ids,
                           balance=balance, my_earnings=my_earnings)


@app.route('/kiosk/start/<int:chore_id>', methods=['POST'])
@kiosk_mode()
def kiosk_start_chore(chore_id):
    child = g.child
    chore = db_module.get_chore(chore_id)
    if not chore or not chore['is_active']:
        flash('Chore not available.', 'danger')
        return redirect(url_for('child_chores'))
    if chore['requires_hard_chores'] and not child['can_do_hard_chores']:
        flash('This chore is for older kids only.', 'warning')
        return redirect(url_for('child_chores'))
    if chore['single_child_only'] and db_module.is_chore_in_progress_by_others(chore_id, child['id']):
        flash('Someone else is already doing this chore.', 'warning')
        return redirect(url_for('child_chores'))
    db_module.start_chore(child['id'], chore_id)
    flash(f'Started: {chore["name"]}', 'success')
    return redirect(url_for('child_chores'))


@app.route('/kiosk/finish/<int:log_id>', methods=['POST'])
@kiosk_mode()
def kiosk_finish_chore(log_id):
    log = db_module.finish_chore(log_id)
    if log:
        db_module.log_activity(log['user_id'], 'finish_chore', 'Completed a chore, pending approval')
        flash(f'Great job! A parent will review your chore soon.', 'success')
    return redirect(url_for('child_chores'))


@app.route('/kiosk/cancel/<int:log_id>', methods=['POST'])
@kiosk_mode()
def kiosk_cancel_chore(log_id):
    db_module.cancel_chore_log(log_id)
    flash('Chore cancelled.', 'info')
    return redirect(url_for('child_chores'))


@app.route('/kiosk/logout')
def kiosk_child_logout():
    session.pop('kiosk_child_id', None)
    return redirect(url_for('kiosk_login'))


# ====================
# ADMIN / PARENT ROUTES
# ====================

@app.route('/dashboard')
@require_role('admin', 'parent')
def dashboard():
    month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    children = db_module.get_children()
    earnings = db_module.get_monthly_earnings(month=month)
    total_earned = db_module.get_total_earned(month)
    chore_count = db_module.get_chore_count(month)
    active_logs = db_module.get_active_logs()
    stat_icons = {
        'earned': db_module.get_setting('stat_icon_earned', ''),
        'chores': db_module.get_setting('stat_icon_chores', ''),
        'progress': db_module.get_setting('stat_icon_progress', ''),
    }
    return render_template('dashboard.html', children=children, earnings=earnings,
                           total_earned=total_earned, chore_count=chore_count,
                           active_logs=active_logs, selected_month=month,
                           stat_icons=stat_icons)


@app.route('/family')
@require_role('admin', 'parent')
def family_dashboard():
    children = db_module.get_children()
    notices = db_module.get_active_notices()
    recent_activity = db_module.get_recent_activity(limit=10)
    upcoming_events = db_module.get_upcoming_events(limit=5)
    status_counts = {row['status']: row['cnt'] for row in db_module.get_children_by_status()}
    active_children = [c for c in children if c['status'] == 'active']
    holiday_children = [c for c in children if c['status'] == 'holiday']
    sick_children = [c for c in children if c['status'] == 'sick']
    return render_template('family_dashboard.html', children=children, notices=notices,
                           recent_activity=recent_activity, upcoming_events=upcoming_events,
                           status_counts=status_counts,
                           active_children=active_children,
                           holiday_children=holiday_children,
                           sick_children=sick_children)


# --- Kids management ---

@app.route('/kids')
@require_role('admin', 'parent')
def manage_kids():
    children = db_module.get_children()
    return render_template('kids.html', children=children)


@app.route('/kids/add', methods=['POST'])
@require_role('admin', 'parent')
def add_kid():
    name = request.form.get('name', '').strip()
    surname = request.form.get('surname', '').strip() or None
    nickname = request.form.get('nickname', '').strip() or None
    pin = request.form.get('pin', '').strip() or None
    date_of_birth = request.form.get('date_of_birth', '').strip() or None
    color = request.form.get('color', '#00d9ff').strip() or '#00d9ff'
    status = request.form.get('status', 'active').strip()
    photo = request.files.get('photo')
    photo_path = save_image(photo, app.config['UPLOAD_FOLDER'], 'child', 400) if photo else None
    if not name:
        flash('First name is required.', 'danger')
        return redirect(url_for('manage_kids'))
    if pin and (len(pin) < 4 or len(pin) > 6 or not pin.isdigit()):
        flash('PIN must be 4 to 6 digits.', 'danger')
        return redirect(url_for('manage_kids'))
    db_module.create_user(name, None, None, role='child', pin=pin, photo_path=photo_path,
                          surname=surname, nickname=nickname, date_of_birth=date_of_birth,
                          color=color, status=status)
    db_module.log_activity(session.get('user_id'), 'add_child', f'Added child: {name}')
    flash(f'Added {name}.', 'success')
    return redirect(url_for('manage_kids'))


@app.route('/kids/<int:kid_id>/edit', methods=['GET', 'POST'])
@require_role('admin', 'parent')
def edit_kid(kid_id):
    child = db_module.get_user(kid_id)
    if not child or child['role'] != 'child':
        flash('Child not found.', 'danger')
        return redirect(url_for('manage_kids'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        surname = request.form.get('surname', '').strip() or None
        nickname = request.form.get('nickname', '').strip() or None
        pin = request.form.get('pin', '').strip() or None
        date_of_birth = request.form.get('date_of_birth', '').strip() or None
        color = request.form.get('color', '#00d9ff').strip() or '#00d9ff'
        status = request.form.get('status', 'active').strip()
        photo = request.files.get('photo')
        wallpaper = request.files.get('wallpaper')
        can_do_hard_chores = 1 if request.form.get('can_do_hard_chores') else 0
        updates = {'name': name, 'surname': surname, 'nickname': nickname,
                   'date_of_birth': date_of_birth, 'color': color, 'status': status,
                   'can_do_hard_chores': can_do_hard_chores}
        if pin and (len(pin) < 4 or len(pin) > 6 or not pin.isdigit()):
            flash('PIN must be 4 to 6 digits.', 'danger')
            return render_template('edit_kid.html', child=child)
        if pin:
            updates['pin'] = pin
        if photo and photo.filename:
            photo_path = save_image(photo, app.config['UPLOAD_FOLDER'], 'child', 400)
            if photo_path:
                updates['photo_path'] = photo_path
        if wallpaper and wallpaper.filename:
            wp_path = save_image(wallpaper, app.config['UPLOAD_FOLDER'], 'wallpaper')
            if wp_path:
                updates['wallpaper'] = wp_path
        db_module.update_user(kid_id, **updates)
        db_module.log_activity(session.get('user_id'), 'edit_child', f'Edited child: {name}')
        flash('Updated child profile.', 'success')
        return redirect(url_for('manage_kids'))
    return render_template('edit_kid.html', child=child)


@app.route('/kids/<int:kid_id>/delete', methods=['POST'])
@require_role('admin')
def delete_kid(kid_id):
    child = db_module.get_user(kid_id)
    db_module.delete_user(kid_id)
    if child:
        db_module.log_activity(session.get('user_id'), 'delete_child', f'Removed child: {child["name"]}')
    flash('Child removed.', 'info')
    return redirect(url_for('manage_kids'))


@app.route('/kids/<int:kid_id>/reset-pin', methods=['POST'])
@require_role('admin')
def reset_pin(kid_id):
    new_pin = request.form.get('pin', '').strip() or None
    if new_pin and (len(new_pin) < 4 or len(new_pin) > 6 or not new_pin.isdigit()):
        flash('PIN must be 4 to 6 digits.', 'danger')
        return redirect(url_for('manage_kids'))
    db_module.set_pin(kid_id, new_pin)
    flash('PIN updated.', 'success')
    return redirect(url_for('manage_kids'))


# --- Chores management ---

@app.route('/chores')
@require_role('admin', 'parent')
def manage_chores():
    chores = db_module.get_all_chores()
    children = db_module.get_children()
    assignments = {}
    for c in chores:
        assignments[c['id']] = [r['user_id'] for r in db_module.get_assignments_for_chore(c['id'])]
    return render_template('chores.html', chores=chores, children=children, assignments=assignments)


@app.route('/chores/add', methods=['POST'])
@require_role('admin', 'parent')
def add_chore():
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', 'bi-list-check')
    pay = float(request.form.get('pay_amount', 0) or 0)
    description = request.form.get('description', '').strip()
    chore_emoji = request.form.get('chore_emoji', '').strip()
    repeat_frequency = request.form.get('repeat_frequency', 'daily').strip()
    due_days = ','.join(request.form.getlist('due_days'))
    if not due_days:
        due_days = '0,1,2,3,4,5,6'
    if not name:
        flash('Chore name is required.', 'danger')
        return redirect(url_for('manage_chores'))
    chore_image = ''
    img_file = request.files.get('chore_image')
    if img_file and img_file.filename:
        chore_image = save_image(img_file, app.config['UPLOAD_FOLDER'], 'chore')
    single_child_only = 1 if request.form.get('single_child_only') else 0
    requires_hard_chores = 1 if request.form.get('requires_hard_chores') else 0
    db_module.create_chore(name, icon, pay, description, chore_emoji=chore_emoji,
                          chore_image=chore_image, repeat_frequency=repeat_frequency, due_days=due_days,
                          single_child_only=single_child_only, requires_hard_chores=requires_hard_chores)
    chore_id = db_module.get_all_chores(active_only=False)[-1]['id']
    user_ids = request.form.getlist('user_ids')
    if user_ids:
        for uid in user_ids:
            db_module.assign_chore(chore_id, int(uid))
    flash(f'Added chore: {name}.', 'success')
    return redirect(url_for('manage_chores'))


@app.route('/chores/<int:chore_id>/edit', methods=['GET', 'POST'])
@require_role('admin', 'parent')
def edit_chore(chore_id):
    chore = db_module.get_chore(chore_id)
    if not chore:
        flash('Chore not found.', 'danger')
        return redirect(url_for('manage_chores'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        icon = request.form.get('icon', 'bi-list-check')
        pay = float(request.form.get('pay_amount', 0) or 0)
        description = request.form.get('description', '').strip()
        is_active = 1 if request.form.get('is_active') else 0
        single_child_only = 1 if request.form.get('single_child_only') else 0
        requires_hard_chores = 1 if request.form.get('requires_hard_chores') else 0
        chore_emoji = request.form.get('chore_emoji', '').strip()
        repeat_frequency = request.form.get('repeat_frequency', 'daily').strip()
        due_days = ','.join(request.form.getlist('due_days'))
        if not due_days:
            due_days = '0,1,2,3,4,5,6'
        updates = dict(name=name, icon=icon, pay_amount=pay, description=description,
                      is_active=is_active, chore_emoji=chore_emoji,
                      repeat_frequency=repeat_frequency, due_days=due_days,
                      single_child_only=single_child_only, requires_hard_chores=requires_hard_chores)
        img_file = request.files.get('chore_image')
        if img_file and img_file.filename:
            updates['chore_image'] = save_image(img_file, app.config['UPLOAD_FOLDER'], 'chore')
        db_module.update_chore(chore_id, **updates)
        flash('Chore updated.', 'success')
        return redirect(url_for('manage_chores'))
    return render_template('edit_chore.html', chore=chore)


@app.route('/chores/<int:chore_id>/delete', methods=['POST'])
@require_role('admin')
def delete_chore_route(chore_id):
    db_module.delete_chore(chore_id)
    flash('Chore deleted.', 'info')
    return redirect(url_for('manage_chores'))


@app.route('/chores/<int:chore_id>/assign', methods=['POST'])
@require_role('admin', 'parent')
def assign_chore_route(chore_id):
    user_ids = request.form.getlist('user_ids')
    # Clear existing assignments
    db = db_module.get_db()
    db.execute("DELETE FROM chore_assignments WHERE chore_id=?", (chore_id,))
    db.commit()
    for uid in user_ids:
        db_module.assign_chore(chore_id, int(uid))
    flash('Assignments updated.', 'success')
    return redirect(url_for('manage_chores'))


# --- Payments ---

@app.route('/payments')
@require_role('admin', 'parent')
def manage_payments():
    month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    child_id = request.args.get('child_id', type=int)
    children = db_module.get_children()
    payments = db_module.get_payments(user_id=child_id, month=month)
    balances = {c['id']: db_module.get_balance(c['id']) for c in children}
    currency = db_module.get_currency_settings()
    gbp_value = currency['gbp_value']
    balances_gbp = {c['id']: round(balances[c['id']] * gbp_value, 2) for c in children}
    total_tokens = sum(balances.values())
    total_gbp = round(total_tokens * gbp_value, 2)
    return render_template('payments.html', children=children, payments=payments,
                           balances=balances, balances_gbp=balances_gbp,
                           gbp_value=gbp_value, total_tokens=total_tokens,
                           total_gbp=total_gbp,
                           selected_month=month, selected_child=child_id)


@app.route('/payments/add', methods=['POST'])
@require_role('admin', 'parent')
def add_payment():
    user_id = int(request.form.get('user_id'))
    amount = round(float(request.form.get('amount', 0)), 2)
    ptype = request.form.get('type', 'payout')
    description = request.form.get('description', '').strip()
    payout_method = request.form.get('payout_method', '').strip()
    if ptype == 'payout':
        amount = -abs(amount)
    else:
        amount = abs(amount)
    amount = round(amount, 2)
    currency = db_module.get_currency_settings()
    token_amt = abs(amount)
    gbp_amt = round(token_amt * currency['gbp_value'], 2)
    db_module.create_payment(user_id, amount, ptype=ptype, description=description,
                              created_by=session.get('user_id'),
                              payout_method=payout_method,
                              token_amount=token_amt, gbp_amount=gbp_amt)
    flash('Payment recorded.', 'success')
    return redirect(url_for('manage_payments'))


@app.route('/payments/<int:payment_id>/delete', methods=['POST'])
@require_role('admin')
def delete_payment_route(payment_id):
    db_module.delete_payment(payment_id)
    flash('Payment deleted.', 'info')
    return redirect(url_for('manage_payments'))


@app.route('/payments/payout-all', methods=['POST'])
@require_role('admin', 'parent')
def payout_all():
    payout_method = request.form.get('payout_method', 'cash').strip()
    if payout_method not in ('cash', 'bank'):
        payout_method = 'cash'
    currency = db_module.get_currency_settings()
    gbp_value = currency['gbp_value']
    children = db_module.get_children()
    paid_count = 0
    for c in children:
        balance = db_module.get_balance(c['id'])
        if balance <= 0:
            continue
        token_amt = balance
        gbp_amt = round(token_amt * gbp_value, 2)
        db_module.create_payment(
            c['id'], -balance, ptype='payout',
            description=f'Payout (End of Month) - {payout_method.title()}',
            created_by=session.get('user_id'),
            payout_method=payout_method,
            token_amount=token_amt,
            gbp_amount=gbp_amt
        )
        paid_count += 1
    if paid_count > 0:
        db_module.log_activity(session.get('user_id'), 'payout_all',
                               f'End of month payout to {paid_count} kids via {payout_method}')
        flash(f'Payout completed for {paid_count} kid(s). All balances reset to 0.', 'success')
    else:
        flash('No kids had a balance to pay out.', 'info')
    return redirect(url_for('manage_payments'))


# --- Logs ---

@app.route('/logs')
@require_role('admin', 'parent')
def view_logs():
    month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    child_id = request.args.get('child_id', type=int)
    children = db_module.get_children()
    logs = db_module.get_completed_logs(user_id=child_id, month=month)
    return render_template('logs.html', logs=logs, children=children,
                           selected_month=month, selected_child=child_id)


# --- Parents (admin only) ---

@app.route('/parents')
@require_role('admin')
def manage_parents():
    parents = db_module.get_all_users(role='parent')
    admins = db_module.get_all_users(role='admin')
    return render_template('parents.html', parents=parents, admins=admins)


@app.route('/parents/add', methods=['POST'])
@require_role('admin')
def add_parent():
    name = request.form.get('name', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'parent')
    if not name or not username or not password:
        flash('All fields are required.', 'danger')
        return redirect(url_for('manage_parents'))
    if len(password) < 10:
        flash('Password must be at least 10 characters.', 'danger')
        return redirect(url_for('manage_parents'))
    try:
        db_module.create_user(name, None, password, role=role, username=username)
        flash(f'Added {role}: {name}.', 'success')
    except Exception:
        flash('Username already in use.', 'danger')
    return redirect(url_for('manage_parents'))


@app.route('/parents/<int:parent_id>/delete', methods=['POST'])
@require_role('admin')
def delete_parent(parent_id):
    admin_count = len(db_module.get_all_users(role='admin'))
    user = db_module.get_user(parent_id)
    if user and user['role'] == 'admin' and admin_count <= 1:
        flash('Cannot delete the last admin.', 'danger')
        return redirect(url_for('manage_parents'))
    db_module.delete_user(parent_id)
    flash('User removed.', 'info')
    return redirect(url_for('manage_parents'))


# --- Family Notices ---

@app.route('/notices')
@require_role('admin', 'parent')
def manage_notices():
    notices = db_module.get_all_notices()
    return render_template('notices.html', notices=notices)


@app.route('/notices/add', methods=['POST'])
@require_role('admin', 'parent')
def add_notice():
    title = request.form.get('title', '').strip()
    body = request.form.get('body', '').strip()
    expires_at = request.form.get('expires_at', '').strip() or None
    if not title:
        flash('Notice title is required.', 'danger')
        return redirect(url_for('manage_notices'))
    db_module.create_notice(title, body, created_by=session.get('user_id'), expires_at=expires_at)
    db_module.log_activity(session.get('user_id'), 'add_notice', f'Notice: {title}')
    flash('Notice posted.', 'success')
    return redirect(url_for('manage_notices'))


@app.route('/notices/<int:notice_id>/delete', methods=['POST'])
@require_role('admin', 'parent')
def delete_notice(notice_id):
    db_module.delete_notice(notice_id)
    flash('Notice removed.', 'info')
    return redirect(url_for('manage_notices'))


# --- Calendar Events ---

@app.route('/events')
@require_role('admin', 'parent')
def manage_events():
    events = db_module.get_all_events()
    return render_template('events.html', events=events)


@app.route('/events/add', methods=['POST'])
@require_role('admin', 'parent')
def add_event():
    title = request.form.get('title', '').strip()
    event_date = request.form.get('event_date', '').strip()
    event_time = request.form.get('event_time', '').strip() or None
    description = request.form.get('description', '').strip()
    if not title or not event_date:
        flash('Title and date are required.', 'danger')
        return redirect(url_for('manage_events'))
    db_module.create_event(title, event_date, description, event_time, created_by=session.get('user_id'))
    db_module.log_activity(session.get('user_id'), 'add_event', f'Event: {title}')
    flash('Event added.', 'success')
    return redirect(url_for('manage_events'))


@app.route('/events/<int:event_id>/delete', methods=['POST'])
@require_role('admin', 'parent')
def delete_event(event_id):
    db_module.delete_event(event_id)
    flash('Event removed.', 'info')
    return redirect(url_for('manage_events'))


# --- Network Settings ---

def get_network_info():
    port = int(db_module.get_setting('app_port', str(DEFAULT_PORT)))
    try:
        hostname = socket.gethostname()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = '127.0.0.1'
        hostname = 'localhost'
    app_url = f"http://{ip}:{port}"
    local_url = f"http://familyhub.local:{port}"
    return {'ip': ip, 'hostname': hostname, 'app_url': app_url, 'local_url': local_url, 'port': port}


@app.route('/network')
@require_role('admin')
def network_settings():
    net = get_network_info()
    remote_access = db_module.get_setting('remote_access_enabled', '0') == '1'
    return render_template('network.html', net=net, remote_access=remote_access)


@app.route('/network/update', methods=['POST'])
@require_role('admin')
def network_update():
    port = request.form.get('port', str(DEFAULT_PORT)).strip()
    try:
        port_num = int(port)
        if port_num < 1024 or port_num > 65535:
            flash('Port must be between 1024 and 65535.', 'danger')
            return redirect(url_for('network_settings'))
    except ValueError:
        flash('Port must be a number.', 'danger')
        return redirect(url_for('network_settings'))
    db_module.set_setting('app_port', str(port_num))
    db_module.log_activity(session.get('user_id'), 'update_port', f'Port changed to {port_num}')
    flash(f'Port set to {port_num}. Restart the service for it to take effect.', 'success')
    return redirect(url_for('network_settings'))


@app.route('/network/qr')
@require_role('admin')
def network_qr():
    import qrcode
    net = get_network_info()
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(net['app_url'])
    qr.make(fit=True)
    img = qr.make_image(fill_color='#0a0e1a', back_color='#00d9ff')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    response = make_response(buf.read())
    response.headers['Content-Type'] = 'image/png'
    response.headers['Cache-Control'] = 'no-cache'
    return response


# --- Password Reset (admin only) ---

@app.route('/parents/<int:parent_id>/reset-password', methods=['POST'])
@require_role('admin')
def reset_password(parent_id):
    password = request.form.get('password', '').strip()
    if len(password) < 10:
        flash('Password must be at least 10 characters.', 'danger')
        return redirect(url_for('manage_parents'))
    db_module.set_password(parent_id, password)
    db_module.log_activity(session.get('user_id'), 'reset_password', f'Reset password for user {parent_id}')
    flash('Password reset.', 'success')
    return redirect(url_for('manage_parents'))


# --- Storage Management ---

@app.route('/storage')
@require_role('admin')
def storage_page():
    import shutil
    storage = db_module.get_storage_config()
    data_dir = os.path.dirname(db_module.DB_PATH)
    if not os.path.exists(data_dir):
        data_dir = storage['data_dir']

    # Current data dir info
    dir_info = {'path': data_dir, 'exists': os.path.exists(data_dir), 'size': 'N/A', 'free': 'N/A'}
    if dir_info['exists']:
        try:
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(data_dir):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    total_size += os.path.getsize(fp)
            dir_info['size'] = format_size(total_size)
        except Exception:
            dir_info['size'] = 'N/A'
        try:
            usage = shutil.disk_usage(os.path.dirname(data_dir))
            dir_info['free'] = format_size(usage.free)
            dir_info['disk_total'] = format_size(usage.total)
        except Exception:
            dir_info['free'] = 'N/A'

    # Detect available drives
    drives = []
    try:
        result = __import__('subprocess').run(['lsblk', '-b', '-d', '-n', '-o', 'NAME,SIZE,MOUNTPOINT,TYPE'],
                                              capture_output=True, text=True, timeout=5)
        for line in result.stdout.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 3 and parts[-1] == 'disk':
                drives.append({'name': '/dev/' + parts[0], 'size': format_size(int(parts[1])) if parts[1].isdigit() else parts[1],
                               'mountpoint': parts[2] if len(parts) > 2 else ''})
    except Exception:
        pass

    return render_template('storage.html', storage=storage, dir_info=dir_info, drives=drives)


@app.route('/storage/move', methods=['POST'])
@require_role('admin')
def storage_move():
    import shutil
    import tempfile
    target = request.form.get('target_path', '').strip()
    if not target:
        flash('Please specify a target path.', 'danger')
        return redirect(url_for('storage_page'))
    if not os.path.isabs(target):
        flash('Path must be an absolute path.', 'danger')
        return redirect(url_for('storage_page'))

    storage = db_module.get_storage_config()
    current_dir = os.path.dirname(db_module.DB_PATH)
    if not os.path.exists(current_dir):
        current_dir = storage['data_dir']

    if os.path.normpath(target) == os.path.normpath(current_dir):
        flash('Target path is the same as the current location.', 'warning')
        return redirect(url_for('storage_page'))

    # Check target is writable
    try:
        os.makedirs(target, exist_ok=True)
        test_file = os.path.join(target, '.write_test')
        with open(test_file, 'w') as f:
            f.write('test')
        os.unlink(test_file)
    except Exception as e:
        flash(f'Target path is not writable: {e}', 'danger')
        return redirect(url_for('storage_page'))

    # Copy all data
    try:
        for item in os.listdir(current_dir):
            src = os.path.join(current_dir, item)
            dst = os.path.join(target, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
    except Exception as e:
        flash(f'Error copying data: {e}', 'danger')
        return redirect(url_for('storage_page'))

    # Verify copy
    try:
        src_files = set(os.listdir(current_dir))
        dst_files = set(os.listdir(target))
        if src_files != dst_files:
            flash('Verification failed: file count mismatch. Old data kept.', 'danger')
            return redirect(url_for('storage_page'))
    except Exception:
        pass

    # Switch over
    db_module.set_storage_config(target, previous_dir=current_dir, moved=True)
    db_module.log_activity(session.get('user_id'), 'storage_move', f'Moved data from {current_dir} to {target}')
    flash(f'Data moved to {target}. Old copy kept at {current_dir} until you confirm deletion.', 'success')
    return redirect(url_for('storage_page'))


@app.route('/storage/confirm-delete', methods=['POST'])
@require_role('admin')
def storage_confirm_delete():
    storage = db_module.get_storage_config()
    old_dir = storage['previous_dir']
    if old_dir and os.path.exists(old_dir):
        import shutil
        shutil.rmtree(old_dir, ignore_errors=True)
        db_module.set_storage_config(storage['data_dir'], previous_dir='', moved=False)
        db_module.log_activity(session.get('user_id'), 'storage_delete_old', f'Deleted old data at {old_dir}')
        flash('Old data copy deleted.', 'success')
    else:
        flash('No old data copy found.', 'info')
    return redirect(url_for('storage_page'))


@app.route('/storage/rollback', methods=['POST'])
@require_role('admin')
def storage_rollback():
    import shutil
    storage = db_module.get_storage_config()
    old_dir = storage['previous_dir']
    current_dir = storage['data_dir']
    if not old_dir or not os.path.exists(old_dir):
        flash('No previous location to roll back to.', 'danger')
        return redirect(url_for('storage_page'))
    db_module.set_storage_config(old_dir, previous_dir='', moved=False)
    db_module.log_activity(session.get('user_id'), 'storage_rollback', f'Rolled back to {old_dir}')
    flash(f'Rolled back to {old_dir}. Restart the service for it to take effect.', 'success')
    return redirect(url_for('storage_page'))


def format_size(bytes_val):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


# --- Currency Management ---

@app.route('/currency')
@require_role('admin')
def currency_page():
    currency = db_module.get_currency_settings()
    return render_template('currency.html', currency=currency)


@app.route('/currency/save', methods=['POST'])
@require_role('admin')
def currency_save():
    token_name = request.form.get('token_name', 'Widgets').strip()
    token_singular = request.form.get('token_singular', 'Widget').strip()
    token_plural = request.form.get('token_plural', 'Widgets').strip()
    gbp_value = request.form.get('gbp_value', '0.01').strip()
    emoji = request.form.get('token_emoji', '\U0001fa9f').strip()
    logo_type = request.form.get('logo_type', 'emoji').strip()

    try:
        gbp_val = float(gbp_value)
    except ValueError:
        flash('GBP value must be a number.', 'danger')
        return redirect(url_for('currency_page'))

    logo_path = None
    if logo_type == 'upload':
        logo_file = request.files.get('logo_file')
        if logo_file and logo_file.filename:
            logo_path = save_currency_logo(logo_file)

    db_module.save_currency_settings(token_name, token_singular, token_plural, gbp_val,
                                      logo_path=logo_path, logo_type=logo_type, emoji=emoji)
    db_module.log_activity(session.get('user_id'), 'update_currency', f'Currency: {token_name}')
    flash('Currency settings saved. New value applies to future conversions only.', 'success')
    return redirect(url_for('currency_page'))


@app.route('/currency/reset-logo', methods=['POST'])
@require_role('admin')
def currency_reset_logo():
    db_module.set_setting('currency_token_logo', '')
    db_module.set_setting('currency_token_logo_type', 'emoji')
    flash('Logo reset to default emoji.', 'info')
    return redirect(url_for('currency_page'))


def save_currency_logo(file):
    if not file or file.filename == '' or not allowed_file(file.filename):
        return None
    ext = file.filename.rsplit('.', 1)[1].lower()
    if ext == 'svg':
        filename = f"currency_logo_{secrets.token_hex(8)}.svg"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(filepath)
        return f"uploads/{filename}"
    filename = f"currency_logo_{secrets.token_hex(8)}.png"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    img = Image.open(file)
    img = img.convert('RGBA')
    img = img.resize((64, 64), Image.LANCZOS)
    img.save(filepath, 'PNG')
    return f"uploads/{filename}"


# --- Security & Remote Access ---

@app.route('/security')
@require_role('admin')
def security_page():
    remote_access = db_module.get_setting('remote_access_enabled', '0') == '1'
    totp_secrets = {}
    for u in db_module.get_all_users():
        totp = db_module.get_totp_secret_unchecked(u['id'])
        if totp:
            totp_secrets[u['id']] = {'enabled': totp['enabled'] == 1, 'backup_count': db_module.get_backup_code_count(u['id'])}
    recent_logins = db_module.get_recent_login_attempts(limit=20)
    return render_template('security.html', remote_access=remote_access,
                           totp_secrets=totp_secrets, users=db_module.get_all_users(),
                           recent_logins=recent_logins)


@app.route('/security/remote-access', methods=['POST'])
@require_role('admin')
def toggle_remote_access():
    enabled = '1' if request.form.get('remote_access') else '0'
    db_module.set_setting('remote_access_enabled', enabled)
    db_module.log_activity(session.get('user_id'), 'toggle_remote_access', f'Remote access {"enabled" if enabled == "1" else "disabled"}')
    if enabled == '1':
        flash('Remote access enabled. Make sure HTTPS and 2FA are configured before opening the port.', 'warning')
    else:
        flash('Remote access disabled.', 'info')
    return redirect(url_for('security_page'))


@app.route('/security/2fa/setup', methods=['GET', 'POST'])
@require_role('admin', 'parent')
def setup_2fa():
    user = g.user
    if request.method == 'POST':
        secret = request.form.get('secret', '')
        code = request.form.get('code', '').strip()
        if not verify_totp(secret, code):
            flash('Invalid code. Please try again.', 'danger')
            return render_template('setup_2fa.html', secret=secret, uri=generate_totp_uri(secret, user['email'] or user['username'] or user['name']))
        db_module.set_totp_secret(user['id'], secret)
        db_module.enable_totp(user['id'])
        # Generate backup codes
        codes = generate_backup_codes()
        for code_str in codes:
            code_hash = hashlib.sha256(code_str.encode()).hexdigest()
            db_module.add_backup_code(user['id'], code_hash)
        db_module.log_activity(user['id'], 'enable_2fa', 'Enabled 2FA')
        return render_template('setup_2fa.html', backup_codes=codes, success=True)
    secret = generate_totp_secret()
    uri = generate_totp_uri(secret, user['email'] or user['username'] or user['name'])
    return render_template('setup_2fa.html', secret=secret, uri=uri)


@app.route('/security/2fa/disable', methods=['POST'])
@require_role('admin', 'parent')
def disable_2fa():
    user = g.user
    db_module.disable_totp(user['id'])
    db_module.log_activity(user['id'], 'disable_2fa', 'Disabled 2FA')
    flash('Two-factor authentication disabled.', 'info')
    return redirect(url_for('security_page'))


# --- Settings ---

@app.route('/settings', methods=['GET', 'POST'])
@require_role('admin')
def settings():
    if request.method == 'POST':
        for field in SETTINGS:
            key = field['key']
            if field['type'] == 'toggle':
                value = '1' if request.form.get(key) else '0'
            else:
                value = request.form.get(key, field['default']).strip()
                if field['type'] == 'radio' and value not in [c['value'] for c in field['choices']]:
                    value = field['default']
            db_module.set_setting(key, value)
        # Stat icon customization
        for stat_key in ['stat_icon_earned', 'stat_icon_chores', 'stat_icon_progress']:
            emoji_val = request.form.get(f'{stat_key}_emoji', '').strip()
            if emoji_val:
                db_module.set_setting(stat_key, f'emoji:{emoji_val}')
            else:
                photo = request.files.get(f'{stat_key}_photo')
                if photo and photo.filename:
                    photo_path = save_image(photo, app.config['UPLOAD_FOLDER'], stat_key)
                    if photo_path:
                        db_module.set_setting(stat_key, f'photo:{photo_path}')
        wallpaper = request.files.get('wallpaper')
        if wallpaper and wallpaper.filename:
            wp_path = save_image(wallpaper, app.config['UPLOAD_FOLDER'], 'wallpaper')
            if wp_path:
                db_module.set_setting('wallpaper', wp_path)
        logo = request.files.get('logo')
        if logo and logo.filename:
            logo_path = save_image(logo, app.config['UPLOAD_FOLDER'], 'logo')
            if logo_path:
                db_module.set_setting('family_logo', logo_path)
        db_module.log_activity(session.get('user_id'), 'update_settings', 'Updated settings')
        flash('Settings saved.', 'success')
        return redirect(url_for('settings'))
    setting_values = {f['key']: db_module.get_setting(f['key'], f['default']) for f in SETTINGS}
    family_logo = db_module.get_setting('family_logo', '')
    wallpaper = db_module.get_setting('wallpaper', '')
    stat_icons = {
        'earned': db_module.get_setting('stat_icon_earned', ''),
        'chores': db_module.get_setting('stat_icon_chores', ''),
        'progress': db_module.get_setting('stat_icon_progress', ''),
    }
    return render_template('settings.html', fields=SETTINGS, setting_values=setting_values,
                           family_logo=family_logo, wallpaper=wallpaper,
                           stat_icons=stat_icons)


# --- Backup / Restore ---

@app.route('/backup')
@require_role('admin')
def backup_page():
    return render_template('backup.html')


@app.route('/backup/download')
@require_role('admin')
def backup_download():
    import shutil
    import tempfile
    db_path = db_module.DB_PATH
    if not os.path.exists(db_path):
        flash('No database found to back up.', 'danger')
        return redirect(url_for('backup_page'))
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    tmp.close()
    shutil.copy2(db_path, tmp.name)
    with open(tmp.name, 'rb') as f:
        data = f.read()
    os.unlink(tmp.name)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    response = make_response(data)
    response.headers['Content-Type'] = 'application/octet-stream'
    response.headers['Content-Disposition'] = f'attachment; filename=choregremlin_backup_{timestamp}.db'
    db_module.log_activity(session.get('user_id'), 'backup', 'Downloaded database backup')
    return response


@app.route('/backup/restore', methods=['POST'])
@require_role('admin')
def backup_restore():
    import shutil
    import tempfile
    file = request.files.get('restore_file')
    if not file or file.filename == '':
        flash('Please select a backup file.', 'danger')
        return redirect(url_for('backup_page'))
    db_path = db_module.DB_PATH
    backup_path = db_path + '.pre_restore'
    if os.path.exists(db_path):
        shutil.copy2(db_path, backup_path)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    tmp.close()
    file.save(tmp.name)
    try:
        conn = sqlite3.connect(tmp.name)
        conn.execute("SELECT count(*) FROM users")
        conn.close()
    except Exception:
        os.unlink(tmp.name)
        flash('Invalid backup file.', 'danger')
        return redirect(url_for('backup_page'))
    shutil.copy2(tmp.name, db_path)
    os.unlink(tmp.name)
    db_module.log_activity(session.get('user_id'), 'restore', 'Restored database from backup')
    flash('Database restored successfully. Please sign in again.', 'success')
    session.clear()
    return redirect(url_for('login'))


# --- System & Maintenance ---

@app.route('/system')
@require_role('admin')
def system_info():
    import subprocess
    net = get_network_info()

    # Get system info
    sys_info = {}
    try:
        sys_info['hostname'] = socket.gethostname()
    except Exception:
        sys_info['hostname'] = 'unknown'
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = int(float(f.read().split()[0]))
            days, remainder = divmod(uptime_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, _ = divmod(remainder, 60)
            sys_info['uptime'] = f"{days}d {hours}h {minutes}m"
    except Exception:
        sys_info['uptime'] = 'unknown'
    try:
        with open('/proc/loadavg', 'r') as f:
            sys_info['load'] = f.read().strip()
    except Exception:
        sys_info['load'] = 'unknown'
    try:
        result = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True, timeout=5)
        sys_info['cpu_temp'] = result.stdout.strip().replace('temp=', '')
    except Exception:
        sys_info['cpu_temp'] = 'N/A'
    try:
        result = subprocess.run(['free', '-h'], capture_output=True, text=True, timeout=5)
        lines = result.stdout.strip().split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            sys_info['mem_total'] = parts[1]
            sys_info['mem_used'] = parts[2]
            sys_info['mem_free'] = parts[3]
    except Exception:
        sys_info['mem_total'] = 'N/A'
        sys_info['mem_used'] = 'N/A'
        sys_info['mem_free'] = 'N/A'
    try:
        result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=5)
        lines = result.stdout.strip().split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            sys_info['disk_total'] = parts[1]
            sys_info['disk_used'] = parts[2]
            sys_info['disk_free'] = parts[3]
            sys_info['disk_pct'] = parts[4]
    except Exception:
        sys_info['disk_total'] = 'N/A'
        sys_info['disk_used'] = 'N/A'
        sys_info['disk_free'] = 'N/A'
        sys_info['disk_pct'] = 'N/A'

    # Check service status
    try:
        result = subprocess.run(['systemctl', 'is-active', 'choregremlin.service'],
                               capture_output=True, text=True, timeout=5)
        sys_info['service_status'] = result.stdout.strip()
    except Exception:
        sys_info['service_status'] = 'unknown'

    try:
        result = subprocess.run(['systemctl', 'is-active', 'choregremlin-update.timer'],
                               capture_output=True, text=True, timeout=5)
        sys_info['update_timer'] = result.stdout.strip()
    except Exception:
        sys_info['update_timer'] = 'unknown'

    record_counts = db_module.get_record_counts()
    auto_update = db_module.get_setting('auto_update_enabled', '1')

    return render_template('system.html', net=net, sys_info=sys_info,
                           record_counts=record_counts, auto_update=auto_update)


@app.route('/system/check-update', methods=['POST'])
@require_role('admin')
def check_update():
    import subprocess
    output = ''
    try:
        result = subprocess.run(
            ['bash', '-c', 'cd /opt/choregremlin 2>/dev/null && git fetch origin 2>&1 && '
             'LOCAL=$(git rev-parse HEAD 2>/dev/null) && '
             'REMOTE=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null) && '
             'if [ "$LOCAL" = "$REMOTE" ]; then echo "UP_TO_DATE"; else echo "UPDATE_AVAILABLE"; fi'],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip()
    except Exception as e:
        output = f'ERROR: {e}'

    if 'UPDATE_AVAILABLE' in output:
        flash('A new update is available. It will be applied automatically on the next timer cycle.', 'info')
    elif 'UP_TO_DATE' in output:
        flash('Family Hub is up to date.', 'success')
    else:
        flash('Could not check for updates (may not be deployed as a git repo).', 'warning')
    return redirect(url_for('system_info'))


# --- Chore Approval ---

@app.route('/approvals')
@require_role('admin', 'parent')
def approvals():
    pending = db_module.get_pending_approvals()
    return render_template('approvals.html', pending=pending)


@app.route('/approvals/<int:log_id>/approve', methods=['POST'])
@require_role('admin', 'parent')
def approve_chore(log_id):
    log = db_module.approve_chore(log_id, session.get('user_id'))
    if log:
        db_module.create_payment(
            log['user_id'], log['earned_amount'],
            ptype='earning',
            description=f"Earned: {log['chore_name'] if 'chore_name' in log.keys() else 'Chore'}",
            log_id=log_id,
            created_by=session.get('user_id')
        )
        db_module.log_activity(session.get('user_id'), 'approve_chore',
                               f'Approved chore for user {log["user_id"]}')
        flash('Chore approved. Payment recorded.', 'success')
    else:
        flash('Could not approve this chore.', 'danger')
    return redirect(url_for('approvals'))


@app.route('/approvals/<int:log_id>/reject', methods=['POST'])
@require_role('admin', 'parent')
def reject_chore(log_id):
    log = db_module.reject_chore(log_id)
    if log:
        db_module.log_activity(session.get('user_id'), 'reject_chore',
                               f'Rejected chore for user {log["user_id"]}')
        flash('Chore rejected and removed.', 'info')
    else:
        flash('Could not reject this chore.', 'danger')
    return redirect(url_for('approvals'))


# --- Drop Chores ---

@app.route('/drop-chores')
@require_role('admin', 'parent')
def manage_drop_chores():
    db_module.update_drop_chore_points()
    drops = db_module.get_active_drop_chores()
    return render_template('drop_chores.html', drops=drops)


@app.route('/drop-chores/add', methods=['POST'])
@require_role('admin', 'parent')
def add_drop_chore():
    name = request.form.get('name', '').strip()
    initial_points = float(request.form.get('initial_points', 0) or 0)
    decay_per_minute = float(request.form.get('decay_per_minute', 0) or 0)
    chore_emoji = request.form.get('chore_emoji', '').strip()
    expires_minutes = int(request.form.get('expires_minutes', 60) or 60)
    if not name:
        flash('Chore name is required.', 'danger')
        return redirect(url_for('manage_drop_chores'))
    chore_image = ''
    img_file = request.files.get('chore_image')
    if img_file and img_file.filename:
        chore_image = save_image(img_file, app.config['UPLOAD_FOLDER'], 'drop')
    db_module.create_drop_chore(name, initial_points, decay_per_minute,
                                chore_emoji=chore_emoji, chore_image=chore_image,
                                created_by=session.get('user_id'), expires_minutes=expires_minutes)
    db_module.log_activity(session.get('user_id'), 'add_drop_chore', f'Drop chore: {name}')
    flash(f'Drop chore posted: {name}', 'success')
    return redirect(url_for('manage_drop_chores'))


@app.route('/drop-chores/<int:drop_id>/delete', methods=['POST'])
@require_role('admin', 'parent')
def delete_drop_chore(drop_id):
    db_module.delete_drop_chore(drop_id)
    flash('Drop chore removed.', 'info')
    return redirect(url_for('manage_drop_chores'))


@app.route('/kiosk/drop-chores')
@kiosk_mode()
def kiosk_drop_chores():
    child = g.child
    db_module.update_drop_chore_points()
    drops = db_module.get_active_drop_chores()
    return render_template('kiosk_drop_chores.html', child=child, drops=drops)


@app.route('/kiosk/drop-chores/<int:drop_id>/claim', methods=['POST'])
@kiosk_mode()
def kiosk_claim_drop_chore(drop_id):
    child = g.child
    drop = db_module.claim_drop_chore(drop_id, child['id'])
    if drop:
        db_module.create_payment(child['id'], drop['current_points'], ptype='earning',
                                description=f"Drop chore: {drop['name']}",
                                created_by=session.get('user_id'))
        db_module.log_activity(child['id'], 'claim_drop_chore',
                              f"Claimed: {drop['name']} for {drop['current_points']} points")
        flash(f'You claimed {drop["name"]} and earned {drop["current_points"]}!', 'success')
    else:
        flash('Too late - that chore was already taken!', 'danger')
    return redirect(url_for('kiosk_drop_chores'))


@app.route('/api/drop-chores')
@kiosk_mode()
def api_drop_chores():
    db_module.update_drop_chore_points()
    drops = db_module.get_active_drop_chores()
    return jsonify([{
        'id': d['id'], 'name': d['name'], 'current_points': d['current_points'],
        'chore_emoji': d['chore_emoji'], 'status': d['status']
    } for d in drops])


# --- Kiosk Calendar ---

@app.route('/kiosk/calendar')
@kiosk_mode()
def kiosk_calendar():
    child = g.child
    events = db_module.get_all_events()
    return render_template('kiosk_calendar.html', child=child, events=events)


@app.route('/kiosk/calendar/add', methods=['POST'])
@kiosk_mode()
def kiosk_add_event():
    title = request.form.get('title', '').strip()
    event_date = request.form.get('event_date', '').strip()
    event_time = request.form.get('event_time', '').strip() or None
    description = request.form.get('description', '').strip()
    if not title or not event_date:
        flash('Title and date are required.', 'danger')
        return redirect(url_for('kiosk_calendar'))
    db_module.create_event(title, event_date, description, event_time,
                          created_by=g.child['id'])
    flash('Event added to the family calendar.', 'success')
    return redirect(url_for('kiosk_calendar'))


# --- PWA ---

@app.route('/manifest.json')
def manifest():
    app_name = db_module.get_setting('app_name', 'ChoreGremlin') if db_module.is_setup_complete() else 'ChoreGremlin'
    return jsonify({
        "name": app_name,
        "short_name": "ChoreGremlin",
        "description": "The little gremlin that gets the chores done",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0e1a",
        "theme_color": "#00d9ff",
        "orientation": "any",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ]
    })


@app.route('/sw.js')
def service_worker():
    response = make_response(send_from_directory(app.static_folder, 'js/sw.js'))
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Cache-Control'] = 'no-cache'
    return response


# --- Error handlers ---

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message="You don't have permission to access this page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message="Page not found."), 404


@app.errorhandler(413)
def too_large(e):
    flash('File too large (max 8MB).', 'danger')
    return redirect(request.url)


# --- CLI ---

@app.cli.command('init-db')
def init_db_command():
    """Initialize the database."""
    db_module.init_db()
    print('Initialized the database.')


if __name__ == '__main__':
    db_module.init_db()
    port = int(os.environ.get('PORT', DEFAULT_PORT))
    app.run(host='0.0.0.0', port=port, debug=False)
