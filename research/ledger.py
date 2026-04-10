# research/ledger.py
#
# Persistent research ledger — durable memory for the autonomous research lab.
#
# Maintains two complementary records per batch:
#
#   data/research_ledger/ledger.jsonl
#     Machine-readable, append-only. One JSON object per line.
#     Parse with: [json.loads(l) for l in open("ledger.jsonl")]
#
#   data/research_ledger/summaries/{batch_id}.md
#     Human-readable markdown. One file per batch.
#     Covers: what was tested, why, what changed, classification, insight,
#             revisit recommendation, and open questions.
#
# The ledger is append-only by design — past entries are never rewritten.
# Use it as an audit trail and a research memory across sessions.

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
LEDGER_DIR    = _ROOT / "data" / "research_ledger"
LEDGER_FILE   = LEDGER_DIR / "ledger.jsonl"
SUMMARIES_DIR = LEDGER_DIR / "summaries"


# ── Public API ────────────────────────────────────────────────────────────────

def log_batch(
    batch_id:    str,
    manifests:   list,                    # list[ExperimentManifest]
    records:     list[dict[str, Any]],    # validation records
    diagnostics: list[dict[str, Any]],
    ranked:      list[dict[str, Any]],    # from scoring.rank_batch()
    insights:    list[dict[str, str]],    # from reviewer.synthesize_insight() per exp
    notes:       str = "",
) -> None:
    """
    Append a batch entry to the ledger and write a markdown summary.

    Args:
        batch_id:    Unique batch identifier.
        manifests:   Generated ExperimentManifest objects.
        records:     Validation records (parallel to manifests).
        diagnostics: Extracted diagnostics (parallel to manifests).
        ranked:      Scored+ranked experiments from scoring.rank_batch().
        insights:    Per-experiment insights from reviewer.synthesize_insight().
        notes:       Optional human context string.
    """
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

    entry = _build_entry(batch_id, manifests, diagnostics, ranked, insights, notes)

    with LEDGER_FILE.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")

    md_path = SUMMARIES_DIR / f"{batch_id}.md"
    md_path.write_text(_build_markdown(entry))

    n_accepted = entry["summary"]["accepted"]
    n_total    = entry["summary"]["total_experiments"]
    try:
        md_rel = md_path.relative_to(_ROOT)
    except ValueError:
        md_rel = md_path
    print(f"[ledger] {batch_id} — {n_accepted}/{n_total} accepted → {md_rel}")


# ── Entry builder ─────────────────────────────────────────────────────────────

def _build_entry(
    batch_id:    str,
    manifests:   list,
    diagnostics: list[dict],
    ranked:      list[dict],
    insights:    list[dict],
    notes:       str,
) -> dict[str, Any]:

    n_accepted = sum(1 for d in diagnostics if d.get("decision") == "ACCEPTED")
    n_rejected = sum(1 for d in diagnostics if d.get("decision") == "REJECTED")
    n_failed   = len(diagnostics) - n_accepted - n_rejected

    # Build a score lookup: experiment_id → {score, tier}
    score_lookup: dict[str, dict] = {
        r["experiment_id"]: {"score": r["score"], "tier": r["tier"]}
        for r in ranked
        if r.get("experiment_id")
    }

    # Candidates for review (accepted or near-miss weak)
    candidates_for_review = []
    for m, d in zip(manifests, diagnostics):
        entry_score = score_lookup.get(m.experiment_id, {})
        tier        = entry_score.get("tier", "rejected")
        if d.get("decision") == "ACCEPTED" or tier == "weak":
            candidates_for_review.append({
                "experiment_id":    m.experiment_id,
                "experiment_class": d.get("experiment_class"),
                "hypothesis":       d.get("hypothesis"),
                "candidate_config": d.get("candidate_config", {}),
                "pnl_delta":        d.get("pnl_delta"),
                "worst_pnl_delta":  d.get("worst_pnl_delta"),
                "score":            entry_score.get("score"),
                "tier":             tier,
                "decision":         d.get("decision"),
                "output_path":      m.output_path,
            })

    open_questions = _derive_open_questions(diagnostics, insights)

    # Per-experiment log (the durable record)
    experiments_log = []
    for m, d, ins in zip(manifests, diagnostics, insights):
        sc = score_lookup.get(m.experiment_id, {})
        experiments_log.append({
            # Identity
            "experiment_id":      m.experiment_id,
            "experiment_class":   d.get("experiment_class"),
            "hypothesis":         d.get("hypothesis"),
            "candidate_config":   d.get("candidate_config", {}),
            "approved_ranges":    m.approved_ranges,
            # Outcome
            "decision":           d.get("decision"),
            "score":              sc.get("score"),
            "tier":               sc.get("tier"),
            # What improved / worsened
            "pnl_delta":          d.get("pnl_delta"),
            "worst_pnl_delta":    d.get("worst_pnl_delta"),
            "trade_count_change": d.get("trade_count_change"),
            "churn_change":       d.get("churn_change"),
            "stop_rate_change":   d.get("stop_rate_change"),
            "win_rate_change":    d.get("win_rate_change"),
            "avg_winner":         d.get("avg_winner"),
            "avg_loser":          d.get("avg_loser"),
            # Qualitative
            "quality_labels":     d.get("quality_labels", []),
            "flags":              d.get("flags", []),
            "worst_case_behavior": d.get("worst_case_behavior"),
            "rejection_reasons":  d.get("rejection_reasons", []),
            # Insight
            "major_learning":     ins.get("major_learning"),
            "revisit_recommendation": ins.get("revisit_recommendation"),
            # Artifact
            "output_path":        m.output_path,
        })

    return {
        "schema_version":      "1.1",
        "batch_id":            batch_id,
        "timestamp":           datetime.now(timezone.utc).isoformat(),
        "notes":               notes,
        "summary": {
            "total_experiments": len(manifests),
            "accepted":          n_accepted,
            "rejected":          n_rejected,
            "failed":            n_failed,
        },
        "experiments":          experiments_log,
        "candidates_for_review": candidates_for_review,
        "open_questions":       open_questions,
    }


