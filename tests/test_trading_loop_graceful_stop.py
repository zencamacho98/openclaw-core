# tests/test_trading_loop_graceful_stop.py
#
# Unit tests for the graceful-stop behavior of app/trading_loop.py.
#
# Graceful-stop contract:
#   - stop_trading() with no open position → immediate stop (_running=False)
#   - stop_trading() with open position → _stop_requested=True, _running stays True
#   - While _stop_requested, the loop keeps ticking (position management continues)
#   - Once position closes during a tick, the loop sets _running=False and exits
#   - start_trading() while stop is requested → cancels stop, returns stop_cancelled
#   - get_status() always reflects both _running and _stop_requested
#
# All tests reset module state before running so they are order-independent.

from __future__ import annotations

import pathlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


# ── helpers ──────────────────────────────────────────────────────────────────

def _reset_loop():
    """Reset all module-level state in app.trading_loop."""
    import app.trading_loop as tl
    tl._running        = False
    tl._stop_requested = False
    tl._interval       = 3
    tl._ticks          = 0
    tl._started_at     = None
    tl._thread         = None


def _snapshot_with_position() -> dict:
    return {"positions": {"SPY": {"qty": 10, "avg_cost": 520.0}}, "cash": 90000.0}


def _snapshot_no_position() -> dict:
    return {"positions": {}, "cash": 100000.0}


# ── TestStopImmediateWhenNoPosition ──────────────────────────────────────────

class TestStopImmediateWhenNoPosition(unittest.TestCase):

    def setUp(self):
        _reset_loop()

    def test_stop_sets_running_false_when_no_position(self):
        import app.trading_loop as tl
        tl._running = True
        with patch("app.trading_loop._has_open_position", return_value=False):
            result = tl.stop_trading()
        self.assertFalse(tl._running)

    def test_stop_returns_stopped_status_when_no_position(self):
        import app.trading_loop as tl
        tl._running = True
        with patch("app.trading_loop._has_open_position", return_value=False):
            result = tl.stop_trading()
        self.assertEqual(result["status"], "stopped")

    def test_stop_clears_stop_requested_when_no_position(self):
        import app.trading_loop as tl
        tl._running        = True
        tl._stop_requested = True  # already set, should be cleared
        with patch("app.trading_loop._has_open_position", return_value=False):
            result = tl.stop_trading()
        self.assertFalse(tl._stop_requested)

    def test_stop_returns_ticks_completed(self):
        import app.trading_loop as tl
        tl._running = True
        tl._ticks   = 7
        with patch("app.trading_loop._has_open_position", return_value=False):
            result = tl.stop_trading()
        self.assertEqual(result["ticks_completed"], 7)

    def test_stop_when_already_stopped_returns_already_stopped(self):
        import app.trading_loop as tl
        # _running=False, _stop_requested=False
        result = tl.stop_trading()
        self.assertEqual(result["status"], "already_stopped")


# ── TestStopGracefulWhenPositionOpen ─────────────────────────────────────────

class TestStopGracefulWhenPositionOpen(unittest.TestCase):

    def setUp(self):
        _reset_loop()

    def test_stop_sets_stop_requested_when_position_open(self):
        import app.trading_loop as tl
        tl._running = True
        with patch("app.trading_loop._has_open_position", return_value=True), \
             patch("app.portfolio.get_snapshot", return_value=_snapshot_with_position()):
            tl.stop_trading()
        self.assertTrue(tl._stop_requested)

    def test_stop_leaves_running_true_when_position_open(self):
        import app.trading_loop as tl
        tl._running = True
        with patch("app.trading_loop._has_open_position", return_value=True), \
             patch("app.portfolio.get_snapshot", return_value=_snapshot_with_position()):
            tl.stop_trading()
        self.assertTrue(tl._running)

    def test_stop_returns_stopping_status_when_position_open(self):
        import app.trading_loop as tl
        tl._running = True
        with patch("app.trading_loop._has_open_position", return_value=True), \
             patch("app.portfolio.get_snapshot", return_value=_snapshot_with_position()):
            result = tl.stop_trading()
        self.assertEqual(result["status"], "stopping")

    def test_stop_returns_open_symbols_in_response(self):
        import app.trading_loop as tl
        tl._running = True
        with patch("app.trading_loop._has_open_position", return_value=True), \
             patch("app.portfolio.get_snapshot", return_value=_snapshot_with_position()):
            result = tl.stop_trading()
        self.assertIn("SPY", result["open_positions"])

    def test_stop_returns_message_mentioning_position_management(self):
        import app.trading_loop as tl
        tl._running = True
        with patch("app.trading_loop._has_open_position", return_value=True), \
             patch("app.portfolio.get_snapshot", return_value=_snapshot_with_position()):
            result = tl.stop_trading()
        self.assertIn("manage", result["message"].lower())


# ── TestGetStatus ─────────────────────────────────────────────────────────────

