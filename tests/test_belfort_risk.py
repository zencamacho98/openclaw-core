# tests/test_belfort_risk.py
#
# Tests for app/belfort_risk.py — RiskGuardrails.
#
# Run with:
#   python -m unittest tests.test_belfort_risk -v

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.belfort_strategy import BelfortSignal
from app.belfort_risk import RiskGuardrails, RiskCheckResult


def _signal(
    action:       str   = "buy",
    qty:          int   = 1,
    limit_price:  float = 100.0,
    session_type: str   = "regular",
    data_lane:    str   = "IEX_ONLY",
    symbol:       str   = "SPY",
) -> BelfortSignal:
    return BelfortSignal(
        symbol       = symbol,
        action       = action,
        qty          = qty,
        order_type   = "marketable_limit" if action != "hold" else "none",
        limit_price  = limit_price if action != "hold" else 0.0,
        rationale    = "test signal",
        data_lane    = data_lane,
        session_type = session_type,
        generated_at = "2026-01-01T00:00:00+00:00",
    )


def _portfolio(
    realized_pnl:  float = 0.0,
    orders_today:  int   = 0,
    cash:          float = 100_000.0,
) -> dict:
    return {
        "realized_pnl_today":  realized_pnl,
        "orders_placed_today": orders_today,
        "cash":                cash,
    }


class TestRiskGuardrailsPassThrough(unittest.TestCase):

    def setUp(self) -> None:
        self.g = RiskGuardrails(
            daily_loss_cap     = 500.0,
            max_orders_per_day = 50,
            max_qty_per_order  = 100,
            min_cash_buffer    = 100.0,
        )

    def test_clean_buy_passes(self) -> None:
        result = self.g.check(_signal("buy", qty=1, limit_price=100.0), _portfolio())
        self.assertTrue(result.passed)
        self.assertEqual(result.check_name, "all_passed")

    def test_clean_sell_passes(self) -> None:
        result = self.g.check(_signal("sell", qty=1, limit_price=100.0), _portfolio())
        self.assertTrue(result.passed)

    def test_hold_passes_at_hold_passthrough(self) -> None:
        result = self.g.check(_signal("hold"), _portfolio())
        self.assertTrue(result.passed)
        self.assertEqual(result.check_name, "hold_passthrough")


class TestRiskGuardrailsBlocks(unittest.TestCase):

    def setUp(self) -> None:
        self.g = RiskGuardrails(
            daily_loss_cap     = 500.0,
            max_orders_per_day = 50,
            max_qty_per_order  = 100,
            min_cash_buffer    = 100.0,
        )

    def test_pre_market_passes_session_check(self) -> None:
        result = self.g.check(_signal("buy", session_type="pre_market"), _portfolio())
        self.assertTrue(result.passed)

    def test_after_hours_passes_session_check(self) -> None:
        result = self.g.check(_signal("sell", session_type="after_hours"), _portfolio())
        self.assertTrue(result.passed)

    def test_unknown_data_lane_blocked(self) -> None:
        result = self.g.check(_signal("buy", data_lane="UNKNOWN"), _portfolio())
        self.assertFalse(result.passed)
        self.assertEqual(result.check_name, "data_lane_check")

    def test_daily_loss_cap_blocked(self) -> None:
        result = self.g.check(
            _signal("buy"),
            _portfolio(realized_pnl=-500.0),
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.check_name, "daily_loss_cap")

    def test_daily_loss_cap_not_triggered_below(self) -> None:
        result = self.g.check(
            _signal("buy"),
            _portfolio(realized_pnl=-499.99),
        )
        self.assertTrue(result.passed)

    def test_daily_order_count_blocked(self) -> None:
        result = self.g.check(
            _signal("buy"),
            _portfolio(orders_today=50),
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.check_name, "daily_order_count")

    def test_default_guardrails_use_config_backstop_not_hardcoded_50(self) -> None:
        g = RiskGuardrails()
        with patch("app.strategy.config.get_config", return_value={"BELFORT_MAX_ORDERS_PER_DAY": 80}):
            result = g.check(_signal("buy"), _portfolio(orders_today=79))
        self.assertTrue(result.passed)

    def test_position_size_blocked(self) -> None:
        result = self.g.check(_signal("buy", qty=101), _portfolio())
        self.assertFalse(result.passed)
        self.assertEqual(result.check_name, "position_size")

    def test_cash_sufficiency_blocked_on_buy(self) -> None:
        # cost = 100.0 * 10 = 1000, buffer = 100 → need 1100, have 500
        result = self.g.check(
            _signal("buy", qty=10, limit_price=100.0),
            _portfolio(cash=500.0),
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.check_name, "cash_sufficiency")

    def test_cash_sufficiency_not_checked_for_sell(self) -> None:
        result = self.g.check(
            _signal("sell", qty=10, limit_price=100.0),
            _portfolio(cash=0.0),
        )
        # sell doesn't need cash
        self.assertTrue(result.passed)

    def test_block_returns_signal_unchanged(self) -> None:
        sig = _signal("buy", session_type="pre_market")
        result = self.g.check(sig, _portfolio())
        self.assertIs(result.signal, sig)

    def test_check_order_session_before_data_lane(self) -> None:
        # Both closed session and unknown lane — session_check should fire first
        result = self.g.check(
            _signal("buy", session_type="closed", data_lane="UNKNOWN"),
            _portfolio(),
        )
        self.assertEqual(result.check_name, "session_check")

    def test_check_order_data_lane_before_hold(self) -> None:
        # Unknown data lane on a hold — data_lane_check should fire before hold_passthrough
        result = self.g.check(_signal("hold", data_lane="UNKNOWN"), _portfolio())
        self.assertFalse(result.passed)
        self.assertEqual(result.check_name, "data_lane_check")

    def test_unexpected_exception_returns_block(self) -> None:
        """Any unexpected error in guardrails must block, not pass through."""
        with patch.object(self.g, "_run_checks", side_effect=RuntimeError("boom")):
            result = self.g.check(_signal("buy"), _portfolio())
        self.assertFalse(result.passed)
        self.assertEqual(result.check_name, "guardrail_error")

    def test_block_reason_non_empty_on_block(self) -> None:
        result = self.g.check(_signal("buy", session_type="closed"), _portfolio())
        self.assertFalse(result.passed)
        self.assertIsNotNone(result.block_reason)
        self.assertGreater(len(result.block_reason), 0)

    def test_passed_has_no_block_reason(self) -> None:
        result = self.g.check(_signal("buy"), _portfolio())
        self.assertTrue(result.passed)
        self.assertIsNone(result.block_reason)

    def test_hold_not_blocked_by_daily_loss(self) -> None:
        """Hold signals should pass through even when loss cap is hit."""
        result = self.g.check(
            _signal("hold"),
            _portfolio(realized_pnl=-1000.0),
        )
        # hold_passthrough fires before daily_loss_cap
        self.assertTrue(result.passed)
        self.assertEqual(result.check_name, "hold_passthrough")


if __name__ == "__main__":
    unittest.main()
