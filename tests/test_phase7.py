"""Experience, streak and reward-store checks for Phase 7."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase7-'))
os.environ.setdefault('SECRET_KEY', 'phase7-test-secret-key-not-for-production')

import db as db_module  # noqa: E402
import gamification  # noqa: E402
import app as app_module  # noqa: E402


class GamificationEngineTests(unittest.TestCase):
    def test_xp_is_bound_to_reward_value(self):
        self.assertEqual(gamification.base_xp_for_reward(0), 1)
        self.assertEqual(gamification.base_xp_for_reward(1), 10)
        self.assertEqual(gamification.base_xp_for_reward(2.5), 25)
        self.assertEqual(gamification.base_xp_for_reward(5), 50)

    def test_streak_multipliers_scale_with_consecutive_days(self):
        self.assertEqual(gamification.streak_multiplier(1), 1.0)
        self.assertEqual(gamification.streak_multiplier(2), 1.0)
        self.assertEqual(gamification.streak_multiplier(3), 1.1)
        self.assertEqual(gamification.streak_multiplier(7), 1.5)
        self.assertEqual(gamification.streak_multiplier(30), 2.0)

        result = gamification.calculate_xp(5, 7)
        self.assertEqual(result['base_xp'], 50)
        self.assertEqual(result['multiplier'], 1.5)
        self.assertEqual(result['xp_awarded'], 75)

    def test_levels_and_progress(self):
        self.assertEqual(gamification.level_for_xp(0), 1)
        self.assertEqual(gamification.level_for_xp(99), 1)
        self.assertEqual(gamification.level_for_xp(100), 2)
        self.assertEqual(gamification.level_for_xp(250), 3)
        progress = gamification.level_progress(250)
        self.assertEqual(progress['level'], 3)
        self.assertEqual(progress['xp_into_level'], 50)
        self.assertEqual(progress['progress_percent'], 50.0)

    def test_streak_advances_on_consecutive_days_and_resets_after_a_gap(self):
        self.assertEqual(gamification.next_completion_streak(None, 0, '2026-01-01'), 1)
        self.assertEqual(gamification.next_completion_streak('2026-01-01', 1, '2026-01-01'), 1)
        self.assertEqual(gamification.next_completion_streak('2026-01-01', 1, '2026-01-02'), 2)
        self.assertEqual(gamification.next_completion_streak('2026-01-02', 2, '2026-01-04'), 1)

    def test_catalog_is_unique_and_has_locked_and_unlocked_items(self):
        for item_type, catalog in gamification.CATALOGS.items():
            keys = [item['key'] for item in catalog]
            self.assertEqual(len(keys), len(set(keys)), item_type)

        avatars = gamification.catalog_with_status(
            'avatar', level=1, total_xp=0, longest_streak=0, current_streak=0
        )
        unlocked = {item['key'] for item in avatars if item['unlocked']}
        self.assertIn('default', unlocked)
        self.assertNotIn('champion', unlocked)

        avatars = gamification.catalog_with_status(
            'avatar', level=3, total_xp=200, longest_streak=7, current_streak=7
        )
        unlocked = {item['key'] for item in avatars if item['unlocked']}
        self.assertTrue({'default', 'explorer', 'rocket', 'dragon'}.issubset(unlocked))
        self.assertNotIn('champion', unlocked)


class GamificationPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def test_migration_22_creates_gamification_tables(self):
        db = db_module.get_db()
        version = db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
        self.assertGreaterEqual(version, 22)
        names = {
            row['name'] for row in db.execute(
                """SELECT name FROM sqlite_master WHERE type='table'
                   AND name IN ('user_gamification', 'xp_events', 'gamification_unlocks')"""
            ).fetchall()
        }
        self.assertEqual(names, {'user_gamification', 'xp_events', 'gamification_unlocks'})

    def test_record_xp_updates_stats_streak_and_unlocks(self):
        child_id = self.child('XP Persistence Child')
        first = db_module.record_xp(
            child_id, 2, completed_date='2026-02-01',
            source_type='chore', source_id=1001
        )
        self.assertTrue(first['awarded'])
        self.assertEqual(first['stats']['total_xp'], 20)
        self.assertEqual(first['stats']['current_streak'], 1)
        unlocked_items = db_module.get_unlocked_items(child_id)
        self.assertIn('default', {
            item['item_key'] for item in unlocked_items if item['item_type'] == 'avatar'
        })
        self.assertIn('helper', {
            item['item_key'] for item in unlocked_items if item['item_type'] == 'badge'
        })

        duplicate = db_module.record_xp(
            child_id, 2, completed_date='2026-02-01',
            source_type='chore', source_id=1001
        )
        self.assertFalse(duplicate['awarded'])
        self.assertEqual(duplicate['stats']['total_xp'], 20)

        second = db_module.record_xp(
            child_id, 2, completed_date='2026-02-02',
            source_type='chore', source_id=1002
        )
        self.assertEqual(second['stats']['current_streak'], 2)
        self.assertEqual(second['stats']['total_xp'], 40)

        third = db_module.record_xp(
            child_id, 2, completed_date='2026-02-03',
            source_type='chore', source_id=1003
        )
        self.assertEqual(third['stats']['current_streak'], 3)
        self.assertEqual(third['stats']['total_xp'], 62)
        self.assertEqual(third['event']['multiplier'], 1.1)
        self.assertEqual(third['stats']['longest_streak'], 3)

    def test_streak_break_resets_current_but_keeps_longest(self):
        child_id = self.child('XP Streak Break Child')
        db_module.record_xp(child_id, 1, completed_date='2026-03-01', source_id=2001)
        db_module.record_xp(child_id, 1, completed_date='2026-03-02', source_id=2002)
        stats = db_module.get_gamification(child_id)
        self.assertEqual(stats['current_streak'], 2)
        self.assertEqual(stats['longest_streak'], 2)

        result = db_module.record_xp(child_id, 1, completed_date='2026-03-05', source_id=2003)
        self.assertEqual(result['stats']['current_streak'], 1)
        self.assertEqual(result['stats']['longest_streak'], 2)

    def test_approved_chore_awards_xp_once(self):
        child_id = self.child('XP Approval Child')
        parent_id = db_module.create_user('XP Approval Parent', None, None, role='parent')
        chore_id = db_module.create_chore('XP Approval Chore', 'bi-star', 5)
        log_id = db_module.start_chore(child_id, chore_id)
        db_module.finish_chore(log_id)

        self.assertIsNotNone(db_module.approve_chore(log_id, parent_id))
        stats = db_module.get_gamification(child_id)
        self.assertEqual(stats['total_xp'], 50)

        self.assertIsNone(db_module.approve_chore(log_id, parent_id))
        stats = db_module.get_gamification(child_id)
        self.assertEqual(stats['total_xp'], 50)
        self.assertEqual(len(db_module.get_xp_events(child_id)), 1)

    def test_rejected_chore_does_not_award_xp(self):
        child_id = self.child('XP Reject Child')
        chore_id = db_module.create_chore('XP Reject Chore', 'bi-star', 4)
        log_id = db_module.start_chore(child_id, chore_id)
        db_module.finish_chore(log_id)
        self.assertIsNotNone(db_module.reject_chore(log_id))
        stats = db_module.get_gamification(child_id)
        self.assertEqual(stats['total_xp'], 0)
        self.assertEqual(db_module.get_xp_events(child_id), [])

    def test_drop_chore_awards_xp_once(self):
        child_id = self.child('XP Drop Child')
        drop_id = db_module.create_drop_chore('XP Drop Chore', 3, 0)
        drop = db_module.claim_drop_chore(drop_id, child_id)
        self.assertIsNotNone(drop)
        first = db_module.award_drop_xp(child_id, drop)
        self.assertTrue(first['awarded'])
        self.assertEqual(first['stats']['total_xp'], 30)
        second = db_module.award_drop_xp(child_id, drop)
        self.assertFalse(second['awarded'])
        self.assertEqual(second['stats']['total_xp'], 30)

    def test_rewards_can_only_be_equipped_when_unlocked(self):
        child_id = self.child('XP Equip Child')
        db_module.record_xp(child_id, 10, completed_date='2026-04-01', source_id=3001)
        stats = db_module.get_gamification(child_id)
        self.assertEqual(stats['level'], 2)

        equipped = db_module.equip_gamification_item(child_id, 'avatar', 'explorer')
        self.assertEqual(equipped['equipped_avatar'], 'explorer')
        equipped = db_module.equip_gamification_item(child_id, 'badge', 'helper')
        self.assertEqual(equipped['equipped_badge'], 'helper')
        equipped = db_module.equip_gamification_item(child_id, 'badge', '')
        self.assertEqual(equipped['equipped_badge'], '')

        with self.assertRaises(ValueError):
            db_module.equip_gamification_item(child_id, 'avatar', 'robot')
        with self.assertRaises(ValueError):
            db_module.equip_gamification_item(child_id, 'badge', 'unknown')


class GamificationRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        if not db_module.is_setup_complete():
            db_module.create_user('Phase 7 Admin', None, 'phase7-test-password',
                                  role='admin', username='phase7_admin')
        cls.parent_id = db_module.create_user(
            'Phase 7 Parent', None, None, role='parent', username='phase7_parent'
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

    def login_child(self, child_id):
        with self.client.session_transaction() as sess:
            sess['kiosk_child_id'] = child_id

    def test_parent_rewards_page_loads(self):
        child_id = db_module.create_user('Phase 7 Page Child', None, None, role='child')
        db_module.record_xp(child_id, 2, completed_date='2026-05-01', source_id=4001)
        self.login_parent()
        response = self.client.get('/rewards')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Phase 7 Page Child', response.data)
        self.assertIn(b'Avatar Store', response.data)

    def test_kiosk_rewards_page_and_equip(self):
        child_id = db_module.create_user('Phase 7 Kiosk Child', None, None, role='child')
        self.login_child(child_id)

        response = self.client.get('/kiosk/rewards')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Avatar Store', response.data)

        response = self.client.post('/kiosk/rewards/equip', data={
            'item_type': 'avatar', 'item_key': 'default'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_gamification(child_id)['equipped_avatar'], 'default')

        response = self.client.post('/kiosk/rewards/equip', data={
            'item_type': 'avatar', 'item_key': 'champion'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'still locked', response.data)

    def test_approval_route_awards_xp(self):
        child_id = db_module.create_user('Phase 7 Approval Route Child', None, None, role='child')
        chore_id = db_module.create_chore('Phase 7 Approval Route Chore', 'bi-star', 3)
        log_id = db_module.start_chore(child_id, chore_id)
        db_module.finish_chore(log_id)
        self.login_parent()

        response = self.client.post(f'/approvals/{log_id}/approve')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db_module.get_gamification(child_id)['total_xp'], 30)

    def test_gamification_routes_have_access_rules(self):
        self.assertEqual(app_module.ROUTE_ACCESS.get('rewards'), 'staff')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_rewards'), 'kiosk')
        self.assertEqual(app_module.ROUTE_ACCESS.get('kiosk_equip_reward'), 'kiosk')


if __name__ == '__main__':
    unittest.main()
