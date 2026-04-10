# research/report.py
#
# Structured per-batch report generator.
#
# Produces a machine-readable JSON and a concise human-readable markdown file
# for each completed research batch. This artifact is the formal output
# contract between the research loop and any future supervising layer.
#
# The report answers:
#   - what ran       (batch metadata, classes, seed count)
#   - what mattered  (key findings from across experiments)
#   - best candidate (highest-scored experiment with full details)
#   - biggest failure (most severe failure mode seen)
#   - what was learned (synthesized insights per experiment)
#   - next action     (specific recommendation for what to do now)
#   - human review    (explicit flag — is human attention needed?)
#
# Output paths (both written on every call):
#   data/research_ledger/reports/{batch_id}.json
#   data/research_ledger/reports/{batch_id}_report.md

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any

_ROOT        = pathlib.Path(__file__).resolve().parent.parent
REPORTS_DIR  = _ROOT / "data" / "research_ledger" / "reports"

_NEXT_ACTION_OPTIONS = (
    "promote_best",           # strong/review_worthy accepted candidate exists
    "retest_accepted",        # accepted but noisy — more seeds or seeds variant
    "retry_with_adjustment",  # near-miss rejected — small param shift may pass
    "run_diagnosis",          # all rejected, no near-miss → use research_cycle.py
    "deprioritize_class",     # consistent failure on one class
    "no_action_needed",       # all rejected, results expected, proceed normally
)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_batch_report(
    batch_id: str,
    manifests: list,
    diagnostics: list[dict[str, Any]],
    ranked: list[dict[str, Any]],    # output of scoring.rank_batch()
    insights: list[dict[str, str]],  # output of reviewer.synthesize_insight() per exp
    notes: str = "",
) -> dict[str, Any]:
    """
    Build the structured batch report, write both JSON and markdown to disk,
    and return the report dict.

    Args:
        batch_id:    Batch identifier.
        manifests:   ExperimentManifest objects (parallel to diagnostics).
        diagnostics: Extracted diagnostics (from reviewer.extract_diagnostics).
        ranked:      Scored+ranked experiments (from scoring.rank_batch).
        insights:    Per-experiment insights (from reviewer.synthesize_insight).
        notes:       Optional human context string.

    Returns:
        The report dict (same content as the JSON file).
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    report = _build_report(batch_id, manifests, diagnostics, ranked, insights, notes)

    json_path = REPORTS_DIR / f"{batch_id}.json"
    md_path   = REPORTS_DIR / f"{batch_id}_report.md"

    json_path.write_text(json.dumps(report, indent=2))
    md_path.write_text(_build_markdown(report))

    return report


# ── Report construction ───────────────────────────────────────────────────────

def _build_report(
    batch_id:    str,
    manifests:   list,
    diagnostics: list[dict[str, Any]],
    ranked:      list[dict[str, Any]],
    insights:    list[dict[str, str]],
    notes:       str,
) -> dict[str, Any]:

    n_total    = len(diagnostics)
    n_accepted = sum(1 for d in diagnostics if d.get("decision") == "ACCEPTED")
    n_rejected = n_total - n_accepted

    classes_tested = sorted({d.get("experiment_class") for d in diagnostics if d.get("experiment_class")})
    seed_count = len(manifests[0].seed_set) if manifests else 0

    # Best and worst candidates
    best_entry     = ranked[0]  if ranked else None
    accepted_ranked = [r for r in ranked if r.get("decision") == "ACCEPTED"]
    rejected_ranked = [r for r in ranked if r.get("decision") == "REJECTED"]

    best_candidate = _describe_candidate(best_entry, diagnostics) if best_entry else None
    worst_failure  = _describe_worst_failure(rejected_ranked, diagnostics)

    # Key findings
    key_findings = _derive_key_findings(diagnostics, ranked)

    # Learned (one insight per experiment)
    learned = []
    for m, d, ins in zip(manifests, diagnostics, insights):
        learned.append({
            "experiment_id":   m.experiment_id,
            "experiment_class": d.get("experiment_class"),
            "major_learning":  ins.get("major_learning"),
            "revisit":         ins.get("revisit_recommendation"),
        })

    # Next action
    next_action = _recommend_next_action(diagnostics, ranked, insights)
    human_review = _should_flag_human_review(diagnostics, ranked)

    return {
        "schema_version": "1.0",
        "batch_id":        batch_id,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "notes":           notes,

        "what_ran": {
            "batch_id":       batch_id,
            "n_experiments":  n_total,
            "n_accepted":     n_accepted,
            "n_rejected":     n_rejected,
            "classes_tested": classes_tested,
            "seeds_per_run":  seed_count,
        },

        "what_mattered": key_findings,

        "best_candidate": best_candidate,
        "biggest_failure": worst_failure,

        "learned": learned,

        "next_action": {
            "recommendation": next_action,
            "rationale":      _next_action_rationale(next_action, diagnostics, ranked),
        },

        "human_review_recommended": human_review,
        "human_review_reason":      _human_review_reason(human_review, diagnostics, ranked),

        "ranking": ranked,
    }


def _describe_candidate(ranked_entry: dict, diagnostics: list[dict]) -> dict[str, Any]:
    eid = ranked_entry.get("experiment_id")
    diag = next((d for d in diagnostics if d.get("experiment_id") == eid), {})
    return {
        "experiment_id":    eid,
        "experiment_class": ranked_entry.get("experiment_class"),
        "score":            ranked_entry.get("score"),
        "tier":             ranked_entry.get("tier"),
        "decision":         ranked_entry.get("decision"),
        "pnl_delta":        ranked_entry.get("pnl_delta"),
        "worst_pnl_delta":  ranked_entry.get("worst_pnl_delta"),
        "candidate_config": ranked_entry.get("candidate_config", {}),
        "quality_labels":   diag.get("quality_labels", []),
        "hypothesis":       diag.get("hypothesis"),
    }


def _describe_worst_failure(
    rejected_ranked: list[dict],
    diagnostics: list[dict],
) -> dict[str, Any] | None:
    if not rejected_ranked:
        return None
    worst = rejected_ranked[-1]   # lowest-scored rejected
    eid   = worst.get("experiment_id")
    diag  = next((d for d in diagnostics if d.get("experiment_id") == eid), {})
    return {
        "experiment_id":   eid,
        "experiment_class": worst.get("experiment_class"),
        "score":           worst.get("score"),
        "pnl_delta":       worst.get("pnl_delta"),
        "worst_pnl_delta": worst.get("worst_pnl_delta"),
        "candidate_config": worst.get("candidate_config", {}),
        "failure_mode":    _dominant_failure_mode(diag),
        "rejection_reasons": diag.get("rejection_reasons", []),
    }


def _dominant_failure_mode(diag: dict) -> str:
    """Return a short label for the most prominent failure signal."""
    if not diag:
        return "unknown"
    reasons = diag.get("rejection_reasons", [])
    flags   = diag.get("flags", [])
    if any("worst_pnl" in r for r in reasons):
        return "worst_pnl_regression"
    if any("median_pnl" in r for r in reasons):
        return "median_pnl_regression"
    if any("avg_trades" in r for r in reasons):
        return "trade_floor_breach"
    if flags:
        return "quality_degradation"
    return "multiple_criteria"


def _derive_key_findings(
    diagnostics: list[dict],
    ranked: list[dict],
) -> list[str]:
    findings: list[str] = []

    accepted = [d for d in diagnostics if d.get("decision") == "ACCEPTED"]
    rejected = [d for d in diagnostics if d.get("decision") == "REJECTED"]

    if not accepted:
        findings.append(
            f"All {len(rejected)} experiments rejected — no candidates meet "
            "acceptance criteria in this batch."
        )
    else:
        best = ranked[0]
        findings.append(
            f"{len(accepted)}/{len(diagnostics)} experiments accepted. "
            f"Best score: {best['score']:.0f} ({best['tier']}) on "
            f"{best['experiment_class']}."
        )

    # Stop rate pattern
    stop_up = [d for d in diagnostics if (d.get("stop_rate_change") or 0) > 0.05]
    if len(stop_up) > len(diagnostics) // 2:
        findings.append(
            f"Stop rate increased in {len(stop_up)}/{len(diagnostics)} experiments — "
            "current parameter region may be increasing stop-out exposure."
        )

    # Trade count pattern
    trade_down = [d for d in diagnostics if (d.get("trade_count_change") or 0) < -15]
    if trade_down:
        findings.append(
            f"{len(trade_down)} experiment(s) produced significantly fewer trades — "
            "entry filters may be over-restrictive in this direction."
        )

    # Worst-case improvement
    worst_up = [d for d in accepted if (d.get("worst_pnl_delta") or 0) > 0]
    if worst_up:
        findings.append(
            f"{len(worst_up)} accepted candidate(s) improved worst-case behavior — "
            "positive signal for downside protection."
        )

    # Quality flags on accepted
    noisy_accepted = [d for d in accepted if d.get("quality_labels")]
    if noisy_accepted:
        findings.append(
            f"{len(noisy_accepted)} accepted candidate(s) carry quality flags — "
            "review trade structure before promoting."
        )

    return findings


def _recommend_next_action(
    diagnostics: list[dict],
    ranked: list[dict],
    insights: list[dict],
) -> str:
    accepted = [d for d in diagnostics if d.get("decision") == "ACCEPTED"]

    if accepted:
        top = ranked[0]
        if top.get("tier") in ("strong", "review_worthy"):
            return "promote_best"
        if top.get("tier") == "noisy":
            return "retest_accepted"

    # Check for near-misses
    near_misses = [
        ins for ins in insights
        if ins.get("revisit_recommendation") == "yes"
        and not any(
            d.get("decision") == "ACCEPTED"
            for d in diagnostics
            if d.get("experiment_id") == next(
                (r["experiment_id"] for r in ranked), None
            )
        )
    ]
    all_rejected = all(d.get("decision") == "REJECTED" for d in diagnostics)

    if all_rejected:
        deprioritize = [ins for ins in insights if ins.get("revisit_recommendation") == "yes"]
        if deprioritize:
            return "retry_with_adjustment"
        return "run_diagnosis"

    return "no_action_needed"


def _next_action_rationale(
    action: str,
    diagnostics: list[dict],
    ranked: list[dict],
) -> str:
    rationales = {
        "promote_best": (
            "At least one experiment scored 'strong' or 'review_worthy'. "
            "Copy its candidate_config to data/candidate_config.json and run "
            "python scripts/promote_candidate.py."
        ),
        "retest_accepted": (
            "Accepted candidate(s) present but carry quality flags. Consider "
            "running validate_strategy.py on the best config with extended seeds "
            "to confirm robustness before promoting."
        ),
        "retry_with_adjustment": (
            "No experiments accepted, but at least one was a near-miss. "
            "Try a small shift in the same parameter direction or combine with "
            "a secondary parameter from the same class."
        ),
        "run_diagnosis": (
            "All experiments rejected with no near-misses. "
            "Run python scripts/research_cycle.py to diagnose the dominant "
            "failure pattern and generate targeted candidates."
        ),
        "deprioritize_class": (
            "Consistent rejection in one experiment class. "
            "Shift focus to a different class or revisit baseline diagnosis."
        ),
        "no_action_needed": (
            "Results are as expected — no strong signals in either direction."
        ),
    }
    return rationales.get(action, "")


def _should_flag_human_review(
    diagnostics: list[dict],
    ranked: list[dict],
) -> bool:
    """Return True if a human should look at this batch's results."""
    accepted = [d for d in diagnostics if d.get("decision") == "ACCEPTED"]
    if not accepted:
        return False
    top = ranked[0]
    return top.get("tier") in ("strong", "review_worthy", "noisy")


