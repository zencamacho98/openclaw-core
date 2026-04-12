# app/reconciler.py
#
# Daily position reconciler for THE ABODE.
#
# Compares broker-reported positions to Belfort's internal portfolio state.
# On any mismatch beyond the configured threshold, it:
#   - logs a RECONCILIATION_FAIL event
#   - writes to the order ledger
#   - halts further orders until the operator resolves the discrepancy
#
# Run at: market close, backend startup, and on demand.
#
# Public API:
#   run_reconciliation(environment)  → ReconciliationReport
#   get_last_report()                → ReconciliationReport | None
#   is_halted()                      → bool  (True if last reconcile failed)

from __future__ import annotations

import json
import pathlib
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Literal

_ROOT       = pathlib.Path(__file__).resolve().parent.parent
_RECON_LOG  = _ROOT / "data" / "reconciliation_log.jsonl"

EnvironmentType = Literal["paper", "shadow", "live"]

_MISMATCH_THRESHOLD_SHARES = 0.01   # any difference >= this triggers FAIL
_lock = threading.Lock()
_halted = False
_last_report: "ReconciliationReport | None" = None


@dataclass
class PositionLine:
    symbol:       str
    internal_qty: float
    broker_qty:   float | None     # None = broker did not report this symbol
    match:        bool
    discrepancy:  float            # internal - broker (0.0 if match)


@dataclass
class ReconciliationReport:
    environment:      EnvironmentType
    timestamp_utc:    str
    passed:           bool
    lines:            list[PositionLine] = field(default_factory=list)
    mismatches:       int = 0
    message:          str = ""
    broker_available: bool = True

    def to_dict(self) -> dict:
        return {
            "environment":   self.environment,
            "timestamp_utc": self.timestamp_utc,
            "passed":        self.passed,
            "mismatches":    self.mismatches,
            "message":       self.message,
            "broker_available": self.broker_available,
            "lines": [asdict(l) for l in self.lines],
        }

    def summary_line(self) -> str:
        if not self.broker_available:
            return "Reconciliation: broker unavailable — skipped."
        if self.passed:
            syms = len(self.lines)
            return f"Reconciliation PASS: {syms} position(s) checked, all match."
        return (
            f"Reconciliation FAIL: {self.mismatches} mismatch(es). "
            f"Trading halted. Message: {self.message}"
        )


def run_reconciliation(environment: EnvironmentType = "paper") -> ReconciliationReport:
    """
    Run a full position reconciliation.

    Reads broker positions and compares to internal portfolio state.
    On mismatch, sets the global halt flag and fires alerts.
    """
    global _halted, _last_report

    ts = datetime.now(timezone.utc).isoformat()

    # ── Get broker positions ───────────────────────────────────────────────────
    broker_positions: dict[str, float] = {}
    broker_available = True

    try:
        from app.broker_connector import get_connector
        conn = get_connector()
        if conn is None:
            broker_available = False
        else:
            for pos in conn.get_positions():
                broker_positions[pos.symbol.upper()] = pos.qty
    except Exception as exc:
        broker_available = False

    if not broker_available:
        report = ReconciliationReport(
            environment      = environment,
            timestamp_utc    = ts,
            passed           = True,   # can't fail without broker data; just skip
            lines            = [],
            mismatches       = 0,
            message          = "Broker unavailable — reconciliation skipped.",
            broker_available = False,
        )
        with _lock:
            _last_report = report
        _write_report(report)
        return report

    # ── Get internal positions ─────────────────────────────────────────────────
    try:
        from app.portfolio import get_snapshot
        snap = get_snapshot()
        internal_positions: dict[str, float] = {
            sym.upper(): pos["qty"]
            for sym, pos in snap.get("positions", {}).items()
        }
    except Exception as exc:
        internal_positions = {}

    # ── Compare ───────────────────────────────────────────────────────────────
    all_symbols = set(internal_positions.keys()) | set(broker_positions.keys())
    lines: list[PositionLine] = []
    mismatches = 0

    for sym in sorted(all_symbols):
        int_qty    = internal_positions.get(sym, 0.0)
        broker_qty = broker_positions.get(sym)
        b_qty      = broker_qty if broker_qty is not None else 0.0
        discrepancy = abs(int_qty - b_qty)
        match = discrepancy < _MISMATCH_THRESHOLD_SHARES

        if not match:
            mismatches += 1

        lines.append(PositionLine(
            symbol       = sym,
            internal_qty = int_qty,
            broker_qty   = broker_qty,
            match        = match,
            discrepancy  = round(int_qty - b_qty, 6),
        ))

    passed = mismatches == 0
    message = "" if passed else (
        f"{mismatches} position(s) differ between internal ledger and broker. "
        "Review and resolve before placing new orders."
    )

    report = ReconciliationReport(
        environment   = environment,
        timestamp_utc = ts,
        passed        = passed,
        lines         = lines,
        mismatches    = mismatches,
        message       = message,
        broker_available = True,
    )

    # ── Update halt state ──────────────────────────────────────────────────────
    with _lock:
        _halted      = not passed
        _last_report = report

    _write_report(report)

    if not passed:
        _fire_alerts(report)

    return report


def is_halted() -> bool:
    """Return True if the last reconciliation failed and trading should be halted."""
    with _lock:
        return _halted


def clear_halt() -> None:
    """Operator-callable: clear the halt flag after manual resolution."""
    global _halted
    with _lock:
        _halted = False


def get_last_report() -> "ReconciliationReport | None":
    with _lock:
        return _last_report


def _write_report(report: ReconciliationReport) -> None:
    try:
        _RECON_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _RECON_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(report.to_dict()) + "\n")
    except Exception:
        pass

    # Also write to order ledger as a reconcile event
    try:
        from app.order_ledger import append
        event_type = "reconcile_ok" if report.passed else "reconcile_fail"
        append(
            event_type  = event_type,    # type: ignore[arg-type]
            order_id    = "RECONCILER",
            environment = report.environment,  # type: ignore[arg-type]
            rationale   = report.message or "Reconciliation complete.",
            extra       = {"mismatches": report.mismatches, "passed": report.passed},
        )
    except Exception:
        pass


def _fire_alerts(report: ReconciliationReport) -> None:
    try:
        from observability.event_log import append_event
        append_event(
            event_type = "reconciliation_fail",
            summary    = (
                f"RECONCILIATION FAIL ({report.environment}): "
                f"{report.mismatches} mismatch(es). Trading halted. "
                f"{report.message}"
            ),
            severity   = "action_needed",
            source     = "reconciler",
        )
    except Exception:
        pass
