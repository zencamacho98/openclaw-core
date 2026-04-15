# app/belfort_risk.py
#
# Belfort risk guardrail layer.
#
# Hard blocks, not advisory. Seven ordered checks.
# Every block is logged to the event journal (observability/event_log.py).
# Stateless between calls — no internal state maintained.
#
# Check order:
#   1. session_check       — market closed / unknown session → block
#   2. data_lane_check     — UNKNOWN lane → block
#   3. hold_passthrough    — hold signal passes without further checks
#   4. daily_loss_cap      — total realized P&L loss exceeds limit → block
#   5. daily_order_count   — too many orders today → block
#   6. position_size       — qty exceeds max per-order size → block
#   7. cash_sufficiency    — insufficient cash for buy → block
#
# Public API:
#   RiskCheckResult     — dataclass
#   RiskGuardrails      — class with check(signal, portfolio) → RiskCheckResult

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.belfort_strategy import BelfortSignal


@dataclass
class RiskCheckResult:
    """Result of running all risk guardrail checks on a signal."""
    passed:       bool
    block_reason: Optional[str]  # None if passed
    check_name:   str            # name of the blocking check, or "all_passed"
    signal:       BelfortSignal  # original signal (unchanged)


# ── Defaults ─────────────────────────────────────────────────────────────────

_DEFAULT_DAILY_LOSS_CAP    = 500.0   # max realized loss per day (absolute USD)
_DEFAULT_MAX_ORDERS_PER_DAY = 100    # config-backed backstop; pacing should bite first
_DEFAULT_MAX_QTY_PER_ORDER  = 100    # max shares per single order
_DEFAULT_MIN_CASH_BUFFER    = 100.0  # minimum cash to maintain after a buy


