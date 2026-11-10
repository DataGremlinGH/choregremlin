"""Recurring household bill scheduling and late-fee calculations for Phase 11."""

from calendar import monthrange
from datetime import date, datetime, timedelta

FREQUENCIES = ('weekly', 'monthly', 'one_off')
CATEGORIES = ('rent', 'utilities', 'subscription', 'other')
LATE_FEE_TYPES = ('none', 'flat', 'percent')


def parse_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError('Due date must be a valid date.') from exc


def normalize_frequency(value):
    frequency = (value or '').strip().lower()
    if frequency not in FREQUENCIES:
        raise ValueError('Frequency must be weekly, monthly or one-off.')
    return frequency


def normalize_category(value):
    category = (value or '').strip().lower()
    if category not in CATEGORIES:
        raise ValueError('Bill category must be rent, utilities, subscription or other.')
    return category


def normalize_late_fee_type(value):
    fee_type = (value or 'none').strip().lower()
    if fee_type not in LATE_FEE_TYPES:
        raise ValueError('Late fee type must be none, flat or percent.')
    return fee_type


def advance_due_date(due_date, frequency):
    due = parse_date(due_date)
    frequency = normalize_frequency(frequency)
    if frequency == 'weekly':
        return (due + timedelta(days=7)).isoformat()
    if frequency == 'monthly':
        year = due.year
        month = due.month + 1
        if month > 12:
            month = 1
            year += 1
        day = min(due.day, monthrange(year, month)[1])
        return date(year, month, day).isoformat()
    return None


def late_fee_amount(amount, fee_type, fee_value):
    amount = max(0.0, round(float(amount or 0), 2))
    value = max(0.0, float(fee_value or 0))
    fee_type = normalize_late_fee_type(fee_type)
    if fee_type == 'flat':
        return round(value, 2)
    if fee_type == 'percent':
        return round(amount * value / 100, 2)
    return 0.0


def total_due(amount, amount_paid=0, late_fee=0):
    return max(0.0, round(
        float(amount or 0) + float(late_fee or 0) - float(amount_paid or 0), 2
    ))


def is_overdue(due_date, status='due', today=None):
    if status in ('paid', 'waived'):
        return False
    today = parse_date(today) if today is not None else date.today()
    return parse_date(due_date) < today


def days_overdue(due_date, status='due', today=None):
    if not is_overdue(due_date, status=status, today=today):
        return 0
    today = parse_date(today) if today is not None else date.today()
    return (today - parse_date(due_date)).days
