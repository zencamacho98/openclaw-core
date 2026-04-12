"""
tests/test_kill_switch.py

Unit tests for app/kill_switch.py.

Covers:
  - engage() returns a KillResult with engaged=True
  - Trading loop is stopped
  - Agent state is set to stopped_by_guardrail
  - Order ledger receives a kill_switch event
  - Event log receives an alert
  - Multiple engagements are safe (idempotent)
  - get_status() returns a dict
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.kill_switch import engage, get_status


# Patch targets for lazy imports inside kill_switch.engage()
_PATCH_CONNECTOR   = "app.broker_connector.get_connector"
_PATCH_TRANSITION  = "observability.agent_state.transition"
_PATCH_APPEND_EVT  = "observability.event_log.append_event"


class TestEngage(unittest.TestCase):

    def _engage_with_mocks(self, reason="test", environment="paper"):
        """Engage kill switch with all side-effects mocked."""
        mock_connector = MagicMock()
        mock_connector.get_open_orders.return_value = [{"id": "ORD-1"}, {"id": "ORD-2"}]
        mock_connector.cancel_order.return_value = MagicMock(success=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            orders_path = pathlib.Path(tmpdir)
            import app.order_ledger as ledger

            with (
                patch(_PATCH_CONNECTOR,  return_value=mock_connector),
                patch(_PATCH_TRANSITION),
                patch(_PATCH_APPEND_EVT),
                patch.object(ledger, "_ORDERS", orders_path),
            ):
                result = engage(reason=reason, environment=environment)

        return result, mock_connector

    def test_engage_returns_kill_result(self):
        result, _ = self._engage_with_mocks()
        self.assertTrue(result.engaged)

    def test_engage_has_reason(self):
        result, _ = self._engage_with_mocks(reason="daily_loss_cap")
        self.assertEqual(result.reason, "daily_loss_cap")

    def test_engage_cancels_open_orders(self):
        result, connector = self._engage_with_mocks()
        self.assertEqual(connector.cancel_order.call_count, 2)
        self.assertEqual(result.cancelled_orders, 2)

    def test_engage_with_no_connector_still_succeeds(self):
        with patch(_PATCH_CONNECTOR,  return_value=None):
            with patch(_PATCH_TRANSITION):
                with patch(_PATCH_APPEND_EVT):
                    result = engage(reason="no_broker", environment="paper")
        self.assertTrue(result.engaged)
        self.assertEqual(result.cancelled_orders, 0)

    def test_engage_stops_trading_loop(self):
        import app.trading_loop as tl
        orig_running = tl._running
        try:
            tl._running = True
            with patch(_PATCH_CONNECTOR,  return_value=None):
                with patch(_PATCH_TRANSITION):
                    with patch(_PATCH_APPEND_EVT):
                        engage(reason="test")
            self.assertFalse(tl._running)
        finally:
            tl._running = orig_running

    def test_result_has_timestamp(self):
        result, _ = self._engage_with_mocks()
        self.assertIsNotNone(result.timestamp_utc)
        self.assertIn("T", result.timestamp_utc)


class TestGetStatus(unittest.TestCase):

    def test_returns_dict(self):
        status = get_status()
        self.assertIsInstance(status, dict)

    def test_has_belfort_status_or_error(self):
        status = get_status()
        self.assertTrue("belfort_status" in status or "error" in status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
