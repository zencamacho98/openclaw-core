# ui/peter_command.py
#
# Thin command adapter for the Peter UI command surface.
#
# This is the single execution path for Peter commands arriving from the UI.
# The same function is designed to be called by a Discord adapter later —
# pass the right context and it works transport-agnostically.
#
# Responsibilities:
#   1. Parse free-form text → Command (via peter.commands.parse_command)
#   2. Action commands: execute directly via ui/campaign_control + ui/review_actions
#   3. Info commands: route through peter.router → handlers → Response → to_chat_text()
#   4. "what happened last": reads event_log + last_completed_action — the same
#      source as Peter Inbox, never diverges from what the operator sees in the UI
#
# Public API:
#   execute_ui_command(text, all_campaigns, resumable, rec_path, b_action_state,
#                      last_completed_action, apply_candidate_fn) → dict
#
#   Returns {ok, message, event_type, severity, extra, command_type}.
#   event_type == "" → caller should not log an event.
#
# Ordering invariants:
#   resumable is newest-first (from list_resumable_campaigns() → list_campaigns()).
#   Resume Safe picks resumable[0] — the MOST RECENT interrupted campaign.
#
# Start Auto is blocked when b_action_state is any of:
#   running, stop_pending, waiting_for_review, review_held

from __future__ import annotations

from typing import Any, Callable, Optional

from peter.commands import CommandType, parse_command
from peter.router import route

from ui.campaign_control import (
    start_campaign,
    resume_campaign,
    request_stop,
    cancel_stop_signal,
)
from ui.peter_helpers import auto_continue_goal
from ui.review_actions import hold_review, resume_review

# "what happened last" reads from the same event log that feeds Peter Inbox.
# Never routed through peter.handlers.handle_explain_result (batch/session reports),
# which can diverge from what the operator sees in the UI.
try:
    from observability.event_log import read_recent_events as _read_events
except Exception:
    def _read_events(*args: Any, **kwargs: Any) -> list:  # type: ignore[misc]
        return []

# States where Start Auto is blocked (operator must resolve before starting)
_START_AUTO_BLOCKED = frozenset({
    "running",
    "stop_pending",
    "waiting_for_review",
    "review_held",
})

# Commands handled locally in this adapter (action execution or event-log sourcing)
_LOCAL_COMMANDS = frozenset({
    CommandType.START_AUTO,
    CommandType.STOP_CAMPAIGN,
    CommandType.CANCEL_STOP,
    CommandType.HOLD_REVIEW,
    CommandType.RESUME_REVIEW,
    CommandType.APPLY_AND_CONTINUE,
    CommandType.RESUME_CAMPAIGN,
    CommandType.WHAT_LAST,
    # ── v2 continuous loop action commands ─────────────────────────────────────
    CommandType.START_CONTINUOUS,
    CommandType.APPROVE_CANDIDATE,
    CommandType.REJECT_CANDIDATE,
    CommandType.HOLD_QUEUED,
})


# ── Public API ────────────────────────────────────────────────────────────────

def execute_ui_command(
    text: str,
    all_campaigns: list,
    resumable: list,
    rec_path: str,
    b_action_state: str,
    last_completed_action: str = "",
    apply_candidate_fn: Optional[Callable[[str], dict]] = None,
) -> dict[str, Any]:
    """
    Parse and execute a Peter command from the UI command surface.

    Parameters
    ----------
    text                   Raw operator input.
    all_campaigns          All campaigns, newest-first (from list_campaigns()).
    resumable              Resumable campaigns, newest-first (from list_resumable_campaigns()).
                           Resume Safe picks resumable[0] — the most recent.
    rec_path               Current candidate record path (for apply / hold / resume_review).
    b_action_state         Belfort action state string (from belfort_action_state()).
    last_completed_action  From agent state (used by 'what happened last').
    apply_candidate_fn     Callable(rec_path) → dict — injected by dashboard to keep
                           HTTP calls out of this module. Required for APPLY_AND_CONTINUE.

    Returns
    -------
    dict with keys:
        ok           — bool
        message      — str, display to operator
        event_type   — str, "" means no event to log
        severity     — str, "" when event_type is ""
        extra        — dict, extra context for the event log
        command_type — str, echo of parsed command type value
    """
    if not text or not text.strip():
        return _blocked("unknown", "Empty command. Try 'help'.")

    cmd = parse_command(text.strip(), transport="cli", operator_id="ui")

    if cmd.type in _LOCAL_COMMANDS:
        return _dispatch_local(
            cmd, all_campaigns, resumable, rec_path,
            b_action_state, last_completed_action, apply_candidate_fn,
        )

    # Info commands: route through the peter router (reads disk artifacts, advisory)
    try:
        response = route(cmd)
        return {
            "ok":           response.ok,
            "message":      response.to_chat_text(),
            "event_type":   "",
            "severity":     "",
            "extra":        {},
            "command_type": cmd.type.value,
        }
    except Exception as exc:
        return _err(cmd.type.value, f"Handler error: {exc}")


# ── Local dispatch ────────────────────────────────────────────────────────────

def _dispatch_local(
    cmd: Any,
    all_campaigns: list,
    resumable: list,
    rec_path: str,
    b_action_state: str,
    last_completed_action: str,
    apply_candidate_fn: Optional[Callable],
) -> dict[str, Any]:
    t = cmd.type
    if t == CommandType.START_AUTO:
        return _handle_start_auto(all_campaigns, b_action_state)
    if t == CommandType.STOP_CAMPAIGN:
        return _handle_stop(b_action_state)
    if t == CommandType.CANCEL_STOP:
        return _handle_cancel_stop(b_action_state)
    if t == CommandType.HOLD_REVIEW:
        return _handle_hold_review(rec_path, b_action_state)
    if t == CommandType.RESUME_REVIEW:
        return _handle_resume_review(rec_path, b_action_state)
    if t == CommandType.APPLY_AND_CONTINUE:
        return _handle_apply_and_continue(
            all_campaigns, resumable, rec_path, b_action_state, apply_candidate_fn,
        )
    if t == CommandType.RESUME_CAMPAIGN:
        return _handle_resume_safe(cmd, resumable)
    if t == CommandType.WHAT_LAST:
        return _handle_what_last(last_completed_action)
    if t == CommandType.START_CONTINUOUS:
        return _handle_start_continuous()
    if t == CommandType.APPROVE_CANDIDATE:
        return _handle_queue_action(cmd, "approved")
    if t == CommandType.REJECT_CANDIDATE:
        return _handle_queue_action(cmd, "rejected")
    if t == CommandType.HOLD_QUEUED:
        return _handle_queue_action(cmd, "held")
    return _blocked(t.value, f"No local handler for {t.value!r}. Try 'help'.")


# ── Action handlers ───────────────────────────────────────────────────────────

def _handle_start_auto(all_campaigns: list, b_action_state: str) -> dict[str, Any]:
    # Blocked states — operator must resolve the condition first
    if b_action_state == "running":
        return _blocked(
            "start_auto",
            "Mr Belfort is already running. "
            "Send 'stop' when you want to halt after the current session.",
        )
    if b_action_state == "stop_pending":
        return _blocked(
            "start_auto",
            "A stop signal is in flight. Wait for it to complete, "
            "or send 'cancel stop' to keep the current campaign running.",
        )
    if b_action_state == "waiting_for_review":
        return _blocked(
            "start_auto",
            "A candidate is waiting for your review. "
            "Apply, skip, or hold it before starting a new campaign.",
        )
    if b_action_state == "review_held":
        return _blocked(
            "start_auto",
            "A deferred review is still pending. "
            "Resume or dismiss the held candidate before starting a new campaign.",
        )

    goal = auto_continue_goal(all_campaigns)
    r    = start_campaign(goal=goal)

    if r.get("ok"):
        return {
            "ok":           True,
            "message":      f"Research campaign started.\nGoal: {goal}\n{r.get('message', '')}",
            "event_type":   "campaign_started",
            "severity":     "important",
            "extra":        {"goal": goal, "auto": True},
            "command_type": "start_auto",
        }
    return {
        "ok":           False,
        "message":      f"Could not start campaign: {r.get('message', '?')}",
        "event_type":   "campaign_start_failed",
        "severity":     "important",
        "extra":        {"goal": goal},
        "command_type": "start_auto",
    }


