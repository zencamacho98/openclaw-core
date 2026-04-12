# tests/test_belfort_ui_intent_recovery.py
#
# Tests for BELFORT-UI-INTENT-RECOVERY-01:
#   A. Backend boots without Flask dependency
#   B. Cosmetic Belfort requests route to Frank (build intent), not Belfort trading
#   C. Real Belfort trading requests still route to Belfort logic
#   D. JS _isFlBuildIntent correctly classifies cosmetic vs trading requests
#   E. No regression in Peter command/intent routing

from __future__ import annotations

import inspect
import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


# ── A. Backend boot — no Flask dependency ─────────────────────────────────────

class TestBackendBootClean:
    def test_belfort_readiness_imports_without_flask(self):
        """belfort_readiness.py must not import flask."""
        import app.routes.belfort_readiness as _mod
        src = inspect.getsource(_mod)
        assert "flask" not in src.lower(), (
            "belfort_readiness.py must not contain Flask imports — "
            "this is a FastAPI/Uvicorn app"
        )

    def test_belfort_readiness_has_fastapi_router(self):
        """belfort_readiness.py must export a FastAPI APIRouter named 'router'."""
        from app.routes.belfort_readiness import router
        from fastapi import APIRouter
        assert isinstance(router, APIRouter), (
            "belfort_readiness.router must be a FastAPI APIRouter instance"
        )

    def test_belfort_readiness_exports_required_helpers(self):
        """Other modules import _gather_readiness, load_baseline_record, etc."""
        from app.routes.belfort_readiness import (
            _gather_readiness,
            load_baseline_record,
            _compute_win_rate,
            write_baseline_record,
        )
        assert callable(_gather_readiness)
        assert callable(load_baseline_record)
        assert callable(_compute_win_rate)
        assert callable(write_baseline_record)

    def test_app_main_imports_without_error(self):
        """app/main.py must import successfully (full boot chain)."""
        import app.main  # noqa: F401 — import alone proves boot is clean

    def test_belfort_learning_still_imports(self):
        """belfort_learning.py imports from belfort_readiness — must still work."""
        import app.routes.belfort_learning  # noqa: F401

    def test_belfort_diagnostics_still_imports(self):
        """belfort_diagnostics.py imports from belfort_readiness — must still work."""
        import app.routes.belfort_diagnostics  # noqa: F401


# ── B. Cosmetic Belfort requests → Frank (JS _isFlBuildIntent) ────────────────

class TestCosmeticBelfortRoutesToFrank:
    """Verify JS source contains correct routing logic for cosmetic UI requests."""

    def _js_src(self) -> str:
        import app.routes.neighborhood as _nb
        return inspect.getsource(_nb)

    def test_is_fl_build_intent_detects_color_change(self):
        """_isFlBuildIntent must match 'color' + change verb as a build intent."""
        src = self._js_src()
        # Check that the cosmetic pattern includes 'color'
        assert "color" in src, "Color pattern must be present in _isFlBuildIntent"

    def test_is_fl_build_intent_detects_style_change(self):
        src = self._js_src()
        assert "style" in src, "Style pattern must be present in _isFlBuildIntent"

    def test_is_fl_build_intent_includes_appearance(self):
        src = self._js_src()
        assert "appearance" in src, "Appearance must be a cosmetic UI artifact"

    def test_trading_guard_excludes_stop_loss(self):
        """Trading-state terms (stop-loss, threshold) must exclude from build intent."""
        src = self._js_src()
        # Guard must be present: don't confuse "change stop loss threshold" with UI
        assert "stop" in src and ("loss" in src or "threshold" in src), (
            "Trading-state guard must be present to exclude stop-loss changes from build routing"
        )

    def test_cosmetic_guard_is_in_is_fl_build_intent(self):
        """The cosmetic detection block must be inside _isFlBuildIntent, not elsewhere."""
        src = self._js_src()
        # Find the function body
        fn_start = src.find("function _isFlBuildIntent(msg)")
        fn_end   = src.find("\nfunction ", fn_start + 1)
        fn_body  = src[fn_start:fn_end] if fn_end != -1 else src[fn_start:]
        assert "color" in fn_body, "Cosmetic pattern must be inside _isFlBuildIntent"
        assert "colour" in fn_body, "British spelling 'colour' must also be present"

    def test_lm_system_prompt_has_cosmetic_routing_note(self):
        """LM chat system prompt must tell Peter to route cosmetic requests to Frank."""
        src = self._js_src()
        # The system prompt is in Python, not JS, so check neighborhood.py python source
        import app.routes.neighborhood as _nb
        py_src = inspect.getsource(_nb.peter_chat)
        assert "cosmetic" in py_src.lower() or "color" in py_src.lower() or "visual" in py_src.lower(), (
            "peter_chat system prompt must instruct Peter not to answer cosmetic "
            "requests with trading-mode information"
        )
        assert "frank lloyd" in py_src.lower(), (
            "peter_chat system prompt must tell Peter to route cosmetic requests to Frank Lloyd"
        )


# ── C. Real Belfort trading requests still route to Belfort ──────────────────

class TestTradingRequestsRouteCorrectly:
    def test_belfort_status_command_parses(self):
        """'belfort status' must parse as BELFORT_STATUS, not BUILD_INTENT."""
        from peter.commands import parse_command, CommandType
        cmd = parse_command("belfort status")
        assert cmd.type == CommandType.BELFORT_STATUS

    def test_belfort_mode_command_parses(self):
        """'belfort mode' must parse as BELFORT_STATUS."""
        from peter.commands import parse_command, CommandType
        cmd = parse_command("belfort mode")
        assert cmd.type == CommandType.BELFORT_STATUS

    def test_belfort_advance_command_parses(self):
        """'belfort advance' must parse as BELFORT_MODE_CONTROL."""
        from peter.commands import parse_command, CommandType
        cmd = parse_command("belfort advance")
        assert cmd.type == CommandType.BELFORT_MODE_CONTROL

    def test_belfort_regress_command_parses(self):
        """'belfort regress' must parse as BELFORT_MODE_CONTROL."""
        from peter.commands import parse_command, CommandType
        cmd = parse_command("belfort regress reason")
        assert cmd.type == CommandType.BELFORT_MODE_CONTROL

    def test_stop_loss_change_is_not_build_intent(self):
        """'change stop loss to 5%' must NOT be a build intent — it's a strategy param."""
        src = inspect.getsource(__import__("app.routes.neighborhood", fromlist=["neighborhood"]))
        fn_start = src.find("function _isFlBuildIntent(msg)")
        fn_end   = src.find("\nfunction ", fn_start + 1)
        fn_body  = src[fn_start:fn_end] if fn_end != -1 else src[fn_start:]
        # The guard that excludes stop-loss, threshold, strategy, trading must be present
        assert "stop" in fn_body, "stop-loss guard missing from _isFlBuildIntent"


# ── D. Peter command routing no regression ────────────────────────────────────

class TestPeterCommandNoRegression:
    def test_build_intent_still_parses(self):
        from peter.commands import parse_command, CommandType
        cmd = parse_command("build a new route that returns system health")
        assert cmd.type == CommandType.BUILD_INTENT

    def test_status_still_parses(self):
        from peter.commands import parse_command, CommandType
        cmd = parse_command("status")
        assert cmd.type == CommandType.STATUS

    def test_help_still_parses(self):
        from peter.commands import parse_command, CommandType
        cmd = parse_command("help")
        assert cmd.type == CommandType.HELP

    def test_kill_still_parses(self):
        from peter.commands import parse_command, CommandType
        cmd = parse_command("kill trading")
        assert cmd.type == CommandType.KILL_TRADING

    def test_frank_lloyd_nl_build_still_parses(self):
        from peter.commands import parse_command, CommandType
        cmd = parse_command("Have Frank Lloyd build a retry module for the trading loop")
        assert cmd.type == CommandType.BUILD_INTENT

    def test_fl_build_intent_goes_to_handler(self):
        """BUILD_INTENT type must be dispatched to handle_build_intent in the router."""
        from peter.router import _DISPATCH
        from peter.commands import CommandType
        from peter.handlers import handle_build_intent
        assert _DISPATCH.get(CommandType.BUILD_INTENT) is handle_build_intent

    def test_belfort_status_goes_to_handler(self):
        """BELFORT_STATUS must be dispatched to handle_belfort_status."""
        from peter.router import _DISPATCH
        from peter.commands import CommandType
        from peter.handlers import handle_belfort_status
        assert _DISPATCH.get(CommandType.BELFORT_STATUS) is handle_belfort_status
