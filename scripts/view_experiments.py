#!/usr/bin/env python3
"""
scripts/view_experiments.py

Terminal viewer for past validation runs stored in data/validation_runs/.

Usage:
    python scripts/view_experiments.py           # list all experiments
    python scripts/view_experiments.py --latest  # full detail on most recent
"""

import argparse
import json
import pathlib
import sys

VALIDATION_DIR = pathlib.Path("data/validation_runs")


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _load_records() -> list[tuple[pathlib.Path, dict]]:
    """Return all validation records sorted newest-first."""
    if not VALIDATION_DIR.exists():
        return []
    files = sorted(VALIDATION_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    records = []
    for f in files:
        try:
            records.append((f, json.loads(f.read_text())))
        except Exception:
            pass
    return records


def _decision_tag(decision: str) -> str:
    return "ACCEPTED" if decision == "ACCEPTED" else "REJECTED"


# ── Views ────────────────────────────────────────────────────────────────────────

def _print_list(records: list[tuple[pathlib.Path, dict]]) -> None:
    if not records:
        print("No validation records found.")
        return

    hdr = (
        f"{'#':>3}  {'timestamp':<22}  {'experiment':<28}  {'decision':<8}  "
        f"{'base_avg':>10}  {'cand_avg':>10}  {'avg_delta':>10}  "
        f"{'base_med':>10}  {'cand_med':>10}  {'med_delta':>10}"
    )
    sep = "-" * len(hdr)
    print(sep)
    print(hdr)
    print(sep)

    for i, (_, r) in enumerate(records, 1):
        b = r["baseline"]
        c = r["candidate"]
        avg_delta = c["avg_pnl"] - b["avg_pnl"]
        med_delta = c["median_pnl"] - b["median_pnl"]
        ts        = r["timestamp"][:19].replace("T", " ")
        name      = r["experiment_name"][:28]
        decision  = _decision_tag(r["decision"])
        print(
            f"{i:>3}  {ts:<22}  {name:<28}  {decision:<8}  "
            f"${b['avg_pnl']:>9,.0f}  ${c['avg_pnl']:>9,.0f}  "
            f"{avg_delta:>+10,.0f}  "
            f"${b['median_pnl']:>9,.0f}  ${c['median_pnl']:>9,.0f}  "
            f"{med_delta:>+10,.0f}"
        )

    print(sep)
    print(f"{len(records)} record(s)")


def _print_detail(path: pathlib.Path, r: dict) -> None:
    b = r["baseline"]
    c = r["candidate"]

    print(f"File       : {path.name}")
    print(f"Timestamp  : {r['timestamp']}")
    print(f"Experiment : {r['experiment_name']}")
    print(f"Mode       : {r.get('mode', '—')}")
    print(f"Decision   : {_decision_tag(r['decision'])}")

    if r.get("rejection_reasons"):
        print("Reasons    :")
        for reason in r["rejection_reasons"]:
            print(f"  - {reason}")

    print()

    # Aggregate stats table
    print(f"  {'metric':<12}  {'baseline':>12}  {'candidate':>12}  {'delta':>12}")
    print(f"  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*12}")
    for key, label in (
        ("avg_pnl",    "avg_pnl"),
        ("median_pnl", "median_pnl"),
        ("worst_pnl",  "worst_pnl"),
    ):
        delta = c[key] - b[key]
        sign  = "+" if delta >= 0 else ""
        print(f"  {label:<12}  ${b[key]:>11,.2f}  ${c[key]:>11,.2f}  {sign}${abs(delta):>10,.2f}")
    delta_tr = c["avg_trades"] - b["avg_trades"]
    sign_tr  = "+" if delta_tr >= 0 else ""
    print(f"  {'avg_trades':<12}  {b['avg_trades']:>12.1f}  {c['avg_trades']:>12.1f}  {sign_tr}{delta_tr:>11.1f}")

    # Candidate config snapshot
    cfg = r.get("candidate_config")
    if cfg:
        print()
        print("Candidate config:")
        for k, v in cfg.items():
            print(f"  {k}: {v}")

    # Per-run breakdown
    runs = r.get("runs", [])
    if runs:
        print()
        hdr = (
            f"{'seed':>6}  {'ticks':>5}  "
            f"{'base_pnl':>12}  {'cand_pnl':>12}  {'pnl_delta':>12}  "
            f"{'base_tr':>7}  {'cand_tr':>7}  {'tr_delta':>8}"
        )
        sep = "-" * len(hdr)
        print("Per-run breakdown:")
        print(sep)
        print(hdr)
        print(sep)
        for row in runs:
            pnl_sign = "+" if row["pnl_delta"] >= 0 else ""
            tr_sign  = "+" if row["trade_delta"] >= 0 else ""
            print(
                f"{row['seed']:>6}  {row['ticks']:>5}  "
                f"{row['base_pnl']:>12,.2f}  {row['cand_pnl']:>12,.2f}  "
                f"{pnl_sign}{row['pnl_delta']:>11,.2f}  "
                f"{row['base_trades']:>7}  {row['cand_trades']:>7}  "
                f"{tr_sign}{row['trade_delta']:>7}"
            )
        print(sep)


# ── Main ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="View past validation run records.")
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Show full details of the most recent experiment",
    )
    args = parser.parse_args()

    records = _load_records()

    if not records:
        print("No validation records found in data/validation_runs/")
        sys.exit(0)

    if args.latest:
        path, record = records[0]
        _print_detail(path, record)
    else:
        _print_list(records)


if __name__ == "__main__":
    main()
