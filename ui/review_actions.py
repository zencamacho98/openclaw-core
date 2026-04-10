# ui/review_actions.py
#
# Pure helpers for the Peter review flow.
# No Streamlit imports. All side-effects go through the backend API or
# observability.agent_state — never touching config files directly.
#
# Public API:
#   get_review_payload(record_path)         → (ok, error_msg, record_dict)
#   skip_and_continue_action(resumable, all_campaigns) → ("resume"|"start", id_or_goal)
#   hold_review(record_path)                → dict
#   resume_review(record_path)              → dict

from __future__ import annotations

import json
import pathlib
from typing import Optional

from observability.agent_state import (
    transition,
    load_state,
    save_state,
    MR_BELFORT,
    STATUS_IDLE,
    STATUS_REVIEW_HELD,
    STATUS_WAITING_FOR_REVIEW,
)


# ── Payload validation ────────────────────────────────────────────────────────

def get_review_payload(record_path: str) -> tuple[bool, str, dict]:
    """
    Validate a validation record locally before making an API call.

    Returns (ok, error_msg, record_dict).
      ok=True, error=""  → record is valid and promotable
      ok=False, error=X  → cannot promote; error is a human-readable explanation
    """
    if not record_path:
        return False, "No record path provided.", {}

    path = pathlib.Path(record_path)
    if not path.exists():
        return False, f"Validation record not found: {record_path}", {}

    try:
        record = json.loads(path.read_text())
    except Exception as exc:
        return False, f"Cannot read validation record: {exc}", {}

    decision = record.get("decision")
    if decision != "ACCEPTED":
        return (
            False,
            f"Promotion blocked: decision is {decision!r}, expected ACCEPTED.",
            record,
        )

    candidate_cfg = record.get("candidate_config")
    if not candidate_cfg:
        return False, "Validation record has no candidate_config — nothing to promote.", record

    return True, "", record


# ── Skip and Continue ─────────────────────────────────────────────────────────

def skip_and_continue_action(
    resumable: list,
    all_campaigns: list,
) -> tuple[str, str]:
    """
    Decide the best "continue without applying" action.

    Returns ("resume", campaign_id) if there is a resumable campaign,
    otherwise ("start", goal) where goal is the last known research goal
    or a sensible default.
    """
    if resumable:
        # Pick the most recent resumable campaign
        return "resume", resumable[-1].get("campaign_id", "")

    goal = _last_goal(all_campaigns)
    return "start", goal


def _last_goal(all_campaigns: list) -> str:
    """
    Return the goal string from the most recent campaign that has one, or a default.

    Assumes all_campaigns is newest-first (as returned by list_campaigns()).
    Iterates directly — do NOT reverse.
    """
    for campaign in all_campaigns:
        goal = campaign.get("goal") or campaign.get("research_goal")
        if goal and isinstance(goal, str) and goal.strip():
            return goal.strip()
    return "systematic strategy research"


# ── Hold / Resume review ──────────────────────────────────────────────────────

def hold_review(record_path: str = "") -> dict:
    """
    Transition Belfort to review_held.

    Preserves the pending candidate context — the record_path is embedded
    in the stop_reason so Peter can surface it on the next load.

    Returns the new AgentState as a dict.
    """
    state = transition(
        MR_BELFORT,
        agent_role="trading_agent",
        status=STATUS_REVIEW_HELD,
        stop_reason=f"review_held:{record_path}" if record_path else "review_held",
        last_completed_action="Operator deferred review — candidate pending",
    )
    from dataclasses import asdict
    return asdict(state)


def resume_review(record_path: str = "") -> dict:
    """
    Transition Belfort back to waiting_for_review.

    Restores the standard review state so the candidate card is shown again.
    """
    state = transition(
        MR_BELFORT,
        agent_role="trading_agent",
        status=STATUS_WAITING_FOR_REVIEW,
        stop_reason=None,
        last_completed_action="Operator resumed deferred review",
    )
    from dataclasses import asdict
    return asdict(state)


def skip_review(record_path: str = "") -> dict:
    """
    Transition Belfort out of any review state without applying the candidate.

    Must be called BEFORE spawning the next campaign in skip/dismiss flows.
    This prevents Belfort from being stuck in waiting_for_review if the
    subsequent campaign spawn fails.

    Note: transition() only clears stop_reason when entering an ACTIVE_STATUS.
    For idle, we explicitly clear it so no stale review context lingers.
    """
    state = transition(
        MR_BELFORT,
        agent_role="trading_agent",
        status=STATUS_IDLE,
        last_completed_action="Candidate skipped — not applied",
    )
    state.stop_reason = None
    save_state(state)
    from dataclasses import asdict
    return asdict(state)
