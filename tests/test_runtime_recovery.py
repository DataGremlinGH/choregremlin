"""Runtime recovery tests for schema repair, template globals and uploads."""
import io
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-runtime-'))
os.environ.setdefault('SECRET_KEY', 'runtime-recovery-test-secret-key-not-for-production')

import db as db_module  # noqa: E402
import app as app_module  # noqa: E402
from uploads import (  # noqa: E402
    UploadError, ensure_upload_folder, save_image,
)

V2_TABLES = {
    'broadcast_alerts', 'custom_milestones', 'achievement_unlocks',
    'live_events', 'system_snapshots',
}
BROADCAST_COLUMNS = {
    'id', 'title', 'body', 'kind', 'child_id', 'achievement_key', 'icon',
    'color', 'is_active', 'created_by', 'expires_at', 'created_at',
}


class SchemaRecoveryTests(unittest.TestCase):
    def setUp(self):
        db_module.init_db()

    def tearDown(self):
        db_module.init_db()

    def test_current_schema_version_still_recreates_missing_v2_tables(self):
        conn = sqlite3.connect(db_module.DB_PATH)
        for table in (
            'achievement_unlocks', 'broadcast_alerts', 'custom_milestones',
            'live_events', 'system_snapshots',
        ):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (len(db_module.MIGRATIONS),),
        )
        conn.commit()
        conn.close()

        db_module.init_db()

        conn = sqlite3.connect(db_module.DB_PATH)
        names = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(broadcast_alerts)"
            ).fetchall()
        }
        conn.close()

        self.assertEqual(V2_TABLES - names, set())
        self.assertEqual(BROADCAST_COLUMNS - columns, set())


class ContextProcessorRecoveryTests(unittest.TestCase):
    def test_missing_broadcast_table_uses_safe_template_defaults(self):
        with app_module.app.test_request_context('/'):
            with mock.patch.object(
                db_module, 'get_latest_active_broadcast',
                side_effect=sqlite3.OperationalError(
                    'no such table: broadcast_alerts'
                ),
            ):
                values = app_module.inject_globals()

        self.assertIsNone(values['latest_broadcast'])
        self.assertEqual(values['app_name'], 'Chore Gremlin')
        self.assertEqual(values['theme_color'], '#10b981')
        self.assertEqual(values['currency_code'], 'GBP')
        self.assertEqual(values['menu_position'], 'left')


class UploadHardeningTests(unittest.TestCase):
    def test_unwritable_upload_folder_has_user_facing_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = os.path.join(tmp, 'not-a-folder')
            with open(blocker, 'w', encoding='utf-8') as handle:
                handle.write('x')
            with self.assertRaisesRegex(UploadError, 'upload folder'):
                ensure_upload_folder(blocker)

            image = io.BytesIO()
            from PIL import Image
            Image.new('RGB', (8, 8), 'red').save(image, 'PNG')
            image.seek(0)
            from werkzeug.datastructures import FileStorage
            upload = FileStorage(
                stream=image, filename='photo.png', content_type='image/png'
            )
            with self.assertRaisesRegex(UploadError, 'upload folder'):
                save_image(upload, blocker, 'child')

    def test_upload_error_handler_returns_json_for_api_clients(self):
        with app_module.app.test_request_context(
            '/', headers={'Accept': 'application/json'}
        ):
            response, status = app_module.handle_upload_error(
                UploadError('That picture could not be saved.')
            )
        self.assertEqual(status, 400)
        self.assertEqual(
            response.get_json()['message'],
            'That picture could not be saved.',
        )


class ModalLayoutTests(unittest.TestCase):
    def test_password_modals_scroll_without_losing_actions(self):
        css_path = os.path.join(ROOT, 'static', 'css', 'family-hub.css')
        with open(css_path, encoding='utf-8') as handle:
            css = handle.read()
        self.assertRegex(
            css, re.compile(r'\.modal-content\s*\{[^}]*max-height:\s*85vh', re.S)
        )
        self.assertRegex(
            css,
            re.compile(
                r'\.modal-content\s+\.modal-body\s*\{[^}]*overflow-y:\s*auto',
                re.S,
            ),
        )


if __name__ == '__main__':
    unittest.main()
