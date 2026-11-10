"""Savings vault, goal lock and parent matching checks for Phase 10."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase10-'))
os.environ.setdefault('SECRET_KEY', 'phase10-test-secret-key-not-for-production')

import banking  # noqa: E402
import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class VaultCalculationTests(unittest.TestCase):
    def test_progress_and_target_reached(self):
        progress = banking.vault_progress(
            25, 50, target_date='2030-01-01', lock_until_target=True,
            today='2026-01-01'
        )
        self.assertEqual(progress['percent'], 50.0)
        self.assertEqual(progress['remaining'], 25.0)
        self.assertFalse(progress['target_reached'])
        self.assertFalse(progress['unlocked'])
        self.assertTrue(progress['locked'])

        reached = banking.vault_progress(
            50, 50, target_date='2030-01-01', lock_until_target=True,
            today='2026-01-01'
        )
        self.assertEqual(reached['percent'], 100.0)
        self.assertTrue(reached['target_reached'])
        self.assertTrue(reached['unlocked'])
        self.assertFalse(reached['locked'])

    def test_date_lock_and_or_semantics(self):
        date_unlocked = banking.vault_progress(
            10, 50, target_date='2025-01-01', lock_until_date=True,
            today='2026-01-01'
        )
        self.assertTrue(date_unlocked['date_reached'])
        self.assertTrue(date_unlocked['unlocked'])

        future_locked = banking.vault_progress(
            10, 50, target_date='2030-01-01',
            lock_until_date=True, lock_until_target=True,
            today='2026-01-01'
        )
        self.assertTrue(future_locked['locked'])

        either_unlocked = banking.vault_progress(
            50, 50, target_date='2030-01-01',
            lock_until_date=True, lock_until_target=True,
            today='2026-01-01'
        )
        self.assertTrue(either_unlocked['unlocked'])

    def test_no_lock_and_closed_vault(self):
        open_goal = banking.vault_progress(5, 10, today='2026-01-01')
        self.assertTrue(open_goal['unlocked'])
        self.assertFalse(open_goal['locked'])

        closed = banking.vault_progress(
            5, 10, lock_until_target=True, status='closed', today='2026-01-01'
        )
        self.assertTrue(closed['closed'])
        self.assertFalse(closed['unlocked'])

    def test_match_amount_respects_percentage_and_weekly_cap(self):
        self.assertEqual(banking.match_amount(30, 50, 10), 10.0)
        self.assertEqual(banking.match_amount(4, 50, 10), 2.0)
        self.assertEqual(banking.match_amount(30, 50, 10, matched_this_week=10), 0.0)
        self.assertEqual(banking.match_amount(30, 50, 10, matched_this_week=8), 2.0)

    def test_week_start_is_monday(self):
        start = banking.week_start(datetime(2026, 11, 8, 15, 30, tzinfo=timezone.utc))
        self.assertEqual(start.isoformat(), '2026-11-02T00:00:00+00:00')


class SavingsVaultPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.parent_id = db_module.create_user(
            'Phase 10 Parent', None, None, role='parent', username='phase10_parent'
        )

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def funded_child(self, name, amount=100):
        child_id = self.child(name)
        db_module.create_payment(
            child_id, amount, ptype='earning',
            description='Phase 10 test funding', auto_repay=False
        )
        return child_id

    def make_vault(self, child_id, name='Bike', target=50, **kwargs):
        return db_module.create_savings_vault(child_id, name, target, **kwargs)

    def test_migration_31_creates_vault_tables(self):
        db = db_module.get_db()
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()[0]
        self.assertGreaterEqual(version, 31)
        names = {
            row['name'] for row in db.execute(
                """SELECT name FROM sqlite_master WHERE type='table'
                   AND name IN ('savings_vaults', 'savings_vault_transactions',
                                'savings_match_rules')"""
            ).fetchall()
        }
        self.assertEqual(names, {
            'savings_vaults', 'savings_vault_transactions', 'savings_match_rules'
        })

    def test_create_update_and_validation(self):
        child_id = self.funded_child('Phase 10 Create Child')
        vault = self.make_vault(
            child_id, 'New bike', 80, target_date='2030-01-01',
            lock_until_target=True, description='A red bike', icon='bi-bicycle'
        )
        self.assertEqual(vault['name'], 'New bike')
        self.assertEqual(vault['target_amount'], 80)
        self.assertEqual(vault['target_date'], '2030-01-01')
        self.assertEqual(vault['lock_until_target'], 1)
        self.assertEqual(vault['lock_until_date'], 0)
        self.assertEqual(vault['status'], 'active')

        updated = db_module.update_savings_vault(
            vault['id'], 'New mountain bike', 120, target_date='2031-01-01',
            lock_until_date=True, lock_until_target=True,
            description='Bigger bike', icon='bi-bicycle', color='#3b82f6'
        )
        self.assertEqual(updated['name'], 'New mountain bike')
        self.assertEqual(updated['target_amount'], 120)
        self.assertEqual(updated['lock_until_date'], 1)
        self.assertEqual(updated['color'], '#3b82f6')

        with self.assertRaises(ValueError):
            self.make_vault(child_id, '', 10)
        with self.assertRaises(ValueError):
            self.make_vault(child_id, 'Bad target', 0)
        with self.assertRaises(ValueError):
            self.make_vault(child_id, 'Bad date', 10, target_date='not-a-date')
        with self.assertRaises(ValueError):
            self.make_vault(child_id, 'Missing date', 10, lock_until_date=True)
        with self.assertRaises(ValueError):
            db_module.create_savings_vault(self.parent_id, 'Parent goal', 10)

    def test_deposit_moves_money_and_applies_match(self):
        child_id = self.funded_child('Phase 10 Deposit Child', 100)
        vault = self.make_vault(child_id, 'Skateboard', 50)
        db_module.set_savings_match_rule(child_id, None, 50, 10)

        result = db_module.deposit_to_savings_vault(vault['id'], child_id, 30)
        self.assertEqual(result['matched'], 10.0)
        self.assertEqual(result['vault']['balance'], 40.0)
        self.assertEqual(db_module.get_balance(child_id), 70.0)

        transactions = db_module.get_savings_vault_transactions(vault_id=vault['id'])
        types = [tx['type'] for tx in transactions]
        self.assertIn('deposit', types)
        self.assertIn('match', types)
        self.assertTrue(any(
            payment['type'] == 'vault_deposit'
            for payment in db_module.get_payments(child_id)
        ))

        second = db_module.deposit_to_savings_vault(vault['id'], child_id, 5)
        self.assertEqual(second['matched'], 0.0)
        self.assertEqual(second['vault']['balance'], 45.0)
        self.assertEqual(db_module.get_balance(child_id), 65.0)

    def test_goal_specific_match_rule_overrides_global(self):
        child_id = self.funded_child('Phase 10 Rule Child', 100)
        vault = self.make_vault(child_id, 'Concert ticket', 50)
        db_module.set_savings_match_rule(child_id, None, 50, 20)
        db_module.set_savings_match_rule(child_id, vault['id'], 100, 5)

        result = db_module.deposit_to_savings_vault(vault['id'], child_id, 20)
        self.assertEqual(result['matched'], 5.0)
        self.assertEqual(result['vault']['balance'], 25.0)

        effective = db_module.get_effective_savings_match_rule(child_id, vault['id'])
        self.assertEqual(effective['vault_id'], vault['id'])
        self.assertEqual(effective['match_percent'], 100)

    def test_target_lock_blocks_until_target_reached(self):
        child_id = self.funded_child('Phase 10 Target Lock Child', 100)
        vault = self.make_vault(child_id, 'Locked goal', 50, lock_until_target=True)
        db_module.deposit_to_savings_vault(vault['id'], child_id, 25)
        with self.assertRaises(ValueError):
            db_module.withdraw_from_savings_vault(vault['id'], child_id, 10)

        db_module.deposit_to_savings_vault(vault['id'], child_id, 25)
        withdrawn = db_module.withdraw_from_savings_vault(vault['id'], child_id, 10)
        self.assertEqual(withdrawn['balance'], 40.0)
        self.assertEqual(db_module.get_balance(child_id), 60.0)

    def test_date_lock_blocks_until_date_reached(self):
        child_id = self.funded_child('Phase 10 Date Lock Child', 100)
        future = self.make_vault(
            child_id, 'Future goal', 50, target_date='2999-01-01',
            lock_until_date=True
        )
        db_module.deposit_to_savings_vault(future['id'], child_id, 10)
        with self.assertRaises(ValueError):
            db_module.withdraw_from_savings_vault(future['id'], child_id, 5)

        past = self.make_vault(
            child_id, 'Past goal', 50, target_date='2000-01-01',
            lock_until_date=True
        )
        db_module.deposit_to_savings_vault(past['id'], child_id, 10)
        withdrawn = db_module.withdraw_from_savings_vault(past['id'], child_id, 5)
        self.assertEqual(withdrawn['balance'], 5.0)

    def test_both_locks_unlock_when_either_condition_is_met(self):
        child_id = self.funded_child('Phase 10 Either Lock Child', 100)
        vault = self.make_vault(
            child_id, 'Either goal', 20, target_date='2999-01-01',
            lock_until_date=True, lock_until_target=True
        )
        db_module.deposit_to_savings_vault(vault['id'], child_id, 10)
        with self.assertRaises(ValueError):
            db_module.withdraw_from_savings_vault(vault['id'], child_id, 5)

        db_module.deposit_to_savings_vault(vault['id'], child_id, 10)
        withdrawn = db_module.withdraw_from_savings_vault(vault['id'], child_id, 5)
        self.assertEqual(withdrawn['balance'], 15.0)

    def test_close_refunds_balance_and_deactivates_rules(self):
        child_id = self.funded_child('Phase 10 Close Child', 100)
        vault = self.make_vault(child_id, 'Close goal', 50)
        rule = db_module.set_savings_match_rule(child_id, vault['id'], 50, 10)
        db_module.deposit_to_savings_vault(vault['id'], child_id, 30)
        self.assertEqual(db_module.get_balance(child_id), 70.0)

        closed = db_module.close_savings_vault(vault['id'])
        self.assertEqual(closed['status'], 'closed')
        self.assertEqual(closed['balance'], 0)
        self.assertEqual(db_module.get_balance(child_id), 110.0)
        self.assertEqual(db_module.get_savings_match_rule(rule['id'])['is_active'], 0)
        self.assertTrue(any(
            payment['type'] == 'vault_close_refund'
            for payment in db_module.get_payments(child_id)
        ))

    def test_unlock_removes_both_lock_flags(self):
        child_id = self.funded_child('Phase 10 Unlock Child', 100)
        vault = self.make_vault(
            child_id, 'Unlock goal', 50, target_date='2999-01-01',
            lock_until_date=True, lock_until_target=True
        )
        db_module.deposit_to_savings_vault(vault['id'], child_id, 10)
        with self.assertRaises(ValueError):
            db_module.withdraw_from_savings_vault(vault['id'], child_id, 5)

        unlocked = db_module.unlock_savings_vault(vault['id'])
        self.assertEqual(unlocked['lock_until_date'], 0)
        self.assertEqual(unlocked['lock_until_target'], 0)
        withdrawn = db_module.withdraw_from_savings_vault(vault['id'], child_id, 5)
        self.assertEqual(withdrawn['balance'], 5.0)

    def test_vault_owner_is_enforced(self):
        owner_id = self.funded_child('Phase 10 Owner Child', 50)
        other_id = self.funded_child('Phase 10 Other Child', 50)
        vault = self.make_vault(owner_id, 'Owner goal', 20)
        with self.assertRaises(ValueError):
            db_module.deposit_to_savings_vault(vault['id'], other_id, 5)
        with self.assertRaises(ValueError):
            db_module.withdraw_from_savings_vault(vault['id'], other_id, 5)


class SavingsVaultRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        if not db_module.is_setup_complete():
            db_module.create_user('Phase 10 Admin', None, 'phase10-test-password',
                                  role='admin', username='phase10_admin')
        cls.parent_id = db_module.create_user(
            'Phase 10 Route Parent', None, None, role='parent', username='phase10_route_parent'
        )
        cls.previous_csrf = app_module.app.config.get('WTF_CSRF_ENABLED', True)
        app_module.app.config['WTF_CSRF_ENABLED'] = False

    @classmethod
    def tearDownClass(cls):
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.previous_csrf
        cls.ctx.pop()

    def setUp(self):
        self.client = app_module.app.test_client()
        with self.client.session_transaction() as sess:
            sess.clear()

    def login_parent(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.parent_id

    def login_child(self, child_id):
        with self.client.session_transaction() as sess:
            sess['kiosk_child_id'] = child_id

    def funded_child(self, name, amount=100):
        child_id = db_module.create_user(name, None, None, role='child')
        db_module.create_payment(
            child_id, amount, ptype='earning',
            description='Phase 10 route funding', auto_repay=False
        )
        return child_id

    def test_parent_bank_page_and_vault_routes(self):
        child_id = self.funded_child('Phase 10 Route Vault Child')
        vault = db_module.create_savings_vault(
            child_id, 'Phase 10 Route Bike', 60, target_date='2030-01-01',
            lock_until_target=True
        )
        db_module.set_savings_match_rule(child_id, None, 50, 10)
        self.login_parent()

        response = self.client.get('/bank')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Savings Vaults', response.data)
        self.assertIn(b'Phase 10 Route Bike', response.data)
        self.assertIn(b'Parent Matching Rules', response.data)
        self.assertIn(b'50', response.data)

        response = self.client.post('/bank/vaults/add', data={
            'child_id': str(child_id),
            'name': 'Phase 10 Route Added Goal',
            'target_amount': '25',
            'target_date': '2030-02-01',
            'description': 'Added by route test',
            'icon': 'bi-gift',
            'color': '#3b82f6',
            'lock_until_target': '1',
        })
        self.assertEqual(response.status_code, 302)
        added = next(
            row for row in db_module.get_savings_vaults(child_id)
            if row['name'] == 'Phase 10 Route Added Goal'
        )
        self.assertEqual(added['target_amount'], 25)

        response = self.client.post('/bank/match-rules/save', data={
            'child_id': str(child_id),
            'vault_id': str(vault['id']),
            'match_percent': '75',
            'weekly_cap': '12',
            'is_active': '1',
        })
        self.assertEqual(response.status_code, 302)
        rule = db_module.get_effective_savings_match_rule(child_id, vault['id'])
        self.assertEqual(rule['match_percent'], 75)
        self.assertEqual(rule['weekly_cap'], 12)

        response = self.client.post(f'/bank/vaults/{vault["id"]}/unlock')
        self.assertEqual(response.status_code, 302)
        unlocked = db_module.get_savings_vault(vault['id'])
        self.assertEqual(unlocked['lock_until_target'], 0)
        self.assertEqual(unlocked['lock_until_date'], 0)

        response = self.client.post(f'/bank/vaults/{vault["id"]}/close')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_savings_vault(vault['id'])['status'], 'closed')

        response = self.client.post(f'/bank/match-rules/{rule["id"]}/delete')
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db_module.get_savings_match_rule(rule['id']))

    def test_kiosk_bank_page_create_deposit_and_locked_withdraw(self):
        child_id = self.funded_child('Phase 10 Kiosk Vault Child', 100)
        self.login_child(child_id)

        response = self.client.get('/kiosk/bank')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Savings Goals', response.data)
        self.assertIn(b'New Goal', response.data)

        response = self.client.post('/kiosk/bank/vaults/add', data={
            'name': 'Phase 10 Kiosk Goal',
            'target_amount': '50',
            'target_date': '2999-01-01',
            'description': 'Kiosk goal',
            'icon': 'bi-bicycle',
            'color': '#10b981',
            'lock_until_target': '1',
        })
        self.assertEqual(response.status_code, 302)
        vault = next(
            row for row in db_module.get_savings_vaults(child_id)
            if row['name'] == 'Phase 10 Kiosk Goal'
        )
        self.assertEqual(vault['target_amount'], 50)

        response = self.client.post(
            f'/kiosk/bank/vaults/{vault["id"]}/deposit', data={'amount': '20'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_savings_vault(vault['id'])['balance'], 20)
        self.assertEqual(db_module.get_balance(child_id), 80)

        response = self.client.post(
            f'/kiosk/bank/vaults/{vault["id"]}/withdraw', data={'amount': '5'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_savings_vault(vault['id'])['balance'], 20)

        response = self.client.post(
            f'/kiosk/bank/vaults/{vault["id"]}/deposit', data={'amount': '30'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_savings_vault(vault['id'])['balance'], 50)

        response = self.client.post(
            f'/kiosk/bank/vaults/{vault["id"]}/withdraw', data={'amount': '5'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_savings_vault(vault['id'])['balance'], 45)

    def test_kiosk_page_shows_match_rule_and_progress(self):
        child_id = self.funded_child('Phase 10 Kiosk Display Child', 100)
        vault = db_module.create_savings_vault(child_id, 'Phase 10 Display Goal', 40)
        db_module.set_savings_match_rule(child_id, vault['id'], 50, 10)
        db_module.deposit_to_savings_vault(vault['id'], child_id, 20)
        self.login_child(child_id)

        response = self.client.get('/kiosk/bank')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Phase 10 Display Goal', response.data)
        self.assertIn(b'Parent matches', response.data)
        self.assertIn(b'50%', response.data)

    def test_vault_routes_have_access_rules(self):
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_vault_add'), 'kiosk')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_vault_deposit'), 'kiosk')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_vault_withdraw'), 'kiosk')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bank_vault_add'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bank_vault_close'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bank_vault_unlock'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bank_match_rule_save'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bank_match_rule_delete'), 'staff')


if __name__ == '__main__':
    unittest.main()
