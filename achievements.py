"""Achievement catalog, milestone metrics and progress helpers for Phase 12."""

import re
from datetime import date, timedelta

CATEGORY_ORDER = (
    'chores', 'endurance', 'holiday', 'streak', 'savings', 'bills',
    'shopping', 'level', 'custom',
)

METRICS = {
    'chores_completed': {
        'label': 'Chores completed', 'unit': 'chores', 'icon': 'bi-check2-square',
    },
    'longest_streak': {
        'label': 'Longest streak', 'unit': 'days', 'icon': 'bi-fire',
    },
    'current_streak': {
        'label': 'Current streak', 'unit': 'days', 'icon': 'bi-fire',
    },
    'level': {
        'label': 'Level reached', 'unit': 'level', 'icon': 'bi-stars',
    },
    'total_xp': {
        'label': 'Total XP', 'unit': 'XP', 'icon': 'bi-lightning-charge-fill',
    },
    'total_earned': {
        'label': 'Total earnings', 'unit': 'currency', 'icon': 'bi-cash-coin',
    },
    'savings_balance': {
        'label': 'Savings balance', 'unit': 'currency', 'icon': 'bi-piggy-bank-fill',
    },
    'vaults_completed': {
        'label': 'Savings goals completed', 'unit': 'goals', 'icon': 'bi-bullseye',
    },
    'bills_paid': {
        'label': 'Bills paid', 'unit': 'bills', 'icon': 'bi-receipt',
    },
    'marketplace_orders': {
        'label': 'Shop orders approved', 'unit': 'orders', 'icon': 'bi-shop',
    },
    'night_chores': {
        'label': 'Chores completed at night', 'unit': 'chores', 'icon': 'bi-moon-stars-fill',
    },
    'all_day_chore_days': {
        'label': 'All-day chore days', 'unit': 'days', 'icon': 'bi-sun-fill',
    },
    'consecutive_weekends': {
        'label': 'Consecutive weekends', 'unit': 'weekends', 'icon': 'bi-calendar-week-fill',
    },
    'pet_cleanings': {
        'label': 'Pet cleanings', 'unit': 'cleanings', 'icon': 'bi-heart-fill',
    },
    'new_year_chores': {
        'label': "New Year's Day chores", 'unit': 'chores', 'icon': 'bi-calendar-heart-fill',
    },
    'christmas_chores': {
        'label': 'Christmas Day chores', 'unit': 'chores', 'icon': 'bi-gift-fill',
    },
    'halloween_chores': {
        'label': 'Halloween chores', 'unit': 'chores', 'icon': 'bi-magic',
    },
    'easter_chores': {
        'label': 'Easter chores', 'unit': 'chores', 'icon': 'bi-egg-fill',
    },
    'birthday_chores': {
        'label': 'Birthday chores', 'unit': 'chores', 'icon': 'bi-balloon-heart-fill',
    },
}

CURRENCY_METRICS = {'total_earned', 'savings_balance'}

METRIC_CHOICES = tuple(
    {'key': key, **value} for key, value in METRICS.items()
)

REWARD_TYPES = ('none', 'xp', 'bonus')

