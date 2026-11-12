"""Application-wide timezone helpers.

Database timestamps are stored as naive UTC for compatibility with the
existing SQLAlchemy DateTime columns. Convert them to Kigali time for display.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KIGALI_TIMEZONE = ZoneInfo("Africa/Kigali")
UTC_TIMEZONE = timezone.utc


def utc_now_naive() -> datetime:
    """Return the current UTC time without tzinfo for database storage."""
    return datetime.now(UTC_TIMEZONE).replace(tzinfo=None)


def kigali_now() -> datetime:
    """Return the current timezone-aware Kigali datetime."""
    return datetime.now(KIGALI_TIMEZONE)


def to_kigali(value: datetime | None) -> datetime | None:
    """Interpret naive database datetimes as UTC and convert to Kigali."""
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC_TIMEZONE)

    return value.astimezone(KIGALI_TIMEZONE)


def format_kigali(
    value: datetime | None,
    fmt: str = "%Y-%m-%d %H:%M",
) -> str:
    """Format a stored timestamp using Kigali local time."""
    converted = to_kigali(value)
    return converted.strftime(fmt) if converted else ""
