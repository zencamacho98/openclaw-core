#!/usr/bin/env python3
"""
scripts/validate_strategy.py

Validation harness for strategy changes.
Runs the experiment across multiple seeds and tick lengths,
compares baseline vs candidate, and prints ACCEPTED or REJECTED.

Baseline  : python -m app.experiment (no extra flags)
Candidate : python -m app.experiment --use-candidate

Requires app.experiment to support --use-candidate, which loads candidate
params from data/candidate_config.json instead of the live config.

Usage:
    python scripts/validate_strategy.py
    python scripts/validate_strategy.py --experiment-name my_filter_v1
"""

import argparse
import json
import pathlib
import statistics
import subprocess
import sys
from datetime import datetime, timezone

SEEDS      = [42, 7, 99, 123, 256, 512, 777]
TICK_SIZES = [2000, 5000]
MODE       = "mean_reversion"

TRADE_FLOOR_RATIO = 0.70   # candidate avg_trades must be >= 70% of baseline

VALIDATION_DIR = pathlib.Path("data/validation_runs")
CANDIDATE_CFG  = pathlib.Path("data/candidate_config.json")

_BASE = ["python", "-m", "app.experiment", "--mode", MODE, "--no-save"]


def _run(ticks: int, seed: int, candidate: bool) -> dict:
    cmd = _BASE + ["--ticks", str(ticks), "--seed", str(seed)]
    if candidate:
        cmd.append("--use-candidate")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        label = "candidate" if candidate else "baseline"
        print(f"[ERROR] {label} seed={seed} ticks={ticks}", file=sys.stderr)
        print(proc.stderr.strip(), file=sys.stderr)
        sys.exit(1)
    return json.loads(proc.stdout)


def _collect(candidate: bool) -> list[dict]:
    results = []
    for ticks in TICK_SIZES:
        for seed in SEEDS:
            r = _run(ticks, seed, candidate)
            results.append(r)
    return results


def _print_run_table(baseline_runs: list[dict], candidate_runs: list[dict]) -> None:
    hdr = (
        f"{'seed':>6}  {'ticks':>5}  "
        f"{'base_pnl':>12}  {'cand_pnl':>12}  {'pnl_delta':>12}  "
        f"{'base_tr':>7}  {'cand_tr':>7}  {'tr_delta':>8}"
    )
    sep = "-" * len(hdr)
    print(sep)
    print(hdr)
    print(sep)
    for b, c in zip(baseline_runs, candidate_runs):
        pnl_delta = c["realized_pnl"] - b["realized_pnl"]
        tr_delta  = c["total_trades"] - b["total_trades"]
        pnl_sign  = "+" if pnl_delta >= 0 else ""
        tr_sign   = "+" if tr_delta  >= 0 else ""
        print(
            f"{b['seed']:>6}  {b['ticks']:>5}  "
            f"{b['realized_pnl']:>12,.2f}  {c['realized_pnl']:>12,.2f}  "
            f"{pnl_sign}{pnl_delta:>11,.2f}  "
            f"{b['total_trades']:>7}  {c['total_trades']:>7}  "
            f"{tr_sign}{tr_delta:>7}"
        )
    print(sep)


def _stats(results: list[dict]) -> dict:
    pnls   = [r["realized_pnl"] for r in results]
    trades = [r["total_trades"]  for r in results]
    return {
        "avg_pnl":    round(sum(pnls)   / len(pnls),  2),
        "median_pnl": round(statistics.median(pnls),  2),
        "worst_pnl":  round(min(pnls),                2),
        "avg_trades": round(sum(trades) / len(trades), 1),
        "n":          len(results),
    }


def _print_stats(label: str, s: dict) -> None:
    print(f"  {label}  ({s['n']} runs)")
    print(f"    avg_pnl    : ${s['avg_pnl']:>10,.2f}")
    print(f"    median_pnl : ${s['median_pnl']:>10,.2f}")
    print(f"    worst_pnl  : ${s['worst_pnl']:>10,.2f}")
    print(f"    avg_trades :  {s['avg_trades']:>10.1f}")


def _evaluate(b: dict, c: dict) -> tuple[bool, list[str]]:
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


def _run_rows(baseline_runs: list[dict], candidate_runs: list[dict]) -> list[dict]:
    """Build the per-run breakdown list for the saved record."""
    rows = []
    for b, c in zip(baseline_runs, candidate_runs):
        rows.append({
            "seed":           b["seed"],
            "ticks":          b["ticks"],
            "base_pnl":       b["realized_pnl"],
            "cand_pnl":       c["realized_pnl"],
            "pnl_delta":      round(c["realized_pnl"] - b["realized_pnl"], 2),
            "base_trades":    b["total_trades"],
            "cand_trades":    c["total_trades"],
            "trade_delta":    c["total_trades"] - b["total_trades"],
        })
    return rows


def _load_candidate_cfg() -> dict | None:
    try:
        return json.loads(CANDIDATE_CFG.read_text())
    except Exception:
        return None


def _save_record(
    experiment_name: str,
    baseline_stats: dict,
    candidate_stats: dict,
    accepted: bool,
    failures: list[str],
    rows: list[dict],
) -> pathlib.Path:
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now(timezone.utc)
    record = {
        "timestamp":        ts.isoformat(),
        "experiment_name":  experiment_name,
        "mode":             MODE,
        "seeds":            SEEDS,
        "tick_sizes":       TICK_SIZES,
        "trade_floor_ratio": TRADE_FLOOR_RATIO,
        "decision":         "ACCEPTED" if accepted else "REJECTED",
        "rejection_reasons": failures,
        "baseline":         baseline_stats,
        "candidate":        candidate_stats,
        "candidate_config": _load_candidate_cfg(),
        "runs":             rows,
    }
    slug = ts.strftime("%Y%m%dT%H%M%S")
    safe_name = experiment_name.replace(" ", "_")
    path = VALIDATION_DIR / f"{slug}_{safe_name}.json"
    path.write_text(json.dumps(record, indent=2))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy validation harness.")
    parser.add_argument(
        "--experiment-name",
        default="unnamed",
        help="Label for this validation run (used in saved filename and record)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Skip saving result to disk",
    )
    args = parser.parse_args()

    n_runs = len(SEEDS) * len(TICK_SIZES)
    print(f"Strategy validation — mode={MODE}  experiment={args.experiment_name}")
    print(f"Seeds     : {SEEDS}")
    print(f"Tick sizes: {TICK_SIZES}")
    print(f"Runs      : {n_runs} baseline + {n_runs} candidate = {n_runs * 2} total")
    print()

    print("Running baseline ...")
    baseline_runs = _collect(candidate=False)

    print("Running candidate ...")
    candidate_runs = _collect(candidate=True)

    b = _stats(baseline_runs)
    c = _stats(candidate_runs)

    print()
    print("Per-run breakdown")
    _print_run_table(baseline_runs, candidate_runs)
    print()
    print("-" * 50)
    _print_stats("BASELINE",  b)
    print()
    _print_stats("CANDIDATE", c)
    print("-" * 50)
    print()

    accepted, failures = _evaluate(b, c)

    if accepted:
        print("ACCEPTED")
    else:
        print("REJECTED")
        for f in failures:
            print(f"  - {f}")

    if not args.no_save:
        rows = _run_rows(baseline_runs, candidate_runs)
        path = _save_record(args.experiment_name, b, c, accepted, failures, rows)
        print(f"\nSaved → {path}")


if __name__ == "__main__":
    main()
