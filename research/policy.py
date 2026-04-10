# research/policy.py
#
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║         OpenClaw Research Lab — Centralized Policy Configuration        ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# This is the single human-editable file that governs the autonomous research
# loop. Adjust values here to change lab behavior.
#
# All other research/ modules import their constants from this file.
# Do NOT scatter policy values across governance.py, scoring.py, etc.
#
# SECTIONS:
#   1. Approved experiment classes and parameter bounds
#   2. Batch size and seed limits
#   3. Validation acceptance criteria
#   4. Scoring and review-readiness thresholds
#   5. Default simulation configuration

from __future__ import annotations

# ── 1. Approved experiment classes and parameter bounds ───────────────────────
#
# Each class defines which parameters are allowed to be mutated and their
# valid numeric ranges [min, max].
#
# Rules:
#   - Only parameters listed here can appear in mutated_params.
#   - Values must be within [min, max] inclusive.
#   - All unlisted parameters retain their live baseline values.
#   - Adding a new class here automatically unlocks it in governance and
#     generator. You must also add templates in generator.py.
#
# Live baseline (as of last promotion):
#   MAX_EFFICIENCY_RATIO = 0.4   TRADE_COOLDOWN      = 5
#   STOP_LOSS_PCT        = 0.015 TAKE_PROFIT_PCT     = 0.04
#   MEAN_REV_EXIT_FRACTION = 1.0 MEAN_REV_THRESHOLD  = 1.0

EXPERIMENT_CLASSES: dict[str, dict[str, list[float]]] = {

    "profit_taking": {
        # When and how aggressively to lock in gains
        "TAKE_PROFIT_PCT":        [0.01, 0.10],   # 0.03 = exit when +3% above entry
        "MEAN_REV_EXIT_FRACTION": [0.30, 1.50],   # 0.7 = exit 70% of way back to mean
    },

    "entry_quality": {
        # Filters controlling when and how deep to enter
        "MAX_EFFICIENCY_RATIO": [0.20, 0.70],   # block MR entries when ER exceeds this
        "MEAN_REV_THRESHOLD":   [0.50, 2.50],   # std devs below mean required to buy
        "TRADE_COOLDOWN":       [2.0,  15.0],   # min ticks between trades
        "MIN_VOLATILITY":       [0.0,   2.0],   # min rolling std required to enter
        "MR_CONFIRM_TICKS":     [0.0,   5.0],   # confirmation lookback ticks (0 = off)
    },

    "loss_structure": {
        # How and when to cut losses
        "STOP_LOSS_PCT":     [0.005, 0.040],   # fixed stop as fraction of entry price
        "STOP_ATR_MULT":     [0.50,  3.00],    # ATR-based stop multiplier (0 = off)
        "MIN_STOP_LOSS_PCT": [0.005, 0.020],   # floor for dynamic stops
    },
}

# ── 2. Batch size and seed limits ─────────────────────────────────────────────
#
# Adjust to change how many experiments run per batch and how many seeds
# each experiment is tested across.

BATCH: dict[str, int] = {
    "min_experiments":        3,    # minimum per batch
    "max_experiments":        5,    # hard cap per batch
    "max_params_per_experiment": 3, # prevents combinatorial explosion
    "max_seeds":             10,    # hard cap on seed list length
}

# ── 3. Validation acceptance criteria ─────────────────────────────────────────
#
# These mirror validate_strategy.py. Do NOT change these thresholds without
# also updating validate_strategy.py — divergence creates inconsistent results.
#
# Acceptance requires ALL of the following:
#   candidate median_pnl >= baseline median_pnl
#   candidate worst_pnl  >= baseline worst_pnl
#   candidate avg_trades >= baseline avg_trades × trade_floor_ratio

ACCEPTANCE: dict[str, float] = {
    "trade_floor_ratio": 0.70,   # candidate must trade at >= 70% of baseline volume
}

# ── 4. Scoring and review-readiness thresholds ────────────────────────────────
#
# Controls the 0–100 scoring formula and tier classification in scoring.py.
#
# Score composition:
#   Base:          60 (accepted) | 20 (rejected) | 38 (near-miss rejected)
#   PnL bonus:     up to max_pnl_bonus, scaled by pnl_scale
#   Worst bonus:   up to max_worst_bonus, scaled by worst_pnl_scale
#   Clean bonus:   added when result has zero quality labels and zero flags
#   Penalties:     deducted per quality label and per flagged concern
#
# Tier thresholds (score → tier label):
#   80–100  strong          Clean accepted with meaningful improvement
#   66–79   review_worthy   Accepted, mostly clean metrics
#   46–65   noisy           Accepted but quality concerns present
#   31–45   weak            Near-miss rejected or barely accepted with issues
#    0–30   rejected        Failed acceptance, no near-miss signal

