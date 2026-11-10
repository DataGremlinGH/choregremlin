"""
Chore Gremlin - Flask Application
The little gremlin that gets the chores done.
A self-hosted family chore & allowance tracker for Raspberry Pi.
"""

import os
import io
import json
import re
import socket
import sqlite3
import secrets
import hashlib
import base64
import ipaddress
import queue
import time
from datetime import datetime
from functools import wraps
from urllib.parse import urlparse, quote

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    jsonify, send_from_directory, send_file, g, flash, abort, make_response,
    has_request_context, Response, stream_with_context,
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from markupsafe import Markup, escape as markup_escape

import db as db_module
from uploads import save_image, UploadError
import clock
import gamification
import achievements
import reporting
import events
import updater
import security_audit
import release
from hardware import HardwareManager
from registry import CURRENCIES, NAV_ITEMS, SETTINGS

app = Flask(__name__, instance_relative_config=True)


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
app.config['UPLOAD_FOLDER'] = os.path.join(app.static_folder, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8MB
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('CHOREGREMLIN_HTTPS') == '1'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
csrf = CSRFProtect(app)
CURRENCY_BY_CODE = {item['code']: item for item in CURRENCIES}

app.jinja_env.globals['NAV_ITEMS'] = NAV_ITEMS
app.jinja_env.filters['localtime'] = clock.format_local

DEFAULT_PORT = 8473
APP_DIR = os.path.abspath(os.path.dirname(__file__))
RELEASE_DIR = os.path.join(db_module.DATA_DIR, 'releases')

app.teardown_appcontext(db_module.close_db)

# Initialize database on import
db_module.init_db()

_hardware_manager = None
LOCAL_HARDWARE_ADDRESSES = {None, '127.0.0.1', '::1', '::ffff:127.0.0.1'}


def get_hardware():
    global _hardware_manager
    if _hardware_manager is None:
        _hardware_manager = HardwareManager()
        _hardware_manager.on_rfid(_hardware_rfid_callback)
    return _hardware_manager


def set_hardware_manager(manager):
    global _hardware_manager
    if _hardware_manager is not None and _hardware_manager is not manager:
        _hardware_manager.stop()
    _hardware_manager = manager


def hardware_beep(pattern):
    try:
        return get_hardware().beep(pattern)
    except Exception:
        app.logger.exception('Hardware buzzer failed')
        return False


def _rfid_request_authorized():
    token = os.environ.get('CHOREGREMLIN_HARDWARE_TOKEN')
    if not token:
        return request.remote_addr in LOCAL_HARDWARE_ADDRESSES
    supplied = request.headers.get('X-Hardware-Token') or request.form.get('hardware_token', '')
    return secrets.compare_digest(str(supplied), token)


def process_rfid_scan(tag_uid):
    tag = db_module.get_rfid_tag(tag_uid)
    if not tag:
        return {'status': 'error', 'message': 'Unknown or inactive RFID tag'}, 404
    child = db_module.get_user(tag['user_id'])
    if not child or child['role'] != 'child' or not child['is_active']:
        return {'status': 'error', 'message': 'RFID tag is assigned to an unavailable child'}, 403
    return {'status': 'selected', 'child_id': child['id']}, 200


def _hardware_rfid_callback(tag_uid):
    try:
        with app.app_context():
            result, _ = process_rfid_scan(tag_uid)
            app.logger.info('Hardware RFID scan: %s', result)
            if result['status'] == 'completed':
                hardware_beep('success')
            elif result['status'] == 'selected':
                hardware_beep('start')
            else:
                hardware_beep('error')
    except Exception:
        app.logger.exception('Hardware RFID scan failed')


def _safe_referrer(fallback_endpoint):
    """Return the referring page on this site, or a sensible fallback."""
    referrer = request.referrer
    if referrer and urlparse(referrer).netloc == request.host:
        return referrer
    return url_for(fallback_endpoint)


def _normalise_ip(value):
    """Return a bounded, valid IP address string or None."""
    text = str(value or '').strip()
    if not text or len(text) > 45:
        return None
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def _clear_auth_session():
    """Drop kiosk/staff auth state without discarding the CSRF token."""
    csrf_token = session.get('csrf_token')
    session.clear()
    if csrf_token:
        session['csrf_token'] = csrf_token


def client_ip():
    """Return the client address without trusting spoofable proxy headers by default."""
    remote = _normalise_ip(request.remote_addr) or 'unknown'
    trust_proxy = os.environ.get('CHOREGREMLIN_TRUST_PROXY', '').strip().lower()
    if trust_proxy not in ('1', 'true', 'yes', 'on'):
        return remote
    forwarded = request.headers.get('X-Forwarded-For', '')
    candidate = forwarded.split(',', 1)[0].strip()
    return _normalise_ip(candidate) or remote


def token_icon_for(currency):
    """Build a safe token icon; uploaded paths and emoji are untrusted settings."""
    currency = currency or {}
    if currency.get('token_logo_type') == 'upload' and currency.get('token_logo'):
        path = str(currency.get('token_logo') or '').strip().replace('\\', '/')
        parts = path.split('/')
        if (path.startswith('uploads/') and '..' not in parts and
                re.fullmatch(r'[A-Za-z0-9._/-]+', path)):
            src = '/static/' + quote(path, safe='/')
            return Markup(
                f'<img src="{src}" alt="" '
                'style="width:16px;height:16px;vertical-align:middle;">'
            )
        return Markup('')
    return markup_escape(str(currency.get('token_emoji') or ''))


@app.errorhandler(UploadError)
def handle_upload_error(error):
    flash(str(error), 'danger')
    return redirect(_safe_referrer('dashboard'))


# --- Decorators ---

def require_role(*roles, allow_pending=False):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not db_module.is_setup_complete():
                return redirect(url_for('setup'))
            uid = session.get('user_id')
            pending = False
            if not uid and allow_pending:
                uid = session.get('pending_2fa_user_id')
                pending = bool(uid)
            if not uid:
                return redirect(url_for('login'))
            user = db_module.get_user(uid)
            if not user or not user['is_active']:
                session.clear()
                return redirect(url_for('login'))
            if roles and user['role'] not in roles:
                abort(403)
            g.user = user
            g.pending_2fa = pending
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

CHORE_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Chore_Images')
CHORE_ICON_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.svg'}
CHORE_ICON_PREFIX = 'chore-icons/'


def list_chore_icons():
    if not os.path.isdir(CHORE_ICON_DIR):
        return []
    files = [f for f in os.listdir(CHORE_ICON_DIR) if os.path.splitext(f)[1].lower() in CHORE_ICON_EXTENSIONS]
    return sorted(files, key=lambda f: chore_icon_label(f).lower())


def chore_icon_label(filename):
    return os.path.splitext(filename)[0].replace('_', ' ')


def chore_image_url(value):
    if value.startswith(CHORE_ICON_PREFIX):
        return url_for('chore_icon_file', filename=value[len(CHORE_ICON_PREFIX):])
    return url_for('static', filename=value)


app.jinja_env.globals['chore_image_url'] = chore_image_url
app.jinja_env.globals['chore_icon_label'] = chore_icon_label


@app.route('/chore-icons/<path:filename>')
def chore_icon_file(filename):
    if filename not in list_chore_icons():
        abort(404)
    return send_from_directory(CHORE_ICON_DIR, filename)


def gamification_view(child_id):
    stats = db_module.get_gamification(child_id)
    if not stats:
        stats = {
            'total_xp': 0, 'level': 1, 'current_streak': 0,
            'longest_streak': 0, 'equipped_avatar': 'default',
            'equipped_badge': '', 'last_completed_date': None,
        }
    progress = gamification.level_progress(stats['total_xp'])
    unlocked_items = db_module.get_unlocked_items(child_id)
    unlocked_avatars = {
        row['item_key'] for row in unlocked_items if row['item_type'] == 'avatar'
    }
    unlocked_badges = {
        row['item_key'] for row in unlocked_items if row['item_type'] == 'badge'
    }
    avatars = gamification.catalog_with_status(
        'avatar', level=stats['level'], total_xp=stats['total_xp'],
        longest_streak=stats['longest_streak'], current_streak=stats['current_streak']
    )
    badges = gamification.catalog_with_status(
        'badge', level=stats['level'], total_xp=stats['total_xp'],
        longest_streak=stats['longest_streak'], current_streak=stats['current_streak']
    )
    for item in avatars:
        item['unlocked'] = item['key'] in unlocked_avatars
    for item in badges:
        item['unlocked'] = item['key'] in unlocked_badges
    equipped_avatar = gamification.get_item('avatar', stats['equipped_avatar']) or gamification.get_item('avatar', 'default')
    equipped_badge = gamification.get_item('badge', stats['equipped_badge']) if stats['equipped_badge'] else None
    achievement_badges = db_module.get_child_achievements(child_id)
    return {
        'stats': stats,
        'progress': progress,
        'avatars': avatars,
        'badges': badges,
        'equipped_avatar': equipped_avatar,
        'equipped_badge': equipped_badge,
        'achievement_badges': achievement_badges,
        'achievement_summary': {
            'unlocked': sum(1 for item in achievement_badges if item['unlocked']),
            'total': len(achievement_badges),
        },
    }


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


def generate_totp_uri(secret, email, app_name='Chore Gremlin'):
    """Generate the otpauth URI for QR code."""
    label = quote(f"{app_name}:{email}", safe='')
    issuer = quote(app_name, safe='')
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"


def generate_backup_codes(count=8):
    """Generate one-time backup codes."""
    codes = []
    for _ in range(count):
        code = secrets.token_hex(4).upper()
        codes.append('-'.join([code[:4], code[4:]]))
    return codes


def qr_data_uri(data, fill_color='#0a0e1a', back_color='#ffffff', box_size=8):
    import qrcode
    qr = qrcode.QRCode(version=None, box_size=box_size, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fill_color, back_color=back_color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def totp_qr_data_uri(uri):
    return qr_data_uri(uri)


def marketplace_qr_data_uri(token):
    if has_request_context():
        target = url_for('marketplace_verify', token=token, _external=True)
    else:
        target = f'/marketplace/verify/{token}'
    return qr_data_uri(target, back_color='#ffffff', box_size=8)


# --- Context processor ---

@app.context_processor
def inject_globals():
    currency = db_module.get_currency_settings()
    selected_currency = CURRENCY_BY_CODE.get(currency['currency_code'], CURRENCIES[0])
    ui_layout = db_module.get_ui_layout_settings()
    return {
        'now': datetime.now(),
        'current_month': datetime.now().strftime('%Y-%m'),
        'app_name': db_module.get_setting('app_name', 'Chore Gremlin'),
        'family_logo': db_module.get_setting('family_logo', ''),
        'currency': currency,
        'currencies': CURRENCIES,
        'currency_code': selected_currency['code'],
        'currency_symbol': selected_currency['symbol'],
        'token_name': currency['token_name'],
        'token_singular': currency['token_singular'],
        'token_plural': currency['token_plural'],
        'token_emoji': currency['token_emoji'],
        'token_logo': currency['token_logo'],
        'token_logo_type': currency['token_logo_type'],
        'token_icon': token_icon_for(currency),
        'gbp_value': currency['gbp_value'],
        'remote_access': db_module.get_setting('remote_access_enabled', '0') == '1',
        'theme_color': achievements.clean_color(
            db_module.get_setting('theme_color', '#10b981')
        ),
        'brightness_mode': db_module.get_setting('brightness_mode', 'dark'),
        'ui_layout': ui_layout,
        'menu_position': ui_layout['menu_position'],
        'button_theme': ui_layout['button_theme'],
        'wallpaper': db_module.get_setting('wallpaper', ''),
        'data_dir': db_module.DATA_DIR,
        'latest_broadcast': db_module.get_latest_active_broadcast(),
    }


PUBLIC_ENDPOINTS = {
    'index', 'setup', 'login', 'logout', 'kiosk_login', 'kiosk_select',
    'kiosk_rfid_scan', 'kiosk_child_logout', 'manifest', 'service_worker',
    'chore_icon_file', 'trust_page', 'trust_ca',
}
KIOSK_ENDPOINTS = {
    'child_chores', 'kiosk_complete_chore', 'kiosk_drop_chores', 'kiosk_claim_drop_chore',
    'kiosk_complete_drop_chore', 'kiosk_calendar', 'kiosk_add_event',
    'kiosk_rewards', 'kiosk_equip_reward',
    'kiosk_bank', 'kiosk_bank_deposit', 'kiosk_bank_withdraw', 'kiosk_loan_apply',
    'kiosk_vault_add', 'kiosk_vault_deposit', 'kiosk_vault_withdraw',
    'kiosk_shop', 'kiosk_shop_buy', 'kiosk_shop_cancel',
    'kiosk_bills', 'kiosk_bill_pay',
}
ADMIN_ENDPOINTS = {
    'delete_kid', 'reset_pin', 'delete_chore_route', 'delete_payment_route',
    'manage_parents', 'add_parent', 'delete_parent', 'reset_password',
    'network_settings', 'network_update', 'network_qr',
    'storage_page', 'storage_move', 'storage_confirm_delete', 'storage_rollback',
    'currency_page', 'currency_save', 'currency_reset_logo',
    'security_page', 'security_audit_page', 'toggle_remote_access', 'settings',
    'backup_page', 'backup_download', 'backup_restore',
    'system_info', 'check_update',
    'snapshots_page', 'snapshot_create', 'snapshot_restore', 'snapshot_delete',
    'update_check', 'update_apply',
    'releases_page', 'release_build', 'release_tag', 'release_download',
}
STAFF_ENDPOINTS = {
    'dashboard', 'family_dashboard', 'rewards', 'bank',
    'bank_settings', 'bank_deposit', 'bank_withdraw',
    'bank_vault_add', 'bank_vault_close', 'bank_vault_unlock',
    'bank_match_rule_save', 'bank_match_rule_delete',
    'loan_approve', 'loan_reject',
    'bills', 'bills_add', 'bills_toggle', 'bills_delete', 'bills_run',
    'bill_occurrence_pay',
    'marketplace', 'marketplace_item_add', 'marketplace_item_update',
    'marketplace_item_toggle', 'marketplace_cash_adjust', 'marketplace_order_approve',
    'marketplace_order_reject', 'marketplace_order_fulfill',
    'marketplace_verify',
    'manage_kids', 'add_kid', 'edit_kid',
    'manage_chores', 'add_chore', 'edit_chore', 'assign_chore_route',
    'manage_payments', 'add_payment', 'payout_all', 'view_logs',
    'manage_notices', 'add_notice', 'delete_notice',
    'manage_events', 'add_event', 'delete_event',
    'achievements_page', 'achievement_milestone_add',
    'achievement_milestone_toggle', 'achievement_milestone_delete',
    'achievement_evaluate_all', 'achievement_broadcast_create',
    'achievement_broadcast_delete', 'reports_page', 'reports_export',
    'approvals', 'approve_chore', 'reject_chore',
    'manage_drop_chores', 'add_drop_chore', 'delete_drop_chore',
}
TWO_FACTOR_ENDPOINTS = {'setup_2fa', 'disable_2fa'}
LIVE_ENDPOINTS = {'events_stream', 'alerts_feed', 'api_drop_chores'}

ROUTE_ACCESS = {}
for _endpoint in PUBLIC_ENDPOINTS:
    ROUTE_ACCESS[_endpoint] = 'public'
for _endpoint in KIOSK_ENDPOINTS:
    ROUTE_ACCESS[_endpoint] = 'kiosk'
for _endpoint in ADMIN_ENDPOINTS:
    ROUTE_ACCESS[_endpoint] = 'admin'
for _endpoint in STAFF_ENDPOINTS:
    ROUTE_ACCESS[_endpoint] = 'staff'
for _endpoint in TWO_FACTOR_ENDPOINTS:
    ROUTE_ACCESS[_endpoint] = '2fa'
for _endpoint in LIVE_ENDPOINTS:
    ROUTE_ACCESS[_endpoint] = 'live'


@app.before_request
def enforce_route_access():
    endpoint = request.endpoint
    if endpoint is None or endpoint == 'static':
        return None
    access = ROUTE_ACCESS.get(endpoint)
    if access is None:
        app.logger.error('No access rule configured for endpoint %s', endpoint)
        abort(403)
    if access == 'public':
        return None
    if not db_module.is_setup_complete():
        return redirect(url_for('setup'))
    if access == 'kiosk':
        child_id = session.get('kiosk_child_id')
        if not child_id:
            return redirect(url_for('kiosk_login'))
        child = db_module.get_user(child_id)
        if not child or child['role'] != 'child' or not child['is_active']:
            session.pop('kiosk_child_id', None)
            return redirect(url_for('kiosk_login'))
        g.child = child
        return None
    if access == '2fa':
        return None
    if access == 'live':
        uid = session.get('user_id')
        if uid:
            user = db_module.get_user(uid)
            if user and user['is_active']:
                g.user = user
                g.pending_2fa = False
                return None
        child_id = session.get('kiosk_child_id')
        if child_id:
            child = db_module.get_user(child_id)
            if child and child['role'] == 'child' and child['is_active']:
                g.child = child
                return None
        abort(401)
    uid = session.get('user_id')
    if not uid:
        return redirect(url_for('login'))
    user = db_module.get_user(uid)
    if not user or not user['is_active']:
        session.clear()
        return redirect(url_for('login'))
    allowed_roles = ('admin',) if access == 'admin' else ('admin', 'parent')
    if user['role'] not in allowed_roles:
        abort(403)
    if user['role'] == 'admin' and not db_module.get_totp_secret(user['id']):
        flash('Administrators must set up two-factor authentication before continuing.', 'warning')
        return redirect(url_for('setup_2fa'))
    g.user = user
    g.pending_2fa = False
    return None


@app.after_request
def apply_security_headers(response):
    https = os.environ.get('CHOREGREMLIN_HTTPS') == '1'
    return security_audit.apply_headers(response, https=https)


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
        app_name = request.form.get('app_name', 'Chore Gremlin').strip()

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
        ip_address = client_ip()

        # Check lockout
        is_locked, minutes_left = db_module.check_lockout(login_id, ip_address)
        if is_locked:
            flash(f'Too many failed attempts. Try again in {minutes_left} minute(s).', 'danger')
            db_module.log_login_attempt(login_id, ip_address, False, 'locked_out')
            return render_template('login.html')

        user = db_module.get_user_by_login(login_id)
        if user and db_module.verify_password(user, password):
            _clear_auth_session()
            remote_access = db_module.get_setting('remote_access_enabled', '0') == '1'
            totp = db_module.get_totp_secret(user['id'])
            if user['role'] == 'admin' and not totp:
                session['pending_2fa_user_id'] = user['id']
                session['pending_2fa_forced'] = True
                db_module.log_login_attempt(login_id, ip_address, True, '2fa_setup_required')
                flash('Administrators must set up two-factor authentication. Scan the QR code with your authenticator app to continue.', 'warning')
                return redirect(url_for('setup_2fa'))
            require_totp = bool(totp) and (user['role'] == 'admin' or remote_access)
            if require_totp:
                if not totp_code:
                    db_module.log_login_attempt(login_id, ip_address, True, 'totp_required')
                    return render_template('login.html', require_totp=True, username=login_id,
                                           admin_2fa=user['role'] == 'admin')
                if not verify_totp(totp['secret'], totp_code):
                    code_hash = hashlib.sha256(totp_code.upper().encode()).hexdigest()
                    if not db_module.verify_backup_code(user['id'], code_hash):
                        db_module.log_login_attempt(login_id, ip_address, False, 'invalid_totp')
                        db_module.record_failed_attempt(login_id, ip_address)
                        flash('Invalid authentication code.', 'danger')
                        return render_template('login.html', require_totp=True, username=login_id,
                                               admin_2fa=user['role'] == 'admin')
            session.pop('pending_2fa_user_id', None)
            session.pop('pending_2fa_forced', None)
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['2fa_verified'] = bool(require_totp)
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
    session.pop('2fa_verified', None)
    session.pop('pending_2fa_user_id', None)
    session.pop('pending_2fa_forced', None)
    session.pop('totp_setup_secret', None)
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


@app.route('/kiosk/scan', methods=['POST'])
@csrf.exempt
def kiosk_rfid_scan():
    if not _rfid_request_authorized():
        hardware_beep('error')
        return jsonify({'status': 'error', 'message': 'RFID scan is not authorized from this address'}), 403
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    tag_uid = request.form.get('tag_uid') or payload.get('tag_uid') or payload.get('uid') or ''
    if not tag_uid:
        hardware_beep('error')
        return jsonify({'status': 'error', 'message': 'tag_uid is required'}), 400
    result, code = process_rfid_scan(tag_uid)
    if result['status'] in {'selected', 'completed'}:
        session['kiosk_child_id'] = result['child_id']
        result['redirect'] = url_for('child_chores')
    hardware_beep({'completed': 'success', 'selected': 'start'}.get(result['status'], 'error'))
    return jsonify(result), code


@app.route('/kiosk/select/<int:child_id>', methods=['GET', 'POST'])
def kiosk_select(child_id):
    child = db_module.get_user(child_id)
    if not child or child['role'] != 'child' or not child['is_active']:
        hardware_beep('error')
        flash('Child not found.', 'danger')
        return redirect(url_for('kiosk_login'))

    if request.method == 'POST':
        if child['pin']:
            result = db_module.check_kiosk_pin(child, request.form.get('pin', ''))
            if result == 'locked':
                hardware_beep('error')
                flash('Too many wrong PINs. Please wait a few minutes and try again.', 'danger')
                return render_template('kiosk_pin.html', child=child)
            if result == 'wrong':
                hardware_beep('error')
                flash('Incorrect PIN. Please try again.', 'danger')
                return render_template('kiosk_pin.html', child=child)
        hardware_beep('success')
        session['kiosk_child_id'] = child_id
        return redirect(url_for('child_chores'))

    if child['pin']:
        return render_template('kiosk_pin.html', child=child)
    hardware_beep('success')
    session['kiosk_child_id'] = child_id
    return redirect(url_for('child_chores'))


@app.route('/kiosk/chores')
@kiosk_mode()
def child_chores():
    child = g.child
    db_module.update_drop_chore_points()
    chores = db_module.get_chores_for_child(child['id'], child['can_do_hard_chores'])
    assigned_drops = [_drop_view(drop) for drop in db_module.get_assigned_drop_chores(child['id'])]
    balance = db_module.get_balance(child['id'])
    month_earnings = db_module.get_monthly_earnings(child['id'])
    my_earnings = month_earnings[0] if month_earnings else None
    rewards = gamification_view(child['id'])
    return render_template('child_chores.html', child=child, chores=chores,
                           assigned_drops=assigned_drops, balance=balance,
                           my_earnings=my_earnings, rewards=rewards)


@app.route('/kiosk/rewards')
@kiosk_mode()
def kiosk_rewards():
    child = g.child
    return render_template('kiosk_rewards.html', child=child,
                           **gamification_view(child['id']))


@app.route('/kiosk/rewards/equip', methods=['POST'])
@kiosk_mode()
def kiosk_equip_reward():
    item_type = request.form.get('item_type', '')
    item_key = request.form.get('item_key', '')
    try:
        db_module.equip_gamification_item(g.child['id'], item_type, item_key)
        hardware_beep('success')
        flash('Reward equipped!', 'success')
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'danger')
    return redirect(url_for('kiosk_rewards'))


@app.route('/kiosk/bank')
@kiosk_mode()
def kiosk_bank():
    child = g.child
    db_module.apply_savings_interest()
    loans = db_module.get_loans(child['id'], limit=20)
    return render_template(
        'kiosk_bank.html', child=child,
        account=db_module.get_savings_account(child['id']),
        spendable=db_module.get_balance(child['id']),
        transactions=db_module.get_bank_transactions(child['id'], limit=15),
        loans=loans,
        active_loan=next((loan for loan in loans if loan['status'] == 'active'), None),
        pending_loan=next((loan for loan in loans if loan['status'] == 'pending'), None),
        vaults=db_module.get_savings_vaults_with_progress(
            child['id'], include_match_rules=True
        ),
        vault_total=db_module.get_savings_vault_total(child['id']),
        vault_transactions=db_module.get_savings_vault_transactions(
            user_id=child['id'], limit=15
        ),
    )


@app.route('/kiosk/bills')
@kiosk_mode()
def kiosk_bills():
    child = g.child
    db_module.schedule_due_bills()
    db_module.apply_overdue_late_fees()
    return render_template(
        'kiosk_bills.html', child=child,
        spendable=db_module.get_balance(child['id']),
        summary=db_module.get_bill_summary(child['id']),
        open_occurrences=db_module.get_bill_occurrences(
            user_id=child['id'], include_paid=False, limit=100
        ),
        paid_occurrences=db_module.get_bill_occurrences(
            user_id=child['id'], status='paid', limit=20
        ),
    )


@app.route('/kiosk/bills/<int:occurrence_id>/pay', methods=['POST'])
@kiosk_mode()
def kiosk_bill_pay(occurrence_id):
    try:
        result = db_module.pay_bill_occurrence(
            occurrence_id, source='kiosk', user_id=g.child['id']
        )
        db_module.log_activity(
            g.child['id'], 'bill_pay',
            f'Paid {result["paid"]:.2f} toward {result["occurrence"]["name"]}'
        )
        hardware_beep('success')
        flash(f'Bill paid: {result["paid"]:.2f}.', 'success')
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'danger')
    return redirect(url_for('kiosk_bills'))


