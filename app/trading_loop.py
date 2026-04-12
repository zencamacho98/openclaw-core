# app/trading_loop.py
#
# Purpose-built loop for repeated mock trading.
# On every tick it assigns mock_trade_spy to the trader agent and executes it.
#
# Separate from app/loop.py (the raw execution loop). This module owns the
# concept of "mock trading is running". Do not run both loops simultaneously.
#
# Imports from protected files but does NOT modify them.
#
# Graceful-stop behavior:
#   stop_trading() checks for an open position.
#   - No open position → stop immediately (_running = False).
#   - Open position → set _stop_requested = True; loop keeps running so that
#     existing risk management (stop-loss / take-profit) and exit signals
#     continue to fire. Once the position closes, the loop sets _running = False
#     and exits cleanly. No new entries are taken while _stop_requested is True
#     because mock_trade_task only enters on BUY when not has_position — and
#     the position is still open until it exits.

import threading
import time
from datetime import datetime, timezone

from app.state import manager      # read-only import from state.py
from app.worker import run_once    # read-only import from worker.py

_running:        bool                      = False
_stop_requested: bool                      = False
_interval:       int                       = 3
_ticks:          int                       = 0
_started_at:     str | None               = None
_thread:         threading.Thread | None  = None

TASK_NAME = "mock_trade_spy"
AGENT_NAME = "trader"


def _has_open_position() -> bool:
    """Return True if the portfolio currently holds any open positions."""
    from app.portfolio import get_snapshot
    return bool(get_snapshot().get("positions"))


def _poll_kill_signal() -> bool:
    """
    Check for a disk-based kill signal written by the operator or Peter.
    Returns True if a signal was found (and consumed). Stops the loop.
    """
    from observability.market_summary import read_kill_signal
    signal = read_kill_signal()
    if signal is None:
        return False
    global _running, _stop_requested
    _running = False
    _stop_requested = False
    try:
        from observability.agent_state import transition
        transition("stopped_by_guardrail")
    except Exception:
        pass
    try:
        from observability.event_log import append_event
        append_event(
            event_type="kill_switch",
            agent="trading_loop",
            summary=f"Kill signal received from disk: {signal.get('reason', 'unknown')}",
            severity="action_needed",
        )
    except Exception:
        pass
    return True


def _loop_body(interval: int) -> None:
    global _running, _stop_requested, _ticks
    while _running:
        # Check disk-based kill signal before each tick
        if _poll_kill_signal():
            break
        manager.assign(AGENT_NAME, TASK_NAME)
        run_once(max_tasks=1)
        _ticks += 1
        # Graceful-stop check: if stop was requested and the position is now
        # closed, transition to fully stopped.
        if _stop_requested and not _has_open_position():
            _running = False
            _stop_requested = False
            break
        time.sleep(interval)


def start_trading(interval: int = 3) -> dict:
    global _running, _stop_requested, _interval, _ticks, _started_at, _thread
    # If stop was requested but loop is still running (managing a position),
    # cancel the stop so trading resumes normally.
    if _running and _stop_requested:
        _stop_requested = False
        return {"status": "stop_cancelled", "ticks": _ticks}
    if _running:
        return {"status": "already_running", "ticks": _ticks}
    _stop_requested = False
    _running    = True
    _interval   = interval
    _ticks      = 0
    _started_at = datetime.now(timezone.utc).isoformat()
    _thread     = threading.Thread(target=_loop_body, args=(interval,), daemon=True)
    _thread.start()
    return {"status": "started", "interval": interval, "agent": AGENT_NAME, "task": TASK_NAME}


def stop_trading() -> dict:
    global _running, _stop_requested
    if not _running and not _stop_requested:
        return {"status": "already_stopped"}
    if _has_open_position():
        # Graceful stop: keep the loop alive so it can manage the open position
        # to completion. New entries are already gated by `not has_position` in
        # mock_trade_task — no separate flag needed there.
        _stop_requested = True
        from app.portfolio import get_snapshot
        open_symbols = list(get_snapshot().get("positions", {}).keys())
        return {
            "status": "stopping",
            "open_positions": open_symbols,
            "message": (
                "Stop requested. Continuing to manage open position until it closes, "
                "then trading will fully stop."
            ),
        }
    # No open position — stop immediately.
    _running = False
    _stop_requested = False
    return {"status": "stopped", "ticks_completed": _ticks}


def get_status() -> dict:
    return {
        "running":        _running,
        "stop_requested": _stop_requested,
        "interval":       _interval,
        "ticks":          _ticks,
        "started_at":     _started_at,
        "agent":          AGENT_NAME,
        "task":           TASK_NAME,
    }
