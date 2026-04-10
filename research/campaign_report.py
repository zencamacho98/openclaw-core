# research/campaign_report.py
#
# Campaign-level operator brief generator.
#
# Produces a machine-readable JSON and a concise human-readable markdown that
# answer all the questions an operator needs after a full campaign:
#
#   - What was the campaign trying to do?
#   - How many sessions / batches / experiments ran?
#   - What experiment families were emphasized?
#   - What improved?
#   - What repeatedly failed?
#   - What is the best candidate of the whole campaign?
#   - Exact artifact path for that best candidate.
#   - Is human review recommended?
#   - What should the next campaign focus on?
#   - Why did the campaign stop?
#
# Output paths:
#   data/campaigns/{campaign_id}/brief.json
#   data/campaigns/{campaign_id}/brief.md
#
# Public API:
#   generate_campaign_report(state: CampaignState) → dict

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── Public API ────────────────────────────────────────────────────────────────

def generate_campaign_report(state: "CampaignState") -> dict[str, Any]:  # type: ignore[name-defined]
    """
    Build the campaign operator brief, write JSON + markdown to disk,
    and return the report dict.

    The returned dict also carries two private keys:
        _brief_json_path — absolute path string for the JSON file
        _brief_md_path   — absolute path string for the markdown file

    These are used by CampaignRunner to store artifact paths before
    the private keys are stripped from the state.
    """
    campaign_dir = _ROOT / "data" / "campaigns" / state.campaign_id
    campaign_dir.mkdir(parents=True, exist_ok=True)

    report = _build_report(state)

    json_path = campaign_dir / "brief.json"
    md_path   = campaign_dir / "brief.md"

    # Write clean copy (without private path keys)
    clean = {k: v for k, v in report.items() if not k.startswith("_")}
    json_path.write_text(json.dumps(clean, indent=2))
    md_path.write_text(_build_markdown(report))

    report["_brief_json_path"] = str(json_path)
    report["_brief_md_path"]   = str(md_path)

    return report


# ── Report construction ───────────────────────────────────────────────────────

def _build_report(state: Any) -> dict[str, Any]:
    p   = state.progress
    cfg = state.config
    bc  = state.best_candidate
    art = state.artifacts

    # Classes emphasised (count occurrences across all sessions)
    class_counts: dict[str, int] = {}
    for s in state.session_summaries:
        for c in s.get("classes_tested", []):
            class_counts[c] = class_counts.get(c, 0) + 1
    classes_emphasized = sorted(class_counts, key=lambda k: class_counts[k], reverse=True)

    human_review = any(s.get("human_review") for s in state.session_summaries)

    promote_cmd: str | None = None
    rec_path = art.get("best_validation_record")
    if rec_path:
        promote_cmd = f"python scripts/promote_candidate.py --record {rec_path}"

    return {
        "schema_version": "1.0",
        "campaign_id":    state.campaign_id,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "goal":           state.goal,
        "notes":          state.notes,
        "status":         state.status,

        "what_ran": {
            "sessions_ran":       p["sessions_completed"],
            "total_batches":      p["total_batches"],
            "total_experiments":  p["total_experiments"],
            "total_accepted":     p["total_accepted"],
            "classes_emphasized": classes_emphasized,
            "session_ids":        state.session_ids,
        },

        "stop_condition": state.stop_condition,
        "stop_reason":    state.stop_reason,

        "dominant_findings":  _dominant_findings(state),
        "what_improved":      _what_improved(state),
        "what_repeatedly_failed": _what_repeatedly_failed(state),

        "best_candidate": bc,

        "artifacts": {
            "best_validation_record": rec_path,
            "best_experiment_id":     art.get("best_experiment_id"),
            "best_session_id":        art.get("best_session_id"),
            "best_promotion_command": promote_cmd,
            "session_reports":        art.get("session_reports", []),
            "session_md_reports":     art.get("session_md_reports", []),
        },

        "human_review_recommended": human_review,
        "human_review_reason": (
            _human_review_reason(state) if human_review
            else "No sessions produced accepted candidates worth reviewing."
        ),

        "next_campaign_focus": _next_campaign_focus(state),

        "session_summaries": state.session_summaries,
    }


# ── Synthesis helpers ─────────────────────────────────────────────────────────

