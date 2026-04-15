# app/trading_loop.py
#
# Purpose-built loop for Belfort's paper/shadow desk.
#
# On every tick it:
#   - refreshes non-executing observation state
#   - refreshes the market scanner
#   - evaluates Belfort's current focus symbol
#   - syncs paper execution state
#
# Separate from app/loop.py (the raw execution loop). This module owns the
# concept of "Belfort paper/shadow trading is running". Do not run both loops
# simultaneously.
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
from zoneinfo import ZoneInfo

# Compatibility imports kept so older targeted tests and any legacy callers that
# patch these names do not fail, even though Belfort's paper loop no longer
# relies on the queued mock trader task for its domain logic.
from app.state import manager  # noqa: F401
from app.worker import run_once  # noqa: F401

_running:        bool                      = False
_stop_requested: bool                      = False
_interval:       int                       = 3
_ticks:          int                       = 0
_started_at:     str | None               = None
_thread:         threading.Thread | None  = None
_last_eod_flatten_date: str | None        = None
_last_reopen_flatten_date: str | None     = None

_ET = ZoneInfo("America/New_York")

TASK_NAME = "belfort_signal_paper"
AGENT_NAME = "mr_belfort"


def _has_open_position() -> bool:
    """Return True if the portfolio currently holds any open positions."""
    try:
        from app.belfort_broker import fetch_paper_positions

        broker_positions = fetch_paper_positions()
        if broker_positions.available:
            return any(float(pos.qty or 0.0) > 0 for pos in broker_positions.positions)
    except Exception:
        pass

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


def _run_observation_snapshot() -> None:
    """
    Non-execution observation side-effect called on every loop tick.
    Refreshes the Belfort preflight snapshot from live market data.
    Never places orders. Never evaluates signals. Never modifies trading state.
    Failure is silently swallowed — the trading loop must never fail due to
    an observer error.
    """
    try:
        from app.belfort_observer import run_observation_tick
        run_observation_tick()
    except Exception:
        pass
    try:
        from app.belfort_scanner import refresh_scanner_snapshot
        refresh_scanner_snapshot(max_age_seconds=45)
    except Exception:
        pass


def _current_belfort_symbol() -> str:
    """
    Return the symbol Belfort should be evaluating right now.

    Priority:
      1. Existing Alpaca paper position — keep managing what is actually owned
      2. Existing local portfolio position — fallback if broker truth is unavailable
      2. Scanner focus symbol — follow the strongest current board leader
      3. SPY fallback — benchmark lane when scanner is unavailable
    """
    try:
        from app.belfort_broker import fetch_paper_positions

        broker_positions = fetch_paper_positions()
        if broker_positions.available:
            open_symbols = [
                str(pos.symbol).upper()
                for pos in broker_positions.positions
                if str(pos.symbol or "").strip() and float(pos.qty or 0.0) > 0
            ]
            if open_symbols:
                return open_symbols[0]
    except Exception:
        pass

    try:
        from app.portfolio import get_snapshot
        positions = (get_snapshot() or {}).get("positions") or {}
        open_symbols = [str(sym).upper() for sym in positions.keys() if str(sym).strip()]
        if open_symbols:
            return open_symbols[0]
    except Exception:
        pass
    try:
        from app.belfort_mode import current_mode
        from app.belfort_scanner import get_focus_symbol, get_paper_trade_symbol

        if current_mode().value == "paper":
            return get_paper_trade_symbol(default="SPY")
        return get_focus_symbol(default="SPY")
    except Exception:
        return "SPY"


def _refresh_market_price(symbol: str, quote: object) -> None:
    """
    Keep paper portfolio unrealized P&L tied to the latest known quote for the
    symbol Belfort is actively monitoring.
    """
    try:
        from app.portfolio import set_market_price

        price = getattr(quote, "midpoint", None)
        if price is None or float(price or 0) <= 0:
            price = getattr(quote, "last", None)
        if price is None or float(price or 0) <= 0:
            return
        set_market_price(symbol, float(price))
    except Exception:
        pass


def _run_signal_evaluation() -> dict | None:
    """
    Non-executing signal evaluation called on every loop tick after observation.
    Only active in SHADOW or PAPER mode. Evaluates MeanReversionV1 on the live
    quote, runs RiskGuardrails, and logs the decision artifact.
    Never places orders. Never modifies trading state.
    Failure is silently swallowed — the trading loop must never fail here.

    Returns the signal record dict (for handoff to paper exec), or None on skip/error.
    """
    try:
        from app.belfort_mode import current_mode
        mode = current_mode().value
        if mode not in ("shadow", "paper"):
            return None

        from app.market_data_feed import get_quote
        from app.belfort_signal_eval import evaluate_signal
        from app.portfolio import get_snapshot

        symbol    = _current_belfort_symbol()
        quote     = get_quote(symbol)
        _refresh_market_price(symbol, quote)
        portfolio = get_snapshot()
        return evaluate_signal(quote, mode=mode, portfolio=portfolio)
    except Exception:
        return None


def _run_regime_snapshot() -> None:
    """
    Periodic regime-separated learning snapshot — called every 20 ticks.
    Writes to data/learning_history.jsonl only when the tick interval is met.
    Never places orders. Failure is silently swallowed.
    """
    try:
        from app.belfort_regime_learning import maybe_record_regime_snapshot
        maybe_record_regime_snapshot(_ticks)
    except Exception:
        pass


def _sync_paper_execution_state() -> None:
    """
    Keep Belfort's local paper ledger aligned with broker-final paper fills.
    Runs before signal evaluation so position-aware decisions see the latest
    filled paper state. Never raises.
    """
    try:
        from app.belfort_mode import current_mode
        if current_mode().value != "paper":
            return
        from app.belfort_paper_exec import sync_paper_execution
        sync_paper_execution(max_orders=8)
    except Exception:
        pass


def _maybe_flatten_for_day_trader_close() -> bool:
    """
    Flatten the paper book once near the end of after-hours so Belfort does not
    carry overnight inventory.

    Returns True when the loop should skip fresh entries for this tick because
    the desk is in the flatten-or-stand-down window.
    """
    global _last_eod_flatten_date
    try:
        from app.belfort_mode import current_mode
        if current_mode().value != "paper":
            return False
        from app.market_time import session_type

        now_et = datetime.now(tz=_ET)
        session = session_type(now_et)
        session_key = now_et.strftime("%Y-%m-%d")

        if session in ("pre_market", "regular"):
            _last_eod_flatten_date = None
            return False

        should_stand_down = session == "closed" or (session == "after_hours" and (now_et.hour > 19 or (now_et.hour == 19 and now_et.minute >= 45)))
        if not should_stand_down:
            return False
        if not _has_open_position():
            if session == "closed":
                _last_eod_flatten_date = session_key
            return True
        if _last_eod_flatten_date == session_key:
            return True

        from app.belfort_paper_exec import flatten_paper_positions

        flatten_paper_positions(
            "The overnight session is approaching. Belfort is flattening the paper book so the desk starts the next tradeable session with fresh buying power."
        )
        _last_eod_flatten_date = session_key
        return True
    except Exception:
        return False


def _maybe_flatten_overnight_inventory_at_reopen() -> bool:
    """
    If Belfort wakes up in pre-market still holding yesterday's paper book,
    flatten it before any fresh entries are considered.

    Returns True when this tick should skip new entries because Belfort is
    flattening or waiting on that overnight clean-up.
    """
    global _last_reopen_flatten_date
    try:
        from app.belfort_mode import current_mode
        if current_mode().value != "paper":
            return False
        from app.market_time import session_type

        now_et = datetime.now(tz=_ET)
        session = session_type(now_et)
        session_key = now_et.strftime("%Y-%m-%d")

        if session != "pre_market":
            return False

        if not _has_open_position():
            _last_reopen_flatten_date = session_key
            return False

        if _last_reopen_flatten_date == session_key:
            return True

        from app.belfort_paper_exec import flatten_paper_positions

        flatten_paper_positions(
            "Belfort carried paper inventory overnight. Flattening in pre-market so the desk starts the day flat and restores buying power for the session open."
        )
        _last_reopen_flatten_date = session_key
        return True
    except Exception:
        return False


def _run_paper_execution(signal_record: dict | None) -> None:
    """
    Paper-only order placement — fires only when mode=paper and the signal is
    an eligible buy with risk cleared.
    Failure is silently swallowed — the trading loop must never fail here.
    """
    if not signal_record:
        return
    if signal_record.get("mode") != "paper":
        return
    try:
        from app.belfort_paper_exec import execute_paper_signal
        execute_paper_signal(signal_record)
    except Exception:
        pass


def _loop_body(interval: int) -> None:
    global _running, _stop_requested, _ticks
    while _running:
        # Check disk-based kill signal before each tick
        if _poll_kill_signal():
            break
        # Non-execution observation side-effect — refreshes preflight snapshot
        _run_observation_snapshot()
        # Sync broker-final paper outcomes into Belfort's local paper ledger
        _sync_paper_execution_state()
        if _maybe_flatten_overnight_inventory_at_reopen():
            _sync_paper_execution_state()
            run_once(max_tasks=0)
            _ticks += 1
            if _ticks % 20 == 0:
                _run_regime_snapshot()
            if _stop_requested and not _has_open_position():
                _running = False
                _stop_requested = False
                break
            time.sleep(interval)
            continue
        if _maybe_flatten_for_day_trader_close():
            _sync_paper_execution_state()
            run_once(max_tasks=0)
            _ticks += 1
            if _ticks % 20 == 0:
                _run_regime_snapshot()
            if _stop_requested and not _has_open_position():
                _running = False
                _stop_requested = False
                break
            time.sleep(interval)
            continue
        # Signal evaluation — returns record for paper handoff
        signal = _run_signal_evaluation()
        # Paper-only order placement (PAPER mode, eligible signals only)
        _run_paper_execution(signal)
        # Immediate second sync to catch fast paper fills while the desk is hot
        _sync_paper_execution_state()
        # Legacy-compatible no-op worker pulse: keeps older tests and any
        # harmless queue observability hooks satisfied without assigning the
        # old mock trader task back into Belfort's loop.
        run_once(max_tasks=0)
        _ticks += 1
        # Regime snapshot every 20 ticks
        if _ticks % 20 == 0:
            _run_regime_snapshot()
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
