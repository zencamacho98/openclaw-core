# app/belfort_strategy.py
#
# Belfort strategy layer — typed signal interface and MeanReversionV1.
#
# BelfortSignal is the typed output of any strategy evaluation.
# All fields are required on every return. No optional fields.
#
# MeanReversionV1:
#   - Rolling window (in-memory, resets on restart)
#   - Hard overrides run BEFORE any state mutation:
#       session_type outside {"regular","pre_market","after_hours"} → hold
#       data_lane == "UNKNOWN"      → hold, "data lane unknown — signal suppressed"
#   - Signals from bid/ask mid price, never from last-trade
#   - Window tracks mid prices over last N ticks (default 20)
#   - When mid falls > threshold below rolling mean → buy signal
#   - When mid rises > threshold above rolling mean → sell signal
#   - Otherwise → hold
#
# Public API:
#   BelfortSignal   — dataclass
#   StrategyBase    — abstract base
#   MeanReversionV1 — strategy implementation

from __future__ import annotations

import collections
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal


@dataclass
class BelfortSignal:
    """Typed output of any strategy evaluation. All fields required."""
    symbol:       str
    action:       Literal["buy", "sell", "hold"]
    qty:          int            # 0 for hold
    order_type:   Literal["limit", "marketable_limit", "none"]  # "none" for hold
    limit_price:  float          # 0.0 for hold; derived from bid/ask only
    rationale:    str            # required, non-empty
    data_lane:    str            # IEX_ONLY | SIP_CONSOLIDATED | UNKNOWN
    session_type: str            # regular | pre_market | after_hours | closed
    generated_at: str            # ISO 8601 UTC


class StrategyBase(ABC):
    """Abstract base for all Belfort strategies."""

    @abstractmethod
    def evaluate(self, quote: object) -> BelfortSignal:
        """
        Evaluate a quote and return a BelfortSignal.
        Must never raise — catch internal errors and return a hold signal.
        """
        ...

    def _hold(self, quote: object, rationale: str) -> BelfortSignal:
        """Convenience factory for hold signals."""
        return BelfortSignal(
            symbol       = getattr(quote, "symbol", "UNKNOWN"),
            action       = "hold",
            qty          = 0,
            order_type   = "none",
            limit_price  = 0.0,
            rationale    = rationale,
            data_lane    = getattr(quote, "data_lane", "UNKNOWN"),
            session_type = getattr(quote, "session_type", "unknown"),
            generated_at = datetime.now(timezone.utc).isoformat(),
        )


class MeanReversionV1(StrategyBase):
    """
    Simple mean-reversion strategy based on rolling mid-price window.

    Parameters:
        window:    number of ticks for rolling mean (default 20)
        threshold: fractional deviation to trigger signal (default 0.005 = 0.5%)
        qty:       fixed order size (default 1)

    Override order (checked before any state mutation):
      1. session_type outside {"regular","pre_market","after_hours"}  → hold
      2. data_lane == "UNKNOWN"     → hold
      3. insufficient window data   → hold (need at least window/2 ticks)
      4. mid below mean by > threshold → buy (marketable_limit at ask)
      5. mid above mean by > threshold → sell (marketable_limit at bid)
      6. otherwise                  → hold
    """

    def __init__(
        self,
        window:    int   = 20,
        threshold: float = 0.005,
        qty:       int   = 1,
    ) -> None:
        self._window    = window
        self._threshold = threshold
        self._qty       = qty
        self._history: collections.deque[float] = collections.deque(maxlen=window)

    def evaluate(self, quote: object) -> BelfortSignal:
        symbol       = getattr(quote, "symbol",       "UNKNOWN")
        bid          = getattr(quote, "bid",          0.0)
        ask          = getattr(quote, "ask",          0.0)
        data_lane    = getattr(quote, "data_lane",    "UNKNOWN")
        session_type = getattr(quote, "session_type", "unknown")

        now_str = datetime.now(timezone.utc).isoformat()

        # ── Hard overrides (run before any state mutation) ────────────────────
        if session_type not in ("regular", "pre_market", "after_hours"):
            return BelfortSignal(
                symbol       = symbol,
                action       = "hold",
                qty          = 0,
                order_type   = "none",
                limit_price  = 0.0,
                rationale    = "paper-tradeable session is closed — no execution",
                data_lane    = data_lane,
                session_type = session_type,
                generated_at = now_str,
            )

        if data_lane == "UNKNOWN":
            return BelfortSignal(
                symbol       = symbol,
                action       = "hold",
                qty          = 0,
                order_type   = "none",
                limit_price  = 0.0,
                rationale    = "data lane unknown — signal suppressed",
                data_lane    = data_lane,
                session_type = session_type,
                generated_at = now_str,
            )

        # ── Mid price from bid/ask only ───────────────────────────────────────
        if bid <= 0.0 or ask <= 0.0 or ask < bid:
            self._history.append(0.0)  # bad quote — still advance window
            return BelfortSignal(
                symbol       = symbol,
                action       = "hold",
                qty          = 0,
                order_type   = "none",
                limit_price  = 0.0,
                rationale    = f"bad bid/ask spread (bid={bid}, ask={ask}) — signal suppressed",
                data_lane    = data_lane,
                session_type = session_type,
                generated_at = now_str,
            )

        mid = (bid + ask) / 2.0

        # ── Require minimum data (before update) ──────────────────────────────
        min_ticks = max(2, self._window // 2)
        if len(self._history) < min_ticks:
            self._history.append(mid)
            return BelfortSignal(
                symbol       = symbol,
                action       = "hold",
                qty          = 0,
                order_type   = "none",
                limit_price  = 0.0,
                rationale    = f"insufficient history ({len(self._history)}/{min_ticks} ticks) — warming up",
                data_lane    = data_lane,
                session_type = session_type,
                generated_at = now_str,
            )

        # ── Mean reversion signal (compare current to historical mean) ────────
        # Compute mean from existing history BEFORE appending current mid.
        # This ensures we measure deviation against prior prices, not the current one.
        mean      = sum(self._history) / len(self._history)
        deviation = (mid - mean) / mean if mean > 0 else 0.0

        # Update history after signal computation
        self._history.append(mid)

        if deviation < -self._threshold:
            # Mid is below mean — expect reversion up → buy at ask (marketable_limit)
            return BelfortSignal(
                symbol       = symbol,
                action       = "buy",
                qty          = self._qty,
                order_type   = "marketable_limit",
                limit_price  = round(ask, 4),
                rationale    = f"mid {mid:.4f} is {abs(deviation)*100:.2f}% below mean {mean:.4f} — reversion buy",
                data_lane    = data_lane,
                session_type = session_type,
                generated_at = now_str,
            )

        if deviation > self._threshold:
            # Mid is above mean — expect reversion down → sell at bid (marketable_limit)
            return BelfortSignal(
                symbol       = symbol,
                action       = "sell",
                qty          = self._qty,
                order_type   = "marketable_limit",
                limit_price  = round(bid, 4),
                rationale    = f"mid {mid:.4f} is {deviation*100:.2f}% above mean {mean:.4f} — reversion sell",
                data_lane    = data_lane,
                session_type = session_type,
                generated_at = now_str,
            )

        return BelfortSignal(
            symbol       = symbol,
            action       = "hold",
            qty          = 0,
            order_type   = "none",
            limit_price  = 0.0,
            rationale    = f"mid {mid:.4f} within {self._threshold*100:.2f}% of mean {mean:.4f} — no edge",
            data_lane    = data_lane,
            session_type = session_type,
            generated_at = now_str,
        )

    def reset(self) -> None:
        """Clear rolling history. Called on restart or session boundary."""
        self._history.clear()
