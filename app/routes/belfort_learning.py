# app/routes/belfort_learning.py
#
# POST-TRADE LEARNING SUMMARY
#
# GET /belfort/learning
#   — what is hurting this strategy most right now
#   — what is helping it
#   — whether to continue, re-tune, or trigger research
#
# Design: deterministic core first, optional bounded LM interpretation second.

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()

_STARTING_CASH   = 100_000.0
_MIN_EVAL_TRADES = 5


# ── Deterministic learning analysis ──────────────────────────────────────────

def _build_learning_summary(
    snap:             dict,
    win_rate_data:    dict,
    exp_data:         dict,
    regime_ctx:       dict,
    research_triggers: dict,
) -> dict:
    """
    Deterministic post-trade learning analysis.
    Returns {hurting, helping, verdict, verdict_note, ...metrics}.
    """
    hurting = []
    helping = []

    total_closed = win_rate_data.get("total_closed", 0)
    win_rate     = win_rate_data.get("win_rate")
    expectancy   = exp_data.get("expectancy")
    avg_win      = exp_data.get("avg_win")
    avg_loss     = exp_data.get("avg_loss")
    pf           = exp_data.get("profit_factor")
    realized_pnl = snap.get("realized_pnl", 0.0)
    regime       = regime_ctx.get("label", "unknown")
    fit          = regime_ctx.get("strategy_fit", "unknown")
    warmed       = regime_ctx.get("warmed_up", False)

    # ── What's hurting ────────────────────────────────────────────────────────
    if win_rate is not None and total_closed >= _MIN_EVAL_TRADES and win_rate < 0.40:
        hurting.append(
            f"Low win rate ({win_rate*100:.0f}%) \u2014 exits too early or entries poorly timed"
        )
    if (avg_win is not None and avg_loss is not None
            and avg_loss < 0 and abs(avg_loss) > avg_win * 1.5):
        hurting.append(
            f"Loss size dominates: avg loss {avg_loss:.2f} vs avg win +{avg_win:.2f}"
        )
    if pf is not None and pf < 1.0:
        hurting.append(
            f"Profit factor {pf:.2f} \u2014 total losses exceed total gains"
        )
    if fit == "poor" and warmed:
        hurting.append(
            f"Regime mismatch: market is {regime} \u2014 MR strategy needs ranging / choppy conditions"
        )
    if realized_pnl < 0 and total_closed >= _MIN_EVAL_TRADES:
        hurting.append(
            f"Negative total P\u0026L ({realized_pnl:+.2f}) across {total_closed} closed trades"
        )

    # ── What's helping ────────────────────────────────────────────────────────
    if win_rate is not None and win_rate >= 0.50:
        helping.append(
            f"Win rate {win_rate*100:.0f}% \u2014 majority of trades are winners"
        )
    if pf is not None and pf >= 1.5:
        helping.append(
            f"Profit factor {pf:.2f} \u2014 gains meaningfully exceed losses"
        )
    if fit in ("good", "ok") and warmed:
        helping.append(
            f"Regime fit: {regime} \u2014 conditions suit mean-reversion approach"
        )
    if realized_pnl > 0 and total_closed >= _MIN_EVAL_TRADES:
        helping.append(
            f"Positive P\u0026L ({realized_pnl:+.2f}) after {total_closed} closed trades"
        )
    if expectancy is not None and expectancy > 5:
        helping.append(
            f"Positive expectancy (+{expectancy:.2f} per trade on average)"
        )

    # ── Sparse-data fallbacks ─────────────────────────────────────────────────
    if not hurting:
        if total_closed < _MIN_EVAL_TRADES:
            hurting = [f"Not enough trades yet ({total_closed}/{_MIN_EVAL_TRADES} needed for pattern analysis)"]
        else:
            hurting = ["No significant issues detected at current trade count"]
    if not helping:
        if total_closed < _MIN_EVAL_TRADES:
            helping = ["Still building evaluation history \u2014 continue trading"]
        else:
            helping = ["No clear edge signals yet \u2014 monitor as history grows"]

    # ── Verdict ───────────────────────────────────────────────────────────────
    n_hard   = research_triggers.get("count", 0)
    n_soft   = research_triggers.get("soft_count", 0)
    pressure = research_triggers.get("pressure", "none")

    if total_closed < _MIN_EVAL_TRADES:
        verdict      = "continue"
        verdict_note = f"Too early \u2014 need {_MIN_EVAL_TRADES}+ closed trades to evaluate"
    elif n_hard >= 2 or (realized_pnl < _STARTING_CASH * -0.03 and total_closed >= 10):
        verdict      = "research"
        verdict_note = "Multiple performance issues \u2014 recommend new research campaign"
    elif n_hard == 1 or (win_rate is not None and 0.30 <= win_rate < 0.40 and total_closed >= 10):
        verdict      = "tune"
        verdict_note = "Marginal performance \u2014 consider targeted parameter adjustment or research"
    elif n_soft >= 2:
        verdict      = "tune"
        verdict_note = "Weak performance signals \u2014 consider parameter tuning or focused research"
    elif n_soft == 1:
        verdict      = "monitor"
        verdict_note = "Soft performance signal \u2014 watch for sustained underperformance"
    elif realized_pnl >= 0 and (win_rate is None or win_rate >= 0.40):
        verdict      = "continue"
        verdict_note = "Performance acceptable \u2014 continue monitoring"
    else:
        verdict      = "monitor"
        verdict_note = "Mixed signals \u2014 watch for sustained underperformance"

    return {
        "hurting":       hurting,
        "helping":       helping,
        "verdict":       verdict,         # continue / tune / research / monitor
        "verdict_note":  verdict_note,
        "trade_count":   snap.get("trade_count", 0),
        "total_closed":  total_closed,
        "realized_pnl":  round(realized_pnl, 2),
        "win_rate":      win_rate,
        "expectancy":    expectancy,
        "profit_factor": pf,
        "avg_win":       avg_win,
        "avg_loss":      avg_loss,
        "regime":        regime,
        "regime_fit":    fit,
    }


