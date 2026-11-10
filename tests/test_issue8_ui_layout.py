"""Issue 8: admin menu position and button theme preferences."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-issue8-'))
os.environ.setdefault('SECRET_KEY', 'issue8-test-secret-key-not-for-production')

import db as db_module  # noqa: E402
import app as app_module  # noqa: E402

PASSWORD = 'issue8-test-password'


class UILayoutPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.client = app_module.app.test_client()
        cls.old_csrf = app_module.app.config.get('WTF_CSRF_ENABLED', True)
        app_module.app.config['WTF_CSRF_ENABLED'] = False

        admin = db_module.get_user_by_login('issue8_admin')
        if not admin:
            db_module.create_user('Issue 8 Admin', None, PASSWORD, role='admin', username='issue8_admin')
            admin = db_module.get_user_by_login('issue8_admin')
        db_module.set_totp_secret(admin['id'], 'JBSWY3DPEHPK3PXP')
        db_module.enable_totp(admin['id'])
        cls.admin = admin

    @classmethod
    def tearDownClass(cls):
        db_module.set_ui_layout_setting('menu_position', 'left')
        db_module.set_ui_layout_setting('button_theme', 'default')
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.old_csrf
        cls.ctx.pop()

    def login(self):
        self.client.get('/logout')
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.admin['id']

    def test_defaults_and_aliases_are_normalised(self):
        db_module.set_ui_layout_setting('menu_position', 'left')
        db_module.set_ui_layout_setting('button_theme', 'default')
        self.assertEqual(db_module.get_ui_layout_settings(), {
            'menu_position': 'left',
            'button_theme': 'default',
        })

        self.assertEqual(db_module.set_ui_layout_setting('menu_position', 'Top Right'), 'top_right')
        self.assertEqual(db_module.set_ui_layout_setting('button_theme', 'Flat/Modern'), 'flat')
        self.assertEqual(db_module.get_ui_layout_settings(), {
            'menu_position': 'top_right',
            'button_theme': 'flat',
        })
        with self.assertRaises(ValueError):
            db_module.set_ui_layout_setting('menu_position', 'somewhere-else')
        with self.assertRaises(ValueError):
            db_module.set_ui_layout_setting('button_theme', 'disco')

    def test_admin_can_save_layout_preferences_and_they_render(self):
        self.login()
        response = self.client.post('/settings', data={
            'app_name': 'Chore Gremlin',
            'theme_color': '#10b981',
            'brightness_mode': 'dark',
            'menu_position': 'top_right',
            'button_theme': 'cyber',
            'auto_update_enabled': '1',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_ui_layout_settings(), {
            'menu_position': 'top_right',
            'button_theme': 'cyber',
        })

        page = self.client.get('/settings').get_data(as_text=True)
        self.assertIn('class="fh-menu-top-right fh-buttons-cyber"', page)
        self.assertIn('data-menu-position="top_right"', page)
        self.assertIn('data-button-theme="cyber"', page)
        self.assertIn('name="menu_position"', page)
        self.assertIn('value="top_right" checked', page)
        self.assertIn('name="button_theme"', page)
        self.assertIn('value="cyber" checked', page)

    def test_invalid_choices_fall_back_to_defaults(self):
        self.login()
        response = self.client.post('/settings', data={
            'app_name': 'Chore Gremlin',
            'theme_color': '#10b981',
            'brightness_mode': 'dark',
            'menu_position': 'moon',
            'button_theme': 'disco',
            'auto_update_enabled': '1',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_ui_layout_settings(), {
            'menu_position': 'left',
            'button_theme': 'default',
        })


class RemoteAccessCheckboxLayoutTests(unittest.TestCase):
    def test_checkbox_resets_bootstrap_float_and_margin(self):
        css = Path(ROOT, 'static', 'css', 'family-hub.css').read_text(
            encoding='utf-8'
        )
        check_block = css[
            css.index('.fh-check {'):css.index('.fh-check-input:checked')
        ]
        self.assertIn('display: flex', check_block)
        self.assertIn('max-width: 100%', check_block)
        self.assertIn('float: none', check_block)
        self.assertIn('margin: 0.1rem 0 0 0', check_block)
        self.assertIn('flex: 0 0 auto', check_block)
        label_block = css[
            css.index('.fh-check-label {'):css.index('.fh-check-label i')
        ]
        self.assertIn('margin-left: 0', label_block)
        self.assertIn('min-width: 0', label_block)
        self.assertIn('overflow-wrap: anywhere', label_block)

    def test_security_remote_checkbox_uses_bounded_classes(self):
        page = Path(ROOT, 'templates', 'security.html').read_text(
            encoding='utf-8'
        )
        self.assertIn('class="form-check fh-check mb-2"', page)
        self.assertIn('class="form-check-input fh-check-input"', page)
        self.assertIn('class="form-check-label fh-check-label"', page)
        self.assertIn('id="remoteAccess"', page)


if __name__ == '__main__':
    unittest.main()
