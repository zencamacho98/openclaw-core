# app/execution_overlay.py
#
# Execution realism overlay for THE ABODE.
#
# Sits between Belfort's order intent and the broker connector.
# Prevents fake fills, enforces bid/ask price discipline, models
# partial fills and no-fill outcomes, and enforces extended-hours rules.
#
# Core rules:
#   - Market orders fill at ask (buys) or bid (sells), NOT at last-trade price.
#   - Non-marketable limit orders: flagged if broker reports instant fill.
#   - Partial fill: when order qty > estimated available size at best price.
#   - No-fill outcome: when spread is wide or liquidity is low.
#   - Extended hours: default = limit-only; market orders blocked by default.
#
# Public API:
#   check_order(order_intent, quote, session_type) → OverlayResult
#   EXTENDED_HOURS_ALLOW_MARKET — module-level flag (default False)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

OrderType = Literal["market", "limit"]
SideType  = Literal["buy", "sell"]

# Module-level safety default: market orders blocked in extended hours
EXTENDED_HOURS_ALLOW_MARKET: bool = False

# Liquidity thresholds for partial / no-fill assessment
_LOW_LIQUIDITY_SIZE = 10       # shares: if available size < this, partial fill likely
_WIDE_SPREAD_THRESHOLD = 0.01  # 1% of midpoint: flag as potentially no-fill


@dataclass
class OrderIntent:
    """The intent Belfort has formed before calling the broker."""
    symbol:      str
    side:        SideType
    qty:         float
    order_type:  OrderType
    limit_price: float | None = None   # required for limit orders


@dataclass
class OverlayResult:
    """
    Outcome of the overlay check.

    is_realistic: False means the broker's reported fill cannot be trusted
                  without adjustment.
    can_proceed:  False means the order should NOT be placed (e.g. market order
                  in extended hours when not permitted).
    adjusted_fill_price: the price Belfort should record for P&L (may differ
                         from broker-reported fill in paper mode).
    partial_fill_qty: if < original qty, the overlay estimates this many shares
                      actually available at the target price.
    """
    is_realistic:        bool
    can_proceed:         bool
    adjusted_fill_price: float | None
    partial_fill_qty:    float | None       # None = full qty is plausible
    warnings:            list[str] = field(default_factory=list)
    block_reason:        str = ""


def check_order(
    intent:       OrderIntent,
    quote:        object,             # QuoteEvent from market_data_feed
    session_type: str = "regular",   # from market_time.session_type()
) -> OverlayResult:
    """
    Apply realism checks to an order intent given the current quote.

    This does NOT place any order. It returns whether the intent is
    realistic and what fill price Belfort should use for accounting.
    """
    warnings: list[str] = []
    extended = session_type in ("pre_market", "after_hours")

    # ── Extended-hours order-type enforcement ──────────────────────────────────
    if extended and intent.order_type == "market" and not EXTENDED_HOURS_ALLOW_MARKET:
        return OverlayResult(
            is_realistic        = False,
            can_proceed         = False,
            adjusted_fill_price = None,
            partial_fill_qty    = None,
            warnings            = [
                "Market orders are blocked in extended hours by default. "
                "Use a limit order or enable EXTENDED_HOURS_ALLOW_MARKET."
            ],
            block_reason = "market_order_extended_hours_blocked",
        )

    bid: float | None = getattr(quote, "bid", None)
    ask: float | None = getattr(quote, "ask", None)
    midpoint: float | None = getattr(quote, "midpoint", None)
    spread_pct: float | None = getattr(quote, "spread_pct", None)
    bid_size: float | None = getattr(quote, "bid_size", None)
    ask_size: float | None = getattr(quote, "ask_size", None)
    data_lane: str = getattr(quote, "data_lane", "UNKNOWN")

    # ── Data lane disclaimer ───────────────────────────────────────────────────
    if data_lane == "IEX_ONLY":
        warnings.append(
            "IEX-only data: bid/ask may not reflect consolidated NBBO. "
            "Fill price is approximate."
        )
    elif data_lane == "UNKNOWN":
        warnings.append("Data lane unknown: all price estimates are indicative only.")

    # ── Extended-hours spread warning ──────────────────────────────────────────
    if extended:
        warnings.append(
            f"Extended hours ({session_type}): wider spreads expected. "
            "Fill quality may be significantly worse than regular session."
        )

    # ── Market order: fill must be at bid or ask, not last-trade ──────────────
    adjusted_fill: float | None = None
    if intent.order_type == "market":
        if intent.side == "buy":
            if ask is not None:
                adjusted_fill = ask
            else:
                warnings.append("Ask price unavailable; cannot determine realistic fill price.")
        else:  # sell
            if bid is not None:
                adjusted_fill = bid
            else:
                warnings.append("Bid price unavailable; cannot determine realistic fill price.")

    # ── Limit order: marketability check ──────────────────────────────────────
    is_realistic = True
    if intent.order_type == "limit" and intent.limit_price is not None:
        if intent.side == "buy":
            # Marketable if limit >= ask
            if ask is not None and intent.limit_price < ask:
                warnings.append(
                    f"Limit buy ${intent.limit_price:.4f} < ask ${ask:.4f}: "
                    "non-marketable. This order may not fill."
                )
                is_realistic = False  # broker instant-fill on this would be fake
        else:
            # Marketable if limit <= bid
            if bid is not None and intent.limit_price > bid:
                warnings.append(
                    f"Limit sell ${intent.limit_price:.4f} > bid ${bid:.4f}: "
                    "non-marketable. This order may not fill."
                )
                is_realistic = False

        adjusted_fill = intent.limit_price  # limit orders fill at limit price if they fill

    # ── Wide-spread / no-fill risk ─────────────────────────────────────────────
    if spread_pct is not None and spread_pct > _WIDE_SPREAD_THRESHOLD:
        warnings.append(
            f"Wide spread detected ({spread_pct*100:.2f}%): "
            "fill quality is uncertain. No-fill or significant slippage possible."
        )

    # ── Partial fill estimation ────────────────────────────────────────────────
    partial_qty: float | None = None
    if intent.order_type == "market":
        available_size = ask_size if intent.side == "buy" else bid_size
        if available_size is not None and available_size < intent.qty:
            if available_size < _LOW_LIQUIDITY_SIZE:
                warnings.append(
                    f"Low available size ({available_size} shares at best price). "
                    f"Partial fill likely: estimated {available_size} of {intent.qty} shares."
                )
            partial_qty = available_size

    return OverlayResult(
        is_realistic        = is_realistic,
        can_proceed         = True,
        adjusted_fill_price = adjusted_fill,
        partial_fill_qty    = partial_qty,
        warnings            = warnings,
        block_reason        = "",
    )