# ── Pattern-to-goal enrichment helpers ───────────────────────────────────────

_ORDINALS = {2: "Second", 3: "Third", 4: "Fourth", 5: "Fifth", 6: "Sixth", 7: "Seventh"}

_KIND_LABELS = {
    "expectancy": "session with negative expectancy",
    "win_rate":   "session with low win rate",
    "pnl":        "session with negative P&L",
    "regime":     "session with regime mismatch",
    "research":   "session triggering research",
}

# Predicates: entry matches a given pattern kind?
_KIND_PRED = {
    "expectancy": lambda e: (e.get("expectancy") or 0.0) < 0.0,
    "win_rate":   lambda e: e.get("win_rate") is not None and e["win_rate"] < 0.40,
    "pnl":        lambda e: (e.get("realized_pnl") or 0.0) < 0.0,
    "regime":     lambda e: e.get("regime_fit") == "poor",
    "research":   lambda e: bool(e.get("research_triggered")),
}


def _consecutive_count(entries: list, kind: str) -> int:
    """
    Count how many of the most-recent completed sessions (newest-first) match
    the given pattern kind in an unbroken run.
    Returns 0 when there is no history or no match.
    """
    pred = _KIND_PRED.get(kind)
    if not pred or not entries:
        return 0
    count = 0
    for e in entries:   # newest-first
        if pred(e):
            count += 1
        else:
            break
    return count


def _enrich_goal_with_history(base_goal: str, kind: str, entries: list) -> str:
    """
    If the same weakness has recurred across the last N completed sessions,
    prepend an ordinal context note to the base goal.
    The current session is not yet in history, so session_num = consecutive_count + 1.

    Examples:
      n_prev=2 → "Third consecutive session with negative expectancy — {base}"
      n_prev=4 → "Fifth consecutive session with negative expectancy — {base}"
      n_prev<2 → base (no enrichment)
    """
    n_prev = _consecutive_count(entries, kind)
    if n_prev < 2:
        return base_goal
    session_num = n_prev + 1   # current session is the next in the streak
    ordinal     = _ORDINALS.get(session_num) or f"{session_num}th"
    kind_label  = _KIND_LABELS.get(kind, "underperforming session")
    return f"{ordinal} consecutive {kind_label} \u2014 {base_goal}"


