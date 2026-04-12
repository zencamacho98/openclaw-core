"""
tests/test_market_time.py

Unit tests for app/market_time.py.

Covers:
  - session_type() returns correct session for known timestamps
  - is_regular_hours() / is_extended_hours() / is_market_open()
  - Holiday and early-close detection
  - next_open() advances past weekends and holidays
"""
from __future__ import annotations

import pathlib
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.market_time import (
    session_type, is_regular_hours, is_extended_hours, is_market_open,
    next_open, session_summary, NYSE_FULL_CLOSE, EARLY_CLOSE_DATES,
)

_ET = ZoneInfo("America/New_York")


def _et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_ET)


class TestSessionType(unittest.TestCase):

    def test_regular_session_midday(self):
        at = _et(2026, 4, 14, 12, 0)    # Tuesday 12:00 ET
        self.assertEqual(session_type(at), "regular")

    def test_regular_session_open(self):
        at = _et(2026, 4, 14, 9, 30)
        self.assertEqual(session_type(at), "regular")

    def test_regular_session_before_close(self):
        at = _et(2026, 4, 14, 15, 59)
        self.assertEqual(session_type(at), "regular")

    def test_after_close_is_after_hours(self):
        at = _et(2026, 4, 14, 16, 1)
        self.assertEqual(session_type(at), "after_hours")

    def test_pre_market(self):
        at = _et(2026, 4, 14, 7, 0)
        self.assertEqual(session_type(at), "pre_market")

    def test_before_premarket_is_closed(self):
        at = _et(2026, 4, 14, 3, 59)
        self.assertEqual(session_type(at), "closed")

    def test_saturday_is_closed(self):
        at = _et(2026, 4, 11, 11, 0)   # Saturday
        self.assertEqual(session_type(at), "closed")

    def test_sunday_is_closed(self):
        at = _et(2026, 4, 12, 11, 0)
        self.assertEqual(session_type(at), "closed")

    def test_holiday_is_closed(self):
        # 2026-01-01 is in NYSE_FULL_CLOSE
        at = _et(2026, 1, 1, 11, 0)
        self.assertEqual(session_type(at), "closed")

    def test_after_extended_hours_is_closed(self):
        at = _et(2026, 4, 14, 20, 1)
        self.assertEqual(session_type(at), "closed")


class TestEarlyClose(unittest.TestCase):

    def test_early_close_regular_session_ends_at_1pm(self):
        # 2026-11-27 is an early-close day
        at = _et(2026, 11, 27, 12, 59)
        self.assertEqual(session_type(at), "regular")

    def test_early_close_after_1pm_is_after_hours(self):
        at = _et(2026, 11, 27, 13, 1)
        self.assertEqual(session_type(at), "after_hours")


class TestHelpers(unittest.TestCase):

    def test_is_regular_hours(self):
        at = _et(2026, 4, 14, 12, 0)
        self.assertTrue(is_regular_hours(at))
        self.assertFalse(is_regular_hours(_et(2026, 4, 14, 17, 0)))

    def test_is_extended_hours(self):
        self.assertTrue(is_extended_hours(_et(2026, 4, 14, 7, 0)))   # pre
        self.assertTrue(is_extended_hours(_et(2026, 4, 14, 17, 0)))  # after
        self.assertFalse(is_extended_hours(_et(2026, 4, 14, 12, 0))) # regular

    def test_is_market_open(self):
        self.assertTrue(is_market_open(_et(2026, 4, 14, 12, 0)))
        self.assertFalse(is_market_open(_et(2026, 4, 14, 17, 0)))

    def test_next_open_skips_weekend(self):
        # Friday 4 PM → next open is Monday 9:30
        at = _et(2026, 4, 10, 16, 0)   # Friday
        nxt = next_open(at)
        self.assertEqual(nxt.weekday(), 0)      # Monday
        self.assertEqual(nxt.hour, 9)
        self.assertEqual(nxt.minute, 30)

    def test_next_open_skips_holiday(self):
        # Day before New Year's (holiday is 2026-01-01)
        at = _et(2025, 12, 31, 17, 0)
        nxt = next_open(at)
        # Should skip Jan 1 (holiday), land on Jan 2
        self.assertEqual(nxt.month, 1)
        self.assertGreater(nxt.day, 1)

    def test_session_summary_keys(self):
        at = _et(2026, 4, 14, 12, 0)
        s  = session_summary(at)
        for key in ("session_type", "is_regular", "is_extended", "is_closed", "eastern_time"):
            self.assertIn(key, s)

    def test_extended_hours_warning_in_pre_market(self):
        at = _et(2026, 4, 14, 7, 0)
        s  = session_summary(at)
        self.assertNotEqual(s["extended_hours_warning"], "")

    def test_no_extended_warning_in_regular(self):
        at = _et(2026, 4, 14, 12, 0)
        s  = session_summary(at)
        self.assertEqual(s["extended_hours_warning"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
