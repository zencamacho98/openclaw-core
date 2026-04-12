# observability/belfort_summary.py
#
# Belfort observability bridge for THE ABODE.
#
# Reads from disk artifacts written by app/belfort_observer.py.
# This module is the only legal path for Peter's handlers and the UI
# to access Belfort's operating mode and preflight state.
#
# Write operations (mode transitions) import from app/ internally — this is
# acceptable because transport isolation applies to peter/handlers.py only.
#
# Public API (read):
#   read_belfort_preflight()        → dict
#   read_belfort_mode()             → str
#   read_observation_log(n)         → list[dict]
#   read_belfort_freshness_state()  → dict
#
# Public API (write / control):
#   apply_belfort_mode_transition(target_mode, initiated_by, reason, force_regression) → dict
#   compute_next_belfort_mode(current_mode) → str | None
#   compute_prev_belfort_mode(current_mode) → str | None

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Optional

_ROOT            = pathlib.Path(__file__).resolve().parent.parent
_PREFLIGHT       = _ROOT / "data" / "belfort" / "preflight.json"
_OBS_LOG         = _ROOT / "data" / "belfort" / "observation_log.jsonl"
_MODE_FILE       = _ROOT / "data" / "agent_state" / "belfort_mode.json"
_SIGNAL_LOG      = _ROOT / "data" / "belfort" / "signal_log.jsonl"
_PAPER_EXEC_LOG  = _ROOT / "data" / "belfort" / "paper_exec_log.jsonl"
_SIM_LOG         = _ROOT / "data" / "belfort" / "sim_log.jsonl"

# ── Mode ordering (mirrors app/belfort_mode._ORDER) ──────────────────────────
# Duplicated here so Peter handlers never import from app/.
_MODE_ORDER = ["observation", "shadow", "paper", "live"]

# ── Freshness thresholds ──────────────────────────────────────────────────────
_STALE_THRESHOLD_MINUTES      = 15
_VERY_STALE_THRESHOLD_MINUTES = 60


# ── Read-only bridge ──────────────────────────────────────────────────────────

def read_belfort_preflight() -> dict:
    """
    Read the most recent Belfort preflight snapshot from disk.
    Returns a safe default if no snapshot exists or is unreadable.
    """
    if not _PREFLIGHT.exists():
        return _default_preflight("No preflight snapshot written yet")
    try:
        return json.loads(_PREFLIGHT.read_text(encoding="utf-8"))
    except Exception:
        return _default_preflight("Preflight snapshot unreadable")


def _default_preflight(blocked_reason: str) -> dict:
    return {
        "written_at":              None,
        "mode":                    "observation",
        "broker_environment":      "not_configured",
        "paper_credentials":       False,
        "data_lane":               "UNKNOWN",
        "session_type":            "unknown",
        "universe":                [],
        "readiness_level":         "NOT_READY",
        "can_advance_to":          None,
        "advancement_blocked_by":  blocked_reason,
        "observation_ticks_today": 0,
        "last_tick_at":            None,
    }


def read_belfort_mode() -> str:
    """
    Read Belfort's current operating mode from disk.
    Returns "observation" if the state file is absent or corrupt.
    """
    if not _MODE_FILE.exists():
        return "observation"
    try:
        data = json.loads(_MODE_FILE.read_text(encoding="utf-8"))
        return data.get("mode", "observation")
    except Exception:
        return "observation"


