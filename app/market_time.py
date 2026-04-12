# app/market_time.py
#
# Market calendar and session-type awareness for THE ABODE.
#
# Knows NYSE regular session hours, pre-market, after-hours, and
# a configurable list of early-close dates (half-days). Does NOT
# require a network call — all rules are local and deterministic.
#
# Public API:
#   session_type()    → Literal["pre_market","regular","after_hours","closed"]
#   is_regular_hours()  → bool
#   is_extended_hours() → bool
#   is_market_open()    → bool   (True during regular hours)
#   next_open()         → datetime | None
#   EARLY_CLOSE_DATES   — frozenset of "YYYY-MM-DD" strings

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Literal
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

# NYSE regular session
_OPEN  = time(9, 30)
_CLOSE = time(16, 0)

# Extended-hours boundaries
_PRE_OPEN    = time(4, 0)
_AFTER_CLOSE = time(20, 0)

# Weekdays: Monday=0 … Friday=4
_TRADING_WEEKDAYS = frozenset({0, 1, 2, 3, 4})

# Known NYSE full-close holidays (Eastern date) for 2025–2026.
# Extend this list as needed. All dates are "YYYY-MM-DD".
NYSE_FULL_CLOSE: frozenset[str] = frozenset({
    # 2025
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17",
    "2025-04-18", "2025-05-26", "2025-06-19", "2025-07-04",
    "2025-09-01", "2025-11-27", "2025-12-25",
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16",
    "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
})

# Known NYSE early closes (1:00 PM ET) for 2025–2026.
EARLY_CLOSE_DATES: frozenset[str] = frozenset({
    "2025-07-03",   # day before Independence Day
    "2025-11-28",   # day after Thanksgiving
    "2025-12-24",   # Christmas Eve
    "2026-11-27",   # day after Thanksgiving
    "2026-12-24",   # Christmas Eve
})

_EARLY_CLOSE_TIME = time(13, 0)  # 1:00 PM ET


def _now_et() -> datetime:
    return datetime.now(tz=_ET)


def _date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _is_trading_day(dt: datetime) -> bool:
    """Return True if dt (in ET) is a weekday and not a full-close holiday."""
    if dt.weekday() not in _TRADING_WEEKDAYS:
        return False
    return _date_str(dt) not in NYSE_FULL_CLOSE


def _close_time(dt: datetime) -> time:
    """Return effective close time for dt — 1 PM on early-close days, 4 PM otherwise."""
    if _date_str(dt) in EARLY_CLOSE_DATES:
        return _EARLY_CLOSE_TIME
    return _CLOSE


SessionType = Literal["pre_market", "regular", "after_hours", "closed"]


def session_type(at: datetime | None = None) -> SessionType:
    """
    Return the current NYSE session type.

    Optionally accepts `at` (timezone-aware datetime) to query
    a specific moment rather than the current time.
    """
    now = (at.astimezone(_ET) if at else _now_et())

    if not _is_trading_day(now):
        return "closed"

    t = now.time()
    close = _close_time(now)

    if _OPEN <= t < close:
        return "regular"
    if _PRE_OPEN <= t < _OPEN:
        return "pre_market"
    if close <= t < _AFTER_CLOSE:
        return "after_hours"
    return "closed"


def is_regular_hours(at: datetime | None = None) -> bool:
    return session_type(at) == "regular"


def is_extended_hours(at: datetime | None = None) -> bool:
    return session_type(at) in ("pre_market", "after_hours")


def is_market_open(at: datetime | None = None) -> bool:
    """True only during the regular NYSE session."""
    return session_type(at) == "regular"


def next_open(at: datetime | None = None) -> datetime:
    """
    Return the next NYSE regular-session open (9:30 AM ET) from `at`.
    Skips weekends and full-close holidays.
    """
    from datetime import timedelta

    now = (at.astimezone(_ET) if at else _now_et())
    candidate = now.replace(hour=9, minute=30, second=0, microsecond=0)

    # If we've already passed 9:30 today, start searching tomorrow
    if candidate <= now:
        candidate += timedelta(days=1)

    # Advance until we land on a trading day
    while not _is_trading_day(candidate):
        candidate += timedelta(days=1)

    return candidate


def session_summary(at: datetime | None = None) -> dict:
    """
    Plain-English summary dict for Peter reporting.
    """
    now   = (at.astimezone(_ET) if at else _now_et())
    stype = session_type(at)
    ds    = _date_str(now)

    return {
        "session_type":      stype,
        "is_regular":        stype == "regular",
        "is_extended":       stype in ("pre_market", "after_hours"),
        "is_closed":         stype == "closed",
        "is_early_close":    ds in EARLY_CLOSE_DATES,
        "is_holiday":        ds in NYSE_FULL_CLOSE,
        "eastern_time":      now.strftime("%Y-%m-%d %H:%M:%S ET"),
        "extended_hours_warning": (
            "Extended hours: wider spreads and lower liquidity expected. "
            "Limit orders only by default."
            if stype in ("pre_market", "after_hours") else ""
        ),
    }
