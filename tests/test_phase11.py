"""Recurring household bill, late fee and payroll deduction checks for Phase 11."""
import os
import sys
import tempfile
import unittest
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase11-'))
os.environ.setdefault('SECRET_KEY', 'phase11-test-secret-key-not-for-production')

import billing  # noqa: E402
import clock  # noqa: E402
import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class BillingCalculationTests(unittest.TestCase):
    def test_advance_due_date(self):
        self.assertEqual(
            billing.advance_due_date('2026-01-01', 'weekly'), '2026-01-08'
        )
        self.assertEqual(
            billing.advance_due_date('2026-01-31', 'monthly'), '2026-02-28'
        )
        self.assertEqual(
            billing.advance_due_date('2024-01-31', 'monthly'), '2024-02-29'
        )
        self.assertIsNone(billing.advance_due_date('2026-01-01', 'one_off'))
        with self.assertRaises(ValueError):
            billing.advance_due_date('2026-01-01', 'yearly')

    def test_late_fee_amounts_and_total_due(self):
        self.assertEqual(billing.late_fee_amount(20, 'flat', 5), 5.0)
        self.assertEqual(billing.late_fee_amount(20, 'percent', 10), 2.0)
        self.assertEqual(billing.late_fee_amount(20, 'none', 5), 0.0)
        self.assertEqual(billing.total_due(20, 5, 2), 17.0)
        self.assertEqual(billing.total_due(20, 30, 2), 0.0)
        with self.assertRaises(ValueError):
            billing.late_fee_amount(20, 'surprise', 5)

    def test_overdue_helpers(self):
        self.assertTrue(billing.is_overdue('2026-01-01', today='2026-01-02'))
        self.assertFalse(billing.is_overdue('2026-01-02', today='2026-01-02'))
        self.assertFalse(
            billing.is_overdue('2026-01-01', status='paid', today='2026-01-02')
        )
        self.assertEqual(
            billing.days_overdue('2026-01-01', today='2026-01-05'), 4
        )


class HouseholdBillPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.previous_csrf = app_module.app.config.get('WTF_CSRF_ENABLED')
        app_module.app.config['WTF_CSRF_ENABLED'] = False
        db_module.create_user(
            'Phase 11 Admin', None, 'phase11-admin-password', role='admin',
            username='phase11_admin'
        )
        cls.parent_id = db_module.create_user(
            'Phase 11 Parent', None, None, role='parent', username='phase11_parent'
        )

    @classmethod
    def tearDownClass(cls):
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.previous_csrf
        cls.ctx.pop()

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def funded_child(self, name, amount=100):
        child_id = self.child(name)
        db_module.create_payment(
            child_id, amount, ptype='earning',
            description='Phase 11 test funding', auto_repay=False
        )
        return child_id

    def make_bill(self, child_id, name='Phone plan', amount=20, due=None,
                  frequency='weekly', **kwargs):
        return db_module.create_household_bill(
            child_id, name, kwargs.pop('category', 'utilities'), amount,
            frequency, due or clock.local_date_text(), **kwargs
        )

    def test_migration_34_creates_bill_tables(self):
        db = db_module.get_db()
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()[0]
        self.assertGreaterEqual(version, 34)
        names = {
            row['name'] for row in db.execute(
                """SELECT name FROM sqlite_master WHERE type='table'
                   AND name IN ('household_bills', 'bill_occurrences',
                                'bill_payments')"""
            ).fetchall()
        }
        self.assertEqual(names, {
            'household_bills', 'bill_occurrences', 'bill_payments'
        })

    def test_create_update_toggle_and_delete_bill(self):
        child_id = self.child('Phase 11 Create Child')
        bill = self.make_bill(
            child_id, 'Phase 11 Create Bill', 25, due='2030-01-01',
            frequency='monthly', auto_deduct=False,
            late_fee_type='flat', late_fee_value=3
        )
        self.assertEqual(bill['name'], 'Phase 11 Create Bill')
        self.assertEqual(bill['amount'], 25)
        self.assertEqual(bill['category'], 'utilities')
        self.assertEqual(bill['frequency'], 'monthly')
        self.assertEqual(bill['next_due_date'], '2030-01-01')
        self.assertEqual(bill['auto_deduct'], 0)
        self.assertEqual(bill['late_fee_type'], 'flat')
        self.assertEqual(bill['late_fee_value'], 3)

        updated = db_module.update_household_bill(
            bill['id'], child_id, 'Phase 11 Updated Bill', 'subscription', 30,
            'weekly', '2030-02-01', auto_deduct=True,
            late_fee_type='percent', late_fee_value=10
        )
        self.assertEqual(updated['name'], 'Phase 11 Updated Bill')
        self.assertEqual(updated['category'], 'subscription')
        self.assertEqual(updated['amount'], 30)
        self.assertEqual(updated['frequency'], 'weekly')
        self.assertEqual(updated['late_fee_type'], 'percent')
        self.assertEqual(updated['late_fee_value'], 10)

        paused = db_module.set_household_bill_active(bill['id'], False)
        self.assertEqual(paused['is_active'], 0)
        active = db_module.set_household_bill_active(bill['id'], True)
        self.assertEqual(active['is_active'], 1)

        with self.assertRaises(ValueError):
            db_module.create_household_bill(
                self.parent_id, 'Parent bill', 'other', 10, 'weekly', '2030-01-01'
            )
        with self.assertRaises(ValueError):
            db_module.create_household_bill(
                child_id, '', 'other', 10, 'weekly', '2030-01-01'
            )
        with self.assertRaises(ValueError):
            db_module.create_household_bill(
                child_id, 'Bad amount', 'other', 0, 'weekly', '2030-01-01'
            )
        with self.assertRaises(ValueError):
            db_module.create_household_bill(
                child_id, 'Bad category', 'games', 10, 'weekly', '2030-01-01'
            )
        with self.assertRaises(ValueError):
            db_module.create_household_bill(
                child_id, 'Bad frequency', 'other', 10, 'yearly', '2030-01-01'
            )
        with self.assertRaises(ValueError):
            db_module.create_household_bill(
                child_id, 'Bad date', 'other', 10, 'weekly', 'not-a-date'
            )
        with self.assertRaises(ValueError):
            db_module.create_household_bill(
                child_id, 'Bad fee', 'other', 10, 'weekly', '2030-01-01',
                late_fee_type='flat', late_fee_value=-1
            )

        deleted = db_module.delete_household_bill(bill['id'])
        self.assertEqual(deleted['name'], 'Phase 11 Updated Bill')
        self.assertIsNone(db_module.get_household_bill(bill['id']))

    def test_scheduler_is_idempotent_and_advances_recurring_bills(self):
        child_id = self.child('Phase 11 Scheduler Child')
        weekly = self.make_bill(
            child_id, 'Phase 11 Weekly', 10, due='2026-01-01',
            frequency='weekly', auto_deduct=False
        )
        one_off = self.make_bill(
            child_id, 'Phase 11 One Off', 30, due='2026-01-01',
            frequency='one_off', auto_deduct=False
        )

        self.assertEqual(db_module.schedule_due_bills(now='2026-01-15'), 4)
        occurrences = db_module.get_bill_occurrences(user_id=child_id, limit=50)
        weekly_dates = [
            row['due_date'] for row in occurrences if row['bill_id'] == weekly['id']
        ]
        self.assertEqual(weekly_dates, ['2026-01-01', '2026-01-08', '2026-01-15'])
        self.assertEqual(
            db_module.get_household_bill(weekly['id'])['next_due_date'],
            '2026-01-22'
        )
        self.assertEqual(
            len([row for row in occurrences if row['bill_id'] == one_off['id']]), 1
        )
        self.assertEqual(db_module.get_household_bill(one_off['id'])['is_active'], 0)

        self.assertEqual(db_module.schedule_due_bills(now='2026-01-15'), 0)
        self.assertEqual(
            len(db_module.get_bill_occurrences(user_id=child_id, limit=50)), 4
        )
        db_module.delete_household_bill(weekly['id'])
        db_module.delete_household_bill(one_off['id'])

        monthly_child = self.child('Phase 11 Monthly Scheduler Child')
        monthly = self.make_bill(
            monthly_child, 'Phase 11 Monthly', 20, due='2026-01-31',
            frequency='monthly', auto_deduct=False
        )
        self.assertEqual(db_module.schedule_due_bills(now='2026-03-01'), 2)
        monthly_dates = [
            row['due_date'] for row in db_module.get_bill_occurrences(
                user_id=monthly_child, limit=50
            )
        ]
        self.assertEqual(monthly_dates, ['2026-01-31', '2026-02-28'])
        self.assertEqual(
            db_module.get_household_bill(monthly['id'])['next_due_date'],
            '2026-03-28'
        )
        self.assertEqual(db_module.schedule_due_bills(now='2026-03-01'), 0)
        db_module.delete_household_bill(monthly['id'])

    def test_overdue_late_fee_is_applied_once(self):
        child_id = self.child('Phase 11 Late Fee Child')
        bill = self.make_bill(
            child_id, 'Phase 11 Late Fee Bill', 20, due='2026-01-01',
            frequency='one_off', auto_deduct=False,
            late_fee_type='flat', late_fee_value=5
        )
        self.assertEqual(db_module.schedule_due_bills(now='2026-01-10'), 1)
        occurrence = db_module.get_bill_occurrences(
            user_id=child_id, include_paid=False
        )[0]
        self.assertEqual(occurrence['status'], 'due')

        result = db_module.apply_overdue_late_fees(now='2026-01-10')
        self.assertEqual(result['fees_applied'], 1)
        updated = db_module.get_bill_occurrence(occurrence['id'])
        self.assertEqual(updated['status'], 'overdue')
        self.assertEqual(updated['late_fee_amount'], 5)
        self.assertIsNotNone(updated['late_fee_applied_at'])

        result = db_module.apply_overdue_late_fees(now='2026-01-11')
        self.assertEqual(result['fees_applied'], 0)
        self.assertEqual(
            db_module.get_bill_occurrence(occurrence['id'])['late_fee_amount'], 5
        )
        db_module.delete_household_bill(bill['id'])

    def test_auto_payroll_deduction_and_partial_payment(self):
        child_id = self.child('Phase 11 Payroll Child')
        bill = self.make_bill(
            child_id, 'Phase 11 Payroll Bill', 30, due=clock.local_date_text(),
            frequency='weekly', auto_deduct=True
        )
        db_module.create_payment(
            child_id, 100, ptype='earning',
            description='Phase 11 payroll earning', auto_repay=True
        )
        self.assertEqual(db_module.get_balance(child_id), 70.0)
        occurrence = db_module.get_bill_occurrences(
            user_id=child_id, include_paid=True
        )[0]
        self.assertEqual(occurrence['status'], 'paid')
        self.assertEqual(occurrence['amount_paid'], 30)
        self.assertTrue(any(
            payment['type'] == 'bill_payment' and payment['amount'] == -30
            for payment in db_module.get_payments(child_id)
        ))

        partial_child = self.child('Phase 11 Partial Child')
        partial_bill = self.make_bill(
            partial_child, 'Phase 11 Partial Bill', 30,
            due=clock.local_date_text(), frequency='weekly', auto_deduct=True
        )
        db_module.create_payment(
            partial_child, 20, ptype='earning',
            description='Phase 11 partial earning 1', auto_repay=True
        )
        self.assertEqual(db_module.get_balance(partial_child), 0.0)
        partial_occurrence = db_module.get_bill_occurrences(
            user_id=partial_child, include_paid=True
        )[0]
        self.assertEqual(partial_occurrence['amount_paid'], 20)
        self.assertEqual(partial_occurrence['status'], 'due')

        db_module.create_payment(
            partial_child, 20, ptype='earning',
            description='Phase 11 partial earning 2', auto_repay=True
        )
        self.assertEqual(db_module.get_balance(partial_child), 10.0)
        partial_occurrence = db_module.get_bill_occurrence(partial_occurrence['id'])
        self.assertEqual(partial_occurrence['amount_paid'], 30)
        self.assertEqual(partial_occurrence['status'], 'paid')

        db_module.delete_household_bill(bill['id'])
        db_module.delete_household_bill(partial_bill['id'])

    def test_auto_deduct_off_and_late_fee_before_deduction(self):
        child_id = self.child('Phase 11 No Auto Child')
        bill = self.make_bill(
            child_id, 'Phase 11 No Auto Bill', 30,
            due=clock.local_date_text(), frequency='weekly', auto_deduct=False
        )
        db_module.create_payment(
            child_id, 50, ptype='earning',
            description='Phase 11 no auto earning', auto_repay=True
        )
        self.assertEqual(db_module.get_balance(child_id), 50.0)
        occurrence = db_module.get_bill_occurrences(
            user_id=child_id, include_paid=True
        )[0]
        self.assertEqual(occurrence['status'], 'due')
        self.assertEqual(occurrence['amount_paid'], 0)
        db_module.delete_household_bill(bill['id'])

        late_child = self.child('Phase 11 Late Payroll Child')
        past_due = (clock.local_date() - timedelta(days=5)).isoformat()
        late_bill = self.make_bill(
            late_child, 'Phase 11 Late Payroll Bill', 20, due=past_due,
            frequency='one_off', auto_deduct=True,
            late_fee_type='flat', late_fee_value=5
        )
        db_module.create_payment(
            late_child, 100, ptype='earning',
            description='Phase 11 late payroll earning', auto_repay=True
        )
        self.assertEqual(db_module.get_balance(late_child), 75.0)
        late_occurrence = db_module.get_bill_occurrences(
            user_id=late_child, include_paid=True
        )[0]
        self.assertEqual(late_occurrence['status'], 'paid')
        self.assertEqual(late_occurrence['late_fee_amount'], 5)
        self.assertEqual(late_occurrence['amount_paid'], 25)
        db_module.delete_household_bill(late_bill['id'])

    def test_manual_payment_and_insufficient_balance(self):
        child_id = self.funded_child('Phase 11 Manual Child', 20)
        other_id = self.funded_child('Phase 11 Manual Other', 100)
        bill = self.make_bill(
            child_id, 'Phase 11 Manual Bill', 30,
            due=clock.local_date_text(), frequency='weekly', auto_deduct=False
        )
        db_module.schedule_due_bills()
        occurrence = db_module.get_bill_occurrences(
            user_id=child_id, include_paid=False
        )[0]

        with self.assertRaises(ValueError):
            db_module.pay_bill_occurrence(occurrence['id'], user_id=other_id)
        with self.assertRaises(ValueError):
            db_module.pay_bill_occurrence(occurrence['id'], user_id=child_id)

        db_module.create_payment(
            child_id, 20, ptype='earning',
            description='Phase 11 manual top up', auto_repay=False
        )
        result = db_module.pay_bill_occurrence(
            occurrence['id'], source='manual', user_id=child_id
        )
        self.assertEqual(result['paid'], 30.0)
        self.assertEqual(db_module.get_balance(child_id), 10.0)
        paid = db_module.get_bill_occurrence(occurrence['id'])
        self.assertEqual(paid['status'], 'paid')
        self.assertEqual(paid['amount_paid'], 30)
        db_module.delete_household_bill(bill['id'])

    def test_bill_routes_and_access_rules(self):
        self.assertEqual(app_module.ROUTE_ACCESS.get('bills'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bills_add'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bills_run'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bills_toggle'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bills_delete'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('bill_occurrence_pay'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_bills'), 'kiosk')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_bill_pay'), 'kiosk')

        child_id = self.funded_child('Phase 11 Route Child', 100)
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = self.parent_id

        response = client.get('/bills')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Household Bills', response.data)

        response = client.post('/bills/add', data={
            'child_id': str(child_id),
            'name': 'Phase 11 Route Bill',
            'category': 'subscription',
            'amount': '30',
            'frequency': 'weekly',
            'next_due_date': clock.local_date_text(),
            'late_fee_type': 'flat',
            'late_fee_value': '5',
        })
        self.assertEqual(response.status_code, 302)
        bill = next(
            row for row in db_module.get_household_bills(child_id)
            if row['name'] == 'Phase 11 Route Bill'
        )
        self.assertEqual(bill['auto_deduct'], 0)

        response = client.get('/bills')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Phase 11 Route Bill', response.data)

        response = client.post(f'/bills/{bill["id"]}/toggle')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_household_bill(bill['id'])['is_active'], 0)
        client.post(f'/bills/{bill["id"]}/toggle')

        response = client.post('/bills/run')
        self.assertEqual(response.status_code, 302)
        occurrence = db_module.get_bill_occurrences(
            user_id=child_id, include_paid=False
        )[0]
        response = client.post(f'/bills/occurrences/{occurrence["id"]}/pay')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            db_module.get_bill_occurrence(occurrence['id'])['status'], 'paid'
        )

        response = client.post(f'/bills/{bill["id"]}/delete')
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db_module.get_household_bill(bill['id']))

    def test_kiosk_bill_page_and_payment(self):
        child_id = self.funded_child('Phase 11 Kiosk Child', 100)
        bill = self.make_bill(
            child_id, 'Phase 11 Kiosk Bill', 40,
            due=clock.local_date_text(), frequency='weekly', auto_deduct=False
        )
        db_module.schedule_due_bills()
        occurrence = db_module.get_bill_occurrences(
            user_id=child_id, include_paid=False
        )[0]
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['kiosk_child_id'] = child_id

        response = client.get('/kiosk/bills')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Phase 11 Kiosk Bill", response.data)
        self.assertIn(b'Your Bills', response.data)

        response = client.post(f'/kiosk/bills/{occurrence["id"]}/pay')
        self.assertEqual(response.status_code, 302)
        paid = db_module.get_bill_occurrence(occurrence['id'])
        self.assertEqual(paid['status'], 'paid')
        self.assertEqual(paid['amount_paid'], 40)
        self.assertEqual(db_module.get_balance(child_id), 60.0)
        db_module.delete_household_bill(bill['id'])


if __name__ == '__main__':
    unittest.main()