@app.route('/kiosk/bank/deposit', methods=['POST'])
@kiosk_mode()
def kiosk_bank_deposit():
    try:
        account = db_module.deposit_to_savings(g.child['id'], request.form.get('amount', '0'))
        db_module.log_activity(
            g.child['id'], 'bank_deposit',
            f'Deposited {request.form.get("amount", "0")} into savings'
        )
        hardware_beep('success')
        flash(f'Savings balance is now {account["balance"]:.2f}.', 'success')
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'danger')
    return redirect(url_for('kiosk_bank'))


@app.route('/kiosk/bank/withdraw', methods=['POST'])
@kiosk_mode()
def kiosk_bank_withdraw():
    try:
        account = db_module.withdraw_from_savings(g.child['id'], request.form.get('amount', '0'))
        db_module.log_activity(
            g.child['id'], 'bank_withdraw',
            f'Withdrew {request.form.get("amount", "0")} from savings'
        )
        hardware_beep('success')
        flash(f'Savings balance is now {account["balance"]:.2f}.', 'success')
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'danger')
    return redirect(url_for('kiosk_bank'))


@app.route('/kiosk/loan/apply', methods=['POST'])
@kiosk_mode()
def kiosk_loan_apply():
    try:
        loan_id = db_module.apply_for_loan(
            g.child['id'],
            request.form.get('amount', '0'),
            request.form.get('term_weeks', '1'),
            request.form.get('purpose', ''),
        )
        db_module.log_activity(
            g.child['id'], 'loan_apply',
            f'Requested loan #{loan_id} for {request.form.get("amount", "0")}'
        )
        hardware_beep('success')
        flash('Loan request sent to a parent for approval.', 'success')
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'danger')
    return redirect(url_for('kiosk_bank'))


