"""
tests/test_shadow_runner.py

Unit tests for app/shadow_runner.py.

Covers:
  - record_intent() returns an intent_id string
  - Intent is written to order ledger with environment="shadow"
  - generate_postmortem() returns a PostMortem
  - Post-mortem has at least one line per intent
  - Post-mortem is written to disk
  - shadow_summary() returns expected keys
  - No orders placed (broker connector never called)
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import app.shadow_runner as sr
import app.order_ledger as ledger


class TestRecordIntent(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = pathlib.Path(self._tmpdir.name)
        self._ledger_patcher = patch.object(ledger, "_ORDERS", self._tmp / "orders")
        self._pm_patcher     = patch.object(sr, "_POSTMORTEMS", self._tmp / "postmortems")
        self._ledger_patcher.start()
        self._pm_patcher.start()

    def tearDown(self):
        self._ledger_patcher.stop()
        self._pm_patcher.stop()
        self._tmpdir.cleanup()

    def test_returns_intent_id_string(self):
        intent_id = sr.record_intent("SPY", "buy", qty=10, order_type="market")
        self.assertIsInstance(intent_id, str)
        self.assertGreater(len(intent_id), 0)

    def test_intent_written_to_ledger(self):
        sr.record_intent("SPY", "buy", qty=10, order_type="market", rationale="test")
        records = ledger.replay(environment="shadow")
        self.assertGreater(len(records), 0)
        self.assertEqual(records[0]["event_type"], "intent")

    def test_intent_has_shadow_environment(self):
        sr.record_intent("AAPL", "sell", qty=5, order_type="limit")
        records = ledger.replay(environment="shadow")
        self.assertTrue(all(r["environment"] == "shadow" for r in records))

    def test_broker_never_called(self):
        """Shadow mode must not place orders via broker connector."""
        mock_connector = MagicMock()
        with patch("app.broker_connector.get_connector", return_value=mock_connector):
            sr.record_intent("SPY", "buy", qty=10, order_type="market")
        mock_connector.place_order.assert_not_called()

    def test_multiple_intents_different_ids(self):
        id1 = sr.record_intent("SPY",  "buy",  qty=10, order_type="market")
        id2 = sr.record_intent("AAPL", "sell", qty=5,  order_type="limit")
        self.assertNotEqual(id1, id2)


class TestPostMortem(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = pathlib.Path(self._tmpdir.name)
        self._ledger_patcher = patch.object(ledger, "_ORDERS", self._tmp / "orders")
        self._pm_patcher     = patch.object(sr, "_POSTMORTEMS", self._tmp / "postmortems")
        self._ledger_patcher.start()
        self._pm_patcher.start()

    def tearDown(self):
        self._ledger_patcher.stop()
        self._pm_patcher.stop()
        self._tmpdir.cleanup()

    def test_postmortem_returns_postmortem(self):
        sr.record_intent("SPY", "buy", qty=10, order_type="market")
        pm = sr.generate_postmortem()
        self.assertIsInstance(pm, sr.PostMortem)

    def test_postmortem_has_intent_count(self):
        sr.record_intent("SPY",  "buy",  qty=10, order_type="market")
        sr.record_intent("AAPL", "sell", qty=5,  order_type="limit")
        pm = sr.generate_postmortem()
        self.assertEqual(pm.intents, 2)

    def test_postmortem_lines_equal_intent_count(self):
        sr.record_intent("SPY", "buy", qty=10, order_type="market")
        pm = sr.generate_postmortem()
        self.assertEqual(len(pm.completed_lines), pm.intents)

    def test_postmortem_written_to_disk(self):
        from datetime import date
        sr.record_intent("SPY", "buy", qty=10, order_type="market")
        sr.generate_postmortem()
        today = date.today().isoformat()
        f = self._tmp / "postmortems" / f"{today}.json"
        self.assertTrue(f.exists())

    def test_postmortem_to_dict_has_keys(self):
        sr.record_intent("SPY", "buy", qty=10, order_type="market")
        pm = sr.generate_postmortem()
        d  = pm.to_dict()
        for key in ("date", "intents", "summary", "lines"):
            self.assertIn(key, d)


class TestShadowSummary(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = pathlib.Path(self._tmpdir.name)
        self._ledger_patcher = patch.object(ledger, "_ORDERS", self._tmp / "orders")
        self._pm_patcher     = patch.object(sr, "_POSTMORTEMS", self._tmp / "postmortems")
        self._ledger_patcher.start()
        self._pm_patcher.start()

    def tearDown(self):
        self._ledger_patcher.stop()
        self._pm_patcher.stop()
        self._tmpdir.cleanup()

    def test_summary_has_required_keys(self):
        summary = sr.shadow_summary()
        for key in ("today_intents", "postmortems_total", "today_postmortem", "today"):
            self.assertIn(key, summary)

    def test_summary_counts_today_intents(self):
        sr.record_intent("SPY", "buy", qty=10, order_type="market")
        sr.record_intent("SPY", "buy", qty=5,  order_type="market")
        summary = sr.shadow_summary()
        self.assertEqual(summary["today_intents"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
