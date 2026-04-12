"""
tests/test_order_ledger.py

Unit tests for app/order_ledger.py.

Covers:
  - append() creates a record and returns it
  - Ledger file is append-only (lines grow monotonically)
  - replay() returns sorted events for a date range
  - get_today_count() counts placed events only
  - get_open_orders() excludes final-state events
  - Corrections: corrected=True records exist alongside originals
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import app.order_ledger as ledger


class TestAppend(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._patcher = patch.object(ledger, "_ORDERS", pathlib.Path(self._tmpdir.name))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def test_append_returns_record(self):
        rec = ledger.append("intent", "ORD-1", "paper", symbol="SPY", side="buy", qty=10)
        self.assertEqual(rec["event_type"], "intent")
        self.assertEqual(rec["order_id"], "ORD-1")
        self.assertEqual(rec["symbol"], "SPY")

    def test_file_is_created(self):
        ledger.append("intent", "ORD-1", "paper")
        today = date.today().isoformat()
        path = pathlib.Path(self._tmpdir.name) / f"{today}.jsonl"
        self.assertTrue(path.exists())

    def test_multiple_appends_grow_file(self):
        for i in range(5):
            ledger.append("intent", f"ORD-{i}", "paper")
        today = date.today().isoformat()
        path = pathlib.Path(self._tmpdir.name) / f"{today}.jsonl"
        lines = [l for l in path.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 5)

    def test_records_are_valid_json(self):
        ledger.append("placed", "ORD-X", "paper", symbol="AAPL", qty=100, side="sell")
        today = date.today().isoformat()
        path = pathlib.Path(self._tmpdir.name) / f"{today}.jsonl"
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = json.loads(line)
            self.assertIn("event_type", parsed)

    def test_correction_record_references_original(self):
        ledger.append("intent", "ORD-1", "paper")
        rec = ledger.append(
            "correction", "ORD-1", "paper",
            corrected=True, corrects_record_id="ORD-1"
        )
        self.assertTrue(rec["corrected"])
        self.assertEqual(rec["corrects_record_id"], "ORD-1")


class TestReplay(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._patcher = patch.object(ledger, "_ORDERS", pathlib.Path(self._tmpdir.name))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def test_replay_today_returns_todays_records(self):
        ledger.append("intent", "ORD-1", "paper")
        ledger.append("placed", "ORD-1", "paper")
        records = ledger.replay()
        self.assertGreaterEqual(len(records), 2)

    def test_replay_filters_by_environment(self):
        ledger.append("intent", "ORD-1", "paper")
        ledger.append("intent", "ORD-2", "shadow")
        paper = ledger.replay(environment="paper")
        shadow = ledger.replay(environment="shadow")
        self.assertTrue(all(r["environment"] == "paper"  for r in paper))
        self.assertTrue(all(r["environment"] == "shadow" for r in shadow))

    def test_replay_sorted_by_timestamp(self):
        for i in range(3):
            ledger.append("intent", f"ORD-{i}", "paper")
        records = ledger.replay()
        ts = [r["timestamp_utc"] for r in records]
        self.assertEqual(ts, sorted(ts))


class TestCounts(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._patcher = patch.object(ledger, "_ORDERS", pathlib.Path(self._tmpdir.name))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def test_get_today_count_only_counts_placed(self):
        ledger.append("intent", "ORD-1", "paper")
        ledger.append("placed", "ORD-1", "paper")
        ledger.append("fill",   "ORD-1", "paper")
        self.assertEqual(ledger.get_today_count("paper"), 1)

    def test_get_today_count_is_zero_initially(self):
        self.assertEqual(ledger.get_today_count("paper"), 0)


class TestOpenOrders(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._patcher = patch.object(ledger, "_ORDERS", pathlib.Path(self._tmpdir.name))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def test_open_order_is_placed_not_filled(self):
        ledger.append("intent", "ORD-1", "paper")
        ledger.append("placed", "ORD-1", "paper")
        open_orders = ledger.get_open_orders("paper")
        self.assertEqual(len(open_orders), 1)

    def test_filled_order_not_open(self):
        ledger.append("placed", "ORD-1", "paper")
        ledger.append("fill",   "ORD-1", "paper")
        open_orders = ledger.get_open_orders("paper")
        self.assertEqual(len(open_orders), 0)

    def test_cancelled_order_not_open(self):
        ledger.append("placed", "ORD-1", "paper")
        ledger.append("cancel", "ORD-1", "paper")
        open_orders = ledger.get_open_orders("paper")
        self.assertEqual(len(open_orders), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
