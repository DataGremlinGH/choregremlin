"""Savings interest and loan contract calculations for Phase 8."""

from datetime import date, datetime, timedelta, timezone

PERIODS_PER_YEAR = {
    'daily': 365,
    'weekly': 52,
}

INTERVAL_DAYS = {
    'daily': 1,
    'weekly': 7,
}


def periods_per_year(frequency):
    try:
        return PERIODS_PER_YEAR[frequency]
    except KeyError as exc:
        raise ValueError('Compounding must be daily or weekly.') from exc


def interval_days(frequency):
    try:
        return INTERVAL_DAYS[frequency]
    except KeyError as exc:
        raise ValueError('Compounding must be daily or weekly.') from exc


def elapsed_periods(last_at, now, frequency):
    if last_at is None or now is None:
        return 0
    seconds = (now - last_at).total_seconds()
    interval = interval_days(frequency) * 86400
    return max(0, int(seconds // interval))


def compound_balance(balance, annual_rate, periods, frequency):
    opening = max(0.0, round(float(balance or 0), 2))
    rate = max(0.0, float(annual_rate or 0)) / 100
    periods = max(0, int(periods or 0))
    if opening == 0 or rate == 0 or periods == 0:
        return opening
    per_period = rate / periods_per_year(frequency)
    return round(opening * ((1 + per_period) ** periods), 2)


def interest_amount(balance, annual_rate, periods, frequency):
    opening = max(0.0, round(float(balance or 0), 2))
    return round(compound_balance(opening, annual_rate, periods, frequency) - opening, 2)


def next_interest_at(last_at, periods, frequency):
    return last_at + timedelta(days=interval_days(frequency) * max(0, int(periods or 0)))


def loan_terms(principal, annual_rate, term_weeks):
    principal = max(0.0, round(float(principal or 0), 2))
    annual_rate = max(0.0, float(annual_rate or 0))
    term_weeks = max(1, int(term_weeks or 1))
    interest = round(principal * (annual_rate / 100) * (term_weeks / 52), 2)
    total_repayable = round(principal + interest, 2)
    installment_amount = round(total_repayable / term_weeks, 2)
    return {
        'principal': principal,
        'annual_interest_rate': annual_rate,
        'term_weeks': term_weeks,
        'interest_amount': interest,
        'total_repayable': total_repayable,
        'installment_amount': installment_amount,
    }


def add_weeks(value, weeks):
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value + timedelta(weeks=weeks)).date().isoformat()
    if isinstance(value, date):
        return (value + timedelta(weeks=weeks)).isoformat()
    if isinstance(value, str):
        try:
            return (datetime.fromisoformat(value[:10]).date() + timedelta(weeks=weeks)).isoformat()
        except ValueError:
            return value
    return value


def vault_progress(balance, target_amount, target_date=None, lock_until_date=False,
                   lock_until_target=False, status='active', today=None):
    """Return visual progress and lock state for a savings goal."""
    balance = max(0.0, round(float(balance or 0), 2))
    target = max(0.0, round(float(target_amount or 0), 2))
    percent = min(100.0, round((balance / target) * 100, 1)) if target > 0 else 0.0
    remaining = max(0.0, round(target - balance, 2))
    target_reached = target > 0 and balance + 0.005 >= target

    if today is None:
        today = date.today()
    elif isinstance(today, datetime):
        today = today.date()
    elif isinstance(today, str):
        today = date.fromisoformat(today[:10])

    target_date_value = None
    days_left = None
    date_reached = False
    if target_date:
        try:
            target_date_value = date.fromisoformat(str(target_date)[:10])
        except ValueError:
            target_date_value = None
        if target_date_value:
            days_left = (target_date_value - today).days
            date_reached = target_date_value <= today

    closed = status == 'closed'
    lock_conditions = []
    if lock_until_date:
        lock_conditions.append(date_reached)
    if lock_until_target:
        lock_conditions.append(target_reached)

    if closed:
        unlocked = False
        lock_reason = 'Goal closed.'
    elif not lock_conditions:
        unlocked = True
        lock_reason = ''
    else:
        unlocked = any(lock_conditions)
        if unlocked:
            lock_reason = ''
        elif lock_until_date and lock_until_target:
            lock_reason = f'Locked until {target_date or "the target date"} or {target:.2f} saved.'
        elif lock_until_date:
            lock_reason = f'Locked until {target_date or "the target date"}.'
        else:
            lock_reason = f'Locked until {target:.2f} is saved.'

    return {
        'balance': balance,
        'target': target,
        'percent': percent,
        'remaining': remaining,
        'target_reached': target_reached,
        'date_reached': date_reached,
        'days_left': days_left,
        'unlocked': unlocked,
        'locked': bool(lock_conditions) and not unlocked and not closed,
        'lock_reason': lock_reason,
        'closed': closed,
    }


def match_amount(contribution, match_percent, weekly_cap, matched_this_week=0):
    """Calculate the parent match for a contribution, respecting the weekly cap."""
    contribution = max(0.0, round(float(contribution or 0), 2))
    percent = max(0.0, min(100.0, float(match_percent or 0)))
    cap = max(0.0, round(float(weekly_cap or 0), 2))
    matched = max(0.0, round(float(matched_this_week or 0), 2))
    remaining = max(0.0, round(cap - matched, 2))
    return round(min(contribution * percent / 100, remaining), 2)


def week_start(now=None):
    """Return the UTC Monday 00:00 that starts the current match week."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif isinstance(now, str):
        now = datetime.fromisoformat(now)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    start = now - timedelta(days=now.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0)
