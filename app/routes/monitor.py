import hashlib
import json
import pathlib
from datetime import datetime, timezone

from fastapi import APIRouter, Body
from app.portfolio import get_snapshot, get_trades
from app.report import compute_report
from app.state import manager
from app.strategy.simple_strategy import get_state as strategy_state

router = APIRouter(prefix="/monitor")

_DISMISS_FILE = pathlib.Path("data/strategy_rec_dismiss.json")
_DISMISS_TTL_HOURS = 48


def _rec_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _read_dismiss() -> dict:
    if not _DISMISS_FILE.exists():
        return {}
    try:
        return json.loads(_DISMISS_FILE.read_text())
    except Exception:
        return {}


def _is_dismissed(rec_text: str) -> tuple[bool, str | None]:
    """Return (dismissed, dismissed_at_iso) for the given recommendation text."""
    if not rec_text:
        return False, None
    d = _read_dismiss()
    if d.get("hash") != _rec_hash(rec_text):
        return False, None
    dismissed_at = d.get("dismissed_at", "")
    try:
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(dismissed_at)).total_seconds() / 3600
        if age_h > _DISMISS_TTL_HOURS:
            return False, None
    except Exception:
        return False, None
    return True, dismissed_at


@router.get("/portfolio")
def portfolio():
    return get_snapshot()


@router.get("/trades")
def trades(n: int | None = None):
    return get_trades(limit=n)


@router.get("/agents")
def agents():
    return manager.get_agents()


@router.get("/report")
def report():
    return compute_report()


def _resolved_symbol(symbol: str | None) -> str:
    raw = str(symbol or "").strip().upper()
    if raw:
        return raw
    try:
        from app.belfort_scanner import get_focus_symbol
        return get_focus_symbol(default="SPY")
    except Exception:
        return "SPY"


@router.get("/strategy")
def strategy(symbol: str | None = None):
    target = _resolved_symbol(symbol)
    try:
        from app.belfort_policy import get_live_policy_state
        return get_live_policy_state(target)
    except Exception:
        return strategy_state(target)


@router.get("/analysis")
def analysis():
    # Lazy import — only loads (and charges) when endpoint is called
    from app.agents.analyzer import run_analysis
    return run_analysis()


@router.get("/decision")
def decision():
    from app.agents.analyzer import run_analysis, get_cached_analysis
    from app.agents.decision_engine import evaluate
    from app import tuning_log

    cached = get_cached_analysis()

    if cached:
        # Cache hit: no OpenRouter call, no new log entry
        analyzer_output = cached["result"]
        cache_used = True
        cached_at = cached["cached_at"]
    else:
        # Cache miss: call OpenRouter, log the result
        analyzer_output = run_analysis()
        cache_used = False
        cached_at = None

    decision_output = evaluate(analyzer_output)

    # Log only fresh decisions (cache miss) with valid analysis
    if not cache_used and "error" not in analyzer_output:
        from app.belfort_policy import get_live_policy_state
        focus_symbol = _resolved_symbol(None)
        pol = get_live_policy_state(focus_symbol)
        strategy_name = (
            f"Belfort {pol.get('active_policy', 'policy')} "
            f"[{pol.get('market_regime', 'unknown')}] "
            f"{focus_symbol}"
        )
        tuning_log.append(
            analysis=analyzer_output,
            decision=decision_output,
            strategy_name=strategy_name,
        )

    return {
        "analysis":        analyzer_output,
        "decision":        decision_output,
        "cache_used":      cache_used,
        "cached_at":       cached_at,
        "action_type":     decision_output.get("action_type"),
        "confidence_score": decision_output.get("confidence_score"),
        "parameter_suggestion": analyzer_output.get("suggested_improvement"),
    }


@router.get("/recommendations")
def recommendations(n: int = 20):
    from app import tuning_log
    return tuning_log.get_recent(n)


@router.get("/patterns")
def patterns(n: int = 20):
    from app.pattern_aggregator import summarize
    return summarize(n)


@router.get("/trading/status")
def trading_status():
    from app.trading_loop import get_status
    return get_status()


@router.post("/trading/start")
def trading_start(interval: int = 3):
    from app.trading_loop import start_trading
    return start_trading(interval)


@router.post("/trading/stop")
def trading_stop(close_positions: bool = True):
    from app.trading_loop import stop_trading
    flatten_result = None
    if close_positions:
        try:
            from app.belfort_paper_exec import flatten_paper_positions
            flatten_result = flatten_paper_positions("Operator stopped the paper lane and requested a full flatten.")
        except Exception as exc:
            flatten_result = {"status": "error", "message": f"Could not flatten open paper positions: {exc}"}
    result = stop_trading()
    if flatten_result:
        result["flatten"] = flatten_result
        if flatten_result.get("submitted", 0):
            result["message"] = (
                flatten_result.get("message")
                or "Close-all exit orders were submitted while the paper lane stops."
            )
        elif flatten_result.get("status") == "blocked":
            result["message"] = flatten_result.get("message") or result.get("message", "")
    return result


