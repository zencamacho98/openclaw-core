# tests/test_belfort_mode.py
#
# Tests for app/belfort_mode.py — BelfortMode state machine.
#
# Run with:
#   python -m unittest tests.test_belfort_mode -v

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import app.belfort_mode as bm
from app.belfort_mode import BelfortMode, current_mode, set_mode, can_advance_to


class TestBelfortMode(unittest.TestCase):

    def setUp(self) -> None:
        self._tmpdir = pathlib.Path(tempfile.mkdtemp())
        self._orig_state   = bm._STATE_FILE
        self._orig_journal = bm._JOURNAL
        self._orig_signoff = bm._SIGN_OFF
        bm._STATE_FILE = self._tmpdir / "belfort_mode.json"
        bm._JOURNAL    = self._tmpdir / "mode_journal.jsonl"
        bm._SIGN_OFF   = self._tmpdir / "live_sign_off.json"

    def tearDown(self) -> None:
        bm._STATE_FILE = self._orig_state
        bm._JOURNAL    = self._orig_journal
        bm._SIGN_OFF   = self._orig_signoff
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ── current_mode defaults ────────────────────────────────────────────────

    def test_default_mode_is_observation(self) -> None:
        self.assertEqual(current_mode(), BelfortMode.OBSERVATION)

    def test_reads_mode_from_state_file(self) -> None:
        bm._STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        bm._STATE_FILE.write_text(json.dumps({"mode": "shadow"}))
        self.assertEqual(current_mode(), BelfortMode.SHADOW)

    def test_corrupt_state_file_returns_observation(self) -> None:
        bm._STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        bm._STATE_FILE.write_text("not-json{{{")
        self.assertEqual(current_mode(), BelfortMode.OBSERVATION)

    # ── set_mode transitions ─────────────────────────────────────────────────

    def test_advance_observation_to_shadow(self) -> None:
        result = set_mode(BelfortMode.SHADOW)
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "shadow")

    def test_journal_written_before_state(self) -> None:
        set_mode(BelfortMode.SHADOW)
        lines = bm._JOURNAL.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["event"], "mode_transition")
        self.assertEqual(entry["from_mode"], "observation")
        self.assertEqual(entry["to_mode"], "shadow")

    def test_same_mode_is_ok_noop(self) -> None:
        result = set_mode(BelfortMode.OBSERVATION)
        self.assertTrue(result["ok"])
        # No journal entry for no-op
        self.assertFalse(bm._JOURNAL.exists())

    def test_skip_mode_blocked(self) -> None:
        result = set_mode(BelfortMode.PAPER)
        self.assertFalse(result["ok"])
        self.assertIn("skip", result["error"].lower())

    def test_regression_requires_force(self) -> None:
        set_mode(BelfortMode.SHADOW)
        result = set_mode(BelfortMode.OBSERVATION)
        self.assertFalse(result["ok"])
        self.assertIn("force_regression", result["error"])

    def test_regression_with_force_ok(self) -> None:
        set_mode(BelfortMode.SHADOW)
        result = set_mode(BelfortMode.OBSERVATION, force_regression=True)
        self.assertTrue(result["ok"])
        self.assertEqual(current_mode(), BelfortMode.OBSERVATION)

    def test_live_blocked_without_signoff(self) -> None:
        # Get to paper mode first
        set_mode(BelfortMode.SHADOW)
        set_mode(BelfortMode.PAPER)
        result = set_mode(BelfortMode.LIVE)
        self.assertFalse(result["ok"])
        self.assertIn("sign-off", result["error"].lower())

    def test_live_allowed_with_signoff(self) -> None:
        set_mode(BelfortMode.SHADOW)
        set_mode(BelfortMode.PAPER)
        bm._SIGN_OFF.parent.mkdir(parents=True, exist_ok=True)
        bm._SIGN_OFF.write_text(json.dumps({"approved": True, "approved_by": "operator"}))
        result = set_mode(BelfortMode.LIVE)
        self.assertTrue(result["ok"])

    # ── can_advance_to ───────────────────────────────────────────────────────

    def test_can_advance_to_shadow_from_observation(self) -> None:
        allowed, reason = can_advance_to(BelfortMode.SHADOW)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_cannot_advance_past_current(self) -> None:
        set_mode(BelfortMode.SHADOW)
        allowed, _ = can_advance_to(BelfortMode.OBSERVATION)
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
