# app/routes/supervisor.py
#
# FastAPI router for continuous learning loop control and checker findings.
#
# Mounts at prefix /supervisor (supervisor state/control, queue management)
# and /checker (read-only findings from the health auditor).
#
# No Streamlit imports — pure JSON API consumed by the dashboard and Peter.
#
# Endpoints:
#   GET  /supervisor/state              — supervisor state dict
#   POST /supervisor/enable             — enable continuous learning loop
#   POST /supervisor/disable            — request graceful stop
#   GET  /supervisor/queue              — list candidate queue (newest-first)
#   GET  /supervisor/queue/{queue_id}   — single queue item
#   POST /supervisor/queue/{queue_id}/approve   — approve candidate
#   POST /supervisor/queue/{queue_id}/reject    — reject candidate
#   POST /supervisor/queue/{queue_id}/hold      — hold candidate (defer)
#   GET  /checker/state                 — checker daemon status
#   GET  /checker/findings              — recent unacknowledged findings
#   POST /checker/findings/{id}/acknowledge — acknowledge a finding

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException

from app.supervisor import (
    get_supervisor_state,
    enable_continuous,
    disable_continuous,
)
from app.checker import (
    get_checker_state,
    read_findings,
    acknowledge_finding,
)
from research.candidate_queue import (
    read_queue,
    get_queue_item,
    update_queue_item,
)

router = APIRouter()

_SUPERVISORS_PREFIX = "/supervisor"
_CHECKER_PREFIX     = "/checker"


# ── Supervisor state / control ────────────────────────────────────────────────

@router.get("/supervisor/state")
def supervisor_state() -> dict:
    return get_supervisor_state()


@router.post("/supervisor/enable")
def supervisor_enable(body: dict = Body(default={})) -> dict:
    """
    Enable continuous learning loop.
    Optionally accepts {goal: str} to seed the next campaign with a trigger-derived goal.
    """
    goal = ((body or {}).get("goal") or "").strip()
    if goal:
        from app.supervisor import write_pending_goal
        write_pending_goal(goal)
    return enable_continuous()


@router.post("/supervisor/disable")
def supervisor_disable() -> dict:
    return disable_continuous()


# ── Candidate queue ───────────────────────────────────────────────────────────

@router.get("/supervisor/queue")
def queue_list(status: Optional[str] = None) -> list[dict]:
    """
    Return the candidate queue, newest-first.

    Optional query param `status` filters by status value
    (e.g. ?status=pending returns only pending items).
    """
    items = read_queue()
    if status:
        items = [i for i in items if i.get("status") == status]
    return items


@router.get("/supervisor/queue/{queue_id}")
def queue_item(queue_id: str) -> dict:
    item = get_queue_item(queue_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Queue item '{queue_id}' not found.")
    return item


@router.post("/supervisor/queue/{queue_id}/approve")
def queue_approve(queue_id: str, body: dict = Body(default={})) -> dict:
    """
    Approve a pending candidate.

    Optionally provide { "operator_id": "...", "note": "..." } in the body.
    Approval does NOT auto-apply — the operator must still run the promote command.
    """
    item = get_queue_item(queue_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Queue item '{queue_id}' not found.")
    if item.get("status") not in ("pending", "held"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve item with status '{item.get('status')}'.",
        )

    operator_id = (body or {}).get("operator_id", "operator")
    note        = (body or {}).get("note", "")

    updated = update_queue_item(
        queue_id,
        status="approved",
        resolved_at=_now(),
        resolution=f"Approved by {operator_id}" + (f": {note}" if note else ""),
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update queue item.")

    # Write to event log
    _emit_queue_event("candidate_approved", queue_id, item, operator_id)

    return {"ok": True, "queue_id": queue_id, "status": "approved"}


@router.post("/supervisor/queue/{queue_id}/reject")
def queue_reject(queue_id: str, body: dict = Body(default={})) -> dict:
    """Reject a pending candidate."""
    item = get_queue_item(queue_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Queue item '{queue_id}' not found.")
    if item.get("status") not in ("pending", "held"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject item with status '{item.get('status')}'.",
        )

    operator_id = (body or {}).get("operator_id", "operator")
    note        = (body or {}).get("note", "")

    updated = update_queue_item(
        queue_id,
        status="rejected",
        resolved_at=_now(),
        resolution=f"Rejected by {operator_id}" + (f": {note}" if note else ""),
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update queue item.")

    _emit_queue_event("candidate_rejected", queue_id, item, operator_id)

    return {"ok": True, "queue_id": queue_id, "status": "rejected"}


@router.post("/supervisor/queue/{queue_id}/hold")
def queue_hold(queue_id: str, body: dict = Body(default={})) -> dict:
    """
    Hold (defer) a pending candidate.

    The candidate remains in the queue with status='held'.
    The loop continues — hold does NOT block Belfort.
    """
    item = get_queue_item(queue_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Queue item '{queue_id}' not found.")
    if item.get("status") != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Can only hold 'pending' items (current: '{item.get('status')}').",
        )

    operator_id = (body or {}).get("operator_id", "operator")
    note        = (body or {}).get("note", "")

    updated = update_queue_item(
        queue_id,
        status="held",
        resolution=f"Deferred by {operator_id}" + (f": {note}" if note else ""),
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update queue item.")

    return {"ok": True, "queue_id": queue_id, "status": "held"}


# ── Checker ───────────────────────────────────────────────────────────────────

@router.get("/checker/state")
def checker_state() -> dict:
    return get_checker_state()


@router.get("/checker/findings")
def checker_findings(
    limit: int = 50,
    include_acknowledged: bool = False,
) -> list[dict]:
    return read_findings(limit=limit, include_acknowledged=include_acknowledged)


@router.post("/checker/findings/{finding_id}/acknowledge")
def checker_acknowledge(finding_id: str, body: dict = Body(default={})) -> dict:
    operator_id = (body or {}).get("operator_id", "operator")
    ok = acknowledge_finding(finding_id, operator_id=operator_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Finding '{finding_id}' not found or already acknowledged.",
        )
    return {"ok": True, "finding_id": finding_id, "acknowledged_by": operator_id}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit_queue_event(event_type: str, queue_id: str, item: dict, operator_id: str) -> None:
    """Mirror queue action to event log (best-effort, never raises)."""
    try:
        from observability.event_log import append_event
        exp_id = item.get("experiment_id", "?")
        tier   = item.get("tier", "?")
        score  = item.get("score", "?")
        append_event(
            event_type=event_type,
            summary=(
                f"Operator {event_type.replace('_', ' ')}: {exp_id} "
                f"(tier={tier}, score={score}) — queue_id={queue_id}."
            ),
            severity="important",
            source=operator_id,
            campaign_id=item.get("campaign_id"),
        )
    except Exception:
        pass