def _handle_stop(b_action_state: str) -> dict[str, Any]:
    if b_action_state == "stop_pending":
        return _blocked(
            "stop_campaign",
            "Stop signal already pending. "
            "Send 'cancel stop' to continue the campaign instead.",
        )
    if b_action_state != "running":
        return _blocked("stop_campaign", "No campaign is currently running.")

    r = request_stop()
    if r.get("ok"):
        return {
            "ok":           True,
            "message":      r.get("message", "Stop signal sent."),
            "event_type":   "stop_requested",
            "severity":     "important",
            "extra":        {},
            "command_type": "stop_campaign",
        }
    return _err("stop_campaign", r.get("message", "Could not send stop signal."))


def _handle_cancel_stop(b_action_state: str) -> dict[str, Any]:
    if b_action_state != "stop_pending":
        return _blocked("cancel_stop", "No stop signal is currently pending.")

    r = cancel_stop_signal()
    if r.get("ok"):
        return {
            "ok":           True,
            "message":      r.get("message", "Stop signal cancelled — campaign will continue."),
            "event_type":   "stop_cancelled",
            "severity":     "routine",
            "extra":        {},
            "command_type": "cancel_stop",
        }
    return _err("cancel_stop", r.get("message", "Could not cancel stop signal."))


def _handle_hold_review(rec_path: str, b_action_state: str) -> dict[str, Any]:
    if b_action_state != "waiting_for_review":
        return _blocked("hold_review", "No candidate is currently waiting for review.")

    hold_review(rec_path)
    return {
        "ok":           True,
        "message":      "Review deferred — candidate held. Send 'resume review' to return to it.",
        "event_type":   "review_held",
        "severity":     "action_needed",
        "extra":        {},
        "command_type": "hold_review",
    }


def _handle_resume_review(rec_path: str, b_action_state: str) -> dict[str, Any]:
    if b_action_state != "review_held":
        return _blocked("resume_review", "No deferred review is currently pending.")

    resume_review(rec_path)
    return {
        "ok":           True,
        "message":      "Review resumed — candidate is ready for your decision.",
        "event_type":   "review_resumed",
        "severity":     "routine",
        "extra":        {},
        "command_type": "resume_review",
    }


def _handle_apply_and_continue(
    all_campaigns: list,
    resumable: list,
    rec_path: str,
    b_action_state: str,
    apply_candidate_fn: Optional[Callable],
) -> dict[str, Any]:
    if b_action_state != "waiting_for_review":
        return _blocked("apply_and_continue", "No candidate is currently waiting for review.")
    if not rec_path:
        return _blocked(
            "apply_and_continue",
            "No candidate record path found. Check the Belfort tab for the pending review.",
        )
    if apply_candidate_fn is None:
        return _blocked("apply_and_continue", "Apply function not available in this context.")

    apply_r = apply_candidate_fn(rec_path)
    if "error" in apply_r:
        return _err("apply_and_continue", f"Apply failed: {apply_r['error']}")

    exp_name = apply_r.get("experiment_name", "?")

    # Determine continue action.
    # resumable is newest-first; index 0 is the most recent interrupted campaign.
    if resumable:
        next_id     = resumable[0].get("campaign_id", "")
        cr          = resume_campaign(next_id)
        action_word = "resumed"
    else:
        goal        = auto_continue_goal(all_campaigns)
        cr          = start_campaign(goal=goal)
        action_word = "started"

    if cr.get("ok"):
        return {
            "ok":           True,
            "message":      f"Applied {exp_name} · {action_word} next research run.",
            "event_type":   "candidate_applied_and_continued",
            "severity":     "important",
            "extra":        {"experiment_name": exp_name, "continue_action": action_word},
            "command_type": "apply_and_continue",
        }
    return {
        "ok":           False,
        "message":      (
            f"Applied {exp_name} — but could not {action_word} next run: "
            f"{cr.get('message', '?')}"
        ),
        "event_type":   "candidate_applied_continue_failed",
        "severity":     "important",
        "extra":        {"experiment_name": exp_name},
        "command_type": "apply_and_continue",
    }