def _human_review_reason(
    flag: bool,
    diagnostics: list[dict],
    ranked: list[dict],
) -> str:
    if not flag:
        return "No accepted candidates — no action needed."
    top = ranked[0]
    tier = top.get("tier")
    score = top.get("score", 0)
    exp_class = top.get("experiment_class")
    if tier == "strong":
        return (
            f"Best candidate scored {score:.0f} (strong) on {exp_class}. "
            "This is a high-quality result worth promoting."
        )
    if tier == "review_worthy":
        return (
            f"Best candidate scored {score:.0f} (review_worthy) on {exp_class}. "
            "Review trade quality before deciding to promote."
        )
    return (
        f"Best candidate scored {score:.0f} ({tier}) on {exp_class}. "
        "Quality flags present — assess whether acceptable before promoting."
    )


# ── Markdown rendering ────────────────────────────────────────────────────────

def _build_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    w = report.get("what_ran", {})
    ts = report.get("generated_at", "")[:10]

    lines += [
        f"# Research Batch Report: {report['batch_id']}",
        "",
        f"**Generated**: {ts}  ",
        f"**Experiments**: {w.get('n_experiments')} total "
        f"({w.get('n_accepted')} accepted / {w.get('n_rejected')} rejected)  ",
        f"**Classes tested**: {', '.join(w.get('classes_tested', []))}  ",
        f"**Seeds per run**: {w.get('seeds_per_run')}  ",
        "",
    ]

    if report.get("notes"):
        lines += [f"**Notes**: {report['notes']}", ""]

    # Human review flag
    hr = report.get("human_review_recommended", False)
    lines += [
        "---",
        "",
        f"## {'⚑ Human Review Recommended' if hr else 'No Human Review Required'}",
        "",
        report.get("human_review_reason", ""),
        "",
    ]

    # Key findings
    lines += ["## Key Findings", ""]
    for f in report.get("what_mattered", []):
        lines.append(f"- {f}")
    lines.append("")

    # Best candidate
    bc = report.get("best_candidate")
    if bc:
        lines += [
            "## Best Candidate",
            "",
            f"**{bc['experiment_id']}** — `{bc['experiment_class']}`  ",
            f"**Score**: {bc['score']} ({bc['tier']})  ",
            f"**Decision**: {bc['decision']}  ",
            f"**Params**: `{bc['candidate_config']}`  ",
            f"**PnL Δ**: {bc['pnl_delta']:+.2f}  " if bc.get("pnl_delta") is not None else "",
            f"**Worst Δ**: {bc['worst_pnl_delta']:+.2f}  " if bc.get("worst_pnl_delta") is not None else "",
        ]
        if bc.get("quality_labels"):
            lines.append(f"**Quality flags**: {', '.join(bc['quality_labels'])}  ")
        if bc.get("hypothesis"):
            lines.append(f"**Hypothesis**: {bc['hypothesis']}  ")
        lines.append("")

    # Biggest failure
    bf = report.get("biggest_failure")
    if bf:
        lines += [
            "## Biggest Failure",
            "",
            f"**{bf['experiment_id']}** — `{bf['experiment_class']}`  ",
            f"**Failure mode**: {bf['failure_mode']}  ",
            f"**Params**: `{bf['candidate_config']}`  ",
            f"**PnL Δ**: {bf['pnl_delta']:+.2f}  " if bf.get("pnl_delta") is not None else "",
        ]
        if bf.get("rejection_reasons"):
            for r in bf["rejection_reasons"]:
                lines.append(f"- {r}  ")
        lines.append("")

    # What was learned
    lines += ["## What Was Learned", ""]
    for item in report.get("learned", []):
        revisit_icon = {"yes": "↩", "no": "✗", "deprioritize": "↓"}.get(
            item.get("revisit", ""), "?"
        )
        lines += [
            f"**{item['experiment_id']}** ({item.get('experiment_class')}) {revisit_icon}  ",
            f"{item.get('major_learning', '')}  ",
            "",
        ]

    # Next action
    na = report.get("next_action", {})
    lines += [
        "## Recommended Next Action",
        "",
        f"**Action**: `{na.get('recommendation')}`  ",
        "",
        na.get("rationale", ""),
        "",
    ]

    # Ranking table
    ranking = report.get("ranking", [])
    if ranking:
        lines += ["## Experiment Ranking", ""]
        lines.append(f"{'Rank':<5} {'ID':<38} {'Class':<16} {'Score':>6} {'Tier':<14} {'Decision':<10} {'PnL Δ':>8}")
        lines.append("-" * 100)
        for i, r in enumerate(ranking, 1):
            lines.append(
                f"{i:<5} {(r.get('experiment_id') or ''):<38} "
                f"{(r.get('experiment_class') or ''):<16} "
                f"{r.get('score', 0):>6.1f} "
                f"{(r.get('tier') or ''):<14} "
                f"{(r.get('decision') or ''):<10} "
                f"{r.get('pnl_delta') or 0:>+8.2f}"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "*Report generated by OpenClaw autonomous research loop.*  ",
        "*Promotion requires explicit human action via scripts/promote_candidate.py*",
    ]

    return "\n".join(lines)
