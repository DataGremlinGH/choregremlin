"""Release bundle construction and tagging for Phase 17."""
import os
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase17-'))
os.environ.setdefault('SECRET_KEY', 'phase17-test-secret-key-not-for-production')

import release  # noqa: E402
import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class ReleaseHelperTests(unittest.TestCase):
    def test_version_helpers(self):
        self.assertEqual(release.validate_version('2.0.0'), '2.0.0')
        self.assertEqual(release.bump_version('2.0.0', 'patch'), '2.0.1')
        self.assertEqual(release.bump_version('2.0.0', 'minor'), '2.1.0')
        self.assertEqual(release.bump_version('2.0.0', 'major'), '3.0.0')
        self.assertEqual(release.bump_version('2.1.4-rc1', 'patch'), '2.1.5')
        self.assertEqual(release.tag_name('2.0.0'), 'v2.0.0')
        self.assertEqual(
            release.bundle_filename('2.0.0'), 'ChoreGremlin-v2.0.0.zip'
        )
        with self.assertRaises(release.ReleaseError):
            release.validate_version('banana')
        with self.assertRaises(release.ReleaseError):
            release.bump_version('1.0.0', 'sideways')

    def test_build_bundle_excludes_private_files(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, 'migrations'))
            os.makedirs(os.path.join(root, 'venv'))
            os.makedirs(os.path.join(root, '__pycache__'))
            for relative in ('app.py', 'VERSION', 'migrations/001.sql'):
                with open(os.path.join(root, relative), 'w', encoding='utf-8') as handle:
                    handle.write('2.0.0' if relative == 'VERSION' else 'print("ok")\n')
            for relative in ('choregremlin.db', '.env', 'venv/lib.py', '__pycache__/app.pyc'):
                with open(os.path.join(root, relative), 'w', encoding='utf-8') as handle:
                    handle.write('secret')

            out_dir = os.path.join(root, 'dist')
            bundle = release.build_bundle(root, out_dir=out_dir, notes='Test bundle')
            self.assertTrue(os.path.isfile(bundle['path']))
            self.assertEqual(bundle['version'], '2.0.0')
            self.assertEqual(bundle['tag'], 'v2.0.0')
            self.assertEqual(bundle['file_count'], 4)
            self.assertEqual(len(bundle['checksum']), 64)
            self.assertGreater(bundle['size_bytes'], 0)

            with zipfile.ZipFile(bundle['path']) as archive:
                names = set(archive.namelist())
                self.assertIn('choregremlin/app.py', names)
                self.assertIn('choregremlin/VERSION', names)
                self.assertIn('choregremlin/migrations/001.sql', names)
                self.assertIn('choregremlin/RELEASE_INFO.json', names)
                self.assertFalse(any('venv/' in name for name in names))
                self.assertFalse(any('__pycache__' in name for name in names))
                self.assertFalse(any(name.endswith('.db') for name in names))
                self.assertNotIn('choregremlin/.env', names)
                manifest = archive.read('choregremlin/RELEASE_INFO.json').decode()
                self.assertIn('"version": "2.0.0"', manifest)
                self.assertIn('Test bundle', manifest)

            listed = release.list_bundles(out_dir)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]['filename'], bundle['filename'])
            self.assertEqual(listed[0]['checksum'], bundle['checksum'])
            self.assertEqual(release.list_bundles(os.path.join(root, 'missing')), [])

    def test_tag_release_with_fake_runner(self):
        calls = []

        def ok_runner(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0, stdout='', stderr='')

        result = release.tag_release('/tmp/project', '2.0.0', runner=ok_runner)
        self.assertEqual(result['status'], 'tagged')
        self.assertEqual(result['tag'], 'v2.0.0')
        self.assertIn('v2.0.0', calls[0][0])

        def exists_runner(command, **kwargs):
            return SimpleNamespace(
                returncode=128, stdout='', stderr='fatal: tag already exists'
            )

        result = release.tag_release('/tmp/project', '2.0.0', runner=exists_runner)
        self.assertEqual(result['status'], 'exists')

        def error_runner(command, **kwargs):
            return SimpleNamespace(returncode=1, stdout='', stderr='not a git repo')

        result = release.tag_release('/tmp/project', '2.0.0', runner=error_runner)
        self.assertEqual(result['status'], 'error')

    def test_changelog_excerpt(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, 'CHANGELOG.md'), 'w', encoding='utf-8') as handle:
                handle.write('\n'.join(f'line {i}' for i in range(60)))
            excerpt = release.changelog_excerpt(root, limit=10)
            self.assertIn('line 0', excerpt)
            self.assertIn('line 9', excerpt)
            self.assertNotIn('line 10', excerpt)
        self.assertEqual(release.changelog_excerpt('/tmp/nonexistent-root'), '')


class ReleaseRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        admin = db_module.get_user_by_login('phase17_admin')
        if not admin:
            db_module.create_user(
                'Phase 17 Admin', None, 'phase17-admin-password',
                role='admin', username='phase17_admin'
            )
            admin = db_module.get_user_by_login('phase17_admin')
        db_module.set_totp_secret(admin['id'], 'JBSWY3DPEHPK3PXP')
        db_module.enable_totp(admin['id'])
        cls.admin_id = admin['id']
        cls.parent_id = db_module.create_user(
            'Phase 17 Parent', None, None,
            role='parent', username='phase17_parent'
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

    def test_releases_page_loads(self):
        self.login_admin()
        response = self.client.get('/system/releases')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Releases', response.data)
        self.assertIn(b'Build Bundle', response.data)
        self.assertIn(b'Built bundles', response.data)

    def test_build_download_and_tag_routes(self):
        self.login_admin()
        version = '9.9.9'
        response = self.client.post(
            '/system/releases/build',
            data={'version': version, 'notes': 'Route build'},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        filename = release.bundle_filename(version)
        self.assertIn(filename.encode(), response.data)
        path = os.path.join(app_module.RELEASE_DIR, filename)
        self.assertTrue(os.path.isfile(path))

        response = self.client.get(
            f'/system/releases/download/{filename}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/zip')
        response.close()

        with patch.object(app_module.release, 'tag_release', return_value={
            'status': 'tagged', 'tag': 'v9.9.9', 'output': '',
        }):
            response = self.client.post(
                '/system/releases/tag',
                data={'version': version, 'message': 'Route tag'},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Created git tag v9.9.9', response.data)

        self.client.post(
            '/system/releases/tag',
            data={'version': 'not-a-version'},
            follow_redirects=True,
        )

    def test_invalid_build_version_flashes(self):
        self.login_admin()
        response = self.client.post(
            '/system/releases/build',
            data={'version': 'nonsense'},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Version must look like', response.data)

    def test_download_rejects_unknown_and_traversal(self):
        self.login_admin()
        self.assertEqual(
            self.client.get('/system/releases/download/missing.zip').status_code,
            404,
        )
        self.assertEqual(
            self.client.get('/system/releases/download/..%2Fsecret.zip').status_code,
            404,
        )
        self.assertEqual(
            self.client.get('/system/releases/download/notazip.txt').status_code,
            404,
        )

    def test_parent_cannot_open_releases(self):
        self.login_parent()
        self.assertEqual(
            self.client.get('/system/releases').status_code, 403
        )

    def test_release_routes_have_access_rules(self):
        for endpoint in (
            'releases_page', 'release_build', 'release_tag',
            'release_download',
        ):
            self.assertEqual(app_module.ROUTE_ACCESS.get(endpoint), 'admin')


if __name__ == '__main__':
    unittest.main()