@app.route('/kiosk/bank/vaults/add', methods=['POST'])
@kiosk_mode()
def kiosk_vault_add():
    try:
        vault = db_module.create_savings_vault(
            g.child['id'],
            request.form.get('name', ''),
            request.form.get('target_amount', '0'),
            target_date=request.form.get('target_date', ''),
            lock_until_date=request.form.get('lock_until_date') == '1',
            lock_until_target=request.form.get('lock_until_target') == '1',
            description=request.form.get('description', ''),
            icon=request.form.get('icon', 'bi-bullseye'),
            color=request.form.get('color', g.child['color']),
        )
        db_module.log_activity(
            g.child['id'], 'vault_create',
            f'Created savings goal {vault["name"]}'
        )
        hardware_beep('success')
        flash(f'Goal "{vault["name"]}" created.', 'success')
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'danger')
    return redirect(url_for('kiosk_bank') + '#savings-goals')


@app.route('/kiosk/bank/vaults/<int:vault_id>/deposit', methods=['POST'])
@kiosk_mode()
def kiosk_vault_deposit(vault_id):
    try:
        result = db_module.deposit_to_savings_vault(
            vault_id, g.child['id'], request.form.get('amount', '0')
        )
        vault = result['vault']
        message = f'Added to {vault["name"]}. Goal balance {vault["balance"]:.2f}.'
        if result['matched'] > 0:
            message += f' Parent matched {result["matched"]:.2f}.'
        db_module.log_activity(
            g.child['id'], 'vault_deposit',
            f'Added to savings goal {vault["name"]}; balance {vault["balance"]:.2f}'
        )
        hardware_beep('success')
        flash(message, 'success')
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'danger')
    return redirect(url_for('kiosk_bank') + '#savings-goals')


@app.route('/kiosk/bank/vaults/<int:vault_id>/withdraw', methods=['POST'])
@kiosk_mode()
def kiosk_vault_withdraw(vault_id):
    try:
        vault = db_module.withdraw_from_savings_vault(
            vault_id, g.child['id'], request.form.get('amount', '0')
        )
        db_module.log_activity(
            g.child['id'], 'vault_withdraw',
            f'Withdrew from savings goal {vault["name"]}; balance {vault["balance"]:.2f}'
        )
        hardware_beep('success')
        flash(f'Withdrew from {vault["name"]}. Goal balance {vault["balance"]:.2f}.', 'success')
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'danger')
    return redirect(url_for('kiosk_bank') + '#savings-goals')


@app.route('/kiosk/shop')
@kiosk_mode()
def kiosk_shop():
    child = g.child
    orders = db_module.get_marketplace_orders(child['id'], limit=50)
    active_orders = []
    history = []
    for order in orders:
        row = dict(order)
        if row['status'] in ('pending', 'approved'):
            row['qr_data_uri'] = marketplace_qr_data_uri(row['qr_token'])
            active_orders.append(row)
        else:
            history.append(row)
    return render_template(
        'kiosk_shop.html', child=child,
        items=db_module.get_marketplace_items(active_only=True),
        balance=db_module.get_balance(child['id']),
        cash_balance=db_module.get_cash_balance(child['id']),
        active_orders=active_orders, history=history,
    )


@app.route('/kiosk/shop/buy/<int:item_id>', methods=['POST'])
@kiosk_mode()
def kiosk_shop_buy(item_id):
    try:
        order_id = db_module.create_marketplace_order(
            g.child['id'], item_id, request.form.get('quantity', '1')
        )
        db_module.log_activity(
            g.child['id'], 'marketplace_purchase',
            f'Placed marketplace order #{order_id}'
        )
        hardware_beep('success')
        flash('Order placed! Show the QR code to a parent to collect it.', 'success')
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'danger')
    return redirect(url_for('kiosk_shop'))


@app.route('/kiosk/shop/orders/<int:order_id>/cancel', methods=['POST'])
@kiosk_mode()
def kiosk_shop_cancel(order_id):
    try:
        db_module.cancel_marketplace_order(order_id, g.child['id'])
        db_module.log_activity(
            g.child['id'], 'marketplace_cancel',
            f'Cancelled marketplace order #{order_id}'
        )
        hardware_beep('cancel')
        flash('Order cancelled and your balance refunded.', 'info')
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'danger')
    return redirect(url_for('kiosk_shop'))


