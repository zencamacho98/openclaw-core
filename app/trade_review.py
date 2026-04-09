# app/trade_review.py
#
# Rule-based trade quality assessor.
#
# Operates on lists of _run_ticks() result dicts (produced by app.experiment).
# Every classification is deterministic — thresholds are constants, not learned.
#
# Public API:
#   review(runs)                         → metrics + flags + labels for one group
#   compare(baseline_runs, cand_runs)    → baseline + candidate reviews + comparison
#
# The returned dicts are designed to be embedded directly in validation records.

from __future__ import annotations

from typing import Any

# ── Classification thresholds ───────────────────────────────────────────────────
# Edit here to recalibrate without touching any logic.

CHURN_HIGH          = 0.08   # trades/tick: > 8% of ticks generate a trade
STOP_RATE_HIGH      = 0.40   # stop-out rate: > 40% of sells are stop-outs
WIN_RATE_WEAK       = 0.45   # win rate: < 45% of sells are profitable
LOSS_WIN_RATIO_HIGH = 1.20   # |avg_loss| / avg_win: > 1.2 means losses outsize wins
TIGHT_STOP_RATE     = 0.30   # combined with TIGHT_STOP_HOLD for "stop too tight"
TIGHT_STOP_HOLD     = 10     # avg holding ticks: < 10 ticks alongside high stop rate

# Comparative (candidate vs baseline) — flags when candidate is this much worse
COMPARE_STOP_RATE_RATIO   = 1.40   # cand stop_rate > 1.4× baseline → "more stop-outs"
COMPARE_CHURN_RATIO       = 1.30   # cand churn > 1.3× baseline → "higher churn"
COMPARE_HOLD_RATIO        = 0.65   # cand hold < 0.65× baseline → "shorter holds"
COMPARE_LOSS_WIN_RATIO    = 1.25   # cand loss/win > 1.25× baseline → "worse loss/win"

# Human-readable label strings (keyed by flag name)
_LABELS: dict[str, str] = {
    "high_churn":          "high churn",
    "losses_too_frequent": "losses too frequent",
    "wins_too_small":      "wins too small for risk",
    "stop_too_tight":      "stop loss too tight",
    "entry_quality_weak":  "entry quality weak",
}
_COMP_LABELS: dict[str, str] = {
    "more_stopouts":        "more stop-outs than baseline",
    "higher_churn":         "higher churn than baseline",
    "shorter_holds":        "holding duration shorter than baseline",
    "worse_loss_win_ratio": "loss/win ratio worse than baseline",
}


# ── Internal helpers ────────────────────────────────────────────────────────────

def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _collect(runs: list[dict], key: str, default: float = 0.0) -> list[float]:
    """Extract a numeric field from each run, skipping absent or zero-default values."""
    return [r[key] for r in runs if key in r]


def _collect_nonzero(runs: list[dict], key: str) -> list[float]:
    return [r[key] for r in runs if r.get(key, 0.0) != 0.0]


# ── Core review ─────────────────────────────────────────────────────────────────

