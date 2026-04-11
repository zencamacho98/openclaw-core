# app/routes/belfort_readiness.py
#
# Belfort Readiness Scorecard API  (V2)
#
# GET /belfort/readiness        — full scorecard: 10 gates, level, win-rate, mentor summary
# GET /belfort/mentor-summary   — plain-text mentor-ready verbal summary only
#
# Design: deterministic core only — no LM calls here.

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_BASELINE_RECORD = _ROOT / "data" / "baseline_adoption_record.json"

# ── Gate thresholds ───────────────────────────────────────────────────────────
_MIN_TRADES_EVALUATION   = 10    # trades needed to reach MONITORING level
_MIN_TRADES_PRELIVE      = 25    # trades needed for PRE-LIVE CANDIDATE
_MIN_OBS_HOURS           = 1.0   # wall-clock hours since baseline reset (for MONITORING)
_MAX_PNL_DRAWDOWN_PCT    = 0.05  # realized P&L must stay above -5% of starting cash
_MIN_CLOSED_FOR_WIN_RATE = 5     # closed trades needed before win-rate/expectancy gates are enforced
_MIN_WIN_RATE            = 0.40  # minimum win rate for PRE-LIVE CANDIDATE
_STARTING_CASH           = 100_000.0

# ── Research trigger thresholds ───────────────────────────────────────────────
_RESEARCH_MIN_TRADES       = 10    # minimum closed trades before most triggers activate
_RESEARCH_PNL_PCT          = -0.02 # -2%: sustained loss trigger
_RESEARCH_DRAWDOWN_WARNING = -0.03 # -3%: early drawdown warning (before hard -5% gate)
_RESEARCH_WIN_RATE_MIN     = 0.30  # below 30% after enough data: critically low
_RESEARCH_EXPECTANCY_MIN   = -5.0  # avg trade P&L below -$5: negative edge trigger
_RESEARCH_WR_REGRESSION    = 0.15  # 15pp win-rate decline vs prior session: regression trigger

# ── Soft trigger thresholds (earlier pressure — weak but not catastrophic) ────
_SOFT_MIN_TRADES   = 5     # min closed trades before soft triggers activate
_SOFT_DRAWDOWN_PCT = 0.01  # session drawdown from peak > 1% of starting cash ($1 000)


# ── Baseline adoption record ──────────────────────────────────────────────────

def write_baseline_record(
    reason: str = "",
    strategy_label: str = "",
    prev_portfolio: dict | None = None,
) -> dict:
    """
    Called by /trading/reset to record strategy context at reset time.
    prev_portfolio should be the pre-reset portfolio snapshot (trades, P&L, win rate).
    Idempotent — always overwrites.
    """
    try:
        from app.strategy.config import get_config
        cfg = get_config()
    except Exception:
        cfg = {}

    promotion = _last_promotion()

    record = {
        "reset_at":        datetime.now(timezone.utc).isoformat(),
        "reason":          reason,
        "strategy_label":  strategy_label or _strategy_description(),
        "config_snapshot": cfg,
        "promotion_ref":   promotion.get("timestamp") if promotion else None,
        "promotion_param": promotion.get("parameter") if promotion else None,
        "prev_portfolio":  prev_portfolio,   # snapshot of what was wiped
    }
    _ROOT.joinpath("data").mkdir(exist_ok=True)
    _BASELINE_RECORD.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def load_baseline_record() -> dict:
    if _BASELINE_RECORD.exists():
        try:
            return json.loads(_BASELINE_RECORD.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _last_promotion() -> dict | None:
    """Return the most recent candidate_promotion changelog entry, or None."""
    try:
        from app.strategy.changelog import get_recent
        for entry in get_recent(100):
            if str(entry.get("parameter", "")).startswith("promotion:"):
                return entry
    except Exception:
        pass
    return None


def _strategy_description() -> str:
    """Compact plain-English description of the live strategy config."""
    try:
        from app.strategy.config import get_config
        cfg      = get_config()
        short    = cfg.get("SHORT_WINDOW", 3)
        long_    = cfg.get("LONG_WINDOW", 7)
        mr_win   = cfg.get("MEAN_REV_WINDOW", 20)
        mr_thr   = cfg.get("MEAN_REV_THRESHOLD", 1.0)
        stop_pct = cfg.get("STOP_LOSS_PCT", 0.02)
        take_pct = cfg.get("TAKE_PROFIT_PCT", 0.04)
        cooldown = cfg.get("TRADE_COOLDOWN", 0)
        parts = [
            f"Mean-reversion ({mr_win}-bar window, {mr_thr:.1f}\u00a0std-dev trigger)",
            f"MA crossover filter ({short}/{long_}-bar)",
            f"Stop {stop_pct*100:.1f}%, target {take_pct*100:.1f}%",
        ]
        if cooldown > 0:
            parts.append(f"{cooldown}-tick cooldown")
        return "; ".join(parts)
    except Exception:
        return "Strategy description unavailable"


def _elapsed_hours(reset_at: str) -> float:
    """Return wall-clock hours since reset_at (ISO timestamp)."""
    try:
        reset_dt = datetime.fromisoformat(reset_at)
        if reset_dt.tzinfo is None:
            reset_dt = reset_dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - reset_dt
        return max(0.0, delta.total_seconds() / 3600.0)
    except Exception:
        return 0.0


def _elapsed_label(hours: float) -> str:
    """Human-readable elapsed time."""
    if hours < 1:
        return f"{int(hours * 60)}m"
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours/24:.1f}d"


