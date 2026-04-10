from fastapi import APIRouter, Body
from app.portfolio import get_snapshot, get_trades
from app.report import compute_report
from app.state import manager
from app.strategy.simple_strategy import get_state as strategy_state

router = APIRouter(prefix="/monitor")


@router.get("/portfolio")
def portfolio():
    return get_snapshot()


@router.get("/trades")
def trades():
    return get_trades()


@router.get("/agents")
def agents():
    return manager.get_agents()


@router.get("/report")
def report():
    return compute_report()


@router.get("/strategy")
def strategy(symbol: str = "SPY"):
    return strategy_state(symbol)


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
        from app.strategy.config import get_config as _get_cfg
        cfg = _get_cfg()
        strategy_name = f"MA Crossover (short={cfg['SHORT_WINDOW']}, long={cfg['LONG_WINDOW']})"
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
def trading_stop():
    from app.trading_loop import stop_trading
    return stop_trading()


@router.post("/trading/reset")
def trading_reset(body: dict = Body(default={})):
    from app.portfolio import reset_portfolio
    reason = (body or {}).get("reason", "Operator reset from neighborhood")
    return reset_portfolio(reason)


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
def regime_state(symbol: str = "SPY"):
    from app.strategy.router import get_state as router_state
    return router_state(symbol)


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

    parsed = parse(
        recommendation=agg.get("most_common_recommendation") or "",
        confidence_trend=agg.get("confidence_trend", "stable"),
        occurrences=agg.get("occurrences", 0),
        records_analyzed=agg.get("records_analyzed", 0),
    )

    return {
        "proposal": parsed,
        "source": {
            "most_common_recommendation": agg.get("most_common_recommendation"),
            "occurrences": agg.get("occurrences"),
            "records_analyzed": agg.get("records_analyzed"),
            "confidence_trend": agg.get("confidence_trend"),
        },
        "applied": False,  # always False — proposals are never auto-applied
    }
