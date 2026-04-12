# peter/handlers.py
#
# Command handlers for Peter.
#
# Each handle_*() function:
#   1. Reads the relevant artifacts from disk (JSON files only)
#   2. Synthesizes a Response with summary, metrics, artifacts, next_action
#
# IMPORTANT: This module does NOT import from research/, app/, discord, or any
# external transport. All information comes from the JSON artifacts written by
# the research system. This is the architectural boundary that keeps Peter
# transport-agnostic and independently deployable.
#
# Artifact sources:
#   data/campaigns/{id}/state.json              — campaign state
#   data/campaigns/{id}/brief.json              — completed campaign brief
#   data/research_ledger/reports/{id}.json      — batch report
#   data/research_ledger/reports/{id}_session.json — session report
#   data/research_ledger/ledger.jsonl           — per-experiment audit trail
#   data/validation_runs/{timestamp}_{id}.json  — validation records
#
# Public API:
#   handle_status(command)           → Response
#   handle_inspect_campaign(command) → Response
#   handle_best_candidate(command)   → Response
#   handle_list_review_worthy(command) → Response
#   handle_promote_guidance(command) → Response
#   handle_explain_result(command)   → Response
#   handle_run_campaign(command)     → Response
#   handle_resume_campaign(command)  → Response
#   handle_help(command)             → Response
#   handle_unknown(command)          → Response

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any, Optional

from peter.commands import Command, CommandType, HELP_TEXT
from peter.responses import Response, error_response, no_data_response
from observability.summary import full_belfort_brief

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_CAMPAIGNS    = _ROOT / "data" / "campaigns"
_REPORTS      = _ROOT / "data" / "research_ledger" / "reports"
_LEDGER       = _ROOT / "data" / "research_ledger" / "ledger.jsonl"
_VAL_RUNS     = _ROOT / "data" / "validation_runs"

# ── Frank Lloyd intake paths (patchable for tests) ────────────────────────────
_FL_REQUESTS  = _ROOT / "data" / "frank_lloyd" / "requests"
_FL_BUILD_LOG = _ROOT / "data" / "frank_lloyd" / "build_log.jsonl"

# Status derivation map — shared across FL NL handler helpers.
# Mirrors the individual module maps; kept here so handlers.py stays self-contained.
_FL_STATUS_MAP: dict[str, str] = {
    "request_queued":            "pending_spec",
    "spec_ready":                "pending_review",
    "spec_approved":             "spec_approved",
    "spec_rejected":             "spec_rejected",
    "abandoned":                 "abandoned",
    "stage2_authorized":         "stage2_authorized",
    "draft_generation_started":  "draft_generating",
    "draft_generated":           "draft_generated",
    "draft_blocked":             "draft_blocked",
    "draft_promoted":            "draft_promoted",
    "draft_discarded":           "stage2_authorized",
}

# Required status per lifecycle action (used by resolver)
_FL_ACTION_TARGET_STATUSES: dict[str, frozenset[str]] = {
    "approve":          frozenset({"pending_review"}),
    "reject":           frozenset({"pending_review"}),
    "authorize_stage2": frozenset({"spec_approved"}),
    "draft":            frozenset({"stage2_authorized"}),
    "promote":          frozenset({"draft_generated"}),
    "discard":          frozenset({"draft_generated", "draft_blocked"}),
}

# HANDOFF_SPEC §1 — success-criterion markers Peter recognises
_SUCCESS_MARKERS = ("success:", "success criterion:", "done when:", "test:", "verify:")
# Pure-vague terms that signal an underspecified description (when used alone)
_VAGUE_TERMS = frozenset({"better", "nicer", "cleaner", "faster", "improve", "fix it"})

# Tier rank for sorting (higher = better)
_TIER_RANK = {"strong": 4, "review_worthy": 3, "noisy": 2, "weak": 1, "rejected": 0}
# Threshold score for "review-worthy"
_REVIEW_WORTHY_SCORE = 66.0


# ── Handlers ──────────────────────────────────────────────────────────────────

def handle_status(command: Command) -> Response:
    """
    Current system state: latest campaign progress, best candidate, pending review.
    Falls back gracefully when no campaign exists.
    """
    state = _load_latest_campaign_state()

    if state is None:
        latest_batch = _load_latest_batch_report()
        if latest_batch is None:
            return no_data_response("status", "campaigns or batch reports")

        # At least show latest batch
        w   = latest_batch.get("what_ran", {})
        bc  = latest_batch.get("best_candidate")
        na  = latest_batch.get("next_action", {})
        hr  = latest_batch.get("human_review_recommended", False)
        summary = (
            f"No campaign found. Latest batch: {latest_batch.get('batch_id')} — "
            f"{w.get('n_accepted', 0)}/{w.get('n_experiments', 0)} accepted."
        )
        metrics = {
            "batch":    latest_batch.get("batch_id", "?"),
            "accepted": f"{w.get('n_accepted', 0)}/{w.get('n_experiments', 0)}",
            "best_tier": (bc or {}).get("tier", "none"),
        }
        belfort = full_belfort_brief()
        return Response(
            command_type        = "status",
            ok                  = True,
            summary             = summary,
            metrics             = metrics,
            next_action         = na.get("recommendation", "run a new campaign"),
            human_review_needed = hr,
            human_review_reason = latest_batch.get("human_review_reason", ""),
            raw                 = {**latest_batch, "belfort": belfort},
        )

    # Campaign found
    p   = state.get("progress", {})
    cfg = state.get("config", {})
    bc  = state.get("best_candidate")
    art = state.get("artifacts", {})
    status_str = state.get("status", "?")
    stop_cond  = state.get("stop_condition") or "in progress"

    sessions_done  = p.get("sessions_completed", 0)
    sessions_total = cfg.get("max_sessions", "?")
    exp_done       = p.get("total_experiments", 0)
    exp_total      = cfg.get("max_total_experiments", "?")
    accepted       = p.get("total_accepted", 0)

    summary_parts = [
        f"Campaign {state.get('campaign_id')} is {status_str}.",
        f"{sessions_done}/{sessions_total} sessions, "
        f"{exp_done}/{exp_total} experiments, "
        f"{accepted} accepted.",
    ]
    if bc:
        summary_parts.append(
            f"Best candidate: {bc.get('experiment_id')} "
            f"({bc.get('tier')}, score={bc.get('score')})."
        )
    if stop_cond != "in progress":
        summary_parts.append(f"Stopped: {stop_cond}.")

    metrics = {
        "status":      status_str,
        "sessions":    f"{sessions_done}/{sessions_total}",
        "experiments": f"{exp_done}/{exp_total}",
        "accepted":    accepted,
        "best_tier":   (bc or {}).get("tier", "none"),
        "best_score":  (bc or {}).get("score", "—"),
        "stop":        stop_cond,
    }

    artifacts: dict[str, str] = {}
    if art.get("best_validation_record"):
        artifacts["best_record"] = art["best_validation_record"]
    if art.get("campaign_brief_md"):
        artifacts["brief"] = art["campaign_brief_md"]

    hr = any(
        s.get("human_review") for s in state.get("session_summaries", [])
    )
    hr_reason = ""
    if hr and bc:
        rec = art.get("best_validation_record", "<path>")
        hr_reason = (
            f"Best candidate {bc.get('experiment_id')} ({bc.get('tier')}) "
            f"ready for review. "
            f"Promote: python scripts/promote_candidate.py --record {rec}"
        )

    next_action = _derive_next_action(state)

    # Include Mr Belfort's live observability state in the response
    belfort = full_belfort_brief(campaign_id=state.get("campaign_id"))
    metrics["belfort_status"]   = belfort["status"]
    metrics["belfort_learning"] = belfort["actively_learning"]
    metrics["belfort_cost_usd"] = belfort["telemetry"]["estimated_cost_usd"]

    return Response(
        command_type        = "status",
        ok                  = True,
        summary             = (
            " ".join(summary_parts)
            + f" {belfort['summaries']['learning']}"
        ),
        metrics             = metrics,
        artifacts           = artifacts,
        next_action         = next_action,
        human_review_needed = hr,
        human_review_reason = hr_reason,
        raw                 = {**state, "belfort": belfort},
    )


def handle_inspect_campaign(command: Command) -> Response:
    """
    Detailed view of a campaign — latest by default, specific by ID.
    """
    campaign_id = command.args.get("campaign_id")

    if campaign_id:
        state = _load_campaign_state(campaign_id)
    else:
        state = _load_latest_campaign_state()

    if state is None:
        return no_data_response("inspect_campaign", "campaign")

    p   = state.get("progress", {})
    cfg = state.get("config", {})
    bc  = state.get("best_candidate")
    art = state.get("artifacts", {})
    cid = state.get("campaign_id", "?")

    sessions = state.get("session_summaries", [])
    session_lines = [
        f"  {s.get('session_id')} — "
        f"{s.get('total_accepted', 0)}/{s.get('total_experiments', 0)} accepted, "
        f"best: {s.get('best_tier', '—')} ({s.get('best_score') or '—'})"
        for s in sessions
    ]

    summary = (
        f"Campaign {cid}: \"{state.get('goal', '?')}\" | "
        f"status={state.get('status')} | "
        f"{p.get('sessions_completed', 0)}/{cfg.get('max_sessions', '?')} sessions | "
        f"{p.get('total_experiments', 0)}/{cfg.get('max_total_experiments', '?')} experiments | "
        f"{p.get('total_accepted', 0)} accepted."
    )

    metrics = {
        "goal":        state.get("goal", "?"),
        "status":      state.get("status", "?"),
        "sessions":    f"{p.get('sessions_completed', 0)}/{cfg.get('max_sessions', '?')}",
        "experiments": f"{p.get('total_experiments', 0)}/{cfg.get('max_total_experiments', '?')}",
        "accepted":    p.get("total_accepted", 0),
        "stop":        state.get("stop_condition") or "in progress",
        "best_tier":   (bc or {}).get("tier", "none"),
        "best_score":  (bc or {}).get("score", "—"),
    }

    artifacts: dict[str, str] = {}
    if art.get("best_validation_record"):
        artifacts["best_record"] = art["best_validation_record"]
    if art.get("best_experiment_id"):
        artifacts["best_experiment"] = art["best_experiment_id"]
    for i, path in enumerate(art.get("session_reports", []), 1):
        artifacts[f"session_{i}_report"] = path
    if art.get("campaign_brief_md"):
        artifacts["brief_md"] = art["campaign_brief_md"]
    if art.get("campaign_brief_json"):
        artifacts["brief_json"] = art["campaign_brief_json"]

    raw = {**state}
    if session_lines:
        raw["_session_lines"] = session_lines

    return Response(
        command_type        = "inspect_campaign",
        ok                  = True,
        summary             = summary,
        metrics             = metrics,
        artifacts           = artifacts,
        next_action         = _derive_next_action(state),
        human_review_needed = any(s.get("human_review") for s in sessions),
        human_review_reason = (
            f"Best candidate: {(bc or {}).get('experiment_id', '?')} "
            f"({(bc or {}).get('tier', '?')})"
            if bc else ""
        ),
        raw                 = raw,
    )


def handle_best_candidate(command: Command) -> Response:
    """
    Best candidate across the latest campaign with promote command.
    """
    state = _load_latest_campaign_state()

    if state is None:
        return no_data_response("best_candidate", "campaigns")

    bc  = state.get("best_candidate")
    art = state.get("artifacts", {})

    if bc is None:
        return Response(
            command_type = "best_candidate",
            ok           = True,
            summary      = (
                f"No accepted candidates found in campaign "
                f"{state.get('campaign_id')}. Run more sessions."
            ),
            next_action  = "python scripts/run_session.py",
            raw          = state,
        )

    rec_path = art.get("best_validation_record")
    promote_cmd = (
        f"python scripts/promote_candidate.py --record {rec_path}"
        if rec_path else "python scripts/promote_candidate.py"
    )

    tier  = bc.get("tier", "?")
    score = bc.get("score", "?")
    cls   = bc.get("experiment_class", "?")
    eid   = bc.get("experiment_id", "?")

    summary = (
        f"Best candidate: {eid} ({cls}) — score={score}, tier={tier}. "
        f"Campaign: {state.get('campaign_id')}."
    )

    metrics = {
        "experiment_id":    eid,
        "class":            cls,
        "score":            score,
        "tier":             tier,
        "pnl_delta":        bc.get("pnl_delta", "?"),
        "worst_pnl_delta":  bc.get("worst_pnl_delta", "?"),
        "params":           str(bc.get("candidate_config", {})),
        "session":          bc.get("session_id", "?"),
    }

    artifacts: dict[str, str] = {}
    if rec_path:
        artifacts["validation_record"] = rec_path
    artifacts["promote_command"] = promote_cmd

    hr = tier in ("strong", "review_worthy", "noisy")
    hr_reason = f"{promote_cmd}" if hr else ""

    return Response(
        command_type        = "best_candidate",
        ok                  = True,
        summary             = summary,
        metrics             = metrics,
        artifacts           = artifacts,
        next_action         = promote_cmd,
        human_review_needed = hr,
        human_review_reason = hr_reason,
        raw                 = bc,
    )


def handle_list_review_worthy(command: Command) -> Response:
    """
    List accepted candidates with score >= 66 from recent ledger entries.
    Scans the last 40 ledger batches.
    """
    candidates = _scan_review_worthy_from_ledger(limit=40)

    if not candidates:
        return Response(
            command_type = "list_review_worthy",
            ok           = True,
            summary      = "No review-worthy candidates found in the recent ledger.",
            next_action  = "python scripts/run_session.py",
            raw          = {"candidates": []},
        )

    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(
            f"{i}. {c.get('experiment_id')} — {c.get('experiment_class')} "
            f"score={c.get('score')} ({c.get('tier')})"
        )

    summary = (
        f"Found {len(candidates)} review-worthy candidate(s) "
        f"(score >= {_REVIEW_WORTHY_SCORE:.0f}) in recent runs."
    )

    artifacts: dict[str, str] = {}
    for c in candidates:
        path = c.get("output_path")
        if path:
            artifacts[c.get("experiment_id", "?")] = path

    top = candidates[0]
    top_path = top.get("output_path", "<path>")
    next_action = (
        f"Review top candidate: "
        f"python scripts/promote_candidate.py --record {top_path}"
    )

    return Response(
        command_type        = "list_review_worthy",
        ok                  = True,
        summary             = summary + "\n" + "\n".join(lines),
        metrics             = {"count": len(candidates)},
        artifacts           = artifacts,
        next_action         = next_action,
        human_review_needed = True,
        human_review_reason = f"{len(candidates)} candidate(s) await review.",
        raw                 = {"candidates": candidates},
    )


def handle_promote_guidance(command: Command) -> Response:
    """
    Exact promotion command for the best candidate of the latest campaign.
    """
    state = _load_latest_campaign_state()

    if state is None:
        return no_data_response("promote_guidance", "campaigns")

    bc  = state.get("best_candidate")
    art = state.get("artifacts", {})
    rec = art.get("best_validation_record")

    if bc is None or rec is None:
        return Response(
            command_type = "promote_guidance",
            ok           = True,
            summary      = "No promotable candidate found. No accepted experiments yet.",
            next_action  = "python scripts/run_session.py --notes \"find candidate to promote\"",
            raw          = {},
        )

    promote_cmd = f"python scripts/promote_candidate.py --record {rec}"

    summary = (
        f"To promote the best candidate ({bc.get('experiment_id')}, "
        f"tier={bc.get('tier')}, score={bc.get('score')}), run the command below."
    )

    return Response(
        command_type        = "promote_guidance",
        ok                  = True,
        summary             = summary,
        metrics             = {
            "experiment_id": bc.get("experiment_id", "?"),
            "tier":          bc.get("tier", "?"),
            "score":         bc.get("score", "?"),
            "class":         bc.get("experiment_class", "?"),
            "params":        str(bc.get("candidate_config", {})),
        },
        artifacts           = {
            "validation_record": rec,
            "promote_command":   promote_cmd,
        },
        next_action         = promote_cmd,
        human_review_needed = True,
        human_review_reason = "Manual confirmation required before promotion.",
        raw                 = bc,
    )


def handle_explain_result(command: Command) -> Response:
    """
    Plain-language explanation of a batch or session report.
    Defaults to the latest batch if no id given.
    """
    artifact_id = command.args.get("artifact_id", "")

    report = None
    report_type = "batch"

    if artifact_id:
        if "session" in artifact_id.lower():
            report = _load_session_report(artifact_id)
            report_type = "session"
        else:
            report = _load_batch_report(artifact_id)
            report_type = "batch"

    if report is None:
        report = _load_latest_batch_report()
        report_type = "batch"

    if report is None:
        return no_data_response("explain_result", "batch or session reports")

    if report_type == "batch":
        return _explain_batch(report)
    else:
        return _explain_session(report)


def handle_run_campaign(command: Command) -> Response:
    """
    Return the exact command to start a new campaign.
    Peter does not execute it — that is always the operator's action.
    """
    goal = command.args.get("goal", "").strip()

    if not goal:
        return error_response(
            "run_campaign",
            "No goal provided. Usage: run campaign <your goal here>",
        )

    cmd = f'python scripts/run_campaign.py --goal "{goal}"'

    return Response(
        command_type = "run_campaign",
        ok           = True,
        summary      = f"To start a new campaign with goal \"{goal}\", run the command below.",
        metrics      = {"goal": goal},
        artifacts    = {"run_command": cmd},
        next_action  = cmd,
        raw          = {"goal": goal, "command": cmd},
    )


def handle_resume_campaign(command: Command) -> Response:
    """
    Return the exact command to resume an interrupted campaign.
    Verifies the campaign state exists and is not already completed.
    """
    campaign_id = command.args.get("campaign_id", "").strip()

    if not campaign_id:
        # Try to find the most recent interrupted campaign
        state = _load_latest_interrupted_campaign()
        if state is None:
            return error_response(
                "resume_campaign",
                "No interrupted campaign found. Provide: resume campaign CAMPAIGN_ID",
            )
        campaign_id = state.get("campaign_id", "?")
    else:
        state = _load_campaign_state(campaign_id)
        if state is None:
            return error_response(
                "resume_campaign",
                f"No state found for campaign '{campaign_id}'. "
                "Check data/campaigns/ for valid campaign IDs.",
            )

    status = state.get("status", "?")
    if status == "completed":
        return Response(
            command_type = "resume_campaign",
            ok           = False,
            summary      = (
                f"Campaign '{campaign_id}' is already completed "
                f"(stop: {state.get('stop_condition')}). "
                "Start a new campaign instead."
            ),
            next_action  = 'python scripts/run_campaign.py --goal "your new goal"',
            raw          = state,
        )

    p = state.get("progress", {})
    cmd = f"python scripts/run_campaign.py --resume {campaign_id}"

    summary = (
        f"Campaign '{campaign_id}' ({status}) can be resumed. "
        f"{p.get('sessions_completed', 0)} sessions and "
        f"{p.get('total_experiments', 0)} experiments completed so far."
    )

    return Response(
        command_type = "resume_campaign",
        ok           = True,
        summary      = summary,
        metrics      = {
            "campaign_id":        campaign_id,
            "status":             status,
            "sessions_completed": p.get("sessions_completed", 0),
            "experiments_done":   p.get("total_experiments", 0),
        },
        artifacts    = {"resume_command": cmd},
        next_action  = cmd,
        raw          = state,
    )


def handle_show_queue(command: Command) -> Response:
    """
    List pending candidates in the upgrade queue.
    Reads data/candidate_queue.json directly — no service imports.
    """
    queue_file = _ROOT / "data" / "candidate_queue.json"
    if not queue_file.exists():
        return Response(
            command_type = "show_queue",
            ok           = True,
            summary      = "Upgrade queue is empty — no queue file found.",
            metrics      = {"pending": 0, "total": 0},
            next_action  = "start continuous",
            raw          = {"pending": [], "total": 0},
        )

    try:
        data = json.loads(queue_file.read_text())
        all_items = data.get("candidates", [])
        # Sort newest-first
        all_items = sorted(
            all_items,
            key=lambda c: (c.get("created_at", ""), c.get("queue_id", "")),
            reverse=True,
        )
    except Exception as exc:
        return error_response("show_queue", f"Failed to read queue: {exc}")

    pending = [c for c in all_items if c.get("status") == "pending"]
    n_pending = len(pending)
    n_total   = len(all_items)

    if n_pending == 0:
        return Response(
            command_type = "show_queue",
            ok           = True,
            summary      = f"Upgrade queue is empty. ({n_total} total items, none pending.)",
            metrics      = {"pending": 0, "total": n_total},
            next_action  = "start continuous",
            raw          = {"pending": [], "total": n_total},
        )

    lines = []
    for i, c in enumerate(pending, 1):
        tier  = c.get("tier", "?")
        score = c.get("score", "?")
        title = c.get("title", c.get("experiment_id", "?"))
        qid   = c.get("queue_id", "?")
        lines.append(f"{i}. [{qid}] {title} — score={score} ({tier})")

    top = pending[0]
    summary = (
        f"{n_pending} candidate(s) pending review in the upgrade queue:\n"
        + "\n".join(lines)
    )

    return Response(
        command_type        = "show_queue",
        ok                  = True,
        summary             = summary,
        metrics             = {"pending": n_pending, "total": n_total},
        next_action         = f"approve {top.get('queue_id', '')}",
        human_review_needed = True,
        human_review_reason = f"{n_pending} candidate(s) awaiting approval.",
        raw                 = {"pending": pending, "total": n_total},
    )


def handle_checker_findings(command: Command) -> Response:
    """
    Show recent health audit findings from the loop checker.
    Reads data/checker_findings.jsonl directly — no service imports.
    """
    findings_file = _ROOT / "data" / "checker_findings.jsonl"
    if not findings_file.exists():
        return Response(
            command_type = "checker_findings",
            ok           = True,
            summary      = "No active checker findings. Loop health looks good.",
            metrics      = {"open_findings": 0},
            raw          = {"findings": []},
        )

    try:
        raw_lines = findings_file.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        return error_response("checker_findings", f"Failed to read findings: {exc}")

    # Parse, newest-first, unacknowledged only, limit 10
    findings: list[dict] = []
    for line in reversed(raw_lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not rec.get("acknowledged"):
            findings.append(rec)
            if len(findings) >= 10:
                break

    if not findings:
        return Response(
            command_type = "checker_findings",
            ok           = True,
            summary      = "No active checker findings. Loop health looks good.",
            metrics      = {"open_findings": 0},
            raw          = {"findings": []},
        )

    lines = []
    for f in findings:
        sev   = f.get("severity", "?")
        title = f.get("title", "?")
        fid   = f.get("finding_id", "?")
        ts    = f.get("timestamp", "")[:16]
        lines.append(f"[{sev.upper()}] {title} — {ts} (id={fid})")

    summary = (
        f"{len(findings)} open checker finding(s):\n"
        + "\n".join(lines)
        + "\n\nTo dismiss: acknowledge via the dashboard or POST /checker/findings/{id}/acknowledge"
    )

    return Response(
        command_type        = "checker_findings",
        ok                  = True,
        summary             = summary,
        metrics             = {"open_findings": len(findings)},
        human_review_needed = any(f.get("severity") == "warning" for f in findings),
        human_review_reason = f"{len(findings)} open finding(s) require attention.",
        raw                 = {"findings": findings},
    )


def handle_warden_status(command: Command) -> Response:
    """
    Show Cost Warden routing policy and recent LM usage summary.
    Reads from disk files only (transport isolation: no app/ imports).
      data/warden_policy.json  — written by app/cost_warden.cache_policy() on startup
      data/warden_usage.jsonl  — appended by LMHelper on each call
    """
    policy_file = _ROOT / "data" / "warden_policy.json"
    usage_file  = _ROOT / "data" / "warden_usage.jsonl"

    # Load policy snapshot
    policy: dict = {}
    if policy_file.exists():
        try:
            policy = json.loads(policy_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Load usage summary from JSONL
    records: list[dict] = []
    if usage_file.exists():
        try:
            for line in reversed(usage_file.read_text(encoding="utf-8").splitlines()):
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
                    if len(records) >= 20:
                        break
        except Exception:
            pass

    total_cost = sum(r.get("cost_usd", 0.0) for r in records)
    tiers:     dict[str, int] = {}
    escalated  = 0
    for r in records:
        t = r.get("tier", "cheap")
        tiers[t] = tiers.get(t, 0) + 1
        if r.get("escalated"):
            escalated += 1
    lm_calls  = tiers.get("cheap", 0) + tiers.get("strong", 0)
    esc_rate  = (escalated / lm_calls * 100.0) if lm_calls > 0 else 0.0
    total_calls = len(records)

    cheap_model  = policy.get("cheap_model",  "openai/gpt-4o-mini")
    strong_model = policy.get("strong_model", "anthropic/claude-sonnet-4-6")
    cheap_tasks  = policy.get("cheap_tasks",  [])
    strong_tasks = policy.get("strong_tasks", [])
    det_tasks    = policy.get("deterministic_tasks", [])

    if total_calls > 0:
        oneliner = (
            f"Cheap default: {cheap_model} ({tiers.get('cheap',0)} call(s)). "
            f"Strong escalation: {strong_model} ({tiers.get('strong',0)} call(s), "
            f"{esc_rate:.0f}% escalation rate). Total cost: ${total_cost:.4f}."
        )
    else:
        oneliner = (
            f"Cheap default: {cheap_model}. "
            f"Strong escalation: {strong_model}. "
            f"No LM calls recorded via Cost Warden yet."
        )

    lines: list[str] = [
        "Cost Warden — LM routing policy:",
        oneliner,
        "",
        f"Cheap model ({cheap_model}): {policy.get('cheap_cost_per_1m', '?')}",
        f"  Tasks: {', '.join(cheap_tasks[:6]) or 'none'}",
        f"Strong model ({strong_model}): {policy.get('strong_cost_per_1m', '?')}",
        f"  Tasks: {', '.join(strong_tasks[:4]) or 'none'}",
        f"Deterministic (no LM): {', '.join(det_tasks[:4]) or 'none'}",
    ]

    if total_calls > 0:
        lines += [
            "",
            f"Recent usage ({total_calls} call(s) via LMHelper): "
            f"cheap={tiers.get('cheap',0)}, strong={tiers.get('strong',0)}, "
            f"escalation={esc_rate:.0f}%, total cost=${total_cost:.4f}",
        ]
    else:
        lines += ["", "No LM calls recorded via LMHelper yet."]

    if not policy:
        lines += ["", "(Policy snapshot not yet written — restart the backend to populate.)"]

    return Response(
        command_type = "warden_status",
        ok           = True,
        summary      = "\n".join(lines),
        metrics      = {
            "cheap_model":         cheap_model,
            "strong_model":        strong_model,
            "total_lm_calls":      total_calls,
            "total_cost_usd":      total_cost,
            "escalation_rate_pct": esc_rate,
        },
        raw          = {"policy": policy, "usage_records": records[:5]},
    )


def handle_sentinel_status(command: Command) -> Response:
    """
    Show the last Test Sentinel patch-safety verdict.
    Reads data/sentinel_report.json — written by the /sentinel/run API endpoint.
    """
    report_file = _ROOT / "data" / "sentinel_report.json"
    if not report_file.exists():
        return Response(
            command_type = "sentinel_status",
            ok           = True,
            summary      = (
                "No Test Sentinel check has been run yet. "
                "Trigger one via the dashboard (Controls tab) or POST /sentinel/run."
            ),
            metrics      = {"verdict": "unknown"},
            raw          = {},
        )

    try:
        data = json.loads(report_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return error_response("sentinel_status", f"Failed to read sentinel report: {exc}")

    verdict    = data.get("verdict", "unknown")
    summary    = data.get("summary", "No summary available.")
    ts         = data.get("timestamp", "")[:19].replace("T", " ")
    scope      = data.get("scope", "?")
    passed     = data.get("passed", 0)
    failed     = data.get("failed", 0)
    errors     = data.get("errors", 0)
    failures   = data.get("failures", [])
    tests_run  = data.get("tests_run", [])

    lines: list[str] = [
        f"Test Sentinel ({ts} UTC) — {verdict.upper()}:",
        summary,
    ]

    if failures:
        lines.append(f"\nFailures ({len(failures)}):")
        for f in failures[:5]:
            lines.append(f"  • [{f.get('kind', '?')}] {f.get('test_id', '?')}")
            if f.get("excerpt"):
                for el in f["excerpt"].splitlines()[:3]:
                    lines.append(f"    {el}")

    verdict_label = {
        "safe":      "Looks safe enough for review.",
        "review":    "Needs stronger review before merging.",
        "not_ready": "Not ready — fix failing tests before review.",
        "unknown":   "Run a check to see results.",
    }.get(verdict, "")

    if verdict_label:
        lines.append(f"\n→ {verdict_label}")

    return Response(
        command_type        = "sentinel_status",
        ok                  = True,
        summary             = "\n".join(lines),
        metrics             = {
            "verdict":    verdict,
            "scope":      scope,
            "passed":     passed,
            "failed":     failed,
            "errors":     errors,
            "tests_run":  len(tests_run),
            "checked_at": ts,
        },
        human_review_needed = verdict in ("review", "not_ready"),
        human_review_reason = summary if verdict in ("review", "not_ready") else "",
        raw                 = data,
    )


def handle_custodian_health(command: Command) -> Response:
    """
    Show the last Custodian runtime health report.
    Reads data/custodian_health.json — written by the /custodian/health API endpoint.
    If no check has been run yet, directs the operator to trigger one.
    """
    health_file = _ROOT / "data" / "custodian_health.json"
    if not health_file.exists():
        return Response(
            command_type = "custodian_health",
            ok           = True,
            summary      = (
                "No Custodian health check has been run yet. "
                "Trigger one via the dashboard (Controls tab) or "
                "GET /custodian/health."
            ),
            metrics      = {"overall": "unknown"},
            raw          = {},
        )

    try:
        data = json.loads(health_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return error_response("custodian_health", f"Failed to read health report: {exc}")

    overall  = data.get("overall", "unknown")
    summary  = data.get("summary", "No summary available.")
    ts       = data.get("timestamp", "")[:19].replace("T", " ")
    items    = data.get("items", [])
    recs     = data.get("recommendations", [])

    lines: list[str] = [f"Custodian report ({ts} UTC) — {overall.upper()}:", summary]

    warn_items = [i for i in items if i.get("severity") == "warning"]
    notice_items = [i for i in items if i.get("severity") == "notice"]

    if warn_items:
        lines.append("\nWarnings:")
        for i in warn_items:
            lines.append(f"  • {i.get('detail', '?')}")
    if notice_items:
        lines.append("\nNotices:")
        for i in notice_items:
            lines.append(f"  • {i.get('detail', '?')}")
    if recs:
        lines.append("\nRecommendations (operator approval required):")
        for r in recs:
            lines.append(f"  → {r}")

    return Response(
        command_type        = "custodian_health",
        ok                  = True,
        summary             = "\n".join(lines),
        metrics             = {
            "overall":      overall,
            "warnings":     len(warn_items),
            "notices":      len(notice_items),
            "checked_at":   ts,
        },
        human_review_needed = overall == "degraded",
        human_review_reason = summary if overall == "degraded" else "",
        raw                 = data,
    )


def handle_help(command: Command) -> Response:
    return Response(
        command_type = "help",
        ok           = True,
        summary      = HELP_TEXT.strip(),
        raw          = {},
    )


def handle_build_intent(command: Command) -> Response:
    """
    Peter intake for Frank Lloyd Stage 1 build requests.

    Applies the HANDOFF_SPEC §1 readiness check before queuing. A request must
    have a non-trivial description AND an explicit, testable success criterion.
    If either is missing Peter asks for clarification (up to 2 rounds) rather
    than queueing an underspecified build.

    When ready:
      - Assigns next BUILD-NNN id from data/frank_lloyd/requests/
      - Writes data/frank_lloyd/requests/{build_id}_request.json
      - Appends request_queued event to data/frank_lloyd/build_log.jsonl
    """
    raw      = command.args.get("raw_request", command.raw_text).strip()
    nl_intake = bool(command.args.get("nl_intake", False))

    # Extract description (strip common intent prefixes if still present)
    lower = raw.lower()
    for prefix in ("frank lloyd:", "frank lloyd,", "build ", "create a new ",
                   "create new ", "create a ", "add a new ", "add a ", "make a "):
        if lower.startswith(prefix):
            raw = raw[len(prefix):].strip()
            lower = raw.lower()
            break

    # Split out explicit success criteria before readiness check
    success_criteria = _fl_extract_success_criteria(raw)
    description = raw
    if success_criteria:
        for marker in _SUCCESS_MARKERS:
            idx = lower.find(marker)
            if idx != -1:
                description = raw[:idx].strip().rstrip(".,;")
                break

    title = _fl_extract_title(description)
    missing = _fl_readiness_check(description, success_criteria)

    if missing:
        return _fl_not_ready_response(missing, nl_mode=nl_intake)

    # Intake gate — reject if Frank is explicitly disabled
    try:
        import frank_lloyd.control as _fl_ctrl
        if not _fl_ctrl.is_enabled():
            ctrl = _fl_ctrl.read_control()
            reason = ctrl.get("disabled_reason") or "Frank disabled by operator"
            return Response(
                command_type = "build_intent",
                ok           = False,
                summary      = (
                    f"Frank Lloyd is currently disabled: {reason}. "
                    "Say \u2018enable frank\u2019 to re-enable build intake."
                ),
                raw          = {"disabled": True, "reason": reason},
            )
    except Exception:
        pass

    # Request is clear enough — assign ID, queue, and auto-start.
    source   = "peter_chat"
    routing  = _fl_build_default_routing()
    build_id = _fl_next_build_id(_FL_REQUESTS)
    req_path = _fl_write_request(_FL_REQUESTS, build_id, title, description, success_criteria, routing)
    _fl_append_log_event(_FL_BUILD_LOG, build_id, title, routing, source=source)

    # Auto-start the full-auto pipeline immediately in a background thread.
    # Operator does not need to say "run BUILD-N" for normal safe work.
    import threading
    import frank_lloyd.auto_runner as _fl_auto_runner
    _t = threading.Thread(
        target=_fl_auto_runner.run_full_auto,
        args=(build_id,),
        kwargs={"initiated_by": "peter_chat"},
        daemon=True,
    )
    _t.start()

    tier         = routing.get("cost_tier", "cheap")
    routing_line = f"Builder: Frank Lloyd ({tier} lane)"

    if nl_intake:
        summary  = (
            f"Got it \u2014 {build_id}: \u201c{title}\u201d. "
            f"{routing_line}. "
            f"Frank Lloyd is building now \u2014 I\u2019ll update you when it\u2019s done."
        )
        next_act = "Watch the Frank Lloyd panel or check back for the result."
    else:
        summary  = (
            f"{build_id}: \u201c{title}\u201d. "
            f"{routing_line}. "
            f"Frank Lloyd is on it."
        )
        next_act = "Frank is building \u2014 check the Frank Lloyd panel for progress."

    return Response(
        command_type        = "build_intent",
        ok                  = True,
        summary             = summary,
        metrics             = {
            "build_id":         build_id,
            "title":            title,
            "success_criteria": success_criteria,
        },
        artifacts           = {"request_file": str(req_path)},
        next_action         = next_act,
        human_review_needed = False,
        raw                 = {
            "build_id":         build_id,
            "title":            title,
            "description":      description,
            "success_criteria": success_criteria,
            "auto_started":     True,
        },
    )


def handle_fl_bulk_abandon(command: Command) -> Response:
    """
    Bulk-abandon all non-terminal Frank Lloyd builds by source channel.

    Typical usage: "abandon frank queue" → abandons all peter_chat_smart builds.
    For explicit source: "abandon frank queue <source>".
    """
    source = (command.args.get("source") or "").strip()
    if not source:
        return Response(
            command_type = "fl_bulk_abandon",
            ok           = False,
            summary      = (
                "No source specified. "
                "Try \u2018abandon frank queue\u2019 to clear peter_chat_smart builds."
            ),
            raw          = {},
        )

    import frank_lloyd.abandoner as _abandoner
    result    = _abandoner.abandon_by_source(source, notes="Bulk-abandoned by operator")
    abandoned = result.get("abandoned", [])
    skipped   = result.get("skipped", [])
    errors    = result.get("errors", [])

    if abandoned:
        summary = (
            f"Abandoned {len(abandoned)} build(s) from \u2018{source}\u2019: "
            + ", ".join(abandoned) + "."
        )
        if skipped:
            summary += f" Skipped {len(skipped)} already-terminal."
    elif skipped:
        summary = (
            f"All {len(skipped)} build(s) from \u2018{source}\u2019 are already terminal "
            "\u2014 nothing abandoned."
        )
    else:
        summary = f"No builds found with source \u2018{source}\u2019."

    return Response(
        command_type = "fl_bulk_abandon",
        ok           = True,
        summary      = summary,
        metrics      = {"source": source, "abandoned_count": len(abandoned), "skipped_count": len(skipped)},
        raw          = {"source": source, "abandoned": abandoned, "skipped": skipped, "errors": errors},
    )


def handle_fl_hard_stop(command: Command) -> Response:
    """
    Stop the currently active Frank Lloyd pipeline.

    Sets the auto_runner stop flag. The pipeline checks this between steps
    and exits cleanly. Does not cancel queued builds — use fl_clear_all for that.
    """
    import frank_lloyd.auto_runner as _ar
    state = _ar.request_stop()
    active = state.get("active_build_id")
    if active:
        summary = (
            f"Frank stopped. Active job {active} will halt after its current step. "
            "Queued builds are still present \u2014 say \u2018clear frank\u2019 to purge them."
        )
    else:
        summary = (
            "Frank has no active pipeline running. "
            "Stop flag set \u2014 it will be honoured if a build starts before being cleared."
        )
    return Response(
        command_type = "fl_hard_stop",
        ok           = True,
        summary      = summary,
        metrics      = {"active_build_id": active, "stop_requested": True},
        raw          = state,
    )


def handle_fl_clear_all(command: Command) -> Response:
    """
    Stop the active Frank Lloyd pipeline AND purge all non-terminal builds.

    Steps (always in this order):
      1. Set auto_runner stop flag — active pipeline halts after current step
      2. abandon_all() — all non-terminal queued builds archived as 'abandoned'

    After this, Frank is idle with an empty queue. Nothing respawns on refresh.
    """
    import frank_lloyd.auto_runner as _ar
    import frank_lloyd.abandoner as _ab

    # 1. Stop active pipeline
    stop_state = _ar.request_stop()
    active     = stop_state.get("active_build_id")

    # 2. Purge all non-terminal builds
    result   = _ab.abandon_all(notes="Cleared by operator — stop and purge all")
    abandoned = result.get("abandoned", [])
    skipped   = result.get("skipped",   [])
    errors    = result.get("errors",    [])

    parts: list[str] = []
    if active:
        parts.append(f"active job {active} halted")
    if abandoned:
        parts.append(f"{len(abandoned)} queued job(s) archived: {', '.join(abandoned)}")
    if skipped:
        parts.append(f"{len(skipped)} already-terminal skipped")
    if errors:
        parts.append(f"{len(errors)} error(s)")

    if not active and not abandoned:
        summary = "Frank queue is already empty. Nothing to clear."
    else:
        summary = "Frank stopped and cleared. " + ". ".join(parts) + "."

    return Response(
        command_type = "fl_clear_all",
        ok           = True,
        summary      = summary,
        metrics      = {
            "active_stopped":   active,
            "abandoned_count":  len(abandoned),
            "skipped_count":    len(skipped),
        },
        raw          = {
            "active_build_id": active,
            "abandoned":       abandoned,
            "skipped":         skipped,
            "errors":          errors,
        },
    )


def handle_fl_disable(command: Command) -> Response:
    """
    Disable Frank Lloyd intake — no new builds accepted until re-enabled.

    Does not stop an in-progress pipeline. Combine with 'stop frank' or
    'clear frank' for a complete shutdown.
    """
    import frank_lloyd.control as _ctrl
    reason = (command.args.get("reason") or "Disabled by operator via Peter").strip()
    result = _ctrl.disable(reason)
    if not result.get("ok"):
        return Response(
            command_type = "fl_disable",
            ok           = False,
            summary      = f"Failed to disable Frank: {result.get('error')}",
            raw          = result,
        )
    return Response(
        command_type = "fl_disable",
        ok           = True,
        summary      = (
            "Frank disabled. No new build intake will run until explicitly re-enabled. "
            "Say \u2018enable frank\u2019 to restore intake."
        ),
        metrics      = {"enabled": False, "disabled_at": result.get("disabled_at")},
        raw          = result,
    )


def handle_fl_enable(command: Command) -> Response:
    """Re-enable Frank Lloyd build intake."""
    import frank_lloyd.control as _ctrl
    result = _ctrl.enable()
    if not result.get("ok"):
        return Response(
            command_type = "fl_enable",
            ok           = False,
            summary      = f"Failed to enable Frank: {result.get('error')}",
            raw          = result,
        )
    return Response(
        command_type = "fl_enable",
        ok           = True,
        summary      = "Frank enabled. Build intake is active.",
        metrics      = {"enabled": True, "enabled_at": result.get("enabled_at")},
        raw          = result,
    )


# ── Frank Lloyd intake helpers ─────────────────────────────────────────────────

def _fl_extract_success_criteria(text: str) -> str:
    """Return the text following the first recognised success-criterion marker, or ''."""
    lower = text.lower()
    for marker in _SUCCESS_MARKERS:
        idx = lower.find(marker)
        if idx != -1:
            return text[idx + len(marker):].strip()
    return ""


def _fl_extract_title(description: str) -> str:
    """Derive a short title (≤ 6 meaningful words) from the description."""
    skip = {"a", "an", "the", "new", "that", "which", "with", "and", "for"}
    words = description.split()
    meaningful = [w for w in words[:12] if w.lower().rstrip(".,") not in skip]
    title = " ".join(meaningful[:6]).rstrip(".,;")
    return title or description[:40]


def _fl_readiness_check(description: str, success_criteria: str) -> list[str]:
    """
    Return a list of readiness failures (empty = ready to queue).

    Checks applied (HANDOFF_SPEC §1):
      description_too_vague  — fewer than 5 words, or pure-vague with no specifics
      missing_success_criteria — no success marker found in the original text
      success_criteria_too_vague — success text is under 4 words
    """
    missing: list[str] = []

    words = description.split()
    if len(words) < 5:
        missing.append("description_too_vague")
    else:
        lower_desc = description.lower()
        if any(term in lower_desc for term in _VAGUE_TERMS) and len(words) < 12:
            missing.append("description_too_vague")

    if not success_criteria:
        missing.append("missing_success_criteria")
    elif len(success_criteria.split()) < 4:
        missing.append("success_criteria_too_vague")

    return missing


def _fl_not_ready_response(missing: list[str], nl_mode: bool = False) -> Response:
    """Build a clarification Response when the readiness check fails."""
    questions: list[str] = []
    if "description_too_vague" in missing:
        if nl_mode:
            questions.append(
                "What exactly should Frank Lloyd build? "
                "A sentence or two about files, endpoints, or specific behaviours would help."
            )
        else:
            questions.append(
                "What exactly should be built? Be specific about files, endpoints, or behaviours."
            )
    if "missing_success_criteria" in missing:
        if nl_mode:
            questions.append(
                "How would you know it\u2019s done? "
                "A quick test or check works great \u2014 e.g. \u201csuccess: the new endpoint returns 200\u201d."
            )
        else:
            questions.append(
                'What does "done" look like? Add a testable criterion, '
                'e.g.: "success: curl /frank-lloyd/count returns {count: N}".'
            )
    if "success_criteria_too_vague" in missing:
        if nl_mode:
            questions.append(
                "Could you make the success check a bit more specific? "
                "What exact command or result would confirm it\u2019s working?"
            )
        else:
            questions.append(
                "The success criterion is too short. What exact command or test would verify this works?"
            )
    joined = " ".join(questions)
    if nl_mode:
        summary     = f"Happy to queue that for Frank Lloyd \u2014 just need a bit more detail. {joined}"
        next_action = "Once you fill in the missing piece, just say it again and I\u2019ll get it queued."
    else:
        summary     = f"Not clear enough for Frank Lloyd yet. {joined}"
        next_action = "Provide the missing details and try again."
    return Response(
        command_type = "build_intent",
        ok           = False,
        summary      = summary,
        next_action  = next_action,
        raw          = {"missing_fields": missing, "questions": questions},
    )


def _fl_next_build_id(requests_dir: pathlib.Path) -> str:
    """Return the next zero-padded build ID (BUILD-001, BUILD-002, …)."""
    existing: list[int] = []
    if requests_dir.exists():
        for f in requests_dir.iterdir():
            stem = f.stem  # e.g. "BUILD-001_request"
            if stem.upper().startswith("BUILD-"):
                try:
                    n = int(stem.split("-", 1)[1].split("_", 1)[0])
                    existing.append(n)
                except (IndexError, ValueError):
                    pass
    return f"BUILD-{max(existing, default=0) + 1:03d}"


def _fl_build_default_routing() -> dict:
    """Default Frank-first routing block for Peter-queued builds."""
    import os as _os
    from datetime import datetime as _dt, timezone as _tz
    cheap_model = _os.environ.get("CHEAP_MODEL", "openai/gpt-4o-mini")
    return {
        "builder_lane":         "frank",
        "model_provider":       "openrouter",
        "model_used":           cheap_model,
        "cost_tier":            "cheap",
        "escalation_reason":    None,
        "absorption_candidate": False,
        "absorption_notes":     "",
        "routing_decided_at":   _dt.now(_tz.utc).isoformat(),
        "routing_decided_by":   "default",
    }


def _fl_write_request(
    requests_dir: pathlib.Path,
    build_id: str,
    title: str,
    description: str,
    success_criteria: str,
    routing: Optional[dict] = None,
) -> pathlib.Path:
    """Write the request JSON file and return the path."""
    requests_dir.mkdir(parents=True, exist_ok=True)
    req_path = requests_dir / f"{build_id}_request.json"
    payload = {
        "request_id":       build_id,
        "title":            title,
        "description":      description,
        "requester":        "operator",
        "requested_at":     datetime.now(timezone.utc).isoformat(),
        "success_criteria": success_criteria,
        "build_type_hint":  "",
        "context_refs":     [],
        "constraints":      [],
        "execution_policy": "auto_apply",
        "routing":          routing or _fl_build_default_routing(),
    }
    req_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return req_path


def _fl_append_log_event(
    build_log: pathlib.Path,
    build_id: str,
    title: str,
    routing: Optional[dict] = None,
    source: str = "peter_chat",
) -> None:
    """Append a request_queued event to data/frank_lloyd/build_log.jsonl."""
    build_log.parent.mkdir(parents=True, exist_ok=True)
    extra: dict = {"title": title, "build_type_hint": "", "source": source}
    if routing:
        extra["routing"] = routing
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "build_id":  build_id,
        "event":     "request_queued",
        "notes":     f"Request queued by Peter: {title}",
        "extra":     extra,
    }
    with build_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def handle_approve_build(command: Command) -> Response:
    """
    Stage 1 terminal gate — approve a pending_review build spec.

    Calls frank_lloyd.spec_approver.approve_build(). Validates state,
    copies staging artifacts to archive, writes decision.json + manifest.json,
    appends spec_approved log event.
    """
    import frank_lloyd.spec_approver as _fl_approver

    build_id = command.args.get("build_id", "").strip().upper()
    notes    = command.args.get("notes", "")

    if not build_id:
        return Response(
            command_type = "approve_build",
            ok           = False,
            summary      = "No build ID provided. Usage: approve BUILD-N [notes]",
            next_action  = "approve BUILD-001",
            raw          = {},
        )

    result = _fl_approver.approve_build(build_id, notes=notes)

    if not result["ok"]:
        return Response(
            command_type = "approve_build",
            ok           = False,
            summary      = result["error"],
            next_action  = f"Check build status: GET /frank-lloyd/status",
            raw          = result,
        )

    return Response(
        command_type        = "approve_build",
        ok                  = True,
        summary             = (
            f"{build_id} spec approved. "
            f"Archive: {result['archive_path']}. "
            f"Stage 1 complete. Stage 2 not yet authorized."
        ),
        metrics             = {"build_id": build_id, "stage": 1},
        artifacts           = {"archive_path": result["archive_path"]},
        next_action         = (
            f"Stage 2 authorization is a separate step. "
            f"Review decision: {result['archive_path']}/decision.json"
        ),
        human_review_needed = False,
        raw                 = result,
    )


def handle_reject_build(command: Command) -> Response:
    """
    Stage 1 terminal gate — reject a pending_review build spec.

    Calls frank_lloyd.spec_approver.reject_build(). Requires a non-empty reason.
    Archives Stage 1 artifacts, writes rejection decision.json + manifest.json,
    appends spec_rejected log event.
    """
    import frank_lloyd.spec_approver as _fl_approver

    build_id = command.args.get("build_id", "").strip().upper()
    reason   = command.args.get("reason", "").strip()

    if not build_id:
        return Response(
            command_type = "reject_build",
            ok           = False,
            summary      = "No build ID provided. Usage: reject BUILD-N <reason>",
            next_action  = "reject BUILD-001 reason text here",
            raw          = {},
        )

    if not reason:
        return Response(
            command_type = "reject_build",
            ok           = False,
            summary      = (
                f"A reason is required to reject {build_id}. "
                f"Usage: reject {build_id} <reason>"
            ),
            next_action  = f"reject {build_id} <reason>",
            raw          = {"build_id": build_id},
        )

    result = _fl_approver.reject_build(build_id, reason=reason)

    if not result["ok"]:
        return Response(
            command_type = "reject_build",
            ok           = False,
            summary      = result["error"],
            next_action  = f"Check build status: GET /frank-lloyd/status",
            raw          = result,
        )

    return Response(
        command_type        = "reject_build",
        ok                  = True,
        summary             = (
            f"{build_id} spec rejected. Reason: {reason}. "
            f"Archive: {result['archive_path']}."
        ),
        metrics             = {"build_id": build_id, "stage": 1, "reason": reason},
        artifacts           = {"archive_path": result["archive_path"]},
        next_action         = (
            f"Submit a revised build request or abandon {build_id}. "
            f"Review rejection: {result['archive_path']}/decision.json"
        ),
        human_review_needed = False,
        raw                 = result,
    )


def handle_authorize_stage2(command: Command) -> Response:
    """
    Stage 2 authorization gate — authorize a spec_approved build for Stage 2.

    Calls frank_lloyd.stage2_authorizer.authorize_stage2(). Validates state,
    writes stage2_authorization.json to the archive, appends stage2_authorized
    log event. Does NOT generate code or initiate any LM call.
    """
    import frank_lloyd.stage2_authorizer as _fl_s2auth

    build_id = command.args.get("build_id", "").strip().upper()
    notes    = command.args.get("notes", "")

    if not build_id:
        return Response(
            command_type = "authorize_stage2",
            ok           = False,
            summary      = "No build ID provided. Usage: authorize BUILD-N stage2 [notes]",
            next_action  = "authorize BUILD-001 stage2",
            raw          = {},
        )

    result = _fl_s2auth.authorize_stage2(build_id, notes=notes)

    if not result["ok"]:
        return Response(
            command_type = "authorize_stage2",
            ok           = False,
            summary      = result["error"],
            next_action  = f"Check build status: GET /frank-lloyd/status",
            raw          = result,
        )

    readiness = result.get("raw", {})
    try:
        import json as _json
        import pathlib as _pathlib
        _auth_text = _pathlib.Path(result["authorization_path"]).read_text(encoding="utf-8")
        _auth_data = _json.loads(_auth_text)
        readiness  = _auth_data.get("provider_readiness", {})
    except Exception:
        pass

    executable = readiness.get("executable_lanes", [])
    external   = readiness.get("external_supervised_lanes", [])
    lane_note  = (
        f"Executable lanes: {', '.join(executable) or 'none'}. "
        f"External-supervised lanes: {', '.join(external) or 'none'}."
    )

    return Response(
        command_type        = "authorize_stage2",
        ok                  = True,
        summary             = (
            f"{build_id} Stage 2 authorized. "
            f"Authorization: {result['authorization_path']}. "
            f"{lane_note}"
        ),
        metrics             = {"build_id": build_id, "stage": 2},
        artifacts           = {
            "archive_path":       result["archive_path"],
            "authorization_path": result["authorization_path"],
        },
        next_action         = (
            f"Stage 2 draft generation is now authorized for {build_id}. "
            f"Note: code generation is not yet implemented — this is authorization only."
        ),
        human_review_needed = False,
        raw                 = result,
    )


def handle_draft_stage2(command: Command) -> Response:
    """
    Stage 2 first draft generation — generate draft artifacts for a stage2_authorized build.

    Calls frank_lloyd.stage2_drafter.generate_stage2_draft(). Uses the cheapest
    executable provider lane (CODE_DRAFT_LOW → cheap OpenRouter). Refuses non-executable
    lanes with a clear draft_blocked event. Writes to staging only — no live repo writes,
    no auto-promotion.
    """
    import frank_lloyd.stage2_drafter as _fl_drafter

    build_id = command.args.get("build_id", "").strip().upper()
    notes    = command.args.get("notes", "")

    if not build_id:
        return Response(
            command_type = "draft_stage2",
            ok           = False,
            summary      = "No build ID provided. Usage: draft BUILD-N [notes]",
            next_action  = "draft BUILD-001",
            raw          = {},
        )

    result = _fl_drafter.generate_stage2_draft(build_id, notes=notes)

    if not result["ok"]:
        return Response(
            command_type = "draft_stage2",
            ok           = False,
            summary      = result["error"],
            next_action  = "Check build status: GET /frank-lloyd/status",
            raw          = result,
        )

    routing        = result.get("routing") or {}
    files          = result.get("files_generated") or []
    staging_path   = result.get("staging_path", "")
    manifest_path  = result.get("manifest_path", "")
    task_class     = routing.get("task_class", "?")
    tier           = routing.get("provider_tier", "?")
    model          = routing.get("model", "?")

    return Response(
        command_type        = "draft_stage2",
        ok                  = True,
        summary             = (
            f"{build_id} Stage 2 first draft generated. "
            f"Lane: {task_class} / {tier} ({model}). "
            f"{len(files)} file(s) written to staging."
        ),
        metrics             = {
            "build_id":      build_id,
            "stage":         2,
            "task_class":    task_class,
            "provider_tier": tier,
            "model":         model,
            "files_count":   len(files),
        },
        artifacts           = {
            "staging_path":  staging_path,
            "manifest_path": manifest_path,
            "files":         files,
        },
        next_action         = (
            f"Review the staged draft artifacts at {staging_path}. "
            f"This is a staged draft only — not written to the live repo. "
            f"Promotion is a separate manual step."
        ),
        human_review_needed = True,
        raw                 = result,
    )


def handle_promote_draft(command: Command) -> Response:
    """
    Stage 2 draft promotion — copies staged draft_module.py to the live repo.

    First-pass: CODE_DRAFT_LOW only. New .py files only. target_path required.
    Calls frank_lloyd.stage2_promoter.promote_draft(). Validates state, manifest
    task class, target path safety, and that the destination does not exist.
    Marks human_review_needed=True — operator should inspect and test the file.
    """
    import frank_lloyd.stage2_promoter as _fl_promoter

    build_id    = command.args.get("build_id", "").strip().upper()
    target_path = command.args.get("target_path", "").strip()
    notes       = command.args.get("notes", "")

    if not build_id:
        return Response(
            command_type = "promote_draft",
            ok           = False,
            summary      = "No build ID provided. Usage: promote BUILD-N path/to/file.py",
            next_action  = "promote BUILD-001 frank_lloyd/my_module.py",
            raw          = {},
        )

    if not target_path:
        return Response(
            command_type = "promote_draft",
            ok           = False,
            summary      = (
                f"No target path provided for {build_id}. "
                "Usage: promote BUILD-N path/to/file.py"
            ),
            next_action  = f"promote {build_id} frank_lloyd/my_module.py",
            raw          = {},
        )

    result = _fl_promoter.promote_draft(build_id, target_path=target_path, notes=notes)

    if not result["ok"]:
        return Response(
            command_type = "promote_draft",
            ok           = False,
            summary      = result["error"],
            next_action  = "Check build status: GET /frank-lloyd/status",
            raw          = result,
        )

    return Response(
        command_type        = "promote_draft",
        ok                  = True,
        summary             = (
            f"{build_id} draft promoted to live repo: {result['target_path']}. "
            "Inspect the file and run tests before importing."
        ),
        metrics             = {
            "build_id":     build_id,
            "stage":        2,
            "target_path":  result["target_path"],
            "promoted_at":  result["promoted_at"],
        },
        artifacts           = {
            "target_path":  result["target_path"],
            "archive_path": result["archive_path"],
        },
        next_action         = (
            f"Inspect {result['target_path']} and run tests. "
            "Staging artifacts preserved at staging/frank_lloyd/{build_id}/stage2/"
        ),
        human_review_needed = True,
        raw                 = result,
    )


def handle_fl_lifecycle_nl(command: Command) -> Response:
    """
    Conversational Frank Lloyd lifecycle handler.

    Handles natural-language requests for all existing FL lifecycle actions
    without requiring the operator to use a structured command. Resolves
    "the current one" / "that one" from live build log state. Asks a brief
    clarification when required info is missing (e.g. reject reason, promote path).

    Supported actions (args["action"]):
      status_query   — plain-English summary of what Frank Lloyd is doing
      run            — run the safe-lane pipeline for a queued build (auto-advance)
      approve        — approve the pending_review build
      reject         — reject the pending_review build (requires reason)
      authorize_stage2 — authorize the spec_approved build for Stage 2
      draft          — generate a Stage 2 draft for the stage2_authorized build
      promote        — promote the draft_generated build (requires target_path)
      discard        — discard the draft_generated/draft_blocked build

    Calls the same internal frank_lloyd.* module functions as the structured
    handlers. Does NOT create a second workflow path.
    """
    action      = command.args.get("action", "")
    build_id    = command.args.get("build_id", "").strip().upper()
    notes       = command.args.get("notes", "").strip()
    reason      = command.args.get("reason", "").strip()
    target_path = command.args.get("target_path", "").strip()

    # ── Status query ──────────────────────────────────────────────────────────
    if action == "status_query":
        return _fl_nl_status_response()

    # ── Resolve build_id if not given ─────────────────────────────────────────
    if not build_id:
        build_id = _fl_resolve_actionable_build(action) or ""
    if not build_id:
        return _fl_nl_nothing_to_do(action)

    # ── Per-action dispatch — same internal functions as structured handlers ──

    if action == "run":
        import frank_lloyd.auto_runner as _fl_auto
        result = _fl_auto.run_full_auto(build_id, initiated_by="peter_nl")
        if result["ok"]:
            promoted_to = result.get("promoted_to", "")
            return Response(
                command_type = "fl_lifecycle_nl",
                ok           = True,
                summary      = (
                    f"Frank Lloyd built {build_id} \u2014 "
                    f"code written to {promoted_to}."
                    if promoted_to else
                    f"Frank Lloyd ran the pipeline for {build_id} \u2014 done."
                ),
                next_action  = f"Review {promoted_to} in the repo." if promoted_to else "Check the build log.",
                raw          = result,
            )
        if result.get("paused_reason"):
            return Response(
                command_type = "fl_lifecycle_nl",
                ok           = False,
                summary      = f"{build_id} paused: {result['paused_reason']}",
                next_action  = "Review the Frank Lloyd panel and take the next manual step.",
                raw          = result,
            )
        return Response(
            command_type = "fl_lifecycle_nl",
            ok           = False,
            summary      = result.get("error") or f"Auto-run for {build_id} failed.",
            next_action  = "Check the build log or review status.",
            raw          = result,
        )

    if action == "approve":
        import frank_lloyd.spec_approver as _fl_approver
        result = _fl_approver.approve_build(build_id, notes=notes)
        if not result["ok"]:
            return Response(
                command_type = "fl_lifecycle_nl",
                ok           = False,
                summary      = result["error"],
                next_action  = f"Check the build status: 'status'",
                raw          = result,
            )
        return Response(
            command_type = "fl_lifecycle_nl",
            ok           = True,
            summary      = f"Done \u2014 {build_id} spec approved. Stage 2 authorization is the next step when you\u2019re ready.",
            next_action  = f"Authorize Stage 2 when ready: 'authorize {build_id} stage2'",
            raw          = result,
        )

    if action == "reject":
        if not reason:
            return Response(
                command_type = "fl_lifecycle_nl",
                ok           = False,
                summary      = f"What\u2019s the reason for rejecting {build_id}? I\u2019ll need that on record.",
                next_action  = f"reject {build_id} <reason>",
                raw          = {"build_id": build_id, "missing": "reason"},
            )
        import frank_lloyd.spec_approver as _fl_approver
        result = _fl_approver.reject_build(build_id, reason=reason)
        if not result["ok"]:
            return Response(
                command_type = "fl_lifecycle_nl",
                ok           = False,
                summary      = result["error"],
                next_action  = f"Check the build status: 'status'",
                raw          = result,
            )
        return Response(
            command_type = "fl_lifecycle_nl",
            ok           = True,
            summary      = f"{build_id} rejected. Reason on record: \u201c{reason}\u201d.",
            next_action  = "Submit a revised build request or queue a new one.",
            raw          = result,
        )

    if action == "authorize_stage2":
        import frank_lloyd.stage2_authorizer as _fl_s2auth
        result = _fl_s2auth.authorize_stage2(build_id, notes=notes)
        if not result["ok"]:
            return Response(
                command_type = "fl_lifecycle_nl",
                ok           = False,
                summary      = result["error"],
                next_action  = f"Check the build status: 'status'",
                raw          = result,
            )
        return Response(
            command_type = "fl_lifecycle_nl",
            ok           = True,
            summary      = f"{build_id} is now Stage 2 authorized. Frank Lloyd can generate a draft whenever you\u2019re ready.",
            next_action  = f"Trigger draft generation: 'draft {build_id}'",
            raw          = result,
        )

    if action == "draft":
        import frank_lloyd.stage2_drafter as _fl_drafter
        result = _fl_drafter.generate_stage2_draft(build_id, notes=notes)
        if not result["ok"]:
            return Response(
                command_type = "fl_lifecycle_nl",
                ok           = False,
                summary      = result["error"],
                next_action  = f"Check the build status: 'status'",
                raw          = result,
            )
        status = result.get("status", "")
        if status == "draft_generated":
            return Response(
                command_type = "fl_lifecycle_nl",
                ok           = True,
                summary      = f"Draft ready for {build_id}. Review it in the Frank Lloyd panel before promoting.",
                next_action  = f"Review then promote: 'promote {build_id} path/to/file.py'",
                raw          = result,
            )
        return Response(
            command_type = "fl_lifecycle_nl",
            ok           = False,
            summary      = f"Draft generation for {build_id} did not complete as expected. Status: {status}.",
            next_action  = f"Check staging/frank_lloyd/{build_id}/stage2/ for details.",
            raw          = result,
        )

    if action == "promote":
        if not target_path:
            return Response(
                command_type = "fl_lifecycle_nl",
                ok           = False,
                summary      = f"Where should the {build_id} draft go? Give me a relative .py path, like \u2018frank_lloyd/my_module.py\u2019.",
                next_action  = f"promote {build_id} frank_lloyd/my_module.py",
                raw          = {"build_id": build_id, "missing": "target_path"},
            )
        import frank_lloyd.stage2_promoter as _fl_promoter
        result = _fl_promoter.promote_draft(build_id, target_path=target_path, notes=notes)
        if not result["ok"]:
            return Response(
                command_type = "fl_lifecycle_nl",
                ok           = False,
                summary      = result["error"],
                next_action  = f"Check the build status: 'status'",
                raw          = result,
            )
        return Response(
            command_type        = "fl_lifecycle_nl",
            ok                  = True,
            summary             = f"{build_id} promoted to {result['target_path']}. Inspect the file and run tests before importing.",
            next_action         = f"Inspect {result['target_path']} and run tests.",
            human_review_needed = True,
            raw                 = result,
        )

    if action == "discard":
        import frank_lloyd.stage2_discarder as _fl_discarder
        result = _fl_discarder.discard_draft(build_id, notes=notes)
        if not result["ok"]:
            return Response(
                command_type = "fl_lifecycle_nl",
                ok           = False,
                summary      = result["error"],
                next_action  = f"Check the build status: 'status'",
                raw          = result,
            )
        return Response(
            command_type = "fl_lifecycle_nl",
            ok           = True,
            summary      = f"Draft for {build_id} discarded. It\u2019s back to stage2_authorized \u2014 ready for a new draft attempt.",
            next_action  = f"Trigger a new draft: 'draft {build_id}'",
            raw          = result,
        )

    # Unknown action — should not happen in normal flow
    return Response(
        command_type = "fl_lifecycle_nl",
        ok           = False,
        summary      = f"Didn\u2019t recognise the lifecycle action \u2018{action}\u2019. Try \u2018help\u2019 for command reference.",
        next_action  = "help",
        raw          = {"action": action},
    )


# ── FL NL lifecycle helpers ───────────────────────────────────────────────────

def _fl_read_build_log() -> list[dict]:
    """Read data/frank_lloyd/build_log.jsonl and return parsed events."""
    import json as _json
    log_path = _FL_BUILD_LOG
    if not log_path.exists():
        return []
    out: list[dict] = []
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(_json.loads(line))
            except (_json.JSONDecodeError, ValueError):
                pass
    except OSError:
        pass
    return out


def _fl_build_statuses() -> dict[str, str]:
    """Return {build_id: current_status} for all builds in the log."""
    events = _fl_read_build_log()
    # Group events by build_id, preserving order (log is chronological)
    by_build: dict[str, list[dict]] = {}
    for ev in events:
        bid = ev.get("build_id")
        if bid:
            by_build.setdefault(bid, []).append(ev)

    statuses: dict[str, str] = {}
    for bid, evs in by_build.items():
        latest_event: str | None = None
        for ev in sorted(evs, key=lambda e: e.get("timestamp", "")):
            etype = ev.get("event", "")
            if etype in _FL_STATUS_MAP:
                latest_event = etype
        if latest_event:
            statuses[bid] = _FL_STATUS_MAP[latest_event]
    return statuses


def _fl_resolve_actionable_build(action: str) -> str | None:
    """
    Find the most recent build in the correct state for the given action.
    Returns build_id string or None if no actionable build exists.
    """
    target_statuses = _FL_ACTION_TARGET_STATUSES.get(action)
    if not target_statuses:
        return None
    statuses = _fl_build_statuses()
    # Return the last build_id (most recently queued) that is in a target state
    for bid in reversed(list(statuses.keys())):
        if statuses[bid] in target_statuses:
            return bid
    return None


def _fl_nl_nothing_to_do(action: str) -> Response:
    """Return a conversational 'nothing to do' response for the given action."""
    action_phrases = {
        "approve":          "a build spec ready for approval (status: pending_review)",
        "reject":           "a build spec ready for rejection (status: pending_review)",
        "authorize_stage2": "an approved build waiting for Stage 2 authorization (status: spec_approved)",
        "draft":            "a Stage 2 authorized build waiting for a draft (status: stage2_authorized)",
        "promote":          "a draft ready to promote (status: draft_generated)",
        "discard":          "a draft to discard (status: draft_generated or draft_blocked)",
    }
    phrase = action_phrases.get(action, f"an actionable build for \u2018{action}\u2019")
    return Response(
        command_type = "fl_lifecycle_nl",
        ok           = False,
        summary      = f"Nothing to act on right now \u2014 there\u2019s no {phrase}.",
        next_action  = "Check the queue: 'status'",
        raw          = {"action": action, "resolved_build_id": None},
    )


def _fl_nl_status_response() -> Response:
    """Return a plain-English summary of Frank Lloyd\u2019s current state."""
    statuses = _fl_build_statuses()
    if not statuses:
        return Response(
            command_type = "fl_lifecycle_nl",
            ok           = True,
            summary      = "Frank Lloyd has no builds queued yet. Queue one with: \u2018build <description>\u2019.",
            next_action  = "Queue a build request.",
            raw          = {"builds": {}},
        )

    # Describe the most actionable build first, then summarise the rest
    priority_order = [
        ("draft_generated",  "has a draft ready for review or promotion"),
        ("draft_blocked",    "has a blocked draft \u2014 needs a discard and retry"),
        ("draft_generating", "is generating a draft right now"),
        ("stage2_authorized","has a Stage 2 authorized build waiting for a draft"),
        ("spec_approved",    "has an approved spec waiting for Stage 2 authorization"),
        ("pending_review",   "has a spec ready for your review"),
        ("pending_spec",     "is writing a spec"),
    ]

    lines: list[str] = []
    covered: set[str] = set()

    for status, phrase in priority_order:
        builds_in_state = [bid for bid, st in statuses.items() if st == status]
        if builds_in_state:
            bid = builds_in_state[-1]  # most recent
            lines.append(f"\u2022 Frank Lloyd {phrase} \u2014 {bid}.")
            covered.add(bid)

    other_states = {
        "spec_rejected", "abandoned", "draft_promoted",
    }
    for bid, st in statuses.items():
        if bid not in covered and st not in other_states:
            lines.append(f"\u2022 {bid}: {st}")

    summary = "\n".join(lines) if lines else "Frank Lloyd has no active builds right now."
    return Response(
        command_type = "fl_lifecycle_nl",
        ok           = True,
        summary      = summary,
        next_action  = "Ask Peter about a specific action, or check the Frank Lloyd panel.",
        raw          = {"statuses": statuses},
    )


def handle_discard_draft(command: Command) -> Response:
    """
    Stage 2 draft discard — removes staged draft artifacts and resets the build
    to stage2_authorized so a new draft attempt can begin.

    Calls frank_lloyd.stage2_discarder.discard_draft(). Allowed only for
    draft_generated and draft_blocked builds. Preserves Stage 1 artifacts and
    the Stage 2 authorization record.
    """
    import frank_lloyd.stage2_discarder as _fl_discarder

    build_id = command.args.get("build_id", "").strip().upper()
    notes    = command.args.get("notes", "")

    if not build_id:
        return Response(
            command_type = "discard_draft",
            ok           = False,
            summary      = "No build ID provided. Usage: discard BUILD-N [notes]",
            next_action  = "discard BUILD-001",
            raw          = {},
        )

    result = _fl_discarder.discard_draft(build_id, notes=notes)

    if not result["ok"]:
        return Response(
            command_type = "discard_draft",
            ok           = False,
            summary      = result["error"],
            next_action  = "Check build status: GET /frank-lloyd/status",
            raw          = result,
        )

    return Response(
        command_type = "discard_draft",
        ok           = True,
        summary      = (
            f"{build_id} Stage 2 draft discarded. "
            "Build is back to stage2_authorized — ready for a new draft attempt."
        ),
        metrics      = {
            "build_id":     build_id,
            "stage":        2,
            "discarded_at": result["discarded_at"],
        },
        next_action  = (
            f"Generate a new draft: draft {build_id} [notes]"
        ),
        raw          = result,
    )


def handle_unknown(command: Command) -> Response:
    return Response(
        command_type = "unknown",
        ok           = False,
        summary      = f"Unknown command: \"{command.raw_text}\". Try 'help'.",
        next_action  = "python scripts/peter.py help",
        raw          = {"raw_text": command.raw_text},
    )


# ── Batch / session explain helpers ───────────────────────────────────────────

def _explain_batch(report: dict) -> Response:
    w   = report.get("what_ran", {})
    bc  = report.get("best_candidate")
    na  = report.get("next_action", {})
    wm  = report.get("what_mattered", [])
    hr  = report.get("human_review_recommended", False)

    summary_parts = [
        f"Batch {report.get('batch_id')}: "
        f"{w.get('n_accepted', 0)}/{w.get('n_experiments', 0)} accepted "
        f"across {', '.join(w.get('classes_tested', []))}."
    ]
    if wm:
        summary_parts.append(wm[0])
    if bc:
        summary_parts.append(
            f"Best: {bc.get('experiment_id')} "
            f"(score={bc.get('score')}, tier={bc.get('tier')})."
        )

    metrics = {
        "batch_id":  report.get("batch_id"),
        "accepted":  f"{w.get('n_accepted', 0)}/{w.get('n_experiments', 0)}",
        "best_tier": (bc or {}).get("tier", "none"),
        "best_score": (bc or {}).get("score", "—"),
        "next":      na.get("recommendation", "—"),
    }

    return Response(
        command_type        = "explain_result",
        ok                  = True,
        summary             = " ".join(summary_parts),
        metrics             = metrics,
        next_action         = na.get("recommendation", ""),
        human_review_needed = hr,
        human_review_reason = report.get("human_review_reason", ""),
        raw                 = report,
    )


def _explain_session(report: dict) -> Response:
    w   = report.get("what_ran", {})
    bc  = report.get("best_candidate")
    nd  = report.get("next_direction", {})
    df  = report.get("dominant_findings", [])
    hr  = report.get("human_review_recommended", False)

    summary_parts = [
        f"Session {report.get('session_id')}: "
        f"{w.get('total_accepted', 0)}/{w.get('total_experiments', 0)} accepted "
        f"across {w.get('batches_completed', 0)} batches."
    ]
    if df:
        summary_parts.append(df[0])
    summary_parts.append(
        f"Stop: {report.get('stop_condition')} — {report.get('stop_reason', '')}"
    )

    metrics = {
        "session_id": report.get("session_id"),
        "accepted":   f"{w.get('total_accepted', 0)}/{w.get('total_experiments', 0)}",
        "batches":    w.get("batches_completed", 0),
        "best_tier":  (bc or {}).get("tier", "none"),
        "best_score": (bc or {}).get("score", "—"),
        "stop":       report.get("stop_condition", "?"),
        "next":       nd.get("recommendation", "—"),
    }

    return Response(
        command_type        = "explain_result",
        ok                  = True,
        summary             = " ".join(summary_parts),
        metrics             = metrics,
        next_action         = nd.get("recommendation", ""),
        human_review_needed = hr,
        human_review_reason = report.get("human_review_reason", ""),
        raw                 = report,
    )


# ── Artifact readers ──────────────────────────────────────────────────────────
# These are the only functions that touch the filesystem.
# Mock these in tests to avoid depending on real data files.

def _load_latest_campaign_state() -> dict | None:
    """Return the most recently created campaign state, or None."""
    if not _CAMPAIGNS.exists():
        return None
    states = []
    for state_file in _CAMPAIGNS.glob("*/state.json"):
        try:
            data = json.loads(state_file.read_text())
            states.append(data)
        except Exception:
            pass
    if not states:
        return None
    # Sort by created_at descending (ISO timestamps sort lexicographically)
    return sorted(states, key=lambda s: s.get("created_at", ""), reverse=True)[0]


def _load_campaign_state(campaign_id: str) -> dict | None:
    """Return state for a specific campaign, or None."""
    path = _CAMPAIGNS / campaign_id / "state.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _load_latest_interrupted_campaign() -> dict | None:
    """Return the most recent campaign with status 'interrupted' or 'running'."""
    if not _CAMPAIGNS.exists():
        return None
    candidates = []
    for state_file in _CAMPAIGNS.glob("*/state.json"):
        try:
            data = json.loads(state_file.read_text())
            if data.get("status") in ("interrupted", "running"):
                candidates.append(data)
        except Exception:
            pass
    if not candidates:
        return None
    return sorted(candidates, key=lambda s: s.get("created_at", ""), reverse=True)[0]


def _load_latest_batch_report() -> dict | None:
    """Return the most recently modified batch report JSON, or None."""
    if not _REPORTS.exists():
        return None
    # Batch reports: {batch_id}.json (not *_session.json, not *_report.md)
    candidates = [
        p for p in _REPORTS.glob("*.json")
        if "_session" not in p.stem and not p.stem.endswith("_report")
    ]
    if not candidates:
        return None
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        return json.loads(newest.read_text())
    except Exception:
        return None


def _load_batch_report(batch_id: str) -> dict | None:
    """Return the batch report for batch_id, or None."""
    path = _REPORTS / f"{batch_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _load_session_report(session_id: str) -> dict | None:
    """Return the session report for session_id, or None."""
    path = _REPORTS / f"{session_id}_session.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _scan_review_worthy_from_ledger(limit: int = 40) -> list[dict]:
    """
    Scan the last `limit` ledger entries and return accepted experiments
    with score >= _REVIEW_WORTHY_SCORE, sorted by score descending.
    """
    if not _LEDGER.exists():
        return []
    try:
        lines = [l.strip() for l in _LEDGER.read_text().splitlines() if l.strip()]
    except Exception:
        return []

    candidates: list[dict] = []
    for line in reversed(lines[-limit:]):
        try:
            entry = json.loads(line)
        except Exception:
            continue
        for exp in entry.get("experiments", []):
            score = exp.get("score") or 0.0
            if exp.get("decision") == "ACCEPTED" and score >= _REVIEW_WORTHY_SCORE:
                candidates.append(exp)

    return sorted(candidates, key=lambda x: x.get("score") or 0.0, reverse=True)


def _derive_next_action(state: dict) -> str:
    """Synthesize the recommended next action from campaign state."""
    status = state.get("status", "?")
    bc     = state.get("best_candidate")
    art    = state.get("artifacts", {})
    p      = state.get("progress", {})
    cfg    = state.get("config", {})
    stop   = state.get("stop_condition")

    if status == "completed":
        if bc and bc.get("tier") in ("strong", "review_worthy"):
            rec = art.get("best_validation_record", "<path>")
            return f"python scripts/promote_candidate.py --record {rec}"
        if bc:
            return (
                f"python scripts/validate_strategy.py  "
                f"# re-test {bc.get('experiment_id')} with more seeds before promoting"
            )
        return 'python scripts/run_campaign.py --goal "new campaign goal"'

    if status in ("running", "interrupted"):
        sessions_left = (
            cfg.get("max_sessions", 0) - p.get("sessions_completed", 0)
        )
        if sessions_left > 0:
            cid = state.get("campaign_id", "?")
            if status == "interrupted":
                return f"python scripts/run_campaign.py --resume {cid}"
            return "Campaign is running — check back with: python scripts/peter.py status"

    return 'python scripts/run_campaign.py --goal "your goal here"'


# ── Market layer handlers ──────────────────────────────────────────────────────

from observability.market_summary import (
    read_market_status, read_readiness,
    read_last_reconciliation, read_today_order_summary,
    write_kill_signal,
)


def handle_market_status(command: Command) -> Response:
    """
    Market status: reads disk artifacts written by the market layer.
    No live app imports — all data comes from observability bridge.
    """
    try:
        status = read_market_status()
        orders = read_today_order_summary()
        recon  = read_last_reconciliation()

        sess_type    = status.get("session_type", "unknown")
        data_lane    = status.get("data_lane", "UNKNOWN")
        feed_live    = status.get("feed_live", False)
        ext_warn     = status.get("extended_hours_warning", "")
        is_halted_v  = status.get("trading_halted", False)
        broker_avail = status.get("broker_available", False)
        broker_env   = status.get("broker_env", "unknown")
        broker_msg   = status.get("broker_message", "")

        feed_line = f"Feed: {'LIVE' if feed_live else 'SIM'} ({data_lane})."

        summary_parts = [
            f"Market session: {sess_type}.",
            feed_line,
        ]
        if ext_warn:
            summary_parts.append(ext_warn)
        if is_halted_v:
            summary_parts.append("TRADING HALTED: reconciliation failure. Resolve before placing orders.")
        if not broker_avail:
            summary_parts.append("Broker: not configured (paper sim only).")
        else:
            summary_parts.append(f"Broker: {broker_msg} ({broker_env} mode).")

        recon_line = "Reconciliation: never run."
        if recon:
            recon_passed    = recon.get("passed", False)
            recon_mismatches = recon.get("mismatches", 0)
            recon_at        = recon.get("timestamp_utc", "")
            recon_status    = "PASS" if recon_passed else "FAIL"
            recon_line = f"Reconciliation: {recon_status} — {recon_mismatches} mismatch(es) at {recon_at}."
        summary_parts.append(recon_line)

        orders_line = (
            f"Orders today: {orders.get('orders_placed', 0)} placed, "
            f"{orders.get('fills', 0)} filled, "
            f"{orders.get('overlay_warnings', 0)} overlay warning(s)."
        )
        summary_parts.append(orders_line)

        return Response(
            command_type = "market_status",
            ok           = True,
            summary      = " ".join(summary_parts),
            metrics      = {
                "session":          sess_type,
                "data_lane":        data_lane,
                "feed_live":        feed_live,
                "broker_env":       broker_env,
                "trading_halted":   is_halted_v,
                "orders_today":     orders.get("orders_placed", 0),
                "overlay_warnings": orders.get("overlay_warnings", 0),
            },
            next_action  = (
                "market readiness"
                if not is_halted_v
                else "Resolve reconciliation mismatch before resuming."
            ),
            raw = {
                "status": status,
                "recon":  recon,
                "orders": orders,
            },
        )
    except Exception as exc:
        return Response(
            command_type = "market_status",
            ok           = False,
            summary      = f"Market status unavailable: {exc}",
            next_action  = "Check market layer modules are installed.",
            raw          = {"error": str(exc)},
        )


def handle_market_readiness(command: Command) -> Response:
    """
    Reads the latest readiness scorecard from disk and reports level in plain English.
    """
    try:
        result = read_readiness()

        if not result:
            return Response(
                command_type = "market_readiness",
                ok           = True,
                summary      = "No readiness scorecard data yet. Run a market readiness evaluation.",
                metrics      = {"level": "NOT_READY", "all_pass": False, "human_signoff": False},
                next_action  = "Trigger a readiness evaluation via the market layer.",
                raw          = {},
            )

        level      = result.get("level", "NOT_READY")
        all_pass   = result.get("all_pass", False)
        signoff    = result.get("human_signoff", False)
        signoff_by = result.get("signoff_by", "")
        signoff_at = result.get("signoff_at", "")
        gates      = result.get("gates", [])

        gate_lines = []
        for g in gates:
            icon = {"PASS": "PASS", "FAIL": "FAIL", "INSUFFICIENT_DATA": "??"}.get(
                g.get("status", ""), "?"
            )
            gate_lines.append(f"  [{icon}] {g.get('name', '')}: {g.get('detail', '')}")

        summary = (
            f"Belfort market readiness: {level}\n"
            + "\n".join(gate_lines)
        )
        if not signoff:
            summary += "\n  [?] Human sign-off: not yet recorded (required for LIVE_ELIGIBLE)"
        else:
            summary += f"\n  [PASS] Human sign-off: {signoff_by} at {signoff_at}"

        next_step = {
            "NOT_READY":        "Fix FAIL gates before advancing.",
            "OBSERVATION_ONLY": "Start paper trading to progress to PAPER_READY.",
            "PAPER_READY":      "Run shadow mode for 5+ days to progress to SHADOW_COMPLETE.",
            "SHADOW_COMPLETE":  "Provide human sign-off to reach LIVE_ELIGIBLE.",
            "LIVE_ELIGIBLE":    "All gates pass. Human sign-off recorded. Live mode authorized.",
        }.get(level, "Evaluate readiness gates.")

        return Response(
            command_type = "market_readiness",
            ok           = True,
            summary      = summary,
            metrics      = {
                "level":         level,
                "all_pass":      all_pass,
                "human_signoff": signoff,
            },
            next_action  = next_step,
            raw          = result,
        )
    except Exception as exc:
        return Response(
            command_type = "market_readiness",
            ok           = False,
            summary      = f"Readiness scorecard unavailable: {exc}",
            next_action  = "Check readiness_scorecard module.",
            raw          = {"error": str(exc)},
        )


def handle_kill_trading(command: Command) -> Response:
    """
    Write kill signal to disk. Trading loop picks it up on next tick.
    No live app imports — uses disk-based signal via observability bridge.
    """
    try:
        environment = command.args.get("environment", "paper")
        write_kill_signal(reason="peter_command", environment=environment)

        summary = (
            f"Kill signal written ({environment}). "
            "Trading loop will stop on next tick and halt all activity."
        )

        return Response(
            command_type        = "kill_trading",
            ok                  = True,
            summary             = summary,
            metrics             = {"environment": environment},
            next_action         = "Investigate reason for kill switch. Resume trading when safe.",
            human_review_needed = True,
            human_review_reason = "Kill switch engaged — operator review required before resuming.",
            raw                 = {"signal_written": True, "environment": environment},
        )
    except Exception as exc:
        return Response(
            command_type = "kill_trading",
            ok           = False,
            summary      = f"Kill switch failed: {exc}",
            next_action  = "Check kill signal write path.",
            raw          = {"error": str(exc)},
        )


# ── Belfort mode/preflight handler ────────────────────────────────────────────

from observability.belfort_summary import (
    read_belfort_preflight, read_belfort_mode,
    read_latest_signal_decision, read_signal_stats_today,
    read_latest_paper_execution, read_paper_exec_stats_today,
    read_latest_sim_trade, read_sim_stats_today, read_sim_running_status,
    read_regime_metrics, read_strategy_profile,
    read_sim_performance, read_latest_regime_snapshot,
    read_live_readiness, read_market_session,
)


def handle_belfort_status(command: Command) -> Response:
    """
    Report Belfort's current operating mode and readiness claim.
    Reads disk-only via observability bridge. No app.* imports.

    IMPORTANT: mode and readiness_level are always reported separately.
    They must never be merged into a single status field.
    """
    try:
        pf = read_belfort_preflight()

        # Authoritative mode comes from the mode state file, not the (possibly stale) preflight.
        # Preflight supplies readiness, data_lane, session, ticks, freshness — but NOT mode.
        mode            = read_belfort_mode()
        readiness_level = pf.get("readiness_level", "NOT_READY")
        data_lane       = pf.get("data_lane", "UNKNOWN")
        session_type    = pf.get("session_type", "unknown")
        ticks_today     = pf.get("observation_ticks_today", 0)
        last_tick_at    = pf.get("last_tick_at")
        can_advance     = pf.get("can_advance_to")
        blocked_by      = pf.get("advancement_blocked_by")
        broker_env      = pf.get("broker_environment", "not_configured")
        paper_creds     = pf.get("paper_credentials", False)
        written_at      = pf.get("written_at")

        # Mode description — use operator-facing labels that match the UI controls
        _mode_desc = {
            "observation": "Observe Live — watching market data, refreshing preflight snapshot, no signal eval, no orders",
            "shadow":      "Shadow Live — evaluating signals and logging decisions, no orders placed, no broker calls",
            "paper":       "Paper Trade Live — evaluating signals and submitting to Alpaca paper account (no real money)",
            "live":        "Live — real order execution (sign-off required)",
        }
        mode_line = _mode_desc.get(mode, f"Mode: {mode}")

        # Readiness description
        _readiness_desc = {
            "NOT_READY":        "Not ready — prerequisites missing",
            "OBSERVATION_ONLY": "Observation only — IEX data, cannot claim higher",
            "PAPER_READY":      "Paper ready — can run paper strategy evaluation",
            "SHADOW_COMPLETE":  "Shadow complete — shadow mode verified",
            "LIVE_ELIGIBLE":    "Live eligible — all gates passed, sign-off on file",
        }
        readiness_line = _readiness_desc.get(readiness_level, f"Readiness: {readiness_level}")

        tick_line = (
            f"Observation ticks today: {ticks_today}"
            + (f" (last at {last_tick_at})" if last_tick_at else "")
        )

        advance_line = ""
        if can_advance:
            advance_line = f"Next: can advance to {can_advance}."
        elif blocked_by:
            advance_line = f"Blocked: {blocked_by}."

        # Signal summary (secondary — only shown for shadow/paper modes)
        signal_line = ""
        signal_metrics: dict = {}
        if mode in ("shadow", "paper"):
            latest = read_latest_signal_decision()
            stats  = read_signal_stats_today()
            if latest:
                action_up = latest.get("signal_action", "hold").upper()
                symbol    = latest.get("symbol", "?")
                rationale = latest.get("signal_rationale", "")
                risk_ok   = latest.get("risk_can_proceed", True)
                risk_lbl  = "allowed" if risk_ok else f"blocked ({latest.get('risk_block_reason', '')})"
                _mode_ui = {"shadow": "Shadow Live", "paper": "Paper Trade Live"}.get(mode, mode)
                signal_line = (
                    f" Latest {_mode_ui} decision: {action_up} {symbol}. "
                    f"Rationale: {rationale}. Risk: {risk_lbl}. No order was placed."
                )
            if stats["total"] > 0:
                signal_line += (
                    f" Today: {stats['total']} decisions "
                    f"({stats['actions'].get('buy', 0)} buy, "
                    f"{stats['actions'].get('sell', 0)} sell, "
                    f"{stats['holds']} hold; "
                    f"{stats['blocked']} blocked by risk)."
                )
            signal_metrics = {
                "signal_decisions_today": stats["total"],
                "signal_holds_today":     stats["holds"],
                "signal_blocked_today":   stats["blocked"],
            }

        # Paper execution summary (PAPER mode only — clearly labeled, not styled as live)
        paper_exec_line = ""
        paper_exec_metrics: dict = {}
        if mode == "paper":
            latest_exec = read_latest_paper_execution()
            exec_stats  = read_paper_exec_stats_today()
            if latest_exec:
                exec_status = latest_exec.get("execution_status", "")
                broker_id   = latest_exec.get("broker_order_id", "")
                gate_reason = latest_exec.get("gate_block_reason", "")
                if exec_status == "submitted":
                    paper_exec_line = (
                        f" Paper order submitted: {latest_exec.get('exec_summary', '')} "
                        "(paper account only — no real money)"
                    )
                elif exec_status == "gated":
                    paper_exec_line = f" Paper order gated: {gate_reason}."
                else:
                    err = latest_exec.get("broker_error") or latest_exec.get("submission_error", "")
                    paper_exec_line = f" Paper order failed: {err}."
            if exec_stats["total"] > 0:
                paper_exec_line += (
                    f" Paper orders today: {exec_stats['submitted']} submitted, "
                    f"{exec_stats['gated']} gated, {exec_stats['errored']} errored."
                )
            paper_exec_metrics = {
                "paper_orders_submitted_today": exec_stats["submitted"],
                "paper_orders_gated_today":     exec_stats["gated"],
            }

        # Sim lane summary (always shown — available regardless of mode)
        sim_line = ""
        sim_metrics: dict = {}
        try:
            ss = read_sim_running_status()
            sim_stats  = read_sim_stats_today()
            sim_latest = read_latest_sim_trade()
            if ss["running"]:
                sim_line = (
                    f" Practice sim is RUNNING — {ss['fills']} fills this session, "
                    f"position {ss['sim_position']} shares, cash ${ss['sim_cash']:.0f}. "
                    "No real money involved."
                )
            elif sim_stats["fills"] > 0:
                sim_line = (
                    f" Sim practice today: {sim_stats['fills']} fills "
                    f"({sim_stats['buys']} buy, {sim_stats['sells']} sell). "
                    "Sim is currently stopped."
                )
            if sim_latest:
                act   = sim_latest.get("action", "hold").upper()
                price = sim_latest.get("fill_price", 0.0)
                pnl   = sim_latest.get("sim_pnl")
                pnl_str = f", P&L ${pnl:+.2f}" if pnl is not None else ""
                sim_line += f" Last sim fill: {act} @ ${price:.2f}{pnl_str}."
            sim_metrics = {
                "sim_fills_today":  sim_stats.get("fills", 0),
                "sim_running":      ss.get("running", False),
            }
        except Exception:
            pass

        # Sim performance (separate from paper — labeled clearly)
        sim_perf_line = ""
        try:
            sim_perf = read_sim_performance()
            if sim_perf["sells"] > 0:
                wr_str = ""
                if sim_perf["win_rate"] is not None:
                    wr_pct = int(round(sim_perf["win_rate"] * 100))
                    wr_note = "" if sim_perf["win_rate_valid"] else " (few trades)"
                    wr_str = f", win rate {wr_pct}%{wr_note}"
                sim_perf_line = (
                    f" Sim performance today: realized P&L ${sim_perf['realized_pnl']:+.2f}"
                    f"{wr_str}, {sim_perf['sells']} completed trade(s) "
                    "(sim only — no broker, no real money)."
                )
        except Exception:
            pass

        # Paper availability (market session context)
        paper_avail_line = ""
        try:
            _cur_sess = read_market_session()
            _avail_labels = {
                "regular":     "open \u2014 paper execution available",
                "pre_market":  "pre-market \u2014 paper not supported, sim available",
                "after_hours": "after hours \u2014 paper not supported, sim available",
                "closed":      "closed \u2014 paper not available, sim runs any time",
            }
            paper_avail_line = f" Market session: {_avail_labels.get(_cur_sess, _cur_sess)}."
        except Exception:
            pass

        # Latest auto-learning snapshot
        snapshot_line = ""
        try:
            snap = read_latest_regime_snapshot()
            if snap:
                snap_time    = (snap.get("written_at") or "")[:16] + " UTC"
                snap_verdict = snap.get("verdict", "unknown")
                snap_regime  = snap.get("market_regime") or snap.get("regime", "")
                snapshot_line = (
                    f" Latest learning snapshot: {snap_time} \u2014 verdict: {snap_verdict}"
                    + (f" [{snap_regime}]" if snap_regime else "") + "."
                )
            else:
                snapshot_line = " No auto-snapshots yet \u2014 trade 20 ticks to generate."
        except Exception:
            pass

        # Regime learning summary
        regime_line = ""
        try:
            profile    = read_strategy_profile()
            cur_regime = profile.get("current_regime", "unknown")
            _reg_labels = {
                "regular":     "Regular hours",
                "pre_market":  "Pre-market (extended)",
                "after_hours": "After hours (extended)",
                "closed":      "Market closed",
            }
            reg_label   = _reg_labels.get(cur_regime, cur_regime)
            fit_regular = profile.get("fitness_regular", "no data")
            fit_sim     = profile.get("fitness_sim", "no data")
            regime_line = (
                f" Market regime: {reg_label}. "
                f"Paper [regular hours]: {fit_regular} "
                f"Sim [any-hour]: {fit_sim} "
                "Extended hours paper: not supported."
            )
        except Exception:
            pass

        # Live readiness gate verdict
        live_readiness_line = ""
        try:
            lr = read_live_readiness()
            _lr_labels = {
                "not_enough_data": "not enough data",
                "not_ready":       "not ready",
                "candidate":       "candidate (human sign-off required)",
            }
            lr_label = _lr_labels.get(lr["verdict"], lr["verdict"])
            live_readiness_line = (
                f" Live readiness gate: {lr_label}. "
                f"{lr['note']}"
            )
        except Exception:
            pass

        # Auto-learning vs manual research distinction
        auto_learn_line = (
            " Auto-learning: runs automatically every 20 ticks from paper/sim lanes \u2014 "
            "no Research Campaigns needed for learning snapshots."
        )

        summary = (
            f"Current mode: {mode_line}. "
            f"Current readiness claim: {readiness_line}. "
            f"Data lane: {data_lane}. Session: {session_type}. "
            f"{tick_line}."
            + (f" {advance_line}" if advance_line else "")
            + signal_line
            + paper_exec_line
            + sim_line
            + sim_perf_line
            + paper_avail_line
            + snapshot_line
            + regime_line
            + live_readiness_line
            + auto_learn_line
        )

        return Response(
            command_type = "belfort_status",
            ok           = True,
            summary      = summary,
            metrics      = {
                "mode":             mode,
                "readiness_level":  readiness_level,
                "data_lane":        data_lane,
                "session_type":     session_type,
                "ticks_today":      ticks_today,
                "broker_env":       broker_env,
                "paper_credentials": paper_creds,
                **signal_metrics,
                **paper_exec_metrics,
                **sim_metrics,
            },
            next_action  = advance_line or "Run observation tick to refresh preflight.",
            raw          = pf,
        )
    except Exception as exc:
        return Response(
            command_type = "belfort_status",
            ok           = False,
            summary      = f"Belfort status unavailable: {exc}",
            next_action  = "Check belfort_observer module.",
            raw          = {"error": str(exc)},
        )


def handle_belfort_mode_control(command: Command) -> Response:
    """
    Advance, regress, or set Belfort's operating mode.
    Reads and writes via observability bridge only. No app.* imports.

    Actions:
        advance — move to next mode (observation→shadow→paper); LIVE blocked via command
        regress — move to previous mode (force_regression=True)
        set     — jump to named mode (live is blocked)

    set_mode() return contract:
        success: {ok: True,  mode: new,  previous_mode: genuine_prev, error: None}
        failure: {ok: False, mode: cur,  previous_mode: cur,          error: str}
    On failure previous_mode == mode (both = unchanged current).
    Do NOT surface previous_mode as a pre-transition value on failure.
    """
    from observability.belfort_summary import (
        read_belfort_mode, read_belfort_preflight,
        compute_next_belfort_mode, compute_prev_belfort_mode,
        apply_belfort_mode_transition,
    )

    args            = command.args or {}
    action          = args.get("action", "")
    reason          = args.get("reason", "") or ""
    target_mode_raw = args.get("target_mode", "")

    _ORDER = ["observation", "shadow", "paper", "live"]

    def _mode_idx(m: str) -> int:
        try:
            return _ORDER.index(m)
        except ValueError:
            return -1

    try:
        cur = read_belfort_mode()

        # ── Determine target mode ─────────────────────────────────────────────
        if action == "advance":
            nxt = compute_next_belfort_mode(cur)
            if nxt is None:
                return Response(
                    command_type = "belfort_mode_control",
                    ok           = False,
                    summary      = (
                        f"Cannot advance: already at {cur!r}. "
                        "Paper is the highest mode reachable via command. "
                        "LIVE requires manual sign-off file."
                    ),
                    metrics      = {"current_mode": cur},
                    next_action  = "Place data/belfort/live_sign_off.json to reach LIVE.",
                    raw          = {"action": action, "current_mode": cur},
                )
            target        = nxt
            force_regress = False

        elif action == "regress":
            prv = compute_prev_belfort_mode(cur)
            if prv is None:
                return Response(
                    command_type = "belfort_mode_control",
                    ok           = False,
                    summary      = f"Cannot regress: already at {cur!r} (bottom of mode order).",
                    metrics      = {"current_mode": cur},
                    next_action  = "No further regression possible.",
                    raw          = {"action": action, "current_mode": cur},
                )
            target        = prv
            force_regress = True

        elif action == "set":
            target = target_mode_raw.lower()
            if target == "live":
                return Response(
                    command_type = "belfort_mode_control",
                    ok           = False,
                    summary      = (
                        "Cannot set mode to LIVE via command. "
                        "Place data/belfort/live_sign_off.json manually."
                    ),
                    metrics      = {"current_mode": cur},
                    next_action  = "Manual sign-off required for LIVE mode.",
                    raw          = {"action": action, "target_mode": target},
                )
            if target not in ("observation", "shadow", "paper"):
                return Response(
                    command_type = "belfort_mode_control",
                    ok           = False,
                    summary      = f"Unknown mode {target!r}. Valid: observation, shadow, paper.",
                    metrics      = {"current_mode": cur},
                    next_action  = "Specify a valid target mode.",
                    raw          = {"action": action, "target_mode": target},
                )
            force_regress = _mode_idx(target) < _mode_idx(cur)

        else:
            return Response(
                command_type = "belfort_mode_control",
                ok           = False,
                summary      = (
                    f"Unknown action {action!r}. "
                    "Use: belfort advance, belfort regress, belfort set <mode>."
                ),
                next_action  = "Re-issue with a valid action.",
                raw          = {"action": action},
            )

        # ── Apply transition ───────────────────────────────────────────────────
        result = apply_belfort_mode_transition(
            target_mode      = target,
            initiated_by     = "peter_command",
            reason           = reason,
            force_regression = force_regress,
        )

        ok        = result.get("ok", False)
        new_mode  = result.get("mode", cur)
        error_msg = result.get("error")

        # Readiness from preflight after transition attempt
        pf        = read_belfort_preflight()
        readiness = pf.get("readiness_level", "NOT_READY")

        if ok:
            genuine_prev = result.get("previous_mode", cur)
            summary = f"Mode changed: {genuine_prev} → {new_mode}."
            if readiness == "OBSERVATION_ONLY" and new_mode != "observation":
                summary += (
                    " Note: readiness capped at OBSERVATION_ONLY "
                    "(IEX_ONLY data lane — SIP required for higher claims)."
                )
            return Response(
                command_type = "belfort_mode_control",
                ok           = True,
                summary      = summary,
                metrics      = {
                    "previous_mode":  genuine_prev,
                    "mode":           new_mode,
                    "readiness_level": readiness,
                    "action":         action,
                },
                next_action  = f"Belfort is now in {new_mode} mode.",
                raw          = result,
            )

        # Failure — previous_mode == mode == unchanged current; do not surface it as pre-transition
        return Response(
            command_type = "belfort_mode_control",
            ok           = False,
            summary      = f"Mode transition to {target!r} failed: {error_msg or 'unknown error'}.",
            metrics      = {
                "current_mode":    new_mode,
                "readiness_level": readiness,
                "action":          action,
            },
            next_action  = "Check mode transition gate conditions.",
            raw          = result,
        )

    except Exception as exc:
        return Response(
            command_type = "belfort_mode_control",
            ok           = False,
            summary      = f"Belfort mode control error: {exc}",
            next_action  = "Check belfort_summary module.",
            raw          = {"error": str(exc)},
        )
