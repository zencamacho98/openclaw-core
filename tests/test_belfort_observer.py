# tests/test_belfort_observer.py
#
# Tests for app/belfort_observer.py — observation runner and preflight snapshot.
#
# Run with:
#   python -m unittest tests.test_belfort_observer -v

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import app.belfort_observer as bo


def _make_fake_quote(
    bid: float = 499.95,
    ask: float = 500.05,
    data_lane: str = "IEX_ONLY",
    session_type: str = "regular",
) -> object:
    class FakeQuote:
        pass
    q = FakeQuote()
    q.symbol       = "SPY"
    q.bid          = bid
    q.ask          = ask
    q.last         = bid
    q.data_lane    = data_lane
    q.session_type = session_type
    return q


def _make_fake_feed_status(data_lane="IEX_ONLY", env="paper", has_creds=True) -> object:
    class FakeFeedStatus:
        pass
    f = FakeFeedStatus()
    f.data_lane        = data_lane
    f.environment      = env
    f.has_credentials  = has_creds
    return f


class TestRunObservationTick(unittest.TestCase):

    def setUp(self) -> None:
        self._tmpdir = pathlib.Path(tempfile.mkdtemp())
        self._orig_obs_log   = bo._OBS_LOG
        self._orig_preflight = bo._PREFLIGHT
        bo._OBS_LOG   = self._tmpdir / "observation_log.jsonl"
        bo._PREFLIGHT = self._tmpdir / "preflight.json"

    def tearDown(self) -> None:
        bo._OBS_LOG   = self._orig_obs_log
        bo._PREFLIGHT = self._orig_preflight
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run_tick(self, bid=499.95, ask=500.05, data_lane="IEX_ONLY"):
        from app.belfort_mode import BelfortMode
        fake_quote = _make_fake_quote(bid=bid, ask=ask, data_lane=data_lane)
        fake_feed  = _make_fake_feed_status(data_lane=data_lane)
        with (
            patch("app.market_data_feed.get_quote",    return_value=fake_quote),
            patch("app.market_data_feed.feed_status",  return_value=fake_feed),
            patch("app.market_time.session_type",      return_value="regular"),
            patch("app.belfort_mode.current_mode",     return_value=BelfortMode.OBSERVATION),
        ):
            return bo.run_observation_tick("SPY")

    def test_tick_returns_ok(self) -> None:
        result = self._run_tick()
        self.assertTrue(result["ok"])

    def test_tick_appends_to_log(self) -> None:
        self._run_tick()
        lines = bo._OBS_LOG.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["symbol"], "SPY")
        self.assertIn("data_lane", rec)
        self.assertIn("bid", rec)
        self.assertIn("ask", rec)

    def test_tick_computes_mid(self) -> None:
        self._run_tick(bid=499.90, ask=500.10)
        rec = json.loads(bo._OBS_LOG.read_text().splitlines()[0])
        self.assertAlmostEqual(rec["mid"], 500.00, places=2)

    def test_tick_writes_preflight(self) -> None:
        self._run_tick()
        self.assertTrue(bo._PREFLIGHT.exists())

    def test_multiple_ticks_append(self) -> None:
        self._run_tick()
        self._run_tick()
        lines = bo._OBS_LOG.read_text().splitlines()
        self.assertEqual(len(lines), 2)

    def test_quote_fetch_failure_returns_error(self) -> None:
        with patch("app.market_data_feed.get_quote", side_effect=RuntimeError("timeout")):
            result = bo.run_observation_tick("SPY")
        self.assertFalse(result["ok"])
        self.assertIn("timeout", result["error"])


class TestWritePreflightSnapshot(unittest.TestCase):

    def setUp(self) -> None:
        self._tmpdir = pathlib.Path(tempfile.mkdtemp())
        self._orig_obs_log   = bo._OBS_LOG
        self._orig_preflight = bo._PREFLIGHT
        bo._OBS_LOG   = self._tmpdir / "observation_log.jsonl"
        bo._PREFLIGHT = self._tmpdir / "preflight.json"

    def tearDown(self) -> None:
        bo._OBS_LOG   = self._orig_obs_log
        bo._PREFLIGHT = self._orig_preflight
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_snapshot(self, data_lane="IEX_ONLY", mode_val="observation"):
        from app.belfort_mode import BelfortMode
        mode = BelfortMode(mode_val)
        fake_feed = _make_fake_feed_status(data_lane=data_lane)
        with (
            patch("app.belfort_mode.current_mode",     return_value=mode),
            patch("app.market_data_feed.feed_status",  return_value=fake_feed),
            patch("app.market_time.session_type",      return_value="regular"),
        ):
            return bo.write_preflight_snapshot()

    def test_snapshot_has_required_fields(self) -> None:
        snap = self._write_snapshot()
        for f in ("written_at", "mode", "broker_environment", "paper_credentials",
                  "data_lane", "session_type", "universe", "readiness_level",
                  "can_advance_to", "advancement_blocked_by",
                  "observation_ticks_today", "last_tick_at"):
            self.assertIn(f, snap, f"Missing required field: {f}")

    def test_iex_caps_readiness_at_observation_only(self) -> None:
        snap = self._write_snapshot(data_lane="IEX_ONLY")
        self.assertEqual(snap["readiness_level"], "OBSERVATION_ONLY")

    def test_snapshot_file_written(self) -> None:
        self._write_snapshot()
        self.assertTrue(bo._PREFLIGHT.exists())

    def test_mode_field_matches_current_mode(self) -> None:
        snap = self._write_snapshot(mode_val="observation")
        self.assertEqual(snap["mode"], "observation")

    def test_universe_is_list(self) -> None:
        snap = self._write_snapshot()
        self.assertIsInstance(snap["universe"], list)
        self.assertGreater(len(snap["universe"]), 0)


if __name__ == "__main__":
    unittest.main()
