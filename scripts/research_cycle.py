#!/usr/bin/env python3
"""
scripts/research_cycle.py

Bounded autonomous research loop. Runs a fixed number of research cycles without
human prompting between them. Each cycle:

  1. Reads recent validation history to diagnose the dominant failure pattern.
  2. Generates a small, targeted set of candidate configs.
  3. Runs bounded in-process validation on those configs.
  4. Saves all validation records (compatible with view_experiments.py).
  5. Writes a structured cycle summary JSON to data/research_cycles/.

Guardrails:
  - --cycles capped at 5
  - --experiments-per-cycle capped at 10
  - Never auto-promotes
  - Never modifies strategy code or live config
  - No LLM calls — all diagnosis and config generation is rule-based
  - Fully deterministic given the same history state

Usage:
    python scripts/research_cycle.py
    python scripts/research_cycle.py --cycles 3 --experiments-per-cycle 5
    python scripts/research_cycle.py --cycles 1 --notes "testing tighter stops"
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import Any

# ── Project root on path ────────────────────────────────────────────────────────
_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.experiment import MODE_MR, _live_params, _run_ticks

# ── Constants ───────────────────────────────────────────────────────────────────

VALIDATION_DIR   = _ROOT / "data" / "validation_runs"
CYCLES_DIR       = _ROOT / "data" / "research_cycles"
MODE             = MODE_MR
SEEDS            = [42, 7, 99, 123, 256, 512, 777]
TICK_SIZES       = [2000, 5000]
TRADE_FLOOR_RATIO = 0.70  # must match validate_strategy.py
WORST_TOLERANCE   = 0.10  # leaderboard: worst_pnl can be ≤10% worse than baseline

MAX_CYCLES_HARD          = 5
MAX_EXPERIMENTS_HARD     = 10
HISTORY_WINDOW           = 10  # recent records to analyse per cycle

# ── Hypothesis types ────────────────────────────────────────────────────────────

HYPO_WORST_WORSE   = "worst_pnl_regression"
HYPO_MEDIAN_WORSE  = "median_pnl_regression"
HYPO_TRADE_FLOOR   = "trade_floor_breach"
HYPO_MIXED         = "mixed_failures"
HYPO_NO_HISTORY    = "no_history"
HYPO_ALL_ACCEPTED  = "all_recent_accepted"

# ── Static probe tables ─────────────────────────────────────────────────────────
# 10 entries per hypothesis; the sweep takes only --experiments-per-cycle.
# Ordered from most targeted to broadest so the first N are always the best guess.

_STATIC_PROBES: dict[str, list[dict]] = {
    HYPO_WORST_WORSE: [
        # Stop is too wide or entries in trending regimes — tighten stop and gate ER
        {"STOP_ATR_MULT": 1.0, "MAX_EFFICIENCY_RATIO": 0.4},
        {"STOP_ATR_MULT": 1.2, "MAX_EFFICIENCY_RATIO": 0.4},
        {"STOP_ATR_MULT": 1.0, "MAX_EFFICIENCY_RATIO": 0.3},
        {"STOP_ATR_MULT": 1.2, "MAX_EFFICIENCY_RATIO": 0.5},
        {"STOP_ATR_MULT": 1.5, "MAX_EFFICIENCY_RATIO": 0.3},
        {"STOP_ATR_MULT": 1.0, "TRADE_COOLDOWN": 5,  "MAX_EFFICIENCY_RATIO": 0.5},
        {"STOP_ATR_MULT": 1.2, "TRADE_COOLDOWN": 5,  "MAX_EFFICIENCY_RATIO": 0.4},
        {"STOP_ATR_MULT": 1.0, "TRADE_COOLDOWN": 10, "MAX_EFFICIENCY_RATIO": 0.4},
        {"STOP_ATR_MULT": 1.5, "TRADE_COOLDOWN": 5,  "MAX_EFFICIENCY_RATIO": 0.4},
        {"STOP_ATR_MULT": 2.0, "TRADE_COOLDOWN": 10, "MAX_EFFICIENCY_RATIO": 0.3},
    ],
    HYPO_MEDIAN_WORSE: [
        # Signal quality or sizing is off — tune threshold and risk fraction
        {"MEAN_REV_THRESHOLD": 1.2, "RISK_PER_TRADE_PCT": 0.002},
        {"MEAN_REV_THRESHOLD": 1.4, "RISK_PER_TRADE_PCT": 0.002},
        {"MEAN_REV_THRESHOLD": 1.2, "STOP_ATR_MULT": 1.5},
        {"MEAN_REV_THRESHOLD": 1.4, "STOP_ATR_MULT": 1.5},
        {"MEAN_REV_THRESHOLD": 1.0, "RISK_PER_TRADE_PCT": 0.003},
        {"MEAN_REV_THRESHOLD": 1.2, "STOP_ATR_MULT": 1.0, "MAX_EFFICIENCY_RATIO": 0.4},
        {"MEAN_REV_THRESHOLD": 1.4, "STOP_ATR_MULT": 1.0, "MAX_EFFICIENCY_RATIO": 0.4},
        {"MEAN_REV_THRESHOLD": 1.2, "TRADE_COOLDOWN": 5},
        {"MEAN_REV_THRESHOLD": 1.0, "STOP_ATR_MULT": 1.5, "MAX_EFFICIENCY_RATIO": 0.4},
        {"MEAN_REV_THRESHOLD": 0.8, "RISK_PER_TRADE_PCT": 0.001},
    ],
    HYPO_TRADE_FLOOR: [
        # Too few trades — ER gate or cooldown is over-restrictive
        {"MAX_EFFICIENCY_RATIO": 0.6, "TRADE_COOLDOWN": 5},
        {"MAX_EFFICIENCY_RATIO": 0.7, "TRADE_COOLDOWN": 5},
        {"MAX_EFFICIENCY_RATIO": 0.6, "TRADE_COOLDOWN": 3},
        {"MAX_EFFICIENCY_RATIO": 1.0, "TRADE_COOLDOWN": 5},   # disable ER gate
        {"MAX_EFFICIENCY_RATIO": 0.5, "TRADE_COOLDOWN": 3},
        {"MAX_EFFICIENCY_RATIO": 0.7, "TRADE_COOLDOWN": 10},
        {"MAX_EFFICIENCY_RATIO": 0.6, "TRADE_COOLDOWN": 10},
        {"MAX_EFFICIENCY_RATIO": 1.0, "TRADE_COOLDOWN": 3},
        {"MAX_EFFICIENCY_RATIO": 0.5, "TRADE_COOLDOWN": 5},
        {"MAX_EFFICIENCY_RATIO": 0.7, "TRADE_COOLDOWN": 20},
    ],
    HYPO_MIXED: [
        # Multiple failure modes — balanced probe across all levers
        {"TRADE_COOLDOWN": 5,  "STOP_ATR_MULT": 1.5,  "MAX_EFFICIENCY_RATIO": 0.5},
        {"TRADE_COOLDOWN": 10, "STOP_ATR_MULT": 1.2,  "MAX_EFFICIENCY_RATIO": 0.4},
        {"TRADE_COOLDOWN": 5,  "MEAN_REV_THRESHOLD": 1.2, "MAX_EFFICIENCY_RATIO": 0.5},
        {"TRADE_COOLDOWN": 3,  "STOP_ATR_MULT": 1.0,  "MAX_EFFICIENCY_RATIO": 0.6},
        {"TRADE_COOLDOWN": 5,  "RISK_PER_TRADE_PCT": 0.002, "MAX_EFFICIENCY_RATIO": 0.4},
        {"TRADE_COOLDOWN": 10, "MEAN_REV_THRESHOLD": 1.2, "STOP_ATR_MULT": 1.5},
        {"TRADE_COOLDOWN": 5,  "STOP_ATR_MULT": 1.0,  "RISK_PER_TRADE_PCT": 0.003},
        {"TRADE_COOLDOWN": 10, "STOP_ATR_MULT": 1.5,  "RISK_PER_TRADE_PCT": 0.002, "MAX_EFFICIENCY_RATIO": 0.4},
        {"TRADE_COOLDOWN": 5,  "STOP_ATR_MULT": 2.0,  "MAX_EFFICIENCY_RATIO": 0.4},
        {"TRADE_COOLDOWN": 20, "STOP_ATR_MULT": 1.5,  "MAX_EFFICIENCY_RATIO": 0.5},
    ],
    HYPO_NO_HISTORY: [
        # No history — run a broad exploratory probe
        {"TRADE_COOLDOWN": 10, "STOP_ATR_MULT": 1.5, "RISK_PER_TRADE_PCT": 0.0025},
        {"TRADE_COOLDOWN": 5,  "STOP_ATR_MULT": 1.5, "RISK_PER_TRADE_PCT": 0.0025},
        {"TRADE_COOLDOWN": 10, "MEAN_REV_THRESHOLD": 1.2, "MAX_EFFICIENCY_RATIO": 0.4},
        {"TRADE_COOLDOWN": 5,  "STOP_ATR_MULT": 1.0, "MAX_EFFICIENCY_RATIO": 0.5},
        {"TRADE_COOLDOWN": 20, "STOP_ATR_MULT": 2.0, "RISK_PER_TRADE_PCT": 0.001},
        {"TRADE_COOLDOWN": 10, "STOP_ATR_MULT": 1.0, "MAX_EFFICIENCY_RATIO": 0.4},
        {"TRADE_COOLDOWN": 5,  "MEAN_REV_THRESHOLD": 1.4, "STOP_ATR_MULT": 1.5},
        {"TRADE_COOLDOWN": 10, "RISK_PER_TRADE_PCT": 0.003, "MAX_EFFICIENCY_RATIO": 0.5},
        {"TRADE_COOLDOWN": 5,  "STOP_ATR_MULT": 1.5, "MAX_EFFICIENCY_RATIO": 0.4},
        {"TRADE_COOLDOWN": 20, "MEAN_REV_THRESHOLD": 1.2, "MAX_EFFICIENCY_RATIO": 0.5},
    ],
    HYPO_ALL_ACCEPTED: [
        # All recent runs accepted — probe for further improvement
        {"TRADE_COOLDOWN": 5,  "STOP_ATR_MULT": 1.5,  "RISK_PER_TRADE_PCT": 0.003},
        {"TRADE_COOLDOWN": 5,  "STOP_ATR_MULT": 1.2,  "RISK_PER_TRADE_PCT": 0.003},
        {"TRADE_COOLDOWN": 3,  "STOP_ATR_MULT": 1.5,  "RISK_PER_TRADE_PCT": 0.002},
        {"TRADE_COOLDOWN": 5,  "STOP_ATR_MULT": 2.0,  "MAX_EFFICIENCY_RATIO": 0.4},
        {"TRADE_COOLDOWN": 10, "MEAN_REV_THRESHOLD": 1.2, "MAX_EFFICIENCY_RATIO": 0.4},
        {"TRADE_COOLDOWN": 5,  "MEAN_REV_THRESHOLD": 1.4, "STOP_ATR_MULT": 1.5},
        {"TRADE_COOLDOWN": 3,  "STOP_ATR_MULT": 1.0,  "MAX_EFFICIENCY_RATIO": 0.5},
        {"TRADE_COOLDOWN": 10, "STOP_ATR_MULT": 1.5,  "MAX_EFFICIENCY_RATIO": 0.3},
        {"TRADE_COOLDOWN": 5,  "RISK_PER_TRADE_PCT": 0.005, "MAX_EFFICIENCY_RATIO": 0.5},
        {"TRADE_COOLDOWN": 3,  "MEAN_REV_THRESHOLD": 1.2, "MAX_EFFICIENCY_RATIO": 0.5},
    ],
}

# Grid used for neighbor probing around a known-good config
_PARAM_GRID: dict[str, list[Any]] = {
    "TRADE_COOLDOWN":       [3, 5, 10, 20, 40],
    "MEAN_REV_THRESHOLD":   [0.8, 1.0, 1.2, 1.4],
    "STOP_ATR_MULT":        [0.8, 1.0, 1.2, 1.5, 2.0],
    "RISK_PER_TRADE_PCT":   [0.001, 0.002, 0.0025, 0.003, 0.005],
    "MAX_EFFICIENCY_RATIO": [0.3, 0.4, 0.5, 0.6, 1.0],
}


# ── Diagnosis ───────────────────────────────────────────────────────────────────

def _load_recent_records(n: int = HISTORY_WINDOW) -> list[dict]:
    """Return up to `n` most recent validation records, newest-first."""
    if not VALIDATION_DIR.exists():
        return []
    files = sorted(
        VALIDATION_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    records = []
    for f in files[:n]:
        try:
            records.append(json.loads(f.read_text()))
        except Exception:
            pass
    return records


def _diagnose(records: list[dict]) -> tuple[str, str]:
    """
    Identify the dominant failure pattern from recent records.
    Returns (hypothesis_type, human-readable description).

    Logic: count how many records mention each failure keyword in
    rejection_reasons, then pick the dominant type. If two types are
    within 1 occurrence of each other, call it MIXED.
    """
    if not records:
        return HYPO_NO_HISTORY, "No experiment history found."

    n_median = 0
    n_worst  = 0
    n_trades = 0
    n_rejected = 0

    for r in records:
        if r.get("decision") != "REJECTED":
            continue
        n_rejected += 1
        for reason in r.get("rejection_reasons", []):
            if "median_pnl" in reason:
                n_median += 1
            if "worst_pnl" in reason:
                n_worst += 1
            if "avg_trades" in reason:
                n_trades += 1

    if n_rejected == 0:
        return (
            HYPO_ALL_ACCEPTED,
            f"All {len(records)} recent records ACCEPTED — probing for further improvement.",
        )

    total = n_median + n_worst + n_trades
    if total == 0:
        return HYPO_NO_HISTORY, "Recent rejections have no parseable reason strings."

    counts = {
        HYPO_WORST_WORSE:  n_worst,
        HYPO_MEDIAN_WORSE: n_median,
        HYPO_TRADE_FLOOR:  n_trades,
    }
    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top_type, top_n = ranked[0]
    _, second_n     = ranked[1]

    # Dominant only when top count is at least 2x the second
    if top_n > 0 and top_n >= 2 * max(second_n, 1):
        descriptions = {
            HYPO_WORST_WORSE: (
                f"worst_pnl regression dominated ({n_worst} occurrences) — "
                "stop distance likely too wide or entries in trending regimes."
            ),
            HYPO_MEDIAN_WORSE: (
                f"median_pnl regression dominated ({n_median} occurrences) — "
                "signal entry timing or position sizing likely suboptimal."
            ),
            HYPO_TRADE_FLOOR: (
                f"trade floor breach dominated ({n_trades} occurrences) — "
                "ER gate or cooldown is over-filtering entries."
            ),
        }
        return top_type, descriptions[top_type]

    return (
        HYPO_MIXED,
        f"Mixed failures across {n_rejected} rejected records "
        f"(median={n_median} worst={n_worst} trades={n_trades}).",
    )


# ── Probe generation ────────────────────────────────────────────────────────────

def _probes_around_best(overrides: dict, n: int) -> list[dict]:
    """
    Generate neighbor configs by varying one parameter at a time from `overrides`.
    Each neighbor changes exactly one param by one step in _PARAM_GRID.
    """
    seen: set[str] = set()
    variants: list[dict] = []

    for key, val in overrides.items():
        if key not in _PARAM_GRID:
            continue
        grid = _PARAM_GRID[key]
        # Find the closest index in the grid for the current value
        try:
            idx = grid.index(val)
        except ValueError:
            idx = min(range(len(grid)), key=lambda i: abs(grid[i] - val))
        for new_idx in (idx - 1, idx + 1):
            if 0 <= new_idx < len(grid):
                candidate = {**overrides, key: grid[new_idx]}
                key_str = json.dumps(candidate, sort_keys=True)
                if key_str not in seen:
                    seen.add(key_str)
                    variants.append(candidate)

    return variants[:n]


def _generate_probes(
    hypothesis: str,
    best_so_far: dict | None,
    n: int,
) -> list[dict]:
    """
    Return up to `n` probe configs for this cycle.

    Priority:
      1. If best_so_far is an ACCEPTED config, probe its neighbors (local search).
      2. Otherwise use the static probe table for the diagnosed hypothesis.
    """
    if best_so_far is not None and best_so_far.get("accepted"):
        neighbors = _probes_around_best(best_so_far["overrides"], n)
        if neighbors:
            return neighbors

    # Fall back to static probes for the hypothesis
    static = _STATIC_PROBES.get(hypothesis, _STATIC_PROBES[HYPO_NO_HISTORY])
    return static[:n]


# ── Simulation helpers (match validate_strategy.py schema exactly) ───────────────

def _run_all(params: dict) -> list[dict]:
    """Run all (ticks, seed) pairs in-process. Returns results in stable order."""
    results = []
    for ticks in TICK_SIZES:
        for seed in SEEDS:
            results.append(_run_ticks(ticks, params, seed, mode=MODE))
    return results


def _stats(results: list[dict]) -> dict:
    pnls   = [r["realized_pnl"] for r in results]
    trades = [r["total_trades"]  for r in results]
    return {
        "avg_pnl":    round(sum(pnls)   / len(pnls),  2),
        "median_pnl": round(statistics.median(pnls),  2),
        "worst_pnl":  round(min(pnls),                2),
        "avg_trades": round(sum(trades) / len(trades), 1),
        "n":          len(pnls),
    }


def _run_rows(baseline_runs: list[dict], candidate_runs: list[dict]) -> list[dict]:
    rows = []
    for b, c in zip(baseline_runs, candidate_runs):
        rows.append({
            "seed":        b["seed"],
            "ticks":       b["ticks"],
            "base_pnl":    b["realized_pnl"],
            "cand_pnl":    c["realized_pnl"],
            "pnl_delta":   round(c["realized_pnl"] - b["realized_pnl"], 2),
            "base_trades": b["total_trades"],
            "cand_trades": c["total_trades"],
            "trade_delta": c["total_trades"] - b["total_trades"],
        })
    return rows


def _evaluate(b: dict, c: dict) -> tuple[bool, list[str]]:
    """Strict acceptance — identical to validate_strategy.py criteria."""
    failures = []
    if c["median_pnl"] < b["median_pnl"]:
        failures.append(
            f"median_pnl ${c['median_pnl']:,.2f} < baseline ${b['median_pnl']:,.2f}"
        )
    if c["worst_pnl"] < b["worst_pnl"]:
        failures.append(
            f"worst_pnl ${c['worst_pnl']:,.2f} < baseline ${b['worst_pnl']:,.2f}"
        )
    if b["avg_trades"] > 0:
        ratio = c["avg_trades"] / b["avg_trades"]
        if ratio < TRADE_FLOOR_RATIO:
            failures.append(
                f"avg_trades {c['avg_trades']:.1f} is {ratio * 100:.0f}% of baseline "
                f"({b['avg_trades']:.1f}) — minimum {TRADE_FLOOR_RATIO * 100:.0f}%"
            )
    return len(failures) == 0, failures


def _leaderboard_score(b: dict, c: dict) -> float | None:
    """
    Ranking score used only for the per-cycle best/worst selection.
    More lenient than _evaluate(): allows worst_pnl to regress by WORST_TOLERANCE.
    Returns None if the tolerance is exceeded (candidate excluded from ranking).
    """
    budget = abs(b["worst_pnl"]) * WORST_TOLERANCE
    if c["worst_pnl"] < b["worst_pnl"] - budget:
        return None
    return c["median_pnl"] - b["median_pnl"]


# ── Persistence ──────────────────────────────────────────────────────────────────

def _save_validation_record(
    name:      str,
    b:         dict,
    c:         dict,
    accepted:  bool,
    failures:  list[str],
    rows:      list[dict],
    overrides: dict,
) -> pathlib.Path:
    """Save a validation record compatible with view_experiments.py."""
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc)
    record = {
        "timestamp":         ts.isoformat(),
        "experiment_name":   name,
        "mode":              MODE,
        "seeds":             SEEDS,
        "tick_sizes":        TICK_SIZES,
        "trade_floor_ratio": TRADE_FLOOR_RATIO,
        "decision":          "ACCEPTED" if accepted else "REJECTED",
        "rejection_reasons": failures,
        "baseline":          b,
        "candidate":         c,
        "candidate_config":  overrides,
        "runs":              rows,
    }
    slug = ts.strftime("%Y%m%dT%H%M%S")
    path = VALIDATION_DIR / f"{slug}_{name}.json"
    path.write_text(json.dumps(record, indent=2))
    return path


def _save_cycle_summary(
    session_id:  str,
    cycle_n:     int,
    hypothesis:  str,
    description: str,
    records_analyzed: int,
    b:           dict,
    probe_results: list[dict],
    notes:       str,
) -> pathlib.Path:
    """Write a cycle summary JSON to data/research_cycles/."""
    CYCLES_DIR.mkdir(parents=True, exist_ok=True)

    scoreable = [r for r in probe_results if r["score"] is not None]
    scoreable.sort(key=lambda r: r["score"], reverse=True)

    best  = scoreable[0]  if scoreable else None
    worst = scoreable[-1] if len(scoreable) > 1 else None

    def _candidate_summary(r: dict) -> dict:
        c = r["candidate"]
        return {
            "config":        r["overrides"],
            "median_pnl":    c["median_pnl"],
            "median_delta":  round(c["median_pnl"] - b["median_pnl"], 2),
            "worst_pnl":     c["worst_pnl"],
            "worst_delta":   round(c["worst_pnl"] - b["worst_pnl"], 2),
            "avg_trades":    c["avg_trades"],
            "accepted":      r["accepted"],
            "record_path":   str(r["path"].relative_to(_ROOT)),
        }

    n_accepted = sum(1 for r in probe_results if r["accepted"])

    no_pass_reason: str | None = None
    if n_accepted == 0:
        failure_sets = [r["failures"] for r in probe_results]
        all_reasons  = [reason for fs in failure_sets for reason in fs]
        if all_reasons:
            # most common failure keyword
            for kw, label in [
                ("median_pnl", "median_pnl regression"),
                ("worst_pnl",  "worst_pnl regression"),
                ("avg_trades", "trade floor breach"),
            ]:
                if any(kw in r for r in all_reasons):
                    no_pass_reason = label
                    break
        else:
            no_pass_reason = "all candidates excluded from leaderboard by worst_pnl tolerance"

    ts = datetime.now(timezone.utc)
    summary = {
        "session_id":        session_id,
        "cycle":             cycle_n,
        "timestamp":         ts.isoformat(),
        "notes":             notes,
        "hypothesis_type":   hypothesis,
        "hypothesis_description": description,
        "records_analyzed":  records_analyzed,
        "probes_tested":     len(probe_results),
        "accepted_count":    n_accepted,
        "baseline": {
            "avg_pnl":    b["avg_pnl"],
            "median_pnl": b["median_pnl"],
            "worst_pnl":  b["worst_pnl"],
            "avg_trades": b["avg_trades"],
        },
        "best_candidate":    _candidate_summary(best)  if best  else None,
        "worst_candidate":   _candidate_summary(worst) if worst else None,
        "no_pass_reason":    no_pass_reason,
        "all_results": [
            {
                "config":       r["overrides"],
                "median_delta": round(r["candidate"]["median_pnl"] - b["median_pnl"], 2),
                "worst_delta":  round(r["candidate"]["worst_pnl"]  - b["worst_pnl"],  2),
                "avg_trades":   r["candidate"]["avg_trades"],
                "accepted":     r["accepted"],
                "score":        round(r["score"], 2) if r["score"] is not None else None,
                "record_path":  str(r["path"].relative_to(_ROOT)),
            }
            for r in probe_results
        ],
    }

    path = CYCLES_DIR / f"rc_{session_id}_cycle_{cycle_n:02d}.json"
    path.write_text(json.dumps(summary, indent=2))
    return path


# ── Per-cycle logic ──────────────────────────────────────────────────────────────

def _run_cycle(
    cycle_n:      int,
    n_cycles:     int,
    n_probes:     int,
    session_id:   str,
    base_params:  dict,
    baseline_runs: list[dict],
    b:            dict,
    best_so_far:  dict | None,
    notes:        str,
) -> tuple[list[dict], dict | None]:
    """
    Execute one research cycle.
    Returns (probe_results, updated_best_so_far).
    """
    SEP  = "─" * 66
    SEP2 = "═" * 66

    print(SEP2)
    print(f" Cycle {cycle_n}/{n_cycles}   [session: {session_id}]")
    print(SEP2)

    # ── Step 1: diagnose ────────────────────────────────────────────────────────
    recent = _load_recent_records(HISTORY_WINDOW)
    hypothesis, description = _diagnose(recent)

    print(f"Analyzing {len(recent)} recent records ...")
    print(f"  Hypothesis : {hypothesis}")
    print(f"  Diagnosis  : {description}")
    print()

    # ── Step 2: generate probes ─────────────────────────────────────────────────
    probes = _generate_probes(hypothesis, best_so_far, n_probes)

    strategy = (
        f"neighbor search around best known config ({list(best_so_far['overrides'].keys())})"
        if (best_so_far and best_so_far.get("accepted"))
        else f"static probe table for {hypothesis}"
    )
    print(f"Probing {len(probes)} candidates  [{strategy}]")
    print(f"  baseline: avg=${b['avg_pnl']:,.0f}  median=${b['median_pnl']:,.0f}  worst=${b['worst_pnl']:,.0f}")
    print()

    # ── Step 3: run probes ──────────────────────────────────────────────────────
    probe_results: list[dict] = []
    w = len(str(len(probes)))

    for i, overrides in enumerate(probes, 1):
        label = "  ".join(f"{k}={v}" for k, v in overrides.items())
        print(f"[{i:{w}d}/{len(probes)}] {label}")

        cand_params = {**base_params, **overrides}
        t0          = time.monotonic()
        cand_runs   = _run_all(cand_params)
        elapsed     = time.monotonic() - t0
        c           = _stats(cand_runs)

        accepted, failures = _evaluate(b, c)
        score              = _leaderboard_score(b, c)

        med_d   = c["median_pnl"] - b["median_pnl"]
        worst_d = c["worst_pnl"]  - b["worst_pnl"]
        sm      = "+" if med_d   >= 0 else ""
        sw      = "+" if worst_d >= 0 else ""
        status  = "ACCEPTED" if accepted else "REJECTED"

        name = f"rc_c{cycle_n:02d}_p{i:02d}"
        rows = _run_rows(baseline_runs, cand_runs)
        path = _save_validation_record(name, b, c, accepted, failures, rows, overrides)

        print(
            f"         median_delta={sm}${med_d:,.0f}  "
            f"worst_delta={sw}${worst_d:,.0f}  "
            f"avg_trades={c['avg_trades']:.1f}  "
            f"[{elapsed:.1f}s]  → {status}"
        )
        for reason in failures:
            print(f"         - {reason}")
        print(f"         {path.relative_to(_ROOT)}")
        print()

        probe_results.append({
            "overrides": overrides,
            "candidate": c,
            "accepted":  accepted,
            "failures":  failures,
            "score":     score,
            "path":      path,
        })

    # ── Step 4: update best_so_far ──────────────────────────────────────────────
    for r in probe_results:
        if r["score"] is None:
            continue
        if best_so_far is None or r["score"] > best_so_far["score"]:
            best_so_far = {
                "overrides": r["overrides"],
                "score":     r["score"],
                "accepted":  r["accepted"],
                "candidate": r["candidate"],
            }

    # ── Step 5: cycle summary ───────────────────────────────────────────────────
    scoreable = [r for r in probe_results if r["score"] is not None]
    scoreable.sort(key=lambda r: r["score"], reverse=True)

    n_accepted = sum(1 for r in probe_results if r["accepted"])

    print(SEP)
    print(f"Cycle {cycle_n} complete — {len(probes)} probes, {n_accepted} ACCEPTED")

    if scoreable:
        best  = scoreable[0]
        worst = scoreable[-1]
        bmed  = best["candidate"]["median_pnl"]  - b["median_pnl"]
        bwst  = best["candidate"]["worst_pnl"]   - b["worst_pnl"]
        wmed  = worst["candidate"]["median_pnl"] - b["median_pnl"]
        wwst  = worst["candidate"]["worst_pnl"]  - b["worst_pnl"]
        sb    = "+" if bmed >= 0 else ""
        sbw   = "+" if bwst >= 0 else ""
        sw2   = "+" if wmed >= 0 else ""
        sww   = "+" if wwst >= 0 else ""
        best_label  = "  ".join(f"{k}={v}" for k, v in best["overrides"].items())
        worst_label = "  ".join(f"{k}={v}" for k, v in worst["overrides"].items())
        status_b = "ACCEPTED" if best["accepted"]  else "REJECTED"
        status_w = "ACCEPTED" if worst["accepted"] else "REJECTED"
        print(f"  Best  [{status_b}]: {best_label}")
        print(f"         median_delta={sb}${bmed:,.0f}  worst_delta={sbw}${bwst:,.0f}")
        if len(scoreable) > 1:
            print(f"  Worst [{status_w}]: {worst_label}")
            print(f"         median_delta={sw2}${wmed:,.0f}  worst_delta={sww}${wwst:,.0f}")
    else:
        print("  No candidates passed the worst_pnl tolerance — nothing scoreable.")

    summary_path = _save_cycle_summary(
        session_id, cycle_n, hypothesis, description,
        len(recent), b, probe_results, notes,
    )
    print(f"  Summary  : {summary_path.relative_to(_ROOT)}")

    return probe_results, best_so_far


# ── Main ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded autonomous research loop. "
            "Diagnoses failure patterns and probes targeted config variants "
            "across multiple cycles — no LLM, no auto-promotion."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--cycles", type=int, default=3, metavar="N",
        help=f"Number of research cycles to run (max {MAX_CYCLES_HARD})",
    )
    parser.add_argument(
        "--experiments-per-cycle", type=int, default=5, metavar="N",
        help=f"Probe configs per cycle (max {MAX_EXPERIMENTS_HARD})",
    )
    parser.add_argument(
        "--mode", default="mean_reversion",
        help="Strategy mode (only mean_reversion supported)",
    )
    parser.add_argument(
        "--notes", default="", metavar="TEXT",
        help="Free-text note saved in each cycle summary",
    )
    args = parser.parse_args()

    # ── Enforce hard caps ───────────────────────────────────────────────────────
    n_cycles  = min(args.cycles,                 MAX_CYCLES_HARD)
    n_probes  = min(args.experiments_per_cycle,  MAX_EXPERIMENTS_HARD)
    if args.cycles > MAX_CYCLES_HARD:
        print(f"[warn] --cycles {args.cycles} exceeds hard cap; clamped to {MAX_CYCLES_HARD}.")
    if args.experiments_per_cycle > MAX_EXPERIMENTS_HARD:
        print(f"[warn] --experiments-per-cycle {args.experiments_per_cycle} exceeds hard cap; clamped to {MAX_EXPERIMENTS_HARD}.")

    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    n_runs     = len(SEEDS) * len(TICK_SIZES)

    print("═" * 66)
    print("Research Cycle")
    print("═" * 66)
    print(f"Session     : {session_id}")
    print(f"Mode        : {MODE}")
    print(f"Cycles      : {n_cycles}")
    print(f"Probes/cycle: {n_probes}")
    print(f"Seeds       : {SEEDS}")
    print(f"Tick sizes  : {TICK_SIZES}")
    print(f"Runs/probe  : {n_runs} baseline + {n_runs} candidate")
    if args.notes:
        print(f"Notes       : {args.notes}")
    print()

    # ── Baseline (computed once for the whole session) ──────────────────────────
    base_params = _live_params()
    print("Computing baseline (once for all cycles) ...")
    t0             = time.monotonic()
    baseline_runs  = _run_all(base_params)
    b              = _stats(baseline_runs)
    baseline_secs  = time.monotonic() - t0
    print(
        f"  avg=${b['avg_pnl']:,.2f}  median=${b['median_pnl']:,.2f}"
        f"  worst=${b['worst_pnl']:,.2f}  avg_trades={b['avg_trades']:.1f}"
        f"  ({baseline_secs:.1f}s)\n"
    )

    # ── Cycle loop ──────────────────────────────────────────────────────────────
    best_so_far: dict | None = None
    all_probe_results: list[dict] = []

    for cycle_n in range(1, n_cycles + 1):
        cycle_results, best_so_far = _run_cycle(
            cycle_n, n_cycles, n_probes, session_id,
            base_params, baseline_runs, b, best_so_far, args.notes,
        )
        all_probe_results.extend(cycle_results)
        print()

    # ── Session summary ─────────────────────────────────────────────────────────
    total_secs = time.monotonic() - t0
    n_total    = len(all_probe_results)
    n_accepted = sum(1 for r in all_probe_results if r["accepted"])

    SEP = "─" * 66
    print("═" * 66)
    print("Session complete")
    print("═" * 66)
    print(f"  Total probes : {n_total}  ({n_accepted} ACCEPTED)")
    print(f"  Wall time    : {total_secs:.1f}s")
    print(f"  Records in   : {VALIDATION_DIR.relative_to(_ROOT)}/")
    print(f"  Summaries in : {CYCLES_DIR.relative_to(_ROOT)}/")
    print()

    scoreable = [r for r in all_probe_results if r["score"] is not None]
    scoreable.sort(key=lambda r: r["score"], reverse=True)

    if not scoreable:
        print("No candidates passed the worst_pnl tolerance filter across all cycles.")
        print("Consider adjusting WORST_TOLERANCE or widening the probe tables.")
        return

    print("TOP CANDIDATE ACROSS ALL CYCLES:")
    best = scoreable[0]
    bmed = best["candidate"]["median_pnl"] - b["median_pnl"]
    bwst = best["candidate"]["worst_pnl"]  - b["worst_pnl"]
    sb   = "+" if bmed >= 0 else ""
    sw   = "+" if bwst >= 0 else ""
    best_label = "  ".join(f"{k}={v}" for k, v in best["overrides"].items())
    status = "ACCEPTED" if best["accepted"] else "REJECTED"
    print(f"  [{status}] {best_label}")
    print(f"  median_delta={sb}${bmed:,.0f}  worst_delta={sw}${bwst:,.0f}  avg_trades={best['candidate']['avg_trades']:.1f}")
    print(f"  Record : {best['path'].relative_to(_ROOT)}")
    print()
    print(SEP)
    print("NEVER auto-promotes. Manual review required before any promotion.")
    print()
    print("Next steps:")
    print("  python scripts/view_experiments.py            # browse all records")
    print("  python scripts/view_experiments.py --latest  # inspect best result")
    if best["accepted"]:
        print()
        print("  To promote the top candidate:")
        best_cfg = json.dumps(best["overrides"], indent=4)
        print("  1. Set data/candidate_config.json:")
        for line in best_cfg.splitlines():
            print(f"       {line}")
        print("  2. python scripts/validate_strategy.py --experiment-name <name>")
        print("  3. python scripts/promote_candidate.py")


if __name__ == "__main__":
    main()
