"""Financial reporting and ledger export checks for Phase 13."""
import os
import sys
import tempfile
import unittest
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase13-'))
os.environ.setdefault('SECRET_KEY', 'phase13-test-secret-key-not-for-production')

import reporting  # noqa: E402
import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class ReportingHelperTests(unittest.TestCase):
    def test_date_range_validation(self):
        self.assertEqual(reporting.normalize_range('2026-01-01', '2026-01-31'),
                         ('2026-01-01', '2026-01-31'))
        self.assertEqual(reporting.normalize_range('', ''), (None, None))
        with self.assertRaises(ValueError):
            reporting.normalize_range('2026-02-01', '2026-01-01')
        with self.assertRaises(ValueError):
            reporting.normalize_range('nope', '')

    def test_report_kind_and_range_helpers(self):
        self.assertEqual(reporting.normalize_kind('LEDGER'), 'ledger')
        with self.assertRaises(ValueError):
            reporting.normalize_kind('payroll')
        self.assertTrue(reporting.in_range('2026-01-15', '2026-01-01', '2026-01-31'))
        self.assertFalse(reporting.in_range('2026-02-01', '2026-01-01', '2026-01-31'))
        self.assertTrue(reporting.in_range('2026-01-15'))

    def test_csv_helpers_quote_and_format(self):
        payload = reporting.csv_bytes(
            ['Name', 'Amount'], [['A, B', '1.50'], ['Quote "x"', '2']]
        ).decode('utf-8')
        self.assertIn('"A, B",1.50', payload)
        self.assertIn('"Quote ""x""",2', payload)
        self.assertEqual(reporting.money(3), '3.00')
        self.assertEqual(reporting.type_label('bill_payment'), 'Bill payments')
        self.assertEqual(
            reporting.default_filename(
                'ledger', '2026-01-01', '2026-01-31',
                now=datetime(2026, 2, 1, 12, 30, 0)
            ),
            'choregremlin-ledger-20260201-123000-2026-01-01_2026-01-31.csv'
        )

    def test_build_export_for_every_kind(self):
        rows = [{
            'created_at': '2026-01-01 10:00:00', 'user_name': 'Alex',
            'type': 'earning', 'type_label': 'Chore earnings',
            'description': 'Dishes', 'amount': 5, 'running_balance': 5,
            'vault_name': 'Bike', 'balance_after': 5,
            'name': 'Phone', 'category': 'utilities', 'due_date': '2026-01-02',
            'status': 'paid', 'amount_paid': 5, 'late_fee_amount': 0,
            'requested_at': '2026-01-01 10:00:00', 'item_name': 'Game',
            'item_category': 'item', 'quantity': 1, 'total_amount': 5,
        }]
        summary = {
            'income': 5, 'expenses': 0, 'savings_in': 0, 'savings_out': 0,
            'net': 5, 'transaction_count': 1,
            'by_type': [{'label': 'Chore earnings', 'total': 5, 'count': 1}],
            'by_child': [{'name': 'Alex', 'net': 5}],
        }
        for kind, data in (
            ('ledger', rows), ('summary', summary), ('savings', rows),
            ('bills', rows), ('marketplace', rows),
        ):
            payload = reporting.build_export(kind, data)
            self.assertIsInstance(payload, bytes)
            self.assertTrue(payload)


class FinancialReportPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.parent_id = db_module.create_user(
            'Phase 13 Parent', None, None, role='parent', username='phase13_parent'
        )

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def test_ledger_filters_running_balance_and_summary(self):
        child_id = self.child('Phase 13 Ledger Child')
        db_module.create_payment(
            child_id, 20, ptype='earning', description='Phase 13 earnings',
            auto_repay=False
        )
        db_module.create_payment(
            child_id, -5, ptype='bill_payment', description='Phase 13 bill',
            auto_repay=False
        )
        db_module.create_payment(
            child_id, 2, ptype='milestone_reward', description='Phase 13 reward',
            auto_repay=False
        )
        entries = db_module.get_ledger_entries(user_id=child_id)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]['type'], 'milestone_reward')
        self.assertEqual(entries[-1]['type'], 'earning')
        self.assertEqual(entries[0]['running_balance'], 17)
        self.assertEqual(entries[1]['running_balance'], 15)
        self.assertEqual(entries[2]['running_balance'], 20)

        filtered = db_module.get_ledger_entries(
            user_id=child_id, types=['earning', 'milestone_reward']
        )
        self.assertEqual(len(filtered), 2)
        self.assertTrue(all(row['type'] != 'bill_payment' for row in filtered))

        today = date.today().isoformat()
        summary = db_module.get_financial_summary(
            start_date=today, end_date=today, user_id=child_id
        )
        self.assertEqual(summary['transaction_count'], 3)
        self.assertEqual(summary['income'], 22)
        self.assertEqual(summary['expenses'], 5)
        self.assertEqual(summary['net'], 17)
        self.assertEqual(summary['by_child'][0]['name'], 'Phase 13 Ledger Child')

    def test_savings_bills_and_marketplace_reports(self):
        child_id = self.child('Phase 13 Reports Child')
        db_module.create_payment(
            child_id, 100, ptype='earning', description='Phase 13 funding',
            auto_repay=False
        )
        vault = db_module.create_savings_vault(
            child_id, 'Phase 13 Vault', 50, target_date='2030-01-01'
        )
        db_module.deposit_to_savings_vault(vault['id'], child_id, 10)

        db_module.create_household_bill(
            child_id, 'Phase 13 Phone', 'utilities', 20, 'one_off', '2026-01-01',
            auto_deduct=False
        )
        db_module.schedule_due_bills(now='2026-01-01')
        occurrence = db_module.get_bill_occurrences(
            user_id=child_id, include_paid=False, limit=1
        )[0]
        db_module.pay_bill_occurrence(occurrence['id'], now='2026-01-01')

        item_id = db_module.create_marketplace_item(
            'Phase 13 Item', 5, requires_approval=0
        )
        db_module.create_marketplace_order(child_id, item_id)

        savings = db_module.get_savings_report(user_id=child_id)
        self.assertEqual(len(savings), 1)
        self.assertEqual(savings[0]['vault_name'], 'Phase 13 Vault')

        bills = db_module.get_bills_report(user_id=child_id)
        self.assertEqual(len(bills), 1)
        self.assertEqual(bills[0]['status'], 'paid')

        orders = db_module.get_marketplace_report(user_id=child_id)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]['item_name'], 'Phase 13 Item')

        self.assertIsInstance(
            db_module.get_report_data('summary', user_id=child_id), dict
        )
        with self.assertRaises(ValueError):
            db_module.get_report_data('nope', user_id=child_id)


class FinancialReportRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        if not db_module.is_setup_complete():
            db_module.create_user(
                'Phase 13 Admin', None, 'phase13-admin-password',
                role='admin', username='phase13_admin'
            )
        cls.parent_id = db_module.create_user(
            'Phase 13 Route Parent', None, None,
            role='parent', username='phase13_route_parent'
        )
        cls.previous_csrf = app_module.app.config.get('WTF_CSRF_ENABLED', True)
        app_module.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.previous_csrf
        cls.ctx.pop()

    def login_parent(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = self.parent_id

    def test_reports_page_loads_with_filters(self):
        child_id = db_module.create_user(
            'Phase 13 Page Child', None, None, role='child'
        )
        db_module.create_payment(
            child_id, 10, ptype='earning', description='Phase 13 page',
            auto_repay=False
        )
        self.login_parent()
        response = self.client.get(f'/reports?child_id={child_id}&report=ledger')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Financial Reports', response.data)
        self.assertIn(b'Phase 13 Page Child', response.data)
        self.assertIn(b'Full ledger', response.data)

    def test_reports_page_rejects_bad_date(self):
        self.login_parent()
        response = self.client.get('/reports?start=bad-date', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'valid date', response.data)

    def test_export_csv_returns_attachment(self):
        child_id = db_module.create_user(
            'Phase 13 Export Child', None, None, role='child'
        )
        db_module.create_payment(
            child_id, 12.5, ptype='earning', description='Export, "quoted"',
            auto_repay=False
        )
        self.login_parent()
        response = self.client.get(
            f'/reports/export.csv?child_id={child_id}&report=ledger'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        self.assertIn('attachment;', response.headers['Content-Disposition'])
        self.assertIn(b'"Export, ""quoted"""', response.data)
        self.assertIn(b'12.50', response.data)

    def test_export_summary_and_bad_kind(self):
        self.login_parent()
        response = self.client.get('/reports/export.csv?report=summary')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Net movement', response.data)
        response = self.client.get('/reports/export.csv?report=unknown')
        self.assertEqual(response.status_code, 400)

    def test_report_routes_have_access_rules(self):
        self.assertEqual(app_module.ROUTE_ACCESS.get('reports_page'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('reports_export'), 'staff')


if __name__ == '__main__':
    unittest.main()
