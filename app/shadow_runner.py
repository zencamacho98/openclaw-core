# app/shadow_runner.py
#
# Shadow mode runner for THE ABODE.
#
# Generates order intents from live market data and strategy logic
# WITHOUT routing them to the broker. Records each intent and produces
# a post-mortem at end-of-day comparing predicted to plausible realized outcomes.
#
# Shadow mode is Stage 3 in the readiness ladder. It exists to verify
# that Belfort's logic, cost estimates, and market understanding are
# realistic before any live orders are placed.
#
# Intents are stored in data/orders/ with environment="shadow".
# Post-mortems are stored in data/shadow_postmortems/YYYY-MM-DD.jsonl.
#
# Public API:
#   record_intent(symbol, side, qty, order_type, quote, rationale)  → str (intent_id)
#   generate_postmortem(date)  → PostMortem
#   get_today_intents()        → list[dict]
#   shadow_summary()           → dict

from __future__ import annotations

import json
import pathlib
import uuid
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timezone
from typing import Literal

_ROOT       = pathlib.Path(__file__).resolve().parent.parent
_POSTMORTEMS = _ROOT / "data" / "shadow_postmortems"

SideType  = Literal["buy", "sell"]


@dataclass
class ShadowIntent:
    intent_id:           str
    timestamp_utc:       str
    symbol:              str
    side:                SideType
    qty:                 float
    order_type:          str
    observed_bid:        float | None
    observed_ask:        float | None
    observed_spread_pct: float | None
    midpoint:            float | None
    session_type:        str
    data_lane:           str
    cost_estimate:       dict | None
    rationale:           str
    invalidation_conditions: list[str]


@dataclass
class PostMortemLine:
    intent_id:          str
    symbol:             str
    side:               str
    qty:                float
    order_type:         str
    intent_price:       float | None    # midpoint or ask/bid at decision time
    session_type:       str
    data_lane:          str
    cost_estimate_usd:  float | None
    frictions_dominant: str             # "spread" | "slippage" | "no_fill_risk" | "none"
    rationale:          str
    note:               str             # what would likely have happened


@dataclass
class PostMortem:
    date:             str
    intents:          int
    completed_lines:  list[PostMortemLine] = field(default_factory=list)
    summary:          str = ""
    data_lanes:       list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date":            self.date,
            "intents":         self.intents,
            "summary":         self.summary,
            "data_lanes":      self.data_lanes,
            "lines":           [asdict(l) for l in self.completed_lines],
        }


# ── Record an intent ──────────────────────────────────────────────────────────

def record_intent(
    symbol:      str,
    side:        SideType,
    qty:         float,
    order_type:  str,
    quote:       object | None        = None,  # QuoteEvent
    rationale:   str                  = "",
    invalidation_conditions: list[str] | None = None,
    cost_estimate: dict | None        = None,
) -> str:
    """
    Record a shadow order intent (no order placed).
    Returns the intent_id for tracking.
    """
    from app.market_time import session_type as get_session_type
    from app.market_data_feed import DATA_LANE

    intent_id = str(uuid.uuid4())[:16]
    ts        = datetime.now(timezone.utc).isoformat()
    stype     = get_session_type()

    bid = ask = spread_pct = midpoint = None
    lane = DATA_LANE

    if quote is not None:
        bid        = getattr(quote, "bid", None)
        ask        = getattr(quote, "ask", None)
        spread_pct = getattr(quote, "spread_pct", None)
        midpoint   = getattr(quote, "midpoint", None)
        lane       = getattr(quote, "data_lane", DATA_LANE)

    intent = ShadowIntent(
        intent_id            = intent_id,
        timestamp_utc        = ts,
        symbol               = symbol.upper(),
        side                 = side,
        qty                  = qty,
        order_type           = order_type,
        observed_bid         = bid,
        observed_ask         = ask,
        observed_spread_pct  = spread_pct,
        midpoint             = midpoint,
        session_type         = stype,
        data_lane            = lane,
        cost_estimate        = cost_estimate,
        rationale            = rationale,
        invalidation_conditions = invalidation_conditions or [],
    )

    # Write to order ledger with environment="shadow"
    try:
        from app.order_ledger import append
        append(
            event_type   = "intent",
            order_id     = intent_id,
            environment  = "shadow",
            symbol       = intent.symbol,
            side         = side,
            qty          = qty,
            order_type   = order_type,
            data_lane    = lane,
            session_type = stype,
            cost_estimate = cost_estimate,
            rationale    = rationale,
            extra        = {
                "observed_bid":  bid,
                "observed_ask":  ask,
                "spread_pct":    spread_pct,
                "midpoint":      midpoint,
                "invalidation_conditions": invalidation_conditions or [],
            },
        )
    except Exception:
        pass

    return intent_id


# ── Post-mortem generation ─────────────────────────────────────────────────────

def generate_postmortem(day: str | None = None) -> PostMortem:
    """
    Build a post-mortem for the given trading day (default: today).
    Reads all shadow intents for that day and produces an analysis.

    Since we have no live fill data to compare against, the analysis is
    based on the observed quote context at decision time and the cost model.
    """
    day = day or date.today().isoformat()

    try:
        from app.order_ledger import replay
        records = [
            r for r in replay(date_from=day, date_to=day, environment="shadow")
            if r.get("event_type") == "intent"
        ]
    except Exception:
        records = []

    lines: list[PostMortemLine] = []
    lanes: set[str] = set()

    for r in records:
        symbol      = r.get("symbol", "")
        side        = r.get("side", "")
        qty         = r.get("qty", 0.0)
        order_type  = r.get("order_type", "market")
        session     = r.get("session_type", "unknown")
        data_lane   = r.get("data_lane", "UNKNOWN")
        lanes.add(data_lane)

        extra        = r.get("extra", {}) or {}
        bid          = extra.get("observed_bid")
        ask          = extra.get("observed_ask")
        spread_pct   = extra.get("spread_pct")
        midpoint     = extra.get("midpoint")
        cost_est     = r.get("cost_estimate")
        cost_total   = cost_est.get("total_estimated_cost_usd") if cost_est else None
        intent_price = ask if side == "buy" else bid  # what market order would have paid

        # Assess dominant friction
        frictions = _assess_frictions(session, data_lane, spread_pct)

        note = _build_note(
            symbol=symbol, side=side, qty=qty, order_type=order_type,
            session=session, data_lane=data_lane,
            bid=bid, ask=ask, spread_pct=spread_pct, cost_total=cost_total,
            frictions=frictions,
        )

        lines.append(PostMortemLine(
            intent_id         = r.get("order_id", ""),
            symbol            = symbol,
            side              = side,
            qty               = qty,
            order_type        = order_type,
            intent_price      = intent_price,
            session_type      = session,
            data_lane         = data_lane,
            cost_estimate_usd = cost_total,
            frictions_dominant = frictions,
            rationale         = r.get("rationale", ""),
            note              = note,
        ))

    summary = (
        f"Shadow post-mortem for {day}: {len(lines)} intent(s). "
        + (f"Data lanes: {', '.join(sorted(lanes))}." if lanes else "No data lanes recorded.")
    )

    pm = PostMortem(
        date            = day,
        intents         = len(lines),
        completed_lines = lines,
        summary         = summary,
        data_lanes      = sorted(lanes),
    )

    _write_postmortem(pm, day)
    return pm


def _assess_frictions(session: str, data_lane: str, spread_pct: float | None) -> str:
    if session in ("pre_market", "after_hours"):
        return "extended_hours_wide_spread"
    if data_lane == "IEX_ONLY":
        return "data_lane_uncertainty"
    if spread_pct is not None and spread_pct > 0.005:
        return "wide_spread"
    if spread_pct is not None and spread_pct > 0.001:
        return "spread"
    return "none"


def _build_note(
    symbol: str, side: str, qty: float, order_type: str,
    session: str, data_lane: str,
    bid: float | None, ask: float | None, spread_pct: float | None,
    cost_total: float | None, frictions: str,
) -> str:
    parts: list[str] = []

    if order_type == "market":
        ref_price = ask if side == "buy" else bid
        if ref_price:
            parts.append(f"Market {side} {qty} {symbol}: would have filled near ${ref_price:.4f} (bid/ask, not last-trade).")
        else:
            parts.append(f"Market {side} {qty} {symbol}: quote data unavailable at decision time.")
    else:
        parts.append(f"Limit {side} {qty} {symbol}: fill not guaranteed.")

    if session in ("pre_market", "after_hours"):
        parts.append("Extended hours: significantly wider spreads and lower liquidity likely dominated execution quality.")
    if data_lane == "IEX_ONLY":
        parts.append("IEX-only data: NBBO may have differed; fill quality estimate is uncertain.")
    if spread_pct is not None:
        parts.append(f"Observed spread: {spread_pct*100:.3f}% of midpoint.")
    if cost_total is not None:
        parts.append(f"Estimated round-trip cost: ${cost_total:.4f}.")

    return " ".join(parts)


def _write_postmortem(pm: PostMortem, day: str) -> None:
    try:
        _POSTMORTEMS.mkdir(parents=True, exist_ok=True)
        path = _POSTMORTEMS / f"{day}.json"
        path.write_text(json.dumps(pm.to_dict(), indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Queries ───────────────────────────────────────────────────────────────────

def get_today_intents() -> list[dict]:
    """Return today's shadow intents from the order ledger."""
    try:
        from app.order_ledger import replay
        return [
            r for r in replay(environment="shadow")
            if r.get("event_type") == "intent"
        ]
    except Exception:
        return []


def get_postmortem(day: str | None = None) -> dict | None:
    """Load a previously written post-mortem JSON for the given day."""
    day = day or date.today().isoformat()
    path = _POSTMORTEMS / f"{day}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def shadow_summary() -> dict:
    """Summary of shadow activity for Peter reports."""
    today    = date.today().isoformat()
    intents  = get_today_intents()
    pm       = get_postmortem(today)

    # Count available post-mortems
    pm_count = 0
    if _POSTMORTEMS.exists():
        pm_count = len(list(_POSTMORTEMS.glob("*.json")))

    return {
        "today_intents":      len(intents),
        "postmortems_total":  pm_count,
        "today_postmortem":   pm is not None,
        "today":              today,
    }