def _handle_resume_safe(cmd: Any, resumable: list) -> dict[str, Any]:
    """
    Resume a campaign.

    If the command carries an explicit campaign_id (e.g. 'resume campaign c123'),
    that ID is used. Otherwise picks the most recent resumable campaign.

    resumable is newest-first (sorted by created_at descending, from
    list_resumable_campaigns() → list_campaigns()). Most recent = index 0.
    """
    explicit_id = (cmd.args.get("campaign_id") or "").strip()

    if explicit_id:
        campaign_id = explicit_id
    elif resumable:
        campaign_id = resumable[0].get("campaign_id", "")  # most recent = index 0
    else:
        campaign_id = ""

    if not campaign_id:
        return _blocked(
            "resume_campaign",
            "No interrupted campaigns to resume. Start a new campaign instead.",
        )

    r = resume_campaign(campaign_id)
    if r.get("ok"):
        return {
            "ok":           True,
            "message":      r.get("message", f"Resuming {campaign_id}."),
            "event_type":   "campaign_resumed",
            "severity":     "important",
            "extra":        {"campaign_id": campaign_id},
            "command_type": "resume_campaign",
        }
    return {
        "ok":           False,
        "message":      f"Could not resume {campaign_id!r}: {r.get('message', '?')}",
        "event_type":   "campaign_resume_failed",
        "severity":     "important",
        "extra":        {"campaign_id": campaign_id},
        "command_type": "resume_campaign",
    }


# ── v2 continuous loop action handlers ───────────────────────────────────────

def _handle_start_continuous() -> dict[str, Any]:
    """Enable the continuous learning loop."""
    try:
        from app.supervisor import enable_continuous, start_supervisor
        result = enable_continuous()
        if result.get("ok"):
            start_supervisor()
    except Exception as exc:
        return _err("start_continuous", f"Failed to enable loop: {exc}")

    return {
        "ok":           result.get("ok", False),
        "message":      result.get("message", ""),
        "event_type":   "continuous_learning_enabled" if result.get("ok") else "",
        "severity":     "important" if result.get("ok") else "",
        "extra":        {},
        "command_type": "start_continuous",
    }


