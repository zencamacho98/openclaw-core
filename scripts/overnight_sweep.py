#!/usr/bin/env python3
"""
scripts/overnight_sweep.py

Randomized grid search over strategy parameters.

For each candidate config, runs the same seeds and tick sizes as
validate_strategy.py, saves a validation record, then moves on.
Never auto-promotes. Stops at --experiments or --runtime, whichever comes first.

Usage:
    python scripts/overnight_sweep.py
    python scripts/overnight_sweep.py --experiments 30 --runtime 90
    python scripts/overnight_sweep.py --experiments 10 --shuffle-seed 42

Records are saved to data/validation_runs/ in the same format as
validate_strategy.py and are readable by scripts/view_experiments.py.
"""

from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import Any

# ── Project root on path ────────────────────────────────────────────────────────
_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.experiment import MODE_MR, _live_params, _run_ticks

# ── Sweep configuration ─────────────────────────────────────────────────────────

VALIDATION_DIR    = _ROOT / "data" / "validation_runs"
MODE              = MODE_MR
SEEDS             = [42, 7, 99, 123, 256, 512, 777]
TICK_SIZES        = [2000, 5000]
TRADE_FLOOR_RATIO = 0.70   # candidate avg_trades must be >= 70% of baseline
WORST_TOLERANCE   = 0.10   # leaderboard filter: worst_pnl can be ≤10% worse than baseline

# Search space — edit values to widen or narrow the sweep
SEARCH_SPACE: dict[str, list[Any]] = {
    "TRADE_COOLDOWN":       [5, 10, 20, 40],
    "MEAN_REV_THRESHOLD":   [0.8, 1.0, 1.2, 1.4],
    "STOP_ATR_MULT":        [1.0, 1.5, 2.0],
    "RISK_PER_TRADE_PCT":   [0.001, 0.0025, 0.005],
    "MAX_EFFICIENCY_RATIO": [0.3, 0.4, 0.5, 1.0],
}


# ── Stats helpers (match validate_strategy.py schema exactly) ───────────────────

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


# ── Acceptance & scoring ────────────────────────────────────────────────────────

