"""Snapshot, rollback and automated update checks for Phase 15."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase15-'))
os.environ.setdefault('SECRET_KEY', 'phase15-test-secret-key-not-for-production')

import updater  # noqa: E402
import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class UpdaterHelperTests(unittest.TestCase):
    def test_parse_and_classify(self):
        self.assertEqual(updater.parse_update_output('UPDATE_AVAILABLE\n'), 'available')
        self.assertEqual(updater.parse_update_output('UP_TO_DATE\n'), 'up_to_date')
        self.assertEqual(updater.parse_update_output('ERROR: no git\n'), 'error')
        self.assertEqual(updater.parse_update_output(''), 'error')
        self.assertEqual(updater.parse_update_output('nonsense'), 'unknown')
        self.assertEqual(updater.classify_update('abc', 'abc'), 'up_to_date')
        self.assertEqual(updater.classify_update('abc', 'def'), 'available')
        self.assertEqual(updater.classify_update('', 'def'), 'unknown')

    def test_check_and_apply_with_injected_runner(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if command[0] == 'bash':
                return SimpleNamespace(returncode=0, stdout='UPDATE_AVAILABLE\n', stderr='')
            return SimpleNamespace(returncode=0, stdout='Already up to date.\n', stderr='')

        result = updater.check_for_updates('/tmp/choregremlin', runner=runner)
        self.assertEqual(result['status'], 'available')
        self.assertIn('checked_at', result)
        applied = updater.apply_update('/tmp/choregremlin', runner=runner)
        self.assertEqual(applied['status'], 'updated')
        self.assertEqual(len(calls), 2)
        self.assertIn('git', calls[1][0])

    def test_check_handles_errors(self):
        def runner(command, **kwargs):
            raise RuntimeError('boom')

        result = updater.check_for_updates('/tmp/choregremlin', runner=runner)
        self.assertEqual(result['status'], 'error')
        self.assertIn('boom', result['output'])
        applied = updater.apply_update('/tmp/choregremlin', runner=runner)
        self.assertEqual(applied['status'], 'error')


class SnapshotPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.parent_id = db_module.create_user(
            'Phase 15 Parent', None, None, role='parent', username='phase15_parent'
        )

    @classmethod
    def tearDownClass(cls):
        db = db_module.get_db()
        for snapshot in db_module.get_system_snapshots(limit=1000):
            db_module.delete_system_snapshot(snapshot['id'])
        cls.ctx.pop()

    def test_migration_39_creates_snapshot_table(self):
        db = db_module.get_db()
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()[0]
        self.assertGreaterEqual(version, 39)
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='system_snapshots'"
        ).fetchone()
        self.assertIsNotNone(row)

    def test_create_lists_checksums_and_delete(self):
        snapshot = db_module.create_system_snapshot(
            'Phase 15 Manual', kind='manual', created_by=self.parent_id,
            note='Snapshot test'
        )
        self.assertEqual(snapshot['label'], 'Phase 15 Manual')
        self.assertEqual(snapshot['kind'], 'manual')
        self.assertTrue(snapshot['file_exists'])
        self.assertGreater(snapshot['size_bytes'], 0)
        self.assertEqual(len(snapshot['checksum']), 64)
        self.assertEqual(snapshot['note'], 'Snapshot test')

        snapshots = db_module.get_system_snapshots()
        self.assertTrue(any(item['id'] == snapshot['id'] for item in snapshots))
        usage = db_module.get_snapshot_storage_usage()
        self.assertGreaterEqual(usage['count'], 1)
        self.assertGreater(usage['bytes'], 0)

        deleted = db_module.delete_system_snapshot(snapshot['id'])
        self.assertEqual(deleted['id'], snapshot['id'])
        self.assertIsNone(db_module.get_system_snapshot(snapshot['id']))
        self.assertFalse(os.path.exists(snapshot['path']))
        with self.assertRaises(ValueError):
            db_module.delete_system_snapshot(snapshot['id'])

    def test_validation_helpers(self):
        with self.assertRaises(ValueError):
            db_module.create_system_snapshot('Bad kind', kind='surprise')
        with self.assertRaises(ValueError):
            db_module.create_system_snapshot('x' * 121)
        with self.assertRaises(ValueError):
            db_module.restore_system_snapshot(999999)
        self.assertEqual(db_module.format_file_size(0), '0 B')
        self.assertEqual(db_module.format_file_size(2048), '2.0 KB')

    def test_restore_returns_database_to_snapshot_state(self):
        db_module.set_setting('phase15_marker', 'before')
        snapshot = db_module.create_system_snapshot(
            'Phase 15 Restore', kind='manual', created_by=self.parent_id
        )
        db_module.set_setting('phase15_marker', 'after')
        self.assertEqual(db_module.get_setting('phase15_marker'), 'after')

        restored = db_module.restore_system_snapshot(
            snapshot['id'], created_by=self.parent_id, safety=False
        )
        self.assertIsNotNone(restored)
        self.assertEqual(restored['id'], snapshot['id'])
        self.assertEqual(db_module.get_setting('phase15_marker'), 'before')
        self.assertIsNotNone(db_module.get_system_snapshot(snapshot['id']))
        db_module.delete_system_snapshot(snapshot['id'])


class SnapshotRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        admin = db_module.get_user_by_login('phase15_admin')
        if not admin:
            db_module.create_user(
                'Phase 15 Admin', None, 'phase15-admin-password',
                role='admin', username='phase15_admin'
            )
            admin = db_module.get_user_by_login('phase15_admin')
        db_module.set_totp_secret(admin['id'], 'JBSWY3DPEHPK3PXP')
        db_module.enable_totp(admin['id'])
        cls.admin_id = admin['id']
        cls.parent_id = db_module.create_user(
            'Phase 15 Route Parent', None, None,
            role='parent', username='phase15_route_parent'
        )
        cls.previous_csrf = app_module.app.config.get('WTF_CSRF_ENABLED', True)
        app_module.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.previous_csrf
        cls.ctx.pop()

    def login_admin(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = self.admin_id

    def login_parent(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = self.parent_id

    def test_snapshots_page_loads_and_creates_deletes(self):
        self.login_admin()
        response = self.client.get('/system/snapshots')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Snapshots', response.data)
        self.assertIn(b'Automated Updates', response.data)

        response = self.client.post(
            '/system/snapshots/create',
            data={'label': 'Route snapshot', 'kind': 'manual', 'note': 'via route'},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Route snapshot', response.data)
        snapshot = next(
            item for item in db_module.get_system_snapshots()
            if item['label'] == 'Route snapshot'
        )
        response = self.client.post(
            f"/system/snapshots/{snapshot['id']}/delete",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db_module.get_system_snapshot(snapshot['id']))

    def test_parent_cannot_open_admin_snapshot_page(self):
        self.login_parent()
        response = self.client.get('/system/snapshots')
        self.assertEqual(response.status_code, 403)

    def test_snapshot_routes_have_access_rules(self):
        for endpoint in (
            'snapshots_page', 'snapshot_create', 'snapshot_restore',
            'snapshot_delete', 'update_check', 'update_apply',
        ):
            self.assertEqual(app_module.ROUTE_ACCESS.get(endpoint), 'admin')


if __name__ == '__main__':
    unittest.main()
