# research/scoring.py
#
# Scoring and review-readiness classification for experiment results.
#
# The score (0–100) is a transparent, interpretable composite built from
# metrics already produced by the validation + review pipeline. There are no
# learned weights or black-box models — every point added or deducted has a
# named reason.
#
# Scoring formula:
#   Base:        60 (accepted) | 38 (near-miss rejected) | 20 (rejected)
#   PnL bonus:   proportional to median PnL improvement, capped
#   Worst bonus: proportional to worst-case PnL improvement, capped
#   Clean bonus: added when result has no quality labels and no flags
#   Penalties:   quality_label_penalty × n_labels + flag_penalty × n_flags
#
# Tier mapping:
#   Score 80–100  →  strong          (accepted, clean, meaningful improvement)
#   Score 66–79   →  review_worthy   (accepted, mostly clean)
#   Score 46–65   →  noisy           (accepted but quality concerns)
#   Score 31–45   →  weak            (near-miss rejected or barely accepted)
#   Score  0–30   →  rejected        (failed criteria, no near-miss)
#
# All thresholds and weights live in research/policy.py under SCORING.

from __future__ import annotations

from typing import Any

from .policy import SCORING as _S


# ── Tier definitions (order matters — checked from highest threshold down) ────

_TIERS: list[tuple[float, str]] = [
    (_S["tier_strong"],        "strong"),
    (_S["tier_review_worthy"], "review_worthy"),
    (_S["tier_noisy"],         "noisy"),
    (_S["tier_weak"],          "weak"),
    (0.0,                      "rejected"),
]


# ── Public API ────────────────────────────────────────────────────────────────

def score_experiment(diagnostic: dict[str, Any]) -> tuple[float, str]:
    """
    Score one experiment result and return a (score, tier) pair.

    Args:
        diagnostic: output of reviewer.extract_diagnostics() — must include
                    'decision', 'pnl_delta', 'worst_pnl_delta',
                    'quality_labels', 'flags', and 'baseline_median_pnl'.

    Returns:
        (score, tier) where score is 0.0–100.0 and tier is one of:
        "strong", "review_worthy", "noisy", "weak", "rejected"
    """
    decision    = diagnostic.get("decision", "REJECTED")
    n_labels    = len(diagnostic.get("quality_labels", []))
    n_flags     = len(diagnostic.get("flags", []))
    pnl_delta   = diagnostic.get("pnl_delta")   or 0.0
    worst_delta = diagnostic.get("worst_pnl_delta") or 0.0
    b_median    = diagnostic.get("baseline_median_pnl") or 0.0

    if decision == "ACCEPTED":
        base = _S["base_accepted"]

        # PnL improvement bonus (only positive delta rewarded)
        pnl_bonus = min(
            max(pnl_delta, 0.0) / _S["pnl_scale"] * 10.0,
            _S["max_pnl_bonus"],
        )

        # Worst-case improvement bonus (only positive delta rewarded)
        worst_bonus = min(
            max(worst_delta, 0.0) / _S["worst_pnl_scale"] * 10.0,
            _S["max_worst_bonus"],
        )

        # Clean bonus — no quality flags, no flagged concerns
        clean_bonus = _S["clean_bonus"] if (n_labels == 0 and n_flags == 0) else 0.0

        # Penalties for quality issues
        penalties = n_labels * _S["quality_label_penalty"] + n_flags * _S["flag_penalty"]

        raw = base + pnl_bonus + worst_bonus + clean_bonus - penalties

    else:
        # Rejected — check for near-miss
        is_near_miss = False
        if b_median > 0 and pnl_delta < 0:
            loss_pct = abs(pnl_delta) / b_median
            is_near_miss = loss_pct <= _S["near_miss_pnl_pct"]
        # Also near-miss if pnl_delta is 0 but rejected on worst_pnl or trade floor
        elif pnl_delta >= 0:
            is_near_miss = True

        base = _S["base_near_miss"] if is_near_miss else _S["base_rejected"]
        penalties = n_flags * _S["flag_penalty"]
        raw = base - penalties

    score = max(0.0, min(100.0, raw))
    tier  = _classify_tier(score)
    return round(score, 1), tier


def score_breakdown(diagnostic: dict[str, Any]) -> dict[str, Any]:
    """
    Return a full breakdown of how the score was computed.
    Useful for debugging and transparency.
    """
    decision    = diagnostic.get("decision", "REJECTED")
    n_labels    = len(diagnostic.get("quality_labels", []))
    n_flags     = len(diagnostic.get("flags", []))
    pnl_delta   = diagnostic.get("pnl_delta")   or 0.0
    worst_delta = diagnostic.get("worst_pnl_delta") or 0.0
    b_median    = diagnostic.get("baseline_median_pnl") or 0.0

    if decision == "ACCEPTED":
        base        = _S["base_accepted"]
        pnl_bonus   = min(max(pnl_delta, 0.0) / _S["pnl_scale"] * 10.0, _S["max_pnl_bonus"])
        worst_bonus = min(max(worst_delta, 0.0) / _S["worst_pnl_scale"] * 10.0, _S["max_worst_bonus"])
        clean_bonus = _S["clean_bonus"] if (n_labels == 0 and n_flags == 0) else 0.0
        penalties   = n_labels * _S["quality_label_penalty"] + n_flags * _S["flag_penalty"]
        near_miss   = False
    else:
        pnl_bonus = worst_bonus = clean_bonus = 0.0
        near_miss = (pnl_delta >= 0) or (b_median > 0 and abs(pnl_delta) / b_median <= _S["near_miss_pnl_pct"])
        base      = _S["base_near_miss"] if near_miss else _S["base_rejected"]
        penalties = n_flags * _S["flag_penalty"]

    raw   = base + pnl_bonus + worst_bonus + clean_bonus - penalties
    score = max(0.0, min(100.0, raw))

    return {
        "score":        round(score, 1),
        "tier":         _classify_tier(score),
        "base":         base,
        "pnl_bonus":    round(pnl_bonus, 2),
        "worst_bonus":  round(worst_bonus, 2),
        "clean_bonus":  clean_bonus,
        "penalties":    round(penalties, 2),
        "near_miss":    near_miss,
        "n_labels":     n_labels,
        "n_flags":      n_flags,
    }


def rank_batch(
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Score all experiments in a batch and return them sorted by score (desc).

    Each entry in the returned list contains:
        experiment_id, experiment_class, score, tier, decision,
        pnl_delta, worst_pnl_delta, candidate_config
    """
    ranked = []
    for d in diagnostics:
        score, tier = score_experiment(d)
        ranked.append({
            "experiment_id":    d.get("experiment_id", "unknown"),
            "experiment_class": d.get("experiment_class"),
            "score":            score,
            "tier":             tier,
            "decision":         d.get("decision"),
            "pnl_delta":        d.get("pnl_delta"),
            "worst_pnl_delta":  d.get("worst_pnl_delta"),
            "candidate_config": d.get("candidate_config", {}),
        })
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


# ── Internal helpers ──────────────────────────────────────────────────────────

def _classify_tier(score: float) -> str:
    for threshold, label in _TIERS:
        if score >= threshold:
            return label
    return "rejected"