class TestGetStatus(unittest.TestCase):

    def setUp(self):
        _reset_loop()

    def test_status_includes_stop_requested_field(self):
        import app.trading_loop as tl
        status = tl.get_status()
        self.assertIn("stop_requested", status)

    def test_status_stop_requested_false_when_idle(self):
        import app.trading_loop as tl
        status = tl.get_status()
        self.assertFalse(status["stop_requested"])

    def test_status_stop_requested_true_during_graceful_stop(self):
        import app.trading_loop as tl
        tl._running        = True
        tl._stop_requested = True
        status = tl.get_status()
        self.assertTrue(status["stop_requested"])

    def test_status_running_false_when_idle(self):
        import app.trading_loop as tl
        status = tl.get_status()
        self.assertFalse(status["running"])

    def test_status_running_true_during_graceful_stop(self):
        import app.trading_loop as tl
        tl._running        = True
        tl._stop_requested = True
        status = tl.get_status()
        self.assertTrue(status["running"])


# ── TestStartWhileStopping ────────────────────────────────────────────────────

class TestStartWhileStopping(unittest.TestCase):

    def setUp(self):
        _reset_loop()

    def test_start_while_stopping_cancels_stop(self):
        import app.trading_loop as tl
        tl._running        = True
        tl._stop_requested = True
        result = tl.start_trading()
        self.assertFalse(tl._stop_requested)

    def test_start_while_stopping_returns_stop_cancelled(self):
        import app.trading_loop as tl
        tl._running        = True
        tl._stop_requested = True
        result = tl.start_trading()
        self.assertEqual(result["status"], "stop_cancelled")

    def test_start_while_stopping_keeps_running_true(self):
        import app.trading_loop as tl
        tl._running        = True
        tl._stop_requested = True
        tl.start_trading()
        self.assertTrue(tl._running)

    def test_start_while_stopping_returns_current_ticks(self):
        import app.trading_loop as tl
        tl._running        = True
        tl._stop_requested = True
        tl._ticks          = 12
        result = tl.start_trading()
        self.assertEqual(result["ticks"], 12)


# ── TestLoopExitsAfterPositionCloses ─────────────────────────────────────────

class TestLoopExitsAfterPositionCloses(unittest.TestCase):
    """
    Simulate _loop_body behavior without spinning a real thread.
    We drive the loop manually by patching _has_open_position and run_once.
    """

    def setUp(self):
        _reset_loop()

    def test_loop_exits_when_stop_requested_and_position_closes(self):
        """
        Sequence: stop requested, position open on tick 1, position closes on
        tick 2.  Loop must exit after tick 2, not continue to tick 3.
        """
        import app.trading_loop as tl

        tl._running        = True
        tl._stop_requested = True
        tl._ticks          = 0

        # Position open on first check, closed after second tick
        position_states = [True, False]  # checked once per tick after run_once
        call_count = [0]

        def fake_has_open():
            idx = min(call_count[0], len(position_states) - 1)
            result = position_states[idx]
            call_count[0] += 1
            return result

        tick_count = [0]

        def fake_run_once(max_tasks=1):
            tick_count[0] += 1

        with patch("app.trading_loop._has_open_position", side_effect=fake_has_open), \
             patch("app.trading_loop.run_once", side_effect=fake_run_once), \
             patch("app.trading_loop.manager"), \
             patch("time.sleep"):
            tl._loop_body(0)

        # Loop should have run exactly 2 ticks (closed on tick 2)
        self.assertEqual(tick_count[0], 2)
        self.assertFalse(tl._running)
        self.assertFalse(tl._stop_requested)

    def test_loop_continues_while_position_is_open(self):
        """
        While stop is requested and position remains open, the loop keeps ticking.
        """
        import app.trading_loop as tl

        tl._running        = True
        tl._stop_requested = True
        tl._ticks          = 0

        # Position stays open for 3 ticks then closes
        position_states = [True, True, True, False]
        call_count = [0]

        def fake_has_open():
            idx = min(call_count[0], len(position_states) - 1)
            result = position_states[idx]
            call_count[0] += 1
            return result

        tick_count = [0]

        def fake_run_once(max_tasks=1):
            tick_count[0] += 1

        with patch("app.trading_loop._has_open_position", side_effect=fake_has_open), \
             patch("app.trading_loop.run_once", side_effect=fake_run_once), \
             patch("app.trading_loop.manager"), \
             patch("time.sleep"):
            tl._loop_body(0)

        self.assertEqual(tick_count[0], 4)
        self.assertFalse(tl._running)

    def test_loop_exits_immediately_when_no_stop_requested(self):
        """
        Normal stop: _running flipped to False externally — loop exits after
        current tick via while condition, not the graceful-stop check.
        """
        import app.trading_loop as tl

        tl._running        = True
        tl._stop_requested = False
        tl._ticks          = 0

        tick_count = [0]

        def fake_run_once(max_tasks=1):
            tick_count[0] += 1
            tl._running = False  # simulate external stop mid-loop

        with patch("app.trading_loop.run_once", side_effect=fake_run_once), \
             patch("app.trading_loop.manager"), \
             patch("time.sleep"):
            tl._loop_body(0)

        self.assertEqual(tick_count[0], 1)
        self.assertFalse(tl._running)

    def test_stop_requested_cleared_when_position_closes(self):
        import app.trading_loop as tl

        tl._running        = True
        tl._stop_requested = True

        def fake_has_open():
            return False  # position already closed

        with patch("app.trading_loop._has_open_position", side_effect=fake_has_open), \
             patch("app.trading_loop.run_once"), \
             patch("app.trading_loop.manager"), \
             patch("time.sleep"):
            tl._loop_body(0)

        self.assertFalse(tl._stop_requested)