def _compute_win_rate() -> dict:
    """
    Win rate from closed trade history (SELL trades with non-zero P&L).
    Returns {wins, losses, total_closed, win_rate (float|None)}.
    """
    try:
        from app.portfolio import get_trades
        trades = get_trades()
    except Exception:
        return {"wins": 0, "losses": 0, "total_closed": 0, "win_rate": None}

    closed = [t for t in trades if t.get("side") == "SELL" and t.get("pnl") is not None]
    wins   = sum(1 for t in closed if (t.get("pnl") or 0) > 0)
    losses = len(closed) - wins
    total  = wins + losses
    return {
        "wins":         wins,
        "losses":       losses,
        "total_closed": total,
        "win_rate":     wins / total if total > 0 else None,
    }


def _regime_context() -> dict:
    """
    Lightweight market-regime label from the existing strategy router.
    No new data sources — reads from app.strategy.router.get_state().
    Returns: {regime, label, efficiency_ratio, strategy_fit, vol_note, warmed_up}
    strategy_fit: 'good' (ranging) / 'ok' (mildly trending) / 'poor' (trending) / 'unknown'
    """
    try:
        from app.strategy.router import get_state as router_state
        state    = router_state("SPY")
        regime   = state.get("regime", "unknown")   # 'trending' or 'ranging'
        er       = state.get("efficiency_ratio")     # float 0-1 or None
        mr       = state.get("mean_reversion", {})
        warmed   = mr.get("warmed_up", False)
        std      = mr.get("std")
        mean_p   = mr.get("mean")

        if not warmed:
            label, fit = "warming up", "unknown"
        elif er is None:
            label, fit = regime, "ok"
        elif er >= 0.50:
            label, fit = "trending", "poor"      # MR underperforms in trend
        elif er >= 0.30:
            label, fit = "mildly trending", "ok"
        else:
            label, fit = "ranging / choppy", "good"  # MR designed for this

        vol_note = None
        if std is not None and mean_p and mean_p > 0:
            vol_pct = std / mean_p * 100
            if vol_pct < 0.10:
                vol_note = "low vol"
            elif vol_pct > 0.40:
                vol_note = "high vol"

        return {
            "regime":           regime,
            "label":            label,
            "efficiency_ratio": er,
            "strategy_fit":     fit,
            "vol_note":         vol_note,
            "warmed_up":        warmed,
        }
    except Exception:
        return {"regime": "unknown", "label": "unknown",
                "efficiency_ratio": None, "strategy_fit": "unknown",
                "vol_note": None, "warmed_up": False}


def _expectancy_data() -> dict:
    """
    Per-trade quality metrics from closed (SELL) trade history.
    Returns: {total_closed, expectancy, avg_win, avg_loss, profit_factor, gross_profit, gross_loss}
    All values are None when there are no closed trades.
    """
    try:
        from app.portfolio import get_trades
        trades = get_trades()
    except Exception:
        return {"total_closed": 0, "expectancy": None, "avg_win": None,
                "avg_loss": None, "profit_factor": None,
                "gross_profit": None, "gross_loss": None}

    closed = [t for t in trades if t.get("side") == "SELL" and t.get("pnl") is not None]
    if not closed:
        return {"total_closed": 0, "expectancy": None, "avg_win": None,
                "avg_loss": None, "profit_factor": None,
                "gross_profit": None, "gross_loss": None,
                "peak_pnl": 0.0, "drawdown_from_peak": 0.0}

    wins   = [t["pnl"] for t in closed if t["pnl"] > 0]
    losses = [t["pnl"] for t in closed if t["pnl"] <= 0]
    total  = sum(t["pnl"] for t in closed)

    avg_win  = round(sum(wins)   / len(wins),   2) if wins   else 0.0
    avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
    expect   = round(total / len(closed), 2)

    g_profit = sum(wins)
    g_loss   = abs(sum(losses))
    pf       = round(g_profit / g_loss, 3) if g_loss > 0 else None

    # Session peak: running cumulative max realized P&L
    peak_pnl, running = 0.0, 0.0
    for t in closed:
        running += t["pnl"]
        if running > peak_pnl:
            peak_pnl = running
    drawdown_from_peak = round(total - peak_pnl, 2)

    return {
        "total_closed":      len(closed),
        "expectancy":        expect,
        "avg_win":           avg_win,
        "avg_loss":          avg_loss,
        "profit_factor":     pf,
        "gross_profit":      round(g_profit, 2),
        "gross_loss":        round(g_loss, 2),
        "peak_pnl":          round(peak_pnl, 2),
        "drawdown_from_peak": drawdown_from_peak,
    }


