# tests/test_belfort_preflight.py
#
# Tests for observability/belfort_summary.py — disk-read bridge.
#
# Run with:
#   python -m unittest tests.test_belfort_preflight -v

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import observability.belfort_summary as obs


class TestReadBelfortPreflight(unittest.TestCase):

    def setUp(self) -> None:
        self._tmpdir = pathlib.Path(tempfile.mkdtemp())
        self._orig_pf   = obs._PREFLIGHT
        self._orig_mode = obs._MODE_FILE
        self._orig_log  = obs._OBS_LOG
        obs._PREFLIGHT = self._tmpdir / "preflight.json"
        obs._MODE_FILE = self._tmpdir / "belfort_mode.json"
        obs._OBS_LOG   = self._tmpdir / "observation_log.jsonl"

    def tearDown(self) -> None:
        obs._PREFLIGHT = self._orig_pf
        obs._MODE_FILE = self._orig_mode
        obs._OBS_LOG   = self._orig_log
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_missing_preflight_returns_safe_default(self) -> None:
        result = obs.read_belfort_preflight()
        self.assertEqual(result["mode"], "observation")
        self.assertEqual(result["readiness_level"], "NOT_READY")
        self.assertEqual(result["data_lane"], "UNKNOWN")

    def test_reads_preflight_from_disk(self) -> None:
        snap = {
            "written_at": "2026-04-11T00:00:00+00:00",
            "mode": "shadow",
            "readiness_level": "PAPER_READY",
            "data_lane": "SIP_CONSOLIDATED",
            "session_type": "regular",
            "observation_ticks_today": 5,
        }
        obs._PREFLIGHT.write_text(json.dumps(snap))
        result = obs.read_belfort_preflight()
        self.assertEqual(result["mode"], "shadow")
        self.assertEqual(result["readiness_level"], "PAPER_READY")

    def test_corrupt_preflight_returns_safe_default(self) -> None:
        obs._PREFLIGHT.write_text("not json{{{{")
        result = obs.read_belfort_preflight()
        self.assertEqual(result["mode"], "observation")
        self.assertEqual(result["readiness_level"], "NOT_READY")

    def test_read_belfort_mode_missing_returns_observation(self) -> None:
        result = obs.read_belfort_mode()
        self.assertEqual(result, "observation")

    def test_read_belfort_mode_from_disk(self) -> None:
        obs._MODE_FILE.write_text(json.dumps({"mode": "paper"}))
        result = obs.read_belfort_mode()
        self.assertEqual(result, "paper")

    def test_read_observation_log_empty(self) -> None:
        result = obs.read_observation_log()
        self.assertEqual(result, [])

    def test_read_observation_log_returns_last_n(self) -> None:
        records = [{"symbol": "SPY", "mid": float(i)} for i in range(30)]
        obs._OBS_LOG.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        result = obs.read_observation_log(n=10)
        self.assertEqual(len(result), 10)
        self.assertEqual(result[-1]["mid"], 29.0)


if __name__ == "__main__":
    unittest.main()
