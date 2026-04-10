# research/reviewer.py
#
# Post-run diagnostic extractor and insight synthesizer.
#
# extract_diagnostics() — converts a validation record into a flat structured
#   diagnostic dict. All fields are safe to access; missing data produces None.
#
# synthesize_insight() — derives a major_learning string and a
#   revisit_recommendation from a diagnostic dict. Both are rule-based
#   and deterministic — no LLM calls.
#
# Nothing here modifies state. Input is a dict; output is a dict.

from __future__ import annotations

from typing import Any


# ── Diagnostic extraction ─────────────────────────────────────────────────────

def extract_diagnostics(record: dict[str, Any]) -> dict[str, Any]:
    """
    Extract a structured diagnostic summary from one validation record.

    Returned fields
    ───────────────
    Identity:
      experiment_id       — from record (or None)
      experiment_class    — profit_taking | entry_quality | loss_structure
      hypothesis          — the stated hypothesis
      candidate_config    — param overrides tested
      rejection_reasons   — list of failure strings (empty if accepted)

    Core outcome:
      decision            — ACCEPTED | REJECTED

    PnL structure:
      baseline_median_pnl — baseline median PnL (for scoring near-miss)
      pnl_delta           — candidate median_pnl − baseline median_pnl
      worst_pnl_delta     — candidate worst_pnl − baseline worst_pnl
      trade_count_change  — candidate avg_trades − baseline avg_trades

    Trade quality changes (candidate vs baseline):
      churn_change        — avg_churn_score delta (+ = more churn)
      stop_rate_change    — avg_stop_rate delta   (+ = more stop-outs)
      win_rate_change     — avg_win_rate delta    (+ = better win rate)
      loss_win_ratio_change — loss/win ratio delta (+ = ratio worsened)

    Winner / loser structure:
      avg_winner          — candidate mean winning trade PnL
      avg_loser           — candidate mean losing trade PnL

    Qualitative:
      worst_case_behavior — text: "improved by $X" or "degraded by $X"
      quality_labels      — all trade-quality flags from trade_review.compare()
      assessment          — "robust" | "marginal" | "noisy" | "rejected"
      flags               — specific concerns worth human attention
    """
    b  = record.get("baseline",  {})
    c  = record.get("candidate", {})
    tr = record.get("trade_review", {})

    bm = tr.get("baseline",  {}).get("metrics", {})
    cm = tr.get("candidate", {}).get("metrics", {})
    all_labels: list[str] = tr.get("all_labels", [])

    pnl_delta   = _delta(c.get("median_pnl"), b.get("median_pnl"))
    worst_delta = _delta(c.get("worst_pnl"),  b.get("worst_pnl"))
    trade_delta = _delta(c.get("avg_trades"), b.get("avg_trades"))

    churn_change     = _delta(cm.get("avg_churn_score"),   bm.get("avg_churn_score"))
    stop_rate_change = _delta(cm.get("avg_stop_rate"),     bm.get("avg_stop_rate"))
    win_rate_change  = _delta(cm.get("avg_win_rate"),      bm.get("avg_win_rate"))
    loss_win_change  = _delta(cm.get("loss_win_ratio"),    bm.get("loss_win_ratio"))

    avg_winner = cm.get("avg_win_pnl")
    avg_loser  = cm.get("avg_loss_pnl")

    # Worst-case text
    cand_worst = c.get("worst_pnl", 0.0)
    if worst_delta is not None:
        if worst_delta >= 0:
            worst_case = (
                f"improved by ${worst_delta:,.2f} "
                f"(candidate worst: ${cand_worst:,.2f})"
            )
        else:
            worst_case = (
                f"degraded by ${abs(worst_delta):,.2f} "
                f"(candidate worst: ${cand_worst:,.2f})"
            )
    else:
        worst_case = "unknown"

    # Simple assessment (pre-scoring rough label)
    decision = record.get("decision", "REJECTED")
    if decision == "ACCEPTED":
        n_labels = len(all_labels)
        if n_labels == 0 and (pnl_delta or 0) >= 0 and (worst_delta or 0) >= 0:
            assessment = "robust"
        elif n_labels <= 1:
            assessment = "marginal"
        else:
            assessment = "noisy"
    else:
        assessment = "rejected"

    # Notable flags
    flags: list[str] = []
    if stop_rate_change is not None and stop_rate_change > 0.05:
        flags.append(
            f"stop rate increased by {stop_rate_change:.1%} "
            f"({bm.get('avg_stop_rate', 0):.1%} → {cm.get('avg_stop_rate', 0):.1%})"
        )
    if churn_change is not None and churn_change > 0.01:
        flags.append(
            f"churn increased by {churn_change:.4f} "
            f"({bm.get('avg_churn_score', 0):.4f} → {cm.get('avg_churn_score', 0):.4f})"
        )
    if win_rate_change is not None and win_rate_change < -0.05:
        flags.append(
            f"win rate fell by {abs(win_rate_change):.1%} "
            f"({bm.get('avg_win_rate', 0):.1%} → {cm.get('avg_win_rate', 0):.1%})"
        )
    if trade_delta is not None and trade_delta < -15:
        flags.append(
            f"significantly fewer trades ({trade_delta:+.0f} avg vs baseline)"
        )
    if loss_win_change is not None and loss_win_change > 0.15:
        flags.append(
            f"loss/win ratio worsened by {loss_win_change:.3f} "
            f"({bm.get('loss_win_ratio', '?')} → {cm.get('loss_win_ratio', '?')})"
        )

    return {
        # Identity
        "experiment_id":      record.get("experiment_id"),
        "experiment_class":   record.get("experiment_class"),
        "hypothesis":         record.get("hypothesis"),
        "candidate_config":   record.get("candidate_config", {}),
        "rejection_reasons":  record.get("rejection_reasons", []),
        # Outcome
        "decision":           decision,
        # Baseline reference (for scoring)
        "baseline_median_pnl": _r(b.get("median_pnl"), 2),
        # PnL
        "pnl_delta":          _r(pnl_delta,   2),
        "worst_pnl_delta":    _r(worst_delta, 2),
        "trade_count_change": _r(trade_delta, 1),
        # Trade quality
        "churn_change":       _r(churn_change,     4),
        "stop_rate_change":   _r(stop_rate_change, 4),
        "win_rate_change":    _r(win_rate_change,  4),
        "loss_win_ratio_change": _r(loss_win_change, 4),
        # Structure
        "avg_winner":         avg_winner,
        "avg_loser":          avg_loser,
        # Qualitative
        "worst_case_behavior": worst_case,
        "quality_labels":     all_labels,
        "assessment":         assessment,
        "flags":              flags,
    }


# ── Insight synthesis ─────────────────────────────────────────────────────────

def synthesize_insight(diagnostic: dict[str, Any]) -> dict[str, str]:
    """
    Derive a major_learning and revisit_recommendation from a diagnostic.

    These are rule-based and deterministic — not LLM-generated.

    Returns:
        {
            "major_learning":         str — concise single-sentence insight
            "revisit_recommendation": str — "yes" | "no" | "deprioritize"
        }
    """
    decision      = diagnostic.get("decision", "REJECTED")
    exp_class     = diagnostic.get("experiment_class", "unknown")
    pnl_delta     = diagnostic.get("pnl_delta") or 0.0
    worst_delta   = diagnostic.get("worst_pnl_delta") or 0.0
    stop_change   = diagnostic.get("stop_rate_change") or 0.0
    trade_change  = diagnostic.get("trade_count_change") or 0.0
    churn_change  = diagnostic.get("churn_change") or 0.0
    quality_labels = diagnostic.get("quality_labels", [])
    flags          = diagnostic.get("flags", [])
    b_median       = diagnostic.get("baseline_median_pnl") or 0.0

    learning: str
    revisit: str

    if decision == "ACCEPTED":
        if len(quality_labels) == 0 and pnl_delta > 0 and worst_delta >= 0:
            learning = (
                f"Clean acceptance on {exp_class}: "
                f"PnL improved ${pnl_delta:+.0f} and worst-case held. "
                "Candidate appears robust across seeds."
            )
            revisit = "yes"

        elif len(quality_labels) == 0 and pnl_delta >= 0:
            learning = (
                f"Accepted on {exp_class} with no quality flags but minimal PnL delta "
                f"(${pnl_delta:+.0f}). Safe to promote but improvement is marginal."
            )
            revisit = "yes"

        elif stop_change > 0.08 and "more stop-outs than baseline" in quality_labels:
            learning = (
                f"Accepted on {exp_class} but stop rate increased sharply "
                f"({stop_change:.1%}). Win rate may suffer under sustained trending. "
                "Review before promoting."
            )
            revisit = "yes"

        elif churn_change > 0.015:
            learning = (
                f"Accepted on {exp_class} but churn increased noticeably "
                f"({churn_change:.4f} delta). Overtrading risk present — "
                "check if cooldown adjustment is warranted."
            )
            revisit = "yes"

        elif len(quality_labels) > 1:
            learning = (
                f"Accepted on {exp_class} but shows {len(quality_labels)} quality flags: "
                f"{', '.join(quality_labels)}. Multiple concerns — "
                "scrutinize before promoting."
            )
            revisit = "yes"

        else:
            learning = (
                f"Accepted on {exp_class} with {len(quality_labels)} quality flag(s). "
                "Adequate but not clean — assess whether the quality tradeoff is acceptable."
            )
            revisit = "yes"

    else:
        # REJECTED
        near_miss = (pnl_delta >= 0) or (b_median > 0 and abs(pnl_delta) / b_median <= 0.05)

        if near_miss and stop_change < 0:
            learning = (
                f"Near-miss rejection on {exp_class}: "
                f"PnL loss only ${abs(pnl_delta):.0f} below baseline. "
                "Stop rate actually improved — small parameter adjustment may pass."
            )
            revisit = "yes"

        elif near_miss:
            learning = (
                f"Near-miss rejection on {exp_class}: "
                f"delta only ${abs(pnl_delta):.0f}. A small further shift "
                "in the same direction may be worth testing."
            )
            revisit = "yes"

        elif trade_change < -20:
            learning = (
                f"Rejected on {exp_class}: trade count fell {trade_change:.0f} "
                "below the 70% floor. Entry filter is too restrictive at these values. "
                "Relax the filter or combine with a smaller cooldown change."
            )
            revisit = "deprioritize"

        elif worst_delta is not None and worst_delta < -300:
            learning = (
                f"Rejected on {exp_class}: worst-case degraded by "
                f"${abs(worst_delta):,.0f}. Significant tail-risk increase — "
                "this parameter direction makes the strategy fragile."
            )
            revisit = "no"

        elif stop_change > 0.10:
            learning = (
                f"Rejected on {exp_class}: stop rate increased {stop_change:.1%}. "
                "This parameter configuration produces excessive stop-outs — "
                "consider looser stop or different entry timing."
            )
            revisit = "deprioritize"

        elif pnl_delta < -200:
            learning = (
                f"Clear rejection on {exp_class}: "
                f"PnL degraded ${abs(pnl_delta):,.0f} vs baseline. "
                "This direction is not viable — deprioritize this parameter change."
            )
            revisit = "no"

        else:
            learning = (
                f"Rejected on {exp_class} without a dominant failure signal. "
                f"PnL delta: ${pnl_delta:+.0f}, worst delta: ${worst_delta:+.0f}. "
                "May be worth revisiting with a different parameter value."
            )
            revisit = "deprioritize"

    return {
        "major_learning":         learning,
        "revisit_recommendation": revisit,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b


def _r(x: float | None, n: int) -> float | None:
    return round(x, n) if x is not None else None