def _soft_triggers(win_rate_data: dict, exp_data: dict) -> dict:
    """
    Early-warning soft triggers: non-catastrophic but sustained weak signals.
    Fire before the hard failure thresholds to give action pressure earlier.
    Returns {soft_triggered, soft_count, soft_reasons}
    """
    soft_reasons = []
    total_closed = win_rate_data.get("total_closed", 0)
    expectancy   = exp_data.get("expectancy")
    pf           = exp_data.get("profit_factor")
    drawdown     = exp_data.get("drawdown_from_peak", 0.0)

    if total_closed >= _SOFT_MIN_TRADES:
        # Any negative expectancy (hard threshold is -$5 — this fires much earlier)
        if expectancy is not None and expectancy < 0:
            soft_reasons.append(
                f"Negative expectancy: {expectancy:+.2f}/trade after {total_closed} closed trades"
            )
        # Profit factor below 1.0 (total losses exceed total gains)
        if pf is not None and pf < 1.0:
            soft_reasons.append(
                f"Profit factor {pf:.2f} \u2014 aggregate losses exceed aggregate gains"
            )

    # Session drawdown from peak (fires regardless of trade count)
    if drawdown < -(_STARTING_CASH * _SOFT_DRAWDOWN_PCT):
        soft_reasons.append(
            f"Drawdown from session peak: ${abs(drawdown):.0f} below peak realized P\u0026L"
        )

    return {
        "soft_triggered": bool(soft_reasons),
        "soft_count":     len(soft_reasons),
        "soft_reasons":   soft_reasons,
    }


def _research_triggers(
    snap:          dict,
    win_rate_data: dict,
    exp_data:      dict,
    baseline_comp: dict | None,
    regime_ctx:    dict,
) -> dict:
    """
    Explicit deterministic triggers for recommending new research.
    Returns: {triggered, count, reasons, recommendation}
    All thresholds are intentionally softer than the hard readiness gates.
    """
    reasons      = []
    total_closed = win_rate_data.get("total_closed", 0)
    realized_pnl = snap.get("realized_pnl", 0.0)
    win_rate     = win_rate_data.get("win_rate")
    expectancy   = exp_data.get("expectancy")

    # 1. Sustained loss after enough trades
    if (total_closed >= _RESEARCH_MIN_TRADES
            and realized_pnl < _STARTING_CASH * _RESEARCH_PNL_PCT):
        reasons.append(
            f"Sustained loss: P&L {realized_pnl:+.2f} after {total_closed} closed trades"
        )

    # 2. Early drawdown warning (softer than hard -5% gate)
    if realized_pnl < _STARTING_CASH * _RESEARCH_DRAWDOWN_WARNING:
        reasons.append(
            f"Drawdown warning: P&L {realized_pnl:+.2f} — approaching safety floor"
        )

    # 3. Critically low win rate after enough data
    if (win_rate is not None and total_closed >= _RESEARCH_MIN_TRADES
            and win_rate < _RESEARCH_WIN_RATE_MIN):
        reasons.append(
            f"Critical win rate: {win_rate*100:.0f}% after {total_closed} trades"
        )

    # 4. Negative edge / expectancy
    if (expectancy is not None and total_closed >= _RESEARCH_MIN_TRADES
            and expectancy < _RESEARCH_EXPECTANCY_MIN):
        reasons.append(
            f"Negative edge: avg trade P&L {expectancy:+.2f} — strategy not generating value"
        )

    # 5. Regime mismatch (MR strategy in trending market)
    if regime_ctx.get("strategy_fit") == "poor" and regime_ctx.get("warmed_up"):
        reasons.append(
            f"Regime mismatch: market is {regime_ctx.get('label', '?')} — MR needs ranging conditions"
        )

    # 6. Win-rate regression vs previous baseline session
    if baseline_comp and baseline_comp.get("available") and total_closed >= 5:
        prev_wr = baseline_comp.get("prev_win_rate")
        curr_wr = baseline_comp.get("curr_win_rate")
        if (prev_wr is not None and curr_wr is not None
                and curr_wr < prev_wr - _RESEARCH_WR_REGRESSION):
            reasons.append(
                f"Win rate regressed: {curr_wr*100:.0f}% vs {prev_wr*100:.0f}% previous session"
            )

    triggered = bool(reasons)
    n         = len(reasons)
    if not triggered:
        rec = "Continue trading — no hard issues detected."
    elif n == 1 and "Regime mismatch" in reasons[0]:
        rec = "Monitor regime — no performance failure yet."
    elif n >= 2 or (realized_pnl < _STARTING_CASH * _RESEARCH_PNL_PCT and total_closed >= _RESEARCH_MIN_TRADES):
        rec = "Recommend research — multiple performance issues detected."
    else:
        rec = "Consider targeted parameter adjustment or focused research."

    soft     = _soft_triggers(win_rate_data, exp_data)
    pressure = "hard" if triggered else ("soft" if soft["soft_triggered"] else "none")

    return {
        "triggered":      triggered,
        "count":          n,
        "reasons":        reasons,          # hard trigger reasons
        "soft_triggered": soft["soft_triggered"],
        "soft_count":     soft["soft_count"],
        "soft_reasons":   soft["soft_reasons"],
        "pressure":       pressure,         # "none" | "soft" | "hard"
        "recommendation": rec,
    }


