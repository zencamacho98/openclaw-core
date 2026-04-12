# app/kill_switch.py
#
# Operator kill switch for THE ABODE.
#
# A single `engage(reason)` call:
#   1. Cancels all open orders via the broker connector (if active)
#   2. Stops the trading loop
#   3. Sets Belfort's agent state to stopped_by_guardrail
#   4. Writes to the order ledger + event log
#   5. Sends Peter a plain-English alert
#
# Must be callable from: Peter command, API endpoint, and programmatically.
# Must be tested in paper mode before live mode is considered.
#
# Public API:
#   engage(reason, environment) → KillResult
#   get_status() → dict

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class KillResult:
    engaged:          bool
    reason:           str
    cancelled_orders: int       # number of open orders cancel-attempted
    cancel_errors:    list[str]
    timestamp_utc:    str


def engage(
    reason:      str = "operator_request",
    environment: str = "paper",            # "paper" | "live"
) -> KillResult:
    """
    Engage the kill switch.

    Safe to call multiple times — idempotent after first engagement.
    Never raises — all errors are captured in the result.
    """
    ts = datetime.now(timezone.utc).isoformat()
    cancelled  = 0
    errors: list[str] = []

    # 1. Cancel open orders via broker connector
    try:
        from app.broker_connector import get_connector
        connector = get_connector()
        if connector is not None:
            open_orders = connector.get_open_orders()
            for order in open_orders:
                oid = order.get("id") or order.get("order_id", "")
                try:
                    connector.cancel_order(oid)
                    cancelled += 1
                except Exception as exc:
                    errors.append(f"cancel {oid}: {exc}")
    except Exception as exc:
        errors.append(f"broker_connector unavailable: {exc}")

    # 2. Stop the trading loop
    try:
        from app import trading_loop
        trading_loop._running        = False
        trading_loop._stop_requested = False
    except Exception as exc:
        errors.append(f"trading_loop stop failed: {exc}")

    # 3. Update Belfort agent state
    try:
        from observability.agent_state import transition, MR_BELFORT, STATUS_STOPPED_GUARDRAIL
        transition(
            MR_BELFORT,
            status      = STATUS_STOPPED_GUARDRAIL,
            agent_role  = "trading_researcher",
            stop_reason = reason,
            last_completed_action = f"Kill switch engaged: {reason}",
        )
    except Exception as exc:
        errors.append(f"agent_state update failed: {exc}")

    # 4. Write to order ledger and event log
    try:
        from app.order_ledger import append
        append(
            event_type  = "kill_switch",
            order_id    = "KILL_SWITCH",
            environment = environment,  # type: ignore[arg-type]
            rationale   = reason,
            extra       = {
                "cancelled_orders": cancelled,
                "cancel_errors":    errors,
                "timestamp_utc":    ts,
            },
        )
    except Exception as exc:
        errors.append(f"order_ledger write failed: {exc}")

    try:
        from observability.event_log import append_event
        append_event(
            event_type = "kill_switch_engaged",
            summary    = f"Kill switch engaged ({environment}): {reason}. {cancelled} order(s) cancelled.",
            severity   = "action_needed",
            source     = "kill_switch",
        )
    except Exception as exc:
        errors.append(f"event_log write failed: {exc}")

    return KillResult(
        engaged          = True,
        reason           = reason,
        cancelled_orders = cancelled,
        cancel_errors    = errors,
        timestamp_utc    = ts,
    )


def get_status() -> dict:
    """Return current Belfort agent state relevant to kill-switch awareness."""
    try:
        from observability.agent_state import load_state, MR_BELFORT
        s = load_state(MR_BELFORT)
        return {
            "belfort_status":  s.status,
            "stop_reason":     s.stop_reason,
            "last_action":     s.last_completed_action,
            "last_heartbeat":  s.last_heartbeat_at,
        }
    except Exception as exc:
        return {"error": str(exc)}
