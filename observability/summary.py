# observability/summary.py
#
# Peter-ready summary helpers for Mr Belfort and Peter.
#
# All functions read from durable state + telemetry artifacts on disk.
# No live system calls, no research/ imports.
# Safe to call from Peter handlers and the UI.
#
# Public API:
#   belfort_status_summary()             → str  — one-paragraph status
#   belfort_learning_status()            → str  — yes/no with reason
#   belfort_cost_summary(campaign_id)    → str  — cost/token summary line
#   belfort_stop_reason()                → str  — why stopped, or "active"
#   full_belfort_brief(campaign_id)      → dict — structured dict for UI / Peter

from __future__ import annotations

from typing import Optional

from observability.agent_state import (
    AgentState,
    load_state,
    MR_BELFORT,
    PETER,
    ACTIVE_STATUSES,
)
from observability.telemetry import summarize as _tel_summarize
from observability.budget import evaluate_budget, BudgetConfig


# ── Text summaries (Peter-ready) ─────────────────────────────────────────────

def belfort_status_summary() -> str:
    """
    One-paragraph plain-English status for Mr Belfort.
    Suitable for Peter to relay to an operator.
    """
    state = load_state(MR_BELFORT, "trading_agent")

    if state.status in ACTIVE_STATUSES:
        label = state.status.replace("_", " ")
        parts = [f"Mr Belfort is ACTIVE — {label}."]
        if state.current_task:
            parts.append(f"Current task: {state.current_task}.")
        if state.campaign_id:
            parts.append(f"Campaign: {state.campaign_id}.")
        if state.session_id:
            parts.append(f"Session: {state.session_id}.")
        if state.batch_id:
            parts.append(f"Batch: {state.batch_id}.")
        if state.started_at:
            parts.append(f"Work started at: {state.started_at[:19]}Z.")
        if state.last_heartbeat_at:
            parts.append(f"Last heartbeat: {state.last_heartbeat_at[:19]}Z.")
        return " ".join(parts)

    label = state.status.replace("_", " ")
    parts = [f"Mr Belfort is INACTIVE — status: {label}."]
    if state.stop_reason:
        parts.append(f"Stop reason: {state.stop_reason}")
    if state.last_completed_action:
        parts.append(f"Last action: {state.last_completed_action}.")
    if state.last_heartbeat_at:
        parts.append(f"Last heartbeat: {state.last_heartbeat_at[:19]}Z.")
    return " ".join(parts)


def belfort_learning_status() -> str:
    """
    Single-sentence answer to "is Mr Belfort actively learning right now?"
    """
    state = load_state(MR_BELFORT, "trading_agent")
    if state.actively_learning:
        task = state.current_task or "unknown task"
        return f"Yes — Mr Belfort is actively learning. Currently: {task}."
    return (
        f"No — Mr Belfort is not currently learning "
        f"(status: {state.status.replace('_', ' ')})."
    )


def belfort_cost_summary(campaign_id: Optional[str] = None) -> str:
    """
    Cost/token summary for a campaign.
    Loads from telemetry JSONL; returns a labeled string.
    Falls back to active campaign if campaign_id not supplied.
    """
    state = load_state(MR_BELFORT, "trading_agent")
    scope_id = campaign_id or state.campaign_id

    if not scope_id:
        return "No active or recent campaign — no cost data available."

    tel = _tel_summarize(scope_id)
    if not tel:
        return f"Campaign {scope_id}: no telemetry recorded yet."

    label = " [ESTIMATED]" if tel.is_estimated else ""
    return (
        f"Campaign {scope_id}{label}: "
        f"${tel.estimated_cost_usd:.4f} USD | "
        f"{tel.request_count} requests | "
        f"{tel.total_tokens:,} tokens "
        f"({tel.input_tokens:,} in / {tel.output_tokens:,} out)."
    )


def belfort_stop_reason() -> str:
    """Why Mr Belfort stopped. Returns "active" message if still running."""
    state = load_state(MR_BELFORT, "trading_agent")
    if state.status in ACTIVE_STATUSES:
        return "Mr Belfort has not stopped — he is currently active."
    if state.stop_reason:
        return f"Stop reason: {state.stop_reason}"
    return "Mr Belfort is idle. No specific stop reason recorded."


