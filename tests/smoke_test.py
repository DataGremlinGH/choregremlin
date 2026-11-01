"""Loads every GET page as an admin and exits non-zero if any returns a server error."""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-smoke-'))
os.environ.setdefault('SECRET_KEY', 'smoke-test-secret-key-not-for-production')

import db as db_module  # noqa: E402
import app as app_module  # noqa: E402

PASSWORD = 'smoke-test-password-1'
SKIP_ENDPOINTS = {'static', 'logout'}


def main():
    db_module.init_db()
    with app_module.app.app_context():
        if not db_module.is_setup_complete():
            db_module.create_user('Smoke Admin', None, PASSWORD, role='admin', username='smoke_admin')

    client = app_module.app.test_client()
    login = client.post('/login', data={'username': 'smoke_admin', 'password': PASSWORD})
    if login.status_code >= 500:
        print(f'Login failed with status {login.status_code}')
        sys.exit(1)

    checked = 0
    failures = []
    for rule in app_module.app.url_map.iter_rules():
        if 'GET' not in rule.methods or rule.endpoint in SKIP_ENDPOINTS:
            continue
        path = re.sub(r'<[^>]+>', '1', rule.rule)
        response = client.get(path)
        checked += 1
        if response.status_code >= 500:
            failures.append(f'{path} -> {response.status_code}')

    print(f'{checked} pages checked')
    if failures:
        for line in failures:
            print(f'FAILED {line}')
        sys.exit(1)
    print('All pages loaded without server errors')


if __name__ == '__main__':
    main()
