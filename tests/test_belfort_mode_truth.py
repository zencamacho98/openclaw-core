# tests/test_belfort_mode_truth.py
#
# BELFORT-MODE-TRUTH-01
#
# Verifies that authoritative mode comes from read_belfort_mode() (state file),
# not from the (possibly stale) preflight snapshot.
#
# Covers:
#   A. handle_belfort_status() uses read_belfort_mode(), not pf["mode"]
#   B. _belfort_state() (UI-facing) uses read_belfort_mode(), not pf["mode"]
#   C. Stale preflight does not override current mode in Peter or UI
#   D. Readiness, data_lane, session, freshness still come from preflight
#   E. apply_belfort_mode_transition() syncs preflight on success (Fix B)
#   F. No regression on existing mode-control tests

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_stale_preflight(mode: str = "observation") -> dict:
    """Preflight still showing old mode."""
    return {
        "written_at":              "2026-04-12T09:00:00Z",
        "mode":                    mode,            # stale value
        "broker_environment":      "paper",
        "paper_credentials":       True,
        "data_lane":               "IEX_ONLY",
        "session_type":            "regular",
        "universe":                ["SPY"],
        "readiness_level":         "OBSERVATION_ONLY",
        "can_advance_to":          None,
        "advancement_blocked_by":  "IEX_ONLY data lane",
        "observation_ticks_today": 12,
        "last_tick_at":            "2026-04-12T09:00:00Z",
    }


# ── A: handle_belfort_status uses authoritative mode ─────────────────────────

class TestHandleBelfortStatusModeTruth:
    """
    After a mode transition, handle_belfort_status must report the new mode
    even when the preflight still shows the old one.
    """

    def test_status_reports_new_mode_despite_stale_preflight(self):
        """Preflight says observation; mode state file says shadow → report shadow."""
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        stale_pf = _make_stale_preflight(mode="observation")

        with (
            patch("peter.handlers.read_belfort_preflight", return_value=stale_pf),
            patch("peter.handlers.read_belfort_mode",      return_value="shadow"),
            patch("peter.handlers.read_latest_signal_decision", return_value=None),
            patch("peter.handlers.read_signal_stats_today", return_value={
                "total": 0, "actions": {"buy": 0, "sell": 0, "hold": 0}, "holds": 0, "blocked": 0, "allowed": 0,
            }),
        ):
            resp = handle_belfort_status(parse_command("belfort status"))

        assert resp.ok
        assert resp.metrics["mode"] == "shadow"
        assert "shadow" in resp.summary.lower()
        assert "observation" not in resp.summary.lower().split("readiness")[0]

    def test_status_readiness_still_from_preflight(self):
        """Readiness, data_lane, session are from preflight — not clobbered."""
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        stale_pf = _make_stale_preflight(mode="observation")
        stale_pf["readiness_level"] = "OBSERVATION_ONLY"
        stale_pf["data_lane"]       = "IEX_ONLY"
        stale_pf["session_type"]    = "regular"

        with (
            patch("peter.handlers.read_belfort_preflight", return_value=stale_pf),
            patch("peter.handlers.read_belfort_mode",      return_value="shadow"),
            patch("peter.handlers.read_latest_signal_decision", return_value=None),
            patch("peter.handlers.read_signal_stats_today", return_value={
                "total": 0, "actions": {"buy": 0, "sell": 0, "hold": 0}, "holds": 0, "blocked": 0, "allowed": 0,
            }),
        ):
            resp = handle_belfort_status(parse_command("belfort status"))

        assert resp.metrics["readiness_level"] == "OBSERVATION_ONLY"
        assert resp.metrics["data_lane"]       == "IEX_ONLY"
        assert resp.metrics["session_type"]    == "regular"

    def test_status_mode_observation_when_state_file_says_observation(self):
        """Sanity: when mode state file says observation, report observation."""
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        pf = _make_stale_preflight(mode="shadow")  # preflight says shadow (also stale, wrong direction)

        with (
            patch("peter.handlers.read_belfort_preflight", return_value=pf),
            patch("peter.handlers.read_belfort_mode",      return_value="observation"),
            patch("peter.handlers.read_latest_signal_decision", return_value=None),
            patch("peter.handlers.read_signal_stats_today", return_value={
                "total": 0, "actions": {"buy": 0, "sell": 0, "hold": 0}, "holds": 0, "blocked": 0, "allowed": 0,
            }),
        ):
            resp = handle_belfort_status(parse_command("belfort status"))

        assert resp.metrics["mode"] == "observation"

    def test_status_paper_mode_from_state_file(self):
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        stale_pf = _make_stale_preflight(mode="shadow")

        with (
            patch("peter.handlers.read_belfort_preflight", return_value=stale_pf),
            patch("peter.handlers.read_belfort_mode",      return_value="paper"),
            patch("peter.handlers.read_latest_signal_decision", return_value=None),
            patch("peter.handlers.read_signal_stats_today", return_value={
                "total": 0, "actions": {"buy": 0, "sell": 0, "hold": 0}, "holds": 0, "blocked": 0, "allowed": 0,
            }),
        ):
            resp = handle_belfort_status(parse_command("belfort status"))

        assert resp.metrics["mode"] == "paper"
        assert "paper" in resp.summary.lower()