BUILTIN_ACHIEVEMENTS = (
    {
        'key': 'first_chore', 'name': 'First Steps', 'category': 'chores',
        'description': 'Complete your first approved chore.',
        'icon': 'bi-1-circle-fill', 'color': '#10b981',
        'metric': 'chores_completed', 'threshold': 1,
    },
    {
        'key': 'chores_10', 'name': 'Chore Starter', 'category': 'chores',
        'description': 'Complete 10 approved chores.',
        'icon': 'bi-check2-circle', 'color': '#22c55e',
        'metric': 'chores_completed', 'threshold': 10,
    },
    {
        'key': 'chores_50', 'name': 'Chore Machine', 'category': 'chores',
        'description': 'Complete 50 approved chores.',
        'icon': 'bi-gear-wide-connected', 'color': '#06b6d4',
        'metric': 'chores_completed', 'threshold': 50,
    },
    {
        'key': 'chores_100', 'name': 'Century Club', 'category': 'chores',
        'description': 'Complete 100 approved chores.',
        'icon': 'bi-award-fill', 'color': '#8b5cf6',
        'metric': 'chores_completed', 'threshold': 100,
    },
    {
        'key': 'night_owl', 'name': 'Night Owl', 'category': 'endurance',
        'description': 'Complete a chore at night, between 8pm and 6am.',
        'icon': 'bi-moon-stars-fill', 'color': '#6366f1',
        'metric': 'night_chores', 'threshold': 1,
    },
    {
        'key': 'night_owl_10', 'name': 'Midnight Guardian', 'category': 'endurance',
        'description': 'Complete 10 chores at night.',
        'icon': 'bi-moon-fill', 'color': '#4f46e5',
        'metric': 'night_chores', 'threshold': 10,
    },
    {
        'key': 'all_day_hero', 'name': 'All-Day Hero', 'category': 'endurance',
        'description': 'Complete chores in the morning, afternoon and evening on the same day.',
        'icon': 'bi-sun-fill', 'color': '#f59e0b',
        'metric': 'all_day_chore_days', 'threshold': 1,
    },
    {
        'key': 'weekends_10', 'name': 'Weekend Warrior', 'category': 'endurance',
        'description': 'Complete a chore on 10 weekends in a row.',
        'icon': 'bi-calendar-week-fill', 'color': '#14b8a6',
        'metric': 'consecutive_weekends', 'threshold': 10,
    },
    {
        'key': 'weekends_20', 'name': 'Weekend Veteran', 'category': 'endurance',
        'description': 'Complete a chore on 20 weekends in a row.',
        'icon': 'bi-calendar-check-fill', 'color': '#0ea5e9',
        'metric': 'consecutive_weekends', 'threshold': 20,
    },
    {
        'key': 'weekends_30', 'name': 'Weekend Champion', 'category': 'endurance',
        'description': 'Complete a chore on 30 weekends in a row.',
        'icon': 'bi-calendar2-check-fill', 'color': '#8b5cf6',
        'metric': 'consecutive_weekends', 'threshold': 30,
    },
    {
        'key': 'weekends_40', 'name': 'Weekend Legend', 'category': 'endurance',
        'description': 'Complete a chore on 40 weekends in a row.',
        'icon': 'bi-trophy-fill', 'color': '#ec4899',
        'metric': 'consecutive_weekends', 'threshold': 40,
    },
    {
        'key': 'weekends_50', 'name': 'Weekend Immortal', 'category': 'endurance',
        'description': 'Complete a chore on 50 weekends in a row.',
        'icon': 'bi-gem', 'color': '#eab308',
        'metric': 'consecutive_weekends', 'threshold': 50,
    },
    {
        'key': 'pet_lover_5', 'name': 'Pet Lover', 'category': 'endurance',
        'description': 'Clean out your pets 5 times.',
        'icon': 'bi-heart-fill', 'color': '#f43f5e',
        'metric': 'pet_cleanings', 'threshold': 5,
    },
    {
        'key': 'pet_lover_10', 'name': 'Pet Lover II', 'category': 'endurance',
        'description': 'Clean out your pets 10 times.',
        'icon': 'bi-heart-fill', 'color': '#ec4899',
        'metric': 'pet_cleanings', 'threshold': 10,
    },
    {
        'key': 'pet_lover_25', 'name': 'Pet Lover III', 'category': 'endurance',
        'description': 'Clean out your pets 25 times.',
        'icon': 'bi-heart-fill', 'color': '#d946ef',
        'metric': 'pet_cleanings', 'threshold': 25,
    },
    {
        'key': 'pet_lover_50', 'name': 'Pet Lover IV', 'category': 'endurance',
        'description': 'Clean out your pets 50 times.',
        'icon': 'bi-heart-fill', 'color': '#a855f7',
        'metric': 'pet_cleanings', 'threshold': 50,
    },
    {
        'key': 'pet_lover_100', 'name': 'Pet Lover V', 'category': 'endurance',
        'description': 'Clean out your pets 100 times.',
        'icon': 'bi-heart-fill', 'color': '#7c3aed',
        'metric': 'pet_cleanings', 'threshold': 100,
    },
    {
        'key': 'holiday_new_year', 'name': "New Year's Day Cleaner", 'category': 'holiday',
        'description': "Complete a chore on New Year's Day.",
        'icon': 'bi-calendar-heart-fill', 'color': '#f59e0b',
        'metric': 'new_year_chores', 'threshold': 1,
    },
    {
        'key': 'holiday_christmas', 'name': 'Christmas Day Cleaner', 'category': 'holiday',
        'description': 'Complete a chore on Christmas Day.',
        'icon': 'bi-gift-fill', 'color': '#ef4444',
        'metric': 'christmas_chores', 'threshold': 1,
    },
    {
        'key': 'holiday_halloween', 'name': 'Halloween Cleaner', 'category': 'holiday',
        'description': 'Complete a chore on Halloween.',
        'icon': 'bi-magic', 'color': '#f97316',
        'metric': 'halloween_chores', 'threshold': 1,
    },
    {
        'key': 'holiday_easter', 'name': 'Easter Cleaner', 'category': 'holiday',
        'description': 'Complete a chore on Easter Sunday.',
        'icon': 'bi-egg-fill', 'color': '#22c55e',
        'metric': 'easter_chores', 'threshold': 1,
    },
    {
        'key': 'birthday_cleaner', 'name': 'Birthday Cleaner', 'category': 'holiday',
        'description': 'Complete a chore on your birthday.',
        'icon': 'bi-balloon-heart-fill', 'color': '#ec4899',
        'metric': 'birthday_chores', 'threshold': 1,
    },
    {
        'key': 'streak_3', 'name': 'On a Roll', 'category': 'streak',
        'description': 'Reach a 3-day chore streak.',
        'icon': 'bi-fire', 'color': '#f59e0b',
        'metric': 'longest_streak', 'threshold': 3,
    },
    {
        'key': 'streak_7', 'name': 'Week Warrior', 'category': 'streak',
        'description': 'Reach a 7-day chore streak.',
        'icon': 'bi-fire', 'color': '#f97316',
        'metric': 'longest_streak', 'threshold': 7,
    },
    {
        'key': 'streak_30', 'name': 'Unstoppable', 'category': 'streak',
        'description': 'Reach a 30-day chore streak.',
        'icon': 'bi-fire', 'color': '#ef4444',
        'metric': 'longest_streak', 'threshold': 30,
    },
    {
        'key': 'savings_10', 'name': 'Little Saver', 'category': 'savings',
        'description': 'Build a savings balance of 10.',
        'icon': 'bi-piggy-bank-fill', 'color': '#14b8a6',
        'metric': 'savings_balance', 'threshold': 10,
    },
    {
        'key': 'savings_50', 'name': 'Super Saver', 'category': 'savings',
        'description': 'Build a savings balance of 50.',
        'icon': 'bi-piggy-bank-fill', 'color': '#0ea5e9',
        'metric': 'savings_balance', 'threshold': 50,
    },
    {
        'key': 'savings_100', 'name': 'Savings Star', 'category': 'savings',
        'description': 'Build a savings balance of 100.',
        'icon': 'bi-piggy-bank-fill', 'color': '#6366f1',
        'metric': 'savings_balance', 'threshold': 100,
    },
    {
        'key': 'vault_1', 'name': 'Goal Getter', 'category': 'savings',
        'description': 'Complete your first savings goal.',
        'icon': 'bi-bullseye', 'color': '#8b5cf6',
        'metric': 'vaults_completed', 'threshold': 1,
    },
    {
        'key': 'bills_1', 'name': 'Bill Buster', 'category': 'bills',
        'description': 'Pay your first household bill.',
        'icon': 'bi-receipt-cutoff', 'color': '#eab308',
        'metric': 'bills_paid', 'threshold': 1,
    },
    {
        'key': 'bills_10', 'name': 'Budget Boss', 'category': 'bills',
        'description': 'Pay 10 household bills.',
        'icon': 'bi-receipt', 'color': '#84cc16',
        'metric': 'bills_paid', 'threshold': 10,
    },
    {
        'key': 'shop_1', 'name': 'Smart Shopper', 'category': 'shopping',
        'description': 'Get your first shop order approved.',
        'icon': 'bi-bag-check-fill', 'color': '#ec4899',
        'metric': 'marketplace_orders', 'threshold': 1,
    },
    {
        'key': 'level_5', 'name': 'Rising Star', 'category': 'level',
        'description': 'Reach level 5.',
        'icon': 'bi-star-fill', 'color': '#f59e0b',
        'metric': 'level', 'threshold': 5,
    },
    {
        'key': 'level_10', 'name': 'Household Hero', 'category': 'level',
        'description': 'Reach level 10.',
        'icon': 'bi-trophy-fill', 'color': '#eab308',
        'metric': 'level', 'threshold': 10,
    },
    {
        'key': 'xp_500', 'name': 'XP Explorer', 'category': 'level',
        'description': 'Earn 500 XP.',
        'icon': 'bi-lightning-charge-fill', 'color': '#06b6d4',
        'metric': 'total_xp', 'threshold': 500,
    },
)