SCORING: dict[str, float] = {
    # Base scores
    "base_accepted":   60.0,
    "base_rejected":   20.0,
    "base_near_miss":  38.0,   # rejected but within near_miss_pnl_pct of baseline

    # PnL improvement bonus
    "pnl_scale":       50.0,   # score_contribution = (pnl_delta / pnl_scale) * 10
    "max_pnl_bonus":   20.0,   # capped contribution from positive PnL delta

    # Worst-case improvement bonus
    "worst_pnl_scale":  100.0,
    "max_worst_bonus":  15.0,

    # Bonus for a clean result (no quality labels, no flagged concerns)
    "clean_bonus":     12.0,

    # Penalties
    "quality_label_penalty": 8.0,  # per label from trade_review.compare()
    "flag_penalty":          4.0,  # per notable concern from reviewer.py

    # Near-miss detection: rejected candidate within this fraction of baseline median
    "near_miss_pnl_pct": 0.05,   # within 5% of baseline median_pnl → near-miss

    # Tier boundaries (score must be >= threshold for that tier)
    "tier_strong":        80.0,
    "tier_review_worthy": 66.0,
    "tier_noisy":         46.0,
    "tier_weak":          31.0,
    # below tier_weak → "rejected"
}

# ── 5. Session orchestration policy ──────────────────────────────────────────
#
# Controls the multi-batch session manager in research/session.py.
# CLI arguments may override defaults but cannot exceed the hard caps.

SESSION: dict = {
    # Hard caps — enforced regardless of CLI arguments
    "max_batches_hard_cap":         4,     # session can never run more than this
    "max_experiments_hard_cap":     5,     # same as BATCH["max_experiments"]

    # Defaults when CLI does not specify
    "default_batches":              3,
    "default_experiments_per_batch": 3,    # lighter than a full standalone batch

    # Stop conditions (evaluated after each batch within the session)
    "no_progress_stop_batches":     3,     # stop if no accepted in this many consecutive batches
    "stop_on_strong":               True,  # stop early when a "strong" tier candidate appears

    # Cross-batch diagnosis
    "deprioritize_after_failures":  2,     # consecutive batch failures before class is deprioritized
    "diagnosis_lookback_entries":   8,     # how many ledger entries to use for diagnosis
}

# ── 6. Campaign orchestration policy ─────────────────────────────────────────
#
# Controls the multi-session campaign manager in research/campaign_runner.py.
# CLI arguments may override defaults but cannot exceed the hard caps.
#
# Campaign stop conditions (evaluated after each session):
#   max_sessions_reached      — sessions_completed >= max_sessions
#   max_experiments_reached   — total_experiments >= max_total_experiments
#   strong_candidate_confirmed — N sessions produced strong/review_worthy candidates
#   no_progress_campaign      — N consecutive sessions with zero accepted
#   dominant_failure_persists  — same dominant failure mode in N consecutive sessions

CAMPAIGN: dict = {
    # Hard caps — enforced regardless of CLI arguments
    "max_sessions_hard_cap":            6,
    "max_total_experiments_hard_cap": 100,

    # Defaults when CLI does not specify
    "default_sessions":                 3,
    "default_max_total_experiments":   60,

    # Campaign-level stop conditions
    "no_progress_sessions_limit":       2,   # consecutive sessions with 0 accepted → stop
    "strong_candidates_threshold":      2,   # N sessions with strong/review_worthy → stop
    "dominant_failure_sessions":        3,   # same failure mode dominates N sessions → stop
}

# ── 7. Default simulation configuration ───────────────────────────────────────
#
# Used by generator.py when no explicit seeds/tick_sizes are provided.
# Seeds and tick_sizes together determine how many runs are executed:
#   n_runs = len(seeds) × len(tick_sizes) per experiment
#   Default: 7 × 2 = 14 runs per experiment (same as validate_strategy.py)

SIMULATION: dict = {
    "default_seeds":      [42, 7, 99, 123, 256, 512, 777],
    "default_tick_sizes": [2000, 5000],
    "mode":               "mean_reversion",
}
