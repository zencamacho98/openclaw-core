# tests/test_belfort_strategy.py
#
# Tests for app/belfort_strategy.py — BelfortSignal and MeanReversionV1.
#
# Run with:
#   python -m unittest tests.test_belfort_strategy -v

from __future__ import annotations

import pathlib
import sys
import unittest
from dataclasses import dataclass
from typing import Literal

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.belfort_strategy import BelfortSignal, MeanReversionV1


@dataclass
class FakeQuote:
    symbol:       str   = "SPY"
    bid:          float = 0.0
    ask:          float = 0.0
    last:         float = 0.0
    data_lane:    str   = "IEX_ONLY"
    session_type: str   = "regular"


def _regular_quote(bid: float = 500.0, ask: float = 500.10, symbol: str = "SPY") -> FakeQuote:
    return FakeQuote(
        symbol       = symbol,
        bid          = bid,
        ask          = ask,
        last         = bid,
        data_lane    = "IEX_ONLY",
        session_type = "regular",
    )


class TestBelfortSignalContract(unittest.TestCase):

    def test_signal_has_all_required_fields(self) -> None:
        s = BelfortSignal(
            symbol="SPY", action="hold", qty=0, order_type="none",
            limit_price=0.0, rationale="test", data_lane="IEX_ONLY",
            session_type="regular", generated_at="2026-01-01T00:00:00+00:00",
        )
        for field in ("symbol", "action", "qty", "order_type", "limit_price",
                      "rationale", "data_lane", "session_type", "generated_at"):
            self.assertTrue(hasattr(s, field), f"Missing field: {field}")

    def test_hold_signal_shape(self) -> None:
        s = BelfortSignal(
            symbol="SPY", action="hold", qty=0, order_type="none",
            limit_price=0.0, rationale="outside hours", data_lane="IEX_ONLY",
            session_type="pre_market", generated_at="2026-01-01T00:00:00+00:00",
        )
        self.assertEqual(s.action, "hold")
        self.assertEqual(s.qty, 0)
        self.assertEqual(s.order_type, "none")
        self.assertEqual(s.limit_price, 0.0)


class TestMeanReversionV1Overrides(unittest.TestCase):

    def setUp(self) -> None:
        self.strat = MeanReversionV1(window=5, threshold=0.01, qty=10)

    def test_closed_session_returns_hold(self) -> None:
        q = FakeQuote(bid=500.0, ask=500.10, session_type="closed")
        sig = self.strat.evaluate(q)
        self.assertEqual(sig.action, "hold")
        self.assertIn("paper-tradeable session is closed", sig.rationale)

    def test_closed_session_does_not_mutate_history(self) -> None:
        q = FakeQuote(bid=500.0, ask=500.10, session_type="closed")
        before = len(self.strat._history)
        self.strat.evaluate(q)
        self.assertEqual(len(self.strat._history), before)

    def test_pre_market_can_evaluate(self) -> None:
        q = FakeQuote(bid=500.0, ask=500.10, session_type="pre_market")
        sig = self.strat.evaluate(q)
        self.assertEqual(sig.session_type, "pre_market")

    def test_unknown_data_lane_returns_hold(self) -> None:
        q = FakeQuote(bid=500.0, ask=500.10, data_lane="UNKNOWN")
        sig = self.strat.evaluate(q)
        self.assertEqual(sig.action, "hold")
        self.assertIn("data lane unknown", sig.rationale)

    def test_unknown_data_lane_does_not_mutate_history(self) -> None:
        q = FakeQuote(bid=500.0, ask=500.10, data_lane="UNKNOWN")
        before = len(self.strat._history)
        self.strat.evaluate(q)
        self.assertEqual(len(self.strat._history), before)

    def test_bad_spread_returns_hold(self) -> None:
        q = _regular_quote(bid=0.0, ask=0.0)
        sig = self.strat.evaluate(q)
        self.assertEqual(sig.action, "hold")

    def test_warmup_returns_hold(self) -> None:
        # window=5, so min_ticks = max(2, 5//2) = 2
        # first tick should still hold (1 < 2)
        q = _regular_quote(bid=500.0, ask=500.10)
        self.strat = MeanReversionV1(window=10, threshold=0.01, qty=1)
        sig = self.strat.evaluate(q)
        self.assertEqual(sig.action, "hold")
        self.assertIn("warming up", sig.rationale)


class TestMeanReversionV1Signals(unittest.TestCase):

    def setUp(self) -> None:
        self.strat = MeanReversionV1(window=5, threshold=0.01, qty=2)

    def _fill_history(self, mid: float = 500.05, n: int = 5) -> None:
        """Prime the strategy with n identical ticks to establish mean."""
        for _ in range(n):
            bid = mid - 0.05
            ask = mid + 0.05
            self.strat.evaluate(_regular_quote(bid=bid, ask=ask))

    def test_below_mean_triggers_buy(self) -> None:
        self._fill_history(mid=500.05)
        # Now quote well below mean
        sig = self.strat.evaluate(_regular_quote(bid=494.0, ask=494.10))
        self.assertEqual(sig.action, "buy")
        self.assertEqual(sig.order_type, "marketable_limit")
        self.assertGreater(sig.limit_price, 0)

    def test_buy_limit_price_is_ask(self) -> None:
        self._fill_history(mid=500.05)
        ask = 494.50
        sig = self.strat.evaluate(_regular_quote(bid=494.40, ask=ask))
        if sig.action == "buy":
            self.assertAlmostEqual(sig.limit_price, round(ask, 4), places=4)

    def test_above_mean_triggers_sell(self) -> None:
        self._fill_history(mid=500.05)
        sig = self.strat.evaluate(_regular_quote(bid=506.90, ask=507.00))
        self.assertEqual(sig.action, "sell")
        self.assertEqual(sig.order_type, "marketable_limit")

    def test_sell_limit_price_is_bid(self) -> None:
        self._fill_history(mid=500.05)
        bid = 506.90
        sig = self.strat.evaluate(_regular_quote(bid=bid, ask=507.00))
        if sig.action == "sell":
            self.assertAlmostEqual(sig.limit_price, round(bid, 4), places=4)

    def test_within_threshold_returns_hold(self) -> None:
        self._fill_history(mid=500.05)
        # 0.001 deviation << 0.01 threshold
        sig = self.strat.evaluate(_regular_quote(bid=500.00, ask=500.10))
        self.assertEqual(sig.action, "hold")

    def test_generated_at_is_present(self) -> None:
        self._fill_history()
        sig = self.strat.evaluate(_regular_quote(bid=494.0, ask=494.10))
        self.assertIsNotNone(sig.generated_at)
        self.assertIn("T", sig.generated_at)

    def test_reset_clears_history(self) -> None:
        self._fill_history()
        self.strat.reset()
        self.assertEqual(len(self.strat._history), 0)
        # Next evaluate should warm up again
        sig = self.strat.evaluate(_regular_quote(bid=494.0, ask=494.10))
        self.assertEqual(sig.action, "hold")
        self.assertIn("warming up", sig.rationale)


if __name__ == "__main__":
    unittest.main()
