# app/order_ledger.py
#
# Append-only order lifecycle ledger for THE ABODE.
#
# Every order event — intent, placement, ack, reject, fill, partial fill,
# cancel, expire — gets one JSONL record. Records are never modified in place.
# Corrections are new records with corrected=True referencing the original.
#
# Storage: data/orders/YYYY-MM-DD.jsonl  (one file per trading day, UTC date)
#
# Public API:
#   append(event_type, order_id, environment, **fields) → dict
#   replay(date_from, date_to)  → list[dict]  (all events in range, sorted)
#   get_today_count(environment)  → int
#   get_open_orders(environment)  → list[dict]  (orders placed but not final)

from __future__ import annotations

import json
import pathlib
from datetime import datetime, date, timezone
from typing import Any, Literal

_ROOT     = pathlib.Path(__file__).resolve().parent.parent
_ORDERS   = _ROOT / "data" / "orders"

# ── Event types ───────────────────────────────────────────────────────────────

EventType = Literal[
    "intent",           # decision to trade — not yet sent to broker
    "placed",           # sent to broker
    "ack",              # broker acknowledged
    "reject",           # broker rejected
    "partial_fill",     # partial execution
    "fill",             # fully executed
    "cancel",           # cancelled (by us or broker)
    "expired",          # time-in-force expired
    "override",         # overlay flagged a realism issue
    "reconcile_ok",     # reconciliation passed for this order
    "reconcile_fail",   # reconciliation mismatch for this order
    "correction",       # correction to a prior record
    "kill_switch",      # order cancelled by kill switch
]

Environment = Literal["paper", "shadow", "live"]

# Final states — orders in these states are not "open"
_FINAL_STATES = frozenset({"reject", "fill", "cancel", "expired", "kill_switch"})


def _today_path() -> pathlib.Path:
    today = date.today().isoformat()
    return _ORDERS / f"{today}.jsonl"


def _date_path(d: str) -> pathlib.Path:
    return _ORDERS / f"{d}.jsonl"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Write ──────────────────────────────────────────────────────────────────────

def append(
    event_type:     EventType,
    order_id:       str,
    environment:    Environment,
    *,
    symbol:         str        = "",
    side:           str        = "",          # "buy" | "sell"
    qty:            float      = 0.0,
    order_type:     str        = "",          # "market" | "limit"
    limit_price:    float | None = None,
    broker_fill_price:    float | None = None,
    overlay_fill_price:   float | None = None,
    cost_estimate:        dict | None  = None,
    data_lane:            str  = "UNKNOWN",
    session_type:         str  = "unknown",
    overlay_warnings:     list[str] | None = None,
    rationale:            str  = "",
    reject_reason:        str  = "",
    corrects_record_id:   str  = "",           # for correction events
    corrected:            bool = False,
    extra:                dict[str, Any] | None = None,
) -> dict:
    """
    Append one order lifecycle event and return the record.
    Thread-safe via file append (OS-level).
    Never raises — write errors are swallowed.
    """
    record: dict[str, Any] = {
        "timestamp_utc":      _ts(),
        "event_type":         event_type,
        "order_id":           order_id,
        "environment":        environment,
        "symbol":             symbol,
        "side":               side,
        "qty":                qty,
        "order_type":         order_type,
        "limit_price":        limit_price,
        "broker_fill_price":  broker_fill_price,
        "overlay_fill_price": overlay_fill_price,
        "cost_estimate":      cost_estimate,
        "data_lane":          data_lane,
        "session_type":       session_type,
        "overlay_warnings":   overlay_warnings or [],
        "rationale":          rationale,
        "reject_reason":      reject_reason,
        "corrected":          corrected,
        "corrects_record_id": corrects_record_id,
        **(extra or {}),
    }
    try:
        _ORDERS.mkdir(parents=True, exist_ok=True)
        path = _today_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass  # best-effort; never block the caller
    return record


# ── Read / Replay ──────────────────────────────────────────────────────────────

def _read_file(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def replay(
    date_from: str | None = None,
    date_to:   str | None = None,
    environment: Environment | None = None,
) -> list[dict]:
    """
    Return all order events within the date range [date_from, date_to] (inclusive).
    Dates are "YYYY-MM-DD" strings. If omitted, uses today only.
    Results are sorted by timestamp_utc ascending.
    """
    if not _ORDERS.exists():
        return []

    if date_from is None and date_to is None:
        files = [_today_path()]
    else:
        from_d = date.fromisoformat(date_from) if date_from else date.today()
        to_d   = date.fromisoformat(date_to)   if date_to   else date.today()
        files  = []
        cur    = from_d
        from datetime import timedelta
        while cur <= to_d:
            files.append(_date_path(cur.isoformat()))
            cur += timedelta(days=1)

    records = []
    for f in files:
        records.extend(_read_file(f))

    if environment:
        records = [r for r in records if r.get("environment") == environment]

    records.sort(key=lambda r: r.get("timestamp_utc", ""))
    return records


def get_today_count(environment: Environment | None = None) -> int:
    """Return number of order events logged today."""
    records = _read_file(_today_path())
    if environment:
        records = [r for r in records if r.get("environment") == environment]
    # Count only placed events (not intents or meta events)
    return sum(1 for r in records if r.get("event_type") == "placed")


def get_open_orders(environment: Environment | None = None) -> list[dict]:
    """
    Return orders that have been placed but not yet reached a final state.
    Uses today's ledger only (intraday open orders).
    """
    records = _read_file(_today_path())
    if environment:
        records = [r for r in records if r.get("environment") == environment]

    # Build latest event per order_id
    latest: dict[str, dict] = {}
    for r in records:
        oid = r.get("order_id", "")
        if oid:
            latest[oid] = r

    return [r for r in latest.values() if r.get("event_type") not in _FINAL_STATES]


def get_today_summary(environment: Environment | None = None) -> dict:
    """Summary stats for today's order activity."""
    records = _read_file(_today_path())
    if environment:
        records = [r for r in records if r.get("environment") == environment]

    fills       = [r for r in records if r.get("event_type") == "fill"]
    rejects     = [r for r in records if r.get("event_type") == "reject"]
    warnings    = [w for r in records for w in r.get("overlay_warnings", [])]
    placed      = [r for r in records if r.get("event_type") == "placed"]

    return {
        "orders_placed":   len(placed),
        "fills":           len(fills),
        "rejects":         len(rejects),
        "fill_rate_pct":   round(len(fills) / len(placed) * 100, 1) if placed else 0.0,
        "overlay_warnings": len(warnings),
        "open_orders":     len(get_open_orders(environment)),
        "environment":     environment or "all",
    }
