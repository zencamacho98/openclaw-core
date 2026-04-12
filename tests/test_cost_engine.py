"""
tests/test_cost_engine.py

Unit tests for app/cost_engine.py.

Covers:
  - Explicit fee calculation: SEC 31, FINRA TAF, commission
  - Spread cost: market orders cross the spread; limit orders do not
  - Slippage uncertainty classification (low / medium / high)
  - Extended-hours warning flag
  - Data lane disclaimer
  - Buy-side: no SEC 31 or TAF
  - FINRA TAF cap enforcement
  - summary_line() output
"""
from __future__ import annotations

import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.cost_engine import estimate, CostEstimate, BROKER_PROFILES


class TestExplicitFees(unittest.TestCase):

    def _sell(self, qty=100, price=100.0, **kwargs) -> CostEstimate:
        return estimate(
            symbol="SPY", side="sell", qty=qty, price=price,
            broker_profile="alpaca_retail", session_type="regular",
            data_lane="SIP_CONSOLIDATED", **kwargs
        )

    def _buy(self, qty=100, price=100.0, **kwargs) -> CostEstimate:
        return estimate(
            symbol="SPY", side="buy", qty=qty, price=price,
            broker_profile="alpaca_retail", session_type="regular",
            data_lane="SIP_CONSOLIDATED", **kwargs
        )

    def test_sec_31_on_sell(self):
        est = self._sell(qty=100, price=100.0)
        # principal = 10000; rate = 0.0000206 → 0.206
        self.assertAlmostEqual(est.sec_31_fee_usd, 0.206, places=4)

    def test_sec_31_zero_on_buy(self):
        est = self._buy()
        self.assertEqual(est.sec_31_fee_usd, 0.0)

    def test_finra_taf_on_sell(self):
        est = self._sell(qty=100, price=100.0)
        # 100 shares × $0.000166 = $0.0166
        self.assertAlmostEqual(est.finra_taf_usd, 0.0166, places=4)

    def test_finra_taf_zero_on_buy(self):
        est = self._buy()
        self.assertEqual(est.finra_taf_usd, 0.0)

    def test_finra_taf_capped(self):
        # 100,000 shares × $0.000166 = $16.60 → capped at $8.30
        est = self._sell(qty=100_000, price=1.0)
        self.assertAlmostEqual(est.finra_taf_usd, 8.30, places=2)

    def test_commission_zero_for_alpaca(self):
        est = self._sell()
        self.assertEqual(est.commission_usd, 0.0)

    def test_total_explicit_buy_is_zero_fees(self):
        # Buy has no SEC 31, no TAF, no commission (alpaca_retail)
        est = self._buy()
        self.assertEqual(est.total_explicit_usd, 0.0)


class TestImplicitCosts(unittest.TestCase):

    def test_market_order_has_spread_cost(self):
        est = estimate(
            symbol="SPY", side="buy", qty=10, price=500.0,
            session_type="regular", data_lane="SIP_CONSOLIDATED",
            observed_spread_pct=0.002, order_type="market",
        )
        # principal = 10 × 500 = 5000
        # half-spread = 0.002 / 2 = 0.001
        # spread_cost = 0.001 × 5000 = 5.0
        self.assertAlmostEqual(est.spread_cost_usd, 5.0, places=4)

    def test_limit_order_no_spread_cost(self):
        est = estimate(
            symbol="SPY", side="buy", qty=10, price=500.0,
            session_type="regular", data_lane="SIP_CONSOLIDATED",
            observed_spread_pct=0.002, order_type="limit",
        )
        self.assertEqual(est.spread_cost_usd, 0.0)

    def test_slippage_positive(self):
        est = estimate(
            symbol="SPY", side="buy", qty=10, price=100.0,
            session_type="regular", data_lane="SIP_CONSOLIDATED",
        )
        self.assertGreater(est.slippage_estimate_usd, 0.0)

    def test_extended_hours_has_higher_slippage(self):
        reg = estimate("SPY", "buy", 10, 100.0, session_type="regular",   data_lane="SIP_CONSOLIDATED")
        ext = estimate("SPY", "buy", 10, 100.0, session_type="after_hours", data_lane="SIP_CONSOLIDATED")
        self.assertGreater(ext.slippage_estimate_usd, reg.slippage_estimate_usd)


class TestUncertainty(unittest.TestCase):

    def test_sip_regular_tight_spread_is_low(self):
        est = estimate(
            "SPY", "buy", 10, 100.0, session_type="regular",
            data_lane="SIP_CONSOLIDATED", observed_spread_pct=0.0001
        )
        self.assertEqual(est.slippage_uncertainty, "low")

    def test_iex_is_high(self):
        est = estimate("SPY", "buy", 10, 100.0, data_lane="IEX_ONLY")
        self.assertEqual(est.slippage_uncertainty, "high")

    def test_extended_is_high(self):
        est = estimate("SPY", "buy", 10, 100.0, session_type="pre_market",
                       data_lane="SIP_CONSOLIDATED")
        self.assertEqual(est.slippage_uncertainty, "high")

    def test_wide_spread_is_high(self):
        est = estimate("SPY", "buy", 10, 100.0, data_lane="SIP_CONSOLIDATED",
                       session_type="regular", observed_spread_pct=0.01)
        self.assertEqual(est.slippage_uncertainty, "high")

    def test_medium_spread_is_medium(self):
        est = estimate("SPY", "buy", 10, 100.0, data_lane="SIP_CONSOLIDATED",
                       session_type="regular", observed_spread_pct=0.003)
        self.assertEqual(est.slippage_uncertainty, "medium")


class TestDisclaimers(unittest.TestCase):

    def test_iex_disclaimer_present(self):
        est = estimate("SPY", "buy", 10, 100.0, data_lane="IEX_ONLY")
        self.assertIn("IEX", est.data_lane_disclaimer)

    def test_sip_no_disclaimer(self):
        est = estimate("SPY", "buy", 10, 100.0, data_lane="SIP_CONSOLIDATED",
                       session_type="regular")
        self.assertEqual(est.data_lane_disclaimer, "")

    def test_extended_hours_warning_set(self):
        est = estimate("SPY", "buy", 10, 100.0, session_type="after_hours",
                       data_lane="SIP_CONSOLIDATED")
        self.assertTrue(est.extended_hours_warning)

    def test_regular_no_extended_warning(self):
        est = estimate("SPY", "buy", 10, 100.0, session_type="regular",
                       data_lane="SIP_CONSOLIDATED")
        self.assertFalse(est.extended_hours_warning)


class TestSummaryLine(unittest.TestCase):

    def test_summary_line_contains_symbol(self):
        est = estimate("AAPL", "sell", 5, 200.0,
                       session_type="regular", data_lane="SIP_CONSOLIDATED")
        line = est.summary_line()
        self.assertIn("AAPL", line)
        self.assertIn("SELL", line)

    def test_summary_line_shows_extended(self):
        est = estimate("SPY", "buy", 10, 100.0, session_type="pre_market",
                       data_lane="IEX_ONLY")
        line = est.summary_line()
        self.assertIn("EXTENDED HOURS", line)

    def test_to_dict_has_all_fields(self):
        est = estimate("SPY", "buy", 10, 100.0)
        d = est.to_dict()
        for key in ("symbol", "side", "qty", "price", "sec_31_fee_usd",
                    "finra_taf_usd", "spread_cost_usd", "slippage_estimate_usd",
                    "total_estimated_cost_usd", "slippage_uncertainty",
                    "data_lane_disclaimer", "extended_hours_warning"):
            self.assertIn(key, d, f"Missing key: {key}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
