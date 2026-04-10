#!/usr/bin/env python3
"""
scripts/run_research.py

Top-level autonomous research batch command.

Chains:
  1. Candidate generation   — 3–5 tightly scoped experiment manifests
  2. Batch validation        — in-process, deterministic, saves to data/validation_runs/
  3. Post-run review         — structured diagnostics + insight synthesis per experiment
  4. Research ledger logging — data/research_ledger/ledger.jsonl + markdown summary
  5. Batch report            — data/research_ledger/reports/{batch_id}.json + .md

Policy and governance:
  All rules (classes, param ranges, batch limits) live in research/policy.py.
  That file is the single human-editable config for the research lab.

Enforced guardrails (see research/governance.py):
  - Only approved experiment classes: profit_taking, entry_quality, loss_structure
  - Only approved parameter mutations within bounded ranges
  - Max 5 experiments per batch; min 3
  - Max 3 parameter mutations per experiment
  - No auto-promotion: accepted candidates require manual action
  - No live config changes; baseline is read-only during each run
  - One failed experiment does not abort the rest of the batch

Usage:
    python scripts/run_research.py
    python scripts/run_research.py --batch-size 3
    python scripts/run_research.py --dry-run
    python scripts/run_research.py --notes "post-drawdown regime check"

What remains manual:
    python scripts/promote_candidate.py   ← promote an accepted record
    python scripts/view_experiments.py    ← browse validation history
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from research.generator    import generate_batch          # noqa: E402
from research.batch_runner import BatchRunner             # noqa: E402
from research.reviewer     import extract_diagnostics, synthesize_insight  # noqa: E402
from research.scoring      import rank_batch              # noqa: E402
from research.ledger       import log_batch               # noqa: E402
from research.report       import generate_batch_report   # noqa: E402
from research.manifest     import make_batch_id           # noqa: E402
from research.governance   import (                       # noqa: E402
    MAX_EXPERIMENTS_PER_BATCH,
    MIN_EXPERIMENTS_PER_BATCH,
)

_DIV = "=" * 64

_TIER_ICON = {
    "strong":        "★★★",
    "review_worthy": "★★☆",
    "noisy":         "★☆☆",
    "weak":          "◇",
    "rejected":      "✗",
    "failed":        "–",
}


def _print_header(batch_id: str, n: int) -> None:
    print(f"\n{_DIV}")
    print(f"  OpenClaw Research Batch  |  {batch_id}")
    print(f"  {n} experiments  |  profit_taking / entry_quality / loss_structure")
    print(f"{_DIV}\n")


def _print_ranking_table(ranked: list[dict]) -> None:
    header = f"{'Rank':<4}  {'ID':<36}  {'Class':<16}  {'Score':>5}  {'Tier':<14}  {'Decision':<10}  {'PnL Δ':>8}"
    print(header)
    print("-" * len(header))
    for i, r in enumerate(ranked, 1):
        icon = _TIER_ICON.get(r.get("tier", "rejected"), "")
        print(
            f"{i:<4}  {(r.get('experiment_id') or ''):<36}  "
            f"{(r.get('experiment_class') or ''):<16}  "
            f"{r.get('score', 0):>5.1f}  "
            f"{(r.get('tier') or ''):<14}  "
            f"{(r.get('decision') or 'FAILED'):<10}  "
            f"{(r.get('pnl_delta') or 0):>+8.2f}"
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one bounded autonomous research batch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--batch-size", type=int, default=MAX_EXPERIMENTS_PER_BATCH,
        metavar="N",
        help=(
            f"Number of experiments "
            f"(min {MIN_EXPERIMENTS_PER_BATCH}, max {MAX_EXPERIMENTS_PER_BATCH})"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate and display manifests without running experiments",
    )
    parser.add_argument(
        "--notes", type=str, default="",
        metavar="TEXT",
        help="Context note stored in the ledger and report",
    )
    args = parser.parse_args()

    batch_id = make_batch_id()
    _print_header(batch_id, args.batch_size)

    # ── Step 1: Generate candidates ───────────────────────────────────────────
    print("[1/5] Generating experiment manifests ...")
    try:
        manifests = generate_batch(batch_id=batch_id, n=args.batch_size)
    except (ValueError, RuntimeError) as exc:
        print(f"\n[ABORT] Candidate generation failed: {exc}", file=sys.stderr)
        return 1

    print(f"      Generated {len(manifests)} manifests:\n")
    for m in manifests:
        print(f"      [{m.experiment_id}]")
        print(f"        class : {m.experiment_class}")
        print(f"        params: {m.mutated_params}")
        print(f"        why   : {m.hypothesis[:88]}...")
        print()

    if args.dry_run:
        print("[DRY RUN] Stopping before validation.\n")
        for m in manifests:
            print(m.to_json())
        return 0

    # ── Step 2: Batch validation ──────────────────────────────────────────────
    print(f"[2/5] Running batch validation ({len(manifests)} experiments) ...\n")
    runner  = BatchRunner()
    records: list[dict | None] = []

    for i, manifest in enumerate(manifests, 1):
        print(f"  [{i}/{len(manifests)}] {manifest.experiment_id}")
        try:
            record, path = runner.run_manifest(manifest)
            records.append(record)
            manifest.status      = "complete"
            manifest.output_path = path
        except (ValueError, RuntimeError) as exc:
            print(f"  [BLOCKED] {manifest.experiment_id}: {exc}", file=sys.stderr)
            manifest.status = "failed"
            records.append(None)
        except Exception as exc:
            print(f"  [ERROR]   {manifest.experiment_id}: {exc}", file=sys.stderr)
            manifest.status = "failed"
            records.append(None)
        print()

    if all(r is None for r in records):
        print("[ABORT] Every experiment failed. Nothing to log.", file=sys.stderr)
        return 1

    # ── Step 3: Extract diagnostics and synthesize insights ───────────────────
    print("[3/5] Extracting diagnostics and synthesizing insights ...")
    _FAILED_DIAG: dict = {
        "experiment_id": None, "experiment_class": "unknown",
        "hypothesis": "run failed or was blocked",
        "candidate_config": {}, "rejection_reasons": [],
        "decision": "FAILED", "baseline_median_pnl": None,
        "pnl_delta": None, "worst_pnl_delta": None, "trade_count_change": None,
        "churn_change": None, "stop_rate_change": None, "win_rate_change": None,
        "loss_win_ratio_change": None, "avg_winner": None, "avg_loser": None,
        "worst_case_behavior": "N/A", "quality_labels": [], "assessment": "failed",
        "flags": [],
    }
    _FAILED_INSIGHT: dict = {
        "major_learning": "Experiment failed to run — no data to analyze.",
        "revisit_recommendation": "deprioritize",
    }

    diagnostics: list[dict] = []
    insights:    list[dict] = []

    for m, record in zip(manifests, records):
        if record is None:
            d = {**_FAILED_DIAG, "experiment_id": m.experiment_id}
            diagnostics.append(d)
            insights.append(_FAILED_INSIGHT)
        else:
            d = extract_diagnostics(record)
            diagnostics.append(d)
            insights.append(synthesize_insight(d))

    ranked = rank_batch([d for d in diagnostics if d.get("decision") != "FAILED"])

    # ── Step 4: Log to research ledger ────────────────────────────────────────
    print(f"\n[4/5] Writing research ledger entry ...")
    valid_manifests   = [m for m, r in zip(manifests, records) if r is not None]
    valid_records     = [r for r in records if r is not None]
    valid_diagnostics = [d for d in diagnostics if d.get("decision") != "FAILED"]
    valid_insights    = [
        ins for d, ins in zip(diagnostics, insights)
        if d.get("decision") != "FAILED"
    ]

    log_batch(
        batch_id=batch_id,
        manifests=valid_manifests,
        records=valid_records,
        diagnostics=valid_diagnostics,
        ranked=ranked,
        insights=valid_insights,
        notes=args.notes,
    )

    # ── Step 5: Generate batch report ─────────────────────────────────────────
    print(f"\n[5/5] Generating batch report ...")
    report = generate_batch_report(
        batch_id=batch_id,
        manifests=valid_manifests,
        diagnostics=valid_diagnostics,
        ranked=ranked,
        insights=valid_insights,
        notes=args.notes,
    )
    report_path = _ROOT / "data" / "research_ledger" / "reports" / f"{batch_id}_report.md"
    print(f"      Report → {report_path.relative_to(_ROOT)}")

    # ── Final output ──────────────────────────────────────────────────────────
    accepted = [d for d in diagnostics if d.get("decision") == "ACCEPTED"]

    print(f"\n{_DIV}")
    print(f"  Batch Complete: {batch_id}")
    print(f"  {len(accepted)} accepted / {len(manifests)} total")
    print()

    if ranked:
        print("  Ranking:")
        _print_ranking_table(ranked)

    na     = report.get("next_action", {})
    hr     = report.get("human_review_recommended", False)
    action = na.get("recommendation", "")

    print(f"  Next action : {action}")
    if na.get("rationale"):
        print(f"  Rationale   : {na['rationale']}")
    print()

    if hr:
        print(f"  ⚑ Human review recommended:")
        print(f"    {report.get('human_review_reason', '')}")
        print()
        if accepted:
            print("  Accepted candidates:")
            for d in valid_diagnostics:
                if d.get("decision") != "ACCEPTED":
                    continue
                score_entry = next(
                    (r for r in ranked if r.get("experiment_id") == d.get("experiment_id")), {}
                )
                print(f"    • {d.get('experiment_id')}  [{d.get('experiment_class')}]")
                print(f"      Params : {d.get('candidate_config')}")
                print(f"      Score  : {score_entry.get('score', 'n/a')} ({score_entry.get('tier', '?')})")
                print(f"      PnL Δ  : {d.get('pnl_delta') or 0:+.2f}")
                print()
            print("  To promote:")
            print("    1. Note the experiment's output_path from the ledger summary")
            print("    2. Confirm it is the most-recent file in data/validation_runs/")
            print("       (promote_candidate.py picks the newest file by timestamp)")
            print("    3. python scripts/promote_candidate.py")
    else:
        print("  No human review required for this batch.")
        if action == "run_diagnosis":
            print("  → python scripts/research_cycle.py  (diagnosis-driven search)")
        elif action == "retry_with_adjustment":
            print("  → Adjust parameter values in next batch (near-miss detected)")

    summary_path = _ROOT / "data" / "research_ledger" / "summaries" / f"{batch_id}.md"
    print(f"\n  Ledger summary : {summary_path.relative_to(_ROOT)}")
    print(f"  Batch report   : {report_path.relative_to(_ROOT)}")
    print(f"{_DIV}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
