"""Timezone utility tests."""

from datetime import datetime, timedelta, timezone

from app.utils.timezone import (
    KIGALI_TIMEZONE,
    format_kigali,
    kigali_now,
    to_kigali,
    utc_now_naive,
)


def test_kigali_timezone_is_utc_plus_two():
    assert datetime.now(KIGALI_TIMEZONE).utcoffset() == timedelta(hours=2)


def test_kigali_now_is_timezone_aware():
    value = kigali_now()
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(hours=2)


def test_utc_now_naive_returns_naive_utc_datetime():
    value = utc_now_naive()
    assert value.tzinfo is None


def test_to_kigali_converts_naive_utc_datetime():
    value = datetime(2026, 11, 9, 16, 0, 0)
    converted = to_kigali(value)

    assert converted == datetime(
        2026, 11, 9, 18, 0, 0, tzinfo=KIGALI_TIMEZONE
    )


def test_to_kigali_converts_aware_utc_datetime():
    value = datetime(2026, 11, 9, 16, 0, 0, tzinfo=timezone.utc)
    converted = to_kigali(value)

    assert converted == datetime(
        2026, 11, 9, 18, 0, 0, tzinfo=KIGALI_TIMEZONE
    )


def test_format_kigali_formats_naive_utc_timestamp():
    value = datetime(2026, 11, 9, 16, 0, 0)

    assert format_kigali(value) == "2026-11-09 18:00"


def test_format_kigali_handles_none():
    assert format_kigali(None) == ""
