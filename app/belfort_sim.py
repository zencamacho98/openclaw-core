# app/belfort_sim.py
#
# Belfort Practice Simulation lane — non-live, non-paper, never touches broker.
#
# Runs a separate Belfort policy engine instance with a _SimQuoteProxy that
# overrides session_type → "regular" and data_lane to real lane or IEX_ONLY
# fallback. This allows practice trading at any hour while keeping sim and live
# policy history fully separate.
#
# Sim fills are recorded immediately at the signal's limit_price.
# No broker orders. No real money. Clearly labeled sim=True in every record.
#
# Artifacts:
#   data/belfort/sim_log.jsonl — append-only log of sim ticks and fills
#
# Public API:
#   start_sim(interval)   → dict
#   stop_sim()            → dict
#   get_sim_status()      → dict

from __future__ import annotations

import json
import pathlib
import threading
import time
from datetime import datetime, timezone

from app.belfort_policy import BelfortPolicyEngine

_ROOT    = pathlib.Path(__file__).resolve().parent.parent
_SIM_LOG = _ROOT / "data" / "belfort" / "sim_log.jsonl"

# ── Module-level state ────────────────────────────────────────────────────────

_running:    bool                     = False
_thread:     threading.Thread | None = None
_ticks:      int                      = 0
_fills:      int                      = 0
_started_at: str | None              = None
_interval:   int                      = 5

# Separate policy instance — never shares rolling history with live signal eval
_sim_strategy = BelfortPolicyEngine("sim")

# Simulated portfolio (resets on each start_sim call)
_sim_cash:     float = 10_000.0
_sim_position: int   = 0        # shares of the current focus symbol held
_sim_cost:     float = 0.0      # total cost basis of open position
_sim_symbol:   str   = "SPY"


# ── SimQuoteProxy ──────────────────────────────────────────────────────────────

class _SimQuoteProxy:
    """
    Wraps a live QuoteEvent and overrides session_type and data_lane.

    Belfort's policy selector reads session_type and data_lane via getattr.
    The overrides ensure the strategy evaluates as if it were regular market
    hours with a known data lane, bypassing the two hard guards that would
    otherwise suppress signals outside market hours.

    session_type override:  always "regular"
    data_lane override:     real lane from quote if not UNKNOWN; else "IEX_ONLY"
    """

    def __init__(self, quote: object) -> None:
        self._quote    = quote
        real_lane      = str(getattr(quote, "data_lane", "UNKNOWN"))
        self._sim_lane = real_lane if real_lane != "UNKNOWN" else "IEX_ONLY"
        raw_bid        = self._as_price(getattr(quote, "bid", None))
        raw_ask        = self._as_price(getattr(quote, "ask", None))
        raw_last       = self._as_price(getattr(quote, "last", None))
        self._sim_bid, self._sim_ask, self._sim_last, self._quote_sanitized = (
            self._sanitize_book(raw_bid, raw_ask, raw_last)
        )

    def __getattr__(self, name: str) -> object:
        return getattr(self._quote, name)

    @property
    def session_type(self) -> str:
        return "regular"

    @property
    def data_lane(self) -> str:
        return self._sim_lane

    @property
    def bid(self) -> float | None:
        return self._sim_bid

    @property
    def ask(self) -> float | None:
        return self._sim_ask

    @property
    def last(self) -> float | None:
        return self._sim_last

    @property
    def midpoint(self) -> float | None:
        if self._sim_bid and self._sim_ask:
            return round((self._sim_bid + self._sim_ask) / 2.0, 6)
        return None

    @property
    def spread(self) -> float | None:
        if self._sim_bid and self._sim_ask:
            return round(self._sim_ask - self._sim_bid, 6)
        return None

    @property
    def spread_pct(self) -> float | None:
        mid = self.midpoint
        spd = self.spread
        if mid and spd is not None:
            return round(spd / mid, 6)
        return None

    @property
    def quote_sanitized(self) -> bool:
        return self._quote_sanitized

    @staticmethod
    def _as_price(value: object) -> float | None:
        try:
            price = float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
        return price if price and price > 0 else None

    @classmethod
    def _sanitize_book(
        cls,
        bid: float | None,
        ask: float | None,
        last: float | None,
    ) -> tuple[float | None, float | None, float | None, bool]:
        if bid and ask and ask >= bid:
            ref = last if last is not None else (bid + ask) / 2.0
            return bid, ask, ref, False

        ref = last
        if ref is None and bid is not None:
            ref = bid
        if ref is None and ask is not None:
            ref = ask
        if ref is None:
            return bid, ask, last, False

        if bid is None and ask is None:
            return ref, ref, ref, True
        if bid is None:
            safe_ask = max(ask or ref, ref)
            return min(ref, safe_ask), safe_ask, ref, True
        if ask is None:
            safe_bid = min(bid, ref)
            safe_ask = max(bid, ref)
            return safe_bid, safe_ask, ref, True

        safe_bid = min(bid, ask, ref)
        safe_ask = max(bid, ask, ref)
        return safe_bid, safe_ask, ref, True


