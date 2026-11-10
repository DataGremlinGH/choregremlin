"""Savings, interest and loan engine checks for Phase 8."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase8-'))
os.environ.setdefault('SECRET_KEY', 'phase8-test-secret-key-not-for-production')

import banking  # noqa: E402
import clock  # noqa: E402
import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class BankingCalculationTests(unittest.TestCase):
    def test_compound_interest_daily_and_weekly(self):
        self.assertEqual(banking.compound_balance(100, 5, 365, 'daily'), 105.13)
        self.assertEqual(banking.compound_balance(100, 5, 52, 'weekly'), 105.12)
        self.assertEqual(banking.interest_amount(100, 5, 365, 'daily'), 5.13)
        self.assertEqual(banking.compound_balance(100, 0, 52, 'weekly'), 100)

    def test_elapsed_periods_and_next_interest_time(self):
        last_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(
            banking.elapsed_periods(last_at, last_at + timedelta(days=2), 'daily'), 2
        )
        self.assertEqual(
            banking.elapsed_periods(last_at, last_at + timedelta(days=8), 'weekly'), 1
        )
        self.assertEqual(
            banking.elapsed_periods(last_at, last_at - timedelta(days=1), 'daily'), 0
        )
        self.assertEqual(
            banking.next_interest_at(last_at, 2, 'daily'),
            last_at + timedelta(days=2)
        )

    def test_loan_terms_use_simple_interest(self):
        terms = banking.loan_terms(50, 10, 10)
        self.assertEqual(terms['principal'], 50)
        self.assertEqual(terms['interest_amount'], 0.96)
        self.assertEqual(terms['total_repayable'], 50.96)
        self.assertEqual(terms['installment_amount'], 5.10)
        self.assertEqual(banking.loan_terms(50, 0, 5)['total_repayable'], 50)

    def test_invalid_compounding_frequency_is_rejected(self):
        with self.assertRaises(ValueError):
            banking.periods_per_year('monthly')
        with self.assertRaises(ValueError):
            banking.interval_days('hourly')


class BankPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.parent_id = db_module.create_user(
            'Phase 8 Parent', None, None, role='parent', username='phase8_parent'
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
            description='Phase 8 test funding', auto_repay=False
        )
        return child_id

    def test_migration_26_creates_bank_tables(self):
        db = db_module.get_db()
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()[0]
        self.assertGreaterEqual(version, 26)
        names = {
            row['name'] for row in db.execute(
                """SELECT name FROM sqlite_master WHERE type='table'
                   AND name IN ('savings_accounts', 'bank_transactions',
                                'loans', 'loan_repayments')"""
            ).fetchall()
        }
        self.assertEqual(
            names,
            {'savings_accounts', 'bank_transactions', 'loans', 'loan_repayments'}
        )

    def test_savings_account_defaults_and_settings(self):
        child_id = self.child('Phase 8 Defaults Child')
        account = db_module.get_savings_account(child_id)
        self.assertEqual(account['balance'], 0)
        self.assertEqual(account['annual_interest_rate'], 5.0)
        self.assertEqual(account['compounding'], 'weekly')

        updated = db_module.update_savings_settings(child_id, 8.5, 'daily')
        self.assertEqual(updated['annual_interest_rate'], 8.5)
        self.assertEqual(updated['compounding'], 'daily')

        with self.assertRaises(ValueError):
            db_module.update_savings_settings(child_id, -1, 'daily')
        with self.assertRaises(ValueError):
            db_module.update_savings_settings(child_id, 5, 'monthly')

    def test_deposit_and_withdraw_move_money_between_wallets(self):
        child_id = self.funded_child('Phase 8 Wallet Child', 100)
        db_module.deposit_to_savings(child_id, 40)
        account = db_module.get_savings_account(child_id)
        self.assertEqual(account['balance'], 40)
        self.assertEqual(db_module.get_balance(child_id), 60)
        self.assertEqual(
            [row['type'] for row in db_module.get_bank_transactions(child_id)],
            ['deposit']
        )

        db_module.withdraw_from_savings(child_id, 15)
        self.assertEqual(db_module.get_savings_account(child_id)['balance'], 25)
        self.assertEqual(db_module.get_balance(child_id), 75)

        with self.assertRaises(ValueError):
            db_module.deposit_to_savings(child_id, 1000)
        with self.assertRaises(ValueError):
            db_module.withdraw_from_savings(child_id, 1000)
        with self.assertRaises(ValueError):
            db_module.deposit_to_savings(child_id, 0)

    def test_savings_interest_accrues_lazily(self):
        child_id = self.funded_child('Phase 8 Interest Child', 100)
        db_module.update_savings_settings(child_id, 5, 'daily')
        db_module.deposit_to_savings(child_id, 100)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db = db_module.get_db()
        db.execute(
            "UPDATE savings_accounts SET last_interest_at=? WHERE user_id=?",
            (clock.to_utc_text(start), child_id)
        )
        db.commit()

        results = db_module.apply_savings_interest(now=start + timedelta(days=10))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['periods'], 10)
        self.assertGreater(results[0]['interest'], 0)
        account = db_module.get_savings_account(child_id)
        self.assertGreater(account['balance'], 100)
        self.assertEqual(
            [row['type'] for row in db_module.get_bank_transactions(child_id)],
            ['interest', 'deposit']
        )

        again = db_module.apply_savings_interest(now=start + timedelta(days=10))
        self.assertEqual(again, [])

    def test_loan_application_validation_and_approval(self):
        child_id = self.child('Phase 8 Loan Child')
        loan_id = db_module.apply_for_loan(child_id, 50, 4, 'skateboard')
        loan = db_module.get_loan(loan_id)
        self.assertEqual(loan['status'], 'pending')
        self.assertEqual(loan['purpose'], 'skateboard')

        with self.assertRaises(ValueError):
            db_module.apply_for_loan(child_id, 10, 2, 'duplicate')
        with self.assertRaises(ValueError):
            db_module.apply_for_loan(self.child('Phase 8 Bad Loan Child'), -5, 2)

        approved = db_module.approve_loan(
            loan_id, self.parent_id, annual_rate=10, term_weeks=4
        )
        self.assertEqual(approved['status'], 'active')
        self.assertEqual(approved['principal'], 50)
        self.assertEqual(approved['total_repayable'], 50.38)
        self.assertEqual(approved['installment_amount'], 12.60)
        self.assertEqual(db_module.get_balance(child_id), 50)
        self.assertTrue(
            any(payment['type'] == 'loan' for payment in db_module.get_payments(child_id))
        )

    def test_loan_can_be_rejected_without_credit(self):
        child_id = self.child('Phase 8 Reject Loan Child')
        loan_id = db_module.apply_for_loan(child_id, 30, 3, 'game')
        rejected = db_module.reject_loan(loan_id, 'Save up first')
        self.assertEqual(rejected['status'], 'rejected')
        self.assertEqual(rejected['rejected_reason'], 'Save up first')
        self.assertEqual(db_module.get_balance(child_id), 0)
        self.assertEqual(db_module.get_payments(child_id), [])

    def test_earnings_automatically_repay_active_loans(self):
        child_id = self.child('Phase 8 Auto Repay Child')
        loan_id = db_module.apply_for_loan(child_id, 20, 2, 'book')
        db_module.approve_loan(loan_id, self.parent_id, annual_rate=0, term_weeks=2)

        db_module.create_payment(child_id, 15, ptype='earning', description='chore one')
        loan = db_module.get_loan(loan_id)
        self.assertEqual(loan['status'], 'active')
        self.assertEqual(loan['amount_repaid'], 10)
        self.assertEqual(loan['remaining_balance'], 10)
        self.assertEqual(db_module.get_balance(child_id), 25)

        db_module.create_payment(child_id, 15, ptype='earning', description='chore two')
        loan = db_module.get_loan(loan_id)
        self.assertEqual(loan['status'], 'repaid')
        self.assertEqual(loan['amount_repaid'], 20)
        self.assertEqual(loan['remaining_balance'], 0)
        self.assertIsNone(loan['next_due_date'])
        self.assertEqual(db_module.get_balance(child_id), 30)

        repayments = db_module.get_db().execute(
            "SELECT * FROM loan_repayments WHERE loan_id=?", (loan_id,)
        ).fetchall()
        self.assertEqual(len(repayments), 2)
        self.assertTrue(
            any(payment['type'] == 'loan_repayment' for payment in db_module.get_payments(child_id))
        )

    def test_repayment_only_uses_earning_payments(self):
        child_id = self.child('Phase 8 Bonus Repay Child')
        loan_id = db_module.apply_for_loan(child_id, 20, 2, 'toy')
        db_module.approve_loan(loan_id, self.parent_id, annual_rate=0, term_weeks=2)
        db_module.create_payment(child_id, 50, ptype='bonus', description='birthday')
        loan = db_module.get_loan(loan_id)
        self.assertEqual(loan['amount_repaid'], 0)
        self.assertEqual(loan['remaining_balance'], 20)

    def test_partial_earning_repays_only_available_amount(self):
        child_id = self.child('Phase 8 Partial Repay Child')
        loan_id = db_module.apply_for_loan(child_id, 20, 2, 'comic')
        db_module.approve_loan(loan_id, self.parent_id, annual_rate=0, term_weeks=2)
        db_module.create_payment(child_id, 5, ptype='earning', description='small chore')
        loan = db_module.get_loan(loan_id)
        self.assertEqual(loan['amount_repaid'], 5)
        self.assertEqual(loan['remaining_balance'], 15)


class BankRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        if not db_module.is_setup_complete():
            db_module.create_user('Phase 8 Admin', None, 'phase8-test-password',
                                  role='admin', username='phase8_admin')
        cls.parent_id = db_module.create_user(
            'Phase 8 Route Parent', None, None, role='parent', username='phase8_route_parent'
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

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def funded_child(self, name, amount=100):
        child_id = db_module.create_user(name, None, None, role='child')
        db_module.create_payment(
            child_id, amount, ptype='earning',
            description='Phase 8 route funding', auto_repay=False
        )
        return child_id

    def test_parent_bank_page_loads_and_actions_work(self):
        child_id = self.funded_child('Phase 8 Bank Page Child')
        self.login_parent()

        response = self.client.get('/bank')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Gremlin Central Bank', response.data)
        self.assertIn(b'Phase 8 Bank Page Child', response.data)

        response = self.client.post(f'/bank/{child_id}/settings', data={
            'annual_interest_rate': '7.5', 'compounding': 'daily'
        })
        self.assertEqual(response.status_code, 302)
        account = db_module.get_savings_account(child_id)
        self.assertEqual(account['annual_interest_rate'], 7.5)
        self.assertEqual(account['compounding'], 'daily')

        response = self.client.post(f'/bank/{child_id}/deposit', data={'amount': '25'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_savings_account(child_id)['balance'], 25)

        response = self.client.post(f'/bank/{child_id}/withdraw', data={'amount': '10'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_savings_account(child_id)['balance'], 15)

    def test_parent_loan_approve_and_reject_routes(self):
        approve_child = self.child('Phase 8 Approve Route Child')
        approve_loan_id = db_module.apply_for_loan(approve_child, 10, 2, 'approve')
        reject_child = self.child('Phase 8 Reject Route Child')
        reject_loan_id = db_module.apply_for_loan(reject_child, 10, 2, 'reject')
        self.login_parent()

        response = self.client.post(f'/bank/loans/{approve_loan_id}/approve', data={
            'annual_rate': '0', 'term_weeks': '2'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_loan(approve_loan_id)['status'], 'active')

        response = self.client.post(f'/bank/loans/{reject_loan_id}/reject', data={
            'reason': 'Not this week'
        })
        self.assertEqual(response.status_code, 302)
        rejected = db_module.get_loan(reject_loan_id)
        self.assertEqual(rejected['status'], 'rejected')
        self.assertEqual(rejected['rejected_reason'], 'Not this week')

    def test_kiosk_bank_page_and_savings_actions(self):
        child_id = self.funded_child('Phase 8 Kiosk Child', 20)
        self.login_child(child_id)

        response = self.client.get('/kiosk/bank')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Phase 8 Kiosk Child's Bank", response.data)

        response = self.client.post('/kiosk/bank/deposit', data={'amount': '8'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_savings_account(child_id)['balance'], 8)

        response = self.client.post('/kiosk/bank/withdraw', data={'amount': '3'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_savings_account(child_id)['balance'], 5)

    def test_kiosk_loan_application_route(self):
        child_id = self.child('Phase 8 Kiosk Loan Child')
        self.login_child(child_id)

        response = self.client.post('/kiosk/loan/apply', data={
            'amount': '12', 'term_weeks': '3', 'purpose': 'comic'
        })
        self.assertEqual(response.status_code, 302)
        loans = db_module.get_loans(child_id)
        self.assertEqual(len(loans), 1)
        self.assertEqual(loans[0]['status'], 'pending')
        self.assertEqual(loans[0]['purpose'], 'comic')

        response = self.client.get('/kiosk/bank')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Loan request pending', response.data)

    def test_bank_routes_have_access_rules(self):
        self.assertEqual(app_module.ROUTE_ACCESS.get('bank'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bank_settings'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bank_deposit'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bank_withdraw'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('loan_approve'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('loan_reject'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_bank'), 'kiosk')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_bank_deposit'), 'kiosk')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_bank_withdraw'), 'kiosk')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_loan_apply'), 'kiosk')


if __name__ == '__main__':
    unittest.main()