@router.post("/trading/flatten")
def trading_flatten():
    from app.belfort_paper_exec import flatten_paper_positions
    return flatten_paper_positions("Operator requested close-all on the paper book.")


@router.post("/trading/sim/start")
def sim_start(interval: int = 5):
    from app.belfort_sim import start_sim
    return start_sim(interval)


@router.post("/trading/sim/stop")
def sim_stop():
    from app.belfort_sim import stop_sim
    return stop_sim()


@router.get("/trading/sim/status")
def sim_status():
    from app.belfort_sim import get_sim_status
    return get_sim_status()


@router.get("/scanner")
def scanner():
    from app.belfort_scanner import read_scanner_snapshot
    return read_scanner_snapshot()


@router.get("/chart")
def chart(symbol: str | None = None, timeframe: str = "5Min", limit: int = 32):
    from app.market_data_feed import get_recent_bars

    target = _resolved_symbol(symbol)
    bars = get_recent_bars(target, timeframe=timeframe, limit=limit)
    latest = bars[-1] if bars else {}
    previous_close = bars[-2]["close"] if len(bars) > 1 else latest.get("open")
    try:
        last_close = float(latest.get("close", 0.0) or 0.0)
    except (TypeError, ValueError):
        last_close = 0.0
    try:
        prev_close = float(previous_close or 0.0)
    except (TypeError, ValueError):
        prev_close = 0.0
    change = (last_close - prev_close) if (last_close and prev_close) else 0.0
    change_pct = (change / prev_close) if prev_close else 0.0
    return {
        "symbol": target,
        "timeframe": timeframe,
        "bars": bars,
        "last_close": last_close,
        "change": round(change, 6),
        "change_pct": round(change_pct, 6),
        "bar_count": len(bars),
    }


@router.post("/belfort/mode/advance")
def belfort_mode_advance():
    """
    Advance Belfort's operating mode one step (observation→shadow→paper).
    LIVE is not reachable from this endpoint — requires human sign-off.
    Gate-checked by the existing can_advance_to() logic.
    """
    from app.belfort_mode import current_mode, set_mode, BelfortMode, _ORDER, _index
    cur     = current_mode()
    cur_idx = _index(cur)
    # Never advance to LIVE from the UI
    if cur_idx >= len(_ORDER) - 2:
        return {
            "ok":    False,
            "mode":  cur.value,
            "error": "Already at Paper mode. LIVE requires a human sign-off file and is not accessible from the UI.",
        }
    next_mode = _ORDER[cur_idx + 1]
    if next_mode == BelfortMode.LIVE:
        return {
            "ok":    False,
            "mode":  cur.value,
            "error": "Cannot advance to LIVE from the neighborhood UI. Use the sign-off process.",
        }
    return set_mode(
        next_mode,
        reason="Operator advanced mode via neighborhood UI",
        initiated_by="neighborhood_ui",
    )


@router.post("/trading/reset")
def trading_reset(body: dict = Body(default={})):
    from app.portfolio import reset_portfolio
    body   = body or {}
    reason = body.get("reason", "Operator reset from neighborhood")

    # Capture pre-reset stats BEFORE wiping — used for baseline comparison display.
    prev_portfolio = None
    try:
        from app.routes.belfort_readiness import _compute_win_rate
        prev_snap = get_snapshot()
        prev_wr   = _compute_win_rate()
        prev_portfolio = {
            "trade_count":   prev_snap.get("trade_count", 0),
            "realized_pnl":  prev_snap.get("realized_pnl", 0.0),
            "cash":          prev_snap.get("cash", 100_000.0),
            "win_rate":      prev_wr.get("win_rate"),
            "wins":          prev_wr.get("wins", 0),
            "losses":        prev_wr.get("losses", 0),
            "total_closed":  prev_wr.get("total_closed", 0),
        }
    except Exception:
        pass

    # Write learning snapshot for the session being ended (before wipe).
    try:
        from app.routes.belfort_learning import _build_snapshot
        from app.routes.belfort_memory import append_snapshot
        snap_entry = _build_snapshot()
        if snap_entry:
            append_snapshot(snap_entry)
    except Exception:
        pass

    result = reset_portfolio(reason)

    # Record adoption context so the readiness scorecard can track clean eval windows.
    try:
        from app.routes.belfort_readiness import write_baseline_record
        write_baseline_record(
            reason=reason,
            strategy_label=body.get("strategy_label", ""),
            prev_portfolio=prev_portfolio,
        )
    except Exception:
        pass
    return result


@router.get("/loop")
def loop_status():
    import app.loop as _loop
    return {"running": _loop.running}