CLEANING_PATTERNS = (
    r'\bclean(?:ing|ed|out)?\b', r'\bscoop(?:ing|ed)?\b',
    r'\bscrub(?:bing|bed)?\b', r'\bwash(?:ing|ed)?\b',
    r'\bchange(?:d|ing)?\b', r'\brefresh(?:ing|ed)?\b',
)
PET_PATTERNS = (
    r'\bpets?\b', r'\bcats?\b', r'\bdogs?\b', r'\blitter\b',
    r'\bhamsters?\b', r'\brabbits?\b', r'\bguinea pigs?\b',
    r'\bfish tanks?\b', r'\baquariums?\b', r'\bbird cages?\b',
    r'\bparrots?\b', r'\bhutch(?:es)?\b', r'\bcoops?\b',
    r'\bstables?\b', r'\bkennels?\b', r'\bcages?\b', r'\btanks?\b',
    r'\bchickens?\b', r'\bpigs?\b', r'\bhorses?\b', r'\bgoats?\b',
    r'\bferrets?\b', r'\bgerbils?\b', r'\brats?\b', r'\bmice\b',
    r'\bsnakes?\b', r'\blizards?\b', r'\bturtles?\b',
)


def is_pet_cleaning_chore(name, description=''):
    """Return True when a chore name looks like cleaning out an animal."""
    text = f"{name or ''} {description or ''}".lower()
    has_cleaning = any(re.search(pattern, text) for pattern in CLEANING_PATTERNS)
    has_pet = any(re.search(pattern, text) for pattern in PET_PATTERNS)
    return has_cleaning and has_pet