def _evaluate(b: dict, c: dict) -> tuple[bool, list[str]]:
    """
    Strict acceptance — matches validate_strategy.py criteria exactly so records
    flagged ACCEPTED here will also pass the official validation harness.
    """
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
    Ranking score for the top-3 leaderboard. More lenient than _evaluate():
    allows worst_pnl to regress up to WORST_TOLERANCE from baseline.

    Returns None when the candidate exceeds the worst_pnl tolerance (excluded
    from leaderboard entirely). Otherwise returns median_pnl_delta — higher wins.
    """
    worst_budget = abs(b["worst_pnl"]) * WORST_TOLERANCE
    if c["worst_pnl"] < b["worst_pnl"] - worst_budget:
        return None
    return c["median_pnl"] - b["median_pnl"]


# ── Record saving ───────────────────────────────────────────────────────────────

def _save_record(
    name:        str,
    b:           dict,
    c:           dict,
    accepted:    bool,
    failures:    list[str],
    rows:        list[dict],
    overrides:   dict,
) -> pathlib.Path:
    """Write a validation record compatible with view_experiments.py."""
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
    slug      = ts.strftime("%Y%m%dT%H%M%S")
    safe_name = name.replace(" ", "_")[:50]
    path      = VALIDATION_DIR / f"{slug}_{safe_name}.json"
    path.write_text(json.dumps(record, indent=2))
    return path


# ── Simulation ──────────────────────────────────────────────────────────────────

def _run_all(params: dict) -> list[dict]:
    """Run all (ticks, seed) pairs. Returns list in same order every time."""
    results = []
    for ticks in TICK_SIZES:
        for seed in SEEDS:
            results.append(_run_ticks(ticks, params, seed, mode=MODE))
    return results


# ── Candidate generation ────────────────────────────────────────────────────────

def _all_combinations() -> list[dict]:
    keys   = list(SEARCH_SPACE.keys())
    values = [SEARCH_SPACE[k] for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _config_label(overrides: dict) -> str:
    return "  ".join(f"{k}={v}" for k, v in overrides.items())


# ── Main ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Overnight parameter sweep — bounded compute, no LLM, no auto-promotion.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--experiments",   type=int, default=30, metavar="N",
                        help="Max number of candidates to test")
    parser.add_argument("--runtime",       type=int, default=90, metavar="MIN",
                        help="Hard runtime cap in minutes")
    parser.add_argument("--shuffle-seed",  type=int, default=0,  metavar="S",
                        help="RNG seed for combination shuffle (0 = random)")
    args = parser.parse_args()

    MAX_N    = args.experiments
    MAX_SECS = args.runtime * 60
    rng_seed = args.shuffle_seed or random.randint(0, 2 ** 32 - 1)

    n_runs       = len(SEEDS) * len(TICK_SIZES)
    total_combos = 1
    for v in SEARCH_SPACE.values():
        total_combos *= len(v)

    SEP  = "─" * 72
    SEP2 = "═" * 72

    print(SEP2)
    print("Overnight Sweep")
    print(SEP2)
    print(f"Mode          : {MODE}")
    print(f"Seeds         : {SEEDS}")
    print(f"Tick sizes    : {TICK_SIZES}")
    print(f"Runs/cand     : {n_runs} baseline + {n_runs} candidate")
    print(f"Grid size     : {total_combos:,} combinations  →  sampling {MAX_N}")
    print(f"Caps          : {MAX_N} experiments / {args.runtime} min")
    print(f"Shuffle seed  : {rng_seed}")
    print()

    # ── Baseline (computed once, reused for every candidate) ────────────────────
    base_params   = _live_params()
    print("Computing baseline ...")
    t0            = time.monotonic()
    baseline_runs = _run_all(base_params)
    b             = _stats(baseline_runs)
    print(
        f"  avg=${b['avg_pnl']:,.2f}  median=${b['median_pnl']:,.2f}"
        f"  worst=${b['worst_pnl']:,.2f}  avg_trades={b['avg_trades']:.1f}"
        f"  ({n_runs} runs)\n"
    )

    # ── Candidate list ───────────────────────────────────────────────────────────
    rng       = random.Random(rng_seed)
    all_c     = _all_combinations()
    rng.shuffle(all_c)
    candidates = all_c[:MAX_N]

    # ── Sweep loop ───────────────────────────────────────────────────────────────
    sweep_results: list[dict] = []
    w = len(str(MAX_N))

    for i, overrides in enumerate(candidates, 1):
        elapsed = time.monotonic() - t0
        if elapsed >= MAX_SECS:
            print(f"\nRuntime cap reached ({args.runtime} min). Stopped after {i - 1} experiments.")
            break

        print(f"[{i:{w}d}/{MAX_N}] {_config_label(overrides)}")

        cand_params = {**base_params, **overrides}
        t_exp       = time.monotonic()
        cand_runs   = _run_all(cand_params)
        exp_secs    = time.monotonic() - t_exp
        c           = _stats(cand_runs)

        accepted, failures = _evaluate(b, c)
        score              = _leaderboard_score(b, c)

        med_d   = c["median_pnl"] - b["median_pnl"]
        worst_d = c["worst_pnl"]  - b["worst_pnl"]
        sm      = "+" if med_d   >= 0 else ""
        sw      = "+" if worst_d >= 0 else ""
        status  = "ACCEPTED" if accepted else "REJECTED"

        name = f"sweep_{i:03d}"
        rows = _run_rows(baseline_runs, cand_runs)
        path = _save_record(name, b, c, accepted, failures, rows, overrides)

        print(
            f"         median_delta={sm}${med_d:,.0f}  "
            f"worst_delta={sw}${worst_d:,.0f}  "
            f"avg_trades={c['avg_trades']:.1f}  "
            f"[{exp_secs:.1f}s]  → {status}"
        )
        for reason in failures:
            print(f"         - {reason}")
        print(f"         {path.relative_to(_ROOT)}")
        print()

        sweep_results.append({
            "index":     i,
            "name":      name,
            "overrides": overrides,
            "candidate": c,
            "accepted":  accepted,
            "score":     score,
            "path":      path,
        })

    # ── Summary ──────────────────────────────────────────────────────────────────
    total_elapsed = time.monotonic() - t0
    n_done        = len(sweep_results)
    n_accepted    = sum(1 for r in sweep_results if r["accepted"])

    print(SEP)
    print(f"Sweep done: {n_done} experiments in {total_elapsed:.1f}s  ({n_accepted} ACCEPTED)")
    print(SEP)
    print()

    # ── Top-3 leaderboard ────────────────────────────────────────────────────────
    scoreable = [r for r in sweep_results if r["score"] is not None]
    scoreable.sort(key=lambda r: r["score"], reverse=True)
    top3 = scoreable[:3]

    if not top3:
        print(
            "No candidates passed the worst_pnl tolerance filter "
            f"(WORST_TOLERANCE={WORST_TOLERANCE:.0%})."
        )
        print("Consider widening the search space or relaxing WORST_TOLERANCE.")
        return

    print("TOP 3 CANDIDATES  (by median_pnl improvement over baseline)")
    print(SEP)
    for rank, r in enumerate(top3, 1):
        c       = r["candidate"]
        med_d   = c["median_pnl"] - b["median_pnl"]
        worst_d = c["worst_pnl"]  - b["worst_pnl"]
        avg_d   = c["avg_pnl"]    - b["avg_pnl"]
        sm      = "+" if med_d   >= 0 else ""
        sw      = "+" if worst_d >= 0 else ""
        sa      = "+" if avg_d   >= 0 else ""
        status  = "ACCEPTED" if r["accepted"] else "REJECTED"
        rel     = r["path"].relative_to(_ROOT)

        print(f"#{rank}  [{status}]")
        print(
            f"    median_delta  {sm}${med_d:>9,.0f}   "
            f"worst_delta  {sw}${worst_d:>9,.0f}   "
            f"avg_delta  {sa}${avg_d:>9,.0f}"
        )
        print(f"    avg_trades={c['avg_trades']:.1f}  (baseline={b['avg_trades']:.1f})")
        print(f"    Config : {_config_label(r['overrides'])}")
        print(f"    Record : {rel}")
        print()

    print(SEP)
    print("Next steps (never auto-promoted — manual review required):")
    print()
    print("  1. Pick the best candidate and copy its config into data/candidate_config.json")
    print("     e.g. for #1:")
    best_cfg = json.dumps(top3[0]["overrides"], indent=4)
    for line in best_cfg.splitlines():
        print(f"       {line}")
    print()
    print("  2. Run the official validation harness:")
    print("       python scripts/validate_strategy.py --experiment-name <name>")
    print()
    print("  3. If ACCEPTED, promote:")
    print("       python scripts/promote_candidate.py")


if __name__ == "__main__":
    main()
