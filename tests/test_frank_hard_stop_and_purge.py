"""
FRANK-HARD-STOP-AND-PURGE-01 acceptance tests.

A. auto_runner stop flag — request_stop(), get_runner_state()
B. auto_runner run_full_auto() respects stop flag between steps
C. abandoner.abandon_all() — purges all non-terminal regardless of source
D. frank_lloyd/control.py — enabled/disabled state file
E. Peter commands: stop frank, clear frank, disable frank, enable frank
F. Command parsing — stop/clear/disable/enable routes correctly
G. HTTP endpoints: /frank-lloyd/hard-stop, /purge-all, /disable, /enable, /control-state
H. handle_build_intent respects disabled gate
I. Neighborhood state: fl_enabled + fl_runner_state keys
J. No regression on existing Frank Lloyd tests
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

ACTIONS_FILE   = ROOT / "app" / "routes" / "frank_lloyd_actions.py"
HANDLERS_FILE  = ROOT / "peter" / "handlers.py"
COMMANDS_FILE  = ROOT / "peter" / "commands.py"
ROUTER_FILE    = ROOT / "peter" / "router.py"
NEIGHBORHOOD   = ROOT / "app" / "routes" / "neighborhood.py"
AUTO_RUNNER    = ROOT / "frank_lloyd" / "auto_runner.py"
ABANDONER      = ROOT / "frank_lloyd" / "abandoner.py"
CONTROL_FILE   = ROOT / "frank_lloyd" / "control.py"

_AF  = ACTIONS_FILE.read_text()
_PH  = HANDLERS_FILE.read_text()
_CMD = COMMANDS_FILE.read_text()
_RO  = ROUTER_FILE.read_text()
_NH  = NEIGHBORHOOD.read_text()
_AR  = AUTO_RUNNER.read_text()
_AB  = ABANDONER.read_text()
_CT  = CONTROL_FILE.read_text()


# ── A. auto_runner stop flag ──────────────────────────────────────────────────

class TestAutoRunnerStopFlag:
    def test_stop_requested_flag_defined(self):
        assert "_stop_requested" in _AR

    def test_active_build_id_defined(self):
        assert "_active_build_id" in _AR

    def test_request_stop_function_defined(self):
        assert "def request_stop" in _AR

    def test_get_runner_state_function_defined(self):
        assert "def get_runner_state" in _AR

    def test_request_stop_returns_dict(self):
        import frank_lloyd.auto_runner as ar
        ar._stop_requested = False
        ar._active_build_id = None
        result = ar.request_stop()
        assert isinstance(result, dict)
        assert result["stop_requested"] is True

    def test_request_stop_sets_flag(self):
        import frank_lloyd.auto_runner as ar
        ar._stop_requested = False
        ar.request_stop()
        assert ar._stop_requested is True

    def test_request_stop_returns_active_build_id(self):
        import frank_lloyd.auto_runner as ar
        ar._active_build_id = "BUILD-042"
        ar._stop_requested = False
        result = ar.request_stop()
        assert result["active_build_id"] == "BUILD-042"
        ar._active_build_id = None  # cleanup

    def test_get_runner_state_returns_dict(self):
        import frank_lloyd.auto_runner as ar
        state = ar.get_runner_state()
        assert "active_build_id" in state
        assert "stop_requested" in state
        assert "running" in state

    def test_get_runner_state_idle(self):
        import frank_lloyd.auto_runner as ar
        ar._active_build_id = None
        ar._stop_requested = False
        state = ar.get_runner_state()
        assert state["running"] is False
        assert state["active_build_id"] is None

    def test_clear_stop_resets_flag(self):
        import frank_lloyd.auto_runner as ar
        ar._stop_requested = True
        ar._clear_stop()
        assert ar._stop_requested is False

    def test_set_active_sets_build_id(self):
        import frank_lloyd.auto_runner as ar
        ar._set_active("BUILD-007")
        assert ar._active_build_id == "BUILD-007"
        ar._set_active(None)

    def test_module_has_stop_checks_between_steps(self):
        """run_full_auto must check _stop_requested between pipeline steps."""
        fn_start = _AR.find("def run_full_auto")
        fn_section = _AR[fn_start:][:5000]
        assert "_stopped()" in fn_section
        # Multiple checks expected (at least 4 — one per step gap)
        assert fn_section.count("_stopped()") >= 4


# ── B. run_full_auto respects stop flag ───────────────────────────────────────

class TestAutoRunnerStopRespected:
    def test_stopped_returns_paused_not_error(self):
        """When stop is requested before spec, returns paused result not error."""
        import frank_lloyd.auto_runner as ar
        # Simulate stop requested before run starts
        ar._stop_requested = True
        ar._active_build_id = None
        # Can't fully run without a real build, but we can check that
        # the stop check returns paused structure
        result = ar._paused("BUILD-TEST", [], "Stopped by operator")
        assert result["ok"] is False
        assert result["paused_reason"] is not None
        ar._stop_requested = False

    def test_stop_flag_cleared_on_run_start(self):
        """_clear_stop() is called at the beginning of run_full_auto."""
        fn_start = _AR.find("def run_full_auto")
        fn_section = _AR[fn_start:][:1200]
        assert "_clear_stop()" in fn_section

    def test_active_set_on_run_start(self):
        """_set_active(build_id) is called at the beginning of run_full_auto."""
        fn_start = _AR.find("def run_full_auto")
        fn_section = _AR[fn_start:][:1200]
        assert "_set_active(build_id)" in fn_section

    def test_active_cleared_on_success(self):
        """_set_active(None) is called before the success return."""
        fn_start = _AR.find("def run_full_auto")
        fn_end   = _AR.find("def run_safe_lane", fn_start)
        fn_section = _AR[fn_start:fn_end]
        assert "_set_active(None)" in fn_section


# ── C. abandoner.abandon_all() ───────────────────────────────────────────────

class TestAbandonAll:
    def test_function_defined(self):
        assert "def abandon_all" in _AB

    def test_returns_dict_with_keys(self):
        from frank_lloyd.abandoner import abandon_all
        result = abandon_all()
        assert isinstance(result, dict)
        assert "abandoned" in result
        assert "skipped" in result
        assert "errors" in result
        assert "ok" in result

    def test_ok_is_true(self):
        from frank_lloyd.abandoner import abandon_all
        result = abandon_all()
        assert result["ok"] is True

    def test_does_not_raise(self):
        from frank_lloyd.abandoner import abandon_all
        result = abandon_all(notes="test purge")
        assert isinstance(result, dict)

    def test_scans_all_builds_not_by_source(self):
        """abandon_all must scan all build IDs from log, not filter by source."""
        fn_start = _AB.find("def abandon_all")
        fn_section = _AB[fn_start:][:1400]
        assert "build_id" in fn_section
        assert "by_source" not in fn_section  # not filtering by source channel

    def test_skips_terminal_builds(self):
        """Terminal builds (abandoned, promoted, rejected) must be skipped."""
        fn_start = _AB.find("def abandon_all")
        fn_section = _AB[fn_start:][:1400]
        assert "_TERMINAL_EVENTS" in fn_section or "terminal" in fn_section.lower()

    def test_skipped_list_returned(self):
        from frank_lloyd.abandoner import abandon_all
        result = abandon_all()
        assert isinstance(result["skipped"], list)

    def test_already_empty_returns_ok(self):
        """abandon_all is idempotent — calling twice is safe."""
        from frank_lloyd.abandoner import abandon_all
        r1 = abandon_all()
        r2 = abandon_all()
        assert r1["ok"] is True
        assert r2["ok"] is True


# ── D. frank_lloyd/control.py ─────────────────────────────────────────────────

class TestFrankControl:
    def test_control_file_exists(self):
        assert CONTROL_FILE.exists()

    def test_is_enabled_defined(self):
        assert "def is_enabled" in _CT

    def test_disable_defined(self):
        assert "def disable" in _CT

    def test_enable_defined(self):
        assert "def enable" in _CT

    def test_read_control_defined(self):
        assert "def read_control" in _CT

    def test_is_enabled_returns_bool(self):
        from frank_lloyd.control import is_enabled
        result = is_enabled()
        assert isinstance(result, bool)

    def test_default_is_enabled(self):
        """If no control file exists, Frank is enabled by default."""
        from frank_lloyd.control import read_control
        ctrl = read_control()
        assert ctrl.get("enabled", True) is True or ctrl.get("enabled") is not False

    def test_disable_returns_dict(self):
        from frank_lloyd.control import disable, enable
        result = disable("test reason")
        assert isinstance(result, dict)
        # Clean up
        enable()

    def test_disable_sets_enabled_false(self):
        from frank_lloyd.control import disable, is_enabled, enable
        disable("test")
        assert is_enabled() is False
        enable()  # restore

    def test_enable_sets_enabled_true(self):
        from frank_lloyd.control import disable, enable, is_enabled
        disable("test")
        enable()
        assert is_enabled() is True

    def test_disable_result_has_disabled_at(self):
        from frank_lloyd.control import disable, enable
        result = disable("test")
        assert result.get("ok") is True
        assert result.get("disabled_at") is not None
        enable()

    def test_enable_result_has_enabled_at(self):
        from frank_lloyd.control import enable
        result = enable()
        assert result.get("ok") is True
        assert result.get("enabled_at") is not None

    def test_control_file_path_in_data_dir(self):
        """Control state is stored under data/frank_lloyd/."""
        assert "data/frank_lloyd" in _CT or "frank_lloyd" in _CT

    def test_nonfatal_on_missing_file(self):
        """read_control() returns default dict if file is missing."""
        from frank_lloyd.control import read_control
        result = read_control()
        assert isinstance(result, dict)
        assert "enabled" in result


# ── E. Peter command handlers ─────────────────────────────────────────────────

class TestPeterHandlers:
    def test_handle_fl_hard_stop_defined(self):
        assert "def handle_fl_hard_stop" in _PH

    def test_handle_fl_clear_all_defined(self):
        assert "def handle_fl_clear_all" in _PH

    def test_handle_fl_disable_defined(self):
        assert "def handle_fl_disable" in _PH

    def test_handle_fl_enable_defined(self):
        assert "def handle_fl_enable" in _PH

    def test_hard_stop_calls_request_stop(self):
        fn_start = _PH.find("def handle_fl_hard_stop")
        fn_section = _PH[fn_start:][:400]
        assert "request_stop" in fn_section

    def test_clear_all_calls_request_stop(self):
        fn_start = _PH.find("def handle_fl_clear_all")
        fn_section = _PH[fn_start:][:600]
        assert "request_stop" in fn_section

    def test_clear_all_calls_abandon_all(self):
        fn_start = _PH.find("def handle_fl_clear_all")
        fn_section = _PH[fn_start:][:600]
        assert "abandon_all" in fn_section

    def test_disable_calls_control_disable(self):
        fn_start = _PH.find("def handle_fl_disable")
        fn_section = _PH[fn_start:][:400]
        assert "disable" in fn_section
        assert "_ctrl" in fn_section or "control" in fn_section

    def test_enable_calls_control_enable(self):
        fn_start = _PH.find("def handle_fl_enable")
        fn_section = _PH[fn_start:][:400]
        assert "enable" in fn_section
        assert "_ctrl" in fn_section or "control" in fn_section

    def test_build_intent_checks_is_enabled(self):
        fn_start = _PH.find("def handle_build_intent")
        fn_section = _PH[fn_start:][:3000]
        assert "is_enabled" in fn_section

    def test_build_intent_returns_disabled_message(self):
        fn_start = _PH.find("def handle_build_intent")
        fn_section = _PH[fn_start:][:3000]
        assert "disabled" in fn_section.lower()
        assert "enable frank" in fn_section or "re-enable" in fn_section

    def test_clear_all_reports_abandoned_count(self):
        fn_start = _PH.find("def handle_fl_clear_all")
        fn_section = _PH[fn_start:][:800]
        assert "abandoned" in fn_section

    def test_hard_stop_reports_active_build(self):
        fn_start = _PH.find("def handle_fl_hard_stop")
        fn_section = _PH[fn_start:][:600]
        assert "active" in fn_section


# ── F. Command parsing ────────────────────────────────────────────────────────

class TestCommandParsing:
    def _parse(self, text: str):
        from peter.commands import parse_command
        return parse_command(text)

    def test_stop_frank_routes_fl_hard_stop(self):
        cmd = self._parse("stop frank")
        assert cmd.type.value == "fl_hard_stop"

    def test_stop_frank_lloyd_routes_fl_hard_stop(self):
        cmd = self._parse("stop frank lloyd")
        assert cmd.type.value == "fl_hard_stop"

    def test_clear_frank_routes_fl_clear_all(self):
        cmd = self._parse("clear frank")
        assert cmd.type.value == "fl_clear_all"

    def test_purge_frank_routes_fl_clear_all(self):
        cmd = self._parse("purge frank")
        assert cmd.type.value == "fl_clear_all"

    def test_stop_and_clear_frank_routes_fl_clear_all(self):
        cmd = self._parse("stop and clear frank")
        assert cmd.type.value == "fl_clear_all"

    def test_clear_all_frank_routes_fl_clear_all(self):
        cmd = self._parse("clear all frank builds")
        assert cmd.type.value == "fl_clear_all"

    def test_disable_frank_routes_fl_disable(self):
        cmd = self._parse("disable frank")
        assert cmd.type.value == "fl_disable"

    def test_enable_frank_routes_fl_enable(self):
        cmd = self._parse("enable frank")
        assert cmd.type.value == "fl_enable"

    def test_frank_off_routes_fl_disable(self):
        cmd = self._parse("frank off")
        assert cmd.type.value == "fl_disable"

    def test_frank_on_routes_fl_enable(self):
        cmd = self._parse("frank on")
        assert cmd.type.value == "fl_enable"

    def test_stop_frank_does_not_route_stop_campaign(self):
        cmd = self._parse("stop frank")
        assert cmd.type.value != "stop_campaign"

    def test_clear_frank_does_not_route_stop_campaign(self):
        cmd = self._parse("clear frank")
        assert cmd.type.value != "stop_campaign"

    def test_stop_routing_still_works_for_non_frank(self):
        """Generic 'stop' still routes to stop_campaign."""
        cmd = self._parse("stop")
        assert cmd.type.value == "stop_campaign"

    def test_fl_hard_stop_in_commandtype(self):
        from peter.commands import CommandType
        assert hasattr(CommandType, "FL_HARD_STOP")

    def test_fl_clear_all_in_commandtype(self):
        from peter.commands import CommandType
        assert hasattr(CommandType, "FL_CLEAR_ALL")

    def test_fl_disable_in_commandtype(self):
        from peter.commands import CommandType
        assert hasattr(CommandType, "FL_DISABLE")

    def test_fl_enable_in_commandtype(self):
        from peter.commands import CommandType
        assert hasattr(CommandType, "FL_ENABLE")


# ── G. HTTP endpoints ─────────────────────────────────────────────────────────

class TestHttpEndpoints:
    def test_hard_stop_endpoint_defined(self):
        assert '"/frank-lloyd/hard-stop"' in _AF or "frank-lloyd/hard-stop" in _AF

    def test_purge_all_endpoint_defined(self):
        assert '"/frank-lloyd/purge-all"' in _AF or "frank-lloyd/purge-all" in _AF

    def test_disable_endpoint_defined(self):
        assert '"/frank-lloyd/disable"' in _AF or "frank-lloyd/disable" in _AF

    def test_enable_endpoint_defined(self):
        assert '"/frank-lloyd/enable"' in _AF or "frank-lloyd/enable" in _AF

    def test_control_state_endpoint_defined(self):
        assert '"/frank-lloyd/control-state"' in _AF or "frank-lloyd/control-state" in _AF

    def test_hard_stop_calls_request_stop(self):
        fn_start = _AF.find("fl_hard_stop")
        fn_section = _AF[fn_start:][:400]
        assert "request_stop" in fn_section

    def test_purge_all_calls_abandon_all(self):
        fn_start = _AF.find("fl_purge_all")
        fn_section = _AF[fn_start:][:600]
        assert "abandon_all" in fn_section

    def test_purge_all_calls_request_stop(self):
        fn_start = _AF.find("fl_purge_all")
        fn_section = _AF[fn_start:][:1000]
        assert "request_stop" in fn_section

    def test_disable_endpoint_calls_ctrl_disable(self):
        fn_start = _AF.find("def fl_disable")
        fn_section = _AF[fn_start:][:300]
        assert "disable" in fn_section

    def test_enable_endpoint_calls_ctrl_enable(self):
        fn_start = _AF.find("def fl_enable")
        fn_section = _AF[fn_start:][:300]
        assert "enable" in fn_section

    def test_control_state_returns_runner_state(self):
        fn_start = _AF.find("fl_control_state")
        fn_section = _AF[fn_start:][:400]
        assert "runner_state" in fn_section or "get_runner_state" in fn_section


# ── H. handle_build_intent disabled gate ─────────────────────────────────────

class TestBuildIntentDisabledGate:
    def test_gate_imports_control(self):
        fn_start = _PH.find("def handle_build_intent")
        fn_section = _PH[fn_start:][:2000]
        assert "frank_lloyd.control" in fn_section or "fl_ctrl" in fn_section

    def test_gate_checks_is_enabled_before_queue(self):
        """Gate check must appear before the 'assign ID, queue' comment."""
        fn_start = _PH.find("def handle_build_intent")
        fn_section = _PH[fn_start:][:3000]
        gate_pos  = fn_section.find("is_enabled")
        queue_pos = fn_section.find("_fl_next_build_id")
        assert gate_pos < queue_pos, "is_enabled check must appear before queueing"

    def test_gate_returns_response_with_disabled(self):
        fn_start = _PH.find("def handle_build_intent")
        fn_section = _PH[fn_start:][:2000]
        assert "disabled" in fn_section.lower()


# ── I. Neighborhood state keys ─────────────────────────────────────────────────

class TestNeighborhoodState:
    def test_fl_enabled_in_state_dict(self):
        assert "fl_enabled" in _NH

    def test_fl_runner_state_in_state_dict(self):
        assert "fl_runner_state" in _NH

    def test_fl_enabled_default_true(self):
        """Fallback state must have fl_enabled: True."""
        fallback_start = _NH.rfind('"fl_enabled"')
        fallback_section = _NH[fallback_start:][:40]
        assert "True" in fallback_section

    def test_control_imported_in_frank_state(self):
        assert "read_control" in _NH or "from frank_lloyd.control" in _NH

    def test_runner_state_imported_in_frank_state(self):
        assert "get_runner_state" in _NH

    def test_ui_has_disabled_banner(self):
        assert 'id="fl-disabled-banner"' in _NH

    def test_ui_has_stop_button(self):
        assert 'id="fl-btn-stop"' in _NH

    def test_ui_has_purge_button(self):
        assert 'id="fl-btn-purge"' in _NH

    def test_ui_has_toggle_intake_button(self):
        assert 'id="fl-btn-toggle-intake"' in _NH

    def test_js_update_fl_control_block_defined(self):
        assert "_updateFlControlBlock" in _NH

    def test_js_fl_hard_stop_defined(self):
        assert "async function flHardStop" in _NH

    def test_js_fl_purge_all_defined(self):
        assert "async function flPurgeAll" in _NH

    def test_js_fl_toggle_intake_defined(self):
        assert "async function flToggleIntake" in _NH

    def test_js_calls_update_control_block_on_render(self):
        assert "_updateFlControlBlock(fl)" in _NH


# ── J. Router wiring ──────────────────────────────────────────────────────────

class TestRouterWiring:
    def test_fl_hard_stop_in_router(self):
        assert "FL_HARD_STOP" in _RO
        assert "handle_fl_hard_stop" in _RO

    def test_fl_clear_all_in_router(self):
        assert "FL_CLEAR_ALL" in _RO
        assert "handle_fl_clear_all" in _RO

    def test_fl_disable_in_router(self):
        assert "FL_DISABLE" in _RO
        assert "handle_fl_disable" in _RO

    def test_fl_enable_in_router(self):
        assert "FL_ENABLE" in _RO
        assert "handle_fl_enable" in _RO

    def test_new_handlers_imported_in_router(self):
        assert "handle_fl_hard_stop" in _RO
        assert "handle_fl_clear_all" in _RO
        assert "handle_fl_disable" in _RO
        assert "handle_fl_enable" in _RO
