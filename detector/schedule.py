"""Time-of-day scheduling for room checks.

Decides, for the current local time, whether checks are paused (quiet hours) and
how often each room should be checked (a peak interval during configured windows,
a slower default otherwise). All times are interpreted in the configured timezone
(default America/Chicago, which tracks Central daylight/standard time automatically).
"""

from __future__ import annotations

import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None


def _to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _parse_window(s):
    """'07:00-10:00' -> (420, 600) minutes-of-day."""
    a, b = s.split("-")
    return (_to_min(a.strip()), _to_min(b.strip()))


def _in_windows(now_min, windows):
    for start, end in windows:
        if start <= end:
            if start <= now_min < end:
                return True
        else:  # window wraps past midnight, e.g. 22:00-02:00
            if now_min >= start or now_min < end:
                return True
    return False


def _fmt_ampm(total_min):
    h, m = divmod(total_min % 1440, 60)
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


class Scheduler:
    def __init__(self, cfg_schedule):
        cfg_schedule = cfg_schedule or {}
        tzname = cfg_schedule.get("timezone", "America/Chicago")
        self.tz = ZoneInfo(tzname) if ZoneInfo else None
        self.quiet = [_parse_window(w) for w in cfg_schedule.get("quiet_hours", [])]

    def now(self):
        return datetime.datetime.now(self.tz)

    def is_quiet(self, now=None):
        now = now or self.now()
        return _in_windows(now.hour * 60 + now.minute, self.quiet)

    def quiet_resume_str(self, now=None):
        """Human time the current quiet window ends (e.g. '6:00 AM'), or None."""
        now = now or self.now()
        nm = now.hour * 60 + now.minute
        for start, end in self.quiet:
            active = (start <= nm < end) if start <= end else (nm >= start or nm < end)
            if active:
                return _fmt_ampm(end)
        return None

    def room_interval(self, room_schedule, now=None):
        """Seconds between checks for this room at the current local time."""
        room_schedule = room_schedule or {}
        now = now or self.now()
        nm = now.hour * 60 + now.minute
        is_weekend = now.weekday() >= 5  # Mon=0 .. Sat=5, Sun=6
        key = "weekend_windows" if is_weekend else "weekday_windows"
        windows = [_parse_window(w) for w in room_schedule.get(key, [])]
        default = room_schedule.get("default_interval_seconds", 900)
        if windows and _in_windows(nm, windows):
            return room_schedule.get("peak_interval_seconds", default)
        return default