# ── Sim fill accounting ───────────────────────────────────────────────────────

def _apply_sim_fill(
    action: str,
    symbol: str,
    qty: int,
    price: float,
    rationale: str,
    data_lane: str,
) -> dict | None:
    """
    Apply a mock fill to the in-memory sim portfolio and return a fill record.
    Returns None if the fill cannot be applied (e.g. insufficient cash, no position).
    Never raises.
    """
    global _sim_cash, _sim_position, _sim_cost, _fills, _sim_symbol
    now_str = datetime.now(timezone.utc).isoformat()
    symbol = str(symbol or "SPY").upper()

    if action == "buy" and qty > 0 and price > 0:
        if _sim_position > 0 and symbol != _sim_symbol:
            return None  # one open sim symbol at a time
        cost = qty * price
        if _sim_cash < cost:
            return None  # not enough sim capital
        _sim_cash     -= cost
        _sim_position += qty
        _sim_cost     += cost
        _sim_symbol    = symbol
        _fills        += 1
        return {
            "written_at":    now_str,
            "action":        "buy",
            "symbol":        symbol,
            "qty":           qty,
            "fill_price":    round(price, 4),
            "sim_cash":      round(_sim_cash, 2),
            "sim_position":  _sim_position,
            "sim_pnl":       None,
            "rationale":     rationale,
            "data_lane":     data_lane,
            "market_regime": "closed_sim",
            "sim":           True,
        }

    if action == "sell" and _sim_position > 0 and price > 0 and symbol == _sim_symbol:
        actual_qty = min(qty, _sim_position)
        proceeds   = actual_qty * price
        avg_cost   = (_sim_cost / _sim_position) if _sim_position > 0 else 0.0
        trade_pnl  = (price - avg_cost) * actual_qty
        _sim_cash     += proceeds
        _sim_position -= actual_qty
        _sim_cost      = (avg_cost * _sim_position) if _sim_position > 0 else 0.0
        if _sim_position <= 0:
            _sim_symbol = symbol
        _fills        += 1
        return {
            "written_at":    now_str,
            "action":        "sell",
            "symbol":        symbol,
            "qty":           actual_qty,
            "fill_price":    round(price, 4),
            "sim_cash":      round(_sim_cash, 2),
            "sim_position":  _sim_position,
            "sim_pnl":       round(trade_pnl, 2),
            "rationale":     rationale,
            "data_lane":     data_lane,
            "market_regime": "closed_sim",
            "sim":           True,
        }

    return None


# ── Log I/O ───────────────────────────────────────────────────────────────────

def _write_sim_record(record: dict) -> None:
    """Append one record to sim_log.jsonl. Never raises."""
    try:
        _SIM_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _SIM_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _sim_portfolio() -> dict:
    if _sim_position <= 0:
        return {"cash": _sim_cash, "positions": {}}
    return {
        "cash": _sim_cash,
        "positions": {
            _sim_symbol: {
                "qty": _sim_position,
                "avg_cost": (_sim_cost / _sim_position) if _sim_position > 0 else 0.0,
            }
        },
    }


# ── Loop body ─────────────────────────────────────────────────────────────────