def _handle_queue_action(cmd: Any, target_status: str) -> dict[str, Any]:
    """Approve (and apply), reject, or hold a candidate in the upgrade queue."""
    queue_id = (cmd.args.get("queue_id") or "").strip()

    try:
        from research.candidate_queue import (
            pending_candidates,
            get_queue_item,
            update_queue_item,
        )
        from datetime import datetime, timezone
        from observability.event_log import append_event

        # Find item
        if not queue_id:
            pending = pending_candidates()
            if not pending:
                return _blocked(
                    target_status,
                    "No pending candidates in the upgrade queue.",
                )
            item = pending[0]
            queue_id = item["queue_id"]
        else:
            item = get_queue_item(queue_id)
            if item is None:
                return _err(target_status, f"Queue item '{queue_id}' not found.")

        # Validate transition
        if target_status in ("approved", "rejected") and item.get("status") not in ("pending", "held"):
            return _err(target_status, f"Cannot {target_status} item with status '{item.get('status')}'.")
        if target_status == "held" and item.get("status") != "pending":
            return _err(target_status, f"Can only hold 'pending' items (current: '{item.get('status')}').")

        exp_id = item.get("experiment_id", "?")
        title  = item.get("title", exp_id)
        event_type = f"candidate_{target_status}"

        if target_status == "approved":
            # Apply first — only mark approved if apply succeeds.
            rec_path = (item.get("record_path") or "").strip()
            if not rec_path:
                return _err("approved", f"No record_path on queue item '{queue_id}' — cannot apply.")
            try:
                from app.strategy.applier import promote_from_record
                promote_result = promote_from_record(
                    rec_path,
                    reason=f"Approved by {cmd.operator_id}",
                )
            except Exception as apply_exc:
                # Apply failed — do not touch queue state.
                return _err("approved", f"Apply failed: {apply_exc}")

            # Apply succeeded — now persist the approval.
            update_queue_item(
                queue_id,
                status="approved",
                resolved_at=datetime.now(timezone.utc).isoformat(),
                resolution=f"Approved and applied by {cmd.operator_id}",
            )
            append_event(
                event_type,
                f"Operator approved and applied candidate {exp_id} (queue_id={queue_id}).",
                "important",
                source=cmd.operator_id,
                campaign_id=item.get("campaign_id"),
            )
            exp_name = promote_result.get("experiment_name", exp_id)
            changed  = promote_result.get("changed", {})
            return {
                "ok":           True,
                "message":      (
                    f"Applied: {title}. {len(changed)} param(s) updated "
                    f"({exp_name}). Strategy config updated."
                ),
                "event_type":   event_type,
                "severity":     "important",
                "extra":        {"queue_id": queue_id, "changed": changed, "experiment_name": exp_name},
                "command_type": "approve_candidate",
            }

        # reject or held — no apply step
        fields: dict[str, Any] = {"status": target_status}
        if target_status == "rejected":
            fields["resolved_at"] = datetime.now(timezone.utc).isoformat()
            fields["resolution"]  = f"Rejected by {cmd.operator_id}"
        else:
            fields["resolution"] = f"Deferred by {cmd.operator_id}"

        update_queue_item(queue_id, **fields)

        if target_status != "held":
            append_event(
                event_type,
                f"Operator {target_status} candidate {exp_id} (queue_id={queue_id}).",
                "important",
                source=cmd.operator_id,
                campaign_id=item.get("campaign_id"),
            )

    except Exception as exc:
        return _err(target_status, f"Failed to {target_status}: {exc}")

    if target_status == "rejected":
        return {
            "ok":           True,
            "message":      f"Rejected: {title}. Candidate will not be applied.",
            "event_type":   event_type,
            "severity":     "important",
            "extra":        {"queue_id": queue_id},
            "command_type": "reject_candidate",
        }
    else:  # held
        return {
            "ok":           True,
            "message":      f"Deferred: {title}. The loop continues — candidate stays in the queue.",
            "event_type":   "",
            "severity":     "",
            "extra":        {"queue_id": queue_id},
            "command_type": "hold_queued",
        }


# ── Info handler: what happened last ─────────────────────────────────────────

def _handle_what_last(last_completed_action: str) -> dict[str, Any]:
    """
    Answer 'what happened last' from:
      - last_completed_action from agent state  (most recent single action)
      - read_recent_events() from the event log (same source as Peter Inbox)

    This is intentionally LOCAL — never routes through peter.handlers.handle_explain_result,
    which reads batch/session report files and may diverge from the inbox.
    """
    lines: list[str] = []

    if last_completed_action:
        lines.append(f"Last action: {last_completed_action}")

    events = _read_events(limit=5)

    if events:
        if lines:
            lines.append("")
        lines.append("Recent events (newest first):")
        for ev in events:
            etype   = ev.get("event_type", "").replace("_", " ")
            summary = ev.get("summary", "")
            lines.append(f"  \u2022 {etype} \u2014 {summary}")

    if not lines:
        return {
            "ok":           True,
            "message":      "No recent activity recorded yet.",
            "event_type":   "",
            "severity":     "",
            "extra":        {},
            "command_type": "what_last",
        }

    return {
        "ok":           True,
        "message":      "\n".join(lines),
        "event_type":   "",
        "severity":     "",
        "extra":        {},
        "command_type": "what_last",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _blocked(command_type: str, reason: str) -> dict[str, Any]:
    return {
        "ok":           False,
        "message":      reason,
        "event_type":   "",
        "severity":     "",
        "extra":        {},
        "command_type": command_type,
    }


def _err(command_type: str, reason: str) -> dict[str, Any]:
    return {
        "ok":           False,
        "message":      f"Error: {reason}",
        "event_type":   "",
        "severity":     "",
        "extra":        {},
        "command_type": command_type,
    }
