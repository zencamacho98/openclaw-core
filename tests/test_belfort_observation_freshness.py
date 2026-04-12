# tests/test_belfort_observation_freshness.py
#
# Tests for observation tick freshness wiring (BELFORT-REFLECTION-AND-CONTROL-01).
# Covers:
#   - trading_loop._run_observation_snapshot() silently swallows errors
#   - observability/belfort_summary.read_belfort_freshness_state() derivation
#   - freshness labels under all session/elapsed combinations

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


# ── _run_observation_snapshot ─────────────────────────────────────────────────

class TestRunObservationSnapshot:
    def test_calls_run_observation_tick(self):
        mock_tick = MagicMock(return_value={"ok": True})
        with patch("app.belfort_observer.run_observation_tick", mock_tick):
            from app.trading_loop import _run_observation_snapshot
            _run_observation_snapshot()
        mock_tick.assert_called_once()

    def test_swallows_exceptions_silently(self):
        def _raise():
            raise RuntimeError("boom")

        with patch("app.belfort_observer.run_observation_tick", side_effect=RuntimeError("boom")):
            from app.trading_loop import _run_observation_snapshot
            # Must not raise
            _run_observation_snapshot()


# ── read_belfort_freshness_state — no data ────────────────────────────────────

class TestFreshnessNoData:
    def _make_preflight(self, written_at=None, last_tick_at=None, session_type="regular"):
        return {
            "written_at":    written_at,
            "last_tick_at":  last_tick_at,
            "session_type":  session_type,
        }

    def test_no_written_at_returns_no_data(self):
        from observability.belfort_summary import read_belfort_freshness_state
        pf = self._make_preflight()
        with patch("observability.belfort_summary.read_belfort_preflight", return_value=pf):
            result = read_belfort_freshness_state()
        assert result["freshness"] == "no_data"
        assert result["loop_likely_running"] is False
        assert result["minutes_since_tick"] is None

    def test_no_last_tick_at_returns_no_data(self):
        from observability.belfort_summary import read_belfort_freshness_state
        pf = self._make_preflight(written_at="2026-01-01T00:00:00+00:00")
        with patch("observability.belfort_summary.read_belfort_preflight", return_value=pf):
            result = read_belfort_freshness_state()
        assert result["freshness"] == "no_data"

    def test_bad_timestamp_returns_no_data(self):
        from observability.belfort_summary import read_belfort_freshness_state
        pf = self._make_preflight(written_at="bad", last_tick_at="also-bad")
        with patch("observability.belfort_summary.read_belfort_preflight", return_value=pf):
            result = read_belfort_freshness_state()
        assert result["freshness"] == "no_data"


# ── read_belfort_freshness_state — regular session ────────────────────────────

class TestFreshnessRegularSession:
    def _pf_minutes_ago(self, minutes: int) -> dict:
        tick = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        return {
            "written_at":   tick,
            "last_tick_at": tick,
            "session_type": "regular",
        }

    def test_fresh_within_15_minutes(self):
        from observability.belfort_summary import read_belfort_freshness_state
        pf = self._pf_minutes_ago(5)
        with patch("observability.belfort_summary.read_belfort_preflight", return_value=pf):
            result = read_belfort_freshness_state()
        assert result["freshness"] == "fresh"
        assert result["loop_likely_running"] is True

    def test_stale_between_15_and_60_minutes(self):
        from observability.belfort_summary import read_belfort_freshness_state
        pf = self._pf_minutes_ago(30)
        with patch("observability.belfort_summary.read_belfort_preflight", return_value=pf):
            result = read_belfort_freshness_state()
        assert result["freshness"] == "stale"
        assert result["loop_likely_running"] is False

    def test_very_stale_over_60_minutes(self):
        from observability.belfort_summary import read_belfort_freshness_state
        pf = self._pf_minutes_ago(90)
        with patch("observability.belfort_summary.read_belfort_preflight", return_value=pf):
            result = read_belfort_freshness_state()
        assert result["freshness"] == "very_stale"

    def test_freshness_label_includes_minutes(self):
        from observability.belfort_summary import read_belfort_freshness_state
        pf = self._pf_minutes_ago(8)
        with patch("observability.belfort_summary.read_belfort_preflight", return_value=pf):
            result = read_belfort_freshness_state()
        assert "8" in result["freshness_label"]

    def test_minutes_since_tick_populated(self):
        from observability.belfort_summary import read_belfort_freshness_state
        pf = self._pf_minutes_ago(12)
        with patch("observability.belfort_summary.read_belfort_preflight", return_value=pf):
            result = read_belfort_freshness_state()
        # Allow ±1 minute for execution time
        assert abs(result["minutes_since_tick"] - 12) <= 1


# ── read_belfort_freshness_state — off-hours ──────────────────────────────────

class TestFreshnessOffHours:
    def _pf_minutes_ago(self, minutes: int, session_type: str = "pre_market") -> dict:
        tick = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        return {
            "written_at":   tick,
            "last_tick_at": tick,
            "session_type": session_type,
        }

    def test_off_hours_fresh_within_60_minutes(self):
        from observability.belfort_summary import read_belfort_freshness_state
        pf = self._pf_minutes_ago(45, session_type="pre_market")
        with patch("observability.belfort_summary.read_belfort_preflight", return_value=pf):
            result = read_belfort_freshness_state()
        assert result["freshness"] == "fresh"

    def test_off_hours_stale_over_60_minutes(self):
        from observability.belfort_summary import read_belfort_freshness_state
        pf = self._pf_minutes_ago(75, session_type="closed")
        with patch("observability.belfort_summary.read_belfort_preflight", return_value=pf):
            result = read_belfort_freshness_state()
        assert result["freshness"] == "stale"

    def test_session_type_propagated(self):
        from observability.belfort_summary import read_belfort_freshness_state
        pf = self._pf_minutes_ago(5, session_type="after_hours")
        with patch("observability.belfort_summary.read_belfort_preflight", return_value=pf):
            result = read_belfort_freshness_state()
        assert result["session_type"] == "after_hours"
