# observability/agent_state.py
#
# Durable per-agent run-state layer.
#
# Each agent has a JSON file at data/agent_state/{agent_name}.json that is the
# single source of truth for UI display and Peter summaries.
#
# Status values (mutually exclusive):
#   idle                — not running anything
#   running_batch       — executing a bounded validation batch
#   running_session     — running a multi-batch session
#   running_campaign    — running a multi-session campaign
#   waiting_for_review  — stopped, candidate awaiting human review
#   paused_by_budget    — cost budget exhausted, halted
#   stopped_by_guardrail — governance or policy halt
#
# "Actively learning" = status is in ACTIVE_STATUSES.
# This definition is strict and artifact-based: only true when bounded
# validation work is executing and writing results to disk.
#
# Public API:
#   load_state(agent_name, agent_role) → AgentState
#   save_state(state) → None
#   transition(agent_name, *, ...) → AgentState
#   update_heartbeat(agent_name, agent_role) → AgentState

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional

_ROOT      = pathlib.Path(__file__).resolve().parent.parent
STATE_DIR  = _ROOT / "data" / "agent_state"

# Agent name constants
MR_BELFORT = "mr_belfort"
PETER      = "peter"

# Status constants
STATUS_IDLE               = "idle"
STATUS_RUNNING_BATCH      = "running_batch"
STATUS_RUNNING_SESSION    = "running_session"
STATUS_RUNNING_CAMPAIGN   = "running_campaign"
STATUS_WAITING_FOR_REVIEW = "waiting_for_review"
STATUS_REVIEW_HELD        = "review_held"        # operator deferred decision; candidate still pending
STATUS_PAUSED_BY_BUDGET   = "paused_by_budget"
STATUS_STOPPED_GUARDRAIL  = "stopped_by_guardrail"

# Statuses that count as "actively learning"
ACTIVE_STATUSES = frozenset({
    STATUS_RUNNING_BATCH,
    STATUS_RUNNING_SESSION,
    STATUS_RUNNING_CAMPAIGN,
})


@dataclass
class AgentState:
    agent_name:             str
    agent_role:             str
    status:                 str
    actively_learning:      bool
    current_task:           Optional[str]
    campaign_id:            Optional[str]
    session_id:             Optional[str]
    batch_id:               Optional[str]
    started_at:             Optional[str]   # ISO — when current work began
    last_heartbeat_at:      Optional[str]   # ISO — last state update
    last_completed_action:  Optional[str]   # human-readable last milestone
    stop_reason:            Optional[str]   # why stopped / paused
    budget_max_usd:         Optional[float] # configured campaign budget (None = no limit)
    schema_version:         str = "1.0"

    @staticmethod
    def default(agent_name: str, agent_role: str = "unknown") -> "AgentState":
        return AgentState(
            agent_name            = agent_name,
            agent_role            = agent_role,
            status                = STATUS_IDLE,
            actively_learning     = False,
            current_task          = None,
            campaign_id           = None,
            session_id            = None,
            batch_id              = None,
            started_at            = None,
            last_heartbeat_at     = _now(),
            last_completed_action = None,
            stop_reason           = None,
            budget_max_usd        = None,
        )


# ── I/O ───────────────────────────────────────────────────────────────────────

def _state_path(agent_name: str) -> pathlib.Path:
    return STATE_DIR / f"{agent_name}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(agent_name: str, agent_role: str = "unknown") -> AgentState:
    """Load agent state from disk, or return a fresh default."""
    path = _state_path(agent_name)
    if not path.exists():
        return AgentState.default(agent_name, agent_role)
    try:
        data = json.loads(path.read_text())
        # Forward-compatible: only keep known fields
        known = set(AgentState.__dataclass_fields__)
        filtered = {k: v for k, v in data.items() if k in known}
        # Fill any missing fields with defaults
        defaults = asdict(AgentState.default(agent_name, agent_role))
        return AgentState(**{**defaults, **filtered})
    except Exception:
        return AgentState.default(agent_name, agent_role)


def save_state(state: AgentState) -> None:
    """Atomically write state to disk (write temp file → rename)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _state_path(state.agent_name)
    tmp  = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2))
    tmp.rename(path)


# ── Transitions ───────────────────────────────────────────────────────────────

def transition(
    agent_name: str,
    *,
    agent_role:             str = "unknown",
    status:                 str,
    current_task:           Optional[str] = None,
    campaign_id:            Optional[str] = None,
    session_id:             Optional[str] = None,
    batch_id:               Optional[str] = None,
    last_completed_action:  Optional[str] = None,
    stop_reason:            Optional[str] = None,
    budget_max_usd:         Optional[float] = None,
) -> AgentState:
    """
    Atomically transition agent to a new status and save.

    Fields not supplied are inherited from the current state.
    `actively_learning` is derived from `status` automatically.
    `started_at` is set when entering an ACTIVE_STATUS, cleared on exit.
    """
    state = load_state(agent_name, agent_role)

    state.status           = status
    state.actively_learning = status in ACTIVE_STATUSES
    state.last_heartbeat_at = _now()

    # Carry forward or update optional fields
    if current_task is not None:
        state.current_task = current_task
    if campaign_id is not None:
        state.campaign_id = campaign_id
    if session_id is not None:
        state.session_id = session_id
    if batch_id is not None:
        state.batch_id = batch_id
    if last_completed_action is not None:
        state.last_completed_action = last_completed_action
    if stop_reason is not None:
        state.stop_reason = stop_reason
    if budget_max_usd is not None:
        state.budget_max_usd = budget_max_usd

    # started_at: set on first entry into active status, cleared on exit
    if status in ACTIVE_STATUSES:
        state.stop_reason = None   # clear old stop reason when work resumes
        if state.started_at is None:
            state.started_at = _now()
    else:
        state.started_at = None

    save_state(state)
    return state


def update_heartbeat(agent_name: str, agent_role: str = "unknown") -> AgentState:
    """Refresh last_heartbeat_at without changing any other state."""
    state = load_state(agent_name, agent_role)
    state.last_heartbeat_at = _now()
    save_state(state)
    return state
