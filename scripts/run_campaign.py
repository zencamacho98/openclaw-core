#!/usr/bin/env python3
"""
scripts/run_campaign.py

Bounded autonomous research campaign manager.

Runs multiple research sessions in sequence under a single goal and experiment
budget. Writes durable state between sessions so interrupted campaigns can be
safely resumed.

Campaign hierarchy:
  experiment = one candidate config tested across seeds and tick sizes
  batch      = several experiments (3–5)
  session    = several batches with cross-batch diagnosis between them
  campaign   = several sessions under one goal, one budget, one final brief

Usage:
    # Start a new campaign:
    python scripts/run_campaign.py --goal "improve entry quality filters"

    # Start with explicit limits:
    python scripts/run_campaign.py \\
        --goal "reduce tail risk" \\
        --max-sessions 4 \\
        --max-batches 3 \\
        --experiments 4 \\
        --max-experiments 80

    # Dry run — generate manifests, skip validation:
    python scripts/run_campaign.py --goal "explore loss_structure space" --dry-run

    # Resume an interrupted campaign:
    python scripts/run_campaign.py --resume campaign_20260409T120000

    # Inspect live campaign state:
    cat data/campaigns/campaign_20260409T120000/state.json

Outputs:
    data/campaigns/{id}/state.json  — live state (updated every session)
    data/campaigns/{id}/brief.json  — final operator brief (machine-readable)
    data/campaigns/{id}/brief.md    — final operator brief (human-readable)

Promotion (always manual — never automatic):
    python scripts/promote_candidate.py --record <path>
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from datetime import datetime, timezone

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from research.campaign        import (
    CampaignState,
    make_campaign_id,
    save_state,
    load_state,
    acquire_lock,
    check_existing_lock,
)
from research.campaign_runner import CampaignRunner
from research.policy          import CAMPAIGN, SESSION

# ── Policy constants ──────────────────────────────────────────────────────────

_HARD_CAP_SESSIONS  = int(CAMPAIGN.get("max_sessions_hard_cap",            6))
_HARD_CAP_EXP_TOTAL = int(CAMPAIGN.get("max_total_experiments_hard_cap", 100))
_DEFAULT_SESSIONS   = int(CAMPAIGN.get("default_sessions",                 3))
_DEFAULT_MAX_EXP    = int(CAMPAIGN.get("default_max_total_experiments",   60))

_HARD_CAP_BATCHES   = int(SESSION.get("max_batches_hard_cap",              4))
_DEFAULT_BATCHES    = int(SESSION.get("default_batches",                   3))
_DEFAULT_EXP_BATCH  = int(SESSION.get("default_experiments_per_batch",     3))

_CAMPAIGNS_DIR = _ROOT / "data" / "campaigns"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded autonomous research campaign.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--goal", type=str, metavar="TEXT",
        help="Campaign objective (required for new campaigns)",
    )
    mode.add_argument(
        "--resume", type=str, metavar="CAMPAIGN_ID",
        help="Resume an interrupted campaign by its ID",
    )

    parser.add_argument(
        "--max-sessions", type=int, default=_DEFAULT_SESSIONS, metavar="N",
        help=(
            f"Max sessions to run "
            f"(hard cap {_HARD_CAP_SESSIONS}, default {_DEFAULT_SESSIONS})"
        ),
    )
    parser.add_argument(
        "--max-batches", type=int, default=_DEFAULT_BATCHES, metavar="N",
        help=(
            f"Max batches per session "
            f"(hard cap {_HARD_CAP_BATCHES}, default {_DEFAULT_BATCHES})"
        ),
    )
    parser.add_argument(
        "--experiments", type=int, default=_DEFAULT_EXP_BATCH, metavar="N",
        help=f"Experiments per batch (default {_DEFAULT_EXP_BATCH})",
    )
    parser.add_argument(
        "--max-experiments", type=int, default=_DEFAULT_MAX_EXP, metavar="N",
        help=(
            f"Total experiment budget across the full campaign "
            f"(hard cap {_HARD_CAP_EXP_TOTAL}, default {_DEFAULT_MAX_EXP})"
        ),
    )
    parser.add_argument(
        "--notes", type=str, default="", metavar="TEXT",
        help="Optional context note stored in campaign state and reports",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate manifests only — no validation, no ledger writes",
    )

    args = parser.parse_args()

    if not args.goal and not args.resume:
        parser.error(
            "Provide --goal TEXT to start a new campaign, "
            "or --resume CAMPAIGN_ID to continue an interrupted one."
        )

    # ── Enforce hard caps ─────────────────────────────────────────────────────

    max_sessions = min(args.max_sessions,   _HARD_CAP_SESSIONS)
    max_batches  = min(args.max_batches,    _HARD_CAP_BATCHES)
    max_exp      = min(args.max_experiments, _HARD_CAP_EXP_TOTAL)

    if args.max_sessions > _HARD_CAP_SESSIONS:
        print(
            f"[WARN] --max-sessions clamped to hard cap ({_HARD_CAP_SESSIONS})."
        )
    if args.max_experiments > _HARD_CAP_EXP_TOTAL:
        print(
            f"[WARN] --max-experiments clamped to hard cap ({_HARD_CAP_EXP_TOTAL})."
        )

    # ── Check for a live running campaign ─────────────────────────────────────

    existing = check_existing_lock(_CAMPAIGNS_DIR)
    if existing:
        print(
            f"[ERROR] Campaign '{existing.get('campaign_id')}' is already running "
            f"(PID {existing.get('pid')}).\n"
            "Aborting to prevent overlap."
        )
        return 1

    # ── Resume or create ──────────────────────────────────────────────────────

    if args.resume:
        campaign_id = args.resume
        state_path  = _CAMPAIGNS_DIR / campaign_id / "state.json"

        if not state_path.exists():
            print(f"[ERROR] No campaign state found at {state_path}")
            return 1

        state = load_state(state_path)

        if state.status == "completed":
            print(
                f"[INFO] Campaign '{campaign_id}' already completed "
                f"(stop: {state.stop_condition})."
            )
            print(
                "To start fresh, run with --goal instead of --resume.\n"
                f"Brief: data/campaigns/{campaign_id}/brief.md"
            )
            return 0

        done = state.progress["sessions_completed"]
        exp  = state.progress["total_experiments"]
        print(f"[RESUME] Resuming campaign {campaign_id}")
        print(f"  Goal              : {state.goal}")
        print(f"  Sessions completed: {done}/{state.config.get('max_sessions', '?')}")
        print(f"  Experiments so far: {exp}")

    else:
        campaign_id  = make_campaign_id()
        campaign_dir = _CAMPAIGNS_DIR / campaign_id
        campaign_dir.mkdir(parents=True, exist_ok=True)
        state_path   = campaign_dir / "state.json"

        state = CampaignState(
            campaign_id       = campaign_id,
            created_at        = _now_iso(),
            goal              = args.goal,
            notes             = args.notes,
            status            = "running",
            config            = {
                "max_sessions":           max_sessions,
                "max_batches_per_session": max_batches,
                "experiments_per_batch":  args.experiments,
                "max_total_experiments":  max_exp,
            },
            progress          = {
                "sessions_completed":               0,
                "total_batches":                    0,
                "total_experiments":                0,
                "total_accepted":                   0,
                "consecutive_no_progress_sessions": 0,
                "session_dominant_failures":        [],
            },
            session_ids        = [],
            session_summaries  = [],
            best_candidate     = None,
            stop_condition     = None,
            stop_reason        = None,
            artifacts          = {
                "best_validation_record": None,
                "best_experiment_id":     None,
                "best_session_id":        None,
                "session_reports":        [],
                "session_md_reports":     [],
                "campaign_brief_json":    None,
                "campaign_brief_md":      None,
            },
        )
        save_state(state, state_path)

        print(f"[NEW] Campaign {campaign_id}")
        print(f"  Goal             : {args.goal}")
        print(f"  Max sessions     : {max_sessions}")
        print(f"  Max batches/sess : {max_batches}")
        print(f"  Experiments/batch: {args.experiments}")
        print(f"  Experiment budget: {max_exp}")
        if args.notes:
            print(f"  Notes            : {args.notes}")
        if args.dry_run:
            print("  [DRY RUN] Manifests only — no simulation.")

    # ── Acquire run lock ──────────────────────────────────────────────────────

    try:
        lock_path = acquire_lock(_CAMPAIGNS_DIR, campaign_id)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 1

    # ── Run ───────────────────────────────────────────────────────────────────

    runner = CampaignRunner(
        state      = state,
        state_path = state_path,
        lock_path  = lock_path,
        verbose    = True,
        dry_run    = args.dry_run,
    )

    try:
        runner.run()
    except KeyboardInterrupt:
        print(f"\n[INTERRUPTED] State saved. Resume with:")
        print(f"  python scripts/run_campaign.py --resume {campaign_id}")
        return 130
    except Exception as exc:
        print(f"\n[FATAL] {exc}")
        print(f"State saved. Resume with:")
        print(f"  python scripts/run_campaign.py --resume {campaign_id}")
        return 1

    # ── Print artifact summary ────────────────────────────────────────────────

    art = state.artifacts
    print(f"\n{'─'*64}")
    print(f"  Campaign state → data/campaigns/{campaign_id}/state.json")
    print(f"  Brief (MD)     → data/campaigns/{campaign_id}/brief.md")
    print(f"  Brief (JSON)   → data/campaigns/{campaign_id}/brief.json")

    if art.get("best_validation_record"):
        print(f"\n  Best record → {art['best_validation_record']}")
        print(
            f"  Promote   → python scripts/promote_candidate.py "
            f"--record {art['best_validation_record']}"
        )
    print(f"{'─'*64}")

    return 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    sys.exit(main())