# ── Trigger-derived research goal ────────────────────────────────────────────

def _derive_research_goal(
    research_triggers: dict,
    exp_data:          dict,
    win_rate_data:     dict,
    snap:              dict,
    regime_ctx:        dict,
    history_entries:   list | None = None,
) -> str | None:
    """
    Derive a compact plain-English research goal from the top active trigger.
    When history_entries are provided, enriches the goal with a repeated-pattern
    prefix if the same weakness has recurred across prior completed sessions.
    Returns None when no triggers are active.
    Priority: negative edge > sustained loss > low win rate > drawdown > regime > regression.
    """
    if not research_triggers.get("triggered"):
        return None

    reasons      = research_triggers.get("reasons", [])
    expectancy   = exp_data.get("expectancy")
    total_cl     = win_rate_data.get("total_closed", 0)
    win_rate     = win_rate_data.get("win_rate")
    realized_pnl = snap.get("realized_pnl", 0.0)
    regime       = regime_ctx.get("label", "unknown")
    hist         = history_entries or []

    # 1. Negative edge / expectancy
    if any("edge" in r or "expectancy" in r for r in reasons):
        if expectancy is not None:
            base = (
                f"Improve trade expectancy: avg {expectancy:+.2f}/trade "
                f"after {total_cl} closed \u2014 strategy has negative edge"
            )
            return _enrich_goal_with_history(base, "expectancy", hist)

    # 2. Sustained loss
    if any("Sustained loss" in r for r in reasons):
        base = (
            f"Reduce sustained losses: P\u0026L {realized_pnl:+.2f} "
            f"after {total_cl} closed trades"
        )
        return _enrich_goal_with_history(base, "pnl", hist)

    # 3. Critical win rate
    if any("win rate" in r.lower() and "regressed" not in r.lower() for r in reasons):
        if win_rate is not None:
            base = (
                f"Improve win rate: {win_rate*100:.0f}% "
                f"after {total_cl} trades \u2014 below minimum threshold"
            )
            return _enrich_goal_with_history(base, "win_rate", hist)

    # 4. Drawdown warning
    if any("Drawdown" in r for r in reasons):
        base = f"Reduce drawdown: P\u0026L {realized_pnl:+.2f} approaching safety floor"
        return _enrich_goal_with_history(base, "pnl", hist)

    # 5. Regime mismatch
    if any("Regime mismatch" in r for r in reasons):
        base = (
            f"Improve regime alignment: MR strategy underperforming "
            f"in {regime} conditions"
        )
        return _enrich_goal_with_history(base, "regime", hist)

    # 6. Win-rate regression vs baseline
    if any("regressed" in r.lower() for r in reasons):
        base = "Reverse win-rate decline vs previous session"
        return _enrich_goal_with_history(base, "win_rate", hist)

    # Fallback
    base = "Systematic strategy improvement: current performance below threshold"
    return _enrich_goal_with_history(base, "research", hist)


# ── Optional bounded LM interpretation ───────────────────────────────────────

def _lm_interpret(summary: dict) -> str | None:
    """
    2-sentence coaching note via cheap model.
    Gracefully returns None on any failure — deterministic summary is always primary.
    """
    try:
        from app.cost_warden import LMHelper
        helper = LMHelper("belfort_learning", "interpret_summary", max_tokens=120)
        wr_str  = f"{summary['win_rate']*100:.0f}%" if summary["win_rate"] is not None else "n/a"
        pf_str  = f"{summary['profit_factor']:.2f}" if summary["profit_factor"] is not None else "n/a"
        data    = (
            f"Verdict: {summary['verdict']} — {summary['verdict_note']}\n"
            f"Hurting: {'; '.join(summary['hurting'][:2]) or 'none'}\n"
            f"Helping: {'; '.join(summary['helping'][:2]) or 'none'}\n"
            f"Closed trades: {summary['total_closed']}, P&L: {summary['realized_pnl']:+.2f}, "
            f"Win rate: {wr_str}, Profit factor: {pf_str}, "
            f"Regime: {summary['regime']} ({summary['regime_fit']} fit)"
        )
        result = helper.call(
            system=(
                "You are a concise trading coach reviewing mock trading performance. "
                "Write exactly 2 sentences: first the main issue, then one actionable suggestion. "
                "No hype, no caveats, no filler."
            ),
            user=data,
        )
        return result.content if result.ok else None
    except Exception:
        return None


