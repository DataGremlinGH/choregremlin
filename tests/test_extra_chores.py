"""Tests for the v2.1.0 extra-chore request workflow."""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-extra-chores-'))
os.environ.setdefault('SECRET_KEY', 'extra-chores-test-secret-key-not-for-production')

import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class ExtraChoreMigrationTests(unittest.TestCase):
    def test_legacy_database_gains_is_extra_column_without_data_loss(self):
        with tempfile.TemporaryDirectory(prefix='cg-legacy-db-') as tmp:
            legacy_path = os.path.join(tmp, 'legacy.db')
            conn = sqlite3.connect(legacy_path)
            conn.executescript(db_module.SCHEMA)
            conn.execute(
                "INSERT INTO users (name, role) VALUES ('Legacy Child', 'child')"
            )
            conn.execute(
                """INSERT INTO chores (name, icon, pay_amount)
                   VALUES ('Legacy Chore', 'bi-star', 2.5)"""
            )
            conn.execute(
                """INSERT INTO chore_logs
                   (user_id, chore_id, status, finished_at, earned_amount)
                   VALUES (1, 1, 'completed', '2026-01-01 00:00:00', 2.5)"""
            )
            # Simulate a pre-v2.1.0 database that has already recorded the
            # current schema version but predates the extra-chore column.
            conn.execute("ALTER TABLE chore_logs DROP COLUMN is_extra")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version INTEGER NOT NULL)"
            )
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (len(db_module.MIGRATIONS),),
            )
            conn.commit()
            conn.close()

            with patch.object(db_module, 'DB_PATH', legacy_path):
                db_module.init_db()

            conn = sqlite3.connect(legacy_path)
            conn.row_factory = sqlite3.Row
            columns = {
                row[1] for row in conn.execute(
                    "PRAGMA table_info(chore_logs)"
                ).fetchall()
            }
            rows = conn.execute("SELECT * FROM chore_logs").fetchall()
            conn.close()

            self.assertIn('is_extra', columns)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['status'], 'completed')
            self.assertEqual(rows[0]['earned_amount'], 2.5)
            self.assertEqual(rows[0]['is_extra'], 0)


class ExtraChoreWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.parent_id = db_module.create_user(
            'Extra Chore Parent', None, 'extra-chore-parent-password',
            role='parent', username='extra_chore_parent'
        )

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def test_active_chore_is_blocked_with_clear_message(self):
        child_id = self.child('Extra Active Child')
        chore_id = db_module.create_chore(
            'Extra Active Chore', 'bi-star', 3, repeat_frequency='monthly'
        )
        db_module.assign_chore(chore_id, child_id)

        with self.assertRaisesRegex(
            ValueError, 'Please complete existing chore first'
        ):
            db_module.request_extra_chore(child_id, chore_id)

    def test_extra_request_is_independent_and_needs_approval(self):
        child_id = self.child('Extra Monthly Child')
        chore_id = db_module.create_chore(
            'Extra Monthly Chore', 'bi-star', 5, repeat_frequency='monthly'
        )
        db_module.assign_chore(chore_id, child_id)

        db_module.complete_chore(child_id, chore_id)
        extra = db_module.request_extra_chore(child_id, chore_id)

        self.assertEqual(extra['is_extra'], 1)
        self.assertEqual(extra['status'], 'completed')
        self.assertEqual(extra['earned_amount'], 5)
        pending_ids = {row['id'] for row in db_module.get_pending_approvals()}
        self.assertIn(extra['id'], pending_ids)

        with self.assertRaisesRegex(ValueError, 'already waiting for approval'):
            db_module.request_extra_chore(child_id, chore_id)

        # The extra record must not stop the regular monthly chore from
        # returning when its normal cycle resets.
        future = db_module.clock.utc_now() + timedelta(days=32)
        with patch.object(db_module.clock, 'utc_now', return_value=future):
            visible_ids = {
                chore['id'] for chore in db_module.get_chores_for_child(child_id)
            }
            self.assertIn(chore_id, visible_ids)

    def test_approving_extra_creates_separate_payment(self):
        child_id = self.child('Extra Payout Child')
        chore_id = db_module.create_chore(
            'Extra Payout Chore', 'bi-star', 7, repeat_frequency='once'
        )
        db_module.assign_chore(chore_id, child_id)
        db_module.complete_chore(child_id, chore_id)
        extra = db_module.request_extra_chore(child_id, chore_id)

        approved = db_module.approve_chore(extra['id'], self.parent_id)
        self.assertIsNotNone(approved)
        payment_id = db_module.create_payment(
            child_id, approved['earned_amount'], ptype='earning',
            description='Earned: Extra Payout Chore (extra)',
            log_id=approved['id'], created_by=self.parent_id
        )
        payment = db_module.get_db().execute(
            'SELECT * FROM payments WHERE id=?', (payment_id,)
        ).fetchone()
        self.assertEqual(payment['amount'], 7)
        self.assertEqual(payment['type'], 'earning')
        self.assertIn('(extra)', payment['description'])
        self.assertNotIn(
            extra['id'],
            {row['id'] for row in db_module.get_pending_approvals()},
        )


if __name__ == '__main__':
    unittest.main()
