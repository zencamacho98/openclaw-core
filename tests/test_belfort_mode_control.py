# tests/test_belfort_mode_control.py
#
# Tests for Peter's belfort mode control command (BELFORT-REFLECTION-AND-CONTROL-01).
# Covers:
#   - Command parse rules (advance / regress / set)
#   - handle_belfort_mode_control() behavior: advance, regress, set
#   - Failure contract: on failure previous_mode is NOT shown as pre-transition value
#   - LIVE mode blocked via command
#   - IEX cap note on success when readiness == OBSERVATION_ONLY

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ── Parse rules ───────────────────────────────────────────────────────────────

class TestBelfortModeControlParse:
    def _parse(self, text: str):
        from peter.commands import parse_command
        return parse_command(text)

    def test_advance_parses_to_mode_control(self):
        cmd = self._parse("belfort advance")
        from peter.commands import CommandType
        assert cmd.type == CommandType.BELFORT_MODE_CONTROL
        assert cmd.args["action"] == "advance"

    def test_advance_with_reason(self):
        cmd = self._parse("belfort advance because shadow testing done")
        assert cmd.args["action"] == "advance"
        assert "shadow testing done" in cmd.args["reason"]

    def test_regress_parses_to_mode_control(self):
        cmd = self._parse("belfort regress")
        from peter.commands import CommandType
        assert cmd.type == CommandType.BELFORT_MODE_CONTROL
        assert cmd.args["action"] == "regress"

    def test_regress_with_reason(self):
        cmd = self._parse("belfort regress because something went wrong")
        assert cmd.args["action"] == "regress"
        assert "something" in cmd.args["reason"]

    def test_set_shadow_parses_correctly(self):
        cmd = self._parse("belfort set shadow")
        from peter.commands import CommandType
        assert cmd.type == CommandType.BELFORT_MODE_CONTROL
        assert cmd.args["action"] == "set"
        assert cmd.args["target_mode"] == "shadow"

    def test_set_observation_parses_correctly(self):
        cmd = self._parse("belfort set observation")
        assert cmd.args["target_mode"] == "observation"

    def test_set_paper_parses_correctly(self):
        cmd = self._parse("belfort set paper")
        assert cmd.args["target_mode"] == "paper"


# ── handle_belfort_mode_control — advance ─────────────────────────────────────

class TestHandleBelfortModeControlAdvance:
    def _make_command(self, action: str, reason: str = "", target_mode: str = ""):
        from peter.commands import Command, CommandType
        return Command(
            type=CommandType.BELFORT_MODE_CONTROL,
            args={"action": action, "reason": reason, "target_mode": target_mode},
            transport="cli",
            operator_id="test",
            raw_text="",
        )

    def _ok_result(self, prev: str, new: str) -> dict:
        return {"ok": True, "mode": new, "previous_mode": prev, "error": None}

    def _fail_result(self, cur: str, msg: str) -> dict:
        return {"ok": False, "mode": cur, "previous_mode": cur, "error": msg}

    def test_advance_from_observation_succeeds(self):
        from peter.handlers import handle_belfort_mode_control
        with (
            patch("observability.belfort_summary.read_belfort_mode", return_value="observation"),
            patch("observability.belfort_summary.compute_next_belfort_mode", return_value="shadow"),
            patch("observability.belfort_summary.apply_belfort_mode_transition",
                  return_value=self._ok_result("observation", "shadow")),
            patch("observability.belfort_summary.read_belfort_preflight",
                  return_value={"readiness_level": "PAPER_READY"}),
        ):
            r = handle_belfort_mode_control(self._make_command("advance"))
        assert r.ok is True
        assert "observation" in r.summary
        assert "shadow" in r.summary
        assert r.metrics["previous_mode"] == "observation"
        assert r.metrics["mode"] == "shadow"

    def test_advance_at_paper_returns_not_ok(self):
        from peter.handlers import handle_belfort_mode_control
        with (
            patch("observability.belfort_summary.read_belfort_mode", return_value="paper"),
            patch("observability.belfort_summary.compute_next_belfort_mode", return_value=None),
        ):
            r = handle_belfort_mode_control(self._make_command("advance"))
        assert r.ok is False
        assert "paper" in r.summary.lower() or "cannot advance" in r.summary.lower()

    def test_advance_failure_does_not_surface_previous_mode(self):
        """On failure, previous_mode == mode == current. Do not present it as pre-transition."""
        from peter.handlers import handle_belfort_mode_control
        with (
            patch("observability.belfort_summary.read_belfort_mode", return_value="observation"),
            patch("observability.belfort_summary.compute_next_belfort_mode", return_value="shadow"),
            patch("observability.belfort_summary.apply_belfort_mode_transition",
                  return_value=self._fail_result("observation", "gate condition not met")),
            patch("observability.belfort_summary.read_belfort_preflight",
                  return_value={"readiness_level": "NOT_READY"}),
        ):
            r = handle_belfort_mode_control(self._make_command("advance"))
        assert r.ok is False
        # metrics must NOT contain previous_mode on failure (it would be misleading)
        assert "previous_mode" not in r.metrics

    def test_advance_with_iex_cap_adds_note(self):
        """On success, if readiness == OBSERVATION_ONLY and mode != observation, add note."""
        from peter.handlers import handle_belfort_mode_control
        with (
            patch("observability.belfort_summary.read_belfort_mode", return_value="observation"),
            patch("observability.belfort_summary.compute_next_belfort_mode", return_value="shadow"),
            patch("observability.belfort_summary.apply_belfort_mode_transition",
                  return_value=self._ok_result("observation", "shadow")),
            patch("observability.belfort_summary.read_belfort_preflight",
                  return_value={"readiness_level": "OBSERVATION_ONLY"}),
        ):
            r = handle_belfort_mode_control(self._make_command("advance"))
        assert r.ok is True
        assert "IEX" in r.summary or "cap" in r.summary.lower()


