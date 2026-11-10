"""Stores times in UTC and shows them in the local time zone."""
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc)


def to_utc_text(value):
    return value.astimezone(timezone.utc).isoformat()


def parse_utc(text):
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def format_local(text, fmt='%d %b %Y, %H:%M'):
    if not text:
        return ''
    try:
        return parse_utc(text).astimezone().strftime(fmt)
    except ValueError:
        return text


def local_date(value=None):
    if value is None:
        moment = utc_now()
    elif isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, str):
        moment = parse_utc(value)
    else:
        return value
    return moment.astimezone().date()


def local_date_text(value=None):
    return local_date(value).isoformat()
