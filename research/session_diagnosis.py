# research/session_diagnosis.py
#
# Cross-batch diagnosis for the session orchestrator.
#
# Reads recent ledger entries and applies deterministic, auditable rules to:
#   1. determine which experiment classes to focus on in the next batch
#   2. identify classes to temporarily deprioritize
#   3. detect the dominant failure mode across recent batches
#   4. surface stop signals for the session (no_progress, all_deprioritized)
#
# All logic is rule-based. No LLM calls, no learned weights.
# Every conclusion is traceable to a specific entry and rule.
#
# Public API:
#   load_recent_ledger_entries(n)  — read ledger, return list of entry dicts
#   diagnose_session_state(entries) — analyze entries, return diagnosis dict
#   check_stop_conditions(...)     — evaluate whether session should halt

from __future__ import annotations

import json
import pathlib
from typing import Any

from .policy import EXPERIMENT_CLASSES, SESSION, SCORING

_ROOT       = pathlib.Path(__file__).resolve().parent.parent
_LEDGER     = _ROOT / "data" / "research_ledger" / "ledger.jsonl"

_ALL_CLASSES: list[str] = list(EXPERIMENT_CLASSES.keys())

# Tier weight for stop-condition checks: higher = the result was meaningful
_TIER_WEIGHTS: dict[str, int] = {
    "strong":        4,
    "review_worthy": 3,
    "noisy":         2,
    "weak":          1,
    "rejected":      0,
}


# ── Ledger access ─────────────────────────────────────────────────────────────

def load_recent_ledger_entries(n: int | None = None) -> list[dict]:
    """
    Read the n most recent entries from ledger.jsonl, newest-first.

    Returns an empty list if the ledger does not exist or is unreadable.
    """
    if n is None:
        n = int(SESSION.get("diagnosis_lookback_entries", 8))
    if not _LEDGER.exists():
        return []
    lines = []
    try:
        lines = [l.strip() for l in _LEDGER.read_text().splitlines() if l.strip()]
    except Exception:
        return []
    entries = []
    for line in reversed(lines):   # most recent last in file → reverse for newest-first
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    return entries[:n]


# ── Diagnosis ─────────────────────────────────────────────────────────────────