# ── handle_belfort_mode_control — regress ─────────────────────────────────────

class TestHandleBelfortModeControlRegress:
    def _make_command(self, action: str = "regress", reason: str = ""):
        from peter.commands import Command, CommandType
        return Command(
            type=CommandType.BELFORT_MODE_CONTROL,
            args={"action": action, "reason": reason, "target_mode": ""},
            transport="cli",
            operator_id="test",
            raw_text="",
        )

    def test_regress_from_shadow_succeeds(self):
        from peter.handlers import handle_belfort_mode_control
        with (
            patch("observability.belfort_summary.read_belfort_mode", return_value="shadow"),
            patch("observability.belfort_summary.compute_prev_belfort_mode", return_value="observation"),
            patch("observability.belfort_summary.apply_belfort_mode_transition",
                  return_value={"ok": True, "mode": "observation", "previous_mode": "shadow", "error": None}),
            patch("observability.belfort_summary.read_belfort_preflight",
                  return_value={"readiness_level": "OBSERVATION_ONLY"}),
        ):
            r = handle_belfort_mode_control(self._make_command())
        assert r.ok is True
        assert r.metrics["previous_mode"] == "shadow"
        assert r.metrics["mode"] == "observation"

    def test_regress_at_observation_returns_not_ok(self):
        from peter.handlers import handle_belfort_mode_control
        with (
            patch("observability.belfort_summary.read_belfort_mode", return_value="observation"),
            patch("observability.belfort_summary.compute_prev_belfort_mode", return_value=None),
        ):
            r = handle_belfort_mode_control(self._make_command())
        assert r.ok is False
        assert "cannot regress" in r.summary.lower() or "bottom" in r.summary.lower()

    def test_regress_calls_transition_with_force_regression_true(self):
        from peter.handlers import handle_belfort_mode_control
        mock_transition = MagicMock(
            return_value={"ok": True, "mode": "observation", "previous_mode": "shadow", "error": None}
        )
        with (
            patch("observability.belfort_summary.read_belfort_mode", return_value="shadow"),
            patch("observability.belfort_summary.compute_prev_belfort_mode", return_value="observation"),
            patch("observability.belfort_summary.apply_belfort_mode_transition", mock_transition),
            patch("observability.belfort_summary.read_belfort_preflight",
                  return_value={"readiness_level": "OBSERVATION_ONLY"}),
        ):
            handle_belfort_mode_control(self._make_command())
        _, kwargs = mock_transition.call_args
        assert kwargs.get("force_regression") is True


# ── handle_belfort_mode_control — set ─────────────────────────────────────────

class TestHandleBelfortModeControlSet:
    def _make_command(self, target: str, reason: str = ""):
        from peter.commands import Command, CommandType
        return Command(
            type=CommandType.BELFORT_MODE_CONTROL,
            args={"action": "set", "reason": reason, "target_mode": target},
            transport="cli",
            operator_id="test",
            raw_text="",
        )

    def test_set_live_is_blocked(self):
        from peter.handlers import handle_belfort_mode_control
        with patch("observability.belfort_summary.read_belfort_mode", return_value="paper"):
            r = handle_belfort_mode_control(self._make_command("live"))
        assert r.ok is False
        assert "live" in r.summary.lower()

    def test_set_unknown_mode_rejected(self):
        from peter.handlers import handle_belfort_mode_control
        with patch("observability.belfort_summary.read_belfort_mode", return_value="observation"):
            r = handle_belfort_mode_control(self._make_command("bogus"))
        assert r.ok is False
        assert "bogus" in r.summary.lower() or "unknown mode" in r.summary.lower()

    def test_set_regression_passes_force_regression_true(self):
        from peter.handlers import handle_belfort_mode_control
        mock_transition = MagicMock(
            return_value={"ok": True, "mode": "observation", "previous_mode": "shadow", "error": None}
        )
        with (
            patch("observability.belfort_summary.read_belfort_mode", return_value="shadow"),
            patch("observability.belfort_summary.apply_belfort_mode_transition", mock_transition),
            patch("observability.belfort_summary.read_belfort_preflight",
                  return_value={"readiness_level": "OBSERVATION_ONLY"}),
        ):
            handle_belfort_mode_control(self._make_command("observation"))
        _, kwargs = mock_transition.call_args
        assert kwargs.get("force_regression") is True

    def test_set_progression_passes_force_regression_false(self):
        from peter.handlers import handle_belfort_mode_control
        mock_transition = MagicMock(
            return_value={"ok": True, "mode": "shadow", "previous_mode": "observation", "error": None}
        )
        with (
            patch("observability.belfort_summary.read_belfort_mode", return_value="observation"),
            patch("observability.belfort_summary.apply_belfort_mode_transition", mock_transition),
            patch("observability.belfort_summary.read_belfort_preflight",
                  return_value={"readiness_level": "PAPER_READY"}),
        ):
            handle_belfort_mode_control(self._make_command("shadow"))
        _, kwargs = mock_transition.call_args
        assert kwargs.get("force_regression") is False


# ── compute_next / compute_prev ───────────────────────────────────────────────

class TestModeOrderHelpers:
    def test_next_from_observation_is_shadow(self):
        from observability.belfort_summary import compute_next_belfort_mode
        assert compute_next_belfort_mode("observation") == "shadow"

    def test_next_from_shadow_is_paper(self):
        from observability.belfort_summary import compute_next_belfort_mode
        assert compute_next_belfort_mode("shadow") == "paper"

    def test_next_from_paper_is_none(self):
        """LIVE is blocked via command."""
        from observability.belfort_summary import compute_next_belfort_mode
        assert compute_next_belfort_mode("paper") is None

    def test_next_from_live_is_none(self):
        from observability.belfort_summary import compute_next_belfort_mode
        assert compute_next_belfort_mode("live") is None

    def test_prev_from_shadow_is_observation(self):
        from observability.belfort_summary import compute_prev_belfort_mode
        assert compute_prev_belfort_mode("shadow") == "observation"

    def test_prev_from_observation_is_none(self):
        from observability.belfort_summary import compute_prev_belfort_mode
        assert compute_prev_belfort_mode("observation") is None

    def test_prev_from_paper_is_shadow(self):
        from observability.belfort_summary import compute_prev_belfort_mode
        assert compute_prev_belfort_mode("paper") == "shadow"

    def test_unknown_mode_returns_none_for_next(self):
        from observability.belfort_summary import compute_next_belfort_mode
        assert compute_next_belfort_mode("bogus") is None