# ── TestHasOpenPosition ───────────────────────────────────────────────────────

class TestHasOpenPosition(unittest.TestCase):

    def setUp(self):
        _reset_loop()

    def test_returns_true_when_positions_exist(self):
        import app.trading_loop as tl
        with patch("app.portfolio.get_snapshot", return_value=_snapshot_with_position()):
            self.assertTrue(tl._has_open_position())

    def test_returns_false_when_no_positions(self):
        import app.trading_loop as tl
        with patch("app.portfolio.get_snapshot", return_value=_snapshot_no_position()):
            self.assertFalse(tl._has_open_position())

    def test_returns_false_when_positions_is_empty_dict(self):
        import app.trading_loop as tl
        with patch("app.portfolio.get_snapshot", return_value={"positions": {}}):
            self.assertFalse(tl._has_open_position())


# ── TestStartTradingNormal ────────────────────────────────────────────────────

class TestStartTradingNormal(unittest.TestCase):

    def setUp(self):
        _reset_loop()

    def test_start_clears_stop_requested(self):
        import app.trading_loop as tl
        tl._stop_requested = True  # stale flag; should be cleared on fresh start
        with patch("threading.Thread") as MockThread:
            MockThread.return_value = MagicMock()
            tl.start_trading()
        self.assertFalse(tl._stop_requested)

    def test_start_returns_started_status(self):
        import app.trading_loop as tl
        with patch("threading.Thread") as MockThread:
            MockThread.return_value = MagicMock()
            result = tl.start_trading()
        self.assertEqual(result["status"], "started")

    def test_start_when_already_running_returns_already_running(self):
        import app.trading_loop as tl
        tl._running        = True
        tl._stop_requested = False
        result = tl.start_trading()
        self.assertEqual(result["status"], "already_running")


# ── TestKillSignalPolling ─────────────────────────────────────────────────────

class TestKillSignalPolling(unittest.TestCase):
    """
    Tests for _poll_kill_signal and its integration into _loop_body.
    The disk signal is written by observability.market_summary.write_kill_signal;
    the loop checks for it on each tick and halts if found.
    """

    def setUp(self):
        _reset_loop()

    def test_poll_returns_false_when_no_signal(self):
        import app.trading_loop as tl
        with patch("observability.market_summary.read_kill_signal", return_value=None):
            result = tl._poll_kill_signal()
        self.assertFalse(result)

    def test_poll_returns_true_when_signal_present(self):
        import app.trading_loop as tl
        signal = {"reason": "peter_command", "environment": "paper", "timestamp": "2026-04-11T00:00:00Z"}
        with patch("observability.market_summary.read_kill_signal", return_value=signal), \
             patch("observability.agent_state.transition"), \
             patch("observability.event_log.append_event"):
            result = tl._poll_kill_signal()
        self.assertTrue(result)

    def test_poll_sets_running_false_on_signal(self):
        import app.trading_loop as tl
        tl._running = True
        signal = {"reason": "operator", "environment": "paper", "timestamp": "2026-04-11T00:00:00Z"}
        with patch("observability.market_summary.read_kill_signal", return_value=signal), \
             patch("observability.agent_state.transition"), \
             patch("observability.event_log.append_event"):
            tl._poll_kill_signal()
        self.assertFalse(tl._running)

    def test_loop_stops_on_disk_kill_signal(self):
        """
        When _poll_kill_signal returns True on the first check,
        the loop body should break immediately without ticking.
        """
        import app.trading_loop as tl
        tl._running = True
        tl._ticks   = 0

        tick_count = [0]
        def fake_run_once(max_tasks=1):
            tick_count[0] += 1

        signal = {"reason": "peter_command", "environment": "paper"}
        with patch("app.trading_loop._poll_kill_signal", return_value=True), \
             patch("app.trading_loop.run_once", side_effect=fake_run_once), \
             patch("app.trading_loop.manager"):
            # Loop will see signal on first iteration and break
            tl._loop_body(0)

        self.assertEqual(tick_count[0], 0)

    def test_loop_ticks_normally_when_no_signal(self):
        """
        When no kill signal exists, loop ticks normally until stopped externally.
        """
        import app.trading_loop as tl
        tl._running = True
        tl._ticks   = 0

        tick_count = [0]
        def fake_run_once(max_tasks=1):
            tick_count[0] += 1
            if tick_count[0] >= 3:
                tl._running = False

        with patch("app.trading_loop._poll_kill_signal", return_value=False), \
             patch("app.trading_loop.run_once", side_effect=fake_run_once), \
             patch("app.trading_loop.manager"), \
             patch("time.sleep"):
            tl._loop_body(0)

        self.assertEqual(tick_count[0], 3)


if __name__ == "__main__":
    unittest.main()
