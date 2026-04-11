# app/routes/belfort_diagnostics.py
#
# Compact deterministic diagnostics for the operator.
#   GET /belfort/diagnostics  — strategy drift, session P&L path, trigger detail
#
# Design: deterministic only — no LM calls.
# Reuses helpers from belfort_readiness and portfolio.

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()

_STARTING_CASH       = 100_000.0
_RESEARCH_MIN_TRADES = 10
_RECENT_N            = 5

# Key params used to detect strategy drift vs baseline snapshot
_KEY_PARAMS = [
    "SHORT_WINDOW", "LONG_WINDOW", "MEAN_REV_WINDOW", "MEAN_REV_THRESHOLD",
    "STOP_LOSS_PCT", "TAKE_PROFIT_PCT", "TRADE_COOLDOWN",
    "MAX_EFFICIENCY_RATIO", "POSITION_SIZE", "MR_REBOUND_CAP",
]


# ── Strategy drift ─────────────────────────────────────────────────────────────

def _strategy_drift() -> dict:
    """Compare current strategy config to the baseline snapshot at last reset."""
    try:
        from app.strategy.config import get_config
        current_cfg = get_config()
    except Exception:
        current_cfg = {}

    try:
        from app.routes.belfort_readiness import (
            load_baseline_record,
            _strategy_description,
        )
        baseline      = load_baseline_record()
        baseline_cfg  = baseline.get("config_snapshot", {})
        baseline_label = baseline.get("strategy_label", "")
        reset_at      = baseline.get("reset_at")
        promotion_ref = baseline.get("promotion_ref")
        promotion_param = baseline.get("promotion_param")
        current_label = _strategy_description()
    except Exception:
        baseline_cfg, baseline_label = {}, ""
        reset_at, promotion_ref, promotion_param, current_label = None, None, None, ""

    changed = []
    for k in _KEY_PARAMS:
        curr_v = current_cfg.get(k)
        base_v = baseline_cfg.get(k)
        if curr_v is not None and base_v is not None and curr_v != base_v:
            changed.append(f"{k}: {base_v} → {curr_v}")

    return {
        "current_label":   current_label,
        "baseline_label":  baseline_label,
        "drifted":         bool(changed),
        "changed_params":  changed,
        "reset_at":        reset_at,
        "promotion_ref":   promotion_ref,
        "promotion_param": promotion_param,
    }


# ── Session P&L diagnostics ────────────────────────────────────────────────────

def _session_pnl() -> dict:
    """Realized P&L path: expectancy, recent-trade edge, peak/drawdown."""
    try:
        from app.portfolio import get_snapshot, get_trades
        snap       = get_snapshot()
        all_trades = get_trades()
    except Exception:
        return {
            "realized_pnl": 0.0, "trade_count": 0, "total_closed": 0,
            "wins": 0, "losses": 0, "win_rate": None,
            "expectancy": None, "avg_win": None, "avg_loss": None,
            "recent_expectancy": None, "peak_pnl": 0.0, "drawdown_from_peak": 0.0,
        }

    realized_pnl = snap.get("realized_pnl", 0.0)
    trade_count  = snap.get("trade_count", 0)

    closed = [t for t in all_trades if t.get("side") == "SELL" and t.get("pnl") is not None]
    total_closed = len(closed)
    wins   = sum(1 for t in closed if (t.get("pnl") or 0) > 0)
    losses = total_closed - wins
    win_rate = wins / total_closed if total_closed > 0 else None

    pnls     = [t["pnl"] for t in closed]
    win_pnls  = [p for p in pnls if p > 0]
    loss_pnls = [p for p in pnls if p <= 0]

    expectancy  = round(sum(pnls) / len(pnls), 2) if pnls else None
    avg_win     = round(sum(win_pnls)  / len(win_pnls),  2) if win_pnls  else None
    avg_loss    = round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else None

    recent       = pnls[-_RECENT_N:] if len(pnls) >= _RECENT_N else pnls
    recent_exp   = round(sum(recent) / len(recent), 2) if recent else None

    # Running peak P&L (highest cumulative realized P&L reached)
    peak_pnl, running = 0.0, 0.0
    for t in closed:
        running += t["pnl"]
        if running > peak_pnl:
            peak_pnl = running
    drawdown_from_peak = round(realized_pnl - peak_pnl, 2)

    return {
        "realized_pnl":       round(realized_pnl, 2),
        "trade_count":        trade_count,
        "total_closed":       total_closed,
        "wins":               wins,
        "losses":             losses,
        "win_rate":           round(win_rate, 3) if win_rate is not None else None,
        "expectancy":         expectancy,
        "avg_win":            avg_win,
        "avg_loss":           avg_loss,
        "recent_expectancy":  recent_exp,
        "peak_pnl":           round(peak_pnl, 2),
        "drawdown_from_peak": drawdown_from_peak,
    }


# ── Trigger detail ─────────────────────────────────────────────────────────────