def _derive_open_questions(
    diagnostics: list[dict],
    insights: list[dict],
) -> list[str]:
    questions: list[str] = []

    # Accepted with quality flags
    for d in diagnostics:
        if d.get("decision") == "ACCEPTED" and d.get("quality_labels"):
            questions.append(
                f"Accepted candidate in '{d.get('experiment_class')}' carries quality flags: "
                f"{', '.join(d['quality_labels'])}. "
                "Is this tradeoff acceptable, or should the flags drive a different experiment?"
            )

    # All rejected
    if diagnostics and all(d.get("decision") == "REJECTED" for d in diagnostics):
        near_misses = [ins for ins in insights if ins.get("revisit_recommendation") == "yes"]
        if near_misses:
            questions.append(
                f"{len(near_misses)} near-miss rejection(s) detected. "
                "Should the next batch probe these directions with smaller parameter shifts?"
            )
        else:
            questions.append(
                "All candidates rejected with no near-misses. "
                "Is the baseline unusually strong this session, or are the approved "
                "parameter ranges misaligned with what the strategy actually needs? "
                "Consider running research_cycle.py for diagnosis."
            )

    # Stop rate degraded consistently
    stop_degraded = [d for d in diagnostics if (d.get("stop_rate_change") or 0) > 0.05]
    if len(stop_degraded) > 1:
        questions.append(
            f"Stop rate increased in {len(stop_degraded)}/{len(diagnostics)} experiments. "
            "Is the current stop_loss_pct too tight for the simulated conditions, "
            "causing cascading stop-outs when any filter is changed?"
        )

    # Consistent trade-count collapse
    trade_drop = [d for d in diagnostics if (d.get("trade_count_change") or 0) < -15]
    if len(trade_drop) > 1:
        questions.append(
            f"Trade count dropped significantly in {len(trade_drop)}/{len(diagnostics)} experiments. "
            "Are the entry filters collectively too aggressive? "
            "Consider whether the cooldown or ER gate should be relaxed as a companion change."
        )

    # Revisit recommendations for rejected
    deprioritize = [
        ins for ins in insights
        if ins.get("revisit_recommendation") == "deprioritize"
    ]
    if len(deprioritize) > len(diagnostics) // 2:
        questions.append(
            f"{len(deprioritize)}/{len(diagnostics)} experiments are flagged for deprioritization. "
            "Should the next batch explore a completely different experiment class or focus area?"
        )

    return questions


# ── Markdown builder ──────────────────────────────────────────────────────────

_REVISIT_ICON = {"yes": "↩ revisit", "no": "✗ skip", "deprioritize": "↓ deprioritize"}
_TIER_ICON    = {
    "strong":        "★★★",
    "review_worthy": "★★☆",
    "noisy":         "★☆☆",
    "weak":          "◇ weak",
    "rejected":      "✗",
}