def belfort_next_review() -> str:
    """What the operator should review next, based on state."""
    state = load_state(MR_BELFORT, "trading_agent")
    if state.status == "waiting_for_review":
        cid = state.campaign_id or "unknown campaign"
        return (
            f"Mr Belfort is waiting for operator review. "
            f"Campaign: {cid}. "
            "Check: python scripts/peter.py best candidate"
        )
    if state.status in ACTIVE_STATUSES:
        return "No review needed — Mr Belfort is still running."
    if state.last_completed_action:
        return f"Review output from: {state.last_completed_action}"
    return "No pending review items found."


# ── Structured brief (for UI and Peter raw dict) ─────────────────────────────

def full_belfort_brief(campaign_id: Optional[str] = None) -> dict:
    """
    Structured dict suitable for UI rendering or Peter's `raw` field.

    Fields:
        agent            — "Mr Belfort"
        status           — raw status string
        actively_learning — bool
        current_task     — str | None
        campaign_id      — str | None
        session_id       — str | None
        batch_id         — str | None
        started_at       — ISO str | None
        last_heartbeat_at — ISO str | None
        last_completed_action — str | None
        stop_reason      — str | None
        budget           — dict with max_usd, spent_usd, pct_used, bar, warning, hard_stop
        telemetry        — dict with request_count, total_tokens, cost_usd, is_estimated
        summaries        — dict of ready-made text strings for Peter to relay
    """
    state    = load_state(MR_BELFORT, "trading_agent")
    scope_id = campaign_id or state.campaign_id

    # Telemetry
    tel = _tel_summarize(scope_id) if scope_id else None
    spent_usd = tel.estimated_cost_usd if tel else 0.0
    is_est    = tel.is_estimated       if tel else True

    # Budget (use state.budget_max_usd if set, else no budget defined)
    budget_dict: dict = {}
    if state.budget_max_usd is not None:
        cfg    = BudgetConfig(max_cost_usd=state.budget_max_usd)
        bstatus = evaluate_budget(cfg, spent_usd, is_estimated=is_est)
        budget_dict = {
            "max_usd":    bstatus.max_cost_usd,
            "spent_usd":  round(bstatus.spent_usd, 6),
            "remaining":  round(bstatus.remaining_usd, 6),
            "pct_used":   round(bstatus.pct_used * 100, 1),
            "bar":        bstatus.budget_bar,
            "warning":    bstatus.warning_triggered,
            "hard_stop":  bstatus.hard_stop_triggered,
            "is_estimated": is_est,
        }
    else:
        budget_dict = {"configured": False}

    # Telemetry dict
    tel_dict: dict = {
        "scope_id":          scope_id,
        "request_count":     tel.request_count      if tel else 0,
        "input_tokens":      tel.input_tokens        if tel else 0,
        "output_tokens":     tel.output_tokens       if tel else 0,
        "total_tokens":      tel.total_tokens        if tel else 0,
        "estimated_cost_usd": round(tel.estimated_cost_usd, 6) if tel else 0.0,
        "is_estimated":      tel.is_estimated        if tel else True,
        "note":              (
            "Simulation batches use in-process Python — no API tokens consumed. "
            "Cost is $0 until OpenRouter LLM calls are wired in."
        ),
    }

    return {
        "agent":                 "Mr Belfort",
        "status":                state.status,
        "actively_learning":     state.actively_learning,
        "current_task":          state.current_task,
        "campaign_id":           state.campaign_id,
        "session_id":            state.session_id,
        "batch_id":              state.batch_id,
        "started_at":            state.started_at,
        "last_heartbeat_at":     state.last_heartbeat_at,
        "last_completed_action": state.last_completed_action,
        "stop_reason":           state.stop_reason,
        "budget":                budget_dict,
        "telemetry":             tel_dict,
        "summaries": {
            "status":       belfort_status_summary(),
            "learning":     belfort_learning_status(),
            "cost":         belfort_cost_summary(scope_id),
            "stop_reason":  belfort_stop_reason(),
            "next_review":  belfort_next_review(),
        },
    }