def _baseline_comparison(
    baseline_record: dict,
    current_snap:    dict,
    win_rate_data:   dict,
) -> dict | None:
    """
    Compare current eval-window stats vs. the previous session (pre-reset snapshot).
    Returns None if no prev_portfolio was captured at reset time.
    """
    prev = baseline_record.get("prev_portfolio")
    if not prev:
        return None

    curr_pnl = round(current_snap.get("realized_pnl", 0.0), 2)
    prev_pnl = round(prev.get("realized_pnl", 0.0), 2)
    curr_wr  = win_rate_data.get("win_rate")
    prev_wr  = prev.get("win_rate")

    def _fmt_wr(wr):
        return f"{wr*100:.0f}%" if wr is not None else "—"

    def _fmt_pnl(p):
        return ("+" if p >= 0 else "") + f"${p:.2f}"

    # Performance verdict: improving / declining / similar
    total_closed = win_rate_data.get("total_closed", 0)
    if curr_wr is not None and prev_wr is not None and total_closed >= 5:
        if curr_wr > prev_wr + 0.05:
            verdict = "improving"
        elif curr_wr < prev_wr - 0.10:
            verdict = "declining"
        else:
            verdict = "similar"
    elif curr_pnl > prev_pnl + 50:
        verdict = "improving"
    elif curr_pnl < prev_pnl - 50:
        verdict = "declining"
    else:
        verdict = "similar"

    return {
        "available":     True,
        "prev_trades":   prev.get("trade_count", 0),
        "prev_pnl":      prev_pnl,
        "prev_win_rate": prev_wr,
        "curr_trades":   current_snap.get("trade_count", 0),
        "curr_pnl":      curr_pnl,
        "curr_win_rate": curr_wr,
        "pnl_delta":     round(curr_pnl - prev_pnl, 2),
        "verdict":       verdict,
        "summary": (
            f"Prev session: {prev.get('trade_count', 0)} trades, "
            f"P\u0026L {_fmt_pnl(prev_pnl)}, win rate {_fmt_wr(prev_wr)}. "
            f"Current: {current_snap.get('trade_count', 0)} trades, "
            f"P\u0026L {_fmt_pnl(curr_pnl)}, win rate {_fmt_wr(curr_wr)}."
        ),
    }


def _top_blockers(gates: list[dict], max_n: int = 3) -> list[str]:
    """
    Return up to max_n plain-English blocker notes from failing gates,
    ordered by evaluation priority (most actionable first).
    """
    priority = [
        "strategy_adopted", "baseline_reset",
        "enough_trades", "observation_window",
        "deep_trades", "win_rate_ok", "pnl_quality",
        "no_review_pending", "no_warnings",
        "system_healthy", "budget_ok", "sentinel_ok",
    ]
    failed_map = {g["id"]: g["note"] for g in gates if not g["pass"]}
    ordered = [failed_map[gid] for gid in priority if gid in failed_map]
    # Append any not in the priority list
    for g in gates:
        if not g["pass"] and g["note"] not in ordered:
            ordered.append(g["note"])
    return ordered[:max_n]