# ── B: _belfort_state (UI) uses authoritative mode ───────────────────────────

class TestBelfortStateModeTruth:
    """
    UI-facing _belfort_state() must return the authoritative mode,
    not the one embedded in the stale preflight snapshot.
    """

    def _call_belfort_state(self, auth_mode: str, preflight_mode: str = "observation") -> dict:
        from app.routes.neighborhood import _belfort_state

        stale_pf = _make_stale_preflight(mode=preflight_mode)
        fs = {
            "freshness": "stale", "freshness_label": "Stale — last seen 20 min ago",
            "minutes_since_tick": 20, "session_type": "regular", "loop_likely_running": False,
        }

        with (
            patch("observability.belfort_summary.read_belfort_mode",      return_value=auth_mode),
            patch("observability.belfort_summary.read_belfort_preflight",  return_value=stale_pf),
            patch("observability.belfort_summary.read_belfort_freshness_state", return_value=fs),
            patch("observability.belfort_summary.read_latest_signal_decision", return_value=None),
            # Silence the other _belfort_state branches
            patch("observability.agent_state.load_state", side_effect=Exception("skip")),
            patch("app.portfolio.get_snapshot", return_value={}),
            patch("app.portfolio.get_trades",   return_value=[]),
            patch("app.portfolio.positions",    {}, create=True),
            patch("app.trading_loop.get_status", return_value={"running": False, "stop_requested": False}),
        ):
            return _belfort_state()

    def test_ui_mode_from_state_file_not_preflight(self):
        result = self._call_belfort_state(auth_mode="shadow", preflight_mode="observation")
        assert result["belfort_mode"] == "shadow"

    def test_ui_readiness_still_from_preflight(self):
        result = self._call_belfort_state(auth_mode="shadow", preflight_mode="observation")
        assert result["belfort_readiness"] == "OBSERVATION_ONLY"

    def test_ui_data_lane_still_from_preflight(self):
        result = self._call_belfort_state(auth_mode="shadow", preflight_mode="observation")
        assert result["belfort_data_lane"] == "IEX_ONLY"

    def test_ui_paper_mode_from_state_file(self):
        result = self._call_belfort_state(auth_mode="paper", preflight_mode="shadow")
        assert result["belfort_mode"] == "paper"


# ── C: Stale preflight does not override authoritative mode ───────────────────

class TestStalePrefightDoesNotOverrideMode:
    """
    Even when preflight has a wildly different mode value,
    the authoritative source wins.
    """

    def test_shadow_wins_over_observation_preflight(self):
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        with (
            patch("peter.handlers.read_belfort_preflight", return_value=_make_stale_preflight("observation")),
            patch("peter.handlers.read_belfort_mode",      return_value="shadow"),
            patch("peter.handlers.read_latest_signal_decision", return_value=None),
            patch("peter.handlers.read_signal_stats_today", return_value={
                "total": 0, "actions": {"buy": 0, "sell": 0, "hold": 0}, "holds": 0, "blocked": 0, "allowed": 0,
            }),
        ):
            resp = handle_belfort_status(parse_command("belfort status"))

        # Summary must mention shadow, not observation (before readiness)
        summary_before_readiness = resp.summary.split("Current readiness")[0]
        assert "shadow" in summary_before_readiness.lower()
        assert resp.metrics["mode"] == "shadow"

    def test_paper_wins_over_shadow_preflight(self):
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        with (
            patch("peter.handlers.read_belfort_preflight", return_value=_make_stale_preflight("shadow")),
            patch("peter.handlers.read_belfort_mode",      return_value="paper"),
            patch("peter.handlers.read_latest_signal_decision", return_value=None),
            patch("peter.handlers.read_signal_stats_today", return_value={
                "total": 0, "actions": {"buy": 0, "sell": 0, "hold": 0}, "holds": 0, "blocked": 0, "allowed": 0,
            }),
        ):
            resp = handle_belfort_status(parse_command("belfort status"))

        assert resp.metrics["mode"] == "paper"


# ── D: Other preflight fields still come from preflight ──────────────────────

class TestPreflightFieldsStillUsed:
    def test_ticks_today_from_preflight(self):
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        pf = _make_stale_preflight()
        pf["observation_ticks_today"] = 42

        with (
            patch("peter.handlers.read_belfort_preflight", return_value=pf),
            patch("peter.handlers.read_belfort_mode",      return_value="shadow"),
            patch("peter.handlers.read_latest_signal_decision", return_value=None),
            patch("peter.handlers.read_signal_stats_today", return_value={
                "total": 0, "actions": {"buy": 0, "sell": 0, "hold": 0}, "holds": 0, "blocked": 0, "allowed": 0,
            }),
        ):
            resp = handle_belfort_status(parse_command("belfort status"))

        assert resp.metrics["ticks_today"] == 42
        assert "42" in resp.summary

    def test_broker_env_from_preflight(self):
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command

        pf = _make_stale_preflight()
        pf["broker_environment"] = "paper"

        with (
            patch("peter.handlers.read_belfort_preflight", return_value=pf),
            patch("peter.handlers.read_belfort_mode",      return_value="shadow"),
            patch("peter.handlers.read_latest_signal_decision", return_value=None),
            patch("peter.handlers.read_signal_stats_today", return_value={
                "total": 0, "actions": {"buy": 0, "sell": 0, "hold": 0}, "holds": 0, "blocked": 0, "allowed": 0,
            }),
        ):
            resp = handle_belfort_status(parse_command("belfort status"))

        assert resp.metrics["broker_env"] == "paper"


# ── E: apply_belfort_mode_transition syncs preflight on success ──────────────
# set_mode and BelfortMode are local imports inside apply_belfort_mode_transition,
# so they must be patched at the app.belfort_mode module level.

class TestApplyModeTransitionSyncsPreflightOnSuccess:
    def test_successful_transition_triggers_preflight_sync(self):
        from observability.belfort_summary import apply_belfort_mode_transition

        mock_result = {"ok": True, "mode": "shadow", "previous_mode": "observation", "error": None}

        with (
            patch("app.belfort_mode.set_mode",    return_value=mock_result),
            patch("app.belfort_observer.write_preflight_snapshot") as mock_sync,
        ):
            result = apply_belfort_mode_transition("shadow", reason="test advance")

        assert result["ok"] is True
        mock_sync.assert_called_once()

    def test_failed_transition_does_not_sync_preflight(self):
        from observability.belfort_summary import apply_belfort_mode_transition

        mock_result = {"ok": False, "mode": "observation", "previous_mode": "observation", "error": "gate blocked"}

        with (
            patch("app.belfort_mode.set_mode",    return_value=mock_result),
            patch("app.belfort_observer.write_preflight_snapshot") as mock_sync,
        ):
            result = apply_belfort_mode_transition("shadow", reason="should fail")

        assert result["ok"] is False
        mock_sync.assert_not_called()

    def test_preflight_sync_failure_does_not_break_transition(self):
        """Preflight sync failure is non-fatal — the mode transition result is still returned."""
        from observability.belfort_summary import apply_belfort_mode_transition

        mock_result = {"ok": True, "mode": "shadow", "previous_mode": "observation", "error": None}

        with (
            patch("app.belfort_mode.set_mode",    return_value=mock_result),
            patch("app.belfort_observer.write_preflight_snapshot", side_effect=OSError("disk full")),
        ):
            result = apply_belfort_mode_transition("shadow")

        # Transition result is intact despite sync failure
        assert result["ok"] is True
        assert result["mode"] == "shadow"

    def test_invalid_mode_does_not_call_set_mode_or_sync(self):
        from observability.belfort_summary import apply_belfort_mode_transition

        with (
            patch("app.belfort_mode.set_mode")                        as mock_set,
            patch("app.belfort_observer.write_preflight_snapshot")    as mock_sync,
        ):
            result = apply_belfort_mode_transition("nonexistent_mode")

        assert result["ok"] is False
        mock_set.assert_not_called()
        mock_sync.assert_not_called()


# ── F: No regression — read_belfort_mode authoritative reads ─────────────────

class TestReadBelfortModeAuthoritative:
    """
    read_belfort_mode() must always read from the state file,
    not be confused with preflight data.
    """

    def test_read_belfort_mode_from_state_file(self, tmp_path):
        import json, pathlib
        mode_file = tmp_path / "belfort_mode.json"
        mode_file.write_text(json.dumps({"mode": "shadow", "set_at": "2026-04-12T10:00:00Z"}))

        from observability.belfort_summary import read_belfort_mode
        with patch("observability.belfort_summary._MODE_FILE", mode_file):
            assert read_belfort_mode() == "shadow"

    def test_read_belfort_mode_defaults_observation_when_missing(self, tmp_path):
        from observability.belfort_summary import read_belfort_mode
        with patch("observability.belfort_summary._MODE_FILE", tmp_path / "nope.json"):
            assert read_belfort_mode() == "observation"
