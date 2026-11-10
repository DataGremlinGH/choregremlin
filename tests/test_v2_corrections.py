"""Regression tests for the post-V2.0.0 corrective pass."""
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-v2-corrections-'))
os.environ.setdefault('SECRET_KEY', 'v2-corrections-test-secret-key-not-for-production')

import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class CorrectivePersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.parent_id = db_module.create_user(
            'V2 Corrections Parent', None, None, role='parent',
            username='v2_corrections_parent'
        )

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def test_flexible_child_pin_and_staff_password_rules(self):
        child_id = self.child('Flexible PIN Child')
        db_module.set_pin(child_id, '123456789')
        child = db_module.get_user(child_id)
        self.assertEqual(db_module.check_kiosk_pin(child, '123456789'), 'ok')
        with self.assertRaises(ValueError):
            db_module.validate_pin('12ab')
        with self.assertRaises(ValueError):
            db_module.validate_pin('1' * 65)
        with self.assertRaises(ValueError):
            db_module.create_user('Short Password Parent', None, 'short', role='parent')
        db_module.validate_password('long-enough-password')
        with self.assertRaises(ValueError):
            db_module.set_password(self.parent_id, 'short')

    def test_marketplace_cash_and_token_balances_are_separate(self):
        item_id = db_module.create_marketplace_item(
            'Cash-only reward', None, currency_type='cash', cash_price='7.50',
            stock_quantity=2, requires_approval=0
        )
        item = db_module.get_marketplace_item(item_id)
        self.assertEqual(item['currency_type'], 'cash')
        self.assertEqual(item['cash_price'], 7.5)
        self.assertIsNone(item['token_price'])

        child_id = self.child('Cash Balance Child')
        db_module.adjust_cash_balance(child_id, 20, description='Test float', created_by=self.parent_id)
        db_module.create_payment(
            child_id, 30, ptype='earning', description='Test tokens', auto_repay=False
        )
        order_id = db_module.create_marketplace_order(child_id, item_id, 1)
        order = db_module.get_marketplace_order(order_id)
        self.assertEqual(order['currency_type'], 'cash')
        self.assertEqual(order['total_amount'], 7.5)
        self.assertEqual(order['cash_amount'], 7.5)
        self.assertEqual(order['token_amount'], 0)
        self.assertEqual(db_module.get_cash_balance(child_id), 12.5)
        self.assertEqual(db_module.get_balance(child_id), 30)

        rejected = db_module.reject_marketplace_order(order_id, self.parent_id, 'Test refund')
        self.assertEqual(rejected['status'], 'rejected')
        self.assertEqual(db_module.get_cash_balance(child_id), 20)
        self.assertEqual(db_module.get_balance(child_id), 30)

        poor_child = self.child('No Cash Child')
        with self.assertRaises(ValueError):
            db_module.create_marketplace_order(poor_child, item_id, 1)
        with self.assertRaises(ValueError):
            db_module.adjust_cash_balance(poor_child, -1, description='No overdraft')

    def test_marketplace_item_can_have_both_prices(self):
        item_id = db_module.create_marketplace_item(
            'Dual Price Reward', None, currency_type='token', token_price='10',
            cash_price='2.50', stock_quantity=None, requires_approval=1
        )
        item = db_module.get_marketplace_item(item_id)
        self.assertEqual(item['currency_type'], 'token')
        self.assertEqual(item['token_price'], 10)
        self.assertEqual(item['cash_price'], 2.5)
        child_id = self.child('Dual Price Child')
        db_module.create_payment(
            child_id, 20, ptype='earning', description='Dual price funding', auto_repay=False
        )
        db_module.adjust_cash_balance(child_id, 5, description='Cash float')
        order_id = db_module.create_marketplace_order(child_id, item_id, 1)
        order = db_module.get_marketplace_order(order_id)
        self.assertEqual(order['currency_type'], 'token')
        self.assertEqual(order['token_amount'], 10)
        self.assertEqual(order['cash_amount'], 0)
        self.assertEqual(db_module.get_balance(child_id), 10)
        self.assertEqual(db_module.get_cash_balance(child_id), 5)

    def test_expired_drop_chore_auto_assigns_logs_and_notifies(self):
        child_id = self.child('Drop Expiry Child')
        drop_id = db_module.create_drop_chore(
            'Expired auto drop', 10, 0, expires_minutes=0,
            created_by=self.parent_id
        )
        results = db_module.update_drop_chore_points()
        assigned = next((row for row in results if row['drop_id'] == drop_id), None)
        self.assertIsNotNone(assigned)
        self.assertIsNotNone(assigned['assigned_to'])
        drop = db_module.get_drop_chore(drop_id)
        self.assertEqual(drop['status'], 'assigned')
        self.assertEqual(drop['assigned_to'], assigned['assigned_to'])
        self.assertEqual(drop['current_points'], 0)
        activity = db_module.get_db().execute(
            "SELECT * FROM activity_log WHERE user_id=? AND action='drop_chore_auto_assigned' ORDER BY id DESC LIMIT 1",
            (assigned['assigned_to'],)
        ).fetchone()
        self.assertIsNotNone(activity)
        broadcasts = db_module.get_all_broadcasts(limit=20)
        self.assertTrue(any(
            row['child_id'] == assigned['assigned_to'] and row['title'] == 'Drop chore assigned'
            for row in broadcasts
        ))

    def test_linked_drop_auto_assignment_syncs_child_chore(self):
        chore_id = db_module.create_chore(
            'Linked drop chore', 'bi-droplet', 4, repeat_frequency='daily'
        )
        drop_id = db_module.create_drop_chore(
            'Linked expired drop', 10, 0, chore_id=chore_id,
            expires_minutes=0, created_by=self.parent_id
        )
        results = db_module.update_drop_chore_points()
        assigned = next((row for row in results if row['drop_id'] == drop_id), None)
        self.assertIsNotNone(assigned)
        child_id = assigned['assigned_to']

        assignment = db_module.get_db().execute(
            """SELECT * FROM chore_assignments
               WHERE chore_id=? AND user_id=? AND day_of_week IS NULL""",
            (chore_id, child_id)
        ).fetchone()
        self.assertIsNotNone(assignment)
        visible_ids = [chore['id'] for chore in db_module.get_chores_for_child(child_id)]
        self.assertIn(chore_id, visible_ids)
        assigned_drops = db_module.get_assigned_drop_chores(child_id)
        self.assertIn(drop_id, [drop['id'] for drop in assigned_drops])

        db_module.update_drop_chore_points()
        count = db_module.get_db().execute(
            """SELECT COUNT(*) FROM chore_assignments
               WHERE chore_id=? AND user_id=? AND day_of_week IS NULL""",
            (chore_id, child_id)
        ).fetchone()[0]
        self.assertEqual(count, 1)

        completed = db_module.complete_assigned_drop_chore(drop_id, child_id)
        self.assertIsNotNone(completed)
        self.assertIsNotNone(completed['log'])
        self.assertEqual(completed['log']['chore_id'], chore_id)
        self.assertEqual(completed['drop']['status'], 'completed')
        self.assertNotIn(drop_id, [drop['id'] for drop in db_module.get_assigned_drop_chores(child_id)])


class CorrectiveRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        if not db_module.is_setup_complete():
            db_module.create_user(
                'V2 Route Admin', None, 'v2-route-admin-password',
                role='admin', username='v2_route_admin'
            )
        cls.parent_id = db_module.create_user(
            'V2 Route Parent', None, None, role='parent', username='v2_route_parent'
        )
        cls.pin_child_id = db_module.create_user(
            'V2 Long PIN Child', None, None, role='child', pin='987654321'
        )
        cls.previous_csrf = app_module.app.config.get('WTF_CSRF_ENABLED', True)

    @classmethod
    def tearDownClass(cls):
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.previous_csrf
        cls.ctx.pop()

    def setUp(self):
        app_module.app.config['WTF_CSRF_ENABLED'] = self.previous_csrf
        app_module.g.pop('csrf_token', None)
        self.client = app_module.app.test_client()
        with self.client.session_transaction() as sess:
            sess.clear()

    def test_kiosk_pin_form_has_explicit_csrf_and_accepts_long_pin(self):
        app_module.app.config['WTF_CSRF_ENABLED'] = True
        page = self.client.get(f'/kiosk/select/{self.pin_child_id}')
        self.assertEqual(page.status_code, 200)
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)
        self.assertIsNotNone(token)
        response = self.client.post(
            f'/kiosk/select/{self.pin_child_id}',
            data={'pin': '987654321', 'csrf_token': token.group(1).decode()}
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('kiosk_child_id'), self.pin_child_id)

    def test_drop_chore_api_exposes_live_countdown_and_tokens(self):
        app_module.app.config['WTF_CSRF_ENABLED'] = False
        child_id = db_module.create_user('V2 API Drop Child', None, None, role='child')
        drop_id = db_module.create_drop_chore(
            'API countdown drop', 8, 1, expires_minutes=5, created_by=self.parent_id
        )
        with self.client.session_transaction() as sess:
            sess['kiosk_child_id'] = child_id
        response = self.client.get('/api/drop-chores')
        self.assertEqual(response.status_code, 200)
        drop = next(item for item in response.get_json() if item['id'] == drop_id)
        self.assertGreater(drop['current_points'], 0)
        self.assertLessEqual(drop['current_points'], 8)
        self.assertGreater(drop['seconds_remaining'], 0)
        self.assertIsNotNone(drop['expires_at'])
        self.assertIn('decay_per_minute', drop)

    def test_auto_assigned_drop_renders_complete_button_and_completes(self):
        child_id = db_module.create_user('V2 Action Drop Child', None, None, role='child')
        drop_id = db_module.create_drop_chore(
            'Actionable assigned drop', 5, 0, expires_minutes=60, created_by=self.parent_id
        )
        db_module.get_db().execute(
            """UPDATE drop_chores
               SET status='assigned', assigned_to=?, current_points=0
               WHERE id=?""",
            (child_id, drop_id)
        )
        db_module.get_db().commit()
        with self.client.session_transaction() as sess:
            sess['kiosk_child_id'] = child_id

        page = self.client.get('/kiosk/chores')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Assigned Drop Chores', page.data)
        self.assertIn(f'/kiosk/drop-chores/{drop_id}/complete'.encode(), page.data)
        token = re.search(rb'name="csrf-token" content="([^"]+)"', page.data)
        self.assertIsNotNone(token)

        response = self.client.post(
            f'/kiosk/drop-chores/{drop_id}/complete',
            data={'csrf_token': token.group(1).decode()}
        )
        self.assertEqual(response.status_code, 302)
        drop = db_module.get_drop_chore(drop_id)
        self.assertEqual(drop['status'], 'completed')
        self.assertEqual(drop['assigned_to'], child_id)
        self.assertNotIn(
            drop_id,
            [row['id'] for row in db_module.get_assigned_drop_chores(child_id)]
        )

    def test_marketplace_cash_balance_route(self):
        app_module.app.config['WTF_CSRF_ENABLED'] = False
        child_id = db_module.create_user('V2 Route Cash Child', None, None, role='child')
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.parent_id
        response = self.client.post(
            f'/marketplace/cash/{child_id}',
            data={'amount': '12.50', 'direction': 'add', 'description': 'Pocket money'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_cash_balance(child_id), 12.5)
        page = self.client.get('/marketplace')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Cash Balances', page.data)


class CorrectiveAssetTests(unittest.TestCase):
    def test_mobile_menu_light_theme_and_drop_wrapping_css(self):
        with open(os.path.join(ROOT, 'static', 'css', 'family-hub.css'), encoding='utf-8') as css_file:
            css = css_file.read()
        self.assertIn('@media (max-width: 768px)', css)
        self.assertIn('max-width: 100vw', css)
        self.assertIn('max-height: 100vh', css)
        self.assertIn('box-sizing: border-box', css)
        self.assertIn('overflow-y: auto', css)
        self.assertIn('[data-brightness="light"] .fh-sidebar-link', css)
        self.assertIn('word-break: break-word', css)
        self.assertIn('overflow-wrap: break-word', css)

        with open(os.path.join(ROOT, 'static', 'js', 'drop-chores.js'), encoding='utf-8') as script_file:
            script = script_file.read()
        self.assertIn('/api/drop-chores', script)
        self.assertIn('setInterval', script)
        self.assertIn('dropSeconds', script)


if __name__ == '__main__':
    unittest.main()