def _evaluate_gates(
    portfolio_snap:  dict,
    belfort_state:   dict,
    checker_state:   dict,
    custodian_state: dict,
    sentinel_state:  dict,
    baseline_record: dict,
    last_promo:      dict | None,
    win_rate_data:   dict | None = None,
    exp_data:        dict | None = None,
) -> list[dict]:
    """Evaluate all readiness gates. Returns list of {id, label, pass, note}."""
    if win_rate_data is None:
        win_rate_data = {}
    if exp_data is None:
        exp_data = {}

    status       = belfort_state.get("status", "unknown")
    trade_count  = portfolio_snap.get("trade_count", 0)
    realized_pnl = portfolio_snap.get("realized_pnl", 0.0)
    total_closed = win_rate_data.get("total_closed", 0)
    win_rate     = win_rate_data.get("win_rate")

    # ── Gate 1: strategy ever promoted from research ──
    strategy_adopted = last_promo is not None
    promo_ts         = last_promo.get("timestamp", "")[:10] if last_promo else None

    # ── Gate 2: baseline reset happened after the last promotion ──
    reset_at      = baseline_record.get("reset_at")
    last_promo_at = last_promo.get("timestamp") if last_promo else None
    baseline_after = (
        strategy_adopted
        and reset_at is not None
        and (last_promo_at is None or reset_at >= last_promo_at)
    )

    # ── Gate 3: enough trades for MONITORING (first trade-count gate) ──
    enough_trades = trade_count >= _MIN_TRADES_EVALUATION

    # ── Gate 4: observation window ──
    hours_elapsed = _elapsed_hours(reset_at) if reset_at else 0.0
    obs_ok        = baseline_after and hours_elapsed >= _MIN_OBS_HOURS
    obs_label     = _elapsed_label(hours_elapsed) if reset_at else "—"

    # ── Gate 5: deeper trade count for PRE-LIVE (second trade-count gate) ──
    deep_trades = trade_count >= _MIN_TRADES_PRELIVE

    # ── Gate 6: win-rate quality (only enforced once enough data exists) ──
    if total_closed < _MIN_CLOSED_FOR_WIN_RATE:
        # Not enough data yet — gate is pending, not failing
        win_rate_ok    = True    # does not block
        wr_note_pass   = f"Not enough data yet ({total_closed}/{_MIN_CLOSED_FOR_WIN_RATE} closed trades needed to evaluate)"
        wr_label       = f"Win rate \u2265 {_MIN_WIN_RATE*100:.0f}% (pending \u2014 {total_closed}/{_MIN_CLOSED_FOR_WIN_RATE} trades)"
    elif win_rate is not None:
        win_rate_ok    = win_rate >= _MIN_WIN_RATE
        pct            = win_rate * 100
        wr_note_pass   = f"{pct:.0f}% win rate ({win_rate_data.get('wins',0)}W / {win_rate_data.get('losses',0)}L)"
        wr_label       = f"Win rate \u2265 {_MIN_WIN_RATE*100:.0f}% ({pct:.0f}% actual)"
    else:
        win_rate_ok    = True    # no data at all — do not block
        wr_note_pass   = "No closed trades yet \u2014 will evaluate once trading starts"
        wr_label       = f"Win rate \u2265 {_MIN_WIN_RATE*100:.0f}% (no data)"

    # ── Gate 7: expectancy / average trade quality ──
    exp_val = exp_data.get("expectancy")
    if total_closed < _MIN_CLOSED_FOR_WIN_RATE:
        expectancy_ok  = True
        exp_note_pass  = f"Not enough data yet ({total_closed}/{_MIN_CLOSED_FOR_WIN_RATE} closed trades needed to evaluate)"
        exp_gate_label = f"Positive trade expectancy (pending \u2014 {total_closed}/{_MIN_CLOSED_FOR_WIN_RATE} trades)"
    elif exp_val is not None:
        expectancy_ok  = exp_val >= 0.0
        exp_note_pass  = f"Avg trade P\u0026L: {exp_val:+.2f}"
        exp_gate_label = f"Positive trade expectancy ({exp_val:+.2f} per trade)"
    else:
        expectancy_ok  = True
        exp_note_pass  = "No closed trades yet"
        exp_gate_label = "Positive trade expectancy (no data)"

    # ── Gate 8: P&L quality ──
    pnl_floor  = -(_STARTING_CASH * _MAX_PNL_DRAWDOWN_PCT)
    pnl_ok     = realized_pnl >= pnl_floor
    pnl_pct    = (realized_pnl / _STARTING_CASH) * 100

    # ── Gate 8: no unresolved review ──
    no_review = status not in ("waiting_for_review", "review_held")

    # ── Gate 9: no checker warnings ──
    no_warnings = checker_state.get("open_warnings", 0) == 0

    # ── Gate 10: system healthy ──
    system_healthy = custodian_state.get("overall", "unknown") in ("healthy", "unknown")

    # ── Gate 11: not budget-blocked ──
    not_blocked = status != "paused_by_budget"

    # ── Gate 12: sentinel not failed ──
    sentinel_ok = sentinel_state.get("verdict", "unknown") != "not_ready"

    return [
        {
            "id":    "strategy_adopted",
            "label": "Strategy adopted from research",
            "pass":  strategy_adopted,
            "note":  (f"Adopted {promo_ts}" if strategy_adopted
                      else "Run research and approve a candidate first"),
        },
        {
            "id":    "baseline_reset",
            "label": "Baseline reset after adoption",
            "pass":  baseline_after,
            "note":  (f"Reset {reset_at[:10] if reset_at else '?'}" if baseline_after
                      else "Reset trading baseline after adopting to start a clean eval window"),
        },
        {
            "id":    "enough_trades",
            "label": f"Initial trade depth ({trade_count}\u00a0/\u00a0{_MIN_TRADES_EVALUATION} trades)",
            "pass":  enough_trades,
            "note":  (f"{trade_count} trades recorded" if enough_trades
                      else f"Start mock trading \u2014 need {_MIN_TRADES_EVALUATION} trades to leave Evaluation"),
        },
        {
            "id":    "observation_window",
            "label": f"Observation window \u2265 {_MIN_OBS_HOURS:.0f}h ({obs_label} elapsed)",
            "pass":  obs_ok,
            "note":  (f"{obs_label} since reset \u2014 OK" if obs_ok
                      else f"Need {_MIN_OBS_HOURS:.0f}h+ of running time \u2014 {obs_label} so far"),
        },
        {
            "id":    "deep_trades",
            "label": f"Deep trade depth ({trade_count}\u00a0/\u00a0{_MIN_TRADES_PRELIVE} trades for pre-live)",
            "pass":  deep_trades,
            "note":  (f"{trade_count} trades \u2014 meets pre-live depth" if deep_trades
                      else f"Need {_MIN_TRADES_PRELIVE} trades for pre-live consideration \u2014 {trade_count} so far"),
        },
        {
            "id":    "win_rate_ok",
            "label": wr_label,
            "pass":  win_rate_ok,
            "note":  (wr_note_pass if win_rate_ok
                      else f"Win rate {win_rate*100:.0f}% is below {_MIN_WIN_RATE*100:.0f}% threshold \u2014 strategy may need adjustment"),
        },
        {
            "id":    "expectancy_ok",
            "label": exp_gate_label,
            "pass":  expectancy_ok,
            "note":  (exp_note_pass if expectancy_ok
                      else f"Avg trade P\u0026L {exp_val:+.2f} \u2014 negative edge, review strategy"),
        },
        {
            "id":    "pnl_quality",
            "label": f"P\u0026L above safety floor ({pnl_pct:+.1f}% / floor \u2212{_MAX_PNL_DRAWDOWN_PCT*100:.0f}%)",
            "pass":  pnl_ok,
            "note":  (f"P\u0026L {pnl_pct:+.1f}% \u2014 within floor" if pnl_ok
                      else f"P\u0026L {pnl_pct:+.1f}% \u2014 crossed the \u2212{_MAX_PNL_DRAWDOWN_PCT*100:.0f}% floor, review strategy"),
        },
        {
            "id":    "no_review_pending",
            "label": "No pending research review",
            "pass":  no_review,
            "note":  ("No pending review" if no_review
                      else "Approve or reject the queued research result before continuing"),
        },
        {
            "id":    "no_warnings",
            "label": "No active system warnings",
            "pass":  no_warnings,
            "note":  ("Checker clear" if no_warnings
                      else f"{checker_state.get('open_warnings', 0)} warning(s) open \u2014 check the Loop Checker"),
        },
        {
            "id":    "system_healthy",
            "label": "System health clear",
            "pass":  system_healthy,
            "note":  ("Runtime healthy" if system_healthy
                      else "System health degraded \u2014 run a Custodian check"),
        },
        {
            "id":    "budget_ok",
            "label": "Budget limit OK",
            "pass":  not_blocked,
            "note":  ("Budget OK" if not_blocked
                      else "Belfort is paused by budget limit \u2014 check Cost Warden"),
        },
        {
            "id":    "sentinel_ok",
            "label": "Patch safety check OK",
            "pass":  sentinel_ok,
            "note":  (f"Sentinel: {sentinel_state.get('verdict', 'not run')}" if sentinel_ok
                      else "Sentinel shows a failure \u2014 investigate before continuing"),
        },
    ]


