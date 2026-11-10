"""Initial load, mock-driver and RFID persistence checks for Phase 6."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase6-'))
os.environ.setdefault('SECRET_KEY', 'phase6-test-secret-key-not-for-production')

from flask import Flask  # noqa: E402

import db as db_module  # noqa: E402
import hardware  # noqa: E402
import app as app_module  # noqa: E402


class HardwareLoadTests(unittest.TestCase):
    def setUp(self):
        self.previous_mode = os.environ.get(hardware.MODE_ENV)

    def tearDown(self):
        if self.previous_mode is None:
            os.environ.pop(hardware.MODE_ENV, None)
        else:
            os.environ[hardware.MODE_ENV] = self.previous_mode

    def test_import_does_not_load_gpiozero(self):
        self.assertNotIn('gpiozero', sys.modules)

    def test_mock_backend_auto_initializes(self):
        manager = hardware.HardwareManager(mode='mock')
        self.assertEqual(manager.backend, 'mock')
        self.assertTrue(manager.is_mock)
        self.assertTrue(manager.available())
        self.assertFalse(manager.fallback)
        manager.stop()
        self.assertFalse(manager.available())

    def test_auto_backend_uses_mock_on_non_pi(self):
        if hardware.is_raspberry_pi():
            self.skipTest('This machine is a Raspberry Pi')
        manager = hardware.HardwareManager(mode='auto')
        self.assertEqual(manager.backend, 'mock')
        self.assertFalse(manager.fallback)

    def test_forced_rpi_falls_back_to_mock_on_non_pi(self):
        if hardware.is_raspberry_pi():
            self.skipTest('This machine is a Raspberry Pi')
        manager = hardware.HardwareManager(mode='rpi')
        self.assertEqual(manager.backend, 'mock')
        self.assertTrue(manager.is_mock)
        self.assertTrue(manager.fallback)
        self.assertTrue(manager.available())

    def test_environment_mode_is_respected(self):
        os.environ[hardware.MODE_ENV] = 'mock'
        manager = hardware.HardwareManager()
        self.assertEqual(manager.mode, 'mock')
        self.assertEqual(manager.backend, 'mock')

    def test_mock_rfid_and_button_callbacks(self):
        manager = hardware.HardwareManager(mode='mock')
        seen = []
        manager.on_rfid(lambda tag: seen.append(('rfid', tag)))
        manager.on_button('Start', lambda name: seen.append(('button', name)))

        self.assertTrue(manager.simulate_rfid('ab:cd:12'))
        self.assertTrue(manager.simulate_button('START'))

        self.assertEqual(seen, [('rfid', 'ABCD12'), ('button', 'start')])
        self.assertEqual(manager.provider.events, [
            {'type': 'rfid', 'value': 'ABCD12'},
            {'type': 'button', 'value': 'start'},
        ])

    def test_mock_buzzer_records_patterns(self):
        manager = hardware.HardwareManager(mode='mock')
        self.assertTrue(manager.beep('success'))
        self.assertTrue(manager.beep('error'))
        self.assertEqual(manager.provider.beeps, ['success', 'error'])

    def test_callback_errors_do_not_escape(self):
        manager = hardware.HardwareManager(mode='mock')
        manager.on_rfid(lambda tag: 1 / 0)
        with self.assertLogs('hardware', level='ERROR'):
            self.assertTrue(manager.simulate_rfid('abc'))

    def test_empty_rfid_scan_is_ignored(self):
        manager = hardware.HardwareManager(mode='mock')
        with self.assertLogs('hardware', level='WARNING'):
            self.assertFalse(manager.simulate_rfid('   '))
        self.assertEqual(manager.provider.events, [])

    def test_status_reports_backend(self):
        manager = hardware.HardwareManager(mode='mock')
        status = manager.status()
        self.assertEqual(status['backend'], 'mock')
        self.assertTrue(status['is_mock'])
        self.assertTrue(status['available'])
        self.assertIn('raspberry_pi', status)


class RfidPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = Flask(__name__).app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def test_migration_19_creates_rfid_tags_table(self):
        db = db_module.get_db()
        version = db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
        self.assertGreaterEqual(version, 19)
        table = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='rfid_tags'"
        ).fetchone()
        self.assertIsNotNone(table)

    def test_assign_lookup_and_remove(self):
        child_id = self.child('RFID Child')
        tag_id = db_module.assign_rfid_tag('ab:cd:12', child_id, label='Backpack tag')
        self.assertIsNotNone(tag_id)

        tag = db_module.get_rfid_tag('AB CD 12')
        self.assertIsNotNone(tag)
        self.assertEqual(tag['user_id'], child_id)
        self.assertEqual(tag['tag_uid'], 'ABCD12')
        self.assertEqual(tag['label'], 'Backpack tag')
        self.assertEqual(tag['user_name'], 'RFID Child')

        self.assertTrue(db_module.remove_rfid_tag('abcd-12'))
        self.assertIsNone(db_module.get_rfid_tag('ABCD12'))
        self.assertFalse(db_module.remove_rfid_tag('ABCD12'))

    def test_assign_updates_an_existing_tag(self):
        first_child = self.child('First RFID Child')
        second_child = self.child('Second RFID Child')
        db_module.assign_rfid_tag('TAG-REASSIGN', first_child, label='First')
        db_module.assign_rfid_tag('TAG-REASSIGN', second_child, label='Second')

        tag = db_module.get_rfid_tag('TAGREASSIGN')
        self.assertEqual(tag['user_id'], second_child)
        self.assertEqual(tag['label'], 'Second')
        self.assertEqual(db_module.get_rfid_tags(user_id=second_child)[0]['id'], tag['id'])

    def test_assignment_rejects_non_child_accounts(self):
        parent_id = db_module.create_user('RFID Parent', None, None, role='parent')
        with self.assertRaises(ValueError):
            db_module.assign_rfid_tag('PARENT-TAG', parent_id)

    def test_inactive_tags_are_hidden_from_lookup(self):
        child_id = self.child('Inactive RFID Child')
        db_module.assign_rfid_tag('INACTIVE-TAG', child_id)
        db = db_module.get_db()
        db.execute("UPDATE rfid_tags SET is_active=0 WHERE tag_uid='INACTIVETAG'")
        db.commit()

        self.assertIsNone(db_module.get_rfid_tag('INACTIVETAG'))
        self.assertIsNotNone(db_module.get_rfid_tag('INACTIVETAG', active_only=False))
        active = db_module.get_rfid_tags(user_id=child_id, active_only=True)
        self.assertEqual(active, [])

    def test_empty_tag_is_rejected(self):
        child_id = self.child('Empty RFID Child')
        with self.assertRaises(ValueError):
            db_module.assign_rfid_tag('   ', child_id)
        self.assertIsNone(db_module.get_rfid_tag(''))
        self.assertFalse(db_module.remove_rfid_tag(''))


class KioskRfidIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        if not db_module.is_setup_complete():
            db_module.create_user('Phase 6 Admin', None, 'phase6-test-password',
                                  role='admin', username='phase6_admin')
        cls.previous_csrf = app_module.app.config.get('WTF_CSRF_ENABLED', True)
        app_module.app.config['WTF_CSRF_ENABLED'] = False

    @classmethod
    def tearDownClass(cls):
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.previous_csrf
        cls.ctx.pop()

    def setUp(self):
        self.manager = hardware.HardwareManager(mode='mock')
        app_module.set_hardware_manager(self.manager)
        self.client = app_module.app.test_client()
        with self.client.session_transaction() as sess:
            sess.clear()

    def tearDown(self):
        app_module.set_hardware_manager(None)

    def make_child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def login_child(self, child_id):
        with self.client.session_transaction() as sess:
            sess['kiosk_child_id'] = child_id

    def test_virtual_rfid_scan_selects_child_after_direct_completion(self):
        child_id = self.make_child('RFID Scan Child')
        db_module.assign_rfid_tag('KIOSK-SCAN-1', child_id)
        chore_id = db_module.create_chore('RFID Scan Chore', 'bi-star', 5)
        self.login_child(child_id)

        response = self.client.post(f'/kiosk/complete/{chore_id}')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_active_logs(child_id), [])
        completed = db_module.get_completed_logs(user_id=child_id)
        self.assertEqual(completed[0]['chore_id'], chore_id)
        self.assertIn('success', self.manager.provider.beeps)

        response = self.client.post('/kiosk/scan', json={'tag_uid': 'kiosk scan 1'})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['status'], 'selected')
        self.assertEqual(payload['child_id'], child_id)

    def test_rfid_scan_selects_child_without_active_chore(self):
        child_id = self.make_child('RFID Select Child')
        db_module.assign_rfid_tag('KIOSK-SCAN-2', child_id)

        response = self.client.post('/kiosk/scan', json={'tag_uid': 'KIOSK-SCAN-2'})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['status'], 'selected')
        self.assertEqual(payload['child_id'], child_id)
        self.assertEqual(payload['redirect'], '/kiosk/chores')
        with self.client.session_transaction() as sess:
            self.assertEqual(sess['kiosk_child_id'], child_id)
        self.assertIn('start', self.manager.provider.beeps)

    def test_unknown_rfid_scan_is_rejected(self):
        response = self.client.post('/kiosk/scan', json={'tag_uid': 'UNKNOWN-TAG'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()['status'], 'error')
        with self.client.session_transaction() as sess:
            self.assertNotIn('kiosk_child_id', sess)
        self.assertIn('error', self.manager.provider.beeps)

    def test_scan_requires_a_tag_uid(self):
        response = self.client.post('/kiosk/scan', json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['status'], 'error')
        self.assertIn('error', self.manager.provider.beeps)

    def test_scan_rejects_non_local_requests_without_a_token(self):
        response = self.client.post(
            '/kiosk/scan', json={'tag_uid': 'ANY-TAG'},
            environ_base={'REMOTE_ADDR': '192.168.1.50'}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['status'], 'error')
        self.assertIn('error', self.manager.provider.beeps)

    def test_kiosk_routes_load(self):
        response = self.client.get('/kiosk')
        self.assertEqual(response.status_code, 200)

        child_id = self.make_child('Kiosk Page Child')
        self.login_child(child_id)
        response = self.client.get('/kiosk/chores')
        self.assertEqual(response.status_code, 200)

    def test_hardware_rfid_event_selects_child_without_active_chore(self):
        app_module.set_hardware_manager(None)
        manager = app_module.get_hardware()
        child_id = self.make_child('RFID Event Child')
        db_module.assign_rfid_tag('KIOSK-EVENT-1', child_id)
        self.login_child(child_id)

        self.assertTrue(manager.simulate_rfid('KIOSK-EVENT-1'))
        self.assertEqual(db_module.get_active_logs(child_id), [])
        self.assertIn('start', manager.provider.beeps)

    def test_kiosk_complete_button_emits_buzzer_feedback(self):
        child_id = self.make_child('RFID Buzzer Child')
        chore_id = db_module.create_chore('Buzzer Complete Chore', 'bi-star', 2)
        self.login_child(child_id)

        self.client.post(f'/kiosk/complete/{chore_id}')
        self.assertIn('success', self.manager.provider.beeps)

        self.client.post(f'/kiosk/complete/{chore_id}')
        self.assertIn('error', self.manager.provider.beeps)

        response = self.client.post('/kiosk/cancel/999999')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('cancel', self.manager.provider.beeps)

    def test_kiosk_css_has_pi_touch_breakpoints(self):
        css_path = os.path.join(ROOT, 'static', 'css', 'family-hub.css')
        with open(css_path, encoding='utf-8') as handle:
            css = handle.read()
        self.assertIn('@media (max-width: 1024px) and (max-height: 600px)', css)
        self.assertIn('@media (max-width: 800px) and (max-height: 480px)', css)
        self.assertIn('min-height: 44px', css)

    def test_rfid_scan_endpoint_has_an_access_rule(self):
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_rfid_scan'), 'public')


if __name__ == '__main__':
    unittest.main()
