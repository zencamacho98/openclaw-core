# app/belfort_signal_eval.py
#
# Belfort signal evaluation layer — non-executing decision path.
#
# Wires Belfort's regime-aware policy selector into the live tick path for
# SHADOW and PAPER modes. Evaluates signals, runs them through RiskGuardrails,
# and logs the result as a decision artifact. Never places orders.
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

from app.belfort_policy import live_engine
from app.belfort_risk import RiskGuardrails

_ROOT       = pathlib.Path(__file__).resolve().parent.parent
_SIGNAL_LOG = _ROOT / "data" / "belfort" / "signal_log.jsonl"

# Singletons — shared across all calls, retain rolling window state
_strategy   = live_engine()
_guardrails = RiskGuardrails()

# Modes where signal evaluation is active
_EVAL_MODES = {"shadow", "paper"}


def _clean_setup_tag(raw: object, *, active_policy: str = "", market_regime: str = "") -> str:
    tag = str(raw or "").strip().lower()
    if tag.endswith(" watch"):
        tag = tag[:-6].strip()
    if tag.startswith("avoid"):
        return "avoid / spread risk"
    if tag and tag != "monitor only":
        return tag
    active_policy = str(active_policy or "").strip().lower()
    market_regime = str(market_regime or "").strip().lower()
    if active_policy == "mean_reversion":
        return "mean reversion"
    if active_policy == "ma_crossover" and market_regime == "trending":
        return "trend continuation"
    if active_policy == "ma_crossover":
        return "trend"
    return "monitor only"


class _QuoteProxy:
    """
    Wraps a raw quote object and injects session_type and data_lane as attributes.

    Belfort's policy selector reads these via getattr — the raw quote from
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

    # Build portfolio dict compatible with RiskGuardrails (key remapping)
    pf = portfolio or {}
    orders_placed_today = pf.get("trade_count", 0)
    try:
        from app.order_ledger import get_today_count
        orders_placed_today = max(int(orders_placed_today or 0), int(get_today_count(environment="paper") or 0))
    except Exception:
        orders_placed_today = int(orders_placed_today or 0)
    risk_portfolio = {
        "realized_pnl_today":  pf.get("realized_pnl", 0.0),
        "orders_placed_today": orders_placed_today,
        "cash":                pf.get("cash", 0.0),
        "positions":           pf.get("positions", {}) or {},
    }

    # Run strategy
    try:
        try:
            signal = _strategy.evaluate(proxied, portfolio=risk_portfolio)
        except TypeError:
            signal = _strategy.evaluate(proxied)
    except Exception as exc:
        # Strategy must never raise, but if it does, log a safe hold
        return _write_error_record(now_str, mode, session_type, raw_data_lane, str(exc))
    evidence = getattr(_strategy, "last_evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}
    try:
        from app.belfort_scanner import lookup_candidate
        scanner_ctx = lookup_candidate(signal.symbol)
    except Exception:
        scanner_ctx = None
    active_policy = str(evidence.get("active_policy") or "policy_selector")
    regime_label = str(evidence.get("market_regime") or "unknown")
    setup_tag = _clean_setup_tag(
        (scanner_ctx or {}).get("strategy_fit"),
        active_policy=active_policy,
        market_regime=regime_label,
    )

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
    strategy_name = active_policy
    decision_summary = (
        f"{mode.upper()} decision: {action_upper} {signal.symbol}. "
        f"Setup: {setup_tag}. Policy: {strategy_name} in {regime_label}. "
        f"Rationale: {signal.rationale}. "
        f"Risk: {risk_label}. "
        "No order was placed."
    )

    quote_is_live = (session_type in ("regular", "pre_market", "after_hours")) and (raw_data_lane != "UNKNOWN")

    record: dict = {
        "written_at":                 now_str,
        "symbol":                     signal.symbol,
        "mode":                       mode,
        "session_type":               session_type,
        "data_lane":                  raw_data_lane,
        "quote_source":               raw_data_lane,
        "quote_is_live":              quote_is_live,
        "strategy_name":              strategy_name,
        "policy_selector":            evidence.get("policy_selector", "regime_router_v1"),
        "policy_family":              evidence.get("policy_family", ""),
        "active_policy":              strategy_name,
        "market_regime":              regime_label,
        "selection_reason":           evidence.get("selection_reason", ""),
        "efficiency_ratio":           evidence.get("efficiency_ratio"),
        "setup_tag":                  setup_tag,
        "scanner_strategy_fit":       (scanner_ctx or {}).get("strategy_fit"),
        "price_bucket":               (scanner_ctx or {}).get("price_bucket"),
        "catalyst_type":              (scanner_ctx or {}).get("catalyst_type"),
        "relative_strength_label":    (scanner_ctx or {}).get("relative_strength_label"),
        "relative_strength_vs_spy_pct": (scanner_ctx or {}).get("relative_strength_vs_spy_pct"),
        "relative_volume":            (scanner_ctx or {}).get("relative_volume"),
        "gap_pct":                    (scanner_ctx or {}).get("gap_pct"),
        "float_turnover_pct":         (scanner_ctx or {}).get("float_turnover_pct"),
        "risk_flags":                 list((scanner_ctx or {}).get("risk_flags") or []),
        "paper_eligible":             bool((scanner_ctx or {}).get("paper_eligible")),
        "tradeability_label":         (scanner_ctx or {}).get("tradeability_label"),
        "tradeability_reason":        (scanner_ctx or {}).get("tradeability_reason"),
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
        "strategy_context":           {
            "ma_crossover": evidence.get("ma_crossover"),
            "mean_reversion": evidence.get("mean_reversion"),
        },
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
        "strategy_name":              "policy_selector",
        "policy_selector":            "regime_router_v1",
        "policy_family":              "",
        "active_policy":              "none",
        "market_regime":              "unknown",
        "selection_reason":           "",
        "efficiency_ratio":           None,
        "setup_tag":                  "strategy error",
        "scanner_strategy_fit":       None,
        "price_bucket":               None,
        "catalyst_type":              None,
        "relative_strength_label":    None,
        "risk_flags":                 [],
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
        "strategy_context":           {},
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
