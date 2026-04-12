"""
tests/test_execution_overlay.py

Unit tests for app/execution_overlay.py.

Covers:
  - Market buy fills at ask, not last-trade
  - Market sell fills at bid
  - Non-marketable limit buy flagged (is_realistic=False)
  - Non-marketable limit sell flagged
  - Marketable limit: can_proceed=True
  - Extended hours: market order blocked by default
  - Wide spread warning
  - Partial fill estimation (ask_size < qty)
  - IEX data lane warning
"""
from __future__ import annotations

import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.execution_overlay import (
    check_order, OrderIntent, OverlayResult, EXTENDED_HOURS_ALLOW_MARKET,
)


class _FakeQuote:
    """Minimal quote object for overlay tests."""
    def __init__(
        self,
        bid: float | None = 99.50,
        ask: float | None = 100.50,
        bid_size: float | None = 100,
        ask_size: float | None = 100,
        spread_pct: float | None = 0.01,
        midpoint: float | None = 100.0,
        data_lane: str = "SIP_CONSOLIDATED",
    ):
        self.bid        = bid
        self.ask        = ask
        self.bid_size   = bid_size
        self.ask_size   = ask_size
        self.spread_pct = spread_pct
        self.midpoint   = midpoint
        self.data_lane  = data_lane


class TestMarketOrders(unittest.TestCase):

    def test_market_buy_fills_at_ask(self):
        intent = OrderIntent("SPY", "buy", qty=10, order_type="market")
        quote  = _FakeQuote(ask=100.50, spread_pct=0.001)
        result = check_order(intent, quote, session_type="regular")
        self.assertEqual(result.adjusted_fill_price, 100.50)

    def test_market_sell_fills_at_bid(self):
        intent = OrderIntent("SPY", "sell", qty=10, order_type="market")
        quote  = _FakeQuote(bid=99.50, spread_pct=0.001)
        result = check_order(intent, quote, session_type="regular")
        self.assertEqual(result.adjusted_fill_price, 99.50)

    def test_market_buy_no_ask_warns(self):
        intent = OrderIntent("SPY", "buy", qty=10, order_type="market")
        quote  = _FakeQuote(ask=None, spread_pct=None)
        result = check_order(intent, quote, session_type="regular")
        self.assertTrue(any("Ask price unavailable" in w for w in result.warnings))

    def test_can_proceed_for_market_order(self):
        intent = OrderIntent("SPY", "buy", qty=5, order_type="market")
        quote  = _FakeQuote(spread_pct=0.001)
        result = check_order(intent, quote, session_type="regular")
        self.assertTrue(result.can_proceed)


class TestLimitOrders(unittest.TestCase):

    def test_non_marketable_limit_buy_is_not_realistic(self):
        # Limit buy at $99 < ask of $100.50 → non-marketable
        intent = OrderIntent("SPY", "buy", qty=10, order_type="limit", limit_price=99.0)
        quote  = _FakeQuote(ask=100.50, spread_pct=0.001)
        result = check_order(intent, quote, session_type="regular")
        self.assertFalse(result.is_realistic)
        self.assertTrue(any("non-marketable" in w for w in result.warnings))

    def test_non_marketable_limit_sell_is_not_realistic(self):
        # Limit sell at $101 > bid of $99.50 → non-marketable
        intent = OrderIntent("SPY", "sell", qty=10, order_type="limit", limit_price=101.0)
        quote  = _FakeQuote(bid=99.50, spread_pct=0.001)
        result = check_order(intent, quote, session_type="regular")
        self.assertFalse(result.is_realistic)

    def test_marketable_limit_buy_is_realistic(self):
        # Limit buy at $101 >= ask of $100.50 → marketable
        intent = OrderIntent("SPY", "buy", qty=10, order_type="limit", limit_price=101.0)
        quote  = _FakeQuote(ask=100.50, spread_pct=0.001)
        result = check_order(intent, quote, session_type="regular")
        self.assertTrue(result.is_realistic)

    def test_limit_fill_price_is_limit_price(self):
        intent = OrderIntent("SPY", "buy", qty=5, order_type="limit", limit_price=99.0)
        quote  = _FakeQuote(spread_pct=0.001)
        result = check_order(intent, quote, session_type="regular")
        self.assertEqual(result.adjusted_fill_price, 99.0)


class TestExtendedHours(unittest.TestCase):

    def test_market_order_blocked_in_extended_hours(self):
        import app.execution_overlay as overlay
        # Ensure default is False
        orig = overlay.EXTENDED_HOURS_ALLOW_MARKET
        overlay.EXTENDED_HOURS_ALLOW_MARKET = False
        try:
            intent = OrderIntent("SPY", "buy", qty=10, order_type="market")
            quote  = _FakeQuote(spread_pct=0.005)
            result = check_order(intent, quote, session_type="pre_market")
            self.assertFalse(result.can_proceed)
            self.assertEqual(result.block_reason, "market_order_extended_hours_blocked")
        finally:
            overlay.EXTENDED_HOURS_ALLOW_MARKET = orig

    def test_limit_order_allowed_in_extended_hours(self):
        intent = OrderIntent("SPY", "buy", qty=10, order_type="limit", limit_price=101.0)
        quote  = _FakeQuote(ask=100.50, spread_pct=0.005)
        result = check_order(intent, quote, session_type="after_hours")
        self.assertTrue(result.can_proceed)

    def test_extended_hours_warning_in_result(self):
        intent = OrderIntent("SPY", "buy", qty=5, order_type="limit", limit_price=101.0)
        quote  = _FakeQuote(ask=100.50, spread_pct=0.002)
        result = check_order(intent, quote, session_type="pre_market")
        self.assertTrue(any("Extended hours" in w for w in result.warnings))


class TestPartialFill(unittest.TestCase):

    def test_partial_fill_when_ask_size_less_than_qty(self):
        intent = OrderIntent("SPY", "buy", qty=50, order_type="market")
        quote  = _FakeQuote(ask_size=5, spread_pct=0.001)  # only 5 shares available
        result = check_order(intent, quote, session_type="regular")
        self.assertIsNotNone(result.partial_fill_qty)
        self.assertEqual(result.partial_fill_qty, 5)

    def test_no_partial_fill_when_size_sufficient(self):
        intent = OrderIntent("SPY", "buy", qty=10, order_type="market")
        quote  = _FakeQuote(ask_size=200, spread_pct=0.001)
        result = check_order(intent, quote, session_type="regular")
        self.assertIsNone(result.partial_fill_qty)


class TestDataLane(unittest.TestCase):

    def test_iex_warning_present(self):
        intent = OrderIntent("SPY", "buy", qty=10, order_type="market")
        quote  = _FakeQuote(data_lane="IEX_ONLY", spread_pct=0.001)
        result = check_order(intent, quote, session_type="regular")
        self.assertTrue(any("IEX" in w for w in result.warnings))

    def test_sip_no_lane_warning(self):
        intent = OrderIntent("SPY", "buy", qty=10, order_type="market")
        quote  = _FakeQuote(data_lane="SIP_CONSOLIDATED", spread_pct=0.001)
        result = check_order(intent, quote, session_type="regular")
        lane_warnings = [w for w in result.warnings if "IEX" in w or "unknown" in w.lower()]
        self.assertEqual(len(lane_warnings), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
