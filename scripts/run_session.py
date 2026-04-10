#!/usr/bin/env python3
"""
scripts/run_session.py

Bounded supervised multi-batch research session.

Runs up to --max-batches sequential research batches, automatically
directing focus using cross-batch diagnosis from the research ledger.
Stops early when any stop condition is triggered:
  - strong-tier candidate found
  - no accepted candidates in N consecutive batches
  - all experiment classes deprioritized

Policy, limits, and acceptance criteria all come from research/policy.py.
Human promotion is always a manual step.

Usage:
    python scripts/run_session.py
    python scripts/run_session.py --max-batches 3 --experiments 3
    python scripts/run_session.py --dry-run
    python scripts/run_session.py --notes "post-drawdown regime check"

What remains manual:
    python scripts/promote_candidate.py --record <path>  ← promote an accepted record
    python scripts/view_experiments.py                   ← browse validation history
    python scripts/research_cycle.py                     ← diagnosis-driven search
"""
from __future__ import annotations

import argparse
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from research.session import ResearchSession
from research.policy  import SESSION

_HARD_CAP_BATCHES = int(SESSION.get("max_batches_hard_cap", 4))
_DEFAULT_BATCHES  = int(SESSION.get("default_batches", 3))
_DEFAULT_EXP      = int(SESSION.get("default_experiments_per_batch", 3))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded supervised multi-batch research session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--max-batches", type=int, default=_DEFAULT_BATCHES,
        metavar="N",
        help=(
            f"Number of batches to run "
            f"(max {_HARD_CAP_BATCHES}, default {_DEFAULT_BATCHES})"
        ),
    )
    parser.add_argument(
        "--experiments", type=int, default=_DEFAULT_EXP,
        metavar="N",
        help=f"Experiments per batch (default {_DEFAULT_EXP})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate manifests only — no simulation, no ledger writes",
    )
    parser.add_argument(
        "--notes", type=str, default="",
        metavar="TEXT",
        help="Context note stored in the ledger and session report",
    )
    args = parser.parse_args()

    session = ResearchSession(
        max_batches=args.max_batches,
        experiments_per_batch=args.experiments,
        notes=args.notes,
        dry_run=args.dry_run,
        verbose=True,
    )

    session_report = session.run()

    session_id = session_report.get("session_id", "?")
    report_dir = _ROOT / "data" / "research_ledger" / "reports"
    md_path    = report_dir / f"{session_id}_session_report.md"
    json_path  = report_dir / f"{session_id}_session.json"

    try:
        print(f"Session report → {md_path.relative_to(_ROOT)}")
        print(f"Session JSON   → {json_path.relative_to(_ROOT)}")
    except ValueError:
        print(f"Session report → {md_path}")
        print(f"Session JSON   → {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
