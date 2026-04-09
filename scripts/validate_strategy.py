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
"""

import json
import statistics
import subprocess
import sys

SEEDS      = [42, 7, 99, 123, 256, 512, 777]
TICK_SIZES = [2000, 5000]
MODE       = "mean_reversion"

TRADE_FLOOR_RATIO = 0.70   # candidate avg_trades must be >= 70% of baseline

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


def main() -> None:
    n_runs = len(SEEDS) * len(TICK_SIZES)
    print(f"Strategy validation — mode={MODE}")
    print(f"Seeds     : {SEEDS}")
    print(f"Tick sizes: {TICK_SIZES}")
    print(f"Runs      : {n_runs} baseline + {n_runs} candidate = {n_runs * 2} total")
    print()

    print("Running baseline ...")
    b = _stats(_collect(candidate=False))

    print("Running candidate ...")
    c = _stats(_collect(candidate=True))

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


if __name__ == "__main__":
    main()
