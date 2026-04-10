# research/session_report.py
#
# Session-level report builder.
#
# Produces a machine-readable JSON and human-readable markdown for a
# completed multi-batch research session.
#
# The report answers:
#   - what ran        (batches, total experiments, classes tested)
#   - best candidate  (highest-scored accepted experiment across all batches)
#   - dominant findings (key patterns observed across batches)
#   - repeated failures (classes that consistently failed)
#   - next direction  (recommendation based on session outcome)
#   - human review    (explicit flag with reason)
#   - stop reason     (why the session terminated)
#
# Output paths:
#   data/research_ledger/reports/{session_id}_session.json
#   data/research_ledger/reports/{session_id}_session_report.md

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any

_ROOT       = pathlib.Path(__file__).resolve().parent.parent
REPORTS_DIR = _ROOT / "data" / "research_ledger" / "reports"


# ── Public API ────────────────────────────────────────────────────────────────

def generate_session_report(
    session_id:     str,
    batch_reports:  list[dict],
    diagnosis:      dict,
    stop_condition: str,
    stop_reason:    str,
    notes:          str = "",
) -> dict[str, Any]:
    """
    Build the structured session report, write JSON + markdown to disk,
    and return the report dict.

    Args:
        session_id:     Session identifier (e.g. "session_20260409T120000").
        batch_reports:  List of per-batch report dicts from generate_batch_report().
        diagnosis:      Final session diagnosis from diagnose_session_state().
        stop_condition: condition_name from check_stop_conditions().
        stop_reason:    Human-readable stop reason from check_stop_conditions().
        notes:          Optional human context string.

    Returns:
        The session report dict (same content as the JSON file).
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    report = _build_session_report(
        session_id, batch_reports, diagnosis,
        stop_condition, stop_reason, notes,
    )

    json_path = REPORTS_DIR / f"{session_id}_session.json"
    md_path   = REPORTS_DIR / f"{session_id}_session_report.md"

    json_path.write_text(json.dumps(report, indent=2))
    md_path.write_text(_build_markdown(report))

    return report


# ── Report construction ───────────────────────────────────────────────────────

def _build_session_report(
    session_id:     str,
    batch_reports:  list[dict],
    diagnosis:      dict,
    stop_condition: str,
    stop_reason:    str,
    notes:          str,
) -> dict[str, Any]:

    # Aggregate stats across batches
    total_experiments = sum(
        r.get("what_ran", {}).get("n_experiments", 0) for r in batch_reports
    )
    total_accepted = sum(
        r.get("what_ran", {}).get("n_accepted", 0) for r in batch_reports
    )
    total_rejected = total_experiments - total_accepted

    all_classes: list[str] = []
    for r in batch_reports:
        for c in r.get("what_ran", {}).get("classes_tested", []):
            if c not in all_classes:
                all_classes.append(c)

    best_cand       = _build_best_candidate(batch_reports, diagnosis)
    dominant_findings = _derive_dominant_findings(batch_reports, diagnosis)
    repeated_failures = diagnosis.get("deprioritized", [])
    next_direction  = _recommend_next_direction(batch_reports, diagnosis, stop_condition)
    human_review    = _should_flag_human_review(batch_reports)
    human_review_reason = _human_review_reason(human_review, batch_reports, diagnosis)

    batch_summaries = [
        {
            "batch_id":    r.get("batch_id"),
            "n_accepted":  r.get("what_ran", {}).get("n_accepted", 0),
            "n_total":     r.get("what_ran", {}).get("n_experiments", 0),
            "best_score":  (r.get("best_candidate") or {}).get("score"),
            "best_tier":   (r.get("best_candidate") or {}).get("tier"),
            "next_action": (r.get("next_action") or {}).get("recommendation"),
        }
        for r in batch_reports
    ]

    return {
        "schema_version": "1.0",
        "session_id":     session_id,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "notes":          notes,

        "what_ran": {
            "session_id":        session_id,
            "batches_completed": len(batch_reports),
            "total_experiments": total_experiments,
            "total_accepted":    total_accepted,
            "total_rejected":    total_rejected,
            "classes_tested":    sorted(all_classes),
        },

        "best_candidate":    best_cand,
        "dominant_findings": dominant_findings,
        "repeated_failures": repeated_failures,

        "next_direction": next_direction,

        "human_review_recommended": human_review,
        "human_review_reason":      human_review_reason,

        "stop_condition": stop_condition,
        "stop_reason":    stop_reason,

        "batch_summaries":    batch_summaries,
        "diagnosis_snapshot": {
            "focus_classes":             diagnosis.get("focus_classes", []),
            "deprioritized":             diagnosis.get("deprioritized", []),
            "dominant_failure":          diagnosis.get("dominant_failure"),
            "session_best_score":        diagnosis.get("session_best_score"),
            "session_best_class":        diagnosis.get("session_best_class"),
            "n_consecutive_no_progress": diagnosis.get("n_consecutive_no_progress"),
            "diagnosis_reason":          diagnosis.get("diagnosis_reason"),
        },
    }


def _build_best_candidate(
    batch_reports: list[dict],
    diagnosis:     dict,
) -> dict[str, Any] | None:
    """Find the best-scored accepted candidate across all batches."""
    best_score = -1.0
    best_entry: dict[str, Any] | None = None
    best_batch_id: str | None = None

    for report in batch_reports:
        bc = report.get("best_candidate")
        if bc and bc.get("decision") == "ACCEPTED":
            score = bc.get("score") or 0.0
            if score > best_score:
                best_score    = score
                best_entry    = bc
                best_batch_id = report.get("batch_id")

    if best_entry is None:
        return None

    return {**best_entry, "batch_id": best_batch_id}


def _derive_dominant_findings(
    batch_reports: list[dict],
    diagnosis:     dict,
) -> list[str]:
    findings: list[str] = []

    if not batch_reports:
        return ["No batches completed in this session."]

    total_exp = sum(r.get("what_ran", {}).get("n_experiments", 0) for r in batch_reports)
    total_acc = sum(r.get("what_ran", {}).get("n_accepted", 0)    for r in batch_reports)

    if total_acc == 0:
        findings.append(
            f"No experiments accepted across {len(batch_reports)} batches "
            f"({total_exp} total). The current parameter space may be exhausted "
            "or the baseline may need re-evaluation."
        )
    else:
        findings.append(
            f"{total_acc}/{total_exp} experiments accepted across "
            f"{len(batch_reports)} batches."
        )

    dom = diagnosis.get("dominant_failure")
    if dom:
        label = {
            "worst_pnl":   "worst-case PnL regression (tail-risk concern)",
            "median_pnl":  "median PnL regression (central performance concern)",
            "trade_floor": "trade volume floor breach (over-filtering)",
        }.get(dom, dom)
        findings.append(f"Dominant failure mode across batches: {label}.")

    dep = diagnosis.get("deprioritized", [])
    if dep:
        findings.append(
            f"Classes with consistent worst-case failure (deprioritized): "
            f"{', '.join(dep)}."
        )

    n_no_progress = diagnosis.get("n_consecutive_no_progress", 0)
    if n_no_progress >= 2:
        findings.append(
            f"{n_no_progress} consecutive batches with zero accepted candidates — "
            "this region of the parameter space is not productive."
        )

    best_score = diagnosis.get("session_best_score") or 0.0
    best_class = diagnosis.get("session_best_class")
    if best_score > 0 and best_class:
        findings.append(
            f"Session best score: {best_score:.0f} on {best_class}."
        )

    return findings


def _recommend_next_direction(
    batch_reports:  list[dict],
    diagnosis:      dict,
    stop_condition: str,
) -> dict[str, Any]:
    focus_classes = diagnosis.get("focus_classes", [])
    dep           = diagnosis.get("deprioritized", [])
    best_score    = diagnosis.get("session_best_score") or 0.0
    n_no_progress = diagnosis.get("n_consecutive_no_progress", 0)

    if stop_condition == "strong_candidate_found":
        return {
            "recommendation": "promote_best",
            "rationale": (
                "A strong-tier candidate was found. "
                "Use scripts/promote_candidate.py --record <path> to promote it."
            ),
            "focus_classes": focus_classes,
        }

    total_accepted = sum(
        r.get("what_ran", {}).get("n_accepted", 0) for r in batch_reports
    )

    if total_accepted > 0 and best_score >= 66:
        return {
            "recommendation": "promote_best",
            "rationale": (
                "At least one review_worthy or better candidate was found. "
                "Run scripts/promote_candidate.py --record <path> to promote."
            ),
            "focus_classes": focus_classes,
        }

    if total_accepted > 0 and best_score >= 46:
        return {
            "recommendation": "retest_accepted",
            "rationale": (
                "Accepted candidates are noisy. Consider running validate_strategy.py "
                "with extended seeds before promoting."
            ),
            "focus_classes": focus_classes,
        }

    if n_no_progress >= 2:
        return {
            "recommendation": "run_diagnosis",
            "rationale": (
                "Multiple consecutive batches with no acceptance. "
                "Run scripts/research_cycle.py to diagnose and reorient."
            ),
            "focus_classes": focus_classes,
        }

    if dep:
        return {
            "recommendation": "shift_focus",
            "rationale": (
                f"Classes {dep} are deprioritized. "
                f"Focus next session on: {focus_classes}."
            ),
            "focus_classes": focus_classes,
        }

    return {
        "recommendation": "continue_session",
        "rationale": (
            "Session ended without a strong signal. "
            f"Run another session focusing on: {focus_classes}."
        ),
        "focus_classes": focus_classes,
    }


def _should_flag_human_review(batch_reports: list[dict]) -> bool:
    """True if any batch produced an accepted candidate worth reviewing."""
    for report in batch_reports:
        bc = report.get("best_candidate")
        if bc and bc.get("decision") == "ACCEPTED":
            if bc.get("tier") in ("strong", "review_worthy", "noisy"):
                return True
    return False


def _human_review_reason(
    flag:          bool,
    batch_reports: list[dict],
    diagnosis:     dict,
) -> str:
    if not flag:
        return "No accepted candidates across the session — no action needed."

    # Use the diagnosis best-candidate artifact when available
    cand = diagnosis.get("session_best_candidate")
    if cand:
        return (
            f"Best accepted candidate: {cand.get('experiment_id')} "
            f"(class={cand.get('experiment_class')}, "
            f"score={cand.get('score', '?')}, tier={cand.get('tier', '?')}). "
            "Identify its record path from the ledger summary and run "
            "scripts/promote_candidate.py --record <path>."
        )

    for report in batch_reports:
        bc = report.get("best_candidate")
        if bc and bc.get("decision") == "ACCEPTED":
            return (
                f"Best accepted candidate: {bc.get('experiment_id')} "
                f"(class={bc.get('experiment_class')}, score={bc.get('score')}, "
                f"tier={bc.get('tier')}). "
                "Identify its record path from the ledger summary and run "
                "scripts/promote_candidate.py --record <path>."
            )

    return "Accepted candidates present — review before promoting."


# ── Markdown rendering ────────────────────────────────────────────────────────

def _build_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    w  = report.get("what_ran", {})
    ts = report.get("generated_at", "")[:10]

    lines += [
        f"# Research Session Report: {report['session_id']}",
        "",
        f"**Generated**: {ts}  ",
        f"**Batches completed**: {w.get('batches_completed')}  ",
        f"**Experiments**: {w.get('total_experiments')} total "
        f"({w.get('total_accepted')} accepted / {w.get('total_rejected')} rejected)  ",
        f"**Classes tested**: {', '.join(w.get('classes_tested', []))}  ",
        "",
    ]

    if report.get("notes"):
        lines += [f"**Notes**: {report['notes']}", ""]

    lines += [
        "---",
        "",
        f"## Stop Condition: `{report.get('stop_condition', '—')}`",
        "",
        report.get("stop_reason", ""),
        "",
    ]

    hr = report.get("human_review_recommended", False)
    lines += [
        f"## {'⚑ Human Review Recommended' if hr else 'No Human Review Required'}",
        "",
        report.get("human_review_reason", ""),
        "",
    ]

    bc = report.get("best_candidate")
    if bc:
        lines += [
            "## Best Candidate (Session)",
            "",
            f"**{bc.get('experiment_id')}** — `{bc.get('experiment_class')}`  ",
            f"**Batch**: {bc.get('batch_id')}  ",
            f"**Score**: {bc.get('score')} ({bc.get('tier')})  ",
            f"**Decision**: {bc.get('decision')}  ",
            f"**Params**: `{bc.get('candidate_config', {})}`  ",
        ]
        if bc.get("pnl_delta") is not None:
            lines.append(f"**PnL Δ**: {bc['pnl_delta']:+.2f}  ")
        if bc.get("worst_pnl_delta") is not None:
            lines.append(f"**Worst Δ**: {bc['worst_pnl_delta']:+.2f}  ")
        lines.append("")

    lines += ["## Dominant Findings", ""]
    for f in report.get("dominant_findings", []):
        lines.append(f"- {f}")
    lines.append("")

    dep = report.get("repeated_failures", [])
    if dep:
        lines += [
            "## Repeated Failures",
            "",
            f"Classes deprioritized due to consistent worst-case failure: "
            f"**{', '.join(dep)}**.",
            "",
        ]

    batch_summaries = report.get("batch_summaries", [])
    if batch_summaries:
        lines += ["## Batch Summaries", ""]
        lines.append(
            f"{'Batch':<38} {'Accepted':>9} {'Best Score':>11} "
            f"{'Best Tier':<14} {'Next Action'}"
        )
        lines.append("-" * 95)
        for b in batch_summaries:
            score_str = f"{b['best_score']:.0f}" if b.get("best_score") is not None else "—"
            tier_str  = b.get("best_tier") or "—"
            lines.append(
                f"{(b.get('batch_id') or ''):38} "
                f"{b.get('n_accepted', 0):>4}/{b.get('n_total', 0):<4} "
                f"{score_str:>10} "
                f"{tier_str:<14} "
                f"{(b.get('next_action') or '')}"
            )
        lines.append("")

    nd = report.get("next_direction", {})
    lines += [
        "## Recommended Next Direction",
        "",
        f"**Action**: `{nd.get('recommendation', '—')}`  ",
        "",
        nd.get("rationale", ""),
        "",
    ]
    if nd.get("focus_classes"):
        lines.append(f"**Focus classes for next session**: {nd['focus_classes']}")
        lines.append("")

    # Diagnosis snapshot
    ds = report.get("diagnosis_snapshot", {})
    if ds.get("diagnosis_reason"):
        lines += [
            "## Diagnosis Snapshot",
            "",
            f"_{ds['diagnosis_reason']}_",
            "",
        ]

    lines += [
        "---",
        "",
        "*Report generated by OpenClaw autonomous research session manager.*  ",
        "*Promotion requires explicit human action via scripts/promote_candidate.py --record <path>*",
    ]

    return "\n".join(lines)