# ── Session snapshot (written on reset) ──────────────────────────────────────

def _build_snapshot() -> dict:
    """
    Build a learning snapshot entry for the current session.
    Called just before a baseline reset to record the ending session.
    Returns {} on any failure — caller guards with try/except.
    """
    from datetime import datetime, timezone as tz
    from app.routes.belfort_readiness import _gather_readiness, load_baseline_record

    r  = _gather_readiness()
    br = load_baseline_record()

    exp_data     = r.get("expectancy_data") or {}
    regime_ctx   = r.get("regime_context") or {}
    res_triggers = r.get("research_triggers") or {}

    snap    = {"trade_count": r["trade_count"], "realized_pnl": r["realized_pnl"]}
    wr_data = {
        "total_closed": r["total_closed"],
        "win_rate":     r["win_rate"],
        "wins":         r["wins"],
        "losses":       r["losses"],
    }
    lsummary = _build_learning_summary(snap, wr_data, exp_data, regime_ctx, res_triggers)
    from app.routes.belfort_memory import load_history as _load_hist
    goal     = _derive_research_goal(res_triggers, exp_data, wr_data, snap, regime_ctx, _load_hist(n=10))

    return {
        "timestamp":          datetime.now(tz.utc).isoformat(),
        "strategy_label":     br.get("strategy_label") or "unknown",
        "trade_count":        r.get("trade_count", 0),
        "total_closed":       r.get("total_closed", 0),
        "realized_pnl":       r.get("realized_pnl", 0.0),
        "win_rate":           r.get("win_rate"),
        "expectancy":         exp_data.get("expectancy"),
        "profit_factor":      exp_data.get("profit_factor"),
        "verdict":            lsummary.get("verdict"),
        "hurting":            (lsummary.get("hurting") or [])[:1],
        "helping":            (lsummary.get("helping") or [])[:1],
        "research_triggered": res_triggers.get("triggered", False),
        "research_goal":      goal,
        "regime":             regime_ctx.get("label", "unknown"),
        "regime_fit":         regime_ctx.get("strategy_fit", "unknown"),
        "hours_since_reset":  r.get("hours_since_reset"),
    }


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get("/belfort/learning")
def belfort_learning() -> dict:
    """
    Post-trade learning summary: what's hurting, what's helping, verdict, coach note.
    Deterministic analysis + optional bounded LM interpretation.
    """
    from app.routes.belfort_readiness import _gather_readiness

    r = _gather_readiness()

    snap = {
        "trade_count":  r["trade_count"],
        "realized_pnl": r["realized_pnl"],
    }
    wr_data = {
        "total_closed": r["total_closed"],
        "win_rate":     r["win_rate"],
        "wins":         r["wins"],
        "losses":       r["losses"],
    }

    exp_data    = r.get("expectancy_data") or {}
    regime_ctx  = r.get("regime_context") or {}
    res_triggers = r.get("research_triggers") or {}

    from app.routes.belfort_memory import load_history, build_historical_context
    entries  = load_history(n=10)
    hist_ctx = build_historical_context(entries)

    summary = _build_learning_summary(
        snap             = snap,
        win_rate_data    = wr_data,
        exp_data         = exp_data,
        regime_ctx       = regime_ctx,
        research_triggers = res_triggers,
    )

    research_goal = _derive_research_goal(res_triggers, exp_data, wr_data, snap, regime_ctx, entries)

    summary["research_goal"]      = research_goal
    summary["coach_note"]         = _lm_interpret(summary)
    summary["readiness"]          = r["level_label"]
    summary["research_triggers"]  = res_triggers
    summary["historical_context"] = hist_ctx
    summary["timestamp"]          = datetime.now(timezone.utc).isoformat()

    return summary
