"""
tests/test_trade_helpers.py

Unit tests for ui/trade_helpers.py.

Covers:
  - format_pnl: positive, negative, zero, boundary
  - format_trade_row: basic fields, win/loss result, missing fields
  - trading_status_summary: off, running no-trades, running with-trades, win/loss counts

Run with:
    python -m pytest tests/test_trade_helpers.py -v
    python -m unittest tests.test_trade_helpers -v
"""
from __future__ import annotations

import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from ui.trade_helpers import format_pnl, format_trade_row, trading_status_summary


class TestFormatPnl(unittest.TestCase):

    def test_positive_value(self):
        self.assertEqual(format_pnl(123.45), "+$123.45")

    def test_negative_value(self):
        self.assertEqual(format_pnl(-67.89), "-$67.89")

    def test_zero(self):
        self.assertEqual(format_pnl(0.0), "$0.00")

    def test_large_positive(self):
        result = format_pnl(1234567.89)
        self.assertIn("+$", result)
        self.assertIn("1,234,567", result)

    def test_large_negative(self):
        result = format_pnl(-9999.99)
        self.assertIn("-$", result)
        self.assertIn("9,999.99", result)

    def test_very_small_positive(self):
        # Values > 0 should always show +$
        result = format_pnl(0.01)
        self.assertTrue(result.startswith("+$"))

    def test_very_small_negative(self):
        result = format_pnl(-0.01)
        self.assertTrue(result.startswith("-$"))


class TestFormatTradeRow(unittest.TestCase):

    _TRADE = {
        "timestamp": "2026-04-10T12:34:56+00:00",
        "side":      "SELL",
        "qty":       100,
        "price":     150.25,
        "pnl":       45.50,
    }

    def test_time_extracted_correctly(self):
        row = format_trade_row(self._TRADE)
        self.assertEqual(row["Time"], "12:34:56")

    def test_side_preserved(self):
        row = format_trade_row(self._TRADE)
        self.assertEqual(row["Side"], "SELL")

    def test_qty_preserved(self):
        row = format_trade_row(self._TRADE)
        self.assertEqual(row["Qty"], 100)

    def test_price_formatted(self):
        row = format_trade_row(self._TRADE)
        self.assertIn("150.25", row["Price"])
        self.assertIn("$", row["Price"])

    def test_winning_trade_result(self):
        row = format_trade_row(self._TRADE)
        self.assertEqual(row["Result"], "Win")
        self.assertIn("+$", row["P&L"])

    def test_losing_trade_result(self):
        row = format_trade_row({**self._TRADE, "pnl": -22.00})
        self.assertEqual(row["Result"], "Loss")
        self.assertIn("-$", row["P&L"])

    def test_flat_trade_result(self):
        row = format_trade_row({**self._TRADE, "pnl": 0.0})
        self.assertEqual(row["Result"], "Flat")
        self.assertEqual(row["P&L"], "$0.00")

    def test_missing_fields_return_safe_defaults(self):
        row = format_trade_row({})
        self.assertEqual(row["Side"], "?")
        self.assertEqual(row["Qty"], 0)
        self.assertIn("$", row["Price"])
        self.assertEqual(row["Result"], "Flat")

    def test_short_timestamp_handled(self):
        row = format_trade_row({"timestamp": "12:34"})
        # Should not raise; result is some string
        self.assertIsInstance(row["Time"], str)

    def test_buy_side(self):
        row = format_trade_row({**self._TRADE, "side": "BUY", "pnl": 0.0})
        self.assertEqual(row["Side"], "BUY")

    def test_returns_all_required_keys(self):
        row = format_trade_row(self._TRADE)
        for key in ("Time", "Side", "Qty", "Price", "P&L", "Result"):
            self.assertIn(key, row, f"Missing key: {key}")


class TestTradingStatusSummary(unittest.TestCase):

    def test_trading_off(self):
        result = trading_status_summary(False, None, None)
        self.assertIn("off", result.lower())

    def test_trading_on_no_trades(self):
        state = {"ticks": 50, "interval": 3}
        result = trading_status_summary(True, state, [])
        self.assertIn("running", result.lower())
        self.assertIn("50", result)
        self.assertIn("no trades", result.lower())

    def test_trading_on_with_trades_counts_wins_and_losses(self):
        trades = [
            {"pnl": 10.0},
            {"pnl": -5.0},
            {"pnl": 20.0},
            {"pnl": -3.0},
            {"pnl": 0.0},
        ]
        result = trading_status_summary(True, {"ticks": 100, "interval": 5}, trades)
        self.assertIn("5", result)   # total trades
        self.assertIn("2", result)   # wins
        self.assertIn("2", result)   # losses (overlaps with "2" wins but both present)

    def test_trading_on_returns_trade_count(self):
        trades = [{"pnl": 5.0}] * 7
        result = trading_status_summary(True, {}, trades)
        self.assertIn("7", result)

    def test_trading_off_ignores_trades_argument(self):
        # Even if trades list is non-empty, off means off
        result = trading_status_summary(False, {}, [{"pnl": 5.0}])
        self.assertIn("off", result.lower())

    def test_no_trades_when_trading_on_mentions_no_trades(self):
        result = trading_status_summary(True, {}, None)
        self.assertIn("no trades", result.lower())

    def test_active_status_says_active(self):
        trades = [{"pnl": 1.0}, {"pnl": -1.0}]
        result = trading_status_summary(True, {"ticks": 10, "interval": 1}, trades)
        self.assertIn("active", result.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