def _dominant_findings(state: Any) -> list[str]:
    findings: list[str] = []
    p = state.progress

    total_acc = p["total_accepted"]
    total_exp = p["total_experiments"]
    n_sess    = p["sessions_completed"]

    if total_exp == 0:
        findings.append("Campaign produced no experiments (dry-run or early stop).")
        return findings

    if total_acc == 0:
        findings.append(
            f"No experiments accepted across {n_sess} session(s) "
            f"({total_exp} total). Parameter space may be exhausted or "
            "baseline needs re-evaluation."
        )
    else:
        rate = total_acc / total_exp * 100
        findings.append(
            f"{total_acc}/{total_exp} experiments accepted "
            f"({rate:.0f}%) across {n_sess} session(s)."
        )

    strong_sessions = [
        s for s in state.session_summaries
        if s.get("best_tier") in ("strong", "review_worthy")
    ]
    if strong_sessions:
        findings.append(
            f"{len(strong_sessions)}/{n_sess} session(s) produced strong or "
            "review_worthy candidates."
        )

    dom_failures = [f for f in p.get("session_dominant_failures", []) if f]
    if dom_failures:
        most_common = max(set(dom_failures), key=dom_failures.count)
        count = dom_failures.count(most_common)
        label = {
            "worst_pnl":   "worst-case PnL regression",
            "median_pnl":  "median PnL regression",
            "trade_floor": "trade volume floor breach",
        }.get(most_common, most_common)
        findings.append(
            f"Most frequent failure mode: {label} "
            f"(appeared in {count}/{n_sess} session(s))."
        )

    bc = state.best_candidate
    if bc:
        findings.append(
            f"Campaign best: {bc.get('experiment_id')} — "
            f"score={bc.get('score')}, tier={bc.get('tier')}, "
            f"class={bc.get('experiment_class')}."
        )

    return findings


def _what_improved(state: Any) -> list[str]:
    improved: list[str] = []
    bc = state.best_candidate
    if bc:
        pnl_d  = bc.get("pnl_delta")
        wrst_d = bc.get("worst_pnl_delta")
        if pnl_d is not None and pnl_d > 0:
            improved.append(f"Median PnL: {pnl_d:+.2f} (best candidate).")
        if wrst_d is not None and wrst_d > 0:
            improved.append(f"Worst-case PnL: {wrst_d:+.2f} (best candidate).")
        cls = bc.get("experiment_class")
        if cls:
            improved.append(f"Most productive experiment class: {cls}.")
    if not improved:
        improved.append("No clear improvement found in this campaign.")
    return improved


def _what_repeatedly_failed(state: Any) -> list[str]:
    failed: list[str] = []
    p = state.progress

    dom_failures = [f for f in p.get("session_dominant_failures", []) if f]
    if dom_failures:
        most_common = max(set(dom_failures), key=dom_failures.count)
        count = dom_failures.count(most_common)
        n = p["sessions_completed"]
        label = {
            "worst_pnl": (
                f"Worst-case PnL regression dominated {count}/{n} session(s) — "
                "tail risk is a persistent blocker."
            ),
            "median_pnl": (
                f"Median PnL regression dominated {count}/{n} session(s) — "
                "central performance is consistently degraded."
            ),
            "trade_floor": (
                f"Trade volume floor breach dominated {count}/{n} session(s) — "
                "entry filters are over-restrictive."
            ),
        }.get(most_common, f"Failure mode '{most_common}' dominated {count}/{n} session(s).")
        failed.append(label)

    no_prog = p.get("consecutive_no_progress_sessions", 0)
    if no_prog >= 2:
        failed.append(
            f"{no_prog} consecutive sessions with zero accepted candidates — "
            "current parameter space is not productive."
        )

    if not failed:
        failed.append("No dominant failure pattern identified.")
    return failed


def _human_review_reason(state: Any) -> str:
    bc  = state.best_candidate
    rec = state.artifacts.get("best_validation_record")
    if bc:
        cmd = (
            f"python scripts/promote_candidate.py --record {rec}"
            if rec else "see artifacts"
        )
        return (
            f"Best candidate: {bc.get('experiment_id')} "
            f"(score={bc.get('score')}, tier={bc.get('tier')}, "
            f"class={bc.get('experiment_class')}). "
            f"Promote with: {cmd}"
        )
    return "Accepted candidates present — review session reports for details."


def _next_campaign_focus(state: Any) -> str:
    bc   = state.best_candidate
    cond = state.stop_condition
    p    = state.progress

    if cond in ("strong_candidate_confirmed",):
        exp_id = state.artifacts.get("best_experiment_id", "?")
        return (
            f"Promote the best candidate ({exp_id}) and run a validation "
            "session to confirm robustness before starting a new campaign."
        )

    if bc and bc.get("tier") in ("strong", "review_worthy"):
        return (
            f"Promote or validate the best candidate ({bc.get('experiment_id')}), "
            f"then focus the next campaign on {bc.get('experiment_class')} variants "
            "to see if further improvement is possible."
        )

    if cond == "no_progress_campaign":
        dom_failures = [f for f in p.get("session_dominant_failures", []) if f]
        if dom_failures:
            mode = max(set(dom_failures), key=dom_failures.count)
            suggestions = {
                "worst_pnl": (
                    "Investigate loss structure — consider tightening stops "
                    "or reducing position sizing before the next campaign."
                ),
                "median_pnl": (
                    "Revisit entry quality thresholds — current configs may be "
                    "filtering out too many good entries."
                ),
                "trade_floor": (
                    "Relax entry criteria — current filters block too many trades, "
                    "reducing statistical confidence."
                ),
            }
            return suggestions.get(
                mode,
                f"Address the dominant failure mode '{mode}' before continuing.",
            )
        return (
            "No clear direction. Consider expanding approved parameter ranges "
            "in policy.py or adding new experiment classes."
        )

    if cond == "dominant_failure_persists":
        return (
            "The same failure mode blocked every session. Update policy.py to "
            "allow different parameter ranges or add new experiment classes."
        )

    if bc and bc.get("tier") == "noisy":
        return (
            f"Re-test the best candidate ({bc.get('experiment_id')}) with extended "
            "seeds via scripts/validate_strategy.py before promoting. Then run "
            "another campaign targeting the same class."
        )

    return (
        "No strong signal found. Review policy.py to shift or expand the "
        "parameter search space, then run a new focused campaign."
    )


# ── Markdown rendering ────────────────────────────────────────────────────────

def _build_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    w   = report.get("what_ran", {})
    art = report.get("artifacts", {})
    ts  = report.get("generated_at", "")[:10]

    lines += [
        f"# Campaign Operator Brief: {report['campaign_id']}",
        "",
        f"**Generated**: {ts}  ",
        f"**Goal**: {report.get('goal', '—')}  ",
        f"**Status**: {report.get('status', '—')}  ",
    ]
    if report.get("notes"):
        lines.append(f"**Notes**: {report['notes']}  ")
    lines.append("")

    lines += [
        "---",
        "",
        "## What Ran",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Sessions | {w.get('sessions_ran')} |",
        f"| Batches | {w.get('total_batches')} |",
        f"| Experiments | {w.get('total_experiments')} total / {w.get('total_accepted')} accepted |",
        f"| Classes emphasized | {', '.join(w.get('classes_emphasized', [])) or '—'} |",
        "",
    ]

    lines += [
        f"## Stop Condition: `{report.get('stop_condition', '—')}`",
        "",
        report.get("stop_reason", ""),
        "",
    ]

    # Best candidate
    bc = report.get("best_candidate")
    if bc:
        lines += [
            "## Best Candidate (Campaign)",
            "",
            f"**{bc.get('experiment_id')}** — `{bc.get('experiment_class')}`  ",
            f"**Session**: {bc.get('session_id', '?')}  ",
            f"**Score**: {bc.get('score')} ({bc.get('tier')})  ",
            f"**Params**: `{bc.get('candidate_config', {})}` ",
        ]
        if bc.get("pnl_delta") is not None:
            lines.append(f"**PnL Δ**: {bc['pnl_delta']:+.2f}  ")
        if bc.get("worst_pnl_delta") is not None:
            lines.append(f"**Worst Δ**: {bc['worst_pnl_delta']:+.2f}  ")
        lines.append("")

    # Artifact map
    lines += ["## Artifact Map", ""]
    if art.get("best_experiment_id"):
        lines.append(f"- **Best experiment ID**: `{art['best_experiment_id']}`  ")
    if art.get("best_session_id"):
        lines.append(f"- **Best session ID**: `{art['best_session_id']}`  ")
    if art.get("best_validation_record"):
        lines.append(f"- **Best validation record**: `{art['best_validation_record']}`  ")
    if art.get("best_promotion_command"):
        lines.append(f"- **Promote with**: `{art['best_promotion_command']}`  ")
    if art.get("session_reports"):
        lines.append("")
        lines.append("**Session reports**:")
        for path in art["session_reports"]:
            lines.append(f"  - `{path}`")
    lines.append("")

    # Human review
    hr = report.get("human_review_recommended", False)
    lines += [
        f"## {'Human Review Recommended' if hr else 'No Human Review Required'}",
        "",
        report.get("human_review_reason", ""),
        "",
    ]

    # Dominant findings
    lines += ["## Dominant Findings", ""]
    for f in report.get("dominant_findings", []):
        lines.append(f"- {f}")
    lines.append("")

    # What improved / failed
    lines += ["## What Improved", ""]
    for item in report.get("what_improved", []):
        lines.append(f"- {item}")
    lines.append("")

    lines += ["## What Repeatedly Failed", ""]
    for item in report.get("what_repeatedly_failed", []):
        lines.append(f"- {item}")
    lines.append("")

    # Session summaries table
    summaries = report.get("session_summaries", [])
    if summaries:
        lines += ["## Session Summaries", ""]
        hdr = (
            f"{'Session':<38} {'Accepted':>9} {'Best Score':>11} "
            f"{'Best Tier':<15} Stop Condition"
        )
        lines.append(hdr)
        lines.append("-" * 100)
        for s in summaries:
            score_str = (
                f"{s['best_score']:.0f}"
                if s.get("best_score") is not None
                else "—"
            )
            lines.append(
                f"{(s.get('session_id') or ''):38} "
                f"{s.get('total_accepted', 0):>4}/{s.get('total_experiments', 0):<4} "
                f"{score_str:>10} "
                f"{(s.get('best_tier') or '—'):<15} "
                f"{(s.get('stop_condition') or '')}"
            )
        lines.append("")

    # Next campaign focus
    lines += [
        "## Recommended Next Campaign Focus",
        "",
        report.get("next_campaign_focus", ""),
        "",
        "---",
        "",
        "*Campaign brief generated by OpenClaw autonomous research campaign manager.*  ",
        "*Promotion requires explicit human action via "
        "scripts/promote_candidate.py --record <path>*",
    ]

    return "\n".join(lines)