def easter_date(year):
    """Return Gregorian Easter Sunday for a year using the Anonymous algorithm."""
    year = int(year)
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def weekend_week_start(value):
    """Return the Monday for a Saturday/Sunday, else None."""
    if value.weekday() < 5:
        return None
    return value - timedelta(days=value.weekday())


def longest_consecutive_weekends(days):
    starts = sorted({
        start for start in (weekend_week_start(day) for day in days)
        if start is not None
    })
    best = current = 0
    previous = None
    for start in starts:
        if previous is not None and (start - previous).days == 7:
            current += 1
        else:
            current = 1
        best = max(best, current)
        previous = start
    return best


def time_period(hour):
    if 5 <= hour < 12:
        return 'morning'
    if 12 <= hour < 17:
        return 'afternoon'
    if 17 <= hour < 20:
        return 'evening'
    return 'night'


def is_night_hour(hour):
    return hour >= 20 or hour < 6


def metric_label(metric):
    return METRICS.get(metric, {}).get('label', str(metric or '').replace('_', ' ').title())


def metric_unit(metric):
    return METRICS.get(metric, {}).get('unit', '')


def metric_icon(metric):
    return METRICS.get(metric, {}).get('icon', 'bi-award-fill')


def normalize_metric(value):
    metric = (value or '').strip()
    if metric not in METRICS:
        raise ValueError('Choose a valid achievement metric.')
    return metric


def normalize_reward_type(value):
    reward_type = (value or 'none').strip().lower()
    if reward_type not in REWARD_TYPES:
        raise ValueError('Choose a valid reward type.')
    return reward_type


