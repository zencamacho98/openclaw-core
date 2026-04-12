"""
tests/test_reconciler.py

Unit tests for app/reconciler.py.

Covers:
  - run_reconciliation() returns a ReconciliationReport
  - Passes when broker and internal positions match
  - Fails when they diverge
  - Halted flag is set on FAIL, cleared on PASS
  - No broker → skipped (not FAIL)
  - get_last_report() returns last report
  - is_halted() reflects last result
  - clear_halt() clears the flag
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import app.reconciler as rec

# Patch targets: reconciler uses lazy imports inside run_reconciliation()
_PATCH_CONNECTOR = "app.broker_connector.get_connector"
_PATCH_SNAPSHOT  = "app.portfolio.get_snapshot"
_PATCH_APPEND    = "app.order_ledger.append"
_PATCH_ALERTS    = "observability.event_log.append_event"


class TestReconciliation(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = pathlib.Path(self._tmpdir.name)
        self._log_patcher = patch.object(rec, "_RECON_LOG", self._tmp / "recon.jsonl")
        self._log_patcher.start()
        # Reset module state
        rec._halted = False
        rec._last_report = None

    def tearDown(self):
        self._log_patcher.stop()
        self._tmpdir.cleanup()
        rec._halted = False
        rec._last_report = None

    def _mock_connector(self, broker_positions: dict):
        mock = MagicMock()
        mock_positions = []
        for sym, qty in broker_positions.items():
            p = MagicMock()
            p.symbol = sym
            p.qty    = qty
            mock_positions.append(p)
        mock.get_positions.return_value = mock_positions
        return mock

    def _mock_portfolio(self, internal_positions: dict) -> dict:
        positions = {sym: {"qty": qty, "avg_cost": 100.0} for sym, qty in internal_positions.items()}
        return {"positions": positions, "cash": 100000.0, "realized_pnl": 0.0}

    def test_returns_reconciliation_report(self):
        conn = self._mock_connector({})
        snap = {"positions": {}}
        with patch(_PATCH_CONNECTOR, return_value=conn):
            with patch(_PATCH_SNAPSHOT, return_value=snap):
                with patch(_PATCH_APPEND):
                    report = rec.run_reconciliation("paper")
        self.assertIsInstance(report, rec.ReconciliationReport)

    def test_pass_when_positions_match(self):
        conn = self._mock_connector({"SPY": 10.0})
        snap = self._mock_portfolio({"SPY": 10.0})
        with patch(_PATCH_CONNECTOR, return_value=conn):
            with patch(_PATCH_SNAPSHOT, return_value=snap):
                with patch(_PATCH_APPEND):
                    report = rec.run_reconciliation("paper")
        self.assertTrue(report.passed)
        self.assertEqual(report.mismatches, 0)

    def test_fail_when_positions_diverge(self):
        conn = self._mock_connector({"SPY": 10.0})
        snap = self._mock_portfolio({"SPY": 5.0})
        with patch(_PATCH_CONNECTOR, return_value=conn):
            with patch(_PATCH_SNAPSHOT, return_value=snap):
                with patch(_PATCH_APPEND):
                    with patch(_PATCH_ALERTS):
                        report = rec.run_reconciliation("paper")
        self.assertFalse(report.passed)
        self.assertGreater(report.mismatches, 0)

    def test_halted_on_fail(self):
        conn = self._mock_connector({"SPY": 10.0})
        snap = self._mock_portfolio({"SPY": 0.0})
        with patch(_PATCH_CONNECTOR, return_value=conn):
            with patch(_PATCH_SNAPSHOT, return_value=snap):
                with patch(_PATCH_APPEND):
                    with patch(_PATCH_ALERTS):
                        rec.run_reconciliation("paper")
        self.assertTrue(rec.is_halted())

    def test_not_halted_on_pass(self):
        conn = self._mock_connector({"SPY": 10.0})
        snap = self._mock_portfolio({"SPY": 10.0})
        with patch(_PATCH_CONNECTOR, return_value=conn):
            with patch(_PATCH_SNAPSHOT, return_value=snap):
                with patch(_PATCH_APPEND):
                    rec.run_reconciliation("paper")
        self.assertFalse(rec.is_halted())

    def test_no_broker_skipped_not_fail(self):
        with patch(_PATCH_CONNECTOR, return_value=None):
            with patch(_PATCH_APPEND):
                report = rec.run_reconciliation("paper")
        self.assertTrue(report.passed)
        self.assertFalse(report.broker_available)

    def test_get_last_report_after_run(self):
        conn = self._mock_connector({})
        snap = {"positions": {}}
        with patch(_PATCH_CONNECTOR, return_value=conn):
            with patch(_PATCH_SNAPSHOT, return_value=snap):
                with patch(_PATCH_APPEND):
                    rec.run_reconciliation("paper")
        last = rec.get_last_report()
        self.assertIsNotNone(last)
        self.assertIsInstance(last, rec.ReconciliationReport)

    def test_clear_halt(self):
        rec._halted = True
        rec.clear_halt()
        self.assertFalse(rec.is_halted())

    def test_summary_line_pass(self):
        conn = self._mock_connector({"SPY": 10.0})
        snap = self._mock_portfolio({"SPY": 10.0})
        with patch(_PATCH_CONNECTOR, return_value=conn):
            with patch(_PATCH_SNAPSHOT, return_value=snap):
                with patch(_PATCH_APPEND):
                    report = rec.run_reconciliation("paper")
        self.assertIn("PASS", report.summary_line())

    def test_summary_line_fail(self):
        conn = self._mock_connector({"SPY": 10.0})
        snap = self._mock_portfolio({"SPY": 0.0})
        with patch(_PATCH_CONNECTOR, return_value=conn):
            with patch(_PATCH_SNAPSHOT, return_value=snap):
                with patch(_PATCH_APPEND):
                    with patch(_PATCH_ALERTS):
                        report = rec.run_reconciliation("paper")
        self.assertIn("FAIL", report.summary_line())


if __name__ == "__main__":
    unittest.main(verbosity=2)