def _complete_chore_for_child(chore_id):
    child = g.child
    chore = db_module.get_chore(chore_id)
    if not chore:
        hardware_beep('error')
        flash('Chore not available.', 'danger')
        return redirect(url_for('child_chores'))
    try:
        db_module.complete_chore(child['id'], chore_id)
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'warning')
        return redirect(url_for('child_chores'))
    db_module.log_activity(
        child['id'], 'complete_chore',
        f'Completed {chore["name"]}, pending approval'
    )
    hardware_beep('success')
    flash('Great job! Your chore is waiting for a parent to approve it.', 'success')
    return redirect(url_for('child_chores'))


@app.route('/kiosk/chores/<int:chore_id>/complete', methods=['POST'])
@app.route('/kiosk/complete/<int:chore_id>', methods=['POST'])
@kiosk_mode()
def kiosk_complete_chore(chore_id):
    return _complete_chore_for_child(chore_id)


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
    pending_approvals = db_module.get_pending_approvals()
    stat_icons = {
        'earned': db_module.get_setting('stat_icon_earned', ''),
        'chores': db_module.get_setting('stat_icon_chores', ''),
        'progress': db_module.get_setting('stat_icon_progress', ''),
    }
    return render_template('dashboard.html', children=children, earnings=earnings,
                           total_earned=total_earned, chore_count=chore_count,
                           pending_approvals=pending_approvals, selected_month=month,
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


@app.route('/rewards')
@require_role('admin', 'parent')
def rewards():
    children = []
    for row in db_module.get_gamification_overview():
        child = dict(row)
        view = gamification_view(row['user_id'])
        child.update({
            'total_xp': view['stats']['total_xp'],
            'level': view['stats']['level'],
            'current_streak': view['stats']['current_streak'],
            'longest_streak': view['stats']['longest_streak'],
            'last_completed_date': view['stats']['last_completed_date'],
            'progress': view['progress'],
            'equipped_avatar_item': view['equipped_avatar'],
            'equipped_badge_item': view['equipped_badge'],
            'achievement_summary': view['achievement_summary'],
        })
        children.append(child)
    return render_template(
        'rewards.html', children=children,
        avatars=gamification.AVATAR_CATALOG,
        badges=gamification.BADGE_CATALOG,
        xp_events=db_module.get_xp_events(limit=12),
    )


def _evaluate_all_achievements():
    unlocked = 0
    for child in db_module.get_children():
        unlocked += len(db_module.evaluate_achievements(child['id']))
    return unlocked


@app.route('/achievements')
@require_role('admin', 'parent')
def achievements_page():
    children = []
    for row in db_module.get_children():
        child = dict(row)
        items = db_module.get_child_achievements(child['id'])
        unlocked = [item for item in items if item['unlocked']]
        child['achievement_summary'] = {
            'unlocked': len(unlocked),
            'total': len(items),
        }
        child['latest_achievement'] = unlocked[0] if unlocked else None
        children.append(child)
    return render_template(
        'achievements.html',
        children=children,
        metrics=achievements.METRIC_CHOICES,
        builtin_achievements=achievements.builtin_definitions(),
        custom_milestones=db_module.get_custom_milestones(),
        unlocks=db_module.get_achievement_unlocks(limit=25),
        broadcasts=db_module.get_all_broadcasts(limit=30),
    )


@app.route('/achievements/milestones/add', methods=['POST'])
@require_role('admin', 'parent')
def achievement_milestone_add():
    try:
        milestone = db_module.create_custom_milestone(
            request.form.get('name', ''),
            description=request.form.get('description', ''),
            icon=request.form.get('icon', 'bi-award-fill'),
            color=request.form.get('color', '#10b981'),
            metric=request.form.get('metric', 'chores_completed'),
            threshold=request.form.get('threshold', '1'),
            reward_type=request.form.get('reward_type', 'none'),
            reward_value=request.form.get('reward_value', '0'),
            created_by=session.get('user_id'),
        )
        unlocked = _evaluate_all_achievements()
        db_module.log_activity(
            session.get('user_id'), 'add_milestone',
            f'Added custom milestone: {milestone["name"]}'
        )
        flash(
            f'Added milestone "{milestone["name"]}". '
            f'{unlocked} achievement(s) unlocked.',
            'success'
        )
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('achievements_page'))


@app.route('/achievements/milestones/<int:milestone_id>/toggle', methods=['POST'])
@require_role('admin', 'parent')
def achievement_milestone_toggle(milestone_id):
    milestone = db_module.get_custom_milestone(milestone_id)
    if not milestone:
        flash('Milestone not found.', 'danger')
        return redirect(url_for('achievements_page'))
    try:
        updated = db_module.set_custom_milestone_active(
            milestone_id, not bool(milestone['is_active'])
        )
        unlocked = _evaluate_all_achievements() if updated['is_active'] else 0
        db_module.log_activity(
            session.get('user_id'), 'toggle_milestone',
            f'{"Activated" if updated["is_active"] else "Paused"} milestone: {updated["name"]}'
        )
        flash(
            f'Milestone "{updated["name"]}" '
            f'{"activated" if updated["is_active"] else "paused"}.'
            + (f' {unlocked} achievement(s) unlocked.' if unlocked else ''),
            'success'
        )
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('achievements_page'))


@app.route('/achievements/milestones/<int:milestone_id>/delete', methods=['POST'])
@require_role('admin', 'parent')
def achievement_milestone_delete(milestone_id):
    try:
        milestone = db_module.delete_custom_milestone(milestone_id)
        db_module.log_activity(
            session.get('user_id'), 'delete_milestone',
            f'Deleted custom milestone: {milestone["name"]}'
        )
        flash(f'Deleted milestone "{milestone["name"]}".', 'info')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('achievements_page'))


@app.route('/achievements/evaluate', methods=['POST'])
@require_role('admin', 'parent')
def achievement_evaluate_all():
    unlocked = _evaluate_all_achievements()
    db_module.log_activity(
        session.get('user_id'), 'evaluate_achievements',
        f'Checked achievement progress for all children ({unlocked} new unlocks)'
    )
    flash(f'Checked every child. {unlocked} new achievement(s) unlocked.', 'success')
    return redirect(url_for('achievements_page'))


@app.route('/achievements/broadcast', methods=['POST'])
@require_role('admin', 'parent')
def achievement_broadcast_create():
    try:
        broadcast = db_module.create_broadcast_alert(
            request.form.get('title', ''),
            body=request.form.get('body', ''),
            kind=request.form.get('kind', 'celebration'),
            child_id=request.form.get('child_id') or None,
            icon=request.form.get('icon', 'bi-megaphone-fill'),
            color=request.form.get('color', '#10b981'),
            created_by=session.get('user_id'),
            expires_at=request.form.get('expires_at', ''),
        )
        db_module.log_activity(
            session.get('user_id'), 'broadcast_alert',
            f'Broadcast: {broadcast["title"]}'
        )
        flash('Family broadcast posted.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('achievements_page'))


@app.route('/achievements/broadcast/<int:broadcast_id>/delete', methods=['POST'])
@require_role('admin', 'parent')
def achievement_broadcast_delete(broadcast_id):
    if db_module.deactivate_broadcast_alert(broadcast_id):
        flash('Broadcast cleared.', 'info')
    else:
        flash('Broadcast not found.', 'danger')
    return redirect(url_for('achievements_page'))


# --- Financial reports & ledger exports (Phase 13) ---

def _report_filters():
    child_id = request.args.get('child_id', '').strip()
    if child_id:
        try:
            child_id = int(child_id)
        except ValueError:
            child_id = None
    else:
        child_id = None
    start_date, end_date = reporting.normalize_range(
        request.args.get('start', ''), request.args.get('end', '')
    )
    kind = reporting.normalize_kind(request.args.get('report', 'ledger'))
    return child_id, start_date, end_date, kind


@app.route('/reports')
@require_role('admin', 'parent')
def reports_page():
    try:
        child_id, start_date, end_date, kind = _report_filters()
    except ValueError as exc:
        flash(str(exc), 'danger')
        child_id, start_date, end_date, kind = None, None, None, 'ledger'
    summary = db_module.get_financial_summary(
        start_date=start_date, end_date=end_date, user_id=child_id
    )
    data = db_module.get_report_data(
        kind, user_id=child_id, start_date=start_date, end_date=end_date
    )
    return render_template(
        'reports.html',
        children=db_module.get_children(),
        report_kinds=reporting.REPORT_KINDS,
        report_labels=reporting.REPORT_LABELS,
        report_kind=kind,
        report_data=data,
        summary=summary,
        selected_child=child_id,
        start_date=start_date or '',
        end_date=end_date or '',
        payment_labels=reporting.PAYMENT_TYPE_LABELS,
    )


@app.route('/reports/export.csv')
@require_role('admin', 'parent')
def reports_export():
    try:
        child_id, start_date, end_date, kind = _report_filters()
        data = db_module.get_report_data(
            kind, user_id=child_id, start_date=start_date, end_date=end_date
        )
        payload = reporting.build_export(kind, data)
    except ValueError as exc:
        return make_response(str(exc), 400, {'Content-Type': 'text/plain; charset=utf-8'})
    filename = reporting.default_filename(kind, start_date, end_date)
    response = make_response(payload)
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    db_module.log_activity(
        session.get('user_id'), 'export_report',
        f'Exported {reporting.REPORT_LABELS[kind]} report ({len(data) if isinstance(data, list) else "summary"})'
    )
    return response


@app.route('/bank')
@require_role('admin', 'parent')
def bank():
    db_module.apply_savings_interest()
    accounts = []
    for child in db_module.get_children():
        account = dict(db_module.get_savings_account(child['id']))
        account['color'] = child['color']
        account['spendable'] = db_module.get_balance(child['id'])
        accounts.append(account)
    loans = db_module.get_loans(limit=200)
    children = db_module.get_children()
    return render_template(
        'bank.html', accounts=accounts, loans=loans, children=children,
        pending_loans=[loan for loan in loans if loan['status'] == 'pending'],
        active_loans=[loan for loan in loans if loan['status'] == 'active'],
        recent_transactions=db_module.get_bank_transactions(limit=40),
        vaults=db_module.get_savings_vaults_with_progress(include_match_rules=True),
        match_rules=db_module.get_savings_match_rules(),
        vault_total=db_module.get_savings_vault_total(),
    )


@app.route('/bank/<int:child_id>/settings', methods=['POST'])
@require_role('admin', 'parent')
def bank_settings(child_id):
    try:
        db_module.update_savings_settings(
            child_id,
            request.form.get('annual_interest_rate', '5'),
            request.form.get('compounding', 'weekly'),
        )
        flash('Savings settings updated.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bank'))


