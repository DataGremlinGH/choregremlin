"""Focused tests for Phase 3 access control and mandatory admin 2FA."""
import base64
import hashlib
import hmac
import os
import re
import struct
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase3-'))
os.environ.setdefault('SECRET_KEY', 'phase3-test-secret-key-not-for-production')

import db as db_module  # noqa: E402
import app as app_module  # noqa: E402

CSRF_PATTERN = re.compile(r'name="csrf-token" content="([^"]+)"')
SECRET_PATTERN = re.compile(r'<div class="fh-totp-secret">([^<]+)</div>')
BACKUP_PATTERN = re.compile(r'<div class="fh-backup-code">([^<]+)</div>')
PASSWORD = 'phase3-test-password'


def csrf(client, path):
    response = client.get(path)
    match = CSRF_PATTERN.search(response.get_data(as_text=True))
    return match.group(1) if match else ''


def current_totp(secret):
    key = base64.b32decode(secret + '=' * (-len(secret) % 8))
    counter = int(time.time() // 30)
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value).zfill(6)[-6:]


class Phase3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def admin(self):
        admin = db_module.get_user_by_login('phase3_admin')
        if not admin:
            db_module.create_user('Phase 3 Admin', None, PASSWORD, role='admin', username='phase3_admin')
            admin = db_module.get_user_by_login('phase3_admin')
        return admin

    def login(self, client=None, totp_code=''):
        client = client or self.client
        response = client.post('/login', data={
            'username': 'phase3_admin',
            'password': PASSWORD,
            'totp_code': totp_code,
            'csrf_token': csrf(client, '/login'),
        })
        return response

    def enroll(self):
        admin = self.admin()
        secret = 'JBSWY3DPEHPK3PXP'
        db_module.set_totp_secret(admin['id'], secret)
        db_module.enable_totp(admin['id'])
        return secret

    def logged_in_client(self):
        self.client.get('/logout')
        secret = self.enroll()
        response = self.login(totp_code=current_totp(secret))
        self.assertIn('/dashboard', response.headers['Location'])
        return self.client

    def test_admin_is_forced_to_enroll_2fa_then_backup_codes_are_single_use(self):
        self.client.get('/logout')
        admin = self.admin()
        db_module.disable_totp(admin['id'])
        db_module.clear_backup_codes(admin['id'])

        response = self.login()
        self.assertIn('/security/2fa/setup', response.headers['Location'])

        setup_page = self.client.get('/security/2fa/setup')
        self.assertEqual(setup_page.status_code, 200)
        page = setup_page.get_data(as_text=True)
        secret = SECRET_PATTERN.search(page).group(1)
        token = CSRF_PATTERN.search(page).group(1)
        self.assertTrue(secret)

        response = self.client.post('/security/2fa/setup', data={
            'code': current_totp(secret),
            'csrf_token': token,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'2FA Enabled', response.get_data())
        self.assertIsNotNone(db_module.get_totp_secret(admin['id']))

        codes = BACKUP_PATTERN.findall(response.get_data(as_text=True))
        self.assertEqual(len(codes), 8)
        self.assertEqual(self.client.get('/settings').status_code, 200)

        self.client.get('/logout')
        response = self.login(totp_code=codes[0])
        self.assertIn('/dashboard', response.headers['Location'])

        self.client.get('/logout')
        response = self.login(totp_code=codes[0])
        self.assertNotIn('/dashboard', response.headers.get('Location', ''))
        self.assertEqual(response.status_code, 200)

    def test_every_route_has_an_explicit_access_rule(self):
        endpoints = {rule.endpoint for rule in app_module.app.url_map.iter_rules()}
        endpoints.discard('static')
        self.assertEqual(endpoints, set(app_module.ROUTE_ACCESS))

    def test_unauthenticated_pages_are_fail_closed_and_trust_page_is_public(self):
        client = app_module.app.test_client()
        response = client.get('/settings')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])
        self.assertEqual(client.get('/trust').status_code, 200)

    def test_admin_cannot_disable_2fa(self):
        client = self.logged_in_client()
        response = client.post('/security/2fa/disable', data={
            'csrf_token': csrf(client, '/security'),
        })
        self.assertEqual(response.status_code, 302)
        admin = self.admin()
        self.assertIsNotNone(db_module.get_totp_secret(admin['id']))

    def test_disabled_admin_cannot_keep_using_existing_session(self):
        client = self.logged_in_client()
        admin = self.admin()
        db_module.update_user(admin['id'], is_active=0)
        response = client.get('/settings')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])
        db_module.update_user(admin['id'], is_active=1)


if __name__ == '__main__':
    unittest.main()
