"""Security headers and audit checks for Phase 16."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase16-'))
os.environ.setdefault('SECRET_KEY', 'phase16-test-secret-key-not-for-production')

import security_audit  # noqa: E402
import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class SecurityAuditHelperTests(unittest.TestCase):
    def good_context(self):
        return {
            'admin_count': 1,
            'admins_with_2fa': 1,
            'https': True,
            'remote_access': True,
            'csrf_enabled': True,
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

    def test_good_context_passes_every_check(self):
        checks = security_audit.audit(self.good_context())
        self.assertEqual(len(checks), 12)
        self.assertTrue(all(check['status'] == 'pass' for check in checks))
        result = security_audit.summary(checks)
        self.assertEqual(result['score'], 100)
        self.assertEqual(result['worst'], 'pass')
        self.assertEqual(result['pass'], 12)

    def test_bad_context_flags_failures_and_warnings(self):
        context = self.good_context()
        context.update({
            'admin_count': 2,
            'admins_with_2fa': 0,
            'https': False,
            'remote_access': True,
            'csrf_enabled': False,
            'session_cookie_secure': False,
            'session_cookie_httponly': False,
            'session_cookie_samesite': '',
            'secret_key_length': 4,
            'backup_count': 0,
            'snapshot_count': 0,
            'recent_failed_logins': 12,
            'data_dir_mode': 0o702,
            'debug': True,
            'update_status': 'error',
        })
        checks = {check['key']: check for check in security_audit.audit(context)}
        self.assertEqual(checks['admin_2fa']['status'], 'fail')
        self.assertEqual(checks['https']['status'], 'warn')
        self.assertEqual(checks['remote_access']['status'], 'fail')
        self.assertEqual(checks['csrf']['status'], 'fail')
        self.assertEqual(checks['session_cookie']['status'], 'fail')
        self.assertEqual(checks['secret_key']['status'], 'fail')
        self.assertEqual(checks['backups']['status'], 'warn')
        self.assertEqual(checks['snapshots']['status'], 'warn')
        self.assertEqual(checks['failed_logins']['status'], 'warn')
        self.assertEqual(checks['data_dir']['status'], 'fail')
        self.assertEqual(checks['debug']['status'], 'fail')
        self.assertEqual(checks['updates']['status'], 'warn')
        result = security_audit.summary(list(checks.values()))
        self.assertEqual(result['worst'], 'fail')
        self.assertGreater(result['fail'], 0)
        self.assertGreater(result['warn'], 0)

    def test_missing_data_dir_permissions_warn(self):
        context = self.good_context()
        context['data_dir_mode'] = None
        checks = {check['key']: check for check in security_audit.audit(context)}
        self.assertEqual(checks['data_dir']['status'], 'warn')

    def test_security_headers(self):
        plain = security_audit.headers_for(False)
        self.assertEqual(plain['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(plain['X-Frame-Options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", plain['Content-Security-Policy'])
        self.assertNotIn('Strict-Transport-Security', plain)
        secure = security_audit.headers_for(True)
        self.assertIn('Strict-Transport-Security', secure)


class SecurityAuditRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        admin = db_module.get_user_by_login('phase16_admin')
        if not admin:
            db_module.create_user(
                'Phase 16 Admin', None, 'phase16-admin-password',
                role='admin', username='phase16_admin'
            )
            admin = db_module.get_user_by_login('phase16_admin')
        db_module.set_totp_secret(admin['id'], 'JBSWY3DPEHPK3PXP')
        db_module.enable_totp(admin['id'])
        cls.admin_id = admin['id']
        cls.parent_id = db_module.create_user(
            'Phase 16 Parent', None, None,
            role='parent', username='phase16_parent'
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

    def test_login_response_has_security_headers(self):
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertIn('Content-Security-Policy', response.headers)
        self.assertIn('Referrer-Policy', response.headers)

    def test_security_audit_page_loads(self):
        self.login_admin()
        response = self.client.get('/security/audit')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Security Audit', response.data)
        self.assertIn(b'Audit score', response.data)
        self.assertIn(b'Administrator two-factor authentication', response.data)

    def test_parent_cannot_open_audit(self):
        self.login_parent()
        response = self.client.get('/security/audit')
        self.assertEqual(response.status_code, 403)

    def test_security_audit_route_access_rule(self):
        self.assertEqual(
            app_module.ROUTE_ACCESS.get('security_audit_page'), 'admin'
        )

    def test_failed_login_count_helper(self):
        self.assertGreaterEqual(db_module.get_failed_login_count(24), 0)


if __name__ == '__main__':
    unittest.main()
