"""Experience points, streak multipliers and unlockable rewards for Phase 7."""

from datetime import date, datetime

XP_PER_CURRENCY_UNIT = 10
MIN_XP_PER_COMPLETION = 1
XP_PER_LEVEL = 100

STREAK_TIERS = (
    (1, 1.0),
    (3, 1.1),
    (5, 1.25),
    (7, 1.5),
    (14, 1.75),
    (30, 2.0),
)

AVATAR_CATALOG = (
    {'key': 'default', 'name': 'Gremlin', 'icon': 'bi-person-fill',
     'unlock_type': 'level', 'unlock_value': 1,
     'description': 'The classic Chore Gremlin look.'},
    {'key': 'explorer', 'name': 'Explorer', 'icon': 'bi-compass-fill',
     'unlock_type': 'level', 'unlock_value': 2,
     'description': 'For kids who are always finding the next job.'},
    {'key': 'rocket', 'name': 'Rocket', 'icon': 'bi-rocket-takeoff-fill',
     'unlock_type': 'level', 'unlock_value': 3,
     'description': 'Fast, focused and ready for lift-off.'},
    {'key': 'robot', 'name': 'Robot', 'icon': 'bi-robot',
     'unlock_type': 'level', 'unlock_value': 5,
     'description': 'A chore machine that never misses a beat.'},
    {'key': 'dragon', 'name': 'Dragon', 'icon': 'bi-fire',
     'unlock_type': 'streak', 'unlock_value': 7,
     'description': 'Seven days in a row keeps the fire burning.'},
    {'key': 'champion', 'name': 'Champion', 'icon': 'bi-trophy-fill',
     'unlock_type': 'streak', 'unlock_value': 30,
     'description': 'A full month of daily chores. Legendary.'},
)

BADGE_CATALOG = (
    {'key': 'helper', 'name': 'Helping Hand', 'icon': 'bi-hand-thumbs-up-fill',
     'unlock_type': 'level', 'unlock_value': 1,
     'description': 'Every chore hero starts somewhere.'},
    {'key': 'spark', 'name': 'Spark Starter', 'icon': 'bi-lightning-charge-fill',
     'unlock_type': 'level', 'unlock_value': 2,
     'description': 'You bring the energy.'},
    {'key': 'hero', 'name': 'Chore Hero', 'icon': 'bi-shield-fill-check',
     'unlock_type': 'level', 'unlock_value': 5,
     'description': 'The family can count on you.'},
    {'key': 'legend', 'name': 'Gremlin Legend', 'icon': 'bi-gem',
     'unlock_type': 'level', 'unlock_value': 10,
     'description': 'A true legend of the household.'},
    {'key': 'iron', 'name': 'Iron Will', 'icon': 'bi-calendar-check-fill',
     'unlock_type': 'streak', 'unlock_value': 30,
     'description': 'Thirty days of showing up.'},
)

CATALOGS = {
    'avatar': AVATAR_CATALOG,
    'badge': BADGE_CATALOG,
}


def base_xp_for_reward(reward_amount):
    try:
        amount = float(reward_amount or 0)
    except (TypeError, ValueError):
        amount = 0
    return max(MIN_XP_PER_COMPLETION, int(round(amount * XP_PER_CURRENCY_UNIT)))


def streak_multiplier(streak_days):
    streak = max(1, int(streak_days or 1))
    multiplier = 1.0
    for threshold, value in STREAK_TIERS:
        if streak >= threshold:
            multiplier = value
    return multiplier


def calculate_xp(reward_amount, streak_days):
    base_xp = base_xp_for_reward(reward_amount)
    multiplier = streak_multiplier(streak_days)
    awarded = max(MIN_XP_PER_COMPLETION, int(base_xp * multiplier + 0.5))
    return {
        'base_xp': base_xp,
        'streak_days': max(1, int(streak_days or 1)),
        'multiplier': multiplier,
        'xp_awarded': awarded,
    }


def level_for_xp(total_xp):
    return max(1, int(total_xp or 0) // XP_PER_LEVEL + 1)


def xp_for_level(level):
    return max(0, (max(1, int(level or 1)) - 1) * XP_PER_LEVEL)


def level_progress(total_xp):
    total = max(0, int(total_xp or 0))
    level = level_for_xp(total)
    into_level = total - xp_for_level(level)
    return {
        'level': level,
        'xp_into_level': into_level,
        'xp_for_next_level': XP_PER_LEVEL,
        'progress_percent': round(into_level / XP_PER_LEVEL * 100, 1),
    }


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value[:10]).date()
        except ValueError:
            return None
    return None


def next_completion_streak(last_completed_date, current_streak, completion_date):
    current = max(0, int(current_streak or 0))
    previous = _as_date(last_completed_date)
    today = _as_date(completion_date)
    if today is None:
        return max(1, current)
    if previous is None:
        return 1
    if today == previous:
        return max(1, current)
    if (today - previous).days == 1:
        return max(1, current + 1)
    return 1


def get_item(item_type, item_key):
    for item in CATALOGS.get(item_type, ()):
        if item['key'] == item_key:
            return item
    return None


def item_unlocked(item, level=1, total_xp=0, longest_streak=0, current_streak=0):
    if not item:
        return False
    unlock_type = item.get('unlock_type')
    threshold = int(item.get('unlock_value', 1))
    if unlock_type == 'level':
        return int(level or 1) >= threshold
    if unlock_type == 'xp':
        return int(total_xp or 0) >= threshold
    if unlock_type == 'streak':
        return max(int(longest_streak or 0), int(current_streak or 0)) >= threshold
    return False


def requirement_text(item):
    if not item:
        return ''
    unlock_type = item.get('unlock_type')
    value = item.get('unlock_value', 1)
    if unlock_type == 'level':
        return f'Reach level {value}'
    if unlock_type == 'xp':
        return f'Earn {value} XP'
    if unlock_type == 'streak':
        return f'Reach a {value}-day streak'
    return 'Locked'


def catalog_with_status(item_type, level=1, total_xp=0, longest_streak=0, current_streak=0):
    items = []
    for item in CATALOGS.get(item_type, ()):
        entry = dict(item)
        entry['unlocked'] = item_unlocked(
            item, level=level, total_xp=total_xp,
            longest_streak=longest_streak, current_streak=current_streak
        )
        entry['requirement'] = requirement_text(item)
        items.append(entry)
    return items
