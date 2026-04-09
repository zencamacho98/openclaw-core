#!/usr/bin/env python3
"""
scripts/promote_candidate.py

Promotes a validated candidate configuration to the live baseline.

Flow:
  1. Load the most recent record from data/validation_runs/.
  2. Confirm decision == ACCEPTED.
  3. Show a summary and prompt for explicit confirmation.
  4. On "yes": merge the candidate params (from the validation snapshot)
     into data/strategy_config.json and report what changed.

The candidate params are taken from the validation record snapshot —
not from the live candidate_config.json — so the promotion reflects
exactly what was tested, even if the file has since been edited.
"""

import json
import pathlib
import sys

VALIDATION_DIR = pathlib.Path("data/validation_runs")
STRATEGY_CFG   = pathlib.Path("data/strategy_config.json")


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _latest_record() -> tuple[dict, pathlib.Path]:
    if not VALIDATION_DIR.exists() or not any(VALIDATION_DIR.glob("*.json")):
        print("No validation records found in data/validation_runs/", file=sys.stderr)
        sys.exit(1)
    files = sorted(VALIDATION_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    path  = files[0]
    return json.loads(path.read_text()), path


def _print_summary(record: dict) -> None:
    b = record["baseline"]
    c = record["candidate"]

    print(f"  Experiment : {record['experiment_name']}")
    print(f"  Timestamp  : {record['timestamp']}")
    print(f"  Decision   : {record['decision']}")
    print()
    print(f"  {'metric':<12}  {'baseline':>12}  {'candidate':>12}  {'delta':>12}")
    print(f"  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*12}")
    for key in ("avg_pnl", "median_pnl", "worst_pnl"):
        delta = c[key] - b[key]
        sign  = "+" if delta >= 0 else ""
        print(f"  {key:<12}  ${b[key]:>11,.2f}  ${c[key]:>11,.2f}  {sign}${abs(delta):>10,.2f}")
    delta_tr = c["avg_trades"] - b["avg_trades"]
    sign_tr  = "+" if delta_tr >= 0 else ""
    print(f"  {'avg_trades':<12}  {b['avg_trades']:>12.1f}  {c['avg_trades']:>12.1f}  {sign_tr}{delta_tr:>11.1f}")
    print()

    candidate_cfg = record.get("candidate_config")
    if candidate_cfg:
        print("  Candidate params (from validation snapshot):")
        for k, v in candidate_cfg.items():
            print(f"    {k}: {v}")
        print()


def _load_strategy_cfg() -> dict:
    if STRATEGY_CFG.exists():
        try:
            return json.loads(STRATEGY_CFG.read_text())
        except Exception:
            pass
    return {}


def _promote(candidate_cfg: dict) -> dict:
    """Merge candidate params into strategy_config.json. Returns the diff applied."""
    current = _load_strategy_cfg()
    changed = {k: v for k, v in candidate_cfg.items() if current.get(k) != v}
    merged  = {**current, **candidate_cfg}
    STRATEGY_CFG.parent.mkdir(parents=True, exist_ok=True)
    STRATEGY_CFG.write_text(json.dumps(merged, indent=2))
    return changed


# ── Main ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    record, record_path = _latest_record()

    print(f"Latest validation record: {record_path.name}")
    print()

    if record["decision"] != "ACCEPTED":
        print(f"Decision is {record['decision']} — promotion blocked.")
        for reason in record.get("rejection_reasons", []):
            print(f"  - {reason}")
        sys.exit(0)

    candidate_cfg = record.get("candidate_config")
    if not candidate_cfg:
        print("Validation record contains no candidate config snapshot — cannot promote.", file=sys.stderr)
        sys.exit(1)

    _print_summary(record)

    try:
        ans = input("Promote this candidate to baseline? [yes/no]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(0)

    if ans != "yes":
        print("Aborted.")
        sys.exit(0)

    changed = _promote(candidate_cfg)

    print()
    if changed:
        print(f"Promoted {len(changed)} param(s) → {STRATEGY_CFG}")
        for k, v in changed.items():
            old = _load_strategy_cfg().get(k, "(new)")
            print(f"  {k}: {old} → {v}")
    else:
        print("No params changed (candidate values already match baseline).")


if __name__ == "__main__":
    main()