@router.post("/cache/clear")
def cache_clear():
    from app.agents.analyzer import clear_cache
    clear_cache()
    return {"cleared": True}


@router.get("/config")
def strategy_config():
    from app.strategy.config import get_config
    return get_config()


@router.get("/regime")
def regime_state(symbol: str | None = None):
    target = _resolved_symbol(symbol)
    from app.belfort_policy import get_live_policy_state
    return get_live_policy_state(target)


@router.post("/tuning/apply")
def tuning_apply(proposal: dict):
    from app.strategy.applier import apply
    try:
        return apply(proposal)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/candidate/apply")
def candidate_apply(body: dict = Body(default={})):
    from app.strategy.applier import promote_from_record
    from observability.agent_state import transition, MR_BELFORT, STATUS_IDLE
    from fastapi import HTTPException
    record_path = (body or {}).get("record_path", "")
    reason = (body or {}).get("reason", "Operator applied from UI")
    if not record_path:
        raise HTTPException(status_code=400, detail="record_path is required.")
    try:
        result = promote_from_record(record_path, reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        transition(
            MR_BELFORT,
            agent_role="trading_agent",
            status=STATUS_IDLE,
            last_completed_action=f"Candidate promoted: {result['experiment_name']}",
        )
    except Exception:
        pass
    return result


@router.get("/tuning/changelog")
def tuning_changelog(n: int = 20):
    from app.strategy.changelog import get_recent
    return get_recent(n)


@router.post("/experiment/run")
def experiment_run(body: dict = Body(default={})):
    from app.experiment import run as _run
    try:
        return _run(
            n_ticks=int(body.get("ticks", 500)),
            param_overrides=body.get("params", {}),
            seed=body.get("seed"),
            save=bool(body.get("save", True)),
        )
    except (ValueError, TypeError) as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/experiment/compare")
def experiment_compare(body: dict = Body(default={})):
    from app.experiment import compare as _compare
    try:
        return _compare(
            n_ticks=int(body.get("ticks", 500)),
            variants=body.get("variants", [{}]),
            seed=body.get("seed"),
            save=bool(body.get("save", True)),
        )
    except (ValueError, TypeError) as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/experiment/results")
def experiment_results(n: int = 10):
    from app.experiment import get_saved
    return get_saved(n)


@router.get("/proposal")
def proposal(n: int = 20):
    from app.pattern_aggregator import summarize
    from app.proposal_parser import parse

    agg = summarize(n)
    rec_text = agg.get("most_common_recommendation") or ""

    parsed = parse(
        recommendation=rec_text,
        confidence_trend=agg.get("confidence_trend", "stable"),
        occurrences=agg.get("occurrences", 0),
        records_analyzed=agg.get("records_analyzed", 0),
    )

    dismissed, dismissed_at = _is_dismissed(rec_text)

    return {
        "proposal": parsed,
        "source": {
            "most_common_recommendation": rec_text,
            "occurrences": agg.get("occurrences"),
            "records_analyzed": agg.get("records_analyzed"),
            "confidence_trend": agg.get("confidence_trend"),
        },
        "applied": False,  # always False — proposals are never auto-applied
        "dismissed": dismissed,
        "dismissed_at": dismissed_at,
    }


@router.post("/proposal/apply")
def proposal_apply():
    """Apply the current parsed proposal. Operator-initiated only."""
    from app.pattern_aggregator import summarize
    from app.proposal_parser import parse
    from app.strategy.applier import apply
    from fastapi import HTTPException

    agg = summarize(20)
    rec_text = agg.get("most_common_recommendation") or ""
    parsed = parse(
        recommendation=rec_text,
        confidence_trend=agg.get("confidence_trend", "stable"),
        occurrences=agg.get("occurrences", 0),
        records_analyzed=agg.get("records_analyzed", 0),
    )
    if not parsed:
        raise HTTPException(status_code=400, detail="No actionable proposal available.")
    try:
        result = apply(parsed)
        # Clear any existing dismiss since it's now applied
        if _DISMISS_FILE.exists():
            _DISMISS_FILE.unlink()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/proposal/dismiss")
def proposal_dismiss():
    """Dismiss the current recommendation. It won't reappear until the text changes or 48h pass."""
    from app.pattern_aggregator import summarize
    from fastapi import HTTPException

    agg = summarize(20)
    rec_text = agg.get("most_common_recommendation") or ""
    if not rec_text:
        raise HTTPException(status_code=400, detail="No active recommendation to dismiss.")
    now = datetime.now(timezone.utc).isoformat()
    _DISMISS_FILE.parent.mkdir(exist_ok=True)
    _DISMISS_FILE.write_text(json.dumps({
        "hash": _rec_hash(rec_text),
        "recommendation_text": rec_text,
        "dismissed_at": now,
    }))
    return {"dismissed": True, "dismissed_at": now}
