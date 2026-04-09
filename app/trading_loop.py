# app/trading_loop.py
#
# Purpose-built loop for repeated mock trading.
# On every tick it assigns mock_trade_spy to the trader agent and executes it.
#
# Separate from app/loop.py (the raw execution loop). This module owns the
# concept of "mock trading is running". Do not run both loops simultaneously.
#
# Imports from protected files but does NOT modify them.

import threading
import time
from datetime import datetime, timezone

from app.state import manager      # read-only import from state.py
from app.worker import run_once    # read-only import from worker.py

_running:    bool                      = False
_interval:   int                       = 3
_ticks:      int                       = 0
_started_at: str | None               = None
_thread:     threading.Thread | None  = None

TASK_NAME = "mock_trade_spy"
AGENT_NAME = "trader"


def _loop_body(interval: int) -> None:
    global _running, _ticks
    while _running:
        manager.assign(AGENT_NAME, TASK_NAME)
        run_once(max_tasks=1)
        _ticks += 1
        time.sleep(interval)


def start_trading(interval: int = 3) -> dict:
    global _running, _interval, _ticks, _started_at, _thread
    if _running:
        return {"status": "already_running", "ticks": _ticks}
    _running    = True
    _interval   = interval
    _ticks      = 0
    _started_at = datetime.now(timezone.utc).isoformat()
    _thread     = threading.Thread(target=_loop_body, args=(interval,), daemon=True)
    _thread.start()
    return {"status": "started", "interval": interval, "agent": AGENT_NAME, "task": TASK_NAME}


def stop_trading() -> dict:
    global _running
    if not _running:
        return {"status": "already_stopped"}
    _running = False
    return {"status": "stopped", "ticks_completed": _ticks}


def get_status() -> dict:
    return {
        "running":    _running,
        "interval":   _interval,
        "ticks":      _ticks,
        "started_at": _started_at,
        "agent":      AGENT_NAME,
        "task":       TASK_NAME,
    }
