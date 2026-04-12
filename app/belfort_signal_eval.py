# app/belfort_signal_eval.py
#
# Belfort signal evaluation layer — non-executing decision path.
#
# Wires MeanReversionV1 into the live tick path for SHADOW and PAPER modes.
# Evaluates signals, runs them through RiskGuardrails, and logs the result
# as a decision artifact. Never places orders.
#
# Design:
#   _QuoteProxy       — wraps a raw quote and injects session_type + data_lane
#   evaluate_signal() — main entry point: evaluate + risk check + log
#   read_signal_log() — observability reader
#
# Invariants:
#   was_executed  = False   (always — this block never executes)
#   execution_mode = "none" (always — no order placement)
#
# Public API:
#   evaluate_signal(quote, mode, portfolio=None) → dict
#   read_signal_log(n=20) → list[dict]

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Optional

from app.belfort_strategy import MeanReversionV1
from app.belfort_risk import RiskGuardrails

_ROOT       = pathlib.Path(__file__).resolve().parent.parent
_SIGNAL_LOG = _ROOT / "data" / "belfort" / "signal_log.jsonl"

# Singletons — shared across all calls, retain rolling window state
_strategy   = MeanReversionV1()
_guardrails = RiskGuardrails()

# Modes where signal evaluation is active
_EVAL_MODES = {"shadow", "paper"}


class _QuoteProxy:
    """
    Wraps a raw quote object and injects session_type and data_lane as attributes.

    MeanReversionV1.evaluate() reads these via getattr — the raw quote from
    market_data_feed does not carry session_type, so we inject it here.
    """

    def __init__(self, raw_quote: object, session_type: str, data_lane: str) -> None:
        self._raw         = raw_quote
        self.session_type = session_type
        self.data_lane    = data_lane

    def __getattr__(self, name: str) -> object:
        # Fall through to the raw quote for all other attributes
        return getattr(self._raw, name)


def evaluate_signal(
    quote:     object,
    mode:      str,
    portfolio: Optional[dict] = None,
) -> dict:
    """
    Evaluate a signal for the given quote in the given Belfort mode.

    Only runs in shadow or paper mode. All other modes return a no-op record
    without writing to the signal log.

    Args:
        quote:     Raw quote object from market_data_feed.get_quote()
        mode:      Current Belfort mode string (e.g. "shadow", "paper")
        portfolio: Dict from portfolio.get_snapshot() — keys used:
                     realized_pnl  → mapped to realized_pnl_today for risk check
                     trade_count   → mapped to orders_placed_today for risk check
                     cash          → passed directly

    Returns the full signal record dict.
    """
    now_str = datetime.now(timezone.utc).isoformat()

    if mode not in _EVAL_MODES:
        return {
            "written_at":          now_str,
            "mode":                mode,
            "skipped":             True,
            "skip_reason":         f"mode={mode!r} — signal evaluation only in shadow/paper",
            "was_executed":        False,
            "execution_mode":      "none",
        }

    # Fetch session type and data_lane for the proxy
    try:
        from app.market_time import session_type as get_session_type
        session_type = get_session_type()
    except Exception:
        session_type = "unknown"

    raw_data_lane = str(getattr(quote, "data_lane", "UNKNOWN"))

    # Build proxy so strategy can read session_type + data_lane
    proxied = _QuoteProxy(quote, session_type=session_type, data_lane=raw_data_lane)

    # Run strategy
    try:
        signal = _strategy.evaluate(proxied)
    except Exception as exc:
        # Strategy must never raise, but if it does, log a safe hold
        return _write_error_record(now_str, mode, session_type, raw_data_lane, str(exc))

    # Build portfolio dict compatible with RiskGuardrails (key remapping)
    pf = portfolio or {}
    risk_portfolio = {
        "realized_pnl_today":  pf.get("realized_pnl", 0.0),
        "orders_placed_today": pf.get("trade_count", 0),
        "cash":                pf.get("cash", 0.0),
    }

    # Run risk guardrails
    try:
        risk = _guardrails.check(signal, risk_portfolio)
    except Exception as exc:
        risk_can_proceed  = False
        risk_block_reason = f"guardrail raised unexpected error: {exc}"
        risk_check_name   = "guardrail_error"
    else:
        risk_can_proceed  = risk.passed
        risk_block_reason = risk.block_reason
        risk_check_name   = risk.check_name

    # Plain-English decision summary
    action_upper = signal.action.upper()
    risk_label   = "allowed" if risk_can_proceed else f"blocked ({risk_block_reason})"
    decision_summary = (
        f"{mode.upper()} decision: {action_upper} {signal.symbol}. "
        f"Rationale: {signal.rationale}. "
        f"Risk: {risk_label}. "
        "No order was placed."
    )

    quote_is_live = (session_type == "regular") and (raw_data_lane != "UNKNOWN")

    record: dict = {
        "written_at":                 now_str,
        "symbol":                     signal.symbol,
        "mode":                       mode,
        "session_type":               session_type,
        "data_lane":                  raw_data_lane,
        "quote_source":               raw_data_lane,
        "quote_is_live":              quote_is_live,
        "strategy_name":              "MeanReversionV1",
        "signal_action":              signal.action,
        "signal_qty":                 signal.qty,
        "signal_order_type":          signal.order_type,
        "signal_limit_price":         signal.limit_price,
        "signal_rationale":           signal.rationale,
        "risk_can_proceed":           risk_can_proceed,
        "risk_block_reason":          risk_block_reason,
        "risk_adjusted_qty":          0,
        "risk_checks_run":            risk_check_name,
        "was_executed":               False,
        "execution_mode":             "none",
        "decision_summary_plain_english": decision_summary,
    }

    _write_signal_record(record)
    return record


def _write_signal_record(record: dict) -> None:
    """Append a signal record to the signal log. Never raises."""
    try:
        _SIGNAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _SIGNAL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _write_error_record(
    now_str:      str,
    mode:         str,
    session_type: str,
    data_lane:    str,
    error:        str,
) -> dict:
    record = {
        "written_at":                 now_str,
        "symbol":                     "UNKNOWN",
        "mode":                       mode,
        "session_type":               session_type,
        "data_lane":                  data_lane,
        "quote_source":               data_lane,
        "quote_is_live":              False,
        "strategy_name":              "MeanReversionV1",
        "signal_action":              "hold",
        "signal_qty":                 0,
        "signal_order_type":          "none",
        "signal_limit_price":         0.0,
        "signal_rationale":           f"strategy error: {error}",
        "risk_can_proceed":           False,
        "risk_block_reason":          f"strategy error prevented evaluation: {error}",
        "risk_adjusted_qty":          0,
        "risk_checks_run":            "skipped_due_to_strategy_error",
        "was_executed":               False,
        "execution_mode":             "none",
        "decision_summary_plain_english": (
            f"{mode.upper()} decision: strategy raised an error. No order was placed."
        ),
    }
    _write_signal_record(record)
    return record


def read_signal_log(n: int = 20) -> list[dict]:
    """
    Read the last n signal records from signal_log.jsonl.
    Returns an empty list if the log does not exist or is unreadable.
    """
    if not _SIGNAL_LOG.exists():
        return []
    try:
        lines = [
            ln.strip()
            for ln in _SIGNAL_LOG.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        records: list[dict] = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
        return records[-n:] if len(records) > n else records
    except Exception:
        return []
