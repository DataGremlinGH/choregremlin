"""Focused tests for the Phase 1 safety net: PINs, currency settings and UTC drop chores."""
import os
import subprocess
import sys
import tempfile
import io
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-tests-'))
os.environ.setdefault('SECRET_KEY', 'phase1-test-secret-key-not-for-production')

import clock  # noqa: E402
import db as db_module  # noqa: E402
import app as app_module  # noqa: E402
import uploads  # noqa: E402
from PIL import Image  # noqa: E402


class Phase1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def test_pin_is_hashed_and_locks_after_five_failures(self):
        user_id = db_module.create_user('Pin Child', None, None, role='child', pin='1234')
        user = db_module.get_user(user_id)
        self.assertNotEqual(user['pin'], '1234')
        self.assertTrue(user['pin'].startswith(('scrypt:', 'pbkdf2:')))

        for _ in range(5):
            result = db_module.check_kiosk_pin(user, '0000')
        self.assertEqual(result, 'locked')

        user = db_module.get_user(user_id)
        self.assertEqual(db_module.check_kiosk_pin(user, '1234'), 'locked')

        db_module.get_db().execute(
            "UPDATE users SET pin_locked_until=NULL WHERE id=?", (user_id,)
        )
        db_module.get_db().commit()
        user = db_module.get_user(user_id)
        self.assertEqual(db_module.check_kiosk_pin(user, '1234'), 'ok')

    def test_currency_code_round_trip(self):
        db_module.save_currency_settings('Stars', 'Star', 'Stars', 0.25, currency_code='EUR')
        currency = db_module.get_currency_settings()
        self.assertEqual(currency['currency_code'], 'EUR')
        self.assertEqual(currency['token_plural'], 'Stars')
        self.assertAlmostEqual(currency['gbp_value'], 0.25)

    def test_drop_chore_does_not_decay_instantly(self):
        db_module.create_user('Drop Child', None, None, role='child')
        drop_id = db_module.create_drop_chore('Test drop', 50, 1, expires_minutes=60)
        db_module.update_drop_chore_points()
        drop = db_module.get_drop_chore(drop_id)
        self.assertGreaterEqual(drop['current_points'], 49.9)
        self.assertLessEqual(drop['current_points'], 50)

    def test_clock_parses_naive_values_as_utc(self):
        parsed = clock.parse_utc('2026-01-01 12:00:00')
        self.assertEqual(parsed.tzinfo, clock.timezone.utc)
        self.assertEqual(clock.format_local('2026-01-01T12:00:00+00:00'), clock.format_local('2026-01-01 12:00:00'))

    def test_data_dir_inside_project_is_rejected(self):
        env = dict(os.environ, CHOREGREMLIN_DATA_DIR=ROOT)
        result = subprocess.run(
            [sys.executable, '-c', 'import db'],
            cwd=ROOT, env=env, capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must be outside the project folder', result.stderr)

    def test_upload_helper_resizes_and_rejects_unsupported_files(self):
        buffer = io.BytesIO()
        Image.new('RGB', (1200, 800), 'red').save(buffer, 'PNG')
        buffer.seek(0)
        buffer.filename = 'photo.png'

        folder = tempfile.mkdtemp(prefix='cg-uploads-')
        saved = uploads.save_image(buffer, folder, 'test', max_side=100)
        self.assertTrue(saved.endswith('.jpg'))
        with Image.open(os.path.join(folder, os.path.basename(saved))) as result:
            self.assertLessEqual(max(result.size), 100)

        bad = io.BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        bad.filename = 'logo.svg'
        with self.assertRaises(uploads.UploadError):
            uploads.save_image(bad, folder, 'test')


if __name__ == '__main__':
    unittest.main()