@app.route('/bank/<int:child_id>/deposit', methods=['POST'])
@require_role('admin', 'parent')
def bank_deposit(child_id):
    try:
        account = db_module.deposit_to_savings(child_id, request.form.get('amount', '0'))
        db_module.log_activity(
            session.get('user_id'), 'bank_deposit',
            f'Deposited into savings for child #{child_id}; balance {account["balance"]:.2f}'
        )
        flash('Savings deposit recorded.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bank'))


@app.route('/bank/<int:child_id>/withdraw', methods=['POST'])
@require_role('admin', 'parent')
def bank_withdraw(child_id):
    try:
        account = db_module.withdraw_from_savings(child_id, request.form.get('amount', '0'))
        db_module.log_activity(
            session.get('user_id'), 'bank_withdraw',
            f'Withdrew from savings for child #{child_id}; balance {account["balance"]:.2f}'
        )
        flash('Savings withdrawal recorded.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bank'))


@app.route('/bank/vaults/add', methods=['POST'])
@require_role('admin', 'parent')
def bank_vault_add():
    try:
        vault = db_module.create_savings_vault(
            request.form.get('child_id'),
            request.form.get('name', ''),
            request.form.get('target_amount', '0'),
            target_date=request.form.get('target_date', ''),
            lock_until_date=request.form.get('lock_until_date') == '1',
            lock_until_target=request.form.get('lock_until_target') == '1',
            description=request.form.get('description', ''),
            icon=request.form.get('icon', 'bi-bullseye'),
            color=request.form.get('color', '#10b981'),
        )
        db_module.log_activity(
            session.get('user_id'), 'vault_create',
            f'Created savings goal {vault["name"]} for {vault["user_name"]}'
        )
        flash('Savings goal created.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bank') + '#savings-vaults')


@app.route('/bank/vaults/<int:vault_id>/close', methods=['POST'])
@require_role('admin', 'parent')
def bank_vault_close(vault_id):
    try:
        vault = db_module.close_savings_vault(vault_id)
        db_module.log_activity(
            session.get('user_id'), 'vault_close',
            f'Closed savings goal {vault["name"]} for {vault["user_name"]}'
        )
        flash(f'Closed "{vault["name"]}" and returned any balance to spendable.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bank') + '#savings-vaults')


@app.route('/bank/vaults/<int:vault_id>/unlock', methods=['POST'])
@require_role('admin', 'parent')
def bank_vault_unlock(vault_id):
    try:
        vault = db_module.unlock_savings_vault(vault_id)
        db_module.log_activity(
            session.get('user_id'), 'vault_unlock',
            f'Removed locks from savings goal {vault["name"]} for {vault["user_name"]}'
        )
        flash(f'Locks removed from "{vault["name"]}".', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bank') + '#savings-vaults')


@app.route('/bank/match-rules/save', methods=['POST'])
@require_role('admin', 'parent')
def bank_match_rule_save():
    try:
        rule = db_module.set_savings_match_rule(
            request.form.get('child_id'),
            request.form.get('vault_id') or None,
            request.form.get('match_percent', '50'),
            request.form.get('weekly_cap', '10'),
            is_active=request.form.get('is_active') == '1',
        )
        db_module.log_activity(
            session.get('user_id'), 'match_rule_save',
            f'Saved matching rule for {rule["user_name"]}'
        )
        flash('Parent matching rule saved.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bank') + '#matching-rules')


@app.route('/bank/match-rules/<int:rule_id>/delete', methods=['POST'])
@require_role('admin', 'parent')
def bank_match_rule_delete(rule_id):
    try:
        rule = db_module.delete_savings_match_rule(rule_id)
        db_module.log_activity(
            session.get('user_id'), 'match_rule_delete',
            f'Removed matching rule for {rule["user_name"]}'
        )
        flash('Parent matching rule removed.', 'info')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bank') + '#matching-rules')


@app.route('/bank/loans/<int:loan_id>/approve', methods=['POST'])
@require_role('admin', 'parent')
def loan_approve(loan_id):
    term_weeks = request.form.get('term_weeks') or None
    principal = request.form.get('principal') or None
    try:
        loan = db_module.approve_loan(
            loan_id, session.get('user_id'),
            annual_rate=request.form.get('annual_rate', '0'),
            term_weeks=term_weeks,
            principal=principal,
        )
        db_module.log_activity(
            session.get('user_id'), 'loan_approve',
            f'Approved loan #{loan_id} for {loan["user_name"]}'
        )
        flash('Loan approved and principal added to spendable balance.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bank'))


@app.route('/bank/loans/<int:loan_id>/reject', methods=['POST'])
@require_role('admin', 'parent')
def loan_reject(loan_id):
    try:
        loan = db_module.reject_loan(loan_id, request.form.get('reason', ''))
        db_module.log_activity(
            session.get('user_id'), 'loan_reject',
            f'Rejected loan #{loan_id} for {loan["user_name"]}'
        )
        flash('Loan request rejected.', 'info')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bank'))


@app.route('/bills')
@require_role('admin', 'parent')
def bills():
    db_module.schedule_due_bills()
    db_module.apply_overdue_late_fees()
    children = db_module.get_children()
    per_child = []
    for child in children:
        per_child.append({
            'child': child,
            'summary': db_module.get_bill_summary(child['id']),
            'spendable': db_module.get_balance(child['id']),
        })
    return render_template(
        'bills.html',
        children=children,
        bills=db_module.get_household_bills(),
        open_occurrences=db_module.get_bill_occurrences(include_paid=False, limit=500),
        paid_occurrences=db_module.get_bill_occurrences(status='paid', limit=30),
        summary=db_module.get_bill_summary(),
        per_child=per_child,
        today=clock.local_date_text(),
    )


@app.route('/bills/add', methods=['POST'])
@require_role('admin', 'parent')
def bills_add():
    try:
        bill = db_module.create_household_bill(
            request.form.get('child_id'),
            request.form.get('name', ''),
            request.form.get('category', 'other'),
            request.form.get('amount', '0'),
            request.form.get('frequency', 'weekly'),
            request.form.get('next_due_date', ''),
            auto_deduct=request.form.get('auto_deduct') == '1',
            late_fee_type=request.form.get('late_fee_type', 'none'),
            late_fee_value=request.form.get('late_fee_value', '0'),
        )
        db_module.log_activity(
            session.get('user_id'), 'bill_add',
            f'Added bill {bill["name"]} for {bill["user_name"]}'
        )
        flash('Household bill added.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bills'))


@app.route('/bills/<int:bill_id>/toggle', methods=['POST'])
@require_role('admin', 'parent')
def bills_toggle(bill_id):
    try:
        bill = db_module.get_household_bill(bill_id)
        if not bill:
            raise ValueError('Bill not found.')
        bill = db_module.set_household_bill_active(bill_id, not bill['is_active'])
        db_module.log_activity(
            session.get('user_id'), 'bill_toggle',
            f'{"Activated" if bill["is_active"] else "Paused"} bill {bill["name"]}'
        )
        flash(f'Bill {"activated" if bill["is_active"] else "paused"}.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bills'))


@app.route('/bills/<int:bill_id>/delete', methods=['POST'])
@require_role('admin', 'parent')
def bills_delete(bill_id):
    try:
        bill = db_module.delete_household_bill(bill_id)
        db_module.log_activity(
            session.get('user_id'), 'bill_delete',
            f'Deleted bill {bill["name"]} for {bill["user_name"]}'
        )
        flash('Bill deleted.', 'info')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bills'))


@app.route('/bills/run', methods=['POST'])
@require_role('admin', 'parent')
def bills_run():
    created = db_module.schedule_due_bills()
    fees = db_module.apply_overdue_late_fees()
    flash(
        f'Created {created} bill occurrence(s); applied {fees["fees_applied"]} late fee(s).',
        'success'
    )
    return redirect(url_for('bills'))