def normalize_threshold(value):
    try:
        threshold = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Milestone target must be a number.') from exc
    if threshold <= 0:
        raise ValueError('Milestone target must be greater than zero.')
    return round(threshold, 2)


def normalize_reward_value(value, reward_type):
    if reward_type == 'none':
        return 0.0
    try:
        reward = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Reward value must be a number.') from exc
    if reward <= 0:
        raise ValueError('Reward value must be greater than zero.')
    return round(reward, 2)


def clean_icon(value, default='bi-award-fill'):
    icon = (value or '').strip()
    return icon if icon.startswith('bi-') and len(icon) <= 60 else default


def clean_color(value, default='#10b981'):
    color = (value or '').strip()
    return color if re.fullmatch(r'#[0-9a-fA-F]{6}', color) else default


def format_value(metric, value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    if metric in CURRENCY_METRICS:
        return f'{number:,.2f}'
    if number.is_integer():
        return f'{int(number):,}'
    return f'{number:,.1f}'


def requirement_text(metric, threshold):
    return f'{metric_label(metric)}: {format_value(metric, threshold)}'


def reward_label(reward_type, reward_value):
    if reward_type == 'xp':
        return f'+{format_value("total_xp", reward_value)} XP'
    if reward_type == 'bonus':
        return f'{format_value("total_earned", reward_value)} bonus'
    return 'Badge only'


def progress_percent(value, threshold):
    try:
        target = float(threshold or 0)
        current = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if target <= 0:
        return 100.0
    return round(max(0.0, min(100.0, current / target * 100)), 1)


def remaining(value, threshold):
    try:
        target = float(threshold or 0)
        current = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, target - current), 2)


def _enrich(definition, is_custom=False):
    entry = dict(definition)
    metric = entry.get('metric')
    threshold = float(entry.get('threshold') or 0)
    reward_type = entry.get('reward_type', 'none')
    reward_value = float(entry.get('reward_value') or 0)
    entry.update({
        'category': entry.get('category', 'custom' if is_custom else 'chores'),
        'is_custom': bool(is_custom),
        'is_active': int(entry.get('is_active', 1) or 0),
        'threshold': threshold,
        'reward_type': reward_type,
        'reward_value': reward_value,
        'metric_label': metric_label(metric),
        'metric_unit': metric_unit(metric),
        'metric_icon': metric_icon(metric),
        'requirement': requirement_text(metric, threshold),
        'target_text': format_value(metric, threshold),
        'reward_label': reward_label(reward_type, reward_value),
    })
    return entry


def builtin_definitions():
    return [
        _enrich({**item, 'reward_type': 'none', 'reward_value': 0})
        for item in BUILTIN_ACHIEVEMENTS
    ]


def custom_definition(row):
    data = dict(row)
    definition = {
        'key': f"custom:{data['id']}",
        'id': data['id'],
        'name': data.get('name', ''),
        'description': data.get('description', ''),
        'icon': data.get('icon', 'bi-award-fill'),
        'color': data.get('color', '#10b981'),
        'category': 'custom',
        'metric': data.get('metric', ''),
        'threshold': data.get('threshold', 0),
        'reward_type': data.get('reward_type', 'none'),
        'reward_value': data.get('reward_value', 0),
        'is_active': data.get('is_active', 1),
        'created_by': data.get('created_by'),
        'created_at': data.get('created_at'),
        'updated_at': data.get('updated_at'),
    }
    return _enrich(definition, is_custom=True)


def evaluate(metrics, unlocked_keys, definitions):
    """Return definitions that are newly met, ignoring already-unlocked keys."""
    unlocked = set(unlocked_keys or ())
    ready = []
    for definition in definitions:
        if definition['key'] in unlocked:
            continue
        value = float(metrics.get(definition['metric'], 0) or 0)
        if value + 1e-9 >= float(definition['threshold'] or 0):
            ready.append(definition)
    return ready


def category_sort_key(category):
    try:
        return CATEGORY_ORDER.index(category)
    except ValueError:
        return len(CATEGORY_ORDER)
