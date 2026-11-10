"""Live SSE event bus, alert feed and push checks for Phase 14."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase14-'))
os.environ.setdefault('SECRET_KEY', 'phase14-test-secret-key-not-for-production')

import events  # noqa: E402
import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class EventBusTests(unittest.TestCase):
    def setUp(self):
        events.reset()

    def tearDown(self):
        events.reset()

    def test_publish_subscribe_history_and_unsubscribe(self):
        audience = events.subscribe()
        self.assertEqual(events.subscriber_count(), 1)
        event = events.publish('broadcast', {'title': 'Hello'})
        self.assertEqual(event['type'], 'broadcast')
        queued = audience.get_nowait()
        self.assertEqual(queued['data']['title'], 'Hello')
        self.assertEqual(events.recent(1)[0]['type'], 'broadcast')
        events.unsubscribe(audience)
        self.assertEqual(events.subscriber_count(), 0)
        events.publish('idle')
        self.assertEqual(events.recent(1)[0]['type'], 'idle')

    def test_format_sse_frame(self):
        frame = events.format_sse({
            'id': 7, 'type': 'achievement',
            'data': {'title': 'Badge', 'payload': {'key': 'first_chore'}},
        })
        self.assertIn('id: 7\n', frame)
        self.assertIn('event: achievement\n', frame)
        self.assertIn('data: ', frame)
        self.assertTrue(frame.endswith('\n\n'))
        parsed = json.loads(frame.split('data: ', 1)[1].strip())
        self.assertEqual(parsed['payload']['key'], 'first_chore')

    def test_full_queue_drops_oldest_without_raising(self):
        audience = events.subscribe(maxsize=1)
        events.publish('one')
        events.publish('two')
        self.assertEqual(audience.get_nowait()['type'], 'two')
        events.unsubscribe(audience)


class LiveEventPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.parent_id = db_module.create_user(
            'Phase 14 Parent', None, None, role='parent', username='phase14_parent'
        )

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def setUp(self):
        events.reset()

    def tearDown(self):
        events.reset()
        db = db_module.get_db()
        db.execute("DELETE FROM live_events")
        db.execute("DELETE FROM broadcast_alerts")
        db.commit()

    def test_migration_38_creates_live_events_table(self):
        db = db_module.get_db()
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()[0]
        self.assertGreaterEqual(version, 38)
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='live_events'"
        ).fetchone()
        self.assertIsNotNone(row)

    def test_record_and_read_live_events(self):
        row = db_module.record_live_event(
            'achievement', title='Badge unlocked', body='Well done',
            payload={'key': 'first_chore'}, child_id=None,
        )
        self.assertEqual(row['event_type'], 'achievement')
        latest = db_module.get_latest_live_event_id()
        self.assertGreaterEqual(latest, row['id'])
        items = db_module.get_live_events(after_id=row['id'] - 1, limit=10)
        self.assertEqual(items[-1]['title'], 'Badge unlocked')
        self.assertEqual(items[-1]['payload']['key'], 'first_chore')
        recent = db_module.get_recent_live_events(limit=5)
        self.assertTrue(any(item['id'] == row['id'] for item in recent))

    def test_broadcast_and_achievement_publish_live_events(self):
        child_id = db_module.create_user('Phase 14 Child', None, None, role='child')
        broadcast = db_module.create_broadcast_alert(
            'Phase 14 Broadcast', body='Hello family', child_id=child_id
        )
        self.assertIsNotNone(broadcast)
        broadcast_events = [
            item for item in db_module.get_recent_live_events(limit=20)
            if item['event_type'] == 'broadcast'
        ]
        self.assertTrue(any(
            item['payload'].get('id') == broadcast['id'] for item in broadcast_events
        ))
        self.assertTrue(any(
            item['type'] == 'broadcast' for item in events.recent(20)
        ))

        chore_id = db_module.create_chore('Phase 14 Chore', 'bi-star', 2)
        log_id = db_module.start_chore(child_id, chore_id)
        db_module.finish_chore(log_id)
        db_module.approve_chore(log_id, self.parent_id)
        achievement_events = [
            item for item in db_module.get_recent_live_events(limit=50)
            if item['event_type'] == 'achievement'
        ]
        self.assertTrue(achievement_events)


class LiveRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        if not db_module.is_setup_complete():
            db_module.create_user(
                'Phase 14 Admin', None, 'phase14-admin-password',
                role='admin', username='phase14_admin'
            )
        cls.parent_id = db_module.create_user(
            'Phase 14 Route Parent', None, None,
            role='parent', username='phase14_route_parent'
        )
        cls.previous_csrf = app_module.app.config.get('WTF_CSRF_ENABLED', True)
        app_module.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.previous_csrf
        cls.ctx.pop()

    def setUp(self):
        events.reset()

    def login_parent(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = self.parent_id

    def test_stream_once_returns_sse_frames(self):
        db_module.record_live_event(
            'broadcast', title='Stream hello', body='Test body',
            payload={'kind': 'celebration'},
        )
        self.login_parent()
        response = self.client.get('/events/stream?once=1')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.mimetype.startswith('text/event-stream'))
        self.assertIn(b'event: ready', response.data)
        self.assertIn(b'event: broadcast', response.data)
        self.assertIn(b'Stream hello', response.data)

    def test_alerts_feed_returns_broadcasts_and_events(self):
        child_id = db_module.create_user(
            'Phase 14 Alert Child', None, None, role='child'
        )
        broadcast = db_module.create_broadcast_alert(
            'Feed broadcast', child_id=child_id
        )
        self.login_parent()
        response = self.client.get('/api/alerts')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn('broadcasts', payload)
        self.assertIn('events', payload)
        self.assertGreaterEqual(payload['latest_event_id'], 1)
        self.assertTrue(any(
            item['id'] == broadcast['id'] for item in payload['broadcasts']
        ))

    def test_stream_requires_a_live_session(self):
        anonymous = app_module.app.test_client()
        self.assertEqual(anonymous.get('/events/stream?once=1').status_code, 401)
        self.assertEqual(anonymous.get('/api/alerts').status_code, 401)

    def test_live_routes_have_access_rules(self):
        self.assertEqual(app_module.ROUTE_ACCESS.get('events_stream'), 'live')
        self.assertEqual(app_module.ROUTE_ACCESS.get('alerts_feed'), 'live')

    def test_push_handlers_and_client_are_deployed(self):
        with open(os.path.join(ROOT, 'static', 'js', 'sw.js'), encoding='utf-8') as f:
            worker = f.read()
        self.assertIn("addEventListener('push'", worker)
        self.assertIn("addEventListener('notificationclick'", worker)
        with open(os.path.join(ROOT, 'templates', 'base.html'), encoding='utf-8') as f:
            base = f.read()
        self.assertIn('live-alerts.js', base)
        with open(os.path.join(ROOT, 'static', 'js', 'live-alerts.js'), encoding='utf-8') as f:
            client = f.read()
        self.assertIn('EventSource', client)
        self.assertIn('Notification', client)


if __name__ == '__main__':
    unittest.main()
