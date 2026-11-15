"""Deterministic date/time parsing and speech-friendly formatting.

Relative phrases ("tomorrow", "friday") are resolved here, on the server, in the
user's timezone, so the voice model never has to do date arithmetic.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_DATE_FORMATS = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y"]
_DATE_FORMATS_NO_YEAR = ["%d %B", "%B %d", "%d %b", "%b %d"]


class TimeParseError(ValueError):
    pass


def get_zone(name: str | None, default: str = "Asia/Kolkata") -> ZoneInfo:
    try:
        return ZoneInfo(name or default)
    except (ZoneInfoNotFoundError, ValueError):
        raise TimeParseError(f"Unknown timezone '{name}'. Use an IANA name such as Asia/Kolkata.")


def local_today(tz: ZoneInfo, now_utc: datetime) -> date:
    return now_utc.replace(tzinfo=timezone.utc).astimezone(tz).date()


def parse_date(text: str, tz: ZoneInfo, now_utc: datetime) -> date:
    raw = str(text or "").strip().lower()
    raw = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", raw).replace(",", " ")
    raw = re.sub(r"\s+", " ", raw)
    if not raw:
        raise TimeParseError("A date is required, for example 'tomorrow' or 2026-11-16.")
    today = local_today(tz, now_utc)
    simple = {"today": 0, "aaj": 0, "tonight": 0, "tomorrow": 1, "day after tomorrow": 2, "parso": 2}
    if raw in simple:
        return today + timedelta(days=simple[raw])
    if raw == "yesterday":
        return today - timedelta(days=1)
    m = re.fullmatch(r"(next |this |coming )?(" + "|".join(WEEKDAYS) + ")", raw)
    if m:
        delta = (WEEKDAYS.index(m.group(2)) - today.weekday()) % 7
        if delta == 0 and m.group(1) != "this ":
            delta = 7
        return today + timedelta(days=delta)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    for fmt in _DATE_FORMATS_NO_YEAR:
        try:
            # Parse with an explicit leap-safe year, then move to the upcoming occurrence.
            parsed = datetime.strptime(f"{raw} 2024", fmt + " %Y").date()
        except ValueError:
            continue
        try:
            candidate = parsed.replace(year=today.year)
            if candidate < today:
                candidate = parsed.replace(year=today.year + 1)
        except ValueError:
            raise TimeParseError(f"'{text}' is not a valid date this year.")
        return candidate
    raise TimeParseError(
        f"I could not understand the date '{text}'. Use 'today', 'tomorrow', a weekday, or YYYY-MM-DD."
    )


def parse_time(text: str) -> time:
    raw = str(text or "").strip().lower().replace(".", "")
    raw = re.sub(r"\s+", " ", raw)
    if not raw:
        raise TimeParseError("A time is required, for example 16:00 or 4 PM.")
    if raw in ("noon", "midday", "12 noon"):
        return time(12, 0)
    if raw == "midnight":
        return time(0, 0)
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(?::\d{2})? ?(am|pm)?", raw)
    if not m:
        raise TimeParseError(f"I could not understand the time '{text}'. Use 24-hour HH:MM, like 16:00.")
    hour, minute, suffix = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if minute > 59:
        raise TimeParseError(f"'{text}' is not a valid time.")
    if suffix:
        if not 1 <= hour <= 12:
            raise TimeParseError(f"'{text}' is not a valid time.")
        hour = hour % 12 + (12 if suffix == "pm" else 0)
    elif m.group(2) is None and 1 <= hour <= 12:
        raise TimeParseError(f"Is that {hour} AM or {hour} PM? Send the time as 24-hour HH:MM.")
    if hour > 23:
        raise TimeParseError(f"'{text}' is not a valid time.")
    return time(hour, minute)


def to_utc(d: date, t: time, tz: ZoneInfo) -> datetime:
    """Local wall-clock date+time -> naive UTC datetime."""
    return datetime.combine(d, t, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)


def to_local(dt_utc: datetime, tz: ZoneInfo) -> datetime:
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(tz)


def fmt_time(dt_local: datetime | time) -> str:
    hour = dt_local.hour % 12 or 12
    suffix = "AM" if dt_local.hour < 12 else "PM"
    return f"{hour}:{dt_local.minute:02d} {suffix}"


def fmt_date(d: date, today: date | None = None) -> str:
    label = f"{d.strftime('%A')}, {d.day} {d.strftime('%B')}"
    if today is not None:
        if d == today:
            return f"today, {label}"
        if d == today + timedelta(days=1):
            return f"tomorrow, {label}"
        if d == today - timedelta(days=1):
            return f"yesterday, {label}"
    if today is not None and d.year != today.year:
        label += f" {d.year}"
    return label


def iso_utc(dt_utc: datetime | None) -> str | None:
    return dt_utc.replace(microsecond=0).isoformat() + "Z" if dt_utc else None
