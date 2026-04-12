# app/belfort_paper_exec.py
#
# Paper execution layer — connects signal evaluation output to Alpaca paper orders.
#
# Execution gates (all must pass):
#   1. mode == "paper"
#   2. session_type == "regular"
#   3. signal_action == "buy"          (sell requires position tracking — future block)
#   4. risk_can_proceed == True
#   5. signal_qty > 0
#   6. signal_limit_price > 0
#
# Invariants:
#   paper_only = True          (always — no live execution)
#   was_submitted_to_broker    (True only if broker accepted the order)
#
# All executions (attempted or gated) are logged to data/belfort/paper_exec_log.jsonl.
# No hidden retries. All failures are recorded.
#
# Public API:
#   execute_paper_signal(signal_record) → dict   (execution record)

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

_ROOT          = pathlib.Path(__file__).resolve().parent.parent
_PAPER_EXEC_LOG = _ROOT / "data" / "belfort" / "paper_exec_log.jsonl"


def execute_paper_signal(signal_record: dict) -> dict:
    """
    Attempt to execute a paper order based on an evaluated signal record.

    signal_record is a dict from evaluate_signal() in belfort_signal_eval.py.

    Returns the full execution record (always logged).
    Never raises.
    """
    now_str = datetime.now(timezone.utc).isoformat()

    # ── Gate checks ──────────────────────────────────────────────────────────
    gate_block = _check_gates(signal_record)
    if gate_block:
        record = _build_record(
            now_str          = now_str,
            signal_record    = signal_record,
            gate_passed      = False,
            gate_block_reason = gate_block,
            was_submitted    = False,
            broker_order_id  = "",
            broker_client_oid = "",
            broker_status    = "",
            broker_error     = "",
            submission_error = "",
            exec_status      = "gated",
        )
        _write_exec_record(record)
        return record

    # ── Broker submission ─────────────────────────────────────────────────────
    try:
        from app.belfort_broker import submit_paper_order
        result = submit_paper_order(
            symbol      = signal_record["symbol"],
            qty         = signal_record["signal_qty"],
            limit_price = signal_record["signal_limit_price"],
        )
    except Exception as exc:
        record = _build_record(
            now_str           = now_str,
            signal_record     = signal_record,
            gate_passed       = True,
            gate_block_reason = None,
            was_submitted     = False,
            broker_order_id   = "",
            broker_client_oid = "",
            broker_status     = "",
            broker_error      = "",
            submission_error  = f"Broker import/call raised: {exc}",
            exec_status       = "error",
        )
        _write_exec_record(record)
        return record

    record = _build_record(
        now_str           = now_str,
        signal_record     = signal_record,
        gate_passed       = True,
        gate_block_reason = None,
        was_submitted     = result.submitted,
        broker_order_id   = result.broker_order_id,
        broker_client_oid = result.broker_client_order_id,
        broker_status     = result.broker_status,
        broker_error      = result.broker_error,
        submission_error  = result.submission_error,
        exec_status       = "submitted" if result.submitted else "broker_error",
    )
    _write_exec_record(record)
    return record


# ── Internal helpers ──────────────────────────────────────────────────────────

def _check_gates(signal_record: dict) -> str | None:
    """
    Check all execution gates. Returns a human-readable block reason,
    or None if all gates pass.
    """
    mode = signal_record.get("mode", "")
    if mode != "paper":
        return f"mode={mode!r} — paper execution only in PAPER mode"

    session = signal_record.get("session_type", "")
    if session != "regular":
        return f"session={session!r} — paper execution only during regular session"

    action = signal_record.get("signal_action", "")
    if action == "hold":
        return "signal_action=hold — nothing to execute"

    if action == "sell":
        return (
            "signal_action=sell — sell orders require position tracking; "
            "deferred to BELFORT-PAPER-SELL-01"
        )

    if action not in ("buy",):
        return f"signal_action={action!r} — unknown action, cannot execute"

    if not signal_record.get("risk_can_proceed", False):
        reason = signal_record.get("risk_block_reason", "unknown risk block")
        return f"risk guardrail blocked: {reason}"

    qty = signal_record.get("signal_qty", 0)
    if qty <= 0:
        return f"signal_qty={qty} — must be > 0"

    price = signal_record.get("signal_limit_price", 0.0)
    if price <= 0:
        return f"signal_limit_price={price} — must be > 0"

    return None  # all gates passed


def _build_record(
    now_str:           str,
    signal_record:     dict,
    gate_passed:       bool,
    gate_block_reason: str | None,
    was_submitted:     bool,
    broker_order_id:   str,
    broker_client_oid: str,
    broker_status:     str,
    broker_error:      str,
    submission_error:  str,
    exec_status:       str,
) -> dict:
    symbol    = signal_record.get("symbol", "UNKNOWN")
    action    = signal_record.get("signal_action", "?")
    qty       = signal_record.get("signal_qty", 0)
    price     = signal_record.get("signal_limit_price", 0.0)

    if was_submitted:
        exec_summary = (
            f"PAPER {action.upper()} {qty} {symbol} @ limit ${price:.2f} — "
            f"submitted to broker (id: {broker_order_id or '?'}). "
            "No real money."
        )
    elif gate_block_reason:
        exec_summary = f"PAPER execution gated: {gate_block_reason}. No order submitted."
    else:
        error_detail = broker_error or submission_error or "unknown error"
        exec_summary = (
            f"PAPER {action.upper()} {qty} {symbol} @ limit ${price:.2f} — "
            f"broker rejected: {error_detail}. No fill."
        )

    _session = signal_record.get("session_type", "unknown")
    return {
        "written_at":              now_str,
        "paper_only":              True,
        "signal_written_at":       signal_record.get("written_at", ""),
        "symbol":                  symbol,
        "mode":                    signal_record.get("mode", "paper"),
        "session_type":            _session,
        "market_regime":           "regular" if _session == "regular" else _session,
        "data_lane":               signal_record.get("data_lane", "UNKNOWN"),
        "action":                  action,
        "qty":                     qty,
        "order_type":              "limit",
        "limit_price":             price,
        "signal_rationale":        signal_record.get("signal_rationale", ""),
        "risk_checks_run":         signal_record.get("risk_checks_run", ""),
        "gate_passed":             gate_passed,
        "gate_block_reason":       gate_block_reason,
        "was_submitted_to_broker": was_submitted,
        "broker_order_id":         broker_order_id,
        "broker_client_order_id":  broker_client_oid,
        "broker_status":           broker_status,
        "broker_error":            broker_error,
        "submission_error":        submission_error,
        "execution_status":        exec_status,
        "exec_summary":            exec_summary,
    }


def _write_exec_record(record: dict) -> None:
    """Append an execution record to paper_exec_log.jsonl. Never raises."""
    try:
        _PAPER_EXEC_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _PAPER_EXEC_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass
