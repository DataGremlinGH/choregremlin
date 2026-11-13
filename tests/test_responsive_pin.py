"""Tests for the responsive PIN interfaces and 4-10 digit adult PINs."""
import base64
import hashlib
import hmac
import os
import struct
import sys
import tempfile
import time
import unittest
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-responsive-pin-'))
os.environ.setdefault('SECRET_KEY', 'responsive-pin-test-secret-key-not-for-production')

import db as db_module  # noqa: E402
import app as app_module  # noqa: E402

ADMIN_PASSWORD = 'responsive-pin-admin-password'
PARENT_PASSWORD = 'responsive-pin-parent-password'
ADMIN_TOTP_SECRET = 'JBSWY3DPEHPK3PXP'
_FIXTURES = {}
_FIXTURE_CONTEXT = None


def current_totp(secret):
    key = base64.b32decode(secret + '=' * (-len(secret) % 8))
    counter = int(time.time() // 30)
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value).zfill(6)[-6:]


class _ModalPlacementParser(HTMLParser):
    """Detect whether a modal element is nested inside a .fh-card ancestor."""

    VOID = {
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr',
    }

    def __init__(self, modal_id):
        super().__init__(convert_charrefs=True)
        self.modal_id = modal_id
        self.stack = []
        self.found = False
        self.inside_card = False

    def _record(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id') == self.modal_id:
            self.found = True
            self.inside_card = any('fh-card' in classes for _, classes in self.stack)
        if tag not in self.VOID:
            self.stack.append((tag, (attrs.get('class') or '').split()))

    def handle_starttag(self, tag, attrs):
        self._record(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._record(tag, attrs)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def _ensure_fixtures():
    """Create the shared accounts once for every test class in this module."""
    global _FIXTURE_CONTEXT
    if _FIXTURES:
        return _FIXTURES

    db_module.init_db()
    _FIXTURE_CONTEXT = app_module.app.app_context()
    _FIXTURE_CONTEXT.push()

    def staff(name, username, pin):
        existing = db_module.get_user_by_login(username)
        if existing:
            db_module.set_pin(existing['id'], pin)
            return existing['id']
        return db_module.create_user(
            name, None, PARENT_PASSWORD, role='parent',
            username=username, pin=pin
        )

    admin = db_module.get_user_by_login('responsive_pin_admin')
    if admin:
        admin_id = admin['id']
    else:
        admin_id = db_module.create_user(
            'Responsive PIN Admin', None, ADMIN_PASSWORD,
            role='admin', username='responsive_pin_admin'
        )
    db_module.set_totp_secret(admin_id, 'JBSWY3DPEHPK3PXP')
    db_module.enable_totp(admin_id)

    child = db_module.get_user_by_login('responsive_pin_child')
    child_id = child['id'] if child else db_module.create_user(
        'Responsive PIN Child', None, None, role='child', pin='987654321',
        username='responsive_pin_child'
    )
    db_module.set_pin(child_id, '987654321')

    _FIXTURES.update({
        'admin_id': admin_id,
        'login_parent_id': staff('Responsive PIN Parent', 'responsive_pin_parent', '2468'),
        'target_parent_id': staff('Responsive PIN Target', 'responsive_pin_target', '1111'),
        'self_parent_id': staff('Responsive PIN Self', 'responsive_pin_self', '2222'),
        'pin_child_id': child_id,
    })
    return _FIXTURES


def tearDownModule():
    global _FIXTURE_CONTEXT
    if _FIXTURE_CONTEXT is not None:
        _FIXTURE_CONTEXT.pop()
        _FIXTURE_CONTEXT = None


class AdultPinValidationTests(unittest.TestCase):
    def test_accepts_four_to_ten_digits(self):
        for pin in ('1234', '24680', '1234567890', '0000'):
            self.assertEqual(app_module.validate_adult_pin(pin), pin)

    def test_rejects_wrong_lengths_and_non_digits(self):
        for pin in ('', None, '123', '12345678901', '12ab', '12 34', '１２３４'):
            with self.assertRaises(ValueError):
                app_module.validate_adult_pin(pin)


class ResponsivePinTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for key, value in _ensure_fixtures().items():
            setattr(cls, key, value)
        cls.previous_csrf = app_module.app.config.get('WTF_CSRF_ENABLED', True)

    @classmethod
    def tearDownClass(cls):
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.previous_csrf

    def setUp(self):
        app_module.app.config['WTF_CSRF_ENABLED'] = False
        db_module.clear_lockout('responsive_pin_parent', '127.0.0.1')
        db_module.set_pin(self.login_parent_id, '2468')
        db_module.set_pin(self.target_parent_id, '1111')
        db_module.set_pin(self.self_parent_id, '2222')
        self.client = app_module.app.test_client()
        with self.client.session_transaction() as sess:
            sess.clear()

    def login_as(self, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['role'] = db_module.get_user(user_id)['role']
            sess['2fa_verified'] = True


class ResponsivePinMarkupTests(ResponsivePinTestCase):
    def test_login_page_has_keypad_and_masked_keyboard_input(self):
        page = self.client.get('/login')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        self.assertIn('id="pinForm"', html)
        self.assertIn('id="pinDisplay"', html)
        self.assertIn('id="pinInput"', html)
        self.assertIn('type="password"', html)
        self.assertIn('inputmode="numeric"', html)
        self.assertIn('fh-pin-input-wrap', html)
        self.assertIn('fh-pin-pad', html)
        self.assertIn('data-key="backspace"', html)
        self.assertIn('data-key="clear"', html)
        self.assertIn('data-key="go"', html)
        self.assertIn('data-pin-min="4"', html)
        self.assertIn('data-pin-max="10"', html)
        self.assertIn('4–10 digits', html)
        self.assertIn('Use password instead', html)

    def test_kiosk_pin_page_has_keypad_and_masked_keyboard_input(self):
        page = self.client.get(f'/kiosk/select/{self.pin_child_id}')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        self.assertIn('id="pinForm"', html)
        self.assertIn('id="pinDisplay"', html)
        self.assertIn('id="pinInput"', html)
        self.assertIn('inputmode="numeric"', html)
        self.assertIn('fh-pin-pad', html)
        self.assertIn('data-key="backspace"', html)
        self.assertIn('data-pin-max="64"', html)

    def test_parent_page_offers_pin_management(self):
        self.login_as(self.admin_id)
        page = self.client.get('/parents')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        self.assertIn(f'/parents/{self.target_parent_id}/reset-pin', html)
        self.assertIn('Set Sign-in PIN', html)
        self.assertIn('4–10 digits', html)

    def test_family_page_offers_self_service_pin_form(self):
        self.login_as(self.self_parent_id)
        page = self.client.get('/family')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        self.assertIn('/account/pin', html)
        self.assertIn('Sign-in PIN', html)
        self.assertIn('name="current_pin"', html)
        self.assertIn('name="new_pin"', html)
        self.assertIn('name="confirm_pin"', html)

    def test_pin_modal_is_not_nested_inside_a_card(self):
        self.login_as(self.admin_id)
        page = self.client.get('/parents')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        parser = _ModalPlacementParser(f'resetPinModal{self.target_parent_id}')
        parser.feed(html)
        self.assertTrue(parser.found, 'Set Sign-in PIN modal is missing')
        self.assertFalse(
            parser.inside_card,
            'PIN modal must live outside .fh-card so the backdrop cannot cover it',
        )
        self.assertIn('data-fh-autofocus', html)
        self.assertIn('data-bs-backdrop="true"', html)


class AdminPasswordOnlyLoginTests(ResponsivePinTestCase):
    def test_admin_login_page_has_no_pin_controls(self):
        page = self.client.get('/admin/login')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        self.assertIn('Administrator Sign In', html)
        self.assertIn('name="password"', html)
        self.assertNotIn('pinForm', html)
        self.assertNotIn('pinInput', html)
        self.assertNotIn('fh-pin-pad', html)
        self.assertNotIn('name="pin"', html)

    def test_admin_can_sign_in_with_password_and_totp(self):
        response = self.client.post('/admin/login', data={
            'username': 'responsive_pin_admin',
            'password': ADMIN_PASSWORD,
            'totp_code': current_totp(ADMIN_TOTP_SECRET),
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard', response.headers['Location'])
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('user_id'), self.admin_id)

    def test_admin_pin_is_rejected_on_admin_login(self):
        db_module.set_pin(self.admin_id, '4321')
        response = self.client.post('/admin/login', data={
            'username': 'responsive_pin_admin',
            'pin': '4321',
        })
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    def test_admin_pin_is_rejected_on_shared_login(self):
        db_module.set_pin(self.admin_id, '4321')
        response = self.client.post('/login', data={
            'username': 'responsive_pin_admin',
            'pin': '4321',
        })
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    def test_parent_cannot_use_admin_login(self):
        response = self.client.post('/admin/login', data={
            'username': 'responsive_pin_parent',
            'password': PARENT_PASSWORD,
        })
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    def test_admin_rows_do_not_offer_pin_reset(self):
        self.login_as(self.admin_id)
        html = self.client.get('/parents').get_data(as_text=True)
        self.assertNotIn(f'/parents/{self.admin_id}/reset-pin', html)

    def test_admin_pin_reset_route_rejects_admin(self):
        self.login_as(self.admin_id)
        before = db_module.get_user(self.admin_id)['pin']
        response = self.client.post(
            f'/parents/{self.admin_id}/reset-pin', data={'pin': '9876'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_user(self.admin_id)['pin'], before)

    def test_admin_cannot_update_own_pin(self):
        self.login_as(self.admin_id)
        before = db_module.get_user(self.admin_id)['pin']
        response = self.client.post('/account/pin', data={
            'new_pin': '13579',
            'confirm_pin': '13579',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_user(self.admin_id)['pin'], before)


class AdultPinLoginTests(ResponsivePinTestCase):
    def test_parent_can_sign_in_with_four_digit_pin(self):
        response = self.client.post('/login', data={
            'username': 'responsive_pin_parent',
            'pin': '2468',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard', response.headers['Location'])
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('user_id'), self.login_parent_id)

    def test_parent_can_sign_in_with_ten_digit_pin(self):
        db_module.set_pin(self.login_parent_id, '1234567890')
        try:
            response = self.client.post('/login', data={
                'username': 'responsive_pin_parent',
                'pin': '1234567890',
            })
            self.assertEqual(response.status_code, 302)
            with self.client.session_transaction() as sess:
                self.assertEqual(sess.get('user_id'), self.login_parent_id)
        finally:
            db_module.set_pin(self.login_parent_id, '2468')

    def test_parent_can_still_sign_in_with_password(self):
        response = self.client.post('/login', data={
            'username': 'responsive_pin_parent',
            'password': PARENT_PASSWORD,
        })
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('user_id'), self.login_parent_id)

    def test_wrong_pin_is_rejected(self):
        response = self.client.post('/login', data={
            'username': 'responsive_pin_parent',
            'pin': '9999',
        })
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    def test_three_digit_pin_is_rejected(self):
        response = self.client.post('/login', data={
            'username': 'responsive_pin_parent',
            'pin': '246',
        })
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    def test_eleven_digit_pin_is_rejected(self):
        response = self.client.post('/login', data={
            'username': 'responsive_pin_parent',
            'pin': '12345678901',
        })
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    def test_non_numeric_pin_is_rejected(self):
        response = self.client.post('/login', data={
            'username': 'responsive_pin_parent',
            'pin': '12ab',
        })
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))


class AdultPinManagementTests(ResponsivePinTestCase):
    def test_admin_can_set_staff_pin(self):
        self.login_as(self.admin_id)
        response = self.client.post(
            f'/parents/{self.target_parent_id}/reset-pin',
            data={'pin': '9876'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(db_module.verify_user_pin(
            db_module.get_user(self.target_parent_id), '9876'
        ))

    def test_admin_pin_reset_rejects_short_pin(self):
        self.login_as(self.admin_id)
        before = db_module.get_user(self.target_parent_id)
        response = self.client.post(
            f'/parents/{self.target_parent_id}/reset-pin',
            data={'pin': '123'}
        )
        self.assertEqual(response.status_code, 302)
        after = db_module.get_user(self.target_parent_id)
        self.assertEqual(after['pin'], before['pin'])

    def test_admin_pin_reset_rejects_eleven_digit_pin(self):
        self.login_as(self.admin_id)
        before = db_module.get_user(self.target_parent_id)
        response = self.client.post(
            f'/parents/{self.target_parent_id}/reset-pin',
            data={'pin': '12345678901'}
        )
        self.assertEqual(response.status_code, 302)
        after = db_module.get_user(self.target_parent_id)
        self.assertEqual(after['pin'], before['pin'])

    def test_parent_can_update_own_pin(self):
        self.login_as(self.self_parent_id)
        response = self.client.post('/account/pin', data={
            'current_pin': '2222',
            'new_pin': '13579',
            'confirm_pin': '13579',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(db_module.verify_user_pin(
            db_module.get_user(self.self_parent_id), '13579'
        ))

    def test_self_service_rejects_wrong_current_pin(self):
        self.login_as(self.self_parent_id)
        before = db_module.get_user(self.self_parent_id)
        response = self.client.post('/account/pin', data={
            'current_pin': '0000',
            'new_pin': '13579',
            'confirm_pin': '13579',
        })
        self.assertEqual(response.status_code, 302)
        after = db_module.get_user(self.self_parent_id)
        self.assertEqual(after['pin'], before['pin'])

    def test_self_service_rejects_mismatched_confirmation(self):
        self.login_as(self.self_parent_id)
        before = db_module.get_user(self.self_parent_id)
        response = self.client.post('/account/pin', data={
            'current_pin': '2222',
            'new_pin': '13579',
            'confirm_pin': '24680',
        })
        self.assertEqual(response.status_code, 302)
        after = db_module.get_user(self.self_parent_id)
        self.assertEqual(after['pin'], before['pin'])

    def test_self_service_rejects_invalid_length(self):
        self.login_as(self.self_parent_id)
        before = db_module.get_user(self.self_parent_id)
        response = self.client.post('/account/pin', data={
            'current_pin': '2222',
            'new_pin': '123',
            'confirm_pin': '123',
        })
        self.assertEqual(response.status_code, 302)
        after = db_module.get_user(self.self_parent_id)
        self.assertEqual(after['pin'], before['pin'])

    def test_add_parent_accepts_optional_pin(self):
        self.login_as(self.admin_id)
        response = self.client.post('/parents/add', data={
            'name': 'Responsive Added Parent',
            'username': 'responsive_added_parent',
            'password': PARENT_PASSWORD,
            'pin': '4321',
            'role': 'parent',
        })
        self.assertEqual(response.status_code, 302)
        added = db_module.get_user_by_login('responsive_added_parent')
        self.assertIsNotNone(added)
        self.assertTrue(db_module.verify_user_pin(added, '4321'))

    def test_add_parent_rejects_short_pin(self):
        self.login_as(self.admin_id)
        response = self.client.post('/parents/add', data={
            'name': 'Responsive Bad PIN Parent',
            'username': 'responsive_bad_pin_parent',
            'password': PARENT_PASSWORD,
            'pin': '123',
            'role': 'parent',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db_module.get_user_by_login('responsive_bad_pin_parent'))


if __name__ == '__main__':
    unittest.main()
