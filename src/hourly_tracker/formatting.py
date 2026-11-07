"""Display and parse the timestamps shown in the window."""

from __future__ import annotations

import datetime as dt
import re

_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
)


def format_duration(value: dt.timedelta) -> str:
    total = int(value.total_seconds())
    if total < 0:
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes and seconds:
        return f"{minutes}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m"
    if seconds:
        return f"{seconds}s"
    return "0m"


def format_hms(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def format_clock(value: dt.datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def format_start_field(start: dt.datetime, today: dt.date) -> str:
    clock = format_clock(start)
    if start.date() == today:
        return clock
    return f"{start.strftime('%b')} {start.day}, {clock}"


def most_recent_start(candidate: dt.datetime, now: dt.datetime) -> dt.datetime:
    """Use the latest occurrence of a clock time that is not still in the future.

    After midnight, 11:57 PM is eighteen minutes ago, not later tonight.
    Putting that clock on today's date made the workday look unstarted, so
    worked time and every away total stayed at zero.
    """
    candidate = candidate.replace(second=0, microsecond=0)
    now = now.replace(microsecond=0)
    if candidate <= now:
        return candidate
    previous = candidate - dt.timedelta(days=1)
    if previous <= now:
        return previous
    return now.replace(second=0, microsecond=0)


def format_stamp(value: dt.datetime) -> str:
    clock = value.strftime("%I:%M:%S %p").lstrip("0")
    return f"{value.strftime('%b')} {value.day}, {clock}"


def format_editor(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_day(value: dt.date) -> str:
    return f"{value.strftime('%A, %B')} {value.day}"


def parse_timestamp(text: str) -> dt.datetime:
    cleaned = text.strip()
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return dt.datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    raise ValueError("Use YYYY-MM-DD HH:MM:SS")


def parse_clock(text: str, day: dt.date) -> dt.datetime:
    cleaned = _clean_clock_text(text)
    for fmt in ("%I:%M %p", "%H:%M", "%I:%M:%S %p", "%H:%M:%S"):
        try:
            parsed = dt.datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        return dt.datetime.combine(day, parsed.time())
    raise ValueError("Use a time like 8:30 AM or 08:30")


def parse_start(text: str, now: dt.datetime) -> dt.datetime:
    cleaned = text.strip()
    dated_formats = (
        "%b %d, %I:%M %p",
        "%B %d, %I:%M %p",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %H:%M",
    )
    for fmt in dated_formats:
        try:
            if "%Y" in fmt:
                parsed = dt.datetime.strptime(cleaned, fmt)
            else:
                parsed = dt.datetime.strptime(f"{now.year} {cleaned}", f"%Y {fmt}")
                if parsed > now + dt.timedelta(days=1):
                    parsed = parsed.replace(year=now.year - 1)
        except ValueError:
            continue
        return most_recent_start(parsed, now)
    return most_recent_start(parse_clock(cleaned, now.date()), now)


def _clean_clock_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip().upper().replace(".", ""))
    return re.sub(r"(?<=\d)(AM|PM)$", r" \1", cleaned)
