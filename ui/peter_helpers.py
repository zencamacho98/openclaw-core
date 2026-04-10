# ui/peter_helpers.py
#
# Pure helpers for the Peter tab — Belfort state-to-action mapping and
# Peter intervention state logic.
# No Streamlit imports. No research/ imports. Safe to unit-test directly.
#
# Public API:
#   belfort_action_state(status, stop_pending, resumable)        -> str
#   peter_intervention_state(b_status, stop_pending, resumable)  -> str
#   auto_continue_goal(all_campaigns)                            -> str
#
# belfort_action_state keys (exhaustive):
#   "idle"               — idle, no resumable campaigns
#   "idle_with_resumable"— idle, at least one resumable campaign exists
#   "running"            — active work in progress
#   "stop_pending"       — stop signal sent, current session still finishing
#   "waiting_for_review" — candidate awaiting human review
#   "review_held"        — operator deferred decision; candidate still pending
#
# peter_intervention_state keys (exhaustive):
#   "stop_pending"       — stop in flight, nothing for Peter to do yet
#   "running"            — work in progress, no action needed
#   "review_needed"      — new candidate waiting for a decision
#   "review_held"        — operator previously deferred; prompt to revisit
#   "stopped_hard"       — stopped by guardrail or budget, needs operator attention
#   "resumable"          — paused/idle with campaigns that can be resumed
#   "ready"              — idle, no pending work, ready to start fresh

from __future__ import annotations

_ACTIVE = frozenset({"running_campaign", "running_session", "running_batch"})


def belfort_action_state(status: str, stop_pending: bool, resumable: list) -> str:
    """
    Map current Belfort state to a control action key.

    Priority order (highest first):
      1. stop_pending  — overrides everything; signal is already in flight
      2. running       — active statuses
      3. waiting_for_review
      4. review_held
      5. idle_with_resumable
      6. idle          — fallthrough
    """
    if stop_pending:
        return "stop_pending"
    if status in _ACTIVE:
        return "running"
    if status == "waiting_for_review":
        return "waiting_for_review"
    if status == "review_held":
        return "review_held"
    if resumable:
        return "idle_with_resumable"
    return "idle"


def peter_intervention_state(
    b_status: str,
    stop_pending: bool,
    resumable: list,
) -> str:
    """
    Map Belfort state to a Peter intervention key.

    Peter's view prioritises surfaces that need human attention:
      1. review_needed  — new candidate waiting (waiting_for_review)
      2. review_held    — deferred candidate still pending
      3. stop_pending   — stop in flight
      4. stopped_hard   — hard stop (guardrail / budget)
      5. running        — work in progress, nothing to do
      6. resumable      — idle with campaigns to resume
      7. ready          — truly idle, no pending work
    """
    if b_status == "waiting_for_review":
        return "review_needed"
    if b_status == "review_held":
        return "review_held"
    if stop_pending:
        return "stop_pending"
    if b_status in ("stopped_by_guardrail", "paused_by_budget"):
        return "stopped_hard"
    if b_status in _ACTIVE:
        return "running"
    if resumable:
        return "resumable"
    return "ready"


def loop_explanation_text(
    sup_state: dict,
    camp_state: dict | None,
    *,
    default_sessions: int = 3,
    default_batches: int = 3,
    default_exp: int = 3,
) -> dict[str, str]:
    """
    Return plain-English explanation of the continuous learning loop.

    Returns a dict with two keys:
      "status_line"  — one-sentence current state (dynamic)
      "how_it_works" — multi-sentence explanation using actual current limits

    Parameters
    ----------
    sup_state        From get_supervisor_state() — enabled, cycle_count, stop_requested.
    camp_state       Current campaign state dict (or None). Used to read actual limits.
    default_sessions Fallback when no campaign config is available.
    default_batches  Fallback when no campaign config is available.
    default_exp      Fallback when no campaign config is available.
    """
    enabled  = sup_state.get("enabled", False)
    stop_req = sup_state.get("stop_requested", False)
    cycles   = int(sup_state.get("cycle_count", 0))

    cfg      = (camp_state or {}).get("config") or {}
    sessions = int(cfg.get("max_sessions",          default_sessions))
    batches  = int(cfg.get("max_batches_per_session", default_batches))
    exp      = int(cfg.get("experiments_per_batch",  default_exp))
    total    = sessions * batches * exp

    progress  = (camp_state or {}).get("progress") or {}
    sess_done = int(progress.get("sessions_completed", 0))
    exp_done  = int(progress.get("total_experiments",  0))

    if enabled and not stop_req:
        status = (
            f"Active — cycle {cycles + 1} in progress · "
            f"round {sess_done} of {sessions} · {exp_done} experiments run"
        )
    elif stop_req:
        status = f"Stopping after the current cycle · {cycles} cycle(s) completed"
    else:
        status = f"Off · {cycles} cycle(s) completed"

    how = (
        f"Each learning cycle runs up to {sessions} rounds of research. "
        f"Each round tests {batches} batches of {exp} experiments "
        f"({total} experiments max per cycle). "
        f"Cycles are kept this small so costs stay predictable, "
        f"quality stays high, and you stay in control of what gets applied. "
        f"When a cycle ends, the best-performing candidate appears for your review — "
        f"approve it to apply the upgrade and start the next cycle with the improved strategy."
    )

    return {"status_line": status, "how_it_works": how}


def auto_continue_goal(all_campaigns: list) -> str:
    """
    Return the goal for an auto-continue action.

    Picks the goal string from the most recent campaign that has one,
    falling back to a sensible default.

    Assumes all_campaigns is newest-first (as returned by list_campaigns()).
    Iterates directly — do NOT reverse.
    """
    for campaign in all_campaigns:
        goal = campaign.get("goal") or campaign.get("research_goal")
        if goal and isinstance(goal, str) and goal.strip():
            return goal.strip()
    return "systematic strategy research"
