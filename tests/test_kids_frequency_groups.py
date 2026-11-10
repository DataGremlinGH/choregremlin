"""Tests for grouping chores by repeat frequency on the Kids page."""
import os
import sys
import tempfile
import unittest
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-kids-freq-'))
os.environ.setdefault('SECRET_KEY', 'kids-frequency-test-secret-not-for-production')

import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


def unique(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


class FrequencyGroupingTests(unittest.TestCase):
    def test_group_chores_by_frequency_maps_aliases(self):
        chores = [
            {'name': 'Daily', 'repeat_frequency': 'daily', 'due_days': '0,1'},
            {'name': 'Weekly', 'repeat_frequency': 'weekly', 'due_days': '0'},
            {'name': 'Monthly', 'repeat_frequency': 'monthly', 'due_days': '0'},
            {'name': 'Weekend', 'repeat_frequency': 'weekends', 'due_days': '5,6'},
            {'name': 'Custom', 'repeat_frequency': 'custom', 'due_days': '1,3'},
            {'name': 'Set Days', 'repeat_frequency': 'set_days', 'due_days': '2,4'},
        ]
        groups = app_module.group_chores_by_frequency(chores)
        by_key = {group['key']: group for group in groups}

        self.assertEqual(
            [group['key'] for group in groups],
            ['daily', 'weekly', 'monthly', 'weekend', 'set_days'],
        )
        self.assertEqual(len(by_key['weekend']['chores']), 1)
        self.assertEqual(len(by_key['set_days']['chores']), 2)
        self.assertEqual(
            by_key['set_days']['chores'][0]['due_day_labels'], ['Tue', 'Thu']
        )

    def test_kids_page_renders_frequency_headings(self):
        db_module.init_db()
        with app_module.app.app_context():
            if not db_module.is_setup_complete():
                db_module.create_user(
                    unique('Frequency Admin'), None, 'frequency-admin-password',
                    role='admin', username=unique('frequency_admin'),
                )
            parent = db_module.create_user(
                unique('Frequency Parent'), None, None, role='parent',
                username=unique('frequency_parent'),
            )
            for frequency in ('daily', 'weekly', 'monthly', 'weekends', 'custom'):
                db_module.create_chore(
                    unique(f'Frequency {frequency}'), 'bi-list-check', 2,
                    repeat_frequency=frequency, due_days='0,6',
                )

        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = parent
        response = client.get('/kids')

        self.assertEqual(response.status_code, 200)
        for heading in (b'Daily', b'Weekly', b'Monthly', b'Weekend', b'Set Days'):
            self.assertIn(heading, response.data)


if __name__ == '__main__':
    unittest.main()
