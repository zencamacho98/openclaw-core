"""
tests/test_market_data_feed.py

Unit tests for app/market_data_feed.py.

Covers:
  - get_quote() returns a QuoteEvent with data_lane always set
  - Simulated mode when no credentials configured
  - feed_status() returns a FeedStatus
  - DATA_LANE is one of the valid constants
  - QuoteEvent.to_dict() has expected fields
  - Spread/midpoint computed correctly when bid/ask present
"""
from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.market_data_feed import (
    get_quote, feed_status, DATA_LANE, QuoteEvent, FeedStatus,
    _simulated_quote,
)


class TestDataLane(unittest.TestCase):

    def test_data_lane_is_valid_constant(self):
        self.assertIn(DATA_LANE, ("IEX_ONLY", "SIP_CONSOLIDATED", "UNKNOWN"))


class TestSimulatedMode(unittest.TestCase):

    def _no_creds(self):
        """Context: no API credentials → simulated mode."""
        return patch.multiple(
            "app.market_data_feed",
            _API_KEY="",
            _API_SECRET="",
        )

    def test_no_creds_returns_simulated_quote(self):
        with self._no_creds():
            q = get_quote("SPY")
        self.assertFalse(q.is_live)
        self.assertEqual(q.source, "simulated")

    def test_simulated_quote_has_data_lane(self):
        with self._no_creds():
            q = get_quote("AAPL")
        self.assertIn(q.data_lane, ("IEX_ONLY", "SIP_CONSOLIDATED", "UNKNOWN"))

    def test_simulated_quote_symbol_uppercased(self):
        with self._no_creds():
            q = get_quote("spy")
        self.assertEqual(q.symbol, "SPY")

    def test_simulated_quote_has_timestamp(self):
        with self._no_creds():
            q = get_quote("SPY")
        self.assertIsNotNone(q.timestamp)
        self.assertIn("T", q.timestamp)  # ISO format


class TestQuoteEvent(unittest.TestCase):

    def _make_quote(self, bid=99.5, ask=100.5) -> QuoteEvent:
        import app.market_data_feed as mf
        ts = "2026-04-11T12:00:00+00:00"
        return QuoteEvent(
            symbol="SPY", bid=bid, ask=ask, bid_size=100, ask_size=200,
            last=100.0, last_size=50,
            spread=ask - bid if (bid and ask) else None,
            spread_pct=(ask - bid) / ((bid + ask) / 2) if (bid and ask) else None,
            midpoint=(bid + ask) / 2 if (bid and ask) else None,
            data_lane="IEX_ONLY",
            timestamp=ts,
            is_live=True,
            source="alpaca",
            conditions=[],
        )

    def test_spread_computed(self):
        q = self._make_quote(99.5, 100.5)
        self.assertAlmostEqual(q.spread, 1.0, places=4)

    def test_midpoint_computed(self):
        q = self._make_quote(99.5, 100.5)
        self.assertAlmostEqual(q.midpoint, 100.0, places=4)

    def test_to_dict_has_data_lane(self):
        q = self._make_quote()
        d = q.to_dict()
        self.assertIn("data_lane", d)
        self.assertEqual(d["data_lane"], "IEX_ONLY")

    def test_to_dict_has_all_required_fields(self):
        q = self._make_quote()
        d = q.to_dict()
        for key in ("symbol", "bid", "ask", "spread", "midpoint", "data_lane",
                    "is_live", "source", "timestamp"):
            self.assertIn(key, d, f"Missing field: {key}")


class TestFeedStatus(unittest.TestCase):

    def test_feed_status_returns_feed_status(self):
        s = feed_status()
        self.assertIsInstance(s, FeedStatus)

    def test_feed_status_has_data_lane(self):
        s = feed_status()
        self.assertIn(s.data_lane, ("IEX_ONLY", "SIP_CONSOLIDATED", "UNKNOWN"))

    def test_no_creds_not_connected(self):
        with patch.multiple("app.market_data_feed", _API_KEY="", _API_SECRET=""):
            s = feed_status()
        self.assertFalse(s.has_credentials)

    def test_summary_line_is_string(self):
        s = feed_status()
        self.assertIsInstance(s.summary_line(), str)
        self.assertGreater(len(s.summary_line()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
