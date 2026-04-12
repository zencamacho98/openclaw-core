# observability/market_summary.py
#
# Market layer summary reader for THE ABODE.
#
# Reads from disk artifacts written by the market layer modules:
#   data/market_status.json       — written by market route on each request
#   data/readiness_scorecard.jsonl — written by readiness_scorecard.evaluate()
#   data/orders/YYYY-MM-DD.jsonl  — written by order_ledger.append()
#   data/reconciliation_log.jsonl — written by reconciler.run_reconciliation()
#
# This module is the observability-layer bridge between the market modules
# (app/market_*.py, app/cost_engine.py, etc.) and Peter's handlers.
# Handlers import from here — never directly from app/.
#
# Public API:
#   read_market_status()   → dict
#   read_readiness()       → dict
#   write_kill_signal(reason, environment) → None

from __future__ import annotations

import json
import pathlib
from datetime import date, datetime, timezone

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MARKET_STATUS = _ROOT / "data" / "market_status.json"
_RECON_LOG     = _ROOT / "data" / "reconciliation_log.jsonl"
_ORDERS_DIR    = _ROOT / "data" / "orders"
_SCORECARD_LOG = _ROOT / "data" / "readiness_scorecard.jsonl"
_KILL_SIGNAL   = _ROOT / "data" / "kill_signal.json"


def read_market_status() -> dict:
    """
    Read the latest market status snapshot from disk.
    Returns {} if no snapshot has been written yet.
    """
    if not _MARKET_STATUS.exists():
        return {}
    try:
        return json.loads(_MARKET_STATUS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_readiness() -> dict:
    """Read the most recent readiness scorecard entry from disk."""
    if not _SCORECARD_LOG.exists():
        return {}
    try:
        lines = [l.strip() for l in _SCORECARD_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            return {}
        return json.loads(lines[-1])
    except Exception:
        return {}


def read_last_reconciliation() -> dict:
    """Read the most recent reconciliation report from disk."""
    if not _RECON_LOG.exists():
        return {}
    try:
        lines = [l.strip() for l in _RECON_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            return {}
        return json.loads(lines[-1])
    except Exception:
        return {}


def read_today_order_summary() -> dict:
    """Read today's order ledger summary from disk."""
    today = date.today().isoformat()
    path  = _ORDERS_DIR / f"{today}.jsonl"
    if not path.exists():
        return {"orders_placed": 0, "fills": 0, "overlay_warnings": 0, "open_orders": 0}

    records: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return {}

    placed   = [r for r in records if r.get("event_type") == "placed"]
    fills    = [r for r in records if r.get("event_type") == "fill"]
    warnings = [w for r in records for w in r.get("overlay_warnings", [])]

    # Open orders: placed but not in final state
    _FINAL = {"reject", "fill", "cancel", "expired", "kill_switch"}
    latest: dict[str, dict] = {}
    for r in records:
        oid = r.get("order_id", "")
        if oid:
            latest[oid] = r
    open_orders = [r for r in latest.values() if r.get("event_type") not in _FINAL]

    return {
        "orders_placed":  len(placed),
        "fills":          len(fills),
        "overlay_warnings": len(warnings),
        "open_orders":    len(open_orders),
    }


def write_kill_signal(reason: str = "operator_request", environment: str = "paper") -> None:
    """
    Write a kill signal to disk. The trading loop checks for this file on each tick.
    This is the disk-based trigger for the kill switch — no app imports needed.
    """
    try:
        _KILL_SIGNAL.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "reason":      reason,
            "environment": environment,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        }
        _KILL_SIGNAL.write_text(json.dumps(record, indent=2), encoding="utf-8")
    except Exception:
        pass


def read_kill_signal() -> dict | None:
    """Read and clear the kill signal if present. Returns None if no signal."""
    if not _KILL_SIGNAL.exists():
        return None
    try:
        data = json.loads(_KILL_SIGNAL.read_text(encoding="utf-8"))
        _KILL_SIGNAL.unlink(missing_ok=True)
        return data
    except Exception:
        return None