@app.route('/bills/occurrences/<int:occurrence_id>/pay', methods=['POST'])
@require_role('admin', 'parent')
def bill_occurrence_pay(occurrence_id):
    try:
        result = db_module.pay_bill_occurrence(
            occurrence_id, source='parent', created_by=session.get('user_id')
        )
        db_module.log_activity(
            session.get('user_id'), 'bill_pay',
            f'Paid {result["paid"]:.2f} toward {result["occurrence"]["name"]} for '
            f'{result["occurrence"]["user_name"]}'
        )
        flash(f'Bill payment recorded: {result["paid"]:.2f}.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('bills'))


@app.route('/marketplace')
@require_role('admin', 'parent')
def marketplace():
    orders = db_module.get_marketplace_orders(limit=300)
    children = db_module.get_children()
    return render_template(
        'marketplace.html',
        items=db_module.get_marketplace_items(),
        children=children,
        cash_balances={child['id']: db_module.get_cash_balance(child['id']) for child in children},
        pending_orders=[order for order in orders if order['status'] == 'pending'],
        approved_orders=[order for order in orders if order['status'] == 'approved'],
        history=[order for order in orders if order['status'] not in ('pending', 'approved')],
        categories=[
            ('item', 'Item', 'bi-bag-fill'),
            ('privilege', 'Privilege', 'bi-star-fill'),
            ('screen_time', 'Screen time', 'bi-display'),
        ],
    )


@app.route('/marketplace/items/add', methods=['POST'])
@require_role('admin', 'parent')
def marketplace_item_add():
    try:
        db_module.create_marketplace_item(
            request.form.get('name', ''),
            request.form.get('price', '0'),
            category=request.form.get('category', 'item'),
            description=request.form.get('description', ''),
            stock_quantity=request.form.get('stock_quantity'),
            icon=request.form.get('icon', 'bi-bag-fill'),
            color=request.form.get('color', '#10b981'),
            requires_approval=1 if request.form.get('requires_approval') else 0,
            sort_order=request.form.get('sort_order', '0'),
            currency_type=request.form.get('currency_type', 'token'),
            token_price=request.form.get('token_price'),
            cash_price=request.form.get('cash_price'),
        )
        flash('Marketplace item added.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('marketplace'))


@app.route('/marketplace/items/<int:item_id>/update', methods=['POST'])
@require_role('admin', 'parent')
def marketplace_item_update(item_id):
    try:
        db_module.update_marketplace_item(
            item_id,
            request.form.get('name', ''),
            request.form.get('price', '0'),
            category=request.form.get('category', 'item'),
            description=request.form.get('description', ''),
            stock_quantity=request.form.get('stock_quantity'),
            icon=request.form.get('icon', 'bi-bag-fill'),
            color=request.form.get('color', '#10b981'),
            requires_approval=1 if request.form.get('requires_approval') else 0,
            sort_order=request.form.get('sort_order', '0'),
            currency_type=request.form.get('currency_type', 'token'),
            token_price=request.form.get('token_price'),
            cash_price=request.form.get('cash_price'),
        )
        flash('Marketplace item updated.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('marketplace'))


@app.route('/marketplace/cash/<int:child_id>', methods=['POST'])
@require_role('admin', 'parent')
def marketplace_cash_adjust(child_id):
    try:
        amount = db_module._marketplace_money(request.form.get('amount'), 'Cash amount')
        direction = request.form.get('direction', 'add')
        if direction not in ('add', 'remove'):
            raise ValueError('Choose whether to add or remove cash.')
        description = request.form.get('description', '').strip() or 'Marketplace cash adjustment'
        db_module.adjust_cash_balance(
            child_id, amount if direction == 'add' else -amount,
            description=description, created_by=session.get('user_id')
        )
        flash('Cash balance updated.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('marketplace'))


@app.route('/marketplace/items/<int:item_id>/toggle', methods=['POST'])
@require_role('admin', 'parent')
def marketplace_item_toggle(item_id):
    item = db_module.get_marketplace_item(item_id)
    if not item:
        abort(404)
    db_module.set_marketplace_item_active(item_id, not item['is_active'])
    flash('Marketplace item availability updated.', 'info')
    return redirect(url_for('marketplace'))


@app.route('/marketplace/orders/<int:order_id>/approve', methods=['POST'])
@require_role('admin', 'parent')
def marketplace_order_approve(order_id):
    try:
        order = db_module.approve_marketplace_order(order_id, session.get('user_id'))
        db_module.log_activity(
            session.get('user_id'), 'marketplace_approve',
            f"Approved marketplace order #{order_id} for {order['user_name']}"
        )
        flash('Order approved. The child can now show the QR code for collection.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(_safe_referrer('marketplace'))


@app.route('/marketplace/orders/<int:order_id>/reject', methods=['POST'])
@require_role('admin', 'parent')
def marketplace_order_reject(order_id):
    try:
        order = db_module.reject_marketplace_order(
            order_id, session.get('user_id'), request.form.get('reason', '')
        )
        db_module.log_activity(
            session.get('user_id'), 'marketplace_reject',
            f"Rejected marketplace order #{order_id} for {order['user_name']}"
        )
        flash('Order rejected, stock restored and the child refunded.', 'info')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(_safe_referrer('marketplace'))


@app.route('/marketplace/orders/<int:order_id>/fulfill', methods=['POST'])
@require_role('admin', 'parent')
def marketplace_order_fulfill(order_id):
    try:
        order = db_module.fulfill_marketplace_order(order_id, session.get('user_id'))
        db_module.log_activity(
            session.get('user_id'), 'marketplace_fulfill',
            f"Fulfilled marketplace order #{order_id} for {order['user_name']}"
        )
        flash('Order fulfilled. The redemption is complete.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(_safe_referrer('marketplace'))


@app.route('/marketplace/verify', methods=['GET', 'POST'])
@app.route('/marketplace/verify/<token>', methods=['GET'])
@require_role('admin', 'parent')
def marketplace_verify(token=None):
    token = token or request.form.get('token') or request.args.get('token')
    token = (token or '').strip()
    if not token:
        flash('Enter a redemption code or scan the child\'s QR code.', 'warning')
        return redirect(url_for('marketplace'))
    order = db_module.get_marketplace_order_by_token(token)
    if not order:
        flash('That redemption code was not found.', 'danger')
        return redirect(url_for('marketplace'))
    return render_template(
        'marketplace_verify.html', order=order,
        qr_data_uri=marketplace_qr_data_uri(order['qr_token']),
    )


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
    color = request.form.get('color', '#10b981').strip() or '#10b981'
    status = request.form.get('status', 'active').strip()
    photo = request.files.get('photo')
    photo_path = save_image(photo, app.config['UPLOAD_FOLDER'], 'child', 400) if photo else None
    if not name:
        flash('First name is required.', 'danger')
        return redirect(url_for('manage_kids'))
    try:
        pin = db_module.validate_pin(pin)
    except ValueError as exc:
        flash(str(exc), 'danger')
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
    achievement_badges = db_module.get_child_achievements(kid_id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        surname = request.form.get('surname', '').strip() or None
        nickname = request.form.get('nickname', '').strip() or None
        pin = request.form.get('pin', '').strip() or None
        date_of_birth = request.form.get('date_of_birth', '').strip() or None
        color = request.form.get('color', '#10b981').strip() or '#10b981'
        status = request.form.get('status', 'active').strip()
        photo = request.files.get('photo')
        wallpaper = request.files.get('wallpaper')
        can_do_hard_chores = 1 if request.form.get('can_do_hard_chores') else 0
        updates = {'name': name, 'surname': surname, 'nickname': nickname,
                   'date_of_birth': date_of_birth, 'color': color, 'status': status,
                   'can_do_hard_chores': can_do_hard_chores}
        try:
            pin = db_module.validate_pin(pin)
        except ValueError as exc:
            flash(str(exc), 'danger')
            return render_template(
                'edit_kid.html', child=child, achievement_badges=achievement_badges
            )
        if pin:
            updates['pin'] = pin
        if photo and photo.filename:
            photo_path = save_image(photo, app.config['UPLOAD_FOLDER'], 'child', 400)
            if photo_path:
                updates['photo_path'] = photo_path
        if wallpaper and wallpaper.filename:
            wp_path = save_image(wallpaper, app.config['UPLOAD_FOLDER'], 'wallpaper', 1920)
            if wp_path:
                updates['wallpaper'] = wp_path
        db_module.update_user(kid_id, **updates)
        db_module.log_activity(session.get('user_id'), 'edit_child', f'Edited child: {name}')
        flash('Updated child profile.', 'success')
        return redirect(url_for('manage_kids'))
    return render_template(
        'edit_kid.html', child=child, achievement_badges=achievement_badges
    )


@app.route('/kids/<int:kid_id>/delete', methods=['POST'])
@require_role('admin')
def delete_kid(kid_id):
    child = db_module.get_user(kid_id)
    if not child or child['role'] != 'child':
        flash('Child not found.', 'danger')
        return redirect(url_for('manage_kids'))
    db_module.delete_user(kid_id)
    db_module.log_activity(session.get('user_id'), 'delete_child', f'Removed child: {child["name"]}')
    flash('Child removed.', 'info')
    return redirect(url_for('manage_kids'))


@app.route('/kids/<int:kid_id>/reset-pin', methods=['POST'])
@require_role('admin')
def reset_pin(kid_id):
    child = db_module.get_user(kid_id)
    if not child or child['role'] != 'child':
        flash('Child not found.', 'danger')
        return redirect(url_for('manage_kids'))
    new_pin = request.form.get('pin', '').strip() or None
    try:
        new_pin = db_module.validate_pin(new_pin)
    except ValueError as exc:
        flash(str(exc), 'danger')
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
    return render_template('chores.html', chores=chores, children=children, assignments=assignments,
                           chore_icons=list_chore_icons())


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
    picked_icon = request.form.get('chore_icon_file', '')
    if not chore_image and picked_icon in list_chore_icons():
        chore_image = f'{CHORE_ICON_PREFIX}{picked_icon}'
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
        picked_icon = request.form.get('chore_icon_file', '')
        if not (img_file and img_file.filename) and picked_icon in list_chore_icons():
            updates['chore_image'] = f'{CHORE_ICON_PREFIX}{picked_icon}'
        db_module.update_chore(chore_id, **updates)
        flash('Chore updated.', 'success')
        return redirect(url_for('manage_chores'))
    return render_template('edit_chore.html', chore=chore, chore_icons=list_chore_icons())


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
    if role not in ('admin', 'parent'):
        flash('Choose a valid staff role.', 'danger')
        return redirect(url_for('manage_parents'))
    if not name or not username or not password:
        flash('All fields are required.', 'danger')
        return redirect(url_for('manage_parents'))
    try:
        db_module.validate_password(password)
    except ValueError as exc:
        flash(str(exc), 'danger')
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
    if not user or user['role'] not in ('admin', 'parent'):
        flash('Staff user not found.', 'danger')
        return redirect(url_for('manage_parents'))
    if user['role'] == 'admin' and admin_count <= 1:
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
    if expires_at:
        try:
            expires_at = clock.to_utc_text(datetime.fromisoformat(expires_at).astimezone())
        except ValueError:
            flash('That expiry date is not valid.', 'danger')
            return redirect(url_for('manage_notices'))
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

def https_enabled():
    return os.environ.get('CHOREGREMLIN_HTTPS') == '1'


def ca_cert_path():
    return os.environ.get('CHOREGREMLIN_CA_CERT') or os.path.join(db_module.DATA_DIR, 'caddy-root.crt')


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
    https = https_enabled()
    scheme = 'https' if https else 'http'
    public_port = 443 if https else port
    suffix = '' if https else f':{port}'
    app_url = f"{scheme}://{ip}{suffix}"
    local_url = f"{scheme}://familyhub.local{suffix}"
    return {
        'ip': ip, 'hostname': hostname, 'app_url': app_url,
        'local_url': local_url, 'port': port, 'public_port': public_port,
        'https': https,
    }


@app.route('/trust')
def trust_page():
    net = get_network_info()
    return render_template('trust.html', net=net, ca_available=os.path.isfile(ca_cert_path()))


@app.route('/trust/ca.crt')
def trust_ca():
    path = ca_cert_path()
    if not os.path.isfile(path):
        abort(404)
    response = make_response(send_file(path, mimetype='application/x-x509-ca-cert',
                                       as_attachment=True,
                                       download_name='choregremlin-root.crt'))
    response.headers['Cache-Control'] = 'no-store'
    return response


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
    img = qr.make_image(fill_color='#0a0e1a', back_color='#10b981')
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
    user = db_module.get_user(parent_id)
    if not user or user['role'] not in ('admin', 'parent'):
        flash('Staff user not found.', 'danger')
        return redirect(url_for('manage_parents'))
    password = request.form.get('password', '').strip()
    try:
        db_module.validate_password(password)
    except ValueError as exc:
        flash(str(exc), 'danger')
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
    return render_template('currency.html', currency=currency, currencies=CURRENCIES)


@app.route('/currency/save', methods=['POST'])
@require_role('admin')
def currency_save():
    token_name = request.form.get('token_name', 'Widgets').strip()
    token_singular = request.form.get('token_singular', 'Widget').strip()
    token_plural = request.form.get('token_plural', 'Widgets').strip()
    gbp_value = request.form.get('gbp_value', '0.01').strip()
    emoji = request.form.get('token_emoji', '\U0001fa9f').strip()
    logo_type = request.form.get('logo_type', 'emoji').strip()
    currency_code = request.form.get('currency_code', 'GBP').strip().upper()
    if currency_code not in CURRENCY_BY_CODE:
        flash('That currency is not supported.', 'danger')
        return redirect(url_for('currency_page'))

    try:
        gbp_val = float(gbp_value)
    except ValueError:
        flash('Token value must be a number.', 'danger')
        return redirect(url_for('currency_page'))

    logo_path = None
    if logo_type == 'upload':
        logo_file = request.files.get('logo_file')
        if logo_file and logo_file.filename:
            logo_path = save_currency_logo(logo_file)

    db_module.save_currency_settings(token_name, token_singular, token_plural, gbp_val,
                                      logo_path=logo_path, logo_type=logo_type, emoji=emoji,
                                      currency_code=currency_code)
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
    return save_image(file, app.config['UPLOAD_FOLDER'], 'currency_logo', 64)


# --- Security & Remote Access ---

def _security_audit_context():
    admins = [
        user for user in db_module.get_all_users('admin')
        if user['is_active']
    ]
    admins_with_2fa = sum(
        1 for admin in admins if db_module.get_totp_secret(admin['id'])
    )
    backup_dir = os.path.join(db_module.DATA_DIR, 'backups')
    backup_count = 0
    if os.path.isdir(backup_dir):
        backup_count = len([
            name for name in os.listdir(backup_dir)
            if name.endswith('.db')
        ])
    data_dir_mode = None
    try:
        data_dir_mode = os.stat(db_module.DATA_DIR).st_mode & 0o777
    except OSError:
        pass
    route_endpoints = {
        rule.endpoint for rule in app.url_map.iter_rules()
        if rule.endpoint != 'static'
    }
    csrf_exempt_endpoints = {
        str(name).rsplit('.', 1)[-1].replace('_view', '')
        for name in (getattr(csrf, '_exempt_views', ()) or ())
    }
    jinja_autoescape = app.jinja_env.autoescape
    if not isinstance(jinja_autoescape, bool):
        jinja_autoescape = bool(jinja_autoescape)
    escaped = app.jinja_env.from_string('{{ probe }}').render(probe='<script>')
    return {
        'admin_count': len(admins),
        'admins_with_2fa': admins_with_2fa,
        'https': https_enabled(),
        'remote_access': db_module.get_setting('remote_access_enabled', '0') == '1',
        'csrf_enabled': app.config.get('WTF_CSRF_ENABLED', True),
        'csrf_exempt_endpoints': csrf_exempt_endpoints,
        'route_rules_complete': route_endpoints <= set(ROUTE_ACCESS),
        'login_lockout_enabled': (
            db_module.LOGIN_MAX_ATTEMPTS > 0 and db_module.LOGIN_LOCKOUT_MINUTES > 0
        ),
        'sql_parameter_probe': db_module.parameterized_query_probe(),
        'jinja_autoescape': jinja_autoescape,
        'xss_escape_probe': '<script>' not in escaped,
        'security_headers': bool(security_audit.SECURITY_HEADERS),
        'session_cookie_secure': app.config.get('SESSION_COOKIE_SECURE', False),
        'session_cookie_httponly': app.config.get('SESSION_COOKIE_HTTPONLY', False),
        'session_cookie_samesite': app.config.get('SESSION_COOKIE_SAMESITE', ''),
        'secret_key_length': len(app.config.get('SECRET_KEY') or ''),
        'backup_count': backup_count,
        'snapshot_count': len(db_module.get_system_snapshots(limit=10000)),
        'recent_failed_logins': db_module.get_failed_login_count(24),
        'data_dir_mode': data_dir_mode,
        'debug': bool(app.debug),
        'update_status': db_module.get_setting('last_update_status', 'unknown'),
    }


@app.route('/security/vulnerabilities')
@app.route('/security/audit')
@require_role('admin')
def security_audit_page():
    context = _security_audit_context()
    checks = security_audit.audit(context)
    compliance = security_audit.compliance_registry(context)
    return render_template(
        'security_audit.html', checks=checks,
        summary=security_audit.summary(checks),
        compliance=compliance,
        compliance_summary=security_audit.compliance_summary(compliance),
    )


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
                           recent_logins=recent_logins, https=https_enabled(),
                           ca_available=os.path.isfile(ca_cert_path()))


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


def two_factor_label(user):
    return user['email'] or user['username'] or user['name']


@app.route('/security/2fa/setup', methods=['GET', 'POST'])
@require_role('admin', 'parent', allow_pending=True)
def setup_2fa():
    user = g.user
    secret = session.get('totp_setup_secret')
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        if not secret:
            flash('Your setup session expired. Please scan the new QR code.', 'warning')
            return redirect(url_for('setup_2fa'))
        uri = generate_totp_uri(secret, two_factor_label(user))
        if not verify_totp(secret, code):
            flash('Invalid code. Please try again.', 'danger')
            return render_template('setup_2fa.html', secret=secret,
                                   qr_data_uri=totp_qr_data_uri(uri))
        db_module.clear_backup_codes(user['id'])
        db_module.set_totp_secret(user['id'], secret)
        db_module.enable_totp(user['id'])
        codes = generate_backup_codes()
        for code_str in codes:
            code_hash = hashlib.sha256(code_str.encode()).hexdigest()
            db_module.add_backup_code(user['id'], code_hash)
        session.pop('totp_setup_secret', None)
        if session.get('pending_2fa_forced') and session.get('pending_2fa_user_id') == user['id']:
            _clear_auth_session()
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['2fa_verified'] = True
            db_module.log_login_attempt(two_factor_label(user), client_ip(), True, '2fa_setup_complete')
        db_module.log_activity(user['id'], 'enable_2fa', 'Enabled 2FA')
        return render_template('setup_2fa.html', backup_codes=codes, success=True)
    if not secret:
        secret = generate_totp_secret()
        session['totp_setup_secret'] = secret
    uri = generate_totp_uri(secret, two_factor_label(user))
    return render_template('setup_2fa.html', secret=secret, qr_data_uri=totp_qr_data_uri(uri))


@app.route('/security/2fa/disable', methods=['POST'])
@require_role('admin', 'parent')
def disable_2fa():
    user = g.user
    if user['role'] == 'admin':
        flash('Two-factor authentication is mandatory for administrator accounts.', 'danger')
        return redirect(url_for('security_page'))
    db_module.disable_totp(user['id'])
    db_module.clear_backup_codes(user['id'])
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
                if field['type'] == 'color':
                    value = achievements.clean_color(value, default=field['default'])
            if key in db_module.UI_LAYOUT_SETTINGS:
                try:
                    db_module.set_ui_layout_setting(key, value)
                except ValueError:
                    db_module.set_ui_layout_setting(key, field['default'])
            else:
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
            wp_path = save_image(wallpaper, app.config['UPLOAD_FOLDER'], 'wallpaper', 1920)
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
                           stat_icons=stat_icons, record_counts=db_module.get_record_counts(),
                           data_dir=db_module.DATA_DIR)


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
        flash('Chore Gremlin is up to date.', 'success')
    else:
        flash('Could not check for updates (may not be deployed as a git repo).', 'warning')
    return redirect(url_for('system_info'))


# --- Snapshots & automated updates (Phase 15) ---

@app.route('/system/snapshots')
@require_role('admin')
def snapshots_page():
    return render_template(
        'snapshots.html',
        snapshots=db_module.get_system_snapshots(limit=100),
        usage=db_module.get_snapshot_storage_usage(),
        kinds=db_module.SNAPSHOT_KINDS,
        last_check=db_module.get_setting('last_update_check', ''),
        last_status=db_module.get_setting('last_update_status', 'unknown'),
        last_message=db_module.get_setting('last_update_message', ''),
        app_dir=APP_DIR,
        auto_update_enabled=db_module.get_setting('auto_update_enabled', '1') == '1',
    )


@app.route('/system/snapshots/create', methods=['POST'])
@require_role('admin')
def snapshot_create():
    try:
        snapshot = db_module.create_system_snapshot(
            request.form.get('label', ''),
            kind=request.form.get('kind', 'manual'),
            created_by=session.get('user_id'),
            note=request.form.get('note', ''),
        )
        db_module.prune_system_snapshots(keep=30)
        db_module.log_activity(
            session.get('user_id'), 'create_snapshot',
            f'Created snapshot: {snapshot["label"]}'
        )
        flash(f'Snapshot "{snapshot["label"]}" created.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('snapshots_page'))


@app.route('/system/snapshots/<int:snapshot_id>/restore', methods=['POST'])
@require_role('admin')
def snapshot_restore(snapshot_id):
    try:
        snapshot = db_module.restore_system_snapshot(
            snapshot_id, created_by=session.get('user_id'), safety=True
        )
        db_module.log_activity(
            session.get('user_id'), 'restore_snapshot',
            f'Restored snapshot: {snapshot["label"]}'
        )
        flash(
            f'Restored snapshot "{snapshot["label"]}". '
            'A safety snapshot was taken first.',
            'success'
        )
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('snapshots_page'))


@app.route('/system/snapshots/<int:snapshot_id>/delete', methods=['POST'])
@require_role('admin')
def snapshot_delete(snapshot_id):
    try:
        snapshot = db_module.delete_system_snapshot(snapshot_id)
        db_module.log_activity(
            session.get('user_id'), 'delete_snapshot',
            f'Deleted snapshot: {snapshot["label"]}'
        )
        flash(f'Snapshot "{snapshot["label"]}" deleted.', 'info')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('snapshots_page'))


@app.route('/system/update/check', methods=['POST'])
@require_role('admin')
def update_check():
    result = updater.check_for_updates(APP_DIR)
    db_module.set_setting('last_update_check', result['checked_at'])
    db_module.set_setting('last_update_status', result['status'])
    db_module.set_setting('last_update_message', result['output'][:1000])
    db_module.log_activity(
        session.get('user_id'), 'check_update',
        f"Update check: {result['status']}"
    )
    labels = {
        'available': ('A new update is available.', 'info'),
        'up_to_date': ('Chore Gremlin is up to date.', 'success'),
        'error': ('Could not check for updates.', 'warning'),
        'unknown': ('Update status could not be determined.', 'warning'),
    }
    message, category = labels.get(result['status'], labels['unknown'])
    flash(message, category)
    return redirect(url_for('snapshots_page'))


@app.route('/system/update/apply', methods=['POST'])
@require_role('admin')
def update_apply():
    try:
        snapshot = db_module.create_system_snapshot(
            label='Pre-update snapshot', kind='pre_update',
            created_by=session.get('user_id'),
            note='Created automatically before applying an update.',
        )
    except ValueError as exc:
        flash(f'Could not create a safety snapshot: {exc}', 'danger')
        return redirect(url_for('snapshots_page'))
    result = updater.apply_update(APP_DIR)
    db_module.set_setting('last_update_check', result['applied_at'])
    db_module.set_setting('last_update_status', result['status'])
    db_module.set_setting('last_update_message', result['output'][:1000])
    db_module.log_activity(
        session.get('user_id'), 'apply_update',
        f"Applied update: {result['status']} (snapshot #{snapshot['id']})"
    )
    if result['status'] == 'updated':
        flash(
            'Update applied. Restart the service to load the new code. '
            f'Rollback snapshot: {snapshot["label"]}.',
            'success'
        )
    else:
        flash(
            f'Update failed. Rollback snapshot "{snapshot["label"]}" is available.',
            'danger'
        )
    return redirect(url_for('snapshots_page'))


# --- Release bundles & tagging (Phase 17) ---

@app.route('/system/releases')
@require_role('admin')
def releases_page():
    current = release.read_version(APP_DIR)
    return render_template(
        'releases.html',
        current_version=current,
        suggested={
            'patch': release.bump_version(current, 'patch'),
            'minor': release.bump_version(current, 'minor'),
            'major': release.bump_version(current, 'major'),
        },
        bundles=release.list_bundles(RELEASE_DIR),
        release_dir=RELEASE_DIR,
        changelog=release.changelog_excerpt(APP_DIR),
        last_status=db_module.get_setting('last_release_status', ''),
        last_message=db_module.get_setting('last_release_message', ''),
    )


@app.route('/system/releases/build', methods=['POST'])
@require_role('admin')
def release_build():
    version = request.form.get('version') or release.read_version(APP_DIR)
    try:
        bundle = release.build_bundle(
            APP_DIR, version=version, out_dir=RELEASE_DIR,
            notes=request.form.get('notes', '').strip() or None,
        )
        db_module.set_setting('last_release_status', 'built')
        db_module.set_setting(
            'last_release_message', f"{bundle['filename']} ({bundle['size_human']})"
        )
        db_module.log_activity(
            session.get('user_id'), 'build_release',
            f"Built release {bundle['tag']} ({bundle['size_human']})"
        )
        flash(
            f'Release bundle {bundle["filename"]} built '
            f'({bundle["size_human"]}, sha256 {bundle["checksum"][:12]}...).',
            'success'
        )
    except (release.ReleaseError, OSError) as exc:
        db_module.set_setting('last_release_status', 'error')
        db_module.set_setting('last_release_message', str(exc))
        flash(f'Could not build release: {exc}', 'danger')
    return redirect(url_for('releases_page'))


@app.route('/system/releases/tag', methods=['POST'])
@require_role('admin')
def release_tag():
    version = request.form.get('version') or release.read_version(APP_DIR)
    try:
        result = release.tag_release(
            APP_DIR, version,
            message=request.form.get('message', '').strip() or None,
        )
    except release.ReleaseError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('releases_page'))
    db_module.set_setting('last_release_status', result['status'])
    db_module.set_setting(
        'last_release_message', result['output'][:1000] or result['tag']
    )
    if result['status'] == 'tagged':
        db_module.log_activity(
            session.get('user_id'), 'tag_release',
            f"Created release tag {result['tag']}"
        )
        flash(f'Created git tag {result["tag"]}. Push the tag to trigger CI.', 'success')
    elif result['status'] == 'exists':
        flash(f'Tag {result["tag"]} already exists.', 'warning')
    else:
        flash(
            f'Could not tag {result["tag"]}: '
            f'{result["output"] or "git is unavailable"}',
            'danger'
        )
    return redirect(url_for('releases_page'))


@app.route('/system/releases/download/<filename>')
@require_role('admin')
def release_download(filename):
    if (not filename.endswith('.zip') or filename != os.path.basename(filename)):
        abort(404)
    path = os.path.abspath(os.path.join(RELEASE_DIR, filename))
    if not path.startswith(os.path.abspath(RELEASE_DIR) + os.sep):
        abort(404)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=filename)


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

def _drop_view(drop):
    payload = dict(drop)
    seconds_remaining = 0
    if drop['expires_at']:
        try:
            seconds_remaining = max(0, int((clock.parse_utc(drop['expires_at']) - clock.utc_now()).total_seconds()))
        except (TypeError, ValueError):
            seconds_remaining = 0
    payload['seconds_remaining'] = seconds_remaining
    return payload


@app.route('/drop-chores')
@require_role('admin', 'parent')
def manage_drop_chores():
    db_module.update_drop_chore_points()
    drops = [_drop_view(drop) for drop in db_module.get_active_drop_chores()]
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
    drops = [_drop_view(drop) for drop in db_module.get_active_drop_chores()]
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
        db_module.award_drop_xp(child['id'], drop)
        db_module.log_activity(child['id'], 'claim_drop_chore',
                              f"Claimed: {drop['name']} for {drop['current_points']} points")
        flash(f'You claimed {drop["name"]} and earned {drop["current_points"]}!', 'success')
    else:
        flash('Too late - that chore was already taken!', 'danger')
    return redirect(url_for('kiosk_drop_chores'))


@app.route('/kiosk/drop-chores/<int:drop_id>/complete', methods=['POST'])
@kiosk_mode()
def kiosk_complete_drop_chore(drop_id):
    child = g.child
    try:
        result = db_module.complete_assigned_drop_chore(drop_id, child['id'])
    except ValueError as exc:
        hardware_beep('error')
        flash(str(exc), 'warning')
        return redirect(url_for('child_chores'))
    if not result:
        hardware_beep('error')
        flash('That drop chore is no longer assigned to you.', 'danger')
        return redirect(url_for('child_chores'))
    db_module.log_activity(
        child['id'], 'complete_drop_chore',
        f"Completed assigned drop chore: {result['drop']['name']}"
    )
    hardware_beep('success')
    if result['log']:
        flash('Great job! Your drop chore is waiting for a parent to approve it.', 'success')
    else:
        flash('Drop chore completed!', 'success')
    return redirect(url_for('child_chores'))


@app.route('/api/drop-chores')
def api_drop_chores():
    db_module.update_drop_chore_points()
    drops = [_drop_view(drop) for drop in db_module.get_active_drop_chores()]
    response = jsonify([{
        'id': d['id'], 'name': d['name'], 'current_points': d['current_points'],
        'initial_points': d['initial_points'], 'decay_per_minute': d['decay_per_minute'],
        'posted_at': d['posted_at'], 'expires_at': d['expires_at'],
        'seconds_remaining': d['seconds_remaining'],
        'chore_emoji': d['chore_emoji'], 'status': d['status']
    } for d in drops])
    response.headers['Cache-Control'] = 'no-store'
    return response


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


# --- Live SSE & push alerts (Phase 14) ---

def _live_event_frame(row):
    return events.format_sse({
        'id': row.get('id', 0),
        'type': row.get('event_type', 'message'),
        'data': {
            'id': row.get('id'),
            'title': row.get('title', ''),
            'body': row.get('body', ''),
            'payload': row.get('payload', {}),
            'user_id': row.get('user_id'),
            'child_id': row.get('child_id'),
            'created_at': row.get('created_at', ''),
        },
    })


@app.route('/events/stream')
def events_stream():
    once = request.args.get('once') == '1'
    since = request.args.get('since', 0, type=int) or 0

    def generate():
        yield 'retry: 3000\n\n'
        yield events.format_sse({
            'id': 0, 'type': 'ready',
            'data': {'ok': True, 'latest_event_id': db_module.get_latest_live_event_id()},
        })
        for row in db_module.get_live_events(after_id=since, limit=25):
            yield _live_event_frame(row)
        if once:
            return
        audience = events.subscribe()
        try:
            while True:
                try:
                    event = audience.get(timeout=15)
                except queue.Empty:
                    yield ': heartbeat\n\n'
                    continue
                yield events.format_sse(event)
        finally:
            events.unsubscribe(audience)

    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


@app.route('/api/alerts')
def alerts_feed():
    since = request.args.get('since', 0, type=int) or 0
    broadcasts = [dict(row) for row in db_module.get_active_broadcasts(limit=20)]
    live_events = db_module.get_live_events(after_id=since, limit=50)
    return jsonify({
        'broadcasts': broadcasts,
        'events': live_events,
        'latest_event_id': db_module.get_latest_live_event_id(),
        'subscribers': events.subscriber_count(),
    })


# --- PWA ---

@app.route('/manifest.json')
def manifest():
    app_name = db_module.get_setting('app_name', 'Chore Gremlin') if db_module.is_setup_complete() else 'Chore Gremlin'
    return jsonify({
        "name": app_name,
        "short_name": "Chore Gremlin",
        "description": "The little gremlin that gets the chores done",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0e1a",
        "theme_color": "#10b981",
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


@app.errorhandler(CSRFError)
def csrf_error(e):
    return render_template('error.html', code=400,
                           message='Your session expired or the form was not secure. Please go back and try again.'), 400


@app.errorhandler(500)
def server_error(e):
    app.logger.exception('Unhandled server error')
    return render_template('error.html', code=500,
                           message='Something went wrong. Please try again, or restart the app if it keeps happening.'), 500


# --- CLI ---

@app.cli.command('init-db')
def init_db_command():
    """Initialize the database."""
    db_module.init_db()
    print('Initialized the database.')


if __name__ == '__main__':
    db_module.init_db()
    port = int(os.environ.get('PORT', DEFAULT_PORT))
    app.run(host=os.environ.get('CHOREGREMLIN_BIND', '0.0.0.0'), port=port, debug=False)
