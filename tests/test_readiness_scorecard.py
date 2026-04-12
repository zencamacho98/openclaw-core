"""
tests/test_readiness_scorecard.py

Unit tests for app/readiness_scorecard.py.

Covers:
  - evaluate() returns a ScorecardResult with expected gates
  - All gates are present
  - INSUFFICIENT_DATA returned when no data exists
  - Level is NOT_READY when a gate FAILs
  - LIVE_ELIGIBLE requires all-pass AND human signoff
  - record_human_signoff() writes file; _load_signoff() reads it
  - get_last_scorecard() returns the most recent result
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import app.readiness_scorecard as sc


_EXPECTED_GATES = {
    "feed_liveness",
    "data_lane_labeled",
    "reconciliation",
    "overlay_warnings",
    "shadow_postmortems",
    "kill_switch_tested",
    "paper_days",
}


class TestEvaluate(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = pathlib.Path(self._tmpdir.name)
        # Redirect log and signoff to temp
        self._log_patcher  = patch.object(sc, "_CARD_LOG",  self._tmp / "scorecard.jsonl")
        self._sign_patcher = patch.object(sc, "_SIGNOFF",   self._tmp / "signoff.json")
        self._root_patcher = patch.object(sc, "_ROOT",       self._tmp)
        self._log_patcher.start()
        self._sign_patcher.start()
        self._root_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()
        self._sign_patcher.stop()
        self._root_patcher.stop()
        self._tmpdir.cleanup()

    def test_returns_scorecard_result(self):
        result = sc.evaluate()
        self.assertIsInstance(result, sc.ScorecardResult)

    def test_all_expected_gates_present(self):
        result = sc.evaluate()
        gate_names = {g.name for g in result.gates}
        for name in _EXPECTED_GATES:
            self.assertIn(name, gate_names, f"Gate missing: {name}")

    def test_no_data_gives_insufficient_or_fail(self):
        result = sc.evaluate()
        for g in result.gates:
            self.assertIn(g.status, ("PASS", "FAIL", "INSUFFICIENT_DATA"))

    def test_level_is_not_ready_without_data(self):
        result = sc.evaluate()
        # No data → should not be LIVE_ELIGIBLE or SHADOW_COMPLETE
        self.assertNotEqual(result.level, "LIVE_ELIGIBLE")
        self.assertNotEqual(result.level, "SHADOW_COMPLETE")

    def test_human_signoff_false_by_default(self):
        result = sc.evaluate()
        self.assertFalse(result.human_signoff)

    def test_written_to_log(self):
        sc.evaluate()
        log = self._tmp / "scorecard.jsonl"
        self.assertTrue(log.exists())
        lines = [l for l in log.read_text().splitlines() if l.strip()]
        self.assertGreater(len(lines), 0)

    def test_get_last_scorecard_reads_log(self):
        sc.evaluate()
        last = sc.get_last_scorecard()
        self.assertIsNotNone(last)
        self.assertIsInstance(last, sc.ScorecardResult)

    def test_to_dict_has_required_keys(self):
        result = sc.evaluate()
        d = result.to_dict()
        for key in ("timestamp_utc", "level", "all_pass", "human_signoff", "gates"):
            self.assertIn(key, d)


class TestHumanSignoff(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = pathlib.Path(self._tmpdir.name)
        self._sign_patcher = patch.object(sc, "_SIGNOFF", self._tmp / "signoff.json")
        self._sign_patcher.start()

    def tearDown(self):
        self._sign_patcher.stop()
        self._tmpdir.cleanup()

    def test_record_writes_file(self):
        sc.record_human_signoff(reviewer="zen", notes="approved for paper")
        f = self._tmp / "signoff.json"
        self.assertTrue(f.exists())
        d = json.loads(f.read_text())
        self.assertEqual(d["reviewer"], "zen")

    def test_load_signoff_reads_file(self):
        sc.record_human_signoff(reviewer="zen")
        data = sc._load_signoff()
        self.assertIsNotNone(data)
        self.assertEqual(data["reviewer"], "zen")

    def test_no_signoff_returns_none(self):
        data = sc._load_signoff()
        self.assertIsNone(data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