class RiskGuardrails:
    """
    Stateless risk guardrail layer.

    Parameters (all optional, use defaults if omitted):
        daily_loss_cap:      float  — max realized loss (USD) allowed in a day
        max_orders_per_day:  int    — max orders placed today
        max_qty_per_order:   int    — max qty per single order
        min_cash_buffer:     float  — minimum cash to maintain after buy

    Usage:
        guardrails = RiskGuardrails()
        result = guardrails.check(signal, portfolio)
        if not result.passed:
            # signal is blocked — do not execute
            ...
    """

    def __init__(
        self,
        daily_loss_cap:     float | None = _DEFAULT_DAILY_LOSS_CAP,
        max_orders_per_day: int | None   = None,
        max_qty_per_order:  int | None   = _DEFAULT_MAX_QTY_PER_ORDER,
        min_cash_buffer:    float | None = _DEFAULT_MIN_CASH_BUFFER,
    ) -> None:
        self._daily_loss_cap     = daily_loss_cap
        self._max_orders_per_day = max_orders_per_day
        self._max_qty_per_order  = max_qty_per_order
        self._min_cash_buffer    = min_cash_buffer

    def check(self, signal: BelfortSignal, portfolio: dict) -> RiskCheckResult:
        """
        Run all risk checks in order. Return on first block.

        portfolio dict expected keys (all optional — defaults to safe values):
            realized_pnl_today:   float  — realized P&L for today (negative = loss)
            orders_placed_today:  int    — count of orders placed today
            cash:                 float  — available cash
        """
        try:
            return self._run_checks(signal, portfolio)
        except Exception as exc:
            # Any unexpected error in guardrails → block, never pass through
            return self._block(
                signal,
                check_name   = "guardrail_error",
                block_reason = f"Risk guardrail raised an unexpected error: {exc}",
            )

    def _run_checks(self, signal: BelfortSignal, portfolio: dict) -> RiskCheckResult:
        from app.strategy.config import get_config

        cfg = get_config()
        daily_loss_cap = float(self._daily_loss_cap if self._daily_loss_cap is not None else cfg.get("DAILY_LOSS_CAP", _DEFAULT_DAILY_LOSS_CAP))
        max_orders_per_day = int(self._max_orders_per_day if self._max_orders_per_day is not None else cfg.get("BELFORT_MAX_ORDERS_PER_DAY", _DEFAULT_MAX_ORDERS_PER_DAY))
        max_qty_per_order = int(self._max_qty_per_order if self._max_qty_per_order is not None else cfg.get("MAX_QTY_PER_ORDER", _DEFAULT_MAX_QTY_PER_ORDER))
        min_cash_buffer = float(self._min_cash_buffer if self._min_cash_buffer is not None else cfg.get("MIN_CASH_BUFFER", _DEFAULT_MIN_CASH_BUFFER))

        # 1. session_check
        if signal.session_type not in ("regular", "pre_market", "after_hours"):
            return self._block(
                signal,
                check_name   = "session_check",
                block_reason = f"Paper-tradeable session is closed ({signal.session_type}) — order blocked",
            )

        # 2. data_lane_check
        if signal.data_lane == "UNKNOWN":
            return self._block(
                signal,
                check_name   = "data_lane_check",
                block_reason = "Data lane UNKNOWN — cannot verify quote quality; order blocked",
            )

        # 3. hold_passthrough — hold signals pass without further checks
        if signal.action == "hold":
            return RiskCheckResult(
                passed       = True,
                block_reason = None,
                check_name   = "hold_passthrough",
                signal       = signal,
            )

        # 4. daily_loss_cap
        realized_pnl = float(portfolio.get("realized_pnl_today", 0.0))
        if realized_pnl < 0 and abs(realized_pnl) >= daily_loss_cap:
            return self._block(
                signal,
                check_name   = "daily_loss_cap",
                block_reason = (
                    f"Daily loss cap reached: realized P&L today = ${realized_pnl:.2f}, "
                    f"cap = ${daily_loss_cap:.2f}"
                ),
            )

        # 5. daily_order_count
        orders_today = int(portfolio.get("orders_placed_today", 0))
        if orders_today >= max_orders_per_day:
            return self._block(
                signal,
                check_name   = "daily_order_count",
                block_reason = (
                    f"Max daily order count reached: {orders_today}/{max_orders_per_day}"
                ),
            )

        # 6. position_size
        if signal.qty > max_qty_per_order:
            return self._block(
                signal,
                check_name   = "position_size",
                block_reason = (
                    f"Order qty {signal.qty} exceeds max per-order size {max_qty_per_order}"
                ),
            )

        # 7. cash_sufficiency (buy only)
        if signal.action == "buy":
            cash        = float(portfolio.get("cash", 0.0))
            order_cost  = signal.limit_price * signal.qty
            required    = order_cost + min_cash_buffer
            if cash < required:
                return self._block(
                    signal,
                    check_name   = "cash_sufficiency",
                    block_reason = (
                        f"Insufficient cash: have ${cash:.2f}, "
                        f"need ${required:.2f} (order ${order_cost:.2f} + buffer ${min_cash_buffer:.2f})"
                    ),
                )

        # All checks passed
        _log_risk_event(signal, passed=True, check_name="all_passed", reason="")
        return RiskCheckResult(
            passed       = True,
            block_reason = None,
            check_name   = "all_passed",
            signal       = signal,
        )

    @staticmethod
    def _block(
        signal:       BelfortSignal,
        check_name:   str,
        block_reason: str,
    ) -> RiskCheckResult:
        _log_risk_event(signal, passed=False, check_name=check_name, reason=block_reason)
        return RiskCheckResult(
            passed       = False,
            block_reason = block_reason,
            check_name   = check_name,
            signal       = signal,
        )


# ── Event logging ─────────────────────────────────────────────────────────────

def _log_risk_event(
    signal:     BelfortSignal,
    passed:     bool,
    check_name: str,
    reason:     str,
) -> None:
    """Append a risk check event to the event journal. Never raises."""
    try:
        from observability.event_log import append_event
        append_event(
            event_type = "risk_check",
            agent      = "belfort_risk",
            summary    = (
                f"PASS [{check_name}] {signal.symbol} {signal.action}"
                if passed else
                f"BLOCK [{check_name}] {signal.symbol} {signal.action}: {reason}"
            ),
            severity   = "info" if passed else "warning",
        )
    except Exception:
        pass