def read_observation_log(n: int = 20) -> list[dict]:
    """
    Read the last n observation records from observation_log.jsonl.
    Returns an empty list if the log does not exist or is unreadable.
    """
    if not _OBS_LOG.exists():
        return []
    try:
        lines = [l.strip() for l in _OBS_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
        records: list[dict] = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
        return records[-n:] if len(records) > n else records
    except Exception:
        return []


def read_belfort_freshness_state() -> dict:
    """
    Derive a freshness assessment from the preflight snapshot.

    Returns:
        freshness:           "fresh" | "stale" | "very_stale" | "no_data"
        freshness_label:     plain-English label for direct display
        minutes_since_tick:  int | None
        session_type:        str (from preflight)
        loop_likely_running: bool (heuristic: tick within last 5 min)

    Freshness is a data-quality signal only.
    "fresh" does NOT imply Belfort is ready to trade.
    """
    pf = read_belfort_preflight()
    written_at   = pf.get("written_at")
    last_tick_at = pf.get("last_tick_at")
    session_type = pf.get("session_type", "unknown")

    if written_at is None or last_tick_at is None:
        return {
            "freshness":           "no_data",
            "freshness_label":     "No observation data — trading loop not running",
            "minutes_since_tick":  None,
            "session_type":        session_type,
            "loop_likely_running": False,
        }

    try:
        tick_dt  = datetime.fromisoformat(last_tick_at)
        now_utc  = datetime.now(timezone.utc)
        # Ensure tick_dt is timezone-aware
        if tick_dt.tzinfo is None:
            from datetime import timezone as _tz
            tick_dt = tick_dt.replace(tzinfo=_tz.utc)
        elapsed_seconds = (now_utc - tick_dt).total_seconds()
        minutes_ago     = int(elapsed_seconds / 60)
    except Exception:
        return {
            "freshness":           "no_data",
            "freshness_label":     "Tick timestamp unreadable",
            "minutes_since_tick":  None,
            "session_type":        session_type,
            "loop_likely_running": False,
        }

    loop_likely_running = minutes_ago <= 5

    if session_type == "regular":
        if minutes_ago <= _STALE_THRESHOLD_MINUTES:
            freshness = "fresh"
            label     = f"Fresh — {minutes_ago} min ago"
        elif minutes_ago <= _VERY_STALE_THRESHOLD_MINUTES:
            freshness = "stale"
            label     = f"Stale — last seen {minutes_ago} min ago"
        else:
            freshness = "very_stale"
            label     = (
                f"Very stale — last seen {minutes_ago} min ago. "
                "Trading loop may not be running."
            )
    else:
        # Outside regular hours — no freshness obligation
        if minutes_ago <= _VERY_STALE_THRESHOLD_MINUTES:
            freshness = "fresh"
            label     = f"Outside market hours — last tick {minutes_ago} min ago"
        else:
            freshness = "stale"
            label     = (
                f"Outside market hours — observation paused. "
                f"Last tick {minutes_ago} min ago."
            )

    return {
        "freshness":           freshness,
        "freshness_label":     label,
        "minutes_since_tick":  minutes_ago,
        "session_type":        session_type,
        "loop_likely_running": loop_likely_running,
    }


# ── Signal log bridge ────────────────────────────────────────────────────────

def read_latest_signal_decision() -> Optional[dict]:
    """
    Return the most recent signal log record, or None if no records exist.
    Skips records where skipped=True (mode-gate skips are not decisions).
    """
    if not _SIGNAL_LOG.exists():
        return None
    try:
        lines = [
            ln.strip()
            for ln in _SIGNAL_LOG.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        for line in reversed(lines):
            try:
                rec = json.loads(line)
                if rec.get("skipped"):
                    continue
                return rec
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception:
        pass
    return None


def read_signal_stats_today() -> dict:
    """
    Aggregate today's signal log records into summary counts.

    Returns:
        total:   int — total decisions today (excludes skipped)
        actions: dict — {buy: N, sell: N, hold: N}
        holds:   int — hold signals today
        blocked: int — risk-blocked signals today
        allowed: int — risk-allowed signals today
    """
    from datetime import date as _date
    today = _date.today().isoformat()

    stats = {"total": 0, "actions": {"buy": 0, "sell": 0, "hold": 0}, "holds": 0, "blocked": 0, "allowed": 0}
    if not _SIGNAL_LOG.exists():
        return stats

    try:
        for line in _SIGNAL_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if rec.get("skipped"):
                continue
            written_at = rec.get("written_at", "")
            if not written_at.startswith(today):
                continue
            stats["total"] += 1
            action = rec.get("signal_action", "hold")
            if action in stats["actions"]:
                stats["actions"][action] += 1
            if action == "hold":
                stats["holds"] += 1
            if rec.get("risk_can_proceed"):
                stats["allowed"] += 1
            else:
                stats["blocked"] += 1
    except Exception:
        pass

    return stats


# ── Paper execution log bridge ────────────────────────────────────────────────

def read_latest_paper_execution() -> Optional[dict]:
    """
    Return the most recent paper execution record (submitted or gated).
    Returns None if no records exist or log is absent.
    Only returns records where gate_passed is True or was_submitted_to_broker is True
    (skips pure gate blocks from the most-recent scan, but returns gated too).
    Actually: returns the absolute most recent record regardless of gate/status —
    callers can filter by execution_status if needed.
    """
    if not _PAPER_EXEC_LOG.exists():
        return None
    try:
        lines = [
            ln.strip()
            for ln in _PAPER_EXEC_LOG.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        for line in reversed(lines):
            try:
                return json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception:
        pass
    return None


def read_paper_exec_stats_today() -> dict:
    """
    Aggregate today's paper execution records.

    Returns:
        total:     int — total execution attempts today (all statuses)
        submitted: int — orders successfully submitted to broker
        gated:     int — gate blocked (hold/sell/session/risk)
        errored:   int — gate passed but broker error
        symbols:   list[str] — symbols with submitted orders today
    """
    from datetime import date as _date
    today = _date.today().isoformat()

    stats: dict = {"total": 0, "submitted": 0, "gated": 0, "errored": 0, "symbols": []}
    if not _PAPER_EXEC_LOG.exists():
        return stats

    try:
        for line in _PAPER_EXEC_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not rec.get("written_at", "").startswith(today):
                continue
            stats["total"] += 1
            status = rec.get("execution_status", "")
            if status == "submitted":
                stats["submitted"] += 1
                sym = rec.get("symbol", "")
                if sym and sym not in stats["symbols"]:
                    stats["symbols"].append(sym)
            elif status == "gated":
                stats["gated"] += 1
            elif status in ("broker_error", "error"):
                stats["errored"] += 1
    except Exception:
        pass

    return stats


# ── Sim log bridge ───────────────────────────────────────────────────────────

def read_latest_sim_trade() -> Optional[dict]:
    """
    Return the most recent sim log record where action was buy or sell
    (i.e. an actual fill, not a hold tick).
    Returns None if no fills have been recorded.
    """
    if not _SIM_LOG.exists():
        return None
    try:
        lines = [
            ln.strip()
            for ln in _SIM_LOG.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        for line in reversed(lines):
            try:
                rec = json.loads(line)
                if rec.get("action") in ("buy", "sell"):
                    return rec
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception:
        pass
    return None


def read_learn_strip() -> Optional[dict]:
    """
    Compact learning summary for the inline neighborhood learn strip.

    Returns:
        verdict:              str | None — "continue" | "monitor" | "tune" | "research"
        verdict_note:         str        — short human note from the last learning run
        paper_today:          dict       — {submitted, gated, errored} counts for today
        signal_blocked_today: int        — risk-blocked signals today
        main_blocker:         str | None — most common block reason today
    """
    from datetime import date as _date
    today = _date.today().isoformat()

    # ── Verdict from learning history ──────────────────────────────────────
    verdict: Optional[str] = None
    verdict_note: str = "No learning data yet — run a research session to get feedback."
    _LEARNING_HISTORY = _ROOT / "data" / "learning_history.jsonl"
    if _LEARNING_HISTORY.exists():
        try:
            lines = [
                ln.strip()
                for ln in _LEARNING_HISTORY.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            for line in reversed(lines):
                try:
                    rec = json.loads(line)
                    verdict = rec.get("verdict")
                    if verdict:
                        # Map verdict to a short note
                        _verdict_notes = {
                            "continue": "Strategy is performing — keep running.",
                            "monitor":  "Performance is mixed — watch closely.",
                            "tune":     "Edge exists but needs parameter adjustment.",
                            "research": "Strategy not working — research recommended.",
                        }
                        verdict_note = _verdict_notes.get(verdict, verdict)
                        break
                except (json.JSONDecodeError, ValueError):
                    continue
        except Exception:
            pass

    # ── Signal stats (blocked count + main blocker) ────────────────────────
    signal_blocked_today = 0
    main_blocker: Optional[str] = None
    block_reason_counts: dict = {}
    if _SIGNAL_LOG.exists():
        try:
            for line in _SIGNAL_LOG.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if rec.get("skipped"):
                    continue
                if not rec.get("written_at", "").startswith(today):
                    continue
                if not rec.get("risk_can_proceed", True):
                    signal_blocked_today += 1
                    reason = rec.get("risk_block_reason", "")
                    if reason:
                        # Shorten to first clause
                        short = reason.split(":")[0].strip()[:50]
                        block_reason_counts[short] = block_reason_counts.get(short, 0) + 1
            if block_reason_counts:
                main_blocker = max(block_reason_counts, key=block_reason_counts.get)
        except Exception:
            pass

    # ── Paper stats today ──────────────────────────────────────────────────
    paper_today = {"submitted": 0, "gated": 0, "errored": 0}
    if _PAPER_EXEC_LOG.exists():
        try:
            for line in _PAPER_EXEC_LOG.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not rec.get("written_at", "").startswith(today):
                    continue
                status = rec.get("execution_status", "")
                if status == "submitted":
                    paper_today["submitted"] += 1
                elif status == "gated":
                    paper_today["gated"] += 1
                elif status in ("broker_error", "error"):
                    paper_today["errored"] += 1
        except Exception:
            pass

    return {
        "verdict":              verdict,
        "verdict_note":         verdict_note,
        "paper_today":          paper_today,
        "signal_blocked_today": signal_blocked_today,
        "main_blocker":         main_blocker,
    }


def read_sim_running_status() -> dict:
    """
    Return the current sim lane runtime status from app.belfort_sim.
    Wraps the app-layer import so peter/handlers.py stays transport-isolated.
    Returns a safe default dict if the module is unavailable.
    """
    try:
        from app.belfort_sim import get_sim_status
        return get_sim_status()
    except Exception:
        return {
            "running":      False,
            "interval":     5,
            "ticks":        0,
            "fills":        0,
            "started_at":   None,
            "sim_cash":     10_000.0,
            "sim_position": 0,
        }


def read_sim_stats_today() -> dict:
    """
    Aggregate today's sim log records.

    Returns:
        ticks:  int — total ticks recorded today
        fills:  int — buy or sell fills today
        buys:   int — buy fills today
        sells:  int — sell fills today
        holds:  int — hold ticks today
    """
    from datetime import date as _date
    today = _date.today().isoformat()

    stats: dict = {"ticks": 0, "fills": 0, "buys": 0, "sells": 0, "holds": 0}
    if not _SIM_LOG.exists():
        return stats

    try:
        for line in _SIM_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not rec.get("written_at", "").startswith(today):
                continue
            stats["ticks"] += 1
            action = rec.get("action", "hold")
            if action == "buy":
                stats["buys"]  += 1
                stats["fills"] += 1
            elif action == "sell":
                stats["sells"] += 1
                stats["fills"] += 1
            else:
                stats["holds"] += 1
    except Exception:
        pass

    return stats


# ── Sim performance bridge ───────────────────────────────────────────────────

def read_sim_performance(today_only: bool = True) -> dict:
    """
    Compute sim performance from sim_log.jsonl sell records.

    Win rate is computed only from sell fills (completed round-trips).
    win_rate_valid = True when sells >= 5 (statistically meaningful).

    Returns:
        fills:          int
        buys:           int
        sells:          int
        realized_pnl:   float — sum of sim_pnl from sell records today
        wins:           int   — sells with sim_pnl > 0
        losses:         int   — sells with sim_pnl <= 0
        win_rate:       float | None — wins/sells; None if sells == 0
        win_rate_valid: bool  — True when sells >= 5
    """
    from datetime import date as _date
    today = _date.today().isoformat() if today_only else None

    stats: dict = {
        "fills": 0, "buys": 0, "sells": 0,
        "realized_pnl": 0.0, "wins": 0, "losses": 0,
        "win_rate": None, "win_rate_valid": False,
    }
    if not _SIM_LOG.exists():
        return stats
    try:
        for line in _SIM_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if today and not rec.get("written_at", "").startswith(today):
                continue
            action = rec.get("action", "hold")
            if action == "buy":
                stats["buys"]  += 1
                stats["fills"] += 1
            elif action == "sell":
                stats["sells"] += 1
                stats["fills"] += 1
                pnl = rec.get("sim_pnl")
                if pnl is not None:
                    stats["realized_pnl"] += pnl
                    if pnl > 0:
                        stats["wins"] += 1
                    else:
                        stats["losses"] += 1
        if stats["sells"] > 0:
            stats["win_rate"]       = round(stats["wins"] / stats["sells"], 3)
            stats["win_rate_valid"] = stats["sells"] >= 5
    except Exception:
        pass
    stats["realized_pnl"] = round(stats["realized_pnl"], 2)
    return stats


def read_latest_regime_snapshot() -> Optional[dict]:
    """
    Return the most recent auto_regime snapshot from learning_history.jsonl.
    Returns None if no auto_regime snapshots exist or the file is absent.
    """
    _LEARNING_HISTORY = _ROOT / "data" / "learning_history.jsonl"
    if not _LEARNING_HISTORY.exists():
        return None
    try:
        lines = [
            ln.strip()
            for ln in _LEARNING_HISTORY.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        for line in reversed(lines):
            try:
                rec = json.loads(line)
                if rec.get("snapshot_type") == "auto_regime":
                    return rec
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception:
        pass
    return None


# ── Regime learning bridge ───────────────────────────────────────────────────

def read_regime_metrics() -> dict:
    """
    Per-regime learning metrics (transport-safe wrapper).

    Returns:
        regular:    dict — {submitted, gated, errored, total}
        closed_sim: dict — {fills, buys, sells, holds, ticks}
        extended:   str  — "not_supported"
    """
    try:
        from app.belfort_regime_learning import compute_regime_metrics
        return compute_regime_metrics()
    except Exception:
        return {
            "regular":    {"submitted": 0, "gated": 0, "errored": 0, "total": 0},
            "closed_sim": {"fills": 0, "buys": 0, "sells": 0, "holds": 0, "ticks": 0},
            "extended":   "not_supported",
        }


def read_live_readiness() -> dict:
    """
    Live readiness gate evaluation (transport-safe wrapper).

    Returns:
        verdict:      "not_enough_data" | "not_ready" | "candidate"
        trade_count:  int
        paper_orders: int
        win_rate:     float | None
        expectancy:   float | None
        block_rate:   float | None
        note:         str
    """
    try:
        from app.belfort_live_gate import compute_live_readiness
        return compute_live_readiness()
    except Exception:
        return {
            "verdict":      "not_enough_data",
            "trade_count":  0,
            "paper_orders": 0,
            "win_rate":     None,
            "expectancy":   None,
            "block_rate":   None,
            "note":         "Live readiness data unavailable.",
        }


def read_market_session() -> str:
    """
    Current market session type (transport-safe wrapper).

    Returns one of: "regular", "pre_market", "after_hours", "closed".
    Falls back to "closed" on any error.
    """
    try:
        from app.market_time import session_type as _st
        return _st()
    except Exception:
        return "closed"


def read_strategy_profile() -> dict:
    """
    Current strategy regime fitness summary (transport-safe wrapper).

    Returns:
        current_regime:  str
        paper_regime:    "regular"
        sim_regime:      "closed_sim"
        regime_metrics:  dict
        fitness_regular: str
        fitness_sim:     str
        extended_hours:  "not_supported"
    """
    try:
        from app.belfort_regime_learning import current_strategy_profile
        return current_strategy_profile()
    except Exception:
        return {
            "current_regime":  "unknown",
            "paper_regime":    "regular",
            "sim_regime":      "closed_sim",
            "regime_metrics":  {},
            "fitness_regular": "No data.",
            "fitness_sim":     "No data.",
            "extended_hours":  "not_supported",
        }


# ── Mode ordering helpers ─────────────────────────────────────────────────────

def _mode_index(mode: str) -> int:
    try:
        return _MODE_ORDER.index(mode)
    except ValueError:
        return -1


def compute_next_belfort_mode(current_mode: str) -> Optional[str]:
    """
    Return the next mode in sequence, or None if already at the top
    of the operator-reachable range (paper).
    Returns None for 'live' — LIVE is unreachable via Peter command.
    """
    idx = _mode_index(current_mode)
    if idx < 0 or idx >= len(_MODE_ORDER) - 1:
        return None
    candidate = _MODE_ORDER[idx + 1]
    if candidate == "live":
        return None  # LIVE blocked — operator must place sign-off file manually
    return candidate


def compute_prev_belfort_mode(current_mode: str) -> Optional[str]:
    """Return the previous mode in sequence, or None if already at observation."""
    idx = _mode_index(current_mode)
    if idx <= 0:
        return None
    return _MODE_ORDER[idx - 1]


# ── Mode transition (writes — imports app/ internally) ────────────────────────

def apply_belfort_mode_transition(
    target_mode:      str,
    initiated_by:     str  = "peter_command",
    reason:           str  = "",
    force_regression: bool = False,
) -> dict:
    """
    Apply a mode transition through the app-layer state machine.

    The observability bridge may import from app/ for write operations.
    Transport isolation applies to peter/handlers.py only.

    Returns the dict from set_mode():
        {ok: bool, mode: str, previous_mode: str, error: str | None}

    On success: mode = new mode, previous_mode = genuine pre-transition mode.
    On failure: mode = current (unchanged) mode, previous_mode = same as mode.
    """
    from app.belfort_mode import BelfortMode, set_mode
    try:
        target = BelfortMode(target_mode)
    except ValueError:
        return {
            "ok":            False,
            "mode":          target_mode,
            "previous_mode": None,
            "error":         (
                f"Unknown mode: {target_mode!r}. "
                "Valid values: observation, shadow, paper"
            ),
        }
    result = set_mode(
        mode             = target,
        reason           = reason,
        initiated_by     = initiated_by,
        force_regression = force_regression,
    )

    # Immediately sync preflight snapshot so mode-dependent fields
    # (can_advance_to, advancement_blocked_by) reflect the new mode.
    # Failure here is non-fatal — the mode transition already succeeded.
    if result.get("ok"):
        try:
            from app.belfort_observer import write_preflight_snapshot
            write_preflight_snapshot()
        except Exception:
            pass

    return result
