# app/belfort_paper_exec.py
#
# Paper execution layer — connects signal evaluation output to Alpaca paper orders.
#
# Execution gates (all must pass):
#   1. mode == "paper"
#   2. session_type in {"regular", "pre_market", "after_hours"}
#   3. signal_action in {"buy", "sell"} long-only paper path
#   4. risk_can_proceed == True
#   5. signal_qty > 0
#   6. signal_limit_price > 0
#   7. reconciliation halt not engaged
#
# Invariants:
#   paper_only = True          (always — no live execution)
#   was_submitted_to_broker    (True only if broker accepted the order)
#
# All executions (attempted or gated) are logged to data/belfort/paper_exec_log.jsonl.
# Submitted orders are also synced back from the paper broker so Belfort's
# local paper ledger can track real paper fills.
#
# Public API:
#   execute_paper_signal(signal_record) → dict   (execution record)
#   sync_paper_execution(max_orders=12, order_ids=None) → list[dict]

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

_ROOT          = pathlib.Path(__file__).resolve().parent.parent
_PAPER_EXEC_LOG = _ROOT / "data" / "belfort" / "paper_exec_log.jsonl"


def _parse_ts(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _approx_total_equity(snapshot: dict) -> float:
    positions = (snapshot or {}).get("positions") or {}
    invested_cost = 0.0
    for pos in positions.values():
        try:
            invested_cost += float(pos.get("avg_cost", 0.0) or 0.0) * float(pos.get("qty", 0.0) or 0.0)
        except Exception:
            continue
    cash = float((snapshot or {}).get("cash", 0.0) or 0.0)
    unrealized = float((snapshot or {}).get("unrealized_pnl", 0.0) or 0.0)
    equity = cash + invested_cost + unrealized
    return max(equity, cash)


def _position_exposure(snapshot: dict, symbol: str) -> float:
    positions = (snapshot or {}).get("positions") or {}
    pos = positions.get(symbol) or positions.get(str(symbol).upper()) or {}
    try:
        return float(pos.get("avg_cost", 0.0) or 0.0) * float(pos.get("qty", 0.0) or 0.0)
    except Exception:
        return 0.0


def _active_position_count(snapshot: dict) -> int:
    positions = (snapshot or {}).get("positions") or {}
    count = 0
    for pos in positions.values():
        try:
            if float(pos.get("qty", 0.0) or 0.0) > 0:
                count += 1
        except Exception:
            continue
    return count


def _book_exposure(snapshot: dict) -> float:
    positions = (snapshot or {}).get("positions") or {}
    total = 0.0
    for sym in positions.keys():
        total += _position_exposure(snapshot, str(sym).upper())
    return total


def _expected_edge_pct(signal_record: dict) -> float:
    setup = str(signal_record.get("setup_tag", "") or "").lower()
    relative_volume = float(signal_record.get("relative_volume", 0.0) or 0.0)
    gap_pct = abs(float(signal_record.get("gap_pct", 0.0) or 0.0))
    relative_strength = float(signal_record.get("relative_strength_vs_spy_pct", 0.0) or 0.0)
    base = 0.006
    if any(token in setup for token in ("breakout", "momentum", "trend", "news", "gap-and-go", "volume leader")):
        base = 0.012
    elif any(token in setup for token in ("mean reversion", "fade")):
        base = 0.008

    if relative_volume >= 3.0:
        base += 0.004
    elif relative_volume >= 1.5:
        base += 0.002
    elif relative_volume < 0.7:
        base -= 0.002

    if 0.02 <= gap_pct <= 0.12:
        base += 0.0015
    elif gap_pct >= 0.18:
        base -= 0.002

    if relative_strength >= 0.01:
        base += 0.0015
    elif relative_strength <= -0.006:
        base -= 0.0015

    return round(max(base, 0.003), 4)


def _recent_exec_attempts(symbol: str) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    global_last = None
    symbol_last = None
    try:
        for line in reversed(_PAPER_EXEC_LOG.read_text(encoding="utf-8").splitlines()[-240:]):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ts = _parse_ts(rec.get("written_at"))
            if ts is None or ts.date().isoformat() != today:
                continue
            if global_last is None:
                global_last = ts
            if symbol_last is None and str(rec.get("symbol", "")).upper() == symbol:
                symbol_last = ts
            if global_last and symbol_last:
                break
    except Exception:
        pass
    return {"global_last": global_last, "symbol_last": symbol_last}


def _recent_order_rate() -> dict:
    from app.order_ledger import replay

    now = datetime.now(timezone.utc)
    one_hour_ago = now.timestamp() - 3600
    global_recent = 0
    symbol_counts: dict[str, int] = {}
    try:
        for rec in replay(environment="paper"):
            if rec.get("event_type") != "placed":
                continue
            ts = _parse_ts(rec.get("timestamp_utc"))
            if ts is None or ts.timestamp() < one_hour_ago:
                continue
            global_recent += 1
            sym = str(rec.get("symbol", "")).upper()
            if sym:
                symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
    except Exception:
        pass
    return {"orders_last_hour": global_recent, "symbol_orders_last_hour": symbol_counts}


def paper_entry_policy_state(signal_record: dict | None = None) -> dict:
    """
    Compute Belfort's current paper-entry capacity and pacing state.

    This powers both operator-facing UI truth and buy-side execution gates.
    Current open positions are treated as grandfathered: they remain untouched,
    but new buys must respect the new desk limits.
    """
    from app.cost_engine import estimate
    from app.order_ledger import get_today_count, replay
    from app.portfolio import get_snapshot
    from app.strategy.config import get_config

    signal_record = signal_record or {}
    snapshot = get_snapshot()
    cfg = get_config()
    symbol = str(signal_record.get("symbol", "") or "").upper()
    side = str(signal_record.get("signal_action", "") or "").lower()
    qty = float(signal_record.get("signal_qty", 0) or 0)
    price = float(signal_record.get("signal_limit_price", 0.0) or 0.0)
    spread_pct = signal_record.get("observed_spread_pct")
    if spread_pct is None:
        spread_pct = signal_record.get("spread_pct")
    try:
        spread_pct = float(spread_pct) if spread_pct is not None else None
    except (TypeError, ValueError):
        spread_pct = None

    equity = _approx_total_equity(snapshot)
    total_exposure = _book_exposure(snapshot)
    symbol_exposure = _position_exposure(snapshot, symbol) if symbol else 0.0
    active_positions = _active_position_count(snapshot)

    def _cfg_num(key: str, default, cast):
        raw = cfg.get(key, None)
        if raw is None:
            raw = default
        return cast(raw)

    max_orders = _cfg_num("BELFORT_MAX_ORDERS_PER_DAY", 100, int)
    max_orders_per_hour = _cfg_num("BELFORT_MAX_ORDERS_PER_HOUR", 16, int)
    max_symbol_exposure_pct = _cfg_num("BELFORT_MAX_SYMBOL_EXPOSURE_PCT", 0.2, float)
    max_total_exposure_pct = _cfg_num("BELFORT_MAX_TOTAL_EXPOSURE_PCT", 0.65, float)
    max_active_positions = _cfg_num("BELFORT_MAX_ACTIVE_POSITIONS", 4, int)
    global_cooldown = _cfg_num("BELFORT_GLOBAL_COOLDOWN_SECONDS", 90, int)
    symbol_cooldown = _cfg_num("BELFORT_SYMBOL_COOLDOWN_SECONDS", 300, int)
    turnover_budget_pct = _cfg_num("BELFORT_TURNOVER_BUDGET_PCT", 2.0, float)
    edge_ratio_limit = _cfg_num("BELFORT_COST_EDGE_RATIO_LIMIT", 0.25, float)
    training_commission_per_order = _cfg_num("BELFORT_TRAINING_COMMISSION_PER_ORDER", 0.75, float)
    min_net_edge_pct = _cfg_num("BELFORT_MIN_NET_EDGE_PCT", 0.0035, float)

    max_symbol_exposure_usd = equity * max_symbol_exposure_pct
    max_total_exposure_usd = equity * max_total_exposure_pct
    remaining_exposure_capacity = max(0.0, max_total_exposure_usd - total_exposure)
    placed_today = int(get_today_count(environment="paper") or 0)
    remaining_daily_capacity = max(0, max_orders - placed_today)
    recent_order_rate = _recent_order_rate()
    orders_last_hour = int(recent_order_rate.get("orders_last_hour", 0) or 0)
    remaining_hourly_capacity = max(0, max_orders_per_hour - orders_last_hour)

    turnover_notional = 0.0
    try:
        for rec in replay(environment="paper"):
            if rec.get("event_type") != "placed":
                continue
            turnover_notional += float(rec.get("qty", 0.0) or 0.0) * float(rec.get("limit_price", 0.0) or 0.0)
    except Exception:
        pass
    turnover_budget_usd = equity * turnover_budget_pct
    turnover_remaining_usd = max(0.0, turnover_budget_usd - turnover_notional)

    recency = _recent_exec_attempts(symbol)
    now = datetime.now(timezone.utc)
    global_cooldown_remaining = max(
        0,
        global_cooldown - int((now - recency["global_last"]).total_seconds()),
    ) if recency["global_last"] else 0
    symbol_cooldown_remaining = max(
        0,
        symbol_cooldown - int((now - recency["symbol_last"]).total_seconds()),
    ) if recency["symbol_last"] else 0

    order_value = qty * price if qty > 0 and price > 0 else 0.0
    projected_symbol_exposure = symbol_exposure + (order_value if side == "buy" else 0.0)
    projected_total_exposure = total_exposure + (order_value if side == "buy" else 0.0)
    opens_new_name = side == "buy" and symbol and symbol_exposure <= 0.0

    cost_estimate = None
    cost_ratio = 0.0
    expected_edge_pct = _expected_edge_pct(signal_record)
    expected_edge_usd = order_value * expected_edge_pct if order_value > 0 else 0.0
    round_trip_cost_usd = 0.0
    net_expected_edge_usd = expected_edge_usd
    net_expected_edge_pct = expected_edge_pct
    if side == "buy" and qty > 0 and price > 0:
        try:
            cost_estimate = estimate(
                symbol=symbol or "SPY",
                side="buy",
                qty=qty,
                price=price,
                session_type=str(signal_record.get("session_type", "regular") or "regular"),
                data_lane=str(signal_record.get("data_lane", "UNKNOWN") or "UNKNOWN"),
                observed_spread_pct=spread_pct,
                order_type="limit",
            )
            principal = max(order_value, 0.0)
            if principal > 0:
                cost_ratio = float(cost_estimate.total_estimated_cost_usd or 0.0) / principal
                one_way_cost = float(cost_estimate.total_estimated_cost_usd or 0.0) + training_commission_per_order
                round_trip_cost_usd = max(0.0, one_way_cost * 2.0)
                net_expected_edge_usd = expected_edge_usd - round_trip_cost_usd
                net_expected_edge_pct = net_expected_edge_usd / principal
        except Exception:
            cost_estimate = None

    blocker = ""
    order_pacing_state = "open"
    if side == "buy":
        if remaining_daily_capacity <= 0:
            blocker = "Belfort has already used today's order capacity."
            order_pacing_state = "daily_capacity_used"
        elif remaining_hourly_capacity <= 0:
            blocker = "Belfort has already traded too much in the last hour and is slowing down to protect the day from fee-heavy churn."
            order_pacing_state = "hourly_capacity_used"
        elif global_cooldown_remaining > 0:
            blocker = f"Belfort just traded the desk and is pacing new entries for another {global_cooldown_remaining}s."
            order_pacing_state = "global_cooldown"
        elif symbol_cooldown_remaining > 0:
            blocker = f"Belfort traded {symbol or 'this name'} too recently and is waiting another {symbol_cooldown_remaining}s."
            order_pacing_state = "symbol_cooldown"
        elif turnover_remaining_usd <= 0:
            blocker = "Belfort has already used today's planned notional turnover budget."
            order_pacing_state = "turnover_budget_used"
        elif symbol_exposure >= max_symbol_exposure_usd and symbol_exposure > 0:
            blocker = f"Too much of the book is already in {symbol or 'this name'}."
            order_pacing_state = "symbol_concentration"
        elif projected_symbol_exposure > max_symbol_exposure_usd:
            blocker = f"This entry would make {symbol or 'this name'} too large a share of the book."
            order_pacing_state = "symbol_concentration"
        elif opens_new_name and active_positions >= max_active_positions:
            blocker = "The desk already has enough active names and will not add another one right now."
            order_pacing_state = "position_limit"
        elif total_exposure >= max_total_exposure_usd:
            blocker = "The desk is already fully deployed."
            order_pacing_state = "exposure_full"
        elif projected_total_exposure > max_total_exposure_usd:
            blocker = "This entry would use too much of the book's remaining buying power."
            order_pacing_state = "exposure_full"
        elif order_value > turnover_remaining_usd and turnover_remaining_usd > 0:
            blocker = "This entry would push Belfort past today's planned turnover budget."
            order_pacing_state = "turnover_budget_used"
        elif cost_estimate and expected_edge_pct > 0 and cost_ratio >= expected_edge_pct * edge_ratio_limit:
            blocker = "Skipping: spread and likely fees make this setup too expensive."
            order_pacing_state = "cost_dominant"
        elif cost_estimate and net_expected_edge_usd <= 0:
            blocker = "Skipping: likely slippage and brokerage fees would eat the whole setup."
            order_pacing_state = "net_edge_too_thin"
        elif cost_estimate and net_expected_edge_pct < min_net_edge_pct:
            blocker = "Skipping: expected profit after likely fees and slippage is still too thin."
            order_pacing_state = "net_edge_too_thin"

    return {
        "allowed": not blocker,
        "blocker": blocker,
        "order_pacing_state": order_pacing_state,
        "total_equity_usd": round(equity, 2),
        "total_exposure_usd": round(total_exposure, 2),
        "symbol_exposure_usd": round(symbol_exposure, 2),
        "projected_symbol_exposure_usd": round(projected_symbol_exposure, 2),
        "projected_total_exposure_usd": round(projected_total_exposure, 2),
        "max_symbol_exposure_usd": round(max_symbol_exposure_usd, 2),
        "max_total_exposure_usd": round(max_total_exposure_usd, 2),
        "remaining_exposure_capacity": round(remaining_exposure_capacity, 2),
        "active_positions": active_positions,
        "max_active_positions": max_active_positions,
        "daily_order_cap": max_orders,
        "hourly_order_cap": max_orders_per_hour,
        "orders_last_hour": orders_last_hour,
        "orders_placed_today": placed_today,
        "remaining_daily_capacity": remaining_daily_capacity,
        "remaining_hourly_capacity": remaining_hourly_capacity,
        "turnover_notional_usd": round(turnover_notional, 2),
        "turnover_budget_usd": round(turnover_budget_usd, 2),
        "turnover_remaining_usd": round(turnover_remaining_usd, 2),
        "global_cooldown_remaining": global_cooldown_remaining,
        "symbol_cooldown_remaining": symbol_cooldown_remaining,
        "cost_ratio": round(cost_ratio, 6),
        "expected_edge_pct": round(expected_edge_pct, 4),
        "expected_edge_usd": round(expected_edge_usd, 2),
        "training_commission_per_order": round(training_commission_per_order, 2),
        "round_trip_cost_usd": round(round_trip_cost_usd, 2),
        "net_expected_edge_usd": round(net_expected_edge_usd, 2),
        "net_expected_edge_pct": round(net_expected_edge_pct, 4),
        "cost_estimate": cost_estimate.to_dict() if cost_estimate else None,
    }


def execute_paper_signal(signal_record: dict) -> dict:
    """
    Attempt to execute a paper order based on an evaluated signal record.

    signal_record is a dict from evaluate_signal() in belfort_signal_eval.py.

    Returns the full execution record (always logged).
    Never raises.
    """
    try:
        sync_paper_execution(max_orders=8)
    except Exception:
        pass

    now_str = datetime.now(timezone.utc).isoformat()
    policy_state = paper_entry_policy_state(signal_record)

    # ── Gate checks ──────────────────────────────────────────────────────────
    gate_block = _check_gates(signal_record, policy_state=policy_state)
    if gate_block:
        record = _build_record(
            now_str          = now_str,
            signal_record    = signal_record,
            policy_state     = policy_state,
            gate_passed      = False,
            gate_block_reason = gate_block,
            was_submitted    = False,
            broker_order_id  = "",
            broker_client_oid = "",
            broker_status    = "",
            broker_fill_price = None,
            broker_updated_at = "",
            broker_error     = "",
            submission_error = "",
            filled_qty       = 0.0,
            portfolio_sync_status = "not_applicable",
            exec_status      = "gated",
        )
        _write_exec_record(record)
        return record

    action = str(signal_record.get("signal_action", "buy")).lower()
    qty = _submit_qty(signal_record)

    # ── Broker submission ─────────────────────────────────────────────────────
    try:
        from app.belfort_broker import submit_paper_order
        session = str(signal_record.get("session_type", "") or "")
        result = submit_paper_order(
            symbol      = signal_record["symbol"],
            qty         = qty,
            limit_price = signal_record["signal_limit_price"],
            side        = action,
            extended_hours = session in ("pre_market", "after_hours"),
        )
    except Exception as exc:
        record = _build_record(
            now_str           = now_str,
            signal_record     = signal_record,
            policy_state      = policy_state,
            gate_passed       = True,
            gate_block_reason = None,
            was_submitted     = False,
            broker_order_id   = "",
            broker_client_oid = "",
            broker_status     = "",
            broker_fill_price = None,
            broker_updated_at = "",
            broker_error      = "",
            submission_error  = f"Broker import/call raised: {exc}",
            filled_qty        = 0.0,
            portfolio_sync_status = "not_recorded",
            exec_status       = "error",
        )
        _write_exec_record(record)
        return record

    record = _build_record(
        now_str           = now_str,
        signal_record     = signal_record,
        policy_state      = policy_state,
        gate_passed       = True,
        gate_block_reason = None,
        was_submitted     = result.submitted,
        broker_order_id   = result.broker_order_id,
        broker_client_oid = result.broker_client_order_id,
        broker_status     = result.broker_status,
        broker_fill_price = None,
        broker_updated_at = "",
        broker_error      = result.broker_error,
        submission_error  = result.submission_error,
        filled_qty        = 0.0,
        portfolio_sync_status = "pending_broker_fill" if result.submitted else "not_recorded",
        exec_status       = "submitted" if result.submitted else "broker_error",
    )
    _write_exec_record(record)
    if result.submitted:
        _append_order_event("placed", record)
        try:
            sync_paper_execution(max_orders=4, order_ids=[result.broker_order_id])
        except Exception:
            pass
    return record


def flatten_paper_positions(reason: str = "Operator requested paper flatten.") -> dict:
    """
    Attempt to flatten all currently tracked paper positions through the same
    audited paper execution path Belfort already uses for normal sells.

    Returns a summary dict and never raises.
    """
    from app.market_time import session_type
    from app.market_data_feed import get_quote
    from app.belfort_broker import fetch_paper_positions
    from app.portfolio import get_snapshot

    broker_positions_snapshot = fetch_paper_positions()
    positions_source = "local_fallback"
    positions: dict[str, dict] = {}
    if broker_positions_snapshot.available:
        positions_source = "alpaca_broker"
        for pos in broker_positions_snapshot.positions:
            symbol = str(pos.symbol or "").upper().strip()
            if not symbol:
                continue
            try:
                qty = float(pos.qty or 0.0)
            except (TypeError, ValueError):
                qty = 0.0
            if qty <= 0:
                continue
            positions[symbol] = {
                "qty": qty,
                "avg_cost": float(pos.avg_cost or 0.0),
                "market_value": pos.market_value,
                "unrealized_pnl": pos.unrealized_pnl,
                "source": "broker",
            }
    else:
        snapshot = get_snapshot()
        positions = (snapshot.get("positions") or {})

    if not positions:
        return {
            "status": "already_flat",
            "submitted": 0,
            "gated": 0,
            "symbols": [],
            "message": (
                "There are no open Alpaca paper positions to close."
                if broker_positions_snapshot.available
                else "There are no open paper positions to close."
            ),
            "results": [],
            "positions_source": positions_source,
        }

    session = str(session_type() or "closed")
    if session not in ("regular", "pre_market", "after_hours"):
        open_symbols = [str(sym).upper() for sym in positions.keys()]
        return {
            "status": "blocked",
            "submitted": 0,
            "gated": len(open_symbols),
            "symbols": open_symbols,
            "message": "Could not close paper positions because no paper-tradeable session is open.",
            "results": [],
            "positions_source": positions_source,
        }

    results: list[dict] = []
    for symbol, pos in positions.items():
        sym = str(symbol or "").upper().strip()
        if not sym:
            continue
        try:
            qty = int(float((pos or {}).get("qty", 0) or 0))
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue

        quote = get_quote(sym)
        fallback_price = float((pos or {}).get("avg_cost", 0.0) or 0.0)
        limit_price = (
            float(quote.bid or 0.0)
            or float(quote.midpoint or 0.0)
            or float(quote.last or 0.0)
            or fallback_price
        )
        signal_record = {
            "written_at": datetime.now(timezone.utc).isoformat(),
            "symbol": sym,
            "mode": "paper",
            "session_type": session,
            "data_lane": getattr(quote, "data_lane", "UNKNOWN"),
            "signal_action": "sell",
            "signal_qty": qty,
            "signal_order_type": "marketable_limit",
            "signal_limit_price": float(limit_price),
            "signal_rationale": reason,
            "risk_can_proceed": True,
            "risk_block_reason": None,
            "risk_checks_run": "operator_flatten",
            "setup_tag": "operator flatten",
            "relative_strength_label": "",
            "tradeability_label": "eligible",
            "tradeability_reason": "Risk-reducing exit requested by the operator.",
            "paper_eligible": True,
            "observed_spread_pct": getattr(quote, "spread_pct", None),
        }
        results.append(execute_paper_signal(signal_record))

    submitted = sum(1 for row in results if row.get("was_submitted_to_broker"))
    gated = sum(1 for row in results if row.get("execution_status") == "gated")
    symbols = [str(row.get("symbol", "")).upper() for row in results if row.get("symbol")]
    status = "flatten_submitted" if submitted else ("blocked" if gated else "noop")
    message = (
        f"Close-all requested for {len(symbols)} open paper name(s). Submitted {submitted} exit order(s)."
        if submitted
        else (
            "Close-all was requested, but every exit was blocked."
            if gated
            else "No closeable paper positions were found."
        )
    )
    return {
        "status": status,
        "submitted": submitted,
        "gated": gated,
        "symbols": symbols,
        "message": message,
        "results": results,
        "positions_source": positions_source,
    }


def sync_paper_execution(
    max_orders: int = 12,
    order_ids: list[str] | None = None,
) -> list[dict]:
    """
    Poll open paper orders and record any broker-final outcomes back into
    Belfort's local paper ledger.

    This is paper-only and append-only:
      - order ledger gets final lifecycle events
      - paper_exec_log gets a synced outcome record
      - local paper portfolio records a trade only when the paper broker says
        the order is filled
    """
    try:
        from app.order_ledger import get_open_orders
    except Exception:
        return []

    open_orders = get_open_orders(environment="paper")
    wanted = {str(oid).strip() for oid in (order_ids or []) if str(oid).strip()}
    if wanted:
        open_orders = [rec for rec in open_orders if str(rec.get("order_id", "")).strip() in wanted]
    if max_orders > 0 and len(open_orders) > max_orders:
        open_orders = open_orders[-max_orders:]

    synced: list[dict] = []
    if not open_orders:
        return synced

    try:
        from app.belfort_broker import fetch_paper_order
    except Exception:
        return synced

    for open_order in open_orders:
        order_id = str(open_order.get("order_id", "")).strip()
        if not order_id:
            continue
        status = fetch_paper_order(order_id)
        if not status.submitted and not status.status:
            continue

        signal_record = _signal_from_order(open_order, status)
        normalized = str(status.status or "").strip().lower()
        latest_event_type = str(open_order.get("event_type", "") or "").strip().lower()
        if normalized in ("accepted", "new", "pending_new", "accepted_for_bidding"):
            if latest_event_type not in ("ack", "partial_fill", "fill", "cancel", "expired", "reject"):
                _append_order_event("ack", signal_record, status)
            continue
        if normalized == "partially_filled":
            qty = float(status.filled_qty or signal_record.get("signal_qty", 0) or 0)
            fill_price = status.fill_price or status.limit_price or float(signal_record.get("signal_limit_price", 0) or 0)
            if latest_event_type not in ("partial_fill", "fill", "cancel", "expired", "reject"):
                _append_order_event("partial_fill", signal_record, status, filled_qty=qty, fill_price=fill_price)
            continue

        side = str(signal_record.get("signal_action", "")).lower()
        qty = float(status.filled_qty or signal_record.get("signal_qty", 0) or 0)
        fill_price = status.fill_price or status.limit_price or float(signal_record.get("signal_limit_price", 0) or 0)

        portfolio_sync_status = "not_recorded"
        if normalized == "filled" and qty > 0 and fill_price > 0:
            portfolio_sync_status = _record_filled_trade(
                signal_record.get("symbol", "SPY"),
                side,
                qty,
                fill_price,
            )
            _append_order_event("fill", signal_record, status, filled_qty=qty, fill_price=fill_price)
            record = _build_record(
                now_str=datetime.now(timezone.utc).isoformat(),
                signal_record=signal_record,
                policy_state=paper_entry_policy_state(signal_record),
                gate_passed=True,
                gate_block_reason=None,
                was_submitted=True,
                broker_order_id=status.order_id or order_id,
                broker_client_oid=status.client_order_id,
                broker_status=status.status,
                broker_fill_price=fill_price,
                broker_updated_at=status.updated_at,
                broker_error=status.broker_error,
                submission_error=status.submission_error,
                filled_qty=qty,
                portfolio_sync_status=portfolio_sync_status,
                exec_status="filled",
            )
            _write_exec_record(record)
            synced.append(record)
            continue

        if normalized in ("rejected", "canceled", "cancelled", "expired"):
            event_type = {
                "rejected": "reject",
                "canceled": "cancel",
                "cancelled": "cancel",
                "expired": "expired",
            }.get(normalized, "reject")
            _append_order_event(event_type, signal_record, status, filled_qty=qty, fill_price=fill_price)
            record = _build_record(
                now_str=datetime.now(timezone.utc).isoformat(),
                signal_record=signal_record,
                policy_state=paper_entry_policy_state(signal_record),
                gate_passed=True,
                gate_block_reason=None,
                was_submitted=True,
                broker_order_id=status.order_id or order_id,
                broker_client_oid=status.client_order_id,
                broker_status=status.status,
                broker_fill_price=fill_price,
                broker_updated_at=status.updated_at,
                broker_error=status.broker_error,
                submission_error=status.submission_error,
                filled_qty=qty,
                portfolio_sync_status="not_recorded",
                exec_status="rejected" if event_type == "reject" else event_type,
            )
            _write_exec_record(record)
            synced.append(record)

    return synced


# ── Internal helpers ──────────────────────────────────────────────────────────

def _check_gates(signal_record: dict, *, policy_state: dict | None = None) -> str | None:
    """
    Check all execution gates. Returns a human-readable block reason,
    or None if all gates pass.
    """
    mode = signal_record.get("mode", "")
    if mode != "paper":
        return f"mode={mode!r} — paper execution only in PAPER mode"

    session = signal_record.get("session_type", "")
    if session not in ("regular", "pre_market", "after_hours"):
        return f"session={session!r} — no paper-tradeable session is open"

    try:
        from app.reconciler import is_halted
        if is_halted():
            return "reconciliation halt engaged — paper orders are blocked until positions match"
    except Exception:
        pass

    action = signal_record.get("signal_action", "")
    if action == "hold":
        return "Signal says hold — nothing to execute."

    if action == "sell":
        if _position_qty(signal_record.get("symbol", "")) <= 0:
            return f"No tracked paper position exists in {signal_record.get('symbol', 'UNKNOWN')} yet."
    elif action == "buy":
        try:
            from app.belfort_scanner import lookup_candidate

            candidate = lookup_candidate(str(signal_record.get("symbol", "")).upper())
        except Exception:
            candidate = None
        if not candidate:
            return f"No scanner tradeability context is ready yet for {signal_record.get('symbol', 'UNKNOWN')}."
        if not bool(candidate.get("paper_eligible")):
            reason = str(candidate.get("tradeability_reason", "") or "This name is not paper-eligible in Belfort's current phase.")
            return reason

    if action not in ("buy", "sell"):
        return f"Unknown signal action {action!r} — cannot execute."

    if not signal_record.get("risk_can_proceed", False):
        reason = signal_record.get("risk_block_reason", "unknown risk block")
        return f"Risk blocked the trade: {reason}"

    qty = signal_record.get("signal_qty", 0)
    if qty <= 0:
        return f"Signal size is invalid ({qty})."

    price = signal_record.get("signal_limit_price", 0.0)
    if price <= 0:
        return f"Signal price is invalid ({price})."

    if action == "buy":
        state = policy_state or paper_entry_policy_state(signal_record)
        if not bool(state.get("allowed", True)):
            return str(state.get("blocker", "") or "Brokerage-ready pacing blocked this entry.")

    return None  # all gates passed


def _position_qty(symbol: str) -> float:
    try:
        from app.portfolio import get_snapshot
        positions = (get_snapshot().get("positions") or {})
        pos = positions.get(symbol) or positions.get(str(symbol).upper()) or {}
        return float(pos.get("qty", 0.0) or 0.0)
    except Exception:
        return 0.0


def _submit_qty(signal_record: dict) -> int:
    qty = int(signal_record.get("signal_qty", 0) or 0)
    action = str(signal_record.get("signal_action", "")).lower()
    if action == "sell":
        held_qty = int(_position_qty(signal_record.get("symbol", "")) or 0)
        if held_qty > 0:
            return min(qty, held_qty)
    return qty


def _signal_from_order(open_order: dict, status) -> dict:
    symbol = str(status.symbol or open_order.get("symbol", "SPY")).upper()
    side = str(status.side or open_order.get("side", "buy")).lower()
    limit_price = status.limit_price
    if limit_price is None:
        try:
            limit_price = float(open_order.get("limit_price", 0) or 0)
        except (TypeError, ValueError):
            limit_price = 0.0
    return {
        "written_at": open_order.get("timestamp_utc", ""),
        "symbol": symbol,
        "mode": "paper",
        "session_type": open_order.get("session_type", "regular"),
        "data_lane": open_order.get("data_lane", "UNKNOWN"),
        "setup_tag": open_order.get("setup_tag", "monitor only"),
        "scanner_strategy_fit": open_order.get("scanner_strategy_fit"),
        "price_bucket": open_order.get("price_bucket"),
        "catalyst_type": open_order.get("catalyst_type"),
        "relative_strength_label": open_order.get("relative_strength_label"),
        "risk_flags": list(open_order.get("risk_flags") or []),
        "paper_eligible": bool(open_order.get("paper_eligible", False)),
        "tradeability_label": open_order.get("tradeability_label"),
        "tradeability_reason": open_order.get("tradeability_reason"),
        "signal_action": side,
        "signal_qty": int(status.qty or open_order.get("qty", 0) or 0),
        "signal_limit_price": float(limit_price or 0.0),
        "signal_rationale": open_order.get("rationale", ""),
        "risk_checks_run": "paper_order_sync",
    }


def _record_filled_trade(symbol: str, side: str, qty: float, price: float) -> str:
    try:
        from app.portfolio import record_trade, set_market_price
        set_market_price(str(symbol).upper(), float(price))
        record_trade(str(symbol).upper(), str(side).upper(), float(qty), float(price))
        return "recorded"
    except Exception as exc:
        return f"record_error: {exc}"


def _append_order_event(
    event_type: str,
    signal_record: dict,
    status=None,
    *,
    filled_qty: float = 0.0,
    fill_price: float | None = None,
) -> None:
    try:
        from app.order_ledger import append
    except Exception:
        return

    order_id = ""
    broker_fill_price = fill_price
    reject_reason = ""
    extra: dict = {}
    if status is not None:
        order_id = str(getattr(status, "order_id", "") or getattr(status, "client_order_id", "") or "")
        broker_fill_price = fill_price if fill_price is not None else getattr(status, "fill_price", None)
        extra = {
            "broker_status": getattr(status, "status", ""),
            "broker_order_id": getattr(status, "order_id", ""),
            "broker_client_order_id": getattr(status, "client_order_id", ""),
            "setup_tag": signal_record.get("setup_tag", "monitor only"),
            "scanner_strategy_fit": signal_record.get("scanner_strategy_fit"),
            "price_bucket": signal_record.get("price_bucket"),
            "catalyst_type": signal_record.get("catalyst_type"),
            "relative_strength_label": signal_record.get("relative_strength_label"),
            "risk_flags": list(signal_record.get("risk_flags") or []),
            "paper_eligible": bool(signal_record.get("paper_eligible", False)),
            "tradeability_label": signal_record.get("tradeability_label"),
            "tradeability_reason": signal_record.get("tradeability_reason"),
        }
        reject_reason = str(getattr(status, "broker_error", "") or getattr(status, "submission_error", "") or "")
    else:
        order_id = str(signal_record.get("broker_order_id", "") or signal_record.get("broker_client_order_id", "") or "")
        extra = {
            "setup_tag": signal_record.get("setup_tag", "monitor only"),
            "scanner_strategy_fit": signal_record.get("scanner_strategy_fit"),
            "price_bucket": signal_record.get("price_bucket"),
            "catalyst_type": signal_record.get("catalyst_type"),
            "relative_strength_label": signal_record.get("relative_strength_label"),
            "risk_flags": list(signal_record.get("risk_flags") or []),
            "paper_eligible": bool(signal_record.get("paper_eligible", False)),
            "tradeability_label": signal_record.get("tradeability_label"),
            "tradeability_reason": signal_record.get("tradeability_reason"),
        }

    if not order_id:
        return

    qty = filled_qty or float(signal_record.get("qty", 0) or signal_record.get("signal_qty", 0) or 0)
    try:
        append(
            event_type=event_type,  # type: ignore[arg-type]
            order_id=order_id,
            environment="paper",
            symbol=str(signal_record.get("symbol", "")).upper(),
            side=str(signal_record.get("action", "") or signal_record.get("signal_action", "") or "").lower(),
            qty=qty,
            order_type="limit",
            limit_price=float(signal_record.get("limit_price", 0) or signal_record.get("signal_limit_price", 0) or 0),
            broker_fill_price=broker_fill_price,
            data_lane=str(signal_record.get("data_lane", "UNKNOWN")),
            session_type=str(signal_record.get("session_type", "regular")),
            rationale=str(signal_record.get("signal_rationale", "") or signal_record.get("exec_summary", "") or ""),
            reject_reason=reject_reason,
            extra=extra,
        )
    except Exception:
        pass


def _build_record(
    now_str:           str,
    signal_record:     dict,
    policy_state:      dict | None,
    gate_passed:       bool,
    gate_block_reason: str | None,
    was_submitted:     bool,
    broker_order_id:   str,
    broker_client_oid: str,
    broker_status:     str,
    broker_fill_price: float | None,
    broker_updated_at: str,
    broker_error:      str,
    submission_error:  str,
    filled_qty:        float,
    portfolio_sync_status: str,
    exec_status:       str,
) -> dict:
    symbol    = signal_record.get("symbol", "UNKNOWN")
    action    = signal_record.get("signal_action", "?")
    qty       = signal_record.get("signal_qty", 0)
    price     = signal_record.get("signal_limit_price", 0.0)
    _session  = signal_record.get("session_type", "unknown")

    if exec_status == "filled":
        fill_label = f"${broker_fill_price:.2f}" if broker_fill_price is not None else "broker fill"
        exec_summary = (
            f"PAPER {action.upper()} {filled_qty:g} {symbol} filled @ {fill_label}. "
            f"Portfolio sync: {portfolio_sync_status}. No real money."
        )
    elif was_submitted:
        ext_label = " [extended hours]" if _session in ("pre_market", "after_hours") else ""
        exec_summary = (
            f"PAPER {action.upper()} {qty} {symbol} @ limit ${price:.2f} — "
            f"submitted to broker{ext_label} (id: {broker_order_id or '?'}). "
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

    return {
        "written_at":              now_str,
        "paper_only":              True,
        "signal_written_at":       signal_record.get("written_at", ""),
        "symbol":                  symbol,
        "mode":                    signal_record.get("mode", "paper"),
        "session_type":            _session,
        "market_regime":           "regular" if _session == "regular" else _session,
        "data_lane":               signal_record.get("data_lane", "UNKNOWN"),
        "setup_tag":               signal_record.get("setup_tag", "monitor only"),
        "scanner_strategy_fit":    signal_record.get("scanner_strategy_fit"),
        "price_bucket":            signal_record.get("price_bucket"),
        "catalyst_type":           signal_record.get("catalyst_type"),
        "relative_strength_label": signal_record.get("relative_strength_label"),
        "risk_flags":              list(signal_record.get("risk_flags") or []),
        "paper_eligible":          bool(signal_record.get("paper_eligible", False)),
        "tradeability_label":      signal_record.get("tradeability_label"),
        "tradeability_reason":     signal_record.get("tradeability_reason"),
        "order_pacing_state":      (policy_state or {}).get("order_pacing_state", ""),
        "remaining_daily_capacity": int((policy_state or {}).get("remaining_daily_capacity", 0) or 0),
        "remaining_hourly_capacity": int((policy_state or {}).get("remaining_hourly_capacity", 0) or 0),
        "remaining_exposure_capacity": float((policy_state or {}).get("remaining_exposure_capacity", 0.0) or 0.0),
        "symbol_exposure_usd":     float((policy_state or {}).get("symbol_exposure_usd", 0.0) or 0.0),
        "total_exposure_usd":      float((policy_state or {}).get("total_exposure_usd", 0.0) or 0.0),
        "active_positions":        int((policy_state or {}).get("active_positions", 0) or 0),
        "daily_order_cap":         int((policy_state or {}).get("daily_order_cap", 0) or 0),
        "hourly_order_cap":        int((policy_state or {}).get("hourly_order_cap", 0) or 0),
        "turnover_budget_usd":     float((policy_state or {}).get("turnover_budget_usd", 0.0) or 0.0),
        "turnover_remaining_usd":  float((policy_state or {}).get("turnover_remaining_usd", 0.0) or 0.0),
        "estimated_cost":          (policy_state or {}).get("cost_estimate"),
        "cost_ratio":              float((policy_state or {}).get("cost_ratio", 0.0) or 0.0),
        "expected_edge_usd":       float((policy_state or {}).get("expected_edge_usd", 0.0) or 0.0),
        "round_trip_cost_usd":     float((policy_state or {}).get("round_trip_cost_usd", 0.0) or 0.0),
        "net_expected_edge_usd":   float((policy_state or {}).get("net_expected_edge_usd", 0.0) or 0.0),
        "net_expected_edge_pct":   float((policy_state or {}).get("net_expected_edge_pct", 0.0) or 0.0),
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
        "broker_fill_price":       broker_fill_price,
        "broker_updated_at":       broker_updated_at,
        "broker_error":            broker_error,
        "submission_error":        submission_error,
        "filled_qty":              filled_qty,
        "portfolio_sync_status":   portfolio_sync_status,
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
