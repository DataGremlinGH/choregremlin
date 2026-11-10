"""Regression tests for drop cleanup, kid badges, tickers and notification alerts."""
import os
import sys
import tempfile
import unittest
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-feature-'))
os.environ.setdefault('SECRET_KEY', 'feature-test-secret-key-not-for-production')

import db as db_module  # noqa: E402
import app as app_module  # noqa: E402
import notifications  # noqa: E402


def unique(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


class FeaturePersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.parent_id = db_module.create_user(
            unique('Feature Parent'), None, None, role='parent',
            username=unique('feature_parent')
        )

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def assign_drop_to_child(self, drop_id, child_id, chore_id=None):
        db = db_module.get_db()
        db.execute(
            """UPDATE drop_chores
               SET status='assigned', assigned_to=?, current_points=0
               WHERE id=?""",
            (child_id, drop_id),
        )
        db.commit()

    def test_delete_assigned_drop_cleans_profile_and_linked_assignment(self):
        child_id = self.child(unique('Assigned Drop Child'))
        chore_id = db_module.create_chore(unique('Linked Drop Chore'), 'bi-droplet', 3)
        db_module.assign_chore(chore_id, child_id)
        drop_id = db_module.create_drop_chore(
            unique('Assigned Drop'), 5, 0, chore_id=chore_id,
            created_by=self.parent_id, expires_minutes=60,
        )
        self.assign_drop_to_child(drop_id, child_id, chore_id)

        self.assertIn(
            drop_id,
            [row['id'] for row in db_module.get_assigned_drop_chores(child_id)]
        )
        self.assertTrue(db_module.delete_drop_chore(drop_id))
        self.assertIsNone(db_module.get_drop_chore(drop_id))
        self.assertNotIn(
            drop_id,
            [row['id'] for row in db_module.get_assigned_drop_chores(child_id)]
        )
        assignment = db_module.get_db().execute(
            """SELECT * FROM chore_assignments
               WHERE chore_id=? AND user_id=? AND day_of_week IS NULL""",
            (chore_id, child_id),
        ).fetchone()
        self.assertIsNone(assignment)

    def test_expired_drop_can_be_deleted(self):
        self.child(unique('Expired Drop Child'))
        drop_id = db_module.create_drop_chore(
            unique('Expired Drop'), 4, 0, created_by=self.parent_id,
            expires_minutes=0,
        )
        db_module.update_drop_chore_points()
        self.assertNotEqual(db_module.get_drop_chore(drop_id)['status'], 'available')
        self.assertTrue(db_module.delete_drop_chore(drop_id))
        self.assertIsNone(db_module.get_drop_chore(drop_id))

    def test_calendar_and_drop_post_create_alerts(self):
        event_name = unique('Family Picnic')
        db_module.create_event(
            event_name, '2026-12-01', 'Bring snacks', '14:30',
            created_by=self.parent_id,
        )
        broadcasts = db_module.get_all_broadcasts(limit=500)
        self.assertTrue(any(
            row['title'] == 'New calendar event' and event_name in row['body']
            for row in broadcasts
        ))

        drop_name = unique('New Drop Alert')
        db_module.create_drop_chore(
            drop_name, 9, 1, created_by=self.parent_id, expires_minutes=30
        )
        broadcasts = db_module.get_all_broadcasts(limit=500)
        self.assertTrue(any(
            row['title'] == f'New drop chore: {drop_name}' for row in broadcasts
        ))

    def test_webhook_dispatches_only_when_alerts_are_enabled(self):
        original = notifications.send_webhook
        calls = []
        notifications.send_webhook = lambda *args, **kwargs: calls.append((args, kwargs)) or True
        try:
            db_module.set_setting('notification_webhook_url', 'https://example.invalid/hook')
            db_module.set_notifications_enabled(False)
            db_module.create_event(
                unique('Quiet Event'), '2026-12-02', created_by=self.parent_id
            )
            self.assertEqual(calls, [])

            db_module.set_notifications_enabled(True)
            event_name = unique('Webhook Event')
            db_module.create_event(
                event_name, '2026-12-03', created_by=self.parent_id
            )
            self.assertTrue(calls)
            args, kwargs = calls[-1]
            self.assertEqual(args[0], 'https://example.invalid/hook')
            self.assertEqual(args[1], 'New calendar event')
            self.assertIn(event_name, args[2])
            self.assertEqual(kwargs.get('target_url'), '/kiosk/calendar')
        finally:
            notifications.send_webhook = original
            db_module.set_setting('notification_webhook_url', '')
            db_module.set_notifications_enabled(True)


class FeatureRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        if not db_module.is_setup_complete():
            db_module.create_user(
                unique('Feature Admin'), None, 'feature-admin-password',
                role='admin', username=unique('feature_admin')
            )
        cls.parent_id = db_module.create_user(
            unique('Feature Route Parent'), None, None, role='parent',
            username=unique('feature_route_parent')
        )
        cls.child_id = db_module.create_user(
            unique('Feature Route Child'), None, None, role='child'
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

    def test_manage_drop_chores_lists_non_available_and_deletes_them(self):
        drop_id = db_module.create_drop_chore(
            unique('Assigned Manage Drop'), 5, 0,
            created_by=self.parent_id, expires_minutes=60,
        )
        db_module.get_db().execute(
            """UPDATE drop_chores
               SET status='assigned', assigned_to=?, current_points=0
               WHERE id=?""",
            (self.child_id, drop_id),
        )
        db_module.get_db().commit()

        self.login_parent()
        page = self.client.get('/drop-chores')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Assigned Manage Drop', page.data)
        self.assertIn(f'/drop-chores/{drop_id}/delete'.encode(), page.data)
        self.assertIn(b'Assigned', page.data)

        response = self.client.post(f'/drop-chores/{drop_id}/delete')
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db_module.get_drop_chore(drop_id))

    def test_kid_dashboard_has_ticker_badges_and_client(self):
        with self.client.session_transaction() as sess:
            sess['kiosk_child_id'] = self.child_id
        page = self.client.get('/kiosk/chores')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'fh-alert-ticker', page.data)
        self.assertIn(b'fh-kid-badge-shelf', page.data)
        self.assertIn(b'/static/js/kid-ticker.js', page.data)

    def test_parent_dashboard_toggle_updates_notification_settings(self):
        self.login_parent()
        response = self.client.post(
            '/dashboard/notifications', data={'enabled': '0'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(db_module.get_notifications_enabled())
        self.assertEqual(db_module.get_setting('mobile_notifications_enabled'), '0')
        self.assertEqual(db_module.get_setting('notifications_enabled'), '0')

        response = self.client.post(
            '/dashboard/notifications', data={'enabled': '1'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(db_module.get_notifications_enabled())


if __name__ == '__main__':
    unittest.main()