def review(runs: list[dict]) -> dict[str, Any]:
    """
    Compute aggregate trade quality metrics and qualitative labels for a group of runs.

    Input: list of _run_ticks() result dicts (same format returned by app.experiment.run()).
    Output: {metrics, flags, labels}

    All fields use .get() with safe defaults so this works on records produced
    before the trade quality fields were added.
    """
    if not runs:
        return {"metrics": {}, "flags": {}, "labels": ["no runs"]}

    m_churn    = _mean(_collect(runs, "churn_score"))
    m_stop     = _mean(_collect(runs, "stop_loss_rate"))
    m_win_rate = _mean(_collect(runs, "win_rate"))
    m_avg_win  = _mean(_collect_nonzero(runs, "avg_win_pnl"))
    m_avg_loss = _mean(_collect_nonzero(runs, "avg_loss_pnl"))
    m_hold     = _mean(_collect_nonzero(runs, "avg_holding_ticks"))
    m_pnl_sell = _mean(_collect(runs, "avg_pnl_per_sell"))

    # Loss/win ratio: |avg_loss| / avg_win.  < 1 is good (wins bigger than losses).
    loss_win_ratio: float | None = None
    if m_avg_win is not None and m_avg_win > 0 and m_avg_loss is not None and m_avg_loss < 0:
        loss_win_ratio = round(abs(m_avg_loss) / m_avg_win, 3)

    # ── Flags ───────────────────────────────────────────────────────────────────
    flags: dict[str, bool] = {
        # Trade frequency too high — noise / overtrading
        "high_churn": (
            m_churn is not None and m_churn > CHURN_HIGH
        ),
        # Stop-outs dominate exits — risk management / entry poorly timed
        "losses_too_frequent": (
            m_stop is not None and m_stop > STOP_RATE_HIGH
        ),
        # Each individual loss larger than each individual win — negative expectancy
        "wins_too_small": (
            loss_win_ratio is not None and loss_win_ratio > LOSS_WIN_RATIO_HIGH
        ),
        # Many stops AND short holds — stop too close to entry, triggered by noise
        "stop_too_tight": (
            m_stop is not None and m_stop > TIGHT_STOP_RATE
            and m_hold is not None and m_hold < TIGHT_STOP_HOLD
        ),
        # Win rate weak AND overall PnL negative — entries are poorly timed
        "entry_quality_weak": (
            m_win_rate is not None and m_win_rate < WIN_RATE_WEAK
            and m_pnl_sell is not None and m_pnl_sell < 0
        ),
    }

    labels = [_LABELS[k] for k, v in flags.items() if v]

    def _r(x: float | None, n: int = 4) -> float | None:
        return round(x, n) if x is not None else None

    return {
        "metrics": {
            "avg_churn_score":   _r(m_churn),
            "avg_stop_rate":     _r(m_stop),
            "avg_win_rate":      _r(m_win_rate),
            "avg_win_pnl":       _r(m_avg_win,  2),
            "avg_loss_pnl":      _r(m_avg_loss, 2),
            "loss_win_ratio":    loss_win_ratio,
            "avg_holding_ticks": _r(m_hold, 1),
            "avg_pnl_per_sell":  _r(m_pnl_sell, 2),
        },
        "flags":  flags,
        "labels": labels,
    }


# ── Comparative review ──────────────────────────────────────────────────────────

def compare(
    baseline_runs: list[dict],
    candidate_runs: list[dict],
) -> dict[str, Any]:
    """
    Review both groups and add comparative diagnostics.

    Returns:
        baseline          → review(baseline_runs)
        candidate         → review(candidate_runs)
        candidate_labels  → labels from the candidate review alone
        comparative_labels→ extra labels that only make sense vs. baseline
        all_labels        → union of candidate_labels + comparative_labels
    """
    base_rv = review(baseline_runs)
    cand_rv = review(candidate_runs)

    bm = base_rv["metrics"]
    cm = cand_rv["metrics"]

    def _ratio_exceeds(cand_val, base_val, threshold: float) -> bool:
        """Return True when cand_val / base_val >= threshold and base_val is nonzero."""
        return (
            cand_val is not None
            and base_val is not None
            and base_val != 0
            and cand_val / base_val >= threshold
        )

    def _ratio_below(cand_val, base_val, threshold: float) -> bool:
        return (
            cand_val is not None
            and base_val is not None
            and base_val != 0
            and cand_val / base_val <= threshold
        )

    comp_flags: dict[str, bool] = {
        "more_stopouts": (
            _ratio_exceeds(cm["avg_stop_rate"], bm["avg_stop_rate"], COMPARE_STOP_RATE_RATIO)
            and (cm["avg_stop_rate"] or 0) > 0.20
        ),
        "higher_churn": (
            _ratio_exceeds(cm["avg_churn_score"], bm["avg_churn_score"], COMPARE_CHURN_RATIO)
            and (cm["avg_churn_score"] or 0) > CHURN_HIGH * 0.75
        ),
        "shorter_holds": (
            _ratio_below(cm["avg_holding_ticks"], bm["avg_holding_ticks"], COMPARE_HOLD_RATIO)
            and (bm["avg_holding_ticks"] or 0) > 0
        ),
        "worse_loss_win_ratio": (
            cm["loss_win_ratio"] is not None
            and bm["loss_win_ratio"] is not None
            and cm["loss_win_ratio"] / bm["loss_win_ratio"] >= COMPARE_LOSS_WIN_RATIO
        ),
    }

    comp_labels   = [_COMP_LABELS[k] for k, v in comp_flags.items() if v]
    all_labels    = cand_rv["labels"] + comp_labels

    return {
        "baseline":           base_rv,
        "candidate":          cand_rv,
        "candidate_labels":   cand_rv["labels"],
        "comparative_labels": comp_labels,
        "all_labels":         all_labels,
    }