def diagnose_session_state(entries: list[dict]) -> dict[str, Any]:
    """
    Analyze recent ledger entries and return a diagnosis dict.

    Args:
        entries: List of ledger entries, NEWEST FIRST.
                 Pass the output of load_recent_ledger_entries().

    Returns a dict with:
        focus_classes         — list[str]: classes to prioritize in the next batch
        deprioritized         — list[str]: classes to skip (consistent failure)
        dominant_failure      — str | None: "worst_pnl" | "median_pnl" | "trade_floor"
        session_best_score    — float: highest score seen across entries
        session_best_class    — str | None: class of that best result
        session_best_candidate — dict | None: full candidates_for_review entry if any ACCEPTED
        n_consecutive_no_progress — int: batches in a row with zero accepted
        class_stats           — dict: per-class statistics
        diagnosis_reason      — str: human-readable explanation of focus choice
    """
    if not entries:
        return _default_diagnosis("No ledger history — using default class rotation.")

    # ── Per-class statistics ─────────────────────────────────────────────────
    class_stats: dict[str, dict] = {
        cls: {
            "accepted": 0,
            "rejected": 0,
            "best_score": 0.0,
            "best_tier": "rejected",
            "consecutive_failures": 0,  # batch-level, reset on any acceptance in class
            "failure_modes": [],        # "worst_pnl" | "median_pnl" | "trade_floor"
        }
        for cls in _ALL_CLASSES
    }

    best_score  = 0.0
    best_class  = None
    best_cand   = None   # best candidates_for_review entry

    # Walk entries OLDEST first for consecutive failure tracking
    for entry in reversed(entries):
        batch_accepted_by_class: dict[str, int] = {c: 0 for c in _ALL_CLASSES}

        for exp in entry.get("experiments", []):
            cls   = exp.get("experiment_class")
            if cls not in class_stats:
                continue
            s      = class_stats[cls]
            dec    = exp.get("decision", "REJECTED")
            score  = exp.get("score") or 0.0
            tier   = exp.get("tier", "rejected")

            if dec == "ACCEPTED":
                s["accepted"] += 1
                batch_accepted_by_class[cls] += 1
            else:
                s["rejected"] += 1

            if score > s["best_score"]:
                s["best_score"] = score
                s["best_tier"]  = tier

            if score > best_score:
                best_score = score
                best_class = cls

            # Failure mode from rejection reasons
            for reason in exp.get("rejection_reasons", []):
                if "worst_pnl" in reason:
                    s["failure_modes"].append("worst_pnl")
                elif "median_pnl" in reason:
                    s["failure_modes"].append("median_pnl")
                elif "avg_trades" in reason:
                    s["failure_modes"].append("trade_floor")

        # Update consecutive failure counter per class (batch-level)
        for cls in _ALL_CLASSES:
            if batch_accepted_by_class[cls] > 0:
                class_stats[cls]["consecutive_failures"] = 0
            else:
                class_stats[cls]["consecutive_failures"] += 1

        # Track best accepted candidate artifact
        for cand in entry.get("candidates_for_review", []):
            if cand.get("decision") == "ACCEPTED":
                cand_score = cand.get("score") or 0.0
                if best_cand is None or cand_score > (best_cand.get("score") or 0.0):
                    best_cand = cand

    # ── Deprioritization logic ───────────────────────────────────────────────
    fail_threshold = int(SESSION.get("deprioritize_after_failures", 2))
    deprioritized: list[str] = []

    for cls, stats in class_stats.items():
        consec = stats["consecutive_failures"]
        worst_mode_count = stats["failure_modes"].count("worst_pnl")
        total_failures   = stats["rejected"]
        # Deprioritize if: consecutive failures >= threshold AND
        # worst_pnl is the dominant failure (> half of all failures)
        if (consec >= fail_threshold
                and total_failures > 0
                and worst_mode_count > total_failures // 2):
            deprioritized.append(cls)

    # ── Focus class selection ────────────────────────────────────────────────
    active = [c for c in _ALL_CLASSES if c not in deprioritized]

    # Among active, prefer classes with near-miss results (weak tier) in recent 3 entries
    near_miss_classes: list[str] = []
    for entry in entries[:3]:
        for exp in entry.get("experiments", []):
            cls = exp.get("experiment_class")
            if cls in active and exp.get("tier") == "weak":
                if cls not in near_miss_classes:
                    near_miss_classes.append(cls)

    focus = near_miss_classes if near_miss_classes else active

    # If all classes are deprioritized, reset (avoid infinite block)
    if not focus:
        focus       = list(_ALL_CLASSES)
        deprioritized = []

    # ── Dominant failure mode ────────────────────────────────────────────────
    all_modes: list[str] = []
    for s in class_stats.values():
        all_modes.extend(s["failure_modes"])
    dominant = max(set(all_modes), key=all_modes.count) if all_modes else None

    # ── Consecutive no-progress (newest-first) ───────────────────────────────
    n_no_progress = 0
    for entry in entries:
        if entry.get("summary", {}).get("accepted", 0) == 0:
            n_no_progress += 1
        else:
            break   # stop at first batch that had at least one acceptance

    # ── Reason string ────────────────────────────────────────────────────────
    parts: list[str] = []
    if deprioritized:
        parts.append(
            f"Deprioritizing {deprioritized} — consecutive worst-case failures"
        )
    if near_miss_classes:
        parts.append(
            f"Focusing on {near_miss_classes} — near-miss results detected"
        )
    if dominant:
        parts.append(f"Dominant failure mode: {dominant}")
    if n_no_progress >= 2:
        parts.append(f"{n_no_progress} consecutive batches with no acceptance")
    if not parts:
        parts.append("No strong signal — cycling through active classes")

    return {
        "focus_classes":             focus,
        "deprioritized":             deprioritized,
        "dominant_failure":          dominant,
        "session_best_score":        round(best_score, 1),
        "session_best_class":        best_class,
        "session_best_candidate":    best_cand,
        "n_consecutive_no_progress": n_no_progress,
        "class_stats":               class_stats,
        "diagnosis_reason":          "; ".join(parts),
    }


# ── Stop conditions ───────────────────────────────────────────────────────────

def check_stop_conditions(
    max_batches:          int,
    batches_completed:    int,
    session_batch_results: list[dict],   # batch report dicts from THIS session
    diagnosis:            dict,
    stop_on_strong:       bool | None = None,
    no_progress_threshold: int | None = None,
) -> tuple[bool, str, str]:
    """
    Evaluate whether the session should stop.

    Returns:
        (should_stop: bool, condition_name: str, human_reason: str)

    condition_name is one of:
        "max_batches_reached"      — hit the configured cap
        "strong_candidate_found"   — a "strong" tier result appeared
        "no_progress"              — no accepted in N consecutive session batches
        "all_classes_deprioritized" — nowhere left to explore
        ""                         — should not stop
    """
    if stop_on_strong is None:
        stop_on_strong = bool(SESSION.get("stop_on_strong", True))
    if no_progress_threshold is None:
        no_progress_threshold = int(SESSION.get("no_progress_stop_batches", 3))

    # 1. Max batches
    if batches_completed >= max_batches:
        return (
            True,
            "max_batches_reached",
            f"Completed {batches_completed}/{max_batches} planned batches.",
        )

    # 2. Strong candidate found in current session
    if stop_on_strong:
        for batch_report in session_batch_results:
            for r in batch_report.get("ranking", []):
                if r.get("tier") == "strong":
                    eid = r.get("experiment_id", "?")
                    cls = r.get("experiment_class", "?")
                    return (
                        True,
                        "strong_candidate_found",
                        f"Strong-tier candidate found: {eid} ({cls}) — "
                        "surface for human review before continuing.",
                    )

    # 3. No progress in current session
    consecutive = 0
    for batch_report in reversed(session_batch_results):   # oldest first
        n_accepted = batch_report.get("what_ran", {}).get("n_accepted", 0)
        if n_accepted == 0:
            consecutive += 1
        else:
            consecutive = 0   # reset
    if consecutive >= no_progress_threshold:
        return (
            True,
            "no_progress",
            f"No accepted candidates in the last {consecutive} consecutive "
            f"session batches (threshold: {no_progress_threshold}).",
        )

    # 4. All experiment classes deprioritized
    dep = diagnosis.get("deprioritized", [])
    if len(dep) >= len(_ALL_CLASSES):
        return (
            True,
            "all_classes_deprioritized",
            f"All classes ({', '.join(dep)}) have been deprioritized. "
            "Run research_cycle.py for a fresh diagnosis.",
        )

    return False, "", ""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _default_diagnosis(reason: str) -> dict[str, Any]:
    return {
        "focus_classes":             list(_ALL_CLASSES),
        "deprioritized":             [],
        "dominant_failure":          None,
        "session_best_score":        0.0,
        "session_best_class":        None,
        "session_best_candidate":    None,
        "n_consecutive_no_progress": 0,
        "class_stats":               {
            cls: {"accepted": 0, "rejected": 0, "best_score": 0.0,
                  "best_tier": "rejected", "consecutive_failures": 0, "failure_modes": []}
            for cls in _ALL_CLASSES
        },
        "diagnosis_reason": reason,
    }