def _compute_level(gates: list[dict]) -> tuple[str, str]:
    """Return (level_id, level_label)."""
    passed       = {g["id"] for g in gates if g["pass"]}
    need_eval    = {"strategy_adopted", "baseline_reset"}
    need_monitor = need_eval | {"enough_trades", "no_review_pending", "observation_window"}
    need_prelive = need_monitor | {"deep_trades", "win_rate_ok", "expectancy_ok", "pnl_quality", "no_warnings", "system_healthy", "budget_ok", "sentinel_ok"}

    if need_prelive.issubset(passed):
        return "pre_live_candidate", "PRE-LIVE CANDIDATE"
    if need_monitor.issubset(passed):
        return "monitoring", "MONITORING"
    if need_eval.issubset(passed):
        return "evaluation", "EVALUATION"
    if "strategy_adopted" in passed:
        return "awaiting_reset", "AWAITING RESET"
    return "not_started", "NOT STARTED"


def _plain_english(
    level:           str,
    gates:           list[dict],
    trade_count:     int,
    realized_pnl:    float,
    win_rate_data:   dict,
    hours_elapsed:   float,
    last_promo:      dict | None,
    baseline_record: dict,
) -> str:
    """Short scorecard summary (2-3 sentences)."""
    promo_ts = last_promo.get("timestamp", "")[:10] if last_promo else None
    reset_ts = baseline_record.get("reset_at", "")[:10] if baseline_record.get("reset_at") else None
    pnl_dir  = "up" if realized_pnl >= 0 else "down"
    pnl_str  = f"{pnl_dir} ${abs(realized_pnl):.2f}"
    wr       = win_rate_data.get("win_rate")
    wr_str   = f", {wr*100:.0f}% win rate" if wr is not None else ""
    failed   = [g for g in gates if not g["pass"]]

    if level == "not_started":
        return (
            "No strategy has been formally adopted yet. "
            "Run a research campaign, approve a strong result, then reset the baseline."
        )
    if level == "awaiting_reset":
        return (
            f"Strategy adopted {promo_ts or '?'} — waiting for a baseline reset. "
            f"Use 'Reset trading baseline' in the Belfort controls to open a clean eval window."
        )
    if level == "evaluation":
        return (
            f"Baseline reset {reset_ts or '?'}, {trade_count} mock trade{'s' if trade_count != 1 else ''} so far, "
            f"P\u0026L {pnl_str}{wr_str}. "
            f"Still building evaluation depth before gates advance."
        )
    if level == "monitoring":
        remaining = "; ".join(g["note"] for g in failed[:2]) if failed else "all gates clear"
        return (
            f"{trade_count} trades since reset ({reset_ts or '?'}), "
            f"P\u0026L {pnl_str}{wr_str}. "
            f"To clear: {remaining}."
        )
    if level == "pre_live_candidate":
        return (
            f"All gates pass. {trade_count} trades, P\u0026L {pnl_str}{wr_str}. "
            f"This does NOT mean live trading is ready \u2014 good position for mentor review."
        )
    return "Readiness status unknown."


