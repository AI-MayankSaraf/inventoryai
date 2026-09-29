"""
The business calendar.

"Today" for a rule like "a movement cannot be dated in the future" is the
day in India, not on the server: a server running in UTC would otherwise
reject a receipt entered at 00:30 IST as dated tomorrow, and one dated from
a date-only field would land at UTC midnight, still hours in the future.

India keeps one time zone with no daylight saving, so a fixed +05:30 offset
is exact and needs no tz database (which Windows Python lacks by default).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def today() -> date:
    """The current date in India."""
    return datetime.now(IST).date()


def as_business_time(value: datetime) -> datetime:
    """A naive datetime (e.g. from a date-only field) is Indian time."""
    return value.replace(tzinfo=IST) if value.tzinfo is None else value


def is_future_day(value: date | datetime) -> bool:
    """True when `value` falls on a day after today in India. A later time
    on today's date is not "the future" for dating a document."""
    day = as_business_time(value).astimezone(IST).date() if isinstance(value, datetime) else value
    return day > today()
