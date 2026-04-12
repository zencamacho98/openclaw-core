# peter/router.py
#
# Command dispatcher for Peter.
#
# route() is the single entry point for all transports.
# It performs the auth check then dispatches to the appropriate handler.
#
# Transport adapters (CLI, Discord, WhatsApp) call route() and receive a Response.
# They never call handlers directly — this lets auth and routing stay in one place.
#
# Public API:
#   route(command: Command) → Response

from __future__ import annotations

from peter.commands  import Command, CommandType
from peter.identity  import is_approved
from peter.responses import unauthorized_response
from peter.handlers  import (
    handle_status,
    handle_inspect_campaign,
    handle_best_candidate,
    handle_list_review_worthy,
    handle_promote_guidance,
    handle_explain_result,
    handle_run_campaign,
    handle_resume_campaign,
    handle_help,
    handle_unknown,
    handle_show_queue,
    handle_checker_findings,
    handle_custodian_health,
    handle_sentinel_status,
    handle_warden_status,
    handle_build_intent,
    handle_approve_build,
    handle_reject_build,
    handle_authorize_stage2,
    handle_draft_stage2,
    handle_promote_draft,
    handle_discard_draft,
    handle_fl_lifecycle_nl,
    handle_market_status,
    handle_market_readiness,
    handle_kill_trading,
    handle_belfort_status,
)

_DISPATCH: dict[CommandType, object] = {
    CommandType.STATUS:             handle_status,
    CommandType.INSPECT_CAMPAIGN:   handle_inspect_campaign,
    CommandType.BEST_CANDIDATE:     handle_best_candidate,
    CommandType.LIST_REVIEW_WORTHY: handle_list_review_worthy,
    CommandType.PROMOTE_GUIDANCE:   handle_promote_guidance,
    CommandType.EXPLAIN_RESULT:     handle_explain_result,
    CommandType.RUN_CAMPAIGN:       handle_run_campaign,
    CommandType.RESUME_CAMPAIGN:    handle_resume_campaign,
    CommandType.HELP:               handle_help,
    CommandType.UNKNOWN:            handle_unknown,
    # ── v2 info commands (read-only, handled via handlers) ────────────────────
    CommandType.SHOW_QUEUE:         handle_show_queue,
    CommandType.CHECKER_FINDINGS:   handle_checker_findings,
    CommandType.CUSTODIAN_HEALTH:   handle_custodian_health,
    CommandType.SENTINEL_STATUS:    handle_sentinel_status,
    CommandType.WARDEN_STATUS:      handle_warden_status,
    # Note: START_CONTINUOUS, APPROVE_CANDIDATE, REJECT_CANDIDATE, HOLD_QUEUED
    # are action commands handled locally in ui/peter_command.py — not here.
    CommandType.BUILD_INTENT:       handle_build_intent,
    # ── Frank Lloyd Stage 1 terminal gate ──────────────────────────────────────
    CommandType.APPROVE_BUILD:      handle_approve_build,
    CommandType.REJECT_BUILD:       handle_reject_build,
    # ── Frank Lloyd Stage 2 authorization gate ──────────────────────────────────
    CommandType.AUTHORIZE_STAGE2:   handle_authorize_stage2,
    # ── Frank Lloyd Stage 2 draft generation ────────────────────────────────────
    CommandType.DRAFT_STAGE2:       handle_draft_stage2,
    # ── Frank Lloyd Stage 2 draft promotion ──────────────────────────────────────
    CommandType.PROMOTE_DRAFT:      handle_promote_draft,
    # ── Frank Lloyd Stage 2 draft discard ────────────────────────────────────────
    CommandType.DISCARD_DRAFT:      handle_discard_draft,
    # ── Frank Lloyd conversational lifecycle ──────────────────────────────────────
    CommandType.FL_LIFECYCLE_NL:    handle_fl_lifecycle_nl,
    # ── Market layer ─────────────────────────────────────────────────────────────
    CommandType.MARKET_STATUS:      handle_market_status,
    CommandType.MARKET_READINESS:   handle_market_readiness,
    CommandType.KILL_TRADING:       handle_kill_trading,
    # ── Belfort mode/preflight ────────────────────────────────────────────────────
    CommandType.BELFORT_STATUS:     handle_belfort_status,
}


def route(command: Command) -> "Response":  # type: ignore[name-defined]
    """
    Authenticate and dispatch a Command to the correct handler.

    Steps:
      1. Check identity.json: is this (transport, operator_id) approved?
      2. If not approved, return an unauthorized_response immediately.
      3. Otherwise, look up the handler in _DISPATCH and call it.
      4. If no handler registered, fall back to handle_unknown.

    This is the only entry point transport adapters should use.
    """
    from peter.responses import Response

    if not is_approved(command.transport, command.operator_id, command.type.value):
        return unauthorized_response(
            command_type = command.type.value,
            transport    = command.transport,
            operator_id  = command.operator_id,
        )

    handler = _DISPATCH.get(command.type, handle_unknown)
    return handler(command)  # type: ignore[operator]
