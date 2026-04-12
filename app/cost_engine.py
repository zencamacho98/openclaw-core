# app/cost_engine.py
#
# Deterministic trading cost engine for THE ABODE.
#
# This module is fully deterministic — no LM calls, no randomness.
# It models:
#   - Explicit/ledger costs: commission, SEC Section 31 fee, FINRA TAF
#   - Implicit/market costs: bid/ask spread (crossing cost), slippage estimate
#
# All fee rates are configurable via BROKER_PROFILES. The defaults match
# Alpaca retail as of April 2026 (SEC 31 rate advisory: $20.60 per $1M,
# effective April 4 2026; FINRA TAF: $0.000166/share, max $8.30/trade).
#
# Uncertainty in slippage is elevated when:
#   - Session is extended hours (pre_market / after_hours)
#   - Data lane is IEX_ONLY (single venue, not NBBO-representative)
#   - Observed spread > threshold
#
# Public API:
#   estimate(symbol, side, qty, price, broker_profile, session_type,
#            data_lane, observed_spread_pct) → CostEstimate
#   BROKER_PROFILES — configurable dict
#   CostEstimate    — result dataclass

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

# ── Constants ─────────────────────────────────────────────────────────────────

DataLane    = Literal["IEX_ONLY", "SIP_CONSOLIDATED", "UNKNOWN"]
SideType    = Literal["buy", "sell"]
SessionType = Literal["pre_market", "regular", "after_hours", "closed"]
Uncertainty = Literal["low", "medium", "high"]

# ── Broker profiles ───────────────────────────────────────────────────────────
# Configurable dict — do not hardcode fees inside estimate().
# Each profile has explicit fee rates and slippage defaults.

@dataclass
class BrokerProfile:
    commission_per_trade:   float   # USD; 0.0 for commission-free
    sec_31_rate:            float   # fraction of principal (sell-side only)
    sec_31_effective_date:  str     # informational; rate stored with its date
    finra_taf_per_share:    float   # USD per share (sell-side only)
    finra_taf_max_per_trade: float  # USD cap per trade
    # Conservative slippage defaults by session (basis points of principal)
    slippage_bps_regular:   float   # e.g. 5 bps = 0.0005 = 0.05%
    slippage_bps_extended:  float   # wider spread environment


BROKER_PROFILES: dict[str, BrokerProfile] = {
    "alpaca_retail": BrokerProfile(
        commission_per_trade    = 0.0,
        sec_31_rate             = 0.0000206,     # $20.60 per $1M, eff. 2026-04-04
        sec_31_effective_date   = "2026-04-04",
        finra_taf_per_share     = 0.000166,
        finra_taf_max_per_trade = 8.30,
        slippage_bps_regular    = 5.0,           # 0.05% conservative default
        slippage_bps_extended   = 20.0,          # 4× in extended hours
    ),
    "ibkr_retail": BrokerProfile(
        commission_per_trade    = 0.005,         # per share; minimum $1.00 — simplified
        sec_31_rate             = 0.0000206,
        sec_31_effective_date   = "2026-04-04",
        finra_taf_per_share     = 0.000166,
        finra_taf_max_per_trade = 8.30,
        slippage_bps_regular    = 5.0,
        slippage_bps_extended   = 20.0,
    ),
    "commission_free_generic": BrokerProfile(
        commission_per_trade    = 0.0,
        sec_31_rate             = 0.0000206,
        sec_31_effective_date   = "2026-04-04",
        finra_taf_per_share     = 0.000166,
        finra_taf_max_per_trade = 8.30,
        slippage_bps_regular    = 5.0,
        slippage_bps_extended   = 20.0,
    ),
}

DEFAULT_BROKER_PROFILE = "alpaca_retail"

# Spread thresholds for uncertainty classification
_SPREAD_MEDIUM_THRESHOLD = 0.002   # 0.20% of midpoint
_SPREAD_HIGH_THRESHOLD   = 0.005   # 0.50% of midpoint


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class CostEstimate:
    # Inputs
    symbol:           str
    side:             SideType
    qty:              float
    price:            float
    broker_profile:   str
    session_type:     SessionType
    data_lane:        DataLane

    # Explicit / ledger costs
    commission_usd:   float
    sec_31_fee_usd:   float      # sell-side only; 0.0 for buys
    finra_taf_usd:    float      # sell-side only; 0.0 for buys

    # Implicit / market costs
    spread_cost_usd:          float  # half-spread × qty × price (market orders)
    slippage_estimate_usd:    float
    slippage_uncertainty:     Uncertainty

    # Totals
    total_explicit_usd:       float
    total_implicit_usd:       float
    total_estimated_cost_usd: float

    # Flags / disclaimers
    extended_hours_warning:   bool
    data_lane_disclaimer:     str

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_line(self) -> str:
        """Plain-English one-liner for Peter reports."""
        return (
            f"{self.side.upper()} {self.qty} {self.symbol} @ ${self.price:.2f}: "
            f"total est. cost ${self.total_estimated_cost_usd:.4f} "
            f"(explicit ${self.total_explicit_usd:.4f}, "
            f"implicit ~${self.total_implicit_usd:.4f}, "
            f"slippage confidence: {self.slippage_uncertainty})"
            + (" [EXTENDED HOURS]" if self.extended_hours_warning else "")
            + (f" [{self.data_lane_disclaimer}]" if self.data_lane_disclaimer else "")
        )


# ── Core estimator ────────────────────────────────────────────────────────────

def estimate(
    symbol:               str,
    side:                 SideType,
    qty:                  float,
    price:                float,
    broker_profile:       str      = DEFAULT_BROKER_PROFILE,
    session_type:         SessionType = "regular",
    data_lane:            DataLane  = "IEX_ONLY",
    observed_spread_pct:  float | None = None,  # fraction of midpoint, e.g. 0.002
    order_type:           str = "market",        # "market" or "limit"
) -> CostEstimate:
    """
    Compute a conservative cost estimate for a potential order.

    All amounts in USD. Slippage uncertainty reflects data quality and
    session conditions — err on the side of overestimating costs.

    Args:
        symbol              — ticker symbol
        side                — "buy" or "sell"
        qty                 — number of shares
        price               — reference price (ask for buys, bid for sells)
        broker_profile      — key into BROKER_PROFILES
        session_type        — market session context
        data_lane           — data source quality
        observed_spread_pct — actual spread as fraction of midpoint (optional)
        order_type          — "market" (crosses spread) or "limit" (may not fill)
    """
    profile = BROKER_PROFILES.get(broker_profile, BROKER_PROFILES[DEFAULT_BROKER_PROFILE])
    principal = qty * price

    # ── Explicit costs ─────────────────────────────────────────────────────────
    commission = profile.commission_per_trade  # simplified: per-trade flat

    if side == "sell":
        sec_31 = principal * profile.sec_31_rate
        raw_taf = qty * profile.finra_taf_per_share
        finra_taf = min(raw_taf, profile.finra_taf_max_per_trade)
    else:
        sec_31    = 0.0
        finra_taf = 0.0

    total_explicit = commission + sec_31 + finra_taf

    # ── Implicit costs ─────────────────────────────────────────────────────────
    extended = session_type in ("pre_market", "after_hours")

    if order_type == "market":
        # Spread cost: buyer pays ask (crosses half-spread from midpoint)
        if observed_spread_pct is not None:
            half_spread_frac = observed_spread_pct / 2.0
        else:
            # Fallback: estimate from session; extended = wider
            half_spread_frac = 0.002 if extended else 0.0005
        spread_cost = half_spread_frac * principal
    else:
        # Limit orders: if non-marketable, may not fill at all.
        # If marketable, effectively crosses spread.
        spread_cost = 0.0

    # Slippage: always positive (cost to us), always conservative
    slippage_bps = (
        profile.slippage_bps_extended if extended
        else profile.slippage_bps_regular
    )
    slippage_cost = (slippage_bps / 10_000.0) * principal

    total_implicit = spread_cost + slippage_cost

    # ── Uncertainty classification ─────────────────────────────────────────────
    uncertainty = _classify_uncertainty(
        data_lane=data_lane,
        session_type=session_type,
        observed_spread_pct=observed_spread_pct,
    )

    # ── Disclaimers ────────────────────────────────────────────────────────────
    data_lane_disclaimer = _lane_disclaimer(data_lane)
    extended_warning = extended

    return CostEstimate(
        symbol                  = symbol,
        side                    = side,
        qty                     = qty,
        price                   = price,
        broker_profile          = broker_profile,
        session_type            = session_type,
        data_lane               = data_lane,
        commission_usd          = round(commission, 6),
        sec_31_fee_usd          = round(sec_31, 6),
        finra_taf_usd           = round(finra_taf, 6),
        spread_cost_usd         = round(spread_cost, 6),
        slippage_estimate_usd   = round(slippage_cost, 6),
        slippage_uncertainty    = uncertainty,
        total_explicit_usd      = round(total_explicit, 6),
        total_implicit_usd      = round(total_implicit, 6),
        total_estimated_cost_usd = round(total_explicit + total_implicit, 6),
        extended_hours_warning  = extended_warning,
        data_lane_disclaimer    = data_lane_disclaimer,
    )


def _classify_uncertainty(
    data_lane:           DataLane,
    session_type:        SessionType,
    observed_spread_pct: float | None,
) -> Uncertainty:
    extended = session_type in ("pre_market", "after_hours")

    if extended:
        return "high"
    if data_lane == "IEX_ONLY":
        return "high"
    if data_lane == "UNKNOWN":
        return "high"
    if observed_spread_pct is not None:
        if observed_spread_pct > _SPREAD_HIGH_THRESHOLD:
            return "high"
        if observed_spread_pct > _SPREAD_MEDIUM_THRESHOLD:
            return "medium"
    return "low"


def _lane_disclaimer(data_lane: DataLane) -> str:
    if data_lane == "IEX_ONLY":
        return (
            "IEX-only: single-venue data, not NBBO-representative. "
            "Spread and fill estimates may not reflect full market."
        )
    if data_lane == "UNKNOWN":
        return "Data lane unknown: treat all cost estimates as indicative only."
    return ""  # SIP_CONSOLIDATED: no disclaimer needed
