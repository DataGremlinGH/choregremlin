"""Achievement, custom milestone and family broadcast checks for Phase 12."""
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('CHOREGREMLIN_DATA_DIR', tempfile.mkdtemp(prefix='cg-phase12-'))
os.environ.setdefault('SECRET_KEY', 'phase12-test-secret-key-not-for-production')

import achievements  # noqa: E402
import db as db_module  # noqa: E402
import app as app_module  # noqa: E402


class AchievementDefinitionTests(unittest.TestCase):
    def test_builtin_catalog_is_unique_and_valid(self):
        keys = [item['key'] for item in achievements.BUILTIN_ACHIEVEMENTS]
        self.assertEqual(len(keys), len(set(keys)))
        for item in achievements.BUILTIN_ACHIEVEMENTS:
            self.assertIn(item['metric'], achievements.METRICS)
            self.assertGreater(item['threshold'], 0)
            self.assertTrue(item['icon'].startswith('bi-'))

        definitions = achievements.builtin_definitions()
        self.assertEqual(len(definitions), len(achievements.BUILTIN_ACHIEVEMENTS))
        for item in definitions:
            self.assertEqual(item['reward_type'], 'none')
            self.assertEqual(item['reward_value'], 0)
            self.assertIn(item['category'], achievements.CATEGORY_ORDER)
            self.assertTrue(item['requirement'])

    def test_progress_and_formatting(self):
        self.assertEqual(achievements.progress_percent(5, 10), 50.0)
        self.assertEqual(achievements.progress_percent(20, 10), 100.0)
        self.assertEqual(achievements.progress_percent(-5, 10), 0.0)
        self.assertEqual(achievements.remaining(3, 10), 7.0)
        self.assertEqual(achievements.remaining(12, 10), 0.0)
        self.assertEqual(achievements.format_value('chores_completed', 10), '10')
        self.assertEqual(achievements.format_value('savings_balance', 10), '10.00')
        self.assertEqual(
            achievements.requirement_text('chores_completed', 10),
            'Chores completed: 10'
        )

    def test_validation_helpers(self):
        self.assertEqual(achievements.normalize_metric('chores_completed'),
                         'chores_completed')
        self.assertEqual(achievements.normalize_reward_type('XP'), 'xp')
        self.assertEqual(achievements.normalize_threshold('3.5'), 3.5)
        self.assertEqual(achievements.normalize_reward_value('2.5', 'bonus'), 2.5)
        self.assertEqual(achievements.normalize_reward_value('99', 'none'), 0.0)
        self.assertEqual(achievements.clean_icon('bad'), 'bi-award-fill')
        self.assertEqual(achievements.clean_color('red'), '#10b981')
        with self.assertRaises(ValueError):
            achievements.normalize_metric('unknown')
        with self.assertRaises(ValueError):
            achievements.normalize_reward_type('cash')
        with self.assertRaises(ValueError):
            achievements.normalize_threshold(0)
        with self.assertRaises(ValueError):
            achievements.normalize_reward_value(0, 'xp')

    def test_evaluate_returns_only_newly_met_definitions(self):
        definitions = achievements.builtin_definitions()
        metrics = {'chores_completed': 10, 'longest_streak': 0, 'level': 1}
        ready = achievements.evaluate(metrics, {'first_chore'}, definitions)
        keys = {item['key'] for item in ready}
        self.assertNotIn('first_chore', keys)
        self.assertIn('chores_10', keys)
        self.assertNotIn('chores_50', keys)


class AchievementPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.parent_id = db_module.create_user(
            'Phase 12 Parent', None, None, role='parent', username='phase12_parent'
        )

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def tearDown(self):
        db = db_module.get_db()
        db.execute("DELETE FROM custom_milestones")
        db.execute("DELETE FROM broadcast_alerts")
        db.execute("DELETE FROM achievement_unlocks")
        db.commit()

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def approved_chore(self, child_id, reward=2):
        chore_id = db_module.create_chore(
            f'Phase 12 Chore {child_id}', 'bi-star', reward
        )
        log_id = db_module.start_chore(child_id, chore_id)
        db_module.finish_chore(log_id)
        return db_module.approve_chore(log_id, self.parent_id)

    def test_migration_37_creates_achievement_tables(self):
        db = db_module.get_db()
        version = db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()[0]
        self.assertGreaterEqual(version, 37)
        names = {
            row['name'] for row in db.execute(
                """SELECT name FROM sqlite_master WHERE type='table'
                   AND name IN ('broadcast_alerts', 'custom_milestones',
                                'achievement_unlocks')"""
            ).fetchall()
        }
        self.assertEqual(names, {
            'broadcast_alerts', 'custom_milestones', 'achievement_unlocks'
        })

    def test_approved_chore_unlocks_achievement_and_broadcast(self):
        child_id = self.child('Phase 12 First Chore Child')
        log = self.approved_chore(child_id)
        self.assertIsNotNone(log)

        unlocks = {
            row['achievement_key'] for row in
            db_module.get_achievement_unlocks(child_id)
        }
        self.assertIn('first_chore', unlocks)
        broadcast = db_module.get_latest_active_broadcast()
        self.assertIsNotNone(broadcast)
        self.assertEqual(broadcast['achievement_key'], 'first_chore')
        self.assertEqual(broadcast['child_id'], child_id)

    def test_achievement_evaluation_is_idempotent(self):
        child_id = self.child('Phase 12 Idempotent Child')
        self.approved_chore(child_id)
        first_count = len(db_module.get_achievement_unlocks(child_id))
        first_broadcasts = len(db_module.get_all_broadcasts(limit=100))
        self.assertGreater(first_count, 0)

        db_module.evaluate_achievements(child_id)
        db_module.evaluate_achievements(child_id)
        self.assertEqual(len(db_module.get_achievement_unlocks(child_id)), first_count)
        self.assertEqual(
            len(db_module.get_all_broadcasts(limit=100)), first_broadcasts
        )

    def test_custom_bonus_milestone_pays_once(self):
        child_id = self.child('Phase 12 Bonus Milestone Child')
        db_module.create_payment(
            child_id, 10, ptype='earning',
            description='Phase 12 funding', auto_repay=False
        )
        milestone = db_module.create_custom_milestone(
            'Earn ten', description='First ten earned', metric='total_earned',
            threshold=10, reward_type='bonus', reward_value=5
        )
        self.assertEqual(milestone['reward_label'], '5.00 bonus')

        added = db_module.evaluate_achievements(child_id)
        self.assertTrue(any(item['name'] == 'Earn ten' for item in added))
        self.assertEqual(db_module.get_balance(child_id), 15)
        rewards = [
            payment for payment in db_module.get_payments(child_id)
            if payment['type'] == 'milestone_reward'
        ]
        self.assertEqual(len(rewards), 1)
        self.assertEqual(rewards[0]['amount'], 5)

        unlock = db_module.get_db().execute(
            """SELECT * FROM achievement_unlocks
               WHERE user_id=? AND achievement_key=?""",
            (child_id, milestone['key'])
        ).fetchone()
        self.assertEqual(unlock['reward_payment_id'], rewards[0]['id'])
        self.assertIsNotNone(unlock['broadcast_id'])

        db_module.evaluate_achievements(child_id)
        rewards = [
            payment for payment in db_module.get_payments(child_id)
            if payment['type'] == 'milestone_reward'
        ]
        self.assertEqual(len(rewards), 1)

    def test_custom_xp_milestone_awards_xp_event(self):
        child_id = self.child('Phase 12 XP Milestone Child')
        milestone = db_module.create_custom_milestone(
            'First chore XP', metric='chores_completed', threshold=1,
            reward_type='xp', reward_value=25
        )
        self.approved_chore(child_id)

        stats = db_module.get_gamification(child_id)
        self.assertEqual(stats['total_xp'], 45)
        events = db_module.get_xp_events(child_id)
        self.assertTrue(any(
            event['source_type'] == 'achievement'
            and event['xp_awarded'] == 25
            for event in events
        ))
        unlock = db_module.get_db().execute(
            """SELECT * FROM achievement_unlocks
               WHERE user_id=? AND achievement_key=?""",
            (child_id, milestone['key'])
        ).fetchone()
        self.assertIsNotNone(unlock)

    def test_custom_milestone_validation_toggle_and_delete(self):
        with self.assertRaises(ValueError):
            db_module.create_custom_milestone('', metric='chores_completed')
        with self.assertRaises(ValueError):
            db_module.create_custom_milestone('Bad metric', metric='nope')
        with self.assertRaises(ValueError):
            db_module.create_custom_milestone('Bad target', threshold=0)
        with self.assertRaises(ValueError):
            db_module.create_custom_milestone(
                'Bad reward', reward_type='bonus', reward_value=0
            )
        with self.assertRaises(ValueError):
            db_module.create_custom_milestone('x' * 101)

        milestone = db_module.create_custom_milestone(
            'Toggle me', metric='bills_paid', threshold=2
        )
        paused = db_module.set_custom_milestone_active(milestone['id'], False)
        self.assertEqual(paused['is_active'], 0)
        active = db_module.set_custom_milestone_active(milestone['id'], True)
        self.assertEqual(active['is_active'], 1)
        deleted = db_module.delete_custom_milestone(milestone['id'])
        self.assertEqual(deleted['name'], 'Toggle me')
        self.assertIsNone(db_module.get_custom_milestone(milestone['id']))
        with self.assertRaises(ValueError):
            db_module.delete_custom_milestone(milestone['id'])

    def test_savings_deposit_unlocks_savings_badge(self):
        child_id = self.child('Phase 12 Savings Child')
        db_module.create_payment(
            child_id, 20, ptype='earning',
            description='Phase 12 savings funding', auto_repay=False
        )
        db_module.deposit_to_savings(child_id, 10)
        unlocks = {
            row['achievement_key'] for row in
            db_module.get_achievement_unlocks(child_id)
        }
        self.assertIn('savings_10', unlocks)

    def test_bill_payment_unlocks_bill_badge(self):
        child_id = self.child('Phase 12 Bill Child')
        db_module.create_payment(
            child_id, 50, ptype='earning',
            description='Phase 12 bill funding', auto_repay=False
        )
        db_module.create_household_bill(
            child_id, 'Phase 12 Phone', 'utilities', 20, 'weekly',
            '2026-01-01', auto_deduct=False
        )
        db_module.schedule_due_bills(now='2026-01-01')
        occurrence = db_module.get_bill_occurrences(
            user_id=child_id, include_paid=False, limit=1
        )[0]
        db_module.pay_bill_occurrence(
            occurrence['id'], source='manual', now='2026-01-01'
        )
        unlocks = {
            row['achievement_key'] for row in
            db_module.get_achievement_unlocks(child_id)
        }
        self.assertIn('bills_1', unlocks)

    def test_marketplace_order_unlocks_shopper_badge(self):
        child_id = self.child('Phase 12 Shopper Child')
        db_module.create_payment(
            child_id, 50, ptype='earning',
            description='Phase 12 shop funding', auto_repay=False
        )
        item_id = db_module.create_marketplace_item(
            'Phase 12 Shop Item', 10, requires_approval=0
        )
        db_module.create_marketplace_order(child_id, item_id)
        unlocks = {
            row['achievement_key'] for row in
            db_module.get_achievement_unlocks(child_id)
        }
        self.assertIn('shop_1', unlocks)

    def test_active_broadcasts_ignore_expired_and_cleared(self):
        active = db_module.create_broadcast_alert('Active broadcast')
        expired = db_module.create_broadcast_alert(
            'Expired broadcast', expires_at='2000-01-01 00:00:00'
        )
        active_ids = {row['id'] for row in db_module.get_active_broadcasts()}
        self.assertIn(active['id'], active_ids)
        self.assertNotIn(expired['id'], active_ids)

        self.assertTrue(db_module.deactivate_broadcast_alert(active['id']))
        self.assertIsNone(db_module.get_latest_active_broadcast())

    def test_child_gallery_includes_builtin_and_custom(self):
        child_id = self.child('Phase 12 Gallery Child')
        custom = db_module.create_custom_milestone(
            'Gallery custom', metric='chores_completed', threshold=5,
            reward_type='bonus', reward_value=3
        )
        items = db_module.get_child_achievements(child_id)
        keys = {item['key'] for item in items}
        self.assertIn('first_chore', keys)
        self.assertIn(custom['key'], keys)
        custom_item = next(item for item in items if item['key'] == custom['key'])
        self.assertEqual(custom_item['value'], 0)
        self.assertEqual(custom_item['remaining'], 5)
        self.assertFalse(custom_item['unlocked'])


class HardMilestoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        cls.parent_id = db_module.create_user(
            'Hard Milestone Parent', None, None, role='parent',
            username='hard_milestone_parent'
        )
        cls.local_tz = datetime.now().astimezone().tzinfo

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def child(self, name, date_of_birth=None):
        return db_module.create_user(
            name, None, None, role='child', date_of_birth=date_of_birth
        )

    def add_log(self, child_id, name, finished_at, description='', approved=True):
        chore_id = db_module.create_chore(
            name, 'bi-star', 1, description=description
        )
        db = db_module.get_db()
        db.execute(
            """INSERT INTO chore_logs
               (user_id, chore_id, status, finished_at, earned_amount,
                approved_by, approved_at)
               VALUES (?, ?, 'completed', ?, 1, ?, datetime('now'))""",
            (child_id, chore_id, finished_at,
             self.parent_id if approved else None)
        )
        db.commit()
        return chore_id

    def local_text(self, year, month, day, hour=12, minute=0):
        moment = datetime(
            year, month, day, hour, minute, tzinfo=self.local_tz
        )
        return moment.astimezone(timezone.utc).isoformat()

    def test_hard_milestone_helpers(self):
        self.assertEqual(achievements.easter_date(2024), date(2024, 3, 31))
        self.assertEqual(achievements.easter_date(2025), date(2025, 4, 20))
        self.assertEqual(achievements.easter_date(2026), date(2026, 4, 5))
        self.assertTrue(achievements.is_pet_cleaning_chore('Clean out pets'))
        self.assertTrue(achievements.is_pet_cleaning_chore('Clean cat litter'))
        self.assertFalse(achievements.is_pet_cleaning_chore('Walk the dog'))
        weekends = [
            date(2026, 1, 3) + timedelta(days=7 * index)
            for index in range(10)
        ]
        self.assertEqual(
            achievements.longest_consecutive_weekends(weekends), 10
        )
        self.assertEqual(achievements.time_period(23), 'night')
        self.assertTrue(achievements.is_night_hour(20))
        self.assertTrue(achievements.is_night_hour(23))
        self.assertTrue(achievements.is_night_hour(5))
        self.assertFalse(achievements.is_night_hour(12))
        self.assertFalse(achievements.is_night_hour(19))

    def test_night_and_all_day_chores_unlock(self):
        child_id = self.child('Hard Night Child')
        self.add_log(child_id, 'Night bins', self.local_text(2026, 2, 2, 23))
        self.add_log(child_id, 'Morning feed', self.local_text(2026, 2, 3, 8))
        self.add_log(child_id, 'Afternoon tidy', self.local_text(2026, 2, 3, 13))
        self.add_log(child_id, 'Evening dishes', self.local_text(2026, 2, 3, 19))
        metrics = db_module.get_achievement_metrics(child_id)
        self.assertEqual(metrics['night_chores'], 1)
        self.assertEqual(metrics['all_day_chore_days'], 1)
        db_module.evaluate_achievements(child_id)
        keys = {
            row['achievement_key'] for row in
            db_module.get_achievement_unlocks(child_id)
        }
        self.assertIn('night_owl', keys)
        self.assertIn('all_day_hero', keys)
        self.assertNotIn('night_owl_10', keys)

    def test_pet_lover_tiers_count_pet_cleaning_chores(self):
        child_id = self.child('Hard Pet Child')
        names = (
            'Clean out pets', 'Clean cat litter', 'Scrub dog kennel',
            'Clean hamster cage', 'Scoop rabbit hutch',
        )
        for index, name in enumerate(names):
            self.add_log(
                child_id, name, self.local_text(2026, 3, 1 + index, 10)
            )
        metrics = db_module.get_achievement_metrics(child_id)
        self.assertEqual(metrics['pet_cleanings'], 5)
        db_module.evaluate_achievements(child_id)
        keys = {
            row['achievement_key'] for row in
            db_module.get_achievement_unlocks(child_id)
        }
        self.assertIn('pet_lover_5', keys)
        self.assertNotIn('pet_lover_10', keys)

    def test_consecutive_weekend_tiers(self):
        child_id = self.child('Hard Weekend Child')
        for index in range(10):
            day = date(2026, 1, 3) + timedelta(days=7 * index)
            self.add_log(
                child_id, f'Weekend tidy {index}',
                self.local_text(day.year, day.month, day.day, 11)
            )
        metrics = db_module.get_achievement_metrics(child_id)
        self.assertEqual(metrics['consecutive_weekends'], 10)
        db_module.evaluate_achievements(child_id)
        keys = {
            row['achievement_key'] for row in
            db_module.get_achievement_unlocks(child_id)
        }
        self.assertIn('weekends_10', keys)
        self.assertNotIn('weekends_20', keys)

    def test_special_date_cleaner_badges(self):
        child_id = self.child('Hard Holiday Child', date_of_birth='2010-07-04')
        special_days = (
            (2026, 1, 1), (2026, 12, 25), (2026, 10, 31),
            (2026, 4, 5), (2026, 7, 4),
        )
        for index, (year, month, day) in enumerate(special_days):
            self.add_log(
                child_id, f'Special date chore {index}',
                self.local_text(year, month, day, 12)
            )
        metrics = db_module.get_achievement_metrics(child_id)
        self.assertEqual(metrics['new_year_chores'], 1)
        self.assertEqual(metrics['christmas_chores'], 1)
        self.assertEqual(metrics['halloween_chores'], 1)
        self.assertEqual(metrics['easter_chores'], 1)
        self.assertEqual(metrics['birthday_chores'], 1)
        db_module.evaluate_achievements(child_id)
        keys = {
            row['achievement_key'] for row in
            db_module.get_achievement_unlocks(child_id)
        }
        for key in (
            'holiday_new_year', 'holiday_christmas', 'holiday_halloween',
            'holiday_easter', 'birthday_cleaner',
        ):
            self.assertIn(key, keys)

    def test_gallery_exposes_new_badge_categories(self):
        child_id = self.child('Hard Gallery Child')
        items = db_module.get_child_achievements(child_id)
        by_key = {item['key']: item for item in items}
        self.assertEqual(by_key['night_owl']['category'], 'endurance')
        self.assertEqual(by_key['pet_lover_5']['category'], 'endurance')
        self.assertEqual(by_key['holiday_christmas']['category'], 'holiday')
        self.assertEqual(by_key['weekends_50']['threshold'], 50)


class AchievementRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_module.init_db()
        cls.ctx = app_module.app.app_context()
        cls.ctx.push()
        if not db_module.is_setup_complete():
            db_module.create_user(
                'Phase 12 Admin', None, 'phase12-admin-password',
                role='admin', username='phase12_admin'
            )
        cls.parent_id = db_module.create_user(
            'Phase 12 Route Parent', None, None,
            role='parent', username='phase12_route_parent'
        )
        cls.previous_csrf = app_module.app.config.get('WTF_CSRF_ENABLED', True)
        app_module.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        app_module.app.config['WTF_CSRF_ENABLED'] = cls.previous_csrf
        cls.ctx.pop()

    def setUp(self):
        db = db_module.get_db()
        db.execute("DELETE FROM custom_milestones")
        db.execute("DELETE FROM broadcast_alerts")
        db.execute("DELETE FROM achievement_unlocks")
        db.commit()

    def login_parent(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['user_id'] = self.parent_id

    def login_child(self, child_id):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['kiosk_child_id'] = child_id

    def child(self, name):
        return db_module.create_user(name, None, None, role='child')

    def approved_chore(self, child_id):
        chore_id = db_module.create_chore(
            f'Phase 12 Route Chore {child_id}', 'bi-star', 2
        )
        log_id = db_module.start_chore(child_id, chore_id)
        db_module.finish_chore(log_id)
        db_module.approve_chore(log_id, self.parent_id)

    def test_parent_achievements_page_loads(self):
        self.login_parent()
        response = self.client.get('/achievements')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Achievements', response.data)
        self.assertIn(b'Built-in Achievement Badges', response.data)

    def test_add_custom_milestone_route(self):
        self.login_parent()
        response = self.client.post(
            '/achievements/milestones/add',
            data={
                'name': 'Route milestone',
                'description': 'Created from the route test',
                'metric': 'chores_completed',
                'threshold': '3',
                'reward_type': 'xp',
                'reward_value': '15',
                'icon': 'bi-flag-fill',
                'color': '#22c55e',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Route milestone', response.data)
        milestones = db_module.get_custom_milestones()
        self.assertEqual(len(milestones), 1)
        self.assertEqual(milestones[0]['name'], 'Route milestone')
        self.assertEqual(milestones[0]['reward_type'], 'xp')

    def test_milestone_toggle_and_delete_routes(self):
        milestone = db_module.create_custom_milestone(
            'Toggle route milestone', metric='bills_paid', threshold=1
        )
        self.login_parent()
        response = self.client.post(
            f"/achievements/milestones/{milestone['id']}/toggle",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            db_module.get_custom_milestone(milestone['id'])['is_active'], 0
        )
        response = self.client.post(
            f"/achievements/milestones/{milestone['id']}/delete",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db_module.get_custom_milestone(milestone['id']))

    def test_broadcast_route_shows_banner_and_clears(self):
        child_id = self.child('Phase 12 Broadcast Child')
        self.login_parent()
        response = self.client.post(
            '/achievements/broadcast',
            data={
                'title': 'Route celebration',
                'body': 'Well done everyone!',
                'kind': 'celebration',
                'child_id': str(child_id),
                'icon': 'bi-stars',
                'color': '#f59e0b',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Route celebration', response.data)
        broadcast = db_module.get_latest_active_broadcast()
        self.assertIsNotNone(broadcast)
        self.assertEqual(broadcast['child_id'], child_id)

        response = self.client.post(
            f"/achievements/broadcast/{broadcast['id']}/delete",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(db_module.get_latest_active_broadcast())

    def test_edit_kid_shows_badge_gallery(self):
        child_id = self.child('Phase 12 Gallery Route Child')
        self.approved_chore(child_id)
        self.login_parent()
        response = self.client.get(f'/kids/{child_id}/edit')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Achievement Badge Gallery', response.data)
        self.assertIn(b'First Steps', response.data)

    def test_kiosk_rewards_shows_achievement_gallery(self):
        child_id = self.child('Phase 12 Kiosk Gallery Child')
        self.approved_chore(child_id)
        self.login_child(child_id)
        response = self.client.get('/kiosk/rewards')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Achievement Badges', response.data)
        self.assertIn(b'First Steps', response.data)

    def test_evaluate_all_route(self):
        self.login_parent()
        response = self.client.post('/achievements/evaluate', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Checked every child', response.data)


if __name__ == '__main__':
    unittest.main()