def _sim_tick() -> None:
    """One sim cycle: fetch quote → proxy → evaluate → optionally fill → log."""
    global _ticks
    _ticks += 1
    now_str = datetime.now(timezone.utc).isoformat()

    # Fetch live quote (may return simulated fallback if no API key)
    try:
        from app.belfort_scanner import get_focus_symbol
        from app.market_data_feed import get_quote

        symbol = _sim_symbol if _sim_position > 0 else get_focus_symbol(default="SPY")
        raw_quote = get_quote(symbol)
    except Exception:
        return

    proxy = _SimQuoteProxy(raw_quote)

    # Evaluate strategy with proxy (session/lane gates bypassed)
    try:
        signal = _sim_strategy.evaluate(proxy, portfolio=_sim_portfolio())
    except Exception:
        return
    evidence = _sim_strategy.last_evidence if isinstance(_sim_strategy.last_evidence, dict) else {}
    try:
        from app.belfort_scanner import lookup_candidate
        scanner_ctx = lookup_candidate(signal.symbol)
    except Exception:
        scanner_ctx = None
    setup_tag = str((scanner_ctx or {}).get("strategy_fit") or "").strip().lower()
    if setup_tag.endswith(" watch"):
        setup_tag = setup_tag[:-6].strip()
    if not setup_tag or setup_tag == "monitor only":
        active_policy = str(evidence.get("active_policy") or "").strip().lower()
        regime_label = str(evidence.get("market_regime") or "").strip().lower()
        if active_policy == "mean_reversion":
            setup_tag = "mean reversion"
        elif active_policy == "ma_crossover" and regime_label == "trending":
            setup_tag = "trend continuation"
        elif active_policy == "ma_crossover":
            setup_tag = "trend"
        else:
            setup_tag = "monitor only"

    # Attempt fill for actionable signals
    fill_record = None
    if signal.action in ("buy", "sell") and signal.qty > 0 and signal.limit_price > 0:
        fill_record = _apply_sim_fill(
            action    = signal.action,
            symbol    = signal.symbol,
            qty       = signal.qty,
            price     = signal.limit_price,
            rationale = signal.rationale,
            data_lane = proxy.data_lane,
        )

    if fill_record:
        fill_record.update({
            "strategy_name": evidence.get("active_policy", "unknown"),
            "policy_selector": evidence.get("policy_selector", "regime_router_v1"),
            "policy_family": evidence.get("policy_family", ""),
            "selection_reason": evidence.get("selection_reason", ""),
            "efficiency_ratio": evidence.get("efficiency_ratio"),
            "setup_tag": setup_tag,
            "price_bucket": (scanner_ctx or {}).get("price_bucket"),
            "catalyst_type": (scanner_ctx or {}).get("catalyst_type"),
            "relative_strength_label": (scanner_ctx or {}).get("relative_strength_label"),
            "risk_flags": list((scanner_ctx or {}).get("risk_flags") or []),
            "quote_sanitized": proxy.quote_sanitized,
        })
        _write_sim_record(fill_record)
        return

    # Log hold or ungated tick
    _write_sim_record({
        "written_at":    now_str,
        "action":        signal.action,
        "symbol":        signal.symbol,
        "qty":           signal.qty,
        "fill_price":    signal.limit_price,
        "sim_cash":      round(_sim_cash, 2),
        "sim_position":  _sim_position,
        "sim_pnl":       None,
        "rationale":     signal.rationale,
        "data_lane":     proxy.data_lane,
        "market_regime": "closed_sim",
        "strategy_name": evidence.get("active_policy", "unknown"),
        "policy_selector": evidence.get("policy_selector", "regime_router_v1"),
        "policy_family": evidence.get("policy_family", ""),
        "selection_reason": evidence.get("selection_reason", ""),
        "efficiency_ratio": evidence.get("efficiency_ratio"),
        "setup_tag":      setup_tag,
        "price_bucket":   (scanner_ctx or {}).get("price_bucket"),
        "catalyst_type":  (scanner_ctx or {}).get("catalyst_type"),
        "relative_strength_label": (scanner_ctx or {}).get("relative_strength_label"),
        "risk_flags":     list((scanner_ctx or {}).get("risk_flags") or []),
        "quote_sanitized": proxy.quote_sanitized,
        "sim":           True,
    })


def _run_sim_regime_snapshot() -> None:
    """
    Regime learning snapshot from the sim lane — called every 20 sim ticks.
    Independent of the paper trading loop. Never raises.
    """
    try:
        from app.belfort_regime_learning import maybe_record_regime_snapshot
        maybe_record_regime_snapshot(_ticks)
    except Exception:
        pass


def _loop_body(interval: int) -> None:
    global _running
    while _running:
        try:
            _sim_tick()
        except Exception:
            pass
        if _ticks % 20 == 0:
            _run_sim_regime_snapshot()
        time.sleep(interval)


# ── Public API ────────────────────────────────────────────────────────────────

def start_sim(interval: int = 5) -> dict:
    """Start the sim lane daemon thread. Resets portfolio on each start."""
    global _running, _thread, _ticks, _fills, _started_at, _interval
    global _sim_cash, _sim_position, _sim_cost, _sim_symbol

    if _running:
        return {"status": "already_running", "ticks": _ticks}

    _running    = True
    _interval   = interval
    _ticks      = 0
    _fills      = 0
    _started_at = datetime.now(timezone.utc).isoformat()

    # Reset sim portfolio and strategy window
    _sim_cash     = 10_000.0
    _sim_position = 0
    _sim_cost     = 0.0
    _sim_symbol   = "SPY"
    _sim_strategy.reset()

    _thread = threading.Thread(target=_loop_body, args=(interval,), daemon=True)
    _thread.start()
    return {"status": "started", "interval": interval}


def stop_sim() -> dict:
    """Stop the sim lane. Safe to call when already stopped."""
    global _running
    if not _running:
        return {"status": "already_stopped"}
    _running = False
    return {"status": "stopped", "ticks_completed": _ticks, "fills": _fills}


def get_sim_status() -> dict:
    return {
        "running":      _running,
        "interval":     _interval,
        "ticks":        _ticks,
        "fills":        _fills,
        "started_at":   _started_at,
        "sim_cash":     round(_sim_cash, 2),
        "sim_position": _sim_position,
        "sim_symbol":   _sim_symbol,
    }