def _build_markdown(entry: dict[str, Any]) -> str:
    lines: list[str] = []
    s   = entry["summary"]
    ts  = entry["timestamp"][:10]
    bid = entry["batch_id"]

    lines += [
        f"# Research Batch: {bid}",
        "",
        f"**Date**: {ts}  ",
        f"**Result**: {s['total_experiments']} experiments — "
        f"{s['accepted']} accepted / {s['rejected']} rejected"
        + (f" / {s['failed']} failed" if s["failed"] else ""),
        "",
    ]

    if entry.get("notes"):
        lines += [f"**Notes**: {entry['notes']}", ""]

    lines += ["---", "", "## Experiments", ""]

    for exp in entry["experiments"]:
        tier_icon = _TIER_ICON.get(exp.get("tier") or "rejected", "")
        rev_icon  = _REVISIT_ICON.get(exp.get("revisit_recommendation") or "", "")
        decision_icon = "✓" if exp["decision"] == "ACCEPTED" else "✗"

        score_str = f"{exp['score']:.0f}" if exp.get("score") is not None else "n/a"

        lines += [
            f"### {decision_icon} `{exp['experiment_id']}` — {exp.get('experiment_class')}",
            "",
            f"**Hypothesis**: {exp.get('hypothesis')}  ",
            f"**Params**: `{exp.get('candidate_config')}`  ",
            f"**Decision**: {exp['decision']}  "
            f"| **Score**: {score_str} {tier_icon}  "
            f"| **Revisit**: {rev_icon}",
            "",
        ]

        # PnL and trade metrics
        pnl_d   = exp.get("pnl_delta")
        worst_d = exp.get("worst_pnl_delta")
        tr_d    = exp.get("trade_count_change")
        if pnl_d is not None:
            lines.append(f"**PnL Δ (median)**: {pnl_d:+.2f}  ")
        if worst_d is not None:
            lines.append(f"**Worst PnL Δ**: {worst_d:+.2f}  ")
        if tr_d is not None:
            lines.append(f"**Trade count Δ**: {tr_d:+.1f}  ")

        wc = exp.get("worst_case_behavior")
        if wc:
            lines.append(f"**Worst-case**: {wc}  ")

        aw, al = exp.get("avg_winner"), exp.get("avg_loser")
        if aw is not None and al is not None:
            lines.append(f"**Avg winner / avg loser**: ${aw:,.2f} / ${al:,.2f}  ")

        if exp.get("quality_labels"):
            lines.append(f"**Quality flags**: {', '.join(exp['quality_labels'])}  ")

        if exp.get("flags"):
            lines.append("**Concerns**:  ")
            for flag in exp["flags"]:
                lines.append(f"- {flag}  ")

        if exp.get("rejection_reasons"):
            lines.append("**Rejection reasons**:  ")
            for r in exp["rejection_reasons"]:
                lines.append(f"- {r}  ")

        # Insight
        if exp.get("major_learning"):
            lines += [
                "",
                f"> **Insight**: {exp['major_learning']}",
            ]

        if exp.get("output_path"):
            lines.append(f"  ")
            lines.append(f"*Record*: `{exp['output_path']}`  ")

        lines.append("")

    # Candidates for review
    review_cands = entry.get("candidates_for_review", [])
    if review_cands:
        lines += ["---", "", "## Candidates for Human Review", ""]
        for c in review_cands:
            score_str = f"{c['score']:.0f}" if c.get("score") is not None else "n/a"
            lines += [
                f"- **{c['experiment_id']}** (`{c['experiment_class']}`) "
                f"Score={score_str} Tier={c.get('tier')} Decision={c.get('decision')}  ",
                f"  Config: `{c.get('candidate_config')}`  ",
                f"  PnL Δ={c.get('pnl_delta') or 0:+.2f}, "
                f"Worst Δ={c.get('worst_pnl_delta') or 0:+.2f}  ",
                "",
            ]
        lines += [
            "> To promote: copy the accepted `candidate_config` into "
            "`data/candidate_config.json`, then run `python scripts/promote_candidate.py`",
            "> Note: `promote_candidate.py` loads the **most recent** validation record "
            "by file timestamp. For a specific experiment, note its output_path above "
            "and confirm the timestamp matches.",
            "",
        ]
    else:
        lines += [
            "---",
            "",
            "_No candidates met acceptance criteria or near-miss threshold in this batch._",
            "",
        ]

    # Open questions
    if entry.get("open_questions"):
        lines += ["## Open Questions", ""]
        for q in entry["open_questions"]:
            lines.append(f"- {q}")
        lines.append("")

    lines += [
        "---",
        "",
        "*Generated by OpenClaw autonomous research loop.*  ",
        "*Promotion requires explicit human action via scripts/promote_candidate.py.*",
    ]

    return "\n".join(lines)