def _mentor_summary(
    level:           str,
    gates:           list[dict],
    trade_count:     int,
    realized_pnl:    float,
    win_rate_data:   dict,
    hours_elapsed:   float,
    last_promo:      dict | None,
    baseline_record: dict,
    strategy_desc:   str,
) -> str:
    """
    3-5 sentence mentor-ready verbal summary.
    Structured as: strategy → eval window stats → readiness stage → what's blocking → disclaimer.
    """
    promo_ts  = last_promo.get("timestamp", "")[:10] if last_promo else None
    reset_ts  = baseline_record.get("reset_at", "")[:10] if baseline_record.get("reset_at") else None

    wins      = win_rate_data.get("wins", 0)
    losses    = win_rate_data.get("losses", 0)
    total_cl  = win_rate_data.get("total_closed", 0)
    wr        = win_rate_data.get("win_rate")
    wr_part   = (f"{wr*100:.0f}% win rate ({wins}W / {losses}L out of {total_cl} closed)"
                 if wr is not None and total_cl > 0 else "no closed trades yet")

    pnl_sign  = "+" if realized_pnl >= 0 else ""
    pnl_part  = f"P\u0026L {pnl_sign}${realized_pnl:.2f}"
    elapsed   = _elapsed_label(hours_elapsed) if hours_elapsed > 0 else "recently"
    failed    = [g for g in gates if not g["pass"]]

    if level in ("not_started",):
        return (
            "Mr Belfort has not yet formally adopted a strategy from research. "
            "The next step is to run a research campaign, approve a strong result, "
            "and reset the trading baseline to open a clean evaluation window."
        )

    if level == "awaiting_reset":
        return (
            f"A strategy was adopted from research on {promo_ts or '?'}, "
            f"but the trading baseline has not been reset yet. "
            f"Resetting the baseline will open a clean evaluation window "
            f"so post-adoption performance can be tracked accurately."
        )

    sentences = []

    # 1 — what is being evaluated
    sentences.append(
        f"Mr Belfort is mock-trading a mean-reversion strategy on SPY "
        f"({strategy_desc}), adopted from research on {promo_ts or '?'}."
    )

    # 2 — eval window stats
    sentences.append(
        f"Since the baseline was reset on {reset_ts or '?'} ({elapsed} ago), "
        f"Belfort has completed {trade_count} mock trade{'s' if trade_count != 1 else ''} "
        f"with {pnl_part} and {wr_part}."
    )

    # 3 — readiness stage
    stage_map = {
        "evaluation":        "currently in the Evaluation stage \u2014 building observation depth",
        "monitoring":        "currently in the Monitoring stage \u2014 basic evaluation criteria met",
        "pre_live_candidate": "currently a Pre-Live Candidate \u2014 all readiness gates pass",
    }
    sentences.append(f"The system is {stage_map.get(level, 'at an unknown stage')}.")

    # 4 — blockers (if any)
    if failed:
        blocker_notes = [g["note"] for g in failed[:3]]
        sentences.append("Still to clear: " + "; ".join(blocker_notes) + ".")

    # 5 — disclaimer (only for non-trivial levels)
    if level in ("monitoring", "pre_live_candidate"):
        sentences.append(
            "This is all mock trading only \u2014 no real money is at risk at this stage."
        )

    return " ".join(sentences)