def _hard_threshold_gaps(snap, win_rate_data, exp_data, regime_ctx, hard_triggers):
    """Explains why each hard research trigger is not yet firing."""
    notes  = []
    pnl    = snap.get("realized_pnl", 0.0)
    closed = win_rate_data.get("total_closed", 0)
    wr     = win_rate_data.get("win_rate")
    exp    = exp_data.get("expectancy")

    if not any("Sustained loss" in r for r in hard_triggers):
        thresh = _STARTING_CASH * 0.02
        if closed < _RESEARCH_MIN_TRADES:
            notes.append(f"Sustained loss: {closed}/{_RESEARCH_MIN_TRADES} trades (need {_RESEARCH_MIN_TRADES})")
        else:
            notes.append(f"Sustained loss: P&L {pnl:+.0f} (hard threshold −${thresh:.0f})")

    if not any("Drawdown warning" in r for r in hard_triggers):
        thresh = _STARTING_CASH * 0.03
        notes.append(f"Hard drawdown: {pnl:+.0f} (threshold −${thresh:.0f})")

    if not any("Critical win rate" in r for r in hard_triggers):
        if wr is None:
            notes.append(f"Win rate: no data (hard threshold <30% after {_RESEARCH_MIN_TRADES})")
        elif closed < _RESEARCH_MIN_TRADES:
            notes.append(f"Win rate: {wr*100:.0f}% — need {_RESEARCH_MIN_TRADES} trades for hard check")
        else:
            notes.append(f"Win rate: {wr*100:.0f}% (hard threshold <30%)")

    if not any("Negative edge" in r for r in hard_triggers):
        if exp is None:
            notes.append(f"Expectancy: no data (hard threshold <−$5/trade after {_RESEARCH_MIN_TRADES})")
        elif closed < _RESEARCH_MIN_TRADES:
            notes.append(f"Expectancy: {exp:+.2f}/trade — need {_RESEARCH_MIN_TRADES} trades for hard check")
        else:
            notes.append(f"Expectancy: {exp:+.2f}/trade (hard threshold <−$5)")

    if not any("Regime mismatch" in r for r in hard_triggers):
        label  = regime_ctx.get("label", "unknown")
        fit    = regime_ctx.get("strategy_fit", "unknown")
        warmed = regime_ctx.get("warmed_up", False)
        notes.append(f"Regime: {'warming up' if not warmed else label + ' (' + fit + ' fit)'} — no mismatch")

    return notes


def _trigger_detail() -> dict:
    """Why no adjustment/research candidate has surfaced."""
    try:
        from app.routes.belfort_readiness import (
            _research_triggers,
            _regime_context,
            _expectancy_data,
            _compute_win_rate,
            load_baseline_record,
            _baseline_comparison,
        )
        from app.portfolio import get_snapshot

        snap          = get_snapshot()
        win_rate_data = _compute_win_rate()
        exp_data      = _expectancy_data()
        regime_ctx    = _regime_context()
        baseline_rec  = load_baseline_record()
        baseline_comp = _baseline_comparison(baseline_rec, snap, win_rate_data)
        triggers      = _research_triggers(snap, win_rate_data, exp_data, baseline_comp, regime_ctx)
    except Exception:
        return {
            "pressure":           "none",
            "research_triggered": False,
            "active_triggers":    [],
            "soft_triggered":     False,
            "soft_reasons":       [],
            "hard_threshold_gaps": ["Could not load trigger data"],
            "recommendation":     "",
            "queue_status":       "unavailable",
            "candidate_count":    0,
            "research_bridge":    None,
        }

    hard_triggers = triggers.get("reasons", [])
    soft_reasons  = triggers.get("soft_reasons", [])
    pressure      = triggers.get("pressure", "none")
    gaps          = _hard_threshold_gaps(snap, win_rate_data, exp_data, regime_ctx, hard_triggers)

    # Candidate queue
    try:
        from research.candidate_queue import read_queue
        all_items    = read_queue()
        pending_held = [i for i in all_items if i.get("status") in ("pending", "held")]
        total        = len(pending_held)
        queue_status = f"{total} pending/held" if total > 0 else "empty"
        candidate_count = total
    except Exception:
        queue_status    = "unavailable"
        candidate_count = 0

    # Research bridge: soft or hard pressure with an empty queue
    research_bridge = None
    if pressure == "hard" and candidate_count == 0:
        research_bridge = "Hard failure signals active — begin research to find a better configuration"
    elif pressure == "soft" and candidate_count == 0:
        research_bridge = "Soft signals suggest room to improve — consider beginning a focused research session"

    return {
        "pressure":            pressure,
        "research_triggered":  triggers.get("triggered", False),
        "active_triggers":     hard_triggers,
        "soft_triggered":      triggers.get("soft_triggered", False),
        "soft_reasons":        soft_reasons,
        "hard_threshold_gaps": gaps,
        "recommendation":      triggers.get("recommendation", ""),
        "queue_status":        queue_status,
        "candidate_count":     candidate_count,
        "research_bridge":     research_bridge,
    }


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("/belfort/diagnostics")
def belfort_diagnostics() -> dict:
    """
    Compact deterministic diagnostics:
    - strategy drift vs baseline snapshot
    - session P&L path (expectancy, recent edge, peak/drawdown)
    - trigger detail (which are active, which are not, and why)
    """
    return {
        "strategy_drift": _strategy_drift(),
        "session_pnl":    _session_pnl(),
        "trigger_detail": _trigger_detail(),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }
