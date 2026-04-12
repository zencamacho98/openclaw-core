# app/routes/market.py
#
# Market layer API endpoints for THE ABODE.
#
# Exposes the market observation, cost engine, order ledger, reconciliation,
# shadow runner, kill switch, and readiness scorecard via FastAPI routes.
#
# Endpoints:
#   GET  /market/status              — feed status, session type, data lane
#   GET  /market/quote/{symbol}      — L1 quote with data_lane label
#   GET  /market/spread/{symbol}     — today's spread summary for symbol
#   POST /market/observe/{symbol}    — fetch quote and record spread observation
#   GET  /market/cost                — estimate order cost (query params)
#   GET  /market/session             — current session type and warnings
#   GET  /market/orders/today        — today's order ledger summary
#   GET  /market/orders/replay       — replay order events (date range)
#   GET  /market/reconcile           — run reconciliation now
#   GET  /market/reconcile/status    — last reconciliation report
#   POST /market/shadow/intent       — record a shadow intent (no order placed)
#   POST /market/shadow/postmortem   — generate today's post-mortem
#   GET  /market/shadow/summary      — shadow activity summary
#   POST /market/kill                — engage kill switch
#   GET  /market/readiness           — evaluate readiness scorecard

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/market")


# ── Feed and session status ───────────────────────────────────────────────────

@router.get("/status")
def market_status() -> dict:
    """Aggregated market layer status: feed, session, data lane."""
    try:
        import json
        import pathlib
        from app.market_data_feed import feed_status, DATA_LANE
        from app.market_time import session_summary
        from app.broker_connector import connector_status
        from app.reconciler import is_halted

        feed   = feed_status()
        sess   = session_summary()
        broker = connector_status()
        halted = is_halted()

        snapshot = {
            "feed":    feed.to_dict(),
            "session": sess,
            "broker":  broker,
            "data_lane": DATA_LANE,
            "data_lane_disclaimer": (
                "IEX-only: single-venue data. Spreads and fill estimates are not NBBO-representative."
                if DATA_LANE == "IEX_ONLY" else ""
            ),
            # Flat keys read by Peter's observability bridge
            "session_type":           sess.get("session_type", "unknown"),
            "extended_hours_warning": sess.get("extended_hours_warning", ""),
            "feed_live":              feed.has_credentials and feed.connected,
            "broker_available":       broker.get("available", False),
            "broker_env":             broker.get("environment", "unknown"),
            "broker_message":         broker.get("message", ""),
            "trading_halted":         halted,
        }

        # Persist for Peter's disk-reading handler
        _status_path = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "market_status.json"
        _status_path.parent.mkdir(parents=True, exist_ok=True)
        _status_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

        return snapshot
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/session")
def session_info() -> dict:
    from app.market_time import session_summary
    return session_summary()


# ── Quotes and observations ───────────────────────────────────────────────────

@router.get("/quote/{symbol}")
def get_quote(symbol: str) -> dict:
    """Fetch a live L1 quote. data_lane is always present in the response."""
    from app.market_data_feed import get_quote as _get_quote
    return _get_quote(symbol.upper()).to_dict()


@router.post("/observe/{symbol}")
def observe_symbol(symbol: str) -> dict:
    """Fetch a quote and record it as a spread observation."""
    from app.market_data_feed import get_quote as _get_quote
    from app.spread_monitor import record_quote

    quote = _get_quote(symbol.upper())
    obs   = record_quote(quote)
    return {"quote": quote.to_dict(), "observation": obs.to_dict()}


@router.get("/spread/{symbol}")
def spread_summary(symbol: str, day: str | None = Query(None)) -> dict:
    """Today's spread summary for a symbol (by session type)."""
    from app.spread_monitor import get_daily_summary
    return get_daily_summary(symbol.upper(), day)


# ── Cost estimation ───────────────────────────────────────────────────────────

@router.get("/cost")
def estimate_cost(
    symbol:        str   = Query(...),
    side:          str   = Query(..., pattern="^(buy|sell)$"),
    qty:           float = Query(..., gt=0),
    price:         float = Query(..., gt=0),
    broker:        str   = Query("alpaca_retail"),
    order_type:    str   = Query("market"),
) -> dict:
    """
    Estimate trading cost for a hypothetical order.
    Uses current session type and configured data lane automatically.
    """
    from app.cost_engine import estimate
    from app.market_time import session_type
    from app.market_data_feed import DATA_LANE

    est = estimate(
        symbol         = symbol.upper(),
        side           = side,          # type: ignore[arg-type]
        qty            = qty,
        price          = price,
        broker_profile = broker,
        session_type   = session_type(), # type: ignore[arg-type]
        data_lane      = DATA_LANE,
        order_type     = order_type,
    )
    return est.to_dict()


# ── Order ledger ──────────────────────────────────────────────────────────────

@router.get("/orders/today")
def orders_today(environment: str | None = Query(None)) -> dict:
    from app.order_ledger import get_today_summary
    env = environment  # type: ignore[assignment]
    return get_today_summary(env)  # type: ignore[arg-type]


@router.get("/orders/replay")
def orders_replay(
    date_from: str | None = Query(None),
    date_to:   str | None = Query(None),
    environment: str | None = Query(None),
) -> list:
    from app.order_ledger import replay
    return replay(date_from, date_to, environment)  # type: ignore[arg-type]


# ── Reconciliation ────────────────────────────────────────────────────────────

@router.post("/reconcile")
def run_reconcile(environment: str = Query("paper")) -> dict:
    from app.reconciler import run_reconciliation
    report = run_reconciliation(environment)  # type: ignore[arg-type]
    return report.to_dict()


@router.get("/reconcile/status")
def reconcile_status() -> dict:
    from app.reconciler import get_last_report, is_halted
    report = get_last_report()
    return {
        "halted":      is_halted(),
        "last_report": report.to_dict() if report else None,
    }


# ── Shadow mode ───────────────────────────────────────────────────────────────

@router.post("/shadow/intent")
def record_shadow_intent(body: dict) -> dict:
    """
    Record a shadow order intent. Does NOT place any order.
    Body: {symbol, side, qty, order_type, rationale, invalidation_conditions?}
    """
    from app.shadow_runner import record_intent
    intent_id = record_intent(
        symbol       = body.get("symbol", ""),
        side         = body.get("side", "buy"),      # type: ignore[arg-type]
        qty          = float(body.get("qty", 0)),
        order_type   = body.get("order_type", "market"),
        rationale    = body.get("rationale", ""),
        invalidation_conditions = body.get("invalidation_conditions"),
    )
    return {"intent_id": intent_id, "environment": "shadow", "routed": False}


@router.post("/shadow/postmortem")
def generate_shadow_postmortem(day: str | None = Query(None)) -> dict:
    from app.shadow_runner import generate_postmortem
    pm = generate_postmortem(day)
    return pm.to_dict()


@router.get("/shadow/summary")
def shadow_summary_route() -> dict:
    from app.shadow_runner import shadow_summary
    return shadow_summary()


# ── Kill switch ───────────────────────────────────────────────────────────────

@router.post("/kill")
def engage_kill_switch(reason: str = Query("operator_request"), environment: str = Query("paper")) -> dict:
    from app.kill_switch import engage
    result = engage(reason=reason, environment=environment)
    return {
        "engaged":          result.engaged,
        "reason":           result.reason,
        "cancelled_orders": result.cancelled_orders,
        "cancel_errors":    result.cancel_errors,
        "timestamp_utc":    result.timestamp_utc,
    }


@router.get("/kill/status")
def kill_switch_status() -> dict:
    from app.kill_switch import get_status
    return get_status()


# ── Readiness scorecard ───────────────────────────────────────────────────────

@router.get("/readiness")
def readiness_scorecard() -> dict:
    from app.readiness_scorecard import evaluate
    result = evaluate()
    return result.to_dict()


@router.get("/readiness/last")
def readiness_last() -> dict:
    from app.readiness_scorecard import get_last_scorecard
    result = get_last_scorecard()
    if result is None:
        return {"level": "NOT_READY", "note": "No scorecard evaluated yet."}
    return result.to_dict()


@router.post("/readiness/signoff")
def record_signoff(reviewer: str = Query(...), notes: str = Query("")) -> dict:
    """
    Record human sign-off for live mode authorization.
    This endpoint must only be called by a human — it is not called automatically.
    """
    from app.readiness_scorecard import record_human_signoff
    record_human_signoff(reviewer=reviewer, notes=notes)
    return {"recorded": True, "reviewer": reviewer}