# ── Routes ────────────────────────────────────────────────────────────────────

def _gather_readiness() -> dict:
    """Internal: gather all state and compute readiness. Shared by both endpoints."""
    try:
        from app.portfolio import get_snapshot
        snap = get_snapshot()
    except Exception:
        snap = {"cash": _STARTING_CASH, "realized_pnl": 0.0, "trade_count": 0}

    try:
        from observability.agent_state import load_state, MR_BELFORT
        s = load_state(MR_BELFORT, "trading_researcher")
        belfort = {"status": s.status}
    except Exception:
        belfort = {"status": "unknown"}

    try:
        from app.checker import read_findings
        findings = read_findings(limit=20, include_acknowledged=False)
        checker  = {"open_warnings": len([f for f in findings if f.get("severity") == "warning"])}
    except Exception:
        checker = {"open_warnings": 0}

    try:
        p = _ROOT / "data" / "custodian_health.json"
        custodian = {"overall": json.loads(p.read_text()).get("overall", "unknown")} if p.exists() else {"overall": "unknown"}
    except Exception:
        custodian = {"overall": "unknown"}

    try:
        p = _ROOT / "data" / "sentinel_report.json"
        sentinel = {"verdict": json.loads(p.read_text()).get("verdict", "unknown")} if p.exists() else {"verdict": "unknown"}
    except Exception:
        sentinel = {"verdict": "unknown"}

    baseline_record = load_baseline_record()
    last_promo      = _last_promotion()
    strategy_desc   = _strategy_description()
    win_rate_data   = _compute_win_rate()
    exp_data        = _expectancy_data()
    regime_ctx      = _regime_context()

    reset_at      = baseline_record.get("reset_at")
    hours_elapsed = _elapsed_hours(reset_at) if reset_at else 0.0

    gates               = _evaluate_gates(snap, belfort, checker, custodian, sentinel, baseline_record, last_promo, win_rate_data, exp_data)
    level, level_label  = _compute_level(gates)
    blockers            = _top_blockers(gates)
    baseline_comparison = _baseline_comparison(baseline_record, snap, win_rate_data)
    res_triggers        = _research_triggers(snap, win_rate_data, exp_data, baseline_comparison, regime_ctx)

    trade_count  = snap.get("trade_count", 0)
    realized_pnl = snap.get("realized_pnl", 0.0)

    summary = _plain_english(
        level, gates, trade_count, realized_pnl, win_rate_data, hours_elapsed, last_promo, baseline_record
    )
    msummary = _mentor_summary(
        level, gates, trade_count, realized_pnl, win_rate_data, hours_elapsed,
        last_promo, baseline_record, strategy_desc
    )

    return {
        "level":                  level,
        "level_label":            level_label,
        "gates_passed":           sum(1 for g in gates if g["pass"]),
        "gates_total":            len(gates),
        "gates":                  gates,
        "strategy_description":   strategy_desc,
        "summary":                summary,
        "mentor_summary":         msummary,
        "trade_count":            trade_count,
        "realized_pnl":           round(realized_pnl, 2),
        "wins":                   win_rate_data["wins"],
        "losses":                 win_rate_data["losses"],
        "total_closed":           win_rate_data["total_closed"],
        "win_rate":               win_rate_data["win_rate"],
        "hours_since_reset":      round(hours_elapsed, 2) if reset_at else None,
        "last_adoption_at":       last_promo.get("timestamp") if last_promo else None,
        "last_baseline_reset_at": baseline_record.get("reset_at"),
        "blockers":               blockers,
        "baseline_comparison":    baseline_comparison,
        "regime_context":         regime_ctx,
        "expectancy_data":        exp_data,
        "research_triggers":      res_triggers,
        "timestamp":              datetime.now(timezone.utc).isoformat(),
    }


@router.get("/belfort/readiness")
def belfort_readiness() -> dict:
    """
    Belfort readiness scorecard.
    10 gates, 5 levels, win-rate, observation window, P&L quality, mentor summary.
    Deterministic — no LM calls.
    """
    return _gather_readiness()


@router.get("/belfort/mentor-summary")
def belfort_mentor_summary() -> dict:
    """
    Plain-text mentor-ready verbal summary.
    Returns {text: str, level: str, timestamp: str}.
    """
    d = _gather_readiness()
    return {
        "text":      d["mentor_summary"],
        "level":     d["level"],
        "level_label": d["level_label"],
        "timestamp": d["timestamp"],
    }
