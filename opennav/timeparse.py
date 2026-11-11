"""Parse human departure specs into timezone-aware datetimes.

Accepted forms:
  "now"
  "2026-11-18T08:00"  or  "2026-11-18 08:00"   (local to `tz` unless an offset is given)
  "wed 08:00", "wednesday 8am", "fri 5:30pm"   (next occurrence, strictly in the future)
  "08:00", "5pm"                                (today if still ahead, else tomorrow)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", re.I)


def _parse_clock(text: str) -> tuple[int, int]:
    m = _TIME_RE.match(text.strip())
    if not m:
        raise ValueError(f"Unrecognized time of day: {text!r}")
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"Time out of range: {text!r}")
    return hour, minute


def parse_departure(spec: str | None, tz: str = "America/New_York", now: datetime | None = None) -> datetime | None:
    if spec is None or spec.strip().lower() == "now":
        return None
    zone = ZoneInfo(tz)
    now = (now or datetime.now(zone)).astimezone(zone)
    spec = spec.strip()

    try:
        dt = datetime.fromisoformat(spec)
        return dt if dt.tzinfo else dt.replace(tzinfo=zone)
    except ValueError:
        pass

    parts = spec.split(None, 1)
    day_idx = None
    if parts and parts[0][:3].lower() in DAYS and parts[0].isalpha():
        day_idx = DAYS.index(parts[0][:3].lower())
        clock = parts[1] if len(parts) > 1 else "00:00"
    else:
        clock = spec
    hour, minute = _parse_clock(clock)

    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day_idx is None:
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    ahead = (day_idx - now.weekday()) % 7
    candidate += timedelta(days=ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate
