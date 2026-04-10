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
from typing import Any

from peter.commands import Command, CommandType, HELP_TEXT
from peter.responses import Response, error_response, no_data_response
from observability.summary import full_belfort_brief

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_CAMPAIGNS    = _ROOT / "data" / "campaigns"
_REPORTS      = _ROOT / "data" / "research_ledger" / "reports"
_LEDGER       = _ROOT / "data" / "research_ledger" / "ledger.jsonl"
_VAL_RUNS     = _ROOT / "data" / "validation_runs"

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
