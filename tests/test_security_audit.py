"""Security hardening and vulnerability compliance dashboard checks."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-security-'))
os.environ.setdefault('SECRET_KEY', 'security-audit-test-secret-key-not-for-production')

import achievements  # noqa: E402
import db as db_module  # noqa: E402
import security_audit  # noqa: E402
import app as app_module  # noqa: E402


class ComplianceRegistryTests(unittest.TestCase):
    def good_context(self):
        return {
            'admin_count': 1,
            'admins_with_2fa': 1,
            'https': True,
            'remote_access': False,
            'csrf_enabled': True,
            'csrf_exempt_endpoints': {'kiosk_rfid_scan'},
            'route_rules_complete': True,
            'login_lockout_enabled': True,
            'sql_parameter_probe': True,
            'jinja_autoescape': True,
            'xss_escape_probe': True,
            'security_headers': True,
            'session_cookie_secure': True,
            'session_cookie_httponly': True,
            'session_cookie_samesite': 'Lax',
            'secret_key_length': 64,
            'backup_count': 2,
            'snapshot_count': 1,
            'recent_failed_logins': 0,
            'data_dir_mode': 0o700,
            'debug': False,
            'update_status': 'up_to_date',
        }

    def test_registry_covers_required_vulnerability_classes(self):
        names = [row['name'] for row in security_audit.VULNERABILITY_CLASSES]
        self.assertEqual(names, [
            'SQL Injection', 'CSRF', 'XSS', 'Broken Authentication',
            'Session Hijacking', 'Security Misconfiguration',
        ])
        rows = security_audit.compliance_registry(self.good_context())
        self.assertEqual([row['name'] for row in rows], names)
        self.assertTrue(all(row['status'] == 'protected' for row in rows))
        self.assertTrue(all(row['live'] for row in rows))
        summary = security_audit.compliance_summary(rows)
        self.assertEqual(summary['protected'], 6)
        self.assertEqual(summary['score'], 100)
        self.assertEqual(summary['worst'], 'protected')

    def test_registry_flags_vulnerable_controls(self):
        context = self.good_context()
        context.update({
            'csrf_enabled': False,
            'csrf_exempt_endpoints': {'kiosk_rfid_scan', 'delete_parent'},
            'sql_parameter_probe': False,
            'jinja_autoescape': False,
            'xss_escape_probe': False,
            'admin_count': 2,
            'admins_with_2fa': 0,
            'route_rules_complete': False,
            'login_lockout_enabled': False,
            'session_cookie_httponly': False,
            'session_cookie_samesite': '',
            'secret_key_length': 8,
            'security_headers': False,
            'debug': True,
            'data_dir_mode': 0o777,
            'remote_access': True,
            'https': False,
        })
        rows = {row['name']: row for row in security_audit.compliance_registry(context)}
        for name in rows:
            self.assertEqual(rows[name]['status'], 'vulnerable', name)
            self.assertFalse(rows[name]['live'], name)
            self.assertTrue(rows[name]['remediation'], name)
        summary = security_audit.compliance_summary(rows.values())
        self.assertEqual(summary['vulnerable'], 6)
        self.assertEqual(summary['worst'], 'vulnerable')

    def test_optional_https_gap_is_monitored_not_vulnerable(self):
        context = self.good_context()
        context['https'] = False
        context['session_cookie_secure'] = False
        rows = {row['name']: row for row in security_audit.compliance_registry(context)}
        self.assertEqual(rows['Session Hijacking']['status'], 'monitored')
        self.assertEqual(rows['Security Misconfiguration']['status'], 'monitored')
        self.assertEqual(rows['SQL Injection']['status'], 'protected')


class SecurityHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def test_client_ip_ignores_forwarded_header_unless_proxy_trusted(self):
        env = {'REMOTE_ADDR': '10.0.0.9', 'HTTP_X_FORWARDED_FOR': '203.0.113.5'}
        with mock.patch.dict(os.environ, {'CHOREGREMLIN_TRUST_PROXY': ''}):
            with app_module.app.test_request_context('/login', environ_base=env):
                self.assertEqual(app_module.client_ip(), '10.0.0.9')
        with mock.patch.dict(os.environ, {'CHOREGREMLIN_TRUST_PROXY': '1'}):
            with app_module.app.test_request_context('/login', environ_base=env):
                self.assertEqual(app_module.client_ip(), '203.0.113.5')

    def test_token_icon_escapes_emoji_and_rejects_unsafe_upload_paths(self):
        emoji = app_module.token_icon_for({'token_emoji': '<script>alert(1)</script>'})
        self.assertNotIn('<script>', str(emoji))
        self.assertIn('&lt;script&gt;', str(emoji))

        rejected = app_module.token_icon_for({
            'token_emoji': 'X',
            'token_logo_type': 'upload',
            'token_logo': '../../secret.png',
        })
        self.assertEqual(str(rejected), '')

        safe = app_module.token_icon_for({
            'token_emoji': 'X',
            'token_logo_type': 'upload',
            'token_logo': 'uploads/tokens/star.png',
        })
        self.assertIn('/static/uploads/tokens/star.png', str(safe))
        self.assertIn('<img', str(safe))

    def test_colors_are_validated_and_legacy_values_are_normalised(self):
        self.assertEqual(achievements.clean_color('#A1b2C3'), '#A1b2C3')
        self.assertEqual(
            achievements.clean_color('</style><script>alert(1)</script>'),
            '#10b981',
        )
        child_id = db_module.create_user(
            'Colour Child', None, None, role='child',
            color='</style><script>alert(1)</script>', status='not-a-status',
        )
        child = db_module.get_user(child_id)
        self.assertEqual(child['color'], '#10b981')
        self.assertEqual(child['status'], 'active')
        db = db_module.get_db()
        db.execute(
            "UPDATE users SET color=? WHERE id=?",
            ('red;}</style><script>alert(1)</script>', child_id),
        )
        db.commit()
        db_module.init_db()
        child = db_module.get_user(child_id)
        self.assertEqual(child['color'], '#10b981')

    def test_user_roles_are_validated_on_create_and_update(self):
        with self.assertRaises(ValueError):
            db_module.create_user('Bad Role', None, None, role='superuser')
        child_id = db_module.create_user(
            'Role Child', None, None, role='child', color='#123456'
        )
        with self.assertRaises(ValueError):
            db_module.update_user(child_id, role='superuser')
        db_module.update_user(child_id, role='parent', status='suspended', color='red')
        child = db_module.get_user(child_id)
        self.assertEqual(child['role'], 'parent')
        self.assertEqual(child['status'], 'active')
        self.assertEqual(child['color'], '#10b981')

    def test_parameterized_query_probe(self):
        self.assertTrue(db_module.parameterized_query_probe())


class SecurityAuditRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        admin = db_module.get_user_by_login('security_audit_admin')
        if not admin:
            db_module.create_user(
                'Security Audit Admin', None, 'security-audit-password',
                role='admin', username='security_audit_admin',
            )
            admin = db_module.get_user_by_login('security_audit_admin')
        db_module.set_totp_secret(admin['id'], 'JBSWY3DPEHPK3PXP')
        db_module.enable_totp(admin['id'])
        cls.admin_id = admin['id']
        cls.parent_id = db_module.create_user(
            'Security Audit Parent', None, 'security-parent-password',
            role='parent', username='security_audit_parent',
        )
        cls.child_id = db_module.create_user(
            'Security Audit Child', None, None, role='child', pin='1357'
        )
        cls.previous_csrf = app_module.app.config.get('WTF_CSRF_ENABLED', True)
        app_module.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.previous_csrf
        cls.ctx.pop()

    def login_admin(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = self.admin_id

    def login_parent(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = self.parent_id

    def test_dashboard_loads_every_vulnerability_class(self):
        self.login_admin()
        for path in ('/security/audit', '/security/vulnerabilities'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Security Audit', response.data)
            self.assertIn(b'Vulnerability Classes', response.data)
            self.assertIn(b'SQL Injection', response.data)
            self.assertIn(b'Broken Authentication', response.data)
            self.assertIn(b'Protected', response.data)
            self.assertIn(b'Monitored', response.data)
            self.assertIn(b'Vulnerable', response.data)

    def test_dashboard_is_admin_only(self):
        self.login_parent()
        response = self.client.get('/security/vulnerabilities')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            app_module.ROUTE_ACCESS.get('security_audit_page'), 'admin'
        )

    def test_role_targeted_mutations_reject_wrong_user_type(self):
        self.login_admin()
        self.client.post(f'/kids/{self.parent_id}/delete')
        self.assertIsNotNone(db_module.get_user(self.parent_id))

        self.client.post(f'/kids/{self.parent_id}/reset-pin', data={'pin': '9999'})
        parent = db_module.get_user(self.parent_id)
        self.assertIsNone(parent['pin'])

        self.client.post(f'/parents/{self.child_id}/delete')
        self.assertIsNotNone(db_module.get_user(self.child_id))

        self.client.post(
            f'/parents/{self.child_id}/reset-password',
            data={'password': 'this-should-never-be-saved'},
        )
        child = db_module.get_user(self.child_id)
        self.assertIsNone(child['password_hash'])

    def test_login_audit_uses_socket_address_not_spoofed_forwarded_header(self):
        response = self.client.post(
            '/login',
            data={'username': 'nobody-at-all', 'password': 'wrong-password'},
            headers={'X-Forwarded-For': '203.0.113.99'},
        )
        self.assertEqual(response.status_code, 200)
        attempt = db_module.get_db().execute(
            "SELECT * FROM login_audit WHERE email=? ORDER BY id DESC LIMIT 1",
            ('nobody-at-all',),
        ).fetchone()
        self.assertIsNotNone(attempt)
        self.assertNotEqual(attempt['ip_address'], '203.0.113.99')


if __name__ == '__main__':
    unittest.main()
