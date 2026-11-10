"""Tests for direct chore completion, shared chores and timer-free views."""
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-completion-'))
os.environ.setdefault('SECRET_KEY', 'completion-test-secret-key-not-for-production')

import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class ChoreCompletionRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        if not db_module.is_setup_complete():
            db_module.create_user(
                'Completion Setup Admin', None, 'completion-admin-password',
                role='admin', username='completion_setup_admin'
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

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def login_child(self, child_id):
        with self.client.session_transaction() as sess:
            sess['kiosk_child_id'] = child_id

    def child_page_has_chore(self, child_id, chore_name):
        self.login_child(child_id)
        response = self.client.get('/kiosk/chores')
        self.assertEqual(response.status_code, 200)
        return chore_name.encode() in response.data

    def complete(self, child_id, chore_id):
        self.login_child(child_id)
        response = self.client.post(f'/kiosk/complete/{chore_id}')
        self.assertEqual(response.status_code, 302)

    def test_shared_chore_disappears_after_first_completion(self):
        first = self.child('Shared Completion First')
        second = self.child('Shared Completion Second')
        chore_id = db_module.create_chore(
            'Shared Completion Chore', 'bi-star', 3, single_child_only=1
        )
        db_module.assign_chore(chore_id, first)
        db_module.assign_chore(chore_id, second)

        self.assertTrue(self.child_page_has_chore(first, 'Shared Completion Chore'))
        self.assertTrue(self.child_page_has_chore(second, 'Shared Completion Chore'))

        self.complete(first, chore_id)

        self.assertFalse(self.child_page_has_chore(first, 'Shared Completion Chore'))
        self.assertFalse(self.child_page_has_chore(second, 'Shared Completion Chore'))
        self.assertTrue(db_module.is_chore_completed_by_child(first, chore_id))
        self.assertTrue(db_module.is_chore_completed(chore_id))
        self.assertTrue(db_module.is_chore_fully_completed(chore_id))
        self.assertEqual(db_module.get_active_logs(first), [])

    def test_individual_chore_stays_for_each_child_until_they_complete(self):
        first = self.child('Individual Completion First')
        second = self.child('Individual Completion Second')
        chore_id = db_module.create_chore(
            'Individual Completion Chore', 'bi-star', 2, single_child_only=0
        )
        db_module.assign_chore(chore_id, first)
        db_module.assign_chore(chore_id, second)

        self.complete(first, chore_id)

        self.assertFalse(self.child_page_has_chore(first, 'Individual Completion Chore'))
        self.assertTrue(self.child_page_has_chore(second, 'Individual Completion Chore'))
        self.assertFalse(db_module.is_chore_fully_completed(chore_id))

        self.complete(second, chore_id)

        self.assertFalse(self.child_page_has_chore(first, 'Individual Completion Chore'))
        self.assertFalse(self.child_page_has_chore(second, 'Individual Completion Chore'))
        self.assertTrue(db_module.is_chore_fully_completed(chore_id))

    def test_recurring_chores_reset_after_their_completion_period(self):
        for frequency, delta in (
            ('daily', timedelta(days=1)),
            ('weekly', timedelta(days=8)),
            ('monthly', timedelta(days=32)),
        ):
            with self.subTest(frequency=frequency):
                name = f'{frequency.title()} Reset Chore'
                child_id = self.child(f'{frequency.title()} Reset Child')
                chore_id = db_module.create_chore(
                    name, 'bi-star', 1, repeat_frequency=frequency
                )
                db_module.assign_chore(chore_id, child_id)

                self.complete(child_id, chore_id)
                self.assertFalse(self.child_page_has_chore(child_id, name))

                future = db_module.clock.utc_now() + delta
                with patch.object(db_module.clock, 'utc_now', return_value=future):
                    self.assertTrue(self.child_page_has_chore(child_id, name))

    def test_completion_is_direct_and_creates_pending_approval(self):
        child_id = self.child('Direct Completion Child')
        chore_id = db_module.create_chore('Direct Completion Chore', 'bi-star', 4)
        db_module.assign_chore(chore_id, child_id)

        log = db_module.complete_chore(child_id, chore_id)
        self.assertEqual(log['status'], 'completed')
        self.assertIsNotNone(log['finished_at'])
        self.assertEqual(log['earned_amount'], 4)
        self.assertEqual(db_module.get_active_logs(child_id), [])
        pending_ids = {row['id'] for row in db_module.get_pending_approvals()}
        self.assertIn(log['id'], pending_ids)
        with self.assertRaises(ValueError):
            db_module.complete_chore(child_id, chore_id)

    def test_chore_views_and_assets_no_longer_contain_timers(self):
        with open(os.path.join(ROOT, 'templates', 'child_chores.html'), encoding='utf-8') as handle:
            child_template = handle.read()
        with open(os.path.join(ROOT, 'templates', 'dashboard.html'), encoding='utf-8') as handle:
            dashboard_template = handle.read()

        self.assertIn('Complete', child_template)
        self.assertNotIn('fh-timer', child_template)
        self.assertNotIn('kiosk-timer.js', child_template)
        self.assertNotIn('> Start', child_template)
        self.assertNotIn('fh-timer', dashboard_template)
        self.assertNotIn('Elapsed', dashboard_template)
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'static', 'js', 'kiosk-timer.js')))


if __name__ == '__main__':
    unittest.main()
