# app/routes/neighborhood.py
#
# The Abode Neighborhood — pixel-style visual frontend shell.
#
# Serves the neighborhood HTML view and a state aggregation endpoint.
# This is a frontend layer on top of existing APIs — it does NOT replace
# the existing Streamlit dashboard, which remains the advanced control surface.
#
# Endpoints:
#   GET /neighborhood          — pixel-art neighborhood HTML page
#   GET /neighborhood/state    — aggregated agent/system state for the view

from __future__ import annotations

import json
import pathlib
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse

router = APIRouter()

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


# ── State aggregation ─────────────────────────────────────────────────────────

@router.get("/neighborhood/state")
def neighborhood_state() -> dict:
    """
    Aggregate all agent and system state for the neighborhood view.
    One call replaces many individual fetches.
    """
    return {
        "backend":      _backend_state(),
        "belfort":      _belfort_state(),
        "frank_lloyd":  _frank_lloyd_state(),
        "supervisor":   _supervisor_state(),
        "checker":      _checker_state(),
        "custodian":    _custodian_state(),
        "sentinel":     _sentinel_state(),
        "warden":       _warden_state(),
        "lm_available": _lm_available(),
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }


def _backend_state() -> dict:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


def _belfort_state() -> dict:
    try:
        from observability.agent_state import load_state, MR_BELFORT
        s = load_state(MR_BELFORT, "trading_researcher")
        base: dict = {
            "status":       s.status,
            "is_active":    s.actively_learning,
            "current_task": s.current_task,
            "campaign_id":  (s.campaign_id or "")[-20:] if s.campaign_id else None,
            "last_action":  s.last_completed_action,
            "last_heartbeat": s.last_heartbeat_at,
        }
    except Exception:
        base = {"status": "unknown", "is_active": False}

    try:
        from app.portfolio import get_snapshot, get_trades, positions as _positions
        snap = get_snapshot()
        base["cash"]           = snap.get("cash", 100000.0)
        base["realized_pnl"]   = snap.get("realized_pnl", 0.0)
        base["unrealized_pnl"] = snap.get("unrealized_pnl", 0.0)
        base["trade_count"]    = snap.get("trade_count", 0)
        base["open_positions"] = list(_positions.keys())[:4]
        trades_list = get_trades()
        if trades_list:
            lt = trades_list[-1]
            base["last_trade"] = {
                "symbol": lt.get("symbol"),
                "side":   lt.get("side"),
                "price":  lt.get("price"),
                "pnl":    lt.get("pnl"),
            }
        else:
            base["last_trade"] = None
    except Exception:
        base.update({"cash": 100000.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0,
                     "trade_count": 0, "open_positions": [], "last_trade": None})

    try:
        from app.trading_loop import get_status
        ts = get_status()
        base["trading_active"]   = ts.get("running", False)
        base["trading_stopping"] = ts.get("stop_requested", False)
    except Exception:
        base["trading_active"]   = False
        base["trading_stopping"] = False

    try:
        from observability.belfort_summary import (
            read_belfort_preflight, read_belfort_freshness_state,
            read_latest_signal_decision, read_belfort_mode,
            read_latest_paper_execution,
        )
        pf = read_belfort_preflight()
        fs = read_belfort_freshness_state()
        # Authoritative mode from state file — not from (possibly stale) preflight.
        base["belfort_mode"]            = read_belfort_mode()
        base["belfort_readiness"]       = pf.get("readiness_level", "NOT_READY")
        base["belfort_data_lane"]       = pf.get("data_lane", "UNKNOWN")
        base["belfort_ticks_today"]     = pf.get("observation_ticks_today", 0)
        base["belfort_can_advance"]     = pf.get("can_advance_to")
        base["belfort_freshness"]       = fs.get("freshness", "no_data")
        base["belfort_freshness_label"] = fs.get("freshness_label", "No observation data")
        base["belfort_latest_signal"]   = read_latest_signal_decision()
        base["belfort_latest_paper_exec"] = read_latest_paper_execution()
    except Exception:
        base["belfort_mode"]              = "observation"
        base["belfort_readiness"]         = "NOT_READY"
        base["belfort_data_lane"]         = "UNKNOWN"
        base["belfort_ticks_today"]       = 0
        base["belfort_can_advance"]       = None
        base["belfort_freshness"]         = "no_data"
        base["belfort_freshness_label"]   = "Preflight unavailable"
        base["belfort_latest_signal"]     = None
        base["belfort_latest_paper_exec"] = None

    return base


def _supervisor_state() -> dict:
    try:
        from app.supervisor import get_supervisor_state
        s = get_supervisor_state()
        return {
            "enabled":      s.get("enabled", False),
            "cycle_count":  s.get("cycle_count", 0),
            "stop_requested": s.get("stop_requested", False),
            "errors":       s.get("consecutive_start_errors", 0),
        }
    except Exception:
        return {"enabled": False, "cycle_count": 0}


def _checker_state() -> dict:
    try:
        from app.checker import read_findings
        findings = read_findings(limit=20, include_acknowledged=False)
        warnings = [f for f in findings if f.get("severity") == "warning"]
        return {"open_warnings": len(warnings), "total_findings": len(findings)}
    except Exception:
        return {"open_warnings": 0, "total_findings": 0}


def _custodian_state() -> dict:
    cache = _ROOT / "data" / "custodian_health.json"
    if not cache.exists():
        return {"overall": "unknown", "summary": "No check run yet."}
    try:
        d = json.loads(cache.read_text(encoding="utf-8"))
        return {"overall": d.get("overall", "unknown"), "summary": d.get("summary", "")}
    except Exception:
        return {"overall": "unknown", "summary": ""}


def _sentinel_state() -> dict:
    cache = _ROOT / "data" / "sentinel_report.json"
    if not cache.exists():
        return {"verdict": "unknown", "summary": "No check run yet."}
    try:
        d = json.loads(cache.read_text(encoding="utf-8"))
        return {
            "verdict": d.get("verdict", "unknown"),
            "passed":  d.get("passed", 0),
            "failed":  d.get("failed", 0),
        }
    except Exception:
        return {"verdict": "unknown", "passed": 0, "failed": 0}


def _lm_available() -> bool:
    """Return True if the OpenRouter API key is configured."""
    import os
    if os.getenv("OPENROUTER_API_KEY", ""):
        return True
    env_file = _ROOT / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENROUTER_API_KEY="):
                    return bool(line.split("=", 1)[1].strip())
        except Exception:
            pass
    return False


def _readiness_state() -> dict:
    """Brief readiness summary for Peter's LM context."""
    try:
        from app.routes.belfort_readiness import _gather_readiness
        d = _gather_readiness()
        return {
            "level":          d["level"],
            "level_label":    d["level_label"],
            "gates_passed":   d["gates_passed"],
            "gates_total":    d["gates_total"],
            "strategy":       d["strategy_description"],
            "last_adoption":  d["last_adoption_at"],
            "last_reset":     d["last_baseline_reset_at"],
            "trade_count":    d["trade_count"],
            "realized_pnl":   d["realized_pnl"],
            "win_rate":       d["win_rate"],
            "mentor_summary": d["mentor_summary"],
            "hours_running":  d["hours_since_reset"],
        }
    except Exception:
        return {"level": "unknown", "level_label": "UNKNOWN"}


def _warden_state() -> dict:
    log = _ROOT / "data" / "warden_usage.jsonl"
    if not log.exists():
        return {"total_calls": 0, "total_cost_usd": 0.0}
    try:
        lines = log.read_text(encoding="utf-8").splitlines()
        records = []
        for ln in reversed(lines):
            ln = ln.strip()
            if ln:
                try:
                    records.append(json.loads(ln))
                except Exception:
                    pass
                if len(records) >= 50:
                    break
        cost = sum(r.get("cost_usd", 0.0) for r in records)
        return {"total_calls": len(records), "total_cost_usd": round(cost, 6)}
    except Exception:
        return {"total_calls": 0, "total_cost_usd": 0.0}


def _frank_lloyd_state() -> dict:
    """
    Frank Lloyd status: pending/inprogress/completed build counts, active build,
    spec_approved build, stage2_authorized build, and draft build.
    """
    try:
        from app.routes.frank_lloyd_status import frank_lloyd_status
        result     = frank_lloyd_status()
        summary    = result.get("summary", {})
        pending    = result.get("pending_builds",    [])
        inprogress = result.get("inprogress_builds", [])
        completed  = result.get("completed_builds",  [])

        # In-progress builds are sorted newest-first; take first match per status.
        spec_approved_build = next(
            (b for b in inprogress if b.get("status") == "spec_approved"), None
        )
        stage2_authorized_build = next(
            (b for b in inprogress if b.get("status") == "stage2_authorized"), None
        )
        # draft_build: prioritise reviewable output (draft_generated) over blocked.
        draft_build = next(
            (b for b in inprogress if b.get("status") == "draft_generated"), None
        ) or next(
            (b for b in inprogress
             if b.get("status") in ("draft_blocked", "draft_generating")), None
        )
        promoted_build = next(
            (b for b in completed if b.get("status") == "draft_promoted"), None
        )

        # Check if any active build is about Belfort (for Belfort panel cross-reference)
        belfort_related_build = None
        active_candidates = (
            (pending[:1] if pending else [])
            + [b for b in inprogress if b]
        )
        req_dir = _ROOT / "data" / "frank_lloyd" / "requests"
        for bld in active_candidates:
            bid = (bld or {}).get("build_id")
            if not bid:
                continue
            req_file = req_dir / f"{bid}_request.json"
            if req_file.exists():
                try:
                    req_data = json.loads(req_file.read_text(encoding="utf-8"))
                    desc = (req_data.get("description") or "").lower()
                    if "belfort" in desc:
                        belfort_related_build = {
                            "build_id": bid,
                            "title":    bld.get("title", bid),
                            "status":   bld.get("status", ""),
                        }
                        break
                except Exception:
                    pass

        try:
            from frank_lloyd.job import load_active_job as _laj, list_jobs as _lj
            _aj = _laj()
            active_job = _aj.to_dict() if _aj else None
            # Last routing: from active job, or most recent job with routing info
            last_routing = (_aj.routing if _aj else None)
            if last_routing is None:
                try:
                    for _j in _lj():
                        if _j.routing:
                            last_routing = _j.routing
                            break
                except Exception:
                    pass
        except Exception:
            active_job   = None
            last_routing = None

        # Consume unread Peter relay messages from auto_runner
        fl_relay: list[dict] = []
        try:
            from frank_lloyd.relay import consume_unread as _consume
            fl_relay = _consume(max_messages=5)
        except Exception:
            pass

        return {
            "pending_count":           summary.get("pending_count",    0),
            "inprogress_count":        summary.get("inprogress_count", 0),
            "completed_count":         summary.get("completed_count",  0),
            "approved_count":          summary.get("approved_count",   0),
            "active_build":            pending[0] if pending else None,
            "stage":                   result.get("builder_stage", 1),
            "spec_approved_build":     spec_approved_build,
            "stage2_authorized_build": stage2_authorized_build,
            "draft_build":             draft_build,
            "promoted_build":          promoted_build,
            "belfort_related_build":   belfort_related_build,
            "active_job":              active_job,
            "fl_relay":                fl_relay,
            "last_routing":            last_routing,
        }
    except Exception:
        return {
            "pending_count":           0,
            "inprogress_count":        0,
            "completed_count":         0,
            "approved_count":          0,
            "active_build":            None,
            "stage":                   1,
            "spec_approved_build":     None,
            "stage2_authorized_build": None,
            "draft_build":             None,
            "promoted_build":          None,
            "belfort_related_build":   None,
            "active_job":              None,
            "fl_relay":                [],
            "last_routing":            None,
        }


@router.get("/neighborhood/docs")
def neighborhood_docs(file: str = "BRD.md") -> dict:
    """Read-only access to project docs. Allowlist: BRD.md, TRD.md, CAPABILITY_REGISTRY.md, CHANGE_JOURNAL.md."""
    from fastapi import HTTPException
    ALLOWED = {
        "BRD.md":                  "Business Requirements",
        "TRD.md":                  "Technical Design",
        "CAPABILITY_REGISTRY.md":  "Capability Registry",
        "CHANGE_JOURNAL.md":       "Change Journal",
    }
    if file not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"Unknown doc: {file}")
    path = _ROOT / "docs" / file
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Doc not found: {file}")
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"file": file, "label": ALLOWED[file], "content": content}


@router.post("/peter/chat")
async def peter_chat(body: dict = Body(default={})) -> dict:
    """
    LM-backed Peter chat. Accepts {message: str}, returns {ok: bool, text: str, error: str}.
    Peter answers questions about all Abode agents including Frank Lloyd.
    """
    from fastapi import HTTPException
    body = body or {}
    message = str(body.get("message", "")).strip()[:400]
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    # Build context that includes Frank Lloyd's active job
    fl_state = _frank_lloyd_state()
    fl_job = fl_state.get("active_job")
    fl_context: dict = {
        "pending_count":    fl_state.get("pending_count", 0),
        "inprogress_count": fl_state.get("inprogress_count", 0),
        "completed_count":  fl_state.get("completed_count", 0),
    }
    if fl_job:
        fl_context["active_job"] = {
            "build_id":   fl_job.get("build_id"),
            "title":      fl_job.get("title"),
            "status":     fl_job.get("status"),
            "phase":      fl_job.get("phase"),
            "next_action": fl_job.get("next_action"),
            "waiting_on": fl_job.get("waiting_on"),
            "risk_level": fl_job.get("risk_level"),
        }

    state = {
        "belfort":    _belfort_state(),
        "supervisor": _supervisor_state(),
        "checker":    _checker_state(),
        "custodian":  _custodian_state(),
        "sentinel":   _sentinel_state(),
        "warden":     _warden_state(),
        "readiness":  _readiness_state(),
        "frank_lloyd": fl_context,
    }
    ctx_str = json.dumps(state, separators=(",", ":"))

    system = (
        "You are Peter, the coordinator and front door for The Abode — an AI workforce operating environment. "
        "You monitor and report on all agents: Mr Belfort (trading/research), Frank Lloyd (builder/operator), "
        "and the backstage services (Custodian, Sentinel, Checker, Cost Warden). "
        "Answer the operator's question in plain English — 1 to 3 concise sentences. "
        "Be direct and specific. Use the system state context provided. "
        "When asked about Frank Lloyd, use the frank_lloyd field — report on the active build, "
        "what phase it's in, and what the operator should do next. "
        "When asked about Belfort's readiness or progress, use the 'readiness' field. "
        "Do not mention you are an AI or reference the JSON context."
    )
    user = f"System state:\n{ctx_str}\n\nOperator: {message}"

    try:
        from app.cost_warden import LMHelper
        result = LMHelper("peter", "health_explain", max_tokens=250, temperature=0.4).call(
            system=system, user=user,
        )
        if not result.ok:
            return {"ok": False, "text": "", "error": result.error}
        return {"ok": True, "text": result.content.strip(), "error": ""}
    except Exception as exc:
        return {"ok": False, "text": "", "error": str(exc)}


@router.post("/peter/action")
def peter_action(body: dict = Body(default={})) -> dict:
    """
    Execute a Peter command submitted via the neighborhood UI chat.

    Parses the message using peter.commands.parse_command() and routes through
    peter.router.route(). Covers all FL lifecycle actions (approve/reject/run/draft/
    promote/discard/status) as well as Belfort/system queries.

    Body: {message: str}
    Returns: {ok, summary, command_type, next_action, build_id}
    """
    from peter.commands import parse_command
    from peter.router   import route

    message = (body.get("message") or "").strip()[:500]
    if not message:
        return {"ok": False, "summary": "No message provided.", "command_type": "unknown"}

    try:
        cmd  = parse_command(message, transport="cli", operator_id="neighborhood_ui")
        resp = route(cmd)
        return {
            "ok":           resp.ok,
            "summary":      resp.summary,
            "command_type": resp.command_type,
            "next_action":  resp.next_action or "",
            "build_id":     (resp.raw or {}).get("build_id", "") or (resp.metrics or {}).get("build_id", ""),
        }
    except Exception as exc:
        return {"ok": False, "summary": f"Action failed: {exc}", "command_type": "error"}


@router.post("/peter/queue-build")
def peter_queue_build(body: dict = Body(default={})) -> dict:
    """
    Queue a Frank Lloyd build via Peter's chat. Uses brief_shaper for smart intake.

    Accepts {message: str}. Uses frank_lloyd.brief_shaper to shape the input,
    then queues via frank_lloyd.request_writer and fires the safe-lane pipeline.

    Returns: {ok, queued, build_id, text, needs_clarification, question}
    """
    from fastapi import BackgroundTasks
    import frank_lloyd.brief_shaper   as _shaper
    import frank_lloyd.request_writer as _fl_rw

    message = (body.get("message") or "").strip()[:2000]
    if not message:
        return {"ok": False, "queued": False, "text": "No message provided.",
                "needs_clarification": False}

    brief = _shaper.shape(message)

    if brief.needs_clarification:
        return {
            "ok":                  False,
            "queued":              False,
            "build_id":            None,
            "needs_clarification": True,
            "text":                brief.clarification_question or "Could you be more specific?",
        }

    missing = _fl_rw.readiness_check(brief.description, brief.success_criterion)
    if missing:
        return {
            "ok":                  False,
            "queued":              False,
            "build_id":            None,
            "needs_clarification": True,
            "text":                "Could you describe that in a bit more detail?",
        }

    result = _fl_rw.queue_build(
        description=brief.description,
        success_criterion=brief.success_criterion,
        source="peter_chat_smart",
    )
    if not result["ok"]:
        return {"ok": False, "queued": False, "build_id": None,
                "text": result["error"], "needs_clarification": False}

    build_id = result["build_id"]
    title    = result["title"]

    return {
        "ok":                  True,
        "queued":              True,
        "build_id":            build_id,
        "needs_clarification": False,
        "text":                (
            f"Queued as {build_id} \u2014 \u201c{title}\u201d. "
            f"Say \u2018run {build_id}\u2019 when you want Frank Lloyd to start building."
        ),
    }


# ── HTML page ─────────────────────────────────────────────────────────────────

@router.get("/neighborhood", response_class=HTMLResponse)
def neighborhood_view() -> HTMLResponse:
    """Serve the pixel-art neighborhood frontend."""
    return HTMLResponse(content=_NEIGHBORHOOD_HTML)


_NEIGHBORHOOD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Abode</title>
<style>
/* ── Reset & base ──────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; background: #0a0f1a; overflow: hidden; }

body {
  font-family: 'Courier New', Courier, monospace;
  color: #e0e0e0;
  display: flex;
  flex-direction: column;
  height: 100vh;
}

/* ── Header ────────────────────────────────────────────────────────────── */
#hdr {
  background: #060b14;
  border-bottom: 2px solid #1e2d45;
  padding: 8px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  z-index: 10;
}

.title-text {
  font-size: 14px;
  letter-spacing: 4px;
  color: #f6c90e;
  text-shadow: 0 0 8px #f6c90e88;
  font-weight: bold;
}

.hdr-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

#conn-dot {
  font-size: 11px;
  color: #546e7a;
  letter-spacing: 1px;
  transition: color 0.3s;
}
#conn-dot.ok    { color: #00e676; text-shadow: 0 0 6px #00e67688; }
#conn-dot.warn  { color: #ff6f00; }
#conn-dot.error { color: #ef5350; }

.hdr-link {
  font-size: 11px;
  color: #90a4ae;
  text-decoration: none;
  letter-spacing: 1px;
  padding: 3px 8px;
  border: 1px solid #37474f;
  border-radius: 2px;
  transition: all 0.15s;
}
.hdr-link:hover { color: #e0e0e0; border-color: #607d8b; background: #1a2a3a; }

/* ── Scene wrapper ──────────────────────────────────────────────────────── */
#scene {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Sky ────────────────────────────────────────────────────────────────── */
#sky {
  flex: 1;
  background: linear-gradient(180deg, #060b14 0%, #0d1b35 60%, #162844 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  padding-bottom: 0;
  position: relative;
  overflow: hidden;
}

/* Stars */
#sky::before {
  content: '· · · ·  ·  ·  · ·   ·  · · ·  ·   ·    ·  ·   ·  · ·  ·  ·   ·';
  position: absolute;
  top: 10px;
  left: 20px;
  right: 20px;
  color: #ffffff22;
  font-size: 10px;
  letter-spacing: 8px;
  pointer-events: none;
}

/* ── Main street ────────────────────────────────────────────────────────── */
#main-street {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 80px;
  padding: 0 40px;
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
}

/* ── Houses ─────────────────────────────────────────────────────────────── */
.house {
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  position: relative;
  user-select: none;
  transition: transform 0.15s ease;
}
.house:hover  { transform: translateY(-8px) scale(1.02); }
.house:active { transform: translateY(-3px); }

/* Chimney */
.chimney {
  width: 18px;
  height: 28px;
  border: 2px solid #333;
  border-bottom: none;
  align-self: flex-start;
  margin-left: 28px;
  margin-bottom: -2px;
  position: relative;
  z-index: 1;
}
.peter       .chimney { background: #9e6a00; }
.belfort     .chimney { background: #006b5a; }
.frank-lloyd .chimney { background: #1a3565; }

/* Antenna (Belfort only) */
.antenna {
  width: 3px;
  height: 32px;
  align-self: flex-end;
  margin-right: 22px;
  margin-bottom: -2px;
  position: relative;
  z-index: 1;
}
.belfort .antenna {
  background: linear-gradient(#90a4ae, #546e7a);
  box-shadow: 0 -4px 0 2px #37474f;
}

/* Roof */
.roof {
  width: 0;
  height: 0;
  border-left: 82px solid transparent;
  border-right: 82px solid transparent;
  transition: border-bottom-color 0.3s;
}
.peter       .roof { border-bottom: 56px solid #c4820d; }
.belfort     .roof { border-bottom: 56px solid #008080; }
.frank-lloyd .roof { border-bottom: 56px solid #3949ab; }

/* Body */
.body {
  width: 144px;
  height: 90px;
  border: 3px solid #222;
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 0 10px;
  position: relative;
  transition: background 0.3s, box-shadow 0.4s;
}
.peter       .body { background: #f6c90e; border-color: #a06b00; }
.belfort     .body { background: #00cec9; border-color: #006b5a; }
.frank-lloyd .body { background: #5c6bc0; border-color: #1a237e; }

/* State glows */
@keyframes glow-active  { 0%,100%{box-shadow:0 0 8px 2px #00e676aa}50%{box-shadow:0 0 22px 6px #00e676dd} }
@keyframes glow-review  { 0%,100%{box-shadow:0 0 8px 2px #ffd600aa}50%{box-shadow:0 0 22px 6px #ffd600dd} }
@keyframes glow-warning { 0%,100%{box-shadow:0 0 8px 2px #ff6f00aa}50%{box-shadow:0 0 22px 6px #ff6f00dd} }
@keyframes glow-error   { 0%,100%{box-shadow:0 0 8px 2px #ef5350aa}50%{box-shadow:0 0 22px 6px #ef5350dd} }

.house.st-active  .body { animation: glow-active  1.8s ease-in-out infinite; }
.house.st-review  .body { animation: glow-review  1.6s ease-in-out infinite; }
.house.st-warning .body { animation: glow-warning 1.4s ease-in-out infinite; }
.house.st-error   .body { animation: glow-error   1.2s ease-in-out infinite; }

/* Windows */
.win {
  width: 30px;
  height: 30px;
  border: 2px solid rgba(0,0,0,0.35);
  border-radius: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  transition: background 0.3s, box-shadow 0.3s;
  flex-shrink: 0;
}
.peter       .win { background: #b8e0ff; }
.belfort     .win { background: #b2f0ed; }
.frank-lloyd .win { background: #c5cae9; }

.house.st-active  .win { background: #d0fff0; box-shadow: inset 0 0 8px #00e67666; }
.house.st-review  .win { background: #fffde0; box-shadow: inset 0 0 8px #ffd60066; }
.house.st-warning .win { background: #fff3e0; box-shadow: inset 0 0 8px #ff6f0066; }

/* Door */
.door {
  width: 28px;
  height: 46px;
  border: 2px solid rgba(0,0,0,0.4);
  border-radius: 3px 3px 0 0;
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
}
.peter       .door { background: #6d3a00; }
.belfort     .door { background: #004d40; }
.frank-lloyd .door { background: #0d1d4a; }

/* Nameplate */
.nameplate {
  font-size: 12px;
  letter-spacing: 3px;
  font-weight: bold;
  margin-top: 6px;
  transition: color 0.3s;
}
.peter      .nameplate { color: #f6c90e; text-shadow: 0 0 6px #f6c90e66; }
.belfort    .nameplate { color: #00cec9; text-shadow: 0 0 6px #00cec966; }
.frank-lloyd .nameplate { color: #7986cb; text-shadow: 0 0 6px #7986cb66; }

.subtitle {
  font-size: 9px;
  letter-spacing: 2px;
  color: #546e7a;
  margin-top: 2px;
}

/* Status badge */
.status-badge {
  font-size: 9px;
  letter-spacing: 2px;
  padding: 2px 7px;
  border-radius: 2px;
  margin-top: 5px;
  font-weight: bold;
  transition: background 0.3s, color 0.3s;
  background: #263238;
  color: #78909c;
}
.house.st-idle    .status-badge { background: #1e2a33; color: #78909c; }
.house.st-active  .status-badge { background: #003322; color: #00e676; }
.house.st-review  .status-badge { background: #332800; color: #ffd600; }
.house.st-warning .status-badge { background: #331a00; color: #ff9800; }
.house.st-error   .status-badge { background: #330000; color: #ef5350; }

/* Speech bubble */
.speech {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 50%;
  transform: translateX(-50%);
  background: #0d1b2e;
  border: 1px solid #37474f;
  border-radius: 4px;
  padding: 5px 9px;
  font-size: 9px;
  letter-spacing: 1px;
  color: #90a4ae;
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.3s;
  z-index: 20;
}
.speech::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: #37474f;
}
.speech.visible { opacity: 1; }

/* ── Operations row ─────────────────────────────────────────────────────── */
#ops-row {
  background: #0c0820;
  border-top: 2px solid #1e1440;
  border-bottom: 2px solid #1e1440;
  padding: 10px 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  flex-shrink: 0;
}

.ops-label {
  font-size: 8px;
  letter-spacing: 4px;
  color: #4a3080;
  writing-mode: vertical-rl;
  text-orientation: mixed;
  transform: rotate(180deg);
  margin-right: 4px;
  flex-shrink: 0;
}

.ops-units {
  display: flex;
  gap: 12px;
  flex-wrap: nowrap;
}

.ops-unit {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  cursor: pointer;
  padding: 8px 14px;
  border: 1px solid #1e1440;
  border-radius: 3px;
  background: #100830;
  transition: all 0.2s;
  min-width: 90px;
}
.ops-unit:hover { border-color: #6c5ce7; background: #160d40; transform: translateY(-2px); }

.ops-icon { font-size: 16px; line-height: 1; }

.ops-name {
  font-size: 8px;
  letter-spacing: 2px;
  color: #6c5ce7;
  font-weight: bold;
}

.ops-status {
  font-size: 9px;
  letter-spacing: 1px;
  padding: 1px 6px;
  border-radius: 2px;
  font-weight: bold;
  transition: all 0.3s;
  background: #1e1440;
  color: #78909c;
}

.ops-unit.st-ok      .ops-status { background: #003322; color: #00e676; }
.ops-unit.st-warning .ops-status { background: #331a00; color: #ff9800; }
.ops-unit.st-error   .ops-status { background: #330000; color: #ef5350; }
.ops-unit.st-idle    .ops-status { background: #1e1440; color: #546e7a; }

/* ── Ground ─────────────────────────────────────────────────────────────── */
#ground {
  height: 28px;
  background: linear-gradient(180deg, #1a3a0a 0%, #2d5a12 50%, #1a3a0a 100%);
  border-top: 3px solid #3d6b1e;
  flex-shrink: 0;
  /* pixel-art grass pattern */
  background-image:
    repeating-linear-gradient(90deg, transparent 0, transparent 7px, #3d6b1e33 7px, #3d6b1e33 8px),
    linear-gradient(180deg, #1a3a0a 0%, #2d5a12 50%, #1a3a0a 100%);
}

/* ── Status bar ─────────────────────────────────────────────────────────── */
#statusbar {
  background: #060b14;
  border-top: 1px solid #1e2d45;
  padding: 5px 18px;
  font-size: 9px;
  letter-spacing: 1px;
  color: #37474f;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
#statusbar a { color: #546e7a; text-decoration: none; transition: color 0.2s; }
#statusbar a:hover { color: #90a4ae; }
#conn-status { color: #546e7a; transition: color 0.3s; }
#conn-status.ok { color: #00e676; }
.sb-sep { color: #1e2d45; }

/* ── Selection ring ─────────────────────────────────────────────────────── */
.house.selected .body    { outline: 3px solid rgba(224,224,224,0.7); outline-offset: 4px; }
.house.selected .nameplate { letter-spacing: 5px; }
.ops-unit.selected       { outline: 2px solid #9c88ff; outline-offset: 2px; }

/* ── Detail panel ───────────────────────────────────────────────────────── */
#detail-panel {
  position: fixed;
  top: 44px;
  bottom: 0;
  right: 0;
  transform: translateX(100%);
  width: 340px;
  background: #060b14;
  border: 1px solid #1e2d45;
  border-right: none;
  border-top: none;
  border-radius: 4px 0 0 0;
  z-index: 100;
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  font-family: 'Courier New', Courier, monospace;
  box-shadow: -4px 0 24px #000a;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
#detail-panel.open { transform: translateX(0); }

#dp-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 10px 14px 9px;
  border-bottom: 1px solid #1e2d45;
  background: #07101f;
}
#dp-title    { font-size: 13px; font-weight: bold; letter-spacing: 3px; color: #e0e0e0; }
#dp-subtitle { font-size: 9px; letter-spacing: 2px; color: #546e7a; margin-top: 2px; }
#dp-close {
  background: none; border: 1px solid #37474f; color: #90a4ae;
  font-family: 'Courier New', Courier, monospace; font-size: 10px;
  cursor: pointer; padding: 3px 7px; border-radius: 2px;
  letter-spacing: 1px; transition: all 0.15s; flex-shrink: 0; margin-left: 8px;
}
#dp-close:hover { color: #e0e0e0; border-color: #607d8b; background: #1a2a3a; }

#dp-body { padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; overflow-y: auto; flex: 1; min-height: 0; }

.dp-section-label { font-size: 8px; letter-spacing: 3px; color: #37474f; margin-bottom: 4px; }
.dp-status-row { display: flex; align-items: center; gap: 8px; }

.dp-badge {
  font-size: 9px; letter-spacing: 2px; padding: 2px 8px;
  border-radius: 2px; font-weight: bold;
}
.dp-badge.idle    { background: #1e2a33; color: #78909c; }
.dp-badge.active  { background: #003322; color: #00e676; }
.dp-badge.review  { background: #332800; color: #ffd600; }
.dp-badge.warning { background: #331a00; color: #ff9800; }
.dp-badge.error   { background: #330000; color: #ef5350; }
.dp-badge.ok      { background: #003322; color: #00e676; }

.dp-detail-text { font-size: 10px; color: #90a4ae; letter-spacing: 0.5px; }

/* ── Frank Lloyd builder workspace ───────────────────────────────────── */
.fl-job-header { padding: 8px 0 4px; }
.fl-job-title-row { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.fl-job-title { font-size: 11px; font-weight: bold; color: #b0bec5; letter-spacing: 0.5px; line-height: 1.3; }
.fl-phase-chip { display: inline-block; font-size: 7px; letter-spacing: 1.5px; padding: 2px 6px; border-radius: 2px; flex-shrink: 0; border: 1px solid transparent; }
.fl-phase-queued   { background: #1e2d3d; color: #78909c; border-color: #263238; }
.fl-phase-review   { background: #332800; color: #ffd600; border-color: #4a3800; }
.fl-phase-building { background: #102800; color: #76ff03; border-color: #1a3d00; }
.fl-phase-ready    { background: #0d2318; color: #00e676; border-color: #00e67633; }
.fl-phase-applied  { background: #0a1a0f; color: #69f0ae; border-color: #00e67644; }
.fl-phase-blocked  { background: #2a0a0a; color: #ef9a9a; border-color: #ef535033; }
.fl-job-meta { font-size: 8px; color: #37474f; margin-top: 3px; letter-spacing: 0.5px; }
.fl-stream { margin: 8px 0 6px; }
.fl-stream-label { font-size: 7px; letter-spacing: 2px; color: #263238; margin-bottom: 5px; }
.fl-stream-entry { display: flex; align-items: baseline; gap: 6px; padding: 2px 0; }
.fl-se-icon { width: 10px; flex-shrink: 0; font-size: 8px; text-align: center; }
.fl-se-text { font-size: 9px; color: #37474f; letter-spacing: 0.3px; }
.fl-se-text.se-active  { color: #b0bec5; }
.fl-se-text.se-review  { color: #ffd600; font-weight: bold; }
.fl-se-text.se-ok      { color: #455a64; }
.fl-se-text.se-done    { color: #66bb6a; }
.fl-se-text.se-blocked { color: #ef9a9a; }
.fl-se-detail { font-size: 7px; color: #263238; letter-spacing: 0.5px; }
.fl-review-area { margin-top: 8px; }
.fl-review-tabs { display: flex; gap: 3px; margin-bottom: 4px; }
.fl-tab { background: #07101f; border: 1px solid #1e2d45; color: #37474f; font-family: 'Courier New', Courier, monospace; font-size: 8px; letter-spacing: 1px; padding: 3px 10px; cursor: pointer; border-radius: 2px; transition: all 0.15s; }
.fl-tab:hover { color: #546e7a; border-color: #263238; }
.fl-tab.fl-tab-active { background: #0d1b2e; border-color: #3949ab; color: #7986cb; }
.fl-review-pane { display: none; }
.fl-review-pane.fl-pane-active { display: block; }
.fl-code-view { font-family: 'Courier New',Courier,monospace; font-size: 8px; color: #cfd8dc; background: #0d1117; padding: 6px 8px; border-radius: 2px; max-height: 180px; overflow-y: auto; overflow-x: auto; white-space: pre; margin: 0; border: 1px solid #1a2332; }
.fl-draft-notes { font-size: 9px; color: #90a4ae; line-height: 1.5; padding: 5px 6px; background: #0d1b2e; border-radius: 2px; border: 1px solid #1e2d45; margin-bottom: 4px; }
.fl-draft-meta-row { display: flex; gap: 4px; flex-wrap: wrap; margin: 4px 0; }
.fl-draft-chip { font-size: 7px; letter-spacing: 1px; padding: 2px 5px; border-radius: 2px; background: #1e2d3d; color: #78909c; border: 1px solid #263238; }
.fl-field-label { font-size: 7px; letter-spacing: 2px; color: #37474f; margin-bottom: 3px; margin-top: 8px; }
.fl-composer-label { font-size: 7px; letter-spacing: 2px; color: #37474f; margin-bottom: 4px; margin-top: 10px; }
.fl-prompt-box { width: 100%; box-sizing: border-box; background: #060e1c; border: 1px solid #1e3050; color: #b0bec5; font-family: 'Courier New', Courier, monospace; font-size: 9.5px; letter-spacing: 0.3px; padding: 8px 10px; border-radius: 3px; outline: none; line-height: 1.6; resize: vertical; min-height: 80px; transition: border-color 0.15s; }
.fl-prompt-box:focus { border-color: #3949ab; }
.fl-action-feedback { font-size: 9px; letter-spacing: 0.5px; padding: 5px 6px; margin-top: 6px; border-radius: 2px; }
.fl-fb-ok      { background: #0d2318; color: #66bb6a; border: 1px solid #1b5e20; }
.fl-fb-error   { background: #2a0a0a; color: #ef9a9a; border: 1px solid #5f1f1f; }
.fl-fb-pending { background: #0d1b2e; color: #90a4ae; border: 1px solid #37474f; }
.fl-text-input {
  width: 100%; box-sizing: border-box; background: #0d1b2e; border: 1px solid #37474f;
  color: #b0bec5; font-family: 'Courier New', Courier, monospace; font-size: 10px;
  letter-spacing: 0.5px; padding: 5px 7px; border-radius: 2px; outline: none; margin-top: 6px;
}
.fl-text-input:focus { border-color: #546e7a; }
.fl-form-btns { display: flex; gap: 6px; margin-top: 6px; }
.fl-belfort-work { font-size: 9px; color: #546e7a; letter-spacing: 0.3px; padding: 4px 0 2px; border-top: 1px solid #1e2d4530; margin-top: 4px; }
.fl-belfort-work strong { color: #7986cb; }
.fl-apply-summary { margin: 8px 0 6px; background: #060e1c; border: 1px solid #1e3050; border-radius: 3px; padding: 8px 10px; }
.fl-apply-summary-label { font-size: 7px; letter-spacing: 2px; color: #3949ab; margin-bottom: 6px; }
.fl-apply-row { display: flex; gap: 6px; margin-bottom: 4px; font-size: 9px; line-height: 1.4; }
.fl-apply-key { color: #37474f; letter-spacing: 0.5px; flex-shrink: 0; width: 70px; }
.fl-apply-val { color: #b0bec5; }
.fl-apply-val.risk-low    { color: #66bb6a; }
.fl-apply-val.risk-medium { color: #ffd600; }
.fl-apply-val.risk-high   { color: #ef9a9a; }
.fl-apply-val.risk-critical { color: #ef5350; font-weight: bold; }
.fl-apply-loading { font-size: 9px; color: #37474f; letter-spacing: 0.5px; }
.fl-source-chip {
  display: inline-block; font-size: 7px; letter-spacing: 1px;
  padding: 1px 5px; border-radius: 2px; margin-left: 4px;
  background: #0d1b2e; border: 1px solid #1e2d45; color: #546e7a;
  vertical-align: middle;
}
.fl-source-unknown { border-color: #ff8f00; color: #ff8f00; background: #1a1000; }
.fl-source-warning {
  font-size: 8px; color: #ef9a9a; background: #1a0505; border: 1px solid #ef535033;
  border-radius: 2px; padding: 3px 7px; margin-top: 4px; letter-spacing: 0.3px;
  line-height: 1.5;
}

.dp-items { display: flex; flex-direction: column; gap: 4px; }
.dp-item {
  font-size: 10px; color: #b0bec5; letter-spacing: 0.5px;
  padding-left: 12px; position: relative; line-height: 1.4;
}
.dp-item::before { content: '›'; position: absolute; left: 0; color: #546e7a; }
.dp-item.warn::before { color: #ff9800; }
.dp-item.ok::before   { color: #00e676; }

.dp-divider { height: 1px; background: #1e2d45; }

#dp-actions { display: flex; flex-direction: column; gap: 6px; padding: 0 14px 12px; flex-shrink: 0; border-top: 1px solid #1e2d45; background: #07101f; }
.dp-action-btn {
  background: #0d1b2e; border: 1px solid #37474f; color: #90a4ae;
  font-family: 'Courier New', Courier, monospace; font-size: 10px;
  letter-spacing: 1.5px; padding: 7px 12px; cursor: pointer;
  border-radius: 2px; text-align: left; transition: all 0.15s;
  text-decoration: none; display: block;
}
.dp-action-btn:hover { background: #1a2a3a; border-color: #607d8b; color: #e0e0e0; }
.dp-action-btn.primary { border-color: #546e7a; color: #b0bec5; }
.dp-action-btn.primary:hover { background: #162030; border-color: #90a4ae; color: #e0e0e0; }

/* ── Neighborhood summary bar ───────────────────────────────────────────── */
#nbhd-summary {
  background: #07101f;
  border-top: 1px solid #0d1f35;
  border-bottom: 1px solid #0d1f35;
  padding: 5px 20px;
  font-size: 9px; letter-spacing: 1.5px; color: #546e7a;
  display: flex; align-items: center; gap: 10px;
  flex-shrink: 0; overflow: hidden;
}
.nb-item { white-space: nowrap; }
.nb-item.attn { color: #ffd600; }
.nb-item.warn { color: #ff9800; }
.nb-item.ok   { color: #00e676; }
.nb-sep { color: #1e2d45; flex-shrink: 0; }

/* ── Welcome card ───────────────────────────────────────────────────────── */
#welcome-card {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: #060b14;
  border: 1px solid #2a3f5a;
  border-radius: 6px;
  padding: 28px 30px 22px;
  text-align: center;
  z-index: 200;
  width: 330px;
  box-shadow: 0 8px 48px #000d, 0 0 0 1px #1a2d45;
  display: none;
}
#welcome-card.visible { display: block; }
#wc-close {
  position: absolute; top: 10px; right: 12px;
  background: none; border: none; color: #37474f;
  font-size: 12px; cursor: pointer; letter-spacing: 1px;
  transition: color 0.15s;
}
#wc-close:hover { color: #78909c; }
#wc-title {
  font-size: 12px; font-weight: bold; letter-spacing: 4px;
  color: #f6c90e; text-shadow: 0 0 10px #f6c90e44; margin-bottom: 14px;
}
#wc-desc {
  font-size: 11px; color: #78909c; letter-spacing: 0.3px;
  line-height: 1.7; margin-bottom: 18px; text-align: left;
}
#wc-desc strong { color: #b0bec5; }
#wc-cta {
  background: #07101f; border: 1px solid #546e7a; color: #b0bec5;
  font-family: 'Courier New', Courier, monospace; font-size: 11px;
  letter-spacing: 2px; padding: 9px 20px; cursor: pointer;
  border-radius: 3px; transition: all 0.15s; display: inline-block;
}
#wc-cta:hover { background: #0d1f35; border-color: #90a4ae; color: #e0e0e0; }

/* ── Start-here hint ────────────────────────────────────────────────────── */
.start-hint {
  font-size: 9px; letter-spacing: 2px; color: #f6c90e;
  margin-top: 5px;
  animation: pulse-hint 2.2s ease-in-out infinite;
}
@keyframes pulse-hint {
  0%, 100% { opacity: 0.35; }
  50%       { opacity: 1; }
}

/* ── Ops description label ──────────────────────────────────────────────── */
.ops-desc {
  font-size: 7px; letter-spacing: 1.5px; color: #3a2860;
  margin-top: 1px; text-transform: lowercase;
}

/* ── Peter chat ─────────────────────────────────────────────────────────── */
.peter-chat-history {
  height: 130px; overflow-y: auto;
  display: flex; flex-direction: column; gap: 5px;
  padding: 6px 8px;
  background: #040d1a; border: 1px solid #1e2d45; border-radius: 2px;
  font-size: 10px; line-height: 1.5;
}
.chat-msg-peter    { color: #7ecbbd; letter-spacing: 0.3px; }
.chat-msg-operator { color: #c8d8e0; text-align: right; letter-spacing: 0.3px; }
.chat-loading      { color: #37474f; font-style: italic; }
.peter-chat-input-row { display: flex; gap: 5px; margin-top: 2px; align-items: flex-end; }
.peter-chat-input {
  flex: 1; background: #040d1a; border: 1px solid #1e2d45; color: #b0bec5;
  font-family: 'Courier New', Courier, monospace; font-size: 10px; line-height: 1.5;
  padding: 5px 8px; border-radius: 2px; outline: none; transition: border-color 0.15s;
  resize: none; min-height: 40px; max-height: 160px; overflow-y: auto;
  box-sizing: border-box;
}
.peter-chat-input:focus { border-color: #37474f; }
.peter-chat-send {
  background: #0d1b2e; border: 1px solid #37474f; color: #90a4ae;
  font-family: 'Courier New', Courier, monospace; font-size: 9px;
  letter-spacing: 1px; padding: 5px 9px; cursor: pointer; border-radius: 2px;
  transition: all 0.15s; white-space: nowrap;
}
.peter-chat-send:hover { background: #1a2a3a; color: #e0e0e0; border-color: #607d8b; }
.peter-chat-send:disabled { opacity: 0.45; cursor: not-allowed; }
.chat-chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.chat-chip {
  background: #07101f; border: 1px solid #1e2d45; color: #546e7a;
  font-size: 8px; letter-spacing: 0.5px; padding: 3px 7px;
  cursor: pointer; border-radius: 2px; transition: all 0.15s;
}
.chat-chip:hover { border-color: #37474f; color: #78909c; }

/* ── Belfort controls ───────────────────────────────────────────────────── */
.belfort-stats {
  display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 5px;
}
.bstat {
  background: #040d1a; border: 1px solid #1e2d45; border-radius: 2px;
  padding: 5px 6px; display: flex; flex-direction: column; align-items: center; gap: 2px;
}
.bstat-label { font-size: 7px; letter-spacing: 2px; color: #37474f; }
.bstat-value { font-size: 11px; font-weight: bold; color: #b0bec5; }
.bstat-value.pos { color: #00e676; }
.bstat-value.neg { color: #ef5350; }
.belfort-status-pills { display: flex; gap: 6px; margin-top: 4px; }
.bpill {
  flex: 1; background: #040d1a; border: 1px solid #1e2d45; border-radius: 2px;
  padding: 4px 6px; text-align: center; font-size: 8px; letter-spacing: 2px;
  color: #37474f; transition: all 0.3s;
}
.bpill-active { border-color: #00e676; color: #00e676; background: #001a0e; }
.belfort-mode-readiness {
  display: flex; gap: 6px; margin-top: 4px;
}
.bmr-cell {
  flex: 1; background: #040d1a; border: 1px solid #1e2d45; border-radius: 2px;
  padding: 4px 6px; font-size: 8px; letter-spacing: 1px; color: #546e7a;
}
.bmr-label { font-size: 7px; letter-spacing: 2px; color: #37474f; margin-bottom: 1px; }
.bmr-value { color: #b0bec5; font-weight: bold; }
.bmr-value.bmr-stale  { color: #ff8f00; }
.bmr-value.bmr-bad    { color: #ef5350; }
.bmr-value.bmr-ok     { color: #00e676; }
.belfort-signal-row {
  margin-top: 4px; padding: 4px 6px; background: #040d1a;
  border: 1px solid #1e2d45; border-radius: 2px; font-size: 8px;
  color: #78909c; letter-spacing: 0.5px; line-height: 1.5;
}
.bsig-label { font-size: 7px; letter-spacing: 2px; color: #37474f; margin-bottom: 2px; }
.bsig-action-hold  { color: #78909c; }
.bsig-action-buy   { color: #00e676; }
.bsig-action-sell  { color: #ef9a9a; }
.bsig-risk-allowed { color: #546e7a; }
.bsig-risk-blocked { color: #ff8f00; }
.belfort-paper-exec-row {
  margin-top: 3px; padding: 4px 6px; background: #040d1a;
  border: 1px solid #263238; border-left: 2px solid #37474f;
  border-radius: 2px; font-size: 8px; color: #546e7a; letter-spacing: 0.5px; line-height: 1.5;
}
.bpex-label  { font-size: 7px; letter-spacing: 2px; color: #263238; margin-bottom: 2px; }
.bpex-submitted { color: #78909c; }
.bpex-gated     { color: #37474f; font-style: italic; }
.bpex-error     { color: #ff6e40; }
.belfort-controls-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 5px; margin-top: 2px;
}
.bctrl-btn {
  background: #0d1b2e; border: 1px solid #37474f; color: #78909c;
  font-family: 'Courier New', Courier, monospace; font-size: 9px;
  letter-spacing: 1px; padding: 6px 8px; cursor: pointer; border-radius: 2px;
  transition: all 0.15s; text-align: center;
}
.bctrl-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.bctrl-start:hover:not(:disabled) { border-color: #00e676; color: #00e676; background: #001a0e; }
.bctrl-stop:hover:not(:disabled)  { border-color: #ef5350; color: #ef5350; background: #1a0000; }
.bctrl-on { border-color: #00e676; color: #00e676; background: #001a0e; }

/* LM unavailable notice */
.peter-chat-notice {
  font-size: 9px; color: #ff6f00; letter-spacing: 0.5px; line-height: 1.5;
  padding: 4px 6px; background: #1a1000; border: 1px solid #3a2200; border-radius: 2px;
  display: none;
}
.peter-chat-notice.visible { display: block; }
.belfort-reset-section { margin-top: 6px; }
.belfort-reset-confirm {
  flex-direction: column; gap: 5px; margin-top: 6px;
  padding: 8px; background: #0a0a14; border: 1px solid #1e1440; border-radius: 2px;
}
.reset-warning-text { font-size: 9px; color: #78909c; letter-spacing: 0.5px; line-height: 1.5; }
.reset-reason-input {
  width: 100%; background: #040d1a; border: 1px solid #1e2d45; color: #b0bec5;
  font-family: 'Courier New', Courier, monospace; font-size: 10px;
  padding: 5px 8px; border-radius: 2px; outline: none;
}
.reset-confirm-btns { display: flex; gap: 5px; }
.reset-btn {
  flex: 1; padding: 5px 8px; font-family: 'Courier New', Courier, monospace;
  font-size: 9px; letter-spacing: 1px; cursor: pointer; border-radius: 2px;
  transition: all 0.15s; border: 1px solid; text-align: center;
}
.reset-cancel  { background: #0d1b2e; border-color: #37474f; color: #78909c; }
.reset-cancel:hover { color: #90a4ae; border-color: #546e7a; }
.reset-execute { background: #1a0000; border-color: #ef5350; color: #ef5350; }
.reset-execute:hover:not(:disabled) { background: #2a0000; }
.reset-execute:disabled { opacity: 0.4; cursor: not-allowed; }

/* ── Review card (inline approval in Belfort panel) ────────────────────── */
.review-card { background:#0a1020; border:1px solid #332800; border-radius:2px; padding:9px 10px; }
.review-card-label { font-size:7px; letter-spacing:3px; color:#ffd600; margin-bottom:5px; font-weight:bold; }
.review-title  { font-size:10px; font-weight:bold; color:#e0e0e0; letter-spacing:0.5px; margin-bottom:3px; line-height:1.4; }
.review-summary { font-size:9px; color:#78909c; letter-spacing:0.3px; line-height:1.5; margin-bottom:5px; }
.review-metric { font-size:9px; color:#90a4ae; letter-spacing:0.5px; margin-bottom:8px; }
.review-btns   { display:flex; gap:5px; }
.review-btn {
  flex:1; padding:5px 8px; font-family:'Courier New',Courier,monospace;
  font-size:9px; letter-spacing:1px; cursor:pointer; border-radius:2px;
  transition:all 0.15s; border:1px solid; text-align:center;
}
.review-btn:disabled { opacity:0.4; cursor:not-allowed; }
.review-approve { background:#001a0e; border-color:#00e676; color:#00e676; }
.review-approve:hover:not(:disabled) { background:#002a14; }
.review-reject  { background:#1a0000; border-color:#ef5350; color:#ef5350; }
.review-reject:hover:not(:disabled)  { background:#2a0000; }

/* ── Learning pulse ──────────────────────────────────────────────────────── */
.learning-verdict-row { display:flex; align-items:center; gap:6px; margin-bottom:4px; }
.verdict-badge { font-size:8px; font-weight:600; letter-spacing:0.8px; padding:1px 6px; border-radius:2px; flex-shrink:0; }
.verdict-continue { background:#0a2310; color:#00e676; border:1px solid #1a4a30; }
.verdict-monitor  { background:#0d1a25; color:#90a4ae; border:1px solid #1e2d45; }
.verdict-tune     { background:#1a1200; color:#ffd54f; border:1px solid #3b2c00; }
.verdict-research { background:#2a0808; color:#ef5350; border:1px solid #5a1010; }
.learning-item {
  font-size:9px; letter-spacing:0.3px; line-height:1.5; padding:1px 0;
}
.learning-hurting { color:#ef9a9a; }
.learning-helping { color:#a5d6a7; }
.learning-recommendation {
  font-size:9px; color:#546e7a; letter-spacing:0.3px; line-height:1.5;
  padding:3px 8px; background:#040d1a; border:1px solid #1e2d45; border-radius:2px;
  margin-top:3px;
}
.learning-research-goal {
  font-size:8px; color:#546e7a; letter-spacing:0.3px; line-height:1.4;
  padding:3px 8px; background:#040d1a; border:1px solid #1a2535;
  border-radius:2px; margin-top:4px; font-style:italic; display:none;
}
.learning-history {
  font-size:8px; color:#37474f; letter-spacing:0.3px; line-height:1.5;
  padding:3px 8px; background:#040d1a; border:1px solid #131f2e;
  border-radius:2px; margin-top:3px; display:none;
}
.learning-history b { color:#455a64; }
.learning-research-btn {
  margin-top:4px; width:100%; padding:4px 0; font-size:9px; letter-spacing:0.8px;
  font-weight:600; background:#1a0808; color:#ef5350; border:1px solid #5a1010;
  border-radius:2px; cursor:pointer;
}
.learning-research-btn:hover { background:#2a0a0a; }

/* ── Readiness scorecard ─────────────────────────────────────────────────── */
.readiness-strategy {
  font-size:9px; color:#546e7a; letter-spacing:0.5px; line-height:1.5;
  margin-bottom:5px; font-style:italic;
}
.readiness-gates { display:flex; flex-direction:column; gap:2px; margin-bottom:6px; }
.rgate {
  font-size:9px; letter-spacing:0.5px; padding:1px 0 1px 16px; position:relative;
  line-height:1.4; color:#b0bec5;
}
.rgate::before { content:'\2713'; position:absolute; left:0; color:#00e676; font-size:9px; }
.rgate.fail { color:#546e7a; }
.rgate.fail::before { content:'\2717'; color:#ef5350; }
.readiness-regime {
  font-size:8px; color:#546e7a; letter-spacing:0.4px; padding:0 0 4px;
}
.readiness-regime .regime-good { color:#00e676; }
.readiness-regime .regime-ok { color:#b0bec5; }
.readiness-regime .regime-poor { color:#ef9a9a; }
.readiness-regime .regime-unknown { color:#455a64; font-style:italic; }
.readiness-research-trigger {
  font-size:9px; color:#ffd54f; letter-spacing:0.3px; line-height:1.5;
  padding:4px 8px; background:#1a1200; border:1px solid #3b2c00; border-radius:2px;
  margin-top:4px; display:none;
}
.readiness-research-trigger b { color:#ffb300; font-weight:600; }
.readiness-blockers {
  font-size:9px; color:#ef9a9a; letter-spacing:0.3px; line-height:1.6;
  padding:4px 8px; background:#1a0808; border:1px solid #3b1010; border-radius:2px;
  margin-top:4px; display:none;
}
.readiness-blockers b { color:#ef5350; font-weight:600; }
.readiness-comparison {
  font-size:8px; color:#455a64; letter-spacing:0.3px; line-height:1.6;
  padding:4px 8px; background:#040d1a; border:1px solid #1a2535; border-radius:2px;
  margin-top:4px; display:none;
}
.readiness-comparison b { color:#607d8b; font-weight:600; }
.readiness-badge-prelive { background:#003322; color:#00e676; }
.readiness-badge-monitoring { background:#332800; color:#ffd600; }
.readiness-badge-evaluation { background:#00204a; color:#4fc3f7; }
#readiness-detail > summary {
  font-size:9px; color:#546e7a; letter-spacing:0.5px; cursor:pointer;
  list-style:none; user-select:none; margin-top:4px;
}
#readiness-detail > summary::-webkit-details-marker { display:none; }
.diag-block { margin-bottom:5px; }
.diag-row { display:flex; align-items:center; gap:6px; margin-bottom:2px; }
.diag-label { font-size:7px; letter-spacing:1.5px; color:#37474f; flex-shrink:0; }
.diag-ok        { font-size:9px; color:#00e676; }
.diag-warn      { font-size:9px; color:#ef9a9a; }
.diag-soft      { font-size:9px; color:#ffd54f; }
.diag-warn-text { font-size:9px; color:#ef9a9a; letter-spacing:0.3px; padding-left:4px; line-height:1.5; }
.diag-soft-text { font-size:9px; color:#ffd54f; letter-spacing:0.3px; padding-left:4px; line-height:1.5; }
.diag-muted     { font-size:9px; color:#546e7a; letter-spacing:0.3px; line-height:1.5; }
.diag-bridge    { font-size:9px; color:#4fc3f7; letter-spacing:0.3px; margin-top:4px; padding-top:4px; border-top:1px solid #1a2a35; }
.diag-detail-toggle { list-style:none; font-size:9px; color:#455a64; cursor:pointer; margin-top:3px; }
.diag-detail-toggle::-webkit-details-marker { display:none; }

/* ── Docs viewer ─────────────────────────────────────────────────────────── */
.docs-tabs { display:flex; gap:4px; flex-wrap:wrap; margin-bottom:8px; }
.docs-tab {
  font-size:8px; letter-spacing:1px; padding:3px 8px; cursor:pointer;
  border:1px solid #1e2d45; border-radius:2px; background:#040d1a; color:#546e7a;
  font-family:'Courier New',Courier,monospace; transition:all 0.15s;
}
.docs-tab:hover  { border-color:#37474f; color:#90a4ae; }
.docs-tab.active { border-color:#546e7a; color:#b0bec5; background:#0a1825; }
.docs-content { font-size:9px; line-height:1.6; color:#90a4ae; letter-spacing:0.3px; }
.docs-h1 { font-size:10px; font-weight:bold; color:#b0bec5; letter-spacing:1px; margin:10px 0 3px; }
.docs-h2 { font-size:9px; font-weight:bold; color:#7ecbbd; letter-spacing:0.8px; margin:8px 0 2px; }
.docs-h3 { font-size:9px; color:#78909c; letter-spacing:0.5px; margin:6px 0 2px; }
.docs-hr { height:1px; background:#1e2d45; margin:7px 0; }
.docs-bullet { padding-left:10px; position:relative; margin:1px 0; color:#90a4ae; }
.docs-bullet::before { content:'›'; position:absolute; left:0; color:#455a64; }
.docs-p { margin:1px 0; color:#78909c; }
.docs-table-row { color:#546e7a; font-size:8px; letter-spacing:0.3px; margin:1px 0; border-left:2px solid #1e2d45; padding-left:6px; }
.docs-code { color:#78909c; background:#0a1020; padding:0 3px; border-radius:1px; }
.docs-loading { color:#37474f; font-style:italic; font-size:9px; }
</style>
</head>
<body>

<!-- Header -->
<div id="hdr">
  <span class="title-text">✦ THE ABODE ✦</span>
  <div class="hdr-right">
    <span id="conn-dot">● CONNECTING</span>
    <a class="hdr-link" href="http://localhost:8502" target="_blank">⚙ Dashboard</a>
  </div>
</div>

<!-- Scene -->
<div id="scene">

  <!-- Sky + Main Street -->
  <div id="sky">
    <div id="main-street">

      <!-- PETER'S HOUSE -->
      <div class="house peter st-idle" id="h-peter" onclick="selectItem('peter')" title="Peter — Your Front Door">
        <div class="chimney"></div>
        <div class="roof"></div>
        <div class="body">
          <div class="win">🪟</div>
          <div class="door"></div>
          <div class="win">🪟</div>
        </div>
        <div class="nameplate">PETER</div>
        <div class="subtitle">Your main interface</div>
        <div class="status-badge" id="pb-peter">IDLE</div>
        <div class="start-hint" id="peter-start-hint">↑ start here</div>
        <div class="speech" id="sp-peter">Ready for instructions</div>
      </div>

      <!-- BELFORT'S HOUSE -->
      <div class="house belfort st-idle" id="h-belfort" onclick="selectItem('belfort')" title="Mr Belfort — Trading Floor">
        <div class="antenna"></div>
        <div class="roof"></div>
        <div class="body">
          <div class="win">📊</div>
          <div class="door"></div>
          <div class="win">📈</div>
        </div>
        <div class="nameplate">MR BELFORT</div>
        <div class="subtitle">Research &amp; learning</div>
        <div class="status-badge" id="pb-belfort">IDLE</div>
        <div class="speech" id="sp-belfort"></div>
      </div>

      <!-- FRANK LLOYD'S HOUSE -->
      <div class="house frank-lloyd st-idle" id="h-frank-lloyd" onclick="selectItem('frank-lloyd')" title="Frank Lloyd — Construction House">
        <div class="chimney"></div>
        <div class="roof"></div>
        <div class="body">
          <div class="win">📐</div>
          <div class="door"></div>
          <div class="win">🏗</div>
        </div>
        <div class="nameplate">FRANK LLOYD</div>
        <div class="subtitle">Build &amp; construction</div>
        <div class="status-badge" id="pb-frank-lloyd">IDLE</div>
        <div class="speech" id="sp-frank-lloyd"></div>
      </div>

    </div>
  </div>

  <!-- Neighborhood Summary -->
  <div id="nbhd-summary">
    <span id="nb-attention" class="nb-item">—</span>
    <span class="nb-sep">·</span>
    <span id="nb-belfort" class="nb-item">BELFORT —</span>
    <span class="nb-sep">·</span>
    <span id="nb-frank-lloyd" class="nb-item">BUILD —</span>
    <span class="nb-sep">·</span>
    <span id="nb-ops" class="nb-item">OPS —</span>
  </div>

  <!-- Operations Row -->
  <div id="ops-row">
    <div class="ops-label">OPERATIONS</div>
    <div class="ops-units">

      <div class="ops-unit st-idle" id="u-custodian" onclick="selectItem('custodian')" title="Custodian — Runtime Health">
        <div class="ops-icon">🔧</div>
        <div class="ops-name">CUSTODIAN</div>
        <div class="ops-desc">system health</div>
        <div class="ops-status" id="os-custodian">?</div>
      </div>

      <div class="ops-unit st-idle" id="u-checker" onclick="selectItem('checker')" title="Loop Checker — Audit &amp; Findings">
        <div class="ops-icon">🔍</div>
        <div class="ops-name">CHECKER</div>
        <div class="ops-desc">finds issues</div>
        <div class="ops-status" id="os-checker">?</div>
      </div>

      <div class="ops-unit st-idle" id="u-sentinel" onclick="selectItem('sentinel')" title="Test Sentinel — Patch Safety">
        <div class="ops-icon">🧪</div>
        <div class="ops-name">SENTINEL</div>
        <div class="ops-desc">patch safety</div>
        <div class="ops-status" id="os-sentinel">?</div>
      </div>

      <div class="ops-unit st-idle" id="u-supervisor" onclick="selectItem('supervisor')" title="Loop Supervisor — Execution">
        <div class="ops-icon">🔄</div>
        <div class="ops-name">SUPERVISOR</div>
        <div class="ops-desc">runs the loop</div>
        <div class="ops-status" id="os-supervisor">?</div>
      </div>

      <div class="ops-unit st-idle" id="u-warden" onclick="selectItem('warden')" title="Cost Warden — LM Routing">
        <div class="ops-icon">💰</div>
        <div class="ops-name">WARDEN</div>
        <div class="ops-desc">cost control</div>
        <div class="ops-status" id="os-warden">?</div>
      </div>

      <div class="ops-unit st-idle" id="u-docs" onclick="selectItem('docs')" title="Docs — Project Reference">
        <div class="ops-icon">📖</div>
        <div class="ops-name">DOCS</div>
        <div class="ops-desc">reference</div>
        <div class="ops-status" id="os-docs">4 DOCS</div>
      </div>

    </div>
  </div>

  <!-- Ground -->
  <div id="ground"></div>

  <!-- Status bar -->
  <div id="statusbar">
    <span id="conn-status">Connecting…</span>
    <span class="sb-sep">·</span>
    <span id="last-updated"></span>
    <span class="sb-sep">·</span>
    <a href="http://localhost:8502" target="_blank">Open full dashboard →</a>
  </div>

  <!-- Welcome card (first-time visitors) -->
  <div id="welcome-card">
    <button id="wc-close" onclick="dismissWelcome(false)">✕</button>
    <div id="wc-title">✦ THE ABODE</div>
    <div id="wc-desc">
      An automated AI workspace for trading research and strategy development.<br><br>
      <strong>Peter</strong> is your main interface — he coordinates the system, explains what's happening, and guides you through reviews and decisions.<br><br>
      <strong>Mr Belfort</strong> runs the research in the background.<br><br>
      <strong>Frank Lloyd</strong> is the construction house — queue a build via Peter to get started.<br><br>
      The <strong>Operations</strong> row shows system health at a glance.
    </div>
    <button id="wc-cta" onclick="dismissWelcome(true)">Talk to Peter →</button>
  </div>

  <!-- Detail Panel -->
  <div id="detail-panel">
    <div id="dp-header">
      <div>
        <div id="dp-title">—</div>
        <div id="dp-subtitle">—</div>
      </div>
      <button id="dp-close" onclick="closePanel()">✕ CLOSE</button>
    </div>
    <div id="dp-body">
      <!-- Status (always shown) -->
      <div>
        <div class="dp-section-label">STATUS</div>
        <div class="dp-status-row">
          <span id="dp-badge" class="dp-badge idle">—</span>
          <span id="dp-status-detail" class="dp-detail-text"></span>
        </div>
      </div>
      <div class="dp-divider"></div>
      <!-- Situation (always shown) -->
      <div>
        <div class="dp-section-label">SITUATION</div>
        <div id="dp-situation" class="dp-items"></div>
      </div>
      <!-- Next (hidden for Peter/Belfort which have richer panels) -->
      <div id="dp-next-wrapper">
        <div class="dp-divider"></div>
        <div>
          <div class="dp-section-label">NEXT</div>
          <div id="dp-next" class="dp-items"></div>
        </div>
      </div>

      <!-- Peter chat (shown only when Peter panel is open) -->
      <div id="peter-chat-section" style="display:none">
        <div class="dp-divider"></div>
        <div class="dp-section-label">ASK PETER</div>
        <div id="peter-chat-history" class="peter-chat-history"></div>
        <div class="peter-chat-input-row">
          <textarea id="peter-chat-input" class="peter-chat-input" rows="2"
                    placeholder="Ask anything… (Shift+Enter for newline)" maxlength="4000"
                    autocomplete="off"></textarea>
          <button id="peter-chat-send" class="peter-chat-send" onclick="peterChatSend()">SEND</button>
        </div>
        <div class="chat-chips">
          <span class="chat-chip" onclick="peterChatAsk('What is happening right now?')">What is happening?</span>
          <span class="chat-chip" onclick="peterChatAsk('What needs my attention?')">Needs attention?</span>
          <span class="chat-chip" onclick="peterChatAsk('What should I do next?')">What next?</span>
          <span class="chat-chip" onclick="peterChatAsk('Explain Belfort progress for my mentor')">Belfort progress</span>
          <span class="chat-chip" onclick="peterChatAsk('Is Belfort ready for live trading consideration?')">Ready?</span>
        </div>
        <div id="peter-chat-notice" class="peter-chat-notice">
          &#9888; AI chat offline &mdash; OpenRouter API key not configured.<br>
          Use the Peter workspace for full guidance, or configure the key in Controls.
        </div>
      </div>

      <!-- Belfort controls (shown only when Belfort panel is open) -->
      <div id="belfort-controls-section" style="display:none">
        <div class="dp-divider"></div>
        <div class="dp-section-label">TRADING STATS</div>
        <div id="belfort-stats" class="belfort-stats"></div>
        <div id="belfort-pills" class="belfort-status-pills"></div>
        <div id="belfort-mode-readiness" class="belfort-mode-readiness"></div>
        <div id="belfort-signal-row" class="belfort-signal-row" style="display:none"></div>
        <div id="belfort-paper-exec-row" class="belfort-paper-exec-row" style="display:none"></div>
        <div id="fl-belfort-work" class="fl-belfort-work" style="display:none"></div>
        <div class="dp-divider"></div>
        <div class="dp-section-label">CONTROLS</div>
        <div class="belfort-controls-grid">
          <button class="bctrl-btn bctrl-start" id="btn-trading-toggle" onclick="belfortToggle('trading')">&#9654; Start Trading</button>
          <button class="bctrl-btn bctrl-start" id="btn-loop-toggle"    onclick="belfortToggle('loop')">&#9654; Begin Research</button>
        </div>
        <div class="belfort-reset-section">
          <button class="dp-action-btn" id="btn-reset-init"
                  onclick="belfortResetInit()"
                  style="color:#546e7a;font-size:9px;margin-top:4px">&#9888; Reset trading baseline&#8230;</button>
          <div id="belfort-reset-confirm" class="belfort-reset-confirm" style="display:none">
            <div class="reset-warning-text">Reset cash to $100k and clear all trades. Strategy config is preserved.</div>
            <input id="belfort-reset-reason" class="reset-reason-input"
                   type="text" placeholder="Reason (optional)" maxlength="120" autocomplete="off">
            <div class="reset-confirm-btns">
              <button class="reset-btn reset-cancel" onclick="belfortResetCancel()">Cancel</button>
              <button class="reset-btn reset-execute" onclick="belfortResetExecute()">Confirm Reset</button>
            </div>
          </div>
        </div>
        <!-- Inline review card (visible when waiting_for_review or review_held) -->
        <div id="belfort-review-card" style="display:none">
          <div class="dp-divider" style="margin-top:6px"></div>
          <div class="dp-section-label" style="margin-top:6px">PENDING REVIEW</div>
          <div class="review-card">
            <div id="review-card-label" class="review-card-label">&#9889; READY FOR REVIEW</div>
            <div id="review-title" class="review-title">Loading&hellip;</div>
            <div id="review-summary" class="review-summary"></div>
            <div id="review-metric" class="review-metric"></div>
            <div class="review-btns">
              <button class="review-btn review-approve" id="review-approve-btn" onclick="belfortReviewAction('approve')">&#10003; Approve</button>
              <button class="review-btn review-reject"  id="review-reject-btn"  onclick="belfortReviewAction('reject')">&#10007; Reject</button>
            </div>
          </div>
        </div>
        <!-- Mock trading history (old scorecard — historical performance only) -->
        <div id="belfort-readiness-section" style="display:none">
          <div class="dp-divider" style="margin-top:8px"></div>
          <div class="dp-section-label" style="margin-top:8px">MOCK TRADING HISTORY</div>
          <div style="font-size:7px;color:#37474f;letter-spacing:0.5px;margin-bottom:4px">Past performance \u00b7 current readiness claim is above</div>
          <div class="dp-status-row" style="margin-bottom:5px;gap:8px">
            <span id="readiness-badge" class="dp-badge idle">—</span>
            <span id="readiness-gates-count" class="dp-detail-text"></span>
          </div>
          <div id="readiness-research-trigger" class="readiness-research-trigger"></div>
          <div id="readiness-blockers" class="readiness-blockers"></div>
          <details id="readiness-detail">
            <summary>Detail &#9658;</summary>
            <div id="readiness-strategy" class="readiness-strategy"></div>
            <div id="readiness-regime" class="readiness-regime"></div>
            <div id="readiness-gates" class="readiness-gates"></div>
            <div id="readiness-comparison" class="readiness-comparison"></div>
          </details>
        </div>
        <!-- Mock trading learning history (loaded from /belfort/learning) -->
        <div id="belfort-learning-section" style="display:none">
          <div class="dp-divider" style="margin-top:8px"></div>
          <div class="dp-section-label" style="margin-top:8px">MOCK TRADING LEARNING</div>
          <div id="learning-verdict-row" class="learning-verdict-row"></div>
          <div id="learning-hurting"        class="learning-item learning-hurting"></div>
          <div id="learning-helping"        class="learning-item learning-helping"></div>
          <div id="learning-recommendation" class="learning-recommendation"></div>
          <div id="learning-history"        class="learning-history"></div>
          <div id="learning-research-goal"  class="learning-research-goal"></div>
          <button id="learning-research-btn" class="learning-research-btn" style="display:none"
                  onclick="belfortResearchWithGoal()">\u25b6 Begin Research</button>
        </div>
        <!-- Mock trading diagnostics (loaded from /belfort/diagnostics) -->
        <div id="belfort-diagnostics-section" style="display:none">
          <div class="dp-divider" style="margin-top:8px"></div>
          <div class="dp-section-label" style="margin-top:8px">MOCK TRADING DIAGNOSTICS</div>
          <div id="diag-strategy" class="diag-block"></div>
          <div id="diag-pnl"      class="diag-block"></div>
          <div id="diag-triggers" class="diag-block"></div>
        </div>
      </div>

      <!-- Frank Lloyd builder workspace (shown only when Frank Lloyd panel is open) -->
      <div id="frank-lloyd-section" style="display:none">

        <!-- Active job workspace: header + stream + review + actions -->
        <div id="fl-job-workspace" style="display:none">
          <div class="dp-divider"></div>
          <!-- Job header: title + phase chip + meta -->
          <div class="fl-job-header">
            <div class="fl-job-title-row">
              <div class="fl-job-title" id="fl-job-title"></div>
              <span class="fl-phase-chip" id="fl-phase-chip"></span>
            </div>
            <div class="fl-job-meta" id="fl-job-meta"></div>
            <div class="fl-source-warning" id="fl-source-warning" style="display:none"></div>
          </div>
          <!-- Work stream: chronological log of what Frank Lloyd is doing -->
          <div class="fl-stream">
            <div class="fl-stream-label">WORK STREAM</div>
            <div id="fl-stream-entries"></div>
          </div>
          <!-- Review area: tabbed Plan + Draft Code (toggle-gated) -->
          <div id="fl-review-area" class="fl-review-area" style="display:none">
            <div class="fl-review-tabs">
              <button id="fl-tab-plan" class="fl-tab fl-tab-active" onclick="flTabSwitch('plan')">Plan</button>
              <button id="fl-tab-code" class="fl-tab" onclick="flTabSwitch('code')" style="display:none">Draft Code</button>
            </div>
            <div id="fl-pane-plan" class="fl-review-pane fl-pane-active">
              <pre id="fl-spec-yaml" class="fl-code-view"></pre>
              <div id="fl-preflight-view" class="fl-draft-notes" style="display:none"></div>
            </div>
            <div id="fl-pane-code" class="fl-review-pane">
              <div id="fl-draft-meta-row" class="fl-draft-meta-row"></div>
              <div id="fl-draft-blocked-msg" class="fl-action-feedback fl-fb-error" style="display:none"></div>
              <div id="fl-draft-notes-view" class="fl-draft-notes" style="display:none"></div>
              <pre id="fl-draft-code" class="fl-code-view" style="display:none"></pre>
            </div>
          </div>
          <!-- Action area: feedback + inline forms (contextual) -->
          <div id="fl-action-area">
            <div id="fl-action-feedback" class="fl-action-feedback" style="display:none"></div>
            <!-- Reject plan form -->
            <div id="fl-reject-form" style="display:none">
              <input id="fl-reject-reason" class="fl-text-input" placeholder="Reason for rejection (required)&hellip;" />
              <div class="fl-form-btns">
                <button class="dp-action-btn primary" style="flex:1" onclick="flRejectConfirm()">CONFIRM REJECT</button>
                <button class="dp-action-btn" onclick="flRejectCancel()">CANCEL</button>
              </div>
            </div>
            <!-- Authorize build form -->
            <div id="fl-authorize-form" style="display:none">
              <input id="fl-authorize-notes" class="fl-text-input" placeholder="Authorization notes (optional)&hellip;" />
              <div class="fl-form-btns">
                <button class="dp-action-btn primary" style="flex:1" onclick="flAuthorizeConfirm()">CONFIRM &mdash; START BUILDING</button>
                <button class="dp-action-btn" onclick="flAuthorizeCancel()">CANCEL</button>
              </div>
            </div>
            <!-- Apply summary: plain-English view of what will be applied -->
            <div id="fl-apply-summary" style="display:none">
              <div class="fl-apply-summary">
                <div class="fl-apply-summary-label">WHAT FRANK LLOYD BUILT</div>
                <div id="fl-apply-summary-content"><span class="fl-apply-loading">Loading summary&hellip;</span></div>
              </div>
            </div>
            <!-- Apply to repo form -->
            <div id="fl-promote-form" style="display:none">
              <div class="fl-field-label" id="fl-promote-form-label">TARGET PATH IN REPO</div>
              <input id="fl-promote-target" type="text" class="fl-text-input" style="margin-top:3px" placeholder="e.g. frank_lloyd/my_module.py" autocomplete="off" spellcheck="false">
              <div id="fl-promote-hint" style="font-size:8px;color:#546e7a;margin-top:3px">New .py file only &mdash; file must not already exist.</div>
              <div class="fl-form-btns">
                <button class="dp-action-btn primary" style="flex:1" id="fl-promote-btn" onclick="flPromoteConfirm()">APPLY TO REPO</button>
                <button class="dp-action-btn" onclick="flPromoteCancel()">CANCEL</button>
              </div>
              <div id="fl-promote-feedback" class="fl-action-feedback" style="display:none"></div>
            </div>
          </div>
        </div><!-- /fl-job-workspace -->

        <!-- Composer: smart build request box -->
        <div id="fl-composer">
          <div class="fl-composer-label">WHAT SHOULD FRANK LLOYD DO?</div>
          <textarea id="fl-compose-prompt" class="fl-prompt-box" rows="4"
            placeholder="Describe what to build, fix, refactor, or improve. Frank Lloyd will plan it and build it.&#10;&#10;Examples:&#10;&bull; Add a /stats endpoint that shows per-build timing.&#10;&bull; Clean up the work stream so old entries disappear after completion.&#10;&bull; Diagnose why Peter and Frank Lloyd feel disconnected."></textarea>
          <div class="fl-form-btns" style="margin-top:6px">
            <button class="dp-action-btn primary" style="flex:1" onclick="flQueueBuild()">BUILD IT</button>
          </div>
          <div id="fl-compose-feedback" class="fl-action-feedback" style="display:none"></div>
        </div>

      </div>

      <!-- Docs viewer (shown only when Docs panel is open) -->
      <div id="docs-section" style="display:none">
        <div class="dp-divider"></div>
        <div class="docs-tabs">
          <button class="docs-tab active" onclick="loadDocsContent('BRD.md', this)">Business Requirements</button>
          <button class="docs-tab" onclick="loadDocsContent('TRD.md', this)">Technical Design</button>
          <button class="docs-tab" onclick="loadDocsContent('CAPABILITY_REGISTRY.md', this)">Capability Registry</button>
          <button class="docs-tab" onclick="loadDocsContent('CHANGE_JOURNAL.md', this)">Change Journal</button>
        </div>
        <div id="docs-content" class="docs-content"><div class="docs-loading">Select a document above&hellip;</div></div>
      </div>
    </div>
    <div id="dp-actions"></div>
  </div>

</div><!-- /scene -->

<script>
// ── Config ────────────────────────────────────────────────────────────────
const STATE_URL = '/neighborhood/state';
const DASH_URL  = 'http://localhost:8502';
const POLL_MS   = 5000;

// ── Global state ─────────────────────────────────────────────────────────
let _lastState               = null;
let _currentSelection        = null;
let _sentinelPanelAutoRan    = false;
let _lastReadiness           = null;
let _lastLearning            = null;
let _flActionBuildId         = null;  // build_id currently targeted by FL action buttons
let _flReviewVisible         = false; // true when review area is open
let _flLastStatus            = null;  // previous job status — for transition detection
let _belfortReadinessLastLoad    = 0;
let _belfortLearningLastLoad     = 0;
let _belfortDiagnosticsLastLoad  = 0;

// Open dashboard tab with a unique timestamp so sessionStorage dedup allows re-fire
function openDashTab(view) {
  window.open(DASH_URL + '?view=' + view + '&ts=' + Date.now(), '_blank');
}

// ── House / ops state class management ───────────────────────────────────
const STATUS_CLASSES = ['st-idle', 'st-active', 'st-review', 'st-warning', 'st-error'];

function setClass(el, cls) {
  if (!el) return;
  STATUS_CLASSES.forEach(c => el.classList.remove(c));
  el.classList.add(cls);
}

function belfortStatusClass(status) {
  const s = (status || '').toLowerCase();
  if (['running_batch','running_session','running_campaign'].includes(s)) return 'st-active';
  if (['waiting_for_review','review_held'].includes(s)) return 'st-review';
  if (['paused_by_budget','stopped_by_guardrail'].includes(s)) return 'st-warning';
  if (s === 'unknown') return 'st-warning';
  return 'st-idle';
}

function belfortLabel(status) {
  const m = {
    idle: 'IDLE', running_batch: 'RUNNING', running_session: 'RUNNING',
    running_campaign: 'RUNNING', waiting_for_review: 'REVIEW',
    review_held: 'REVIEW HELD', paused_by_budget: 'BUDGET PAUSE',
    stopped_by_guardrail: 'GUARDRAIL', unknown: 'UNKNOWN',
  };
  return m[status] || (status || '?').toUpperCase().replace(/_/g, ' ');
}

function belfortSummaryLabel(belfort, supervisor) {
  const tradingOn   = (belfort || {}).trading_active  || false;
  const tradingStop = (belfort || {}).trading_stopping || false;
  const loopOn      = (supervisor || {}).enabled       || false;
  const review      = ['waiting_for_review','review_held'].includes((belfort || {}).status || '');
  if (review)                return 'REVIEW NEEDED';
  if (tradingStop && loopOn) return 'STOPPING \u00b7 RESEARCH ON';
  if (tradingStop)           return 'STOPPING\u2026';
  if (tradingOn && loopOn)   return 'TRADING \u00b7 RESEARCH ON';
  if (tradingOn)             return 'TRADING ON';
  if (loopOn)                return 'RESEARCH ON';
  return 'IDLE';
}

function setSpeech(id, text, show) {
  const el = document.getElementById(id);
  if (!el) return;
  if (text) el.textContent = text;
  el.classList.toggle('visible', !!show && !!text);
}

function setOps(unitId, statusId, cls, label) {
  const unit = document.getElementById(unitId);
  const stat = document.getElementById(statusId);
  if (unit) {
    ['st-ok','st-warning','st-error','st-idle'].forEach(c => unit.classList.remove(c));
    unit.classList.add(cls);
  }
  if (stat) stat.textContent = label;
}

// ── Welcome card ──────────────────────────────────────────────────────────
function showWelcomeIfNew() {
  if (!localStorage.getItem('abode_welcomed')) {
    document.getElementById('welcome-card').classList.add('visible');
  } else {
    // Already welcomed — hide start hint too
    const h = document.getElementById('peter-start-hint');
    if (h) h.style.display = 'none';
  }
}

function dismissWelcome(openPeter) {
  localStorage.setItem('abode_welcomed', '1');
  document.getElementById('welcome-card').classList.remove('visible');
  const h = document.getElementById('peter-start-hint');
  if (h) h.style.display = 'none';
  if (openPeter) selectItem('peter');
}

// ── In-place selection ────────────────────────────────────────────────────
function selectItem(id) {
  // Hide start hint on first interaction
  if (!localStorage.getItem('abode_interacted')) {
    localStorage.setItem('abode_interacted', '1');
    const h = document.getElementById('peter-start-hint');
    if (h) h.style.display = 'none';
  }

  if (_currentSelection === id) { closePanel(); return; }

  document.querySelectorAll('.house.selected, .ops-unit.selected')
    .forEach(el => el.classList.remove('selected'));

  const el = document.getElementById('h-' + id) || document.getElementById('u-' + id);
  if (el) el.classList.add('selected');

  _currentSelection = id;
  if (_lastState) populatePanel(id, _lastState);
  else            setBasicPanel(id);
  document.getElementById('detail-panel').classList.add('open');
}

function closePanel() {
  document.getElementById('detail-panel').classList.remove('open');
  document.querySelectorAll('.house.selected, .ops-unit.selected')
    .forEach(el => el.classList.remove('selected'));
  _currentSelection = null;
  _flReviewVisible            = false;
  _belfortReadinessLastLoad   = 0;
  _belfortLearningLastLoad    = 0;
  _belfortDiagnosticsLastLoad = 0;
  const _de = document.getElementById('docs-content');
  if (_de) _de._docsLoaded = false;
}

// ── Panel population ──────────────────────────────────────────────────────
const _META = {
  peter:          ['PETER',           'Your main interface · workspace guide'],
  belfort:        ['MR BELFORT',      'Runs trading research in the background'],
  'frank-lloyd':  ['FRANK LLOYD',     'Construction house · Stage 1 build specs'],
  custodian:      ['CUSTODIAN',       'Monitors system health and environment'],
  checker:    ['LOOP CHECKER',    'Finds issues and flags suspicious patterns'],
  sentinel:   ['TEST SENTINEL',   'Checks that patches are safe before deploy'],
  supervisor: ['LOOP SUPERVISOR', 'Controls the automated research loop'],
  warden:     ['COST WARDEN',     'Manages AI model usage and routing cost'],
  docs:       ['DOCS',            'Project reference — BRD · TRD · Registry · Journal'],
};

function setBasicPanel(id) {
  const [name, sub] = _META[id] || [id.toUpperCase(), ''];
  document.getElementById('dp-title').textContent    = name;
  document.getElementById('dp-subtitle').textContent = sub;
  document.getElementById('dp-situation').innerHTML  = '<div class="dp-item">Loading\u2026</div>';
  document.getElementById('dp-next').innerHTML       = '';
  document.getElementById('dp-actions').innerHTML    = '';
  // Show/hide special sections — defaults: next visible, chat/controls hidden
  const nxw = document.getElementById('dp-next-wrapper');
  if (nxw) nxw.style.display = '';
  const pcs = document.getElementById('peter-chat-section');
  if (pcs) pcs.style.display = 'none';
  const bcs = document.getElementById('belfort-controls-section');
  if (bcs) bcs.style.display = 'none';
  const fls = document.getElementById('frank-lloyd-section');
  if (fls) fls.style.display = 'none';
  const ds = document.getElementById('docs-section');
  if (ds) ds.style.display = 'none';
}

function setBadge(cls, text) {
  const el = document.getElementById('dp-badge');
  el.className   = 'dp-badge ' + cls;
  el.textContent = text;
}

function setItems(containerId, items) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!items.length) {
    el.innerHTML = '<div class="dp-item" style="color:#37474f">Nothing notable</div>';
    return;
  }
  el.innerHTML = items.map(i =>
    `<div class="dp-item ${i.cls || ''}">${i.text}</div>`
  ).join('');
}

function setActions(actions) {
  const el = document.getElementById('dp-actions');
  if (!el) return;
  el.innerHTML = actions.map(a =>
    a.onclick
      ? `<button class="dp-action-btn ${a.primary ? 'primary' : ''}" onclick="${a.onclick}">${a.text}</button>`
      : `<a class="dp-action-btn ${a.primary ? 'primary' : ''}" href="${a.href}" target="_blank">${a.text}</a>`
  ).join('');
}

function populatePanel(id, state, _skipClear) {
  if (!_skipClear) setBasicPanel(id);
  const belfort    = state.belfort    || {};
  const supervisor = state.supervisor || {};
  const checker    = state.checker    || {};
  const custodian  = state.custodian  || {};
  const sentinel   = state.sentinel   || {};
  const warden     = state.warden     || {};

  if (id === 'peter') {
    const bStatus      = belfort.status || 'unknown';
    const reviewNeeded = ['waiting_for_review','review_held'].includes(bStatus);
    const warns        = checker.open_warnings || 0;
    const custBad      = custodian.overall === 'degraded';
    const sentBad      = ['review','not_ready'].includes(sentinel.verdict || '');
    const flRelay      = (state.frank_lloyd || {}).fl_relay || [];
    const flJob        = (state.frank_lloyd || {}).active_job || null;
    const flStatus     = (flJob || {}).status || '';
    const flNeedsReview = ['pending_review', 'draft_generated'].includes(flStatus);
    const flNeedsAttn   = flStatus === 'draft_blocked';
    const needsAttn    = warns > 0 || custBad || sentBad || flNeedsAttn || flRelay.some(r => ['review_needed','spec_blocked','draft_blocked'].includes(r.event));
    const cls          = (reviewNeeded || flNeedsReview) ? 'review' : needsAttn ? 'warning' : 'idle';
    const label        = (reviewNeeded || flNeedsReview) ? 'REVIEW NEEDED' : needsAttn ? 'ATTENTION NEEDED' : 'AVAILABLE';
    setBadge(cls, label);
    document.getElementById('dp-status-detail').textContent = '';

    const sit = [];
    if (reviewNeeded)  sit.push({text: 'A research result is ready for your review', cls: 'warn'});
    if (flNeedsReview && flStatus === 'pending_review')
      sit.push({text: 'Frank Lloyd plan ready: \u201c' + _escHtml((flJob.title || flJob.build_id) || '') + '\u201d \u2014 review in FL panel', cls: 'warn'});
    if (flNeedsReview && flStatus === 'draft_generated')
      sit.push({text: 'Frank Lloyd draft ready: \u201c' + _escHtml((flJob.title || flJob.build_id) || '') + '\u201d \u2014 apply or discard in FL panel', cls: 'warn'});
    if (flNeedsAttn)   sit.push({text: 'Frank Lloyd draft blocked \u2014 check FL panel', cls: 'warn'});
    if (warns > 0)     sit.push({text: `${warns} issue${warns > 1 ? 's' : ''} flagged by the audit system`, cls: 'warn'});
    if (custBad)       sit.push({text: 'System health needs attention', cls: 'warn'});
    if (sentBad)       sit.push({text: `Patch safety check: ${(sentinel.verdict || '').replace('_',' ')}`, cls: 'warn'});
    if (!sit.length)   sit.push({text: 'No urgent items', cls: 'ok'});
    setItems('dp-situation', sit);

    // Inject Frank Lloyd relay messages into Peter's chat (relay = Frank Lloyd → Peter)
    if (flRelay.length) {
      flRelay.forEach(r => {
        const isAlert = ['review_needed','spec_blocked','draft_blocked'].includes(r.event);
        _peterChat.push({role: 'peter', text: '\uD83D\uDEA7 Frank Lloyd: ' + r.msg, cls: isAlert ? 'warn' : ''});
      });
      peterChatRender();
    }

    // Show chat section instead of NEXT
    const nxw = document.getElementById('dp-next-wrapper');
    if (nxw) nxw.style.display = 'none';
    const pcs = document.getElementById('peter-chat-section');
    if (pcs) pcs.style.display = '';

    const lmAvail = !!state.lm_available;
    const notice = document.getElementById('peter-chat-notice');
    if (notice) notice.classList.toggle('visible', !lmAvail);
    const cinp = document.getElementById('peter-chat-input');
    if (cinp) cinp.placeholder = lmAvail ? 'Ask anything\u2026' : 'AI chat offline \u2014 API key not set';

    if (!_peterChat.length) {
      _peterChat = [{role: 'peter', text: lmAvail
        ? 'Ready. Ask me anything about the system.'
        : 'AI chat is offline \u2014 OpenRouter API key is not configured. Deterministic status above is always available.'}];
    }
    peterChatRender();
    if (cinp && !cinp._enterBound) {
      cinp._enterBound = true;
      cinp.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); peterChatSend(); }
      });
      cinp.addEventListener('input', function() { _peterInputGrow(this); });
    }
    setActions([{text: '\u26a1 Open Peter workspace \u2192', onclick: "openDashTab('peter')", primary: true}]);
  }

  else if (id === 'belfort') {
    const bStatus      = belfort.status || 'unknown';
    const tradingOn    = belfort.trading_active || false;
    const tradingStop  = belfort.trading_stopping || false;
    const loopOn       = supervisor.enabled || false;
    const cls          = belfortStatusClass(bStatus).replace('st-', '') || 'idle';
    setBadge(cls === 'st-idle' ? 'idle' : cls, belfortSummaryLabel(belfort, supervisor));
    const tradingLabel = tradingStop ? 'Trading STOPPING\u2026'
                       : tradingOn   ? 'Trading ON'
                       :               'Trading OFF';
    document.getElementById('dp-status-detail').textContent =
      tradingLabel + (loopOn ? ' \u00b7 Research ON' : ' \u00b7 Research OFF');

    // Trading-first situation
    const openPos       = belfort.open_positions || [];
    const reviewPending = ['waiting_for_review','review_held'].includes(bStatus);
    const idle          = !tradingOn && !loopOn && !reviewPending;
    const sit = [];
    if (reviewPending)
      sit.push({text: '\u26a1 Research result ready \u2014 approve or reject below', cls: 'warn'});
    if (idle) {
      // Clean idle — no live trading or research active; show historical context only
      sit.push({text: 'Idle \u2014 trading and research are both off'});
      const lt = belfort.last_trade;
      if (lt) {
        const ltP = lt.pnl != null ? (' (' + (lt.pnl >= 0 ? '+$' : '-$') + Math.abs(lt.pnl).toFixed(2) + ')') : '';
        sit.push({text: 'Last trade: ' + lt.side + '\u00a0' + (lt.symbol || '?') + ' @ $' + (lt.price != null ? lt.price.toFixed(2) : '?') + ltP + ' (historical)'});
      }
    } else {
      // Active or review state — show live position and trade data
      if (openPos.length > 0) {
        sit.push({text: 'Position: ' + openPos.join(', ') + ' (open)', cls: 'ok'});
      } else if (tradingOn) {
        sit.push({text: 'Position: FLAT \u2014 no open position'});
      }
      const lt = belfort.last_trade;
      if (lt) {
        const ltP = lt.pnl != null ? (' (' + (lt.pnl >= 0 ? '+$' : '-$') + Math.abs(lt.pnl).toFixed(2) + ')') : '';
        const ltCls = lt.pnl != null && lt.pnl < 0 ? 'warn' : lt.pnl != null && lt.pnl > 0 ? 'ok' : '';
        sit.push({text: 'Last trade: ' + lt.side + '\u00a0' + (lt.symbol || '?') + ' @ $' + (lt.price != null ? lt.price.toFixed(2) : '?') + ltP, cls: ltCls});
      }
    }
    setItems('dp-situation', sit);

    // Show controls section instead of NEXT
    const nxw = document.getElementById('dp-next-wrapper');
    if (nxw) nxw.style.display = 'none';
    const bcs = document.getElementById('belfort-controls-section');
    if (bcs) bcs.style.display = '';
    updateBelfortStats(belfort, supervisor);
    // Show/hide inline review card based on current Belfort status
    if (['waiting_for_review','review_held'].includes(bStatus)) {
      loadBelfortReviewCard();
    } else {
      const rc = document.getElementById('belfort-review-card');
      if (rc) rc.style.display = 'none';
    }
    // Frank Lloyd cross-reference — show if an active build is about Belfort
    const flBelfortWork = document.getElementById('fl-belfort-work');
    if (flBelfortWork) {
      const flRel = (state.frank_lloyd || {}).belfort_related_build;
      if (flRel && flRel.status !== 'draft_promoted') {
        const statusLabel = (flRel.status || '').replace(/_/g, ' ');
        flBelfortWork.innerHTML = '<strong>Frank Lloyd working on:</strong> '
          + _escHtml(flRel.title || flRel.build_id)
          + ' <span style="color:#37474f">[\u202f' + _escHtml(statusLabel) + '\u202f]</span>';
        flBelfortWork.style.display = '';
      } else {
        flBelfortWork.style.display = 'none';
      }
    }
    // Load readiness scorecard, learning pulse, and diagnostics
    loadBelfortReadiness();
    loadBelfortLearning();
    loadBelfortDiagnostics();
    setActions([{text: '\ud83d\udcca Open Belfort workspace \u2192', onclick: "openDashTab('belfort')", primary: true}]);
  }

  else if (id === 'frank-lloyd') {
    const fl      = state.frank_lloyd || {};
    const pending = fl.pending_count    || 0;
    const inprog  = fl.inprogress_count || 0;
    const complete= fl.completed_count  || 0;
    const job     = fl.active_job       || null;
    const jStatus = (job || {}).status  || '';

    // Status badge — maps to visible builder phase
    let flCls, flLabel;
    if      (jStatus === 'draft_promoted')   { flCls = 'ok';      flLabel = 'APPLIED'; }
    else if (jStatus === 'draft_generated')  { flCls = 'review';  flLabel = 'DRAFT READY'; }
    else if (jStatus === 'draft_blocked')    { flCls = 'warning'; flLabel = 'BLOCKED'; }
    else if (['draft_generating','stage2_authorized','spec_approved'].includes(jStatus))
                                             { flCls = 'active';  flLabel = 'BUILDING'; }
    else if (jStatus === 'pending_review')   { flCls = 'review';  flLabel = 'NEEDS REVIEW'; }
    else if (pending > 0)                    { flCls = 'warning'; flLabel = 'QUEUED'; }
    else                                     { flCls = 'idle';    flLabel = 'IDLE'; }
    setBadge(flCls, flLabel);
    document.getElementById('dp-status-detail').textContent =
      job ? (job.build_id || '') : `${pending} queued \u00b7 ${inprog} active \u00b7 ${complete} done`;

    // Situation
    const sit = [];
    if (job && jStatus === 'draft_promoted') {
      sit.push({text: '\u2713 Applied: ' + _escHtml(job.title || job.build_id), cls: 'ok'});
    } else if (job) {
      sit.push({text: job.next_action || 'Building\u2026', cls: 'warn'});
    } else if (pending > 0) {
      sit.push({text: `${pending} build${pending > 1 ? 's' : ''} queued \u2014 Frank Lloyd is ready`});
    } else {
      sit.push({text: 'No active builds \u2014 describe what to build below'});
    }
    setItems('dp-situation', sit);

    // Show Frank Lloyd section, hide NEXT
    const nxw = document.getElementById('dp-next-wrapper');
    if (nxw) nxw.style.display = 'none';
    const fls = document.getElementById('frank-lloyd-section');
    if (fls) fls.style.display = '';

    // Render builder workspace
    _flRenderWorkspace(job);

    // Contextual actions — only show what makes sense for the current state.
    // Safe lane states (pending_spec, spec_approved, stage2_authorized) collapse
    // into a single "Building…" indicator when auto-run is in progress.
    const flActions = [];
    if (job) {
      switch (jStatus) {
        case 'pending_spec':
          // Auto-run usually fires automatically on queue; show a start button as fallback
          flActions.push({text: '\u25b6 START BUILDING', onclick: 'flAutoRun()', primary: true});
          break;
        case 'pending_review':
          // Plan ready — manual review gate (safe lane paused due to medium/high risk)
          flActions.push({text: '\u2713 APPROVE PLAN',   onclick: 'flApproveSpec()',    primary: true});
          flActions.push({text: '\u2715 REJECT PLAN',    onclick: 'flShowRejectForm()', primary: false});
          flActions.push({text: _flReviewVisible ? '\u25b4 Hide plan' : '\u25be View plan', onclick: 'flToggleReview()', primary: false});
          break;
        case 'spec_approved':
          // After manual approval — authorize Stage 2 to proceed
          flActions.push({text: '\u26a1 START BUILDING', onclick: 'flShowAuthorizeForm()', primary: true});
          flActions.push({text: _flReviewVisible ? '\u25b4 Hide plan' : '\u25be View plan', onclick: 'flToggleReview()', primary: false});
          break;
        case 'stage2_authorized':
          // Authorized but not yet building — generate draft
          flActions.push({text: '\u2699 GENERATE DRAFT', onclick: 'flGenerateDraft()',  primary: true});
          flActions.push({text: _flReviewVisible ? '\u25b4 Hide plan' : '\u25be View plan', onclick: 'flToggleReview()', primary: false});
          break;
        case 'draft_generating':
          // Frank Lloyd is working — no action buttons; stream shows live progress
          break;
        case 'draft_generated':
          // Apply summary is auto-shown; apply is the primary action
          flActions.push({text: '\u2713 APPLY TO REPO',  onclick: 'flShowPromoteForm()', primary: true});
          flActions.push({text: '\u2715 DISCARD',        onclick: 'flDiscardDraft()',    primary: false});
          flActions.push({text: _flReviewVisible ? '\u25b4 Hide code' : '\u25be View code', onclick: 'flToggleReview()', primary: false});
          break;
        case 'draft_blocked':
          flActions.push({text: '\u21ba DISCARD \u0026 RETRY', onclick: 'flDiscardDraft()', primary: true});
          flActions.push({text: _flReviewVisible ? '\u25b4 Hide details' : '\u25be View reason', onclick: 'flToggleReview()', primary: false});
          break;
        case 'draft_promoted':
          // Build complete — no actions; just show status
          break;
      }
      // CANCEL available for any active (non-terminal, non-auto-building) state
      const _terminalStates = ['draft_promoted','spec_rejected','abandoned'];
      const _autoStates     = ['draft_generating','pending_spec'];  // auto-running; cancel via abandon
      if (!_terminalStates.includes(jStatus)) {
        flActions.push({text: '\u2715 CANCEL BUILD', onclick: 'flAbandon()', primary: false});
      }
    }
    setActions(flActions);
  }

  else if (id === 'custodian') {
    const overall = custodian.overall || 'unknown';
    const cls = overall === 'healthy' ? 'ok' : overall === 'degraded' ? 'warning' : 'idle';
    setBadge(cls, overall.toUpperCase());
    document.getElementById('dp-status-detail').textContent = '';
    const sit = custodian.summary
      ? [{text: custodian.summary.slice(0, 90)}]
      : [{text: 'No recent health check data \u2014 run a check to start'}];
    setItems('dp-situation', sit);
    setItems('dp-next', [{text: overall === 'healthy' ? 'All services healthy' : 'Run check to get a fresh report'}]);
    document.getElementById('dp-actions').innerHTML =
      `<button class="dp-action-btn" id="refresh-btn-custodian" onclick="refreshOpsPanel('custodian')">\ud83d\udd27 Run health check</button>` +
      `<a class="dp-action-btn primary" href="${DASH_URL}?view=controls" target="_blank">Open Controls \u2192</a>`;
  }

  else if (id === 'checker') {
    const warns = checker.open_warnings || 0;
    const total = checker.total_findings || 0;
    setBadge(warns > 0 ? 'warning' : 'ok', warns > 0 ? `${warns} WARNINGS` : 'CLEAR');
    document.getElementById('dp-status-detail').textContent =
      total > 0 ? `${total} total findings` : '';
    const sit = [];
    if (warns > 0) sit.push({text: `${warns} unacknowledged warning${warns > 1 ? 's' : ''}`, cls: 'warn'});
    else           sit.push({text: 'No open warnings', cls: 'ok'});
    if (total > 0) sit.push({text: `${total} total findings on record`});
    setItems('dp-situation', sit);
    setItems('dp-next', warns > 0
      ? [{text: 'Review findings in Controls for full detail'}]
      : [{text: 'System clear \u2014 checker runs continuously'}]);
    document.getElementById('dp-actions').innerHTML =
      `<button class="dp-action-btn" id="refresh-btn-checker" onclick="refreshOpsPanel('checker')">\ud83d\udd04 Refresh findings</button>` +
      `<a class="dp-action-btn primary" href="${DASH_URL}?view=controls" target="_blank">Open Controls \u2192</a>`;
  }

  else if (id === 'sentinel') {
    const v = sentinel.verdict || 'unknown';
    const cls = v === 'safe' ? 'ok' : v === 'not_ready' ? 'error' : v === 'review' ? 'warning' : 'idle';
    setBadge(cls, v.toUpperCase().replace('_', ' '));
    document.getElementById('dp-status-detail').textContent =
      sentinel.passed != null ? `${sentinel.passed} passed · ${sentinel.failed || 0} failed` : '';
    const sit = [];
    if (v === 'safe')      sit.push({text: `${sentinel.passed} tests passed`, cls: 'ok'});
    else if (v === 'not_ready') sit.push({text: `${sentinel.failed || 0} tests failed — not safe`, cls: 'warn'});
    else if (v === 'review')    sit.push({text: 'Needs review before deploy', cls: 'warn'});
    else                        sit.push({text: 'No sentinel report available'});
    setItems('dp-situation', sit);
    setItems('dp-next', (v !== 'safe' && v !== 'unknown')
      ? [{text: 'Review sentinel report in Controls'}]
      : [{text: 'Run smoke check to verify patches are safe'}]);
    document.getElementById('dp-actions').innerHTML =
      `<button class="dp-action-btn" id="sentinel-run-btn" onclick="runSentinelSmoke()">🧪 Run smoke check</button>` +
      `<a class="dp-action-btn primary" href="${DASH_URL}?view=controls" target="_blank">Open Controls →</a>`;
    // Auto-run smoke check once per page load when verdict is unknown
    if (!_sentinelPanelAutoRan && v === 'unknown') {
      _sentinelPanelAutoRan = true;
      setTimeout(() => runSentinelSmoke(), 350);
    }
  }

  else if (id === 'supervisor') {
    const on = supervisor.enabled;
    setBadge(on ? 'active' : supervisor.errors > 0 ? 'warning' : 'idle', on ? 'RUNNING' : 'OFF');
    document.getElementById('dp-status-detail').textContent =
      on ? `Cycle ${supervisor.cycle_count || 0}` : '';
    const sit = [];
    if (on)                        sit.push({text: `Running \u2014 cycle ${supervisor.cycle_count || 0}`, cls: 'ok'});
    if (supervisor.stop_requested) sit.push({text: 'Stop requested', cls: 'warn'});
    if (supervisor.errors > 0)     sit.push({text: `${supervisor.errors} consecutive errors`, cls: 'warn'});
    if (!on && !supervisor.errors) sit.push({text: 'Research is off \u2014 enable via Belfort controls'});
    setItems('dp-situation', sit);
    setItems('dp-next', [{text: on ? 'View research detail in Controls' : 'Enable via Belfort \u2192 Begin Research'}]);
    document.getElementById('dp-actions').innerHTML =
      `<button class="dp-action-btn" id="refresh-btn-supervisor" onclick="refreshOpsPanel('supervisor')">\ud83d\udd04 Refresh status</button>` +
      `<a class="dp-action-btn primary" href="${DASH_URL}?view=controls" target="_blank">Open Controls \u2192</a>`;
  }

  else if (id === 'warden') {
    const calls = warden.total_calls || 0;
    const cost  = warden.total_cost_usd || 0;
    setBadge(calls > 0 ? 'ok' : 'idle', calls > 0 ? 'ACTIVE' : 'NO CALLS');
    document.getElementById('dp-status-detail').textContent =
      calls > 0 ? `$${cost.toFixed(4)} / ${calls} calls` : '';
    const sit = calls > 0
      ? [{text: `${calls} recent LM calls \u00b7 $${cost.toFixed(4)} total`, cls: 'ok'}]
      : [{text: 'No LM calls recorded \u2014 API key may not be set'}];
    setItems('dp-situation', sit);
    setItems('dp-next', [{text: 'Full cost breakdown in Controls'}]);
    document.getElementById('dp-actions').innerHTML =
      `<button class="dp-action-btn" id="refresh-btn-warden" onclick="refreshOpsPanel('warden')">\ud83d\udd04 Refresh summary</button>` +
      `<a class="dp-action-btn primary" href="${DASH_URL}?view=controls" target="_blank">Open Controls \u2192</a>`;
  }

  else if (id === 'docs') {
    setBadge('idle', 'READ ONLY');
    document.getElementById('dp-status-detail').textContent = '4 project documents';
    setItems('dp-situation', [{text: 'Select a tab to read the document'}]);
    const nxw = document.getElementById('dp-next-wrapper');
    if (nxw) nxw.style.display = 'none';
    const ds = document.getElementById('docs-section');
    if (ds) ds.style.display = '';
    setActions([]);
    // Auto-load BRD on first open
    const el = document.getElementById('docs-content');
    if (el && !el._docsLoaded) {
      el._docsLoaded = true;
      const firstTab = document.querySelector('.docs-tab');
      loadDocsContent('BRD.md', firstTab);
    }
  }
}

// ── Docs viewer ───────────────────────────────────────────────────────────
function _inlineMd(s) {
  return s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
           .replace(/`([^`]+)`/g, '<span class="docs-code">$1</span>');
}

function _renderMd(text) {
  const out = [];
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd();
    if (line.startsWith('### '))       out.push(`<div class="docs-h3">${_inlineMd(_escHtml(line.slice(4)))}</div>`);
    else if (line.startsWith('## '))   out.push(`<div class="docs-h2">${_inlineMd(_escHtml(line.slice(3)))}</div>`);
    else if (line.startsWith('# '))    out.push(`<div class="docs-h1">${_inlineMd(_escHtml(line.slice(2)))}</div>`);
    else if (/^---+$/.test(line))      out.push('<div class="docs-hr"></div>');
    else if (line.startsWith('- ') || line.startsWith('* '))
                                       out.push(`<div class="docs-bullet">${_inlineMd(_escHtml(line.slice(2)))}</div>`);
    else if (line.startsWith('| ') || (line.startsWith('|') && line.includes('|', 1))) {
      if (!/^[\|:\-\s]+$/.test(line)) out.push(`<div class="docs-table-row">${_inlineMd(_escHtml(line.replace(/\|/g, ' · ')))}</div>`);
    }
    else if (line === '')              out.push('<div style="height:4px"></div>');
    else                               out.push(`<div class="docs-p">${_inlineMd(_escHtml(line))}</div>`);
  }
  return out.join('');
}

async function loadDocsContent(file, tabEl) {
  document.querySelectorAll('.docs-tab').forEach(t => t.classList.remove('active'));
  if (tabEl) tabEl.classList.add('active');
  const el = document.getElementById('docs-content');
  if (!el) return;
  el.innerHTML = '<div class="docs-loading">Loading\u2026</div>';
  try {
    const r = await fetch('/neighborhood/docs?file=' + encodeURIComponent(file));
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    el.innerHTML = _renderMd(d.content || '(empty)');
    el.scrollTop = 0;
  } catch(e) {
    el.innerHTML = `<div class="docs-loading">Could not load ${_escHtml(file)} \u2014 ${_escHtml(e.message)}</div>`;
  }
}

// ── Sentinel inline smoke run ─────────────────────────────────────────────
async function runSentinelSmoke() {
  const btn = document.getElementById('sentinel-run-btn');
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.textContent = '⏳ CHECKING…';
  try {
    const r = await fetch('/sentinel/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({scope: 'smoke'}),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();

    const v   = d.verdict || 'unknown';
    const cls = v === 'safe' ? 'ok' : v === 'not_ready' ? 'error' : v === 'review' ? 'warning' : 'idle';
    setBadge(cls, v.toUpperCase().replace('_', ' '));
    document.getElementById('dp-status-detail').textContent =
      (d.passed != null) ? `${d.passed} passed · ${d.failed || 0} failed` : '';

    const sit = [];
    if (v === 'safe')           sit.push({text: `${d.passed} tests passed`, cls: 'ok'});
    else if (v === 'not_ready') sit.push({text: `${d.failed || 0} tests failed — not safe`, cls: 'warn'});
    else if (v === 'review')    sit.push({text: 'Review required before deploy', cls: 'warn'});
    else                        sit.push({text: d.summary || 'Check complete'});
    setItems('dp-situation', sit);
    setItems('dp-next', [{text: v === 'safe' ? 'All clear' : 'Review full report in Controls'}]);

    // Propagate result into global state so ops unit badge updates immediately
    if (_lastState) {
      _lastState.sentinel = {verdict: d.verdict, passed: d.passed, failed: d.failed || 0};
      applyState(_lastState);
    }

    btn.disabled = false;
    btn.textContent = '🔁 Run again';
  } catch(e) {
    btn.disabled = false;
    btn.textContent = '🧪 Run smoke check';
    setBadge('warning', 'ERROR');
    setItems('dp-situation', [{text: `Could not reach backend — ${e.message}`, cls: 'warn'}]);
  }
}

// ── Peter deterministic layer ─────────────────────────────────────────────
function _peterDeterministicAnswer(msg) {
  if (!_lastState) return 'No state data yet \u2014 try again in a moment.';
  const belfort    = _lastState.belfort    || {};
  const supervisor = _lastState.supervisor || {};
  const checker    = _lastState.checker    || {};
  const custodian  = _lastState.custodian  || {};
  const sentinel   = _lastState.sentinel   || {};

  const bStatus      = belfort.status || 'unknown';
  const tradingOn    = belfort.trading_active || false;
  const loopOn       = supervisor.enabled || false;
  const reviewNeeded = ['waiting_for_review','review_held'].includes(bStatus);
  const warns        = checker.open_warnings || 0;
  const custBad      = custodian.overall === 'degraded';
  const sentBad      = ['review','not_ready'].includes(sentinel.verdict || '');
  const openPos      = belfort.open_positions || [];
  const trades       = belfort.trade_count || 0;
  const pnl          = (belfort.realized_pnl || 0) + (belfort.unrealized_pnl || 0);
  const pnlAbs       = Math.abs(pnl);
  const pnlStr       = (pnl >= 0 ? '+$' : '-$') + (pnlAbs >= 1000 ? (pnlAbs/1000).toFixed(2)+'k' : pnlAbs.toFixed(2));
  const lt           = belfort.last_trade;
  const lower        = msg.toLowerCase();

  if (lower.includes('happen') || lower.includes('going on') || lower.includes('status') || lower.includes('right now')) {
    const parts = [];
    parts.push('Trading is ' + (tradingOn ? 'ON.' : 'OFF.'));
    parts.push('Research is ' + (loopOn ? ('ON \u2014 cycle ' + (supervisor.cycle_count || 0) + '.') : 'OFF.'));
    if (reviewNeeded) parts.push('A result is waiting for your review.');
    if (openPos.length > 0) {
      parts.push('Open position: ' + openPos.join(', ') + '.');
    } else if (lt && tradingOn) {
      const ltP = lt.pnl != null ? (' (' + (lt.pnl >= 0 ? '+$' : '-$') + Math.abs(lt.pnl).toFixed(2) + ')') : '';
      parts.push('Last trade: ' + lt.side + '\u00a0' + lt.symbol + ltP + '.');
    } else if (trades === 0) {
      parts.push('No trades yet \u2014 portfolio is at baseline.');
    }
    // Frank Lloyd status
    const _fl    = (_lastState || {}).frank_lloyd || {};
    const _flJob = _fl.active_job || null;
    if (_flJob) {
      const _jStatus = _flJob.status || '';
      const _jTitle  = _flJob.title  || _flJob.build_id || '';
      const _flShort = {
        pending_spec:      'Frank Lloyd is planning \u201c' + _jTitle + '\u201d.',
        pending_review:    'Frank Lloyd plan ready for \u201c' + _jTitle + '\u201d \u2014 needs your review.',
        spec_approved:     'Frank Lloyd plan approved for \u201c' + _jTitle + '\u201d.',
        stage2_authorized: 'Frank Lloyd authorized to build \u201c' + _jTitle + '\u201d.',
        draft_generating:  'Frank Lloyd is generating code for \u201c' + _jTitle + '\u201d.',
        draft_generated:   'Frank Lloyd draft ready for \u201c' + _jTitle + '\u201d.',
        draft_blocked:     'Frank Lloyd draft blocked on \u201c' + _jTitle + '\u201d.',
        draft_promoted:    '\u201c' + _jTitle + '\u201d applied to repo.',
      };
      if (_flShort[_jStatus]) parts.push(_flShort[_jStatus]);
    } else if ((_fl.pending_count || 0) > 0) {
      parts.push('Frank Lloyd has ' + _fl.pending_count + ' build' + (_fl.pending_count > 1 ? 's' : '') + ' queued.');
    }
    return parts.join(' ');
  }

  if (lower.includes('attention') || lower.includes('need') || lower.includes('urgent') || lower.includes('issue')) {
    const items = [];
    if (reviewNeeded) items.push('A research result is waiting for your review \u2014 open the Belfort workspace.');
    if (warns > 0)    items.push(warns + ' audit warning' + (warns > 1 ? 's' : '') + ' flagged by the Loop Checker.');
    if (custBad)      items.push('System health is degraded \u2014 click Custodian and run a health check.');
    if (sentBad)      items.push('Test Sentinel shows ' + (sentinel.verdict || '').replace('_', ' ') + ' \u2014 click Sentinel and run a smoke check.');
    if (supervisor.stop_requested) items.push('Research stop was requested.');
    if (!items.length) return 'Nothing needs attention right now. Trading: ' + (tradingOn ? 'ON' : 'OFF') + ', Research: ' + (loopOn ? 'ON' : 'OFF') + '.';
    return items.join(' ');
  }

  if (lower.includes('next') || lower.includes('should i') || lower.includes('what do') || lower.includes('what to')) {
    if (reviewNeeded) return 'Open the Belfort workspace \u2014 a research result is waiting for your approval.';
    if (warns > 0)    return 'Check the Loop Checker panel: ' + warns + ' warning' + (warns > 1 ? 's need' : ' needs') + ' review in Controls.';
    if (custBad)      return 'Click Custodian and run a health check to diagnose the system issue.';
    if (sentBad)      return 'Click Sentinel and run a smoke check to clear the safety flag.';
    // Use learning verdict to guide next action
    if (_lastLearning) {
      const lv = _lastLearning.verdict;
      const rt = _lastLearning.research_triggers;
      if (lv === 'research' && !loopOn) {
        return (rt && rt.recommendation ? rt.recommendation : 'Research recommended.') + ' Use the Begin Research button in the Belfort panel or Controls tab.';
      }
      if (lv === 'tune') {
        return 'Strategy may need adjustment \u2014 ' + (_lastLearning.verdict_note || '') + ' Consider running a targeted research campaign.';
      }
    }
    if (!tradingOn && !loopOn) return 'Click the Belfort house and use the controls to start mock trading or begin research.';
    if (loopOn)       return 'Research is running on cycle ' + (supervisor.cycle_count || 0) + '. Watch for review-needed status on the Belfort house.';
    return 'Mock trading is active. Watch the Belfort house for position updates.';
  }

  if (lower.includes('run research') || lower.includes('start research') || lower.includes('begin research')) {
    if (loopOn) return 'Research is already running on cycle ' + (supervisor.cycle_count || 0) + '. Watch for review-needed status on the Belfort house.';
    const L = _lastLearning;
    if (L && L.verdict === 'research') {
      const rt = L.research_triggers;
      return (rt && rt.recommendation ? rt.recommendation : 'Research recommended.') + ' Use Begin Research in the Belfort panel or Controls tab.';
    }
    const verdict = L ? L.verdict : null;
    return verdict
      ? 'No active research trigger. Verdict: ' + verdict.toUpperCase() + ' \u2014 ' + (L.verdict_note || '') + '. You can still start research manually via Controls.'
      : 'Open the Belfort panel first to load learning status, then use Begin Research in Controls if needed.';
  }

  if (lower.includes('pattern') || lower.includes('history') || lower.includes('past session') || lower.includes('repeated') || lower.includes('how many session')) {
    const L = _lastLearning;
    if (!L) return 'Open the Belfort panel first \u2014 learning data will load automatically.';
    const hc = L.historical_context;
    if (!hc || hc.entry_count === 0) return 'No prior sessions in learning history yet \u2014 history builds after the first baseline reset.';
    const base = `${hc.entry_count} session${hc.entry_count !== 1 ? 's' : ''} in learning history.`;
    if (hc.patterns && hc.patterns.length > 0) {
      return base + ' Patterns: ' + hc.patterns.slice(0, 2).join('; ') + '.';
    }
    return base + ' ' + (hc.summary || 'No repeated patterns detected yet.');
  }

  if (lower.includes('what research') || lower.includes('research goal') || lower.includes('why research') || lower.includes('why should belfort')) {
    const L = _lastLearning;
    if (!L) return 'Open the Belfort panel first \u2014 learning data will load automatically.';
    const goal = L.research_goal;
    const rt   = L.research_triggers;
    if (goal) {
      const topReason = rt && rt.reasons && rt.reasons[0] ? ' Reason: ' + rt.reasons[0] + '.' : '';
      return 'Suggested research goal: \u201c' + goal + '\u201d.' + topReason;
    }
    if (rt && rt.triggered) {
      return 'Research recommended: ' + rt.recommendation + (rt.reasons && rt.reasons[0] ? ' Top trigger: ' + rt.reasons[0] : '') + '.';
    }
    return 'No active research trigger. Current verdict: ' + (L.verdict || 'continue').toUpperCase() + '.';
  }

  if (lower.includes('learn') || lower.includes('how is belfort') || lower.includes('what is hurting') || lower.includes('what is helping') || lower.includes('is the strategy')) {
    const L = _lastLearning;
    if (!L) return 'Open the Belfort panel first \u2014 learning data will load automatically.';
    const topHurt = L.hurting && L.hurting[0] ? L.hurting[0] : 'nothing flagged';
    const topHelp = L.helping && L.helping[0] ? L.helping[0] : 'nothing noted yet';
    const pnlStr  = (L.realized_pnl >= 0 ? '+$' : '-$') + Math.abs(L.realized_pnl || 0).toFixed(2);
    const wrStr   = L.win_rate != null ? (', ' + Math.round(L.win_rate * 100) + '% win rate') : '';
    return (
      'Learning verdict: ' + (L.verdict || '?').toUpperCase() + '. '
      + 'Main issue: ' + topHurt + '. '
      + 'What\u2019s helping: ' + topHelp + '. '
      + 'P\u0026L ' + pnlStr + wrStr + ', '
      + (L.total_closed || 0) + ' closed trades.'
    );
  }

  if (lower.includes('ready') || lower.includes('live') || lower.includes('readiness') || lower.includes('mentor') || lower.includes('progress') || lower.includes('explain belfort')) {
    const r = _lastReadiness;
    if (!r) return 'Readiness data not loaded yet \u2014 open the Belfort panel first.';
    // Use mentor_summary if available (structured verbal update)
    if (r.mentor_summary) return r.mentor_summary;
    // Fallback to structured inline answer
    const level = (r.level_label || r.level || 'unknown').toUpperCase().replace(/_/g, ' ');
    const wr    = r.win_rate != null ? (Math.round(r.win_rate * 100) + '% win rate') : null;
    const pnl   = (belfort.realized_pnl || 0);
    const pnlS  = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
    return (
      'Belfort readiness: ' + level + '. '
      + r.gates_passed + '/' + r.gates_total + ' gates. '
      + (r.last_adoption ? 'Adopted ' + r.last_adoption + '. ' : '')
      + (trades > 0 ? trades + ' trades, P\u0026L ' + pnlS + (wr ? ', ' + wr : '') + '.' : 'No trades yet.')
    );
  }

  // Frank Lloyd status queries — deterministic, no LM needed
  if (/frank\s*lloyd|builder|building|fl\b/.test(lower)) {
    const fl     = (_lastState || {}).frank_lloyd || {};
    const job    = fl.active_job || null;
    const pend   = fl.pending_count || 0;
    if (!job && pend === 0) return 'Frank Lloyd is idle. Describe what to build in the Frank Lloyd panel or here.';
    if (!job && pend > 0) return pend + ' build' + (pend > 1 ? 's' : '') + ' queued \u2014 Frank Lloyd is picking up work.';
    const jTitle  = job.title || job.build_id || '';
    const jStatus = job.status || '';
    const jMode   = job.mode   ? ' (' + job.mode + ')' : '';
    const statusText = {
      pending_spec:      'Planning' + jMode + ': \u201c' + jTitle + '\u201d \u2014 generating spec.',
      pending_review:    'Plan ready' + jMode + ' for \u201c' + jTitle + '\u201d. Needs your review \u2014 approve or reject in the Frank Lloyd panel.',
      spec_approved:     '\u201c' + jTitle + '\u201d plan approved. Authorize Stage 2 to start draft generation.',
      stage2_authorized: '\u201c' + jTitle + '\u201d authorized. Draft generation starting shortly.',
      draft_generating:  'Frank Lloyd is writing code for \u201c' + jTitle + '\u201d' + jMode + '. Check back in a moment.',
      draft_generated:   'Draft ready for \u201c' + jTitle + '\u201d. Review the apply summary, then apply or discard.',
      draft_blocked:     'Draft blocked on \u201c' + jTitle + '\u201d. Discard and retry from the Frank Lloyd panel.',
      draft_promoted:    '\u201c' + jTitle + '\u201d applied to repo. Build complete.',
      spec_rejected:     'Plan rejected for \u201c' + jTitle + '\u201d. Queue a new request to try again.',
      abandoned:         '\u201c' + jTitle + '\u201d was abandoned.',
    };
    return statusText[jStatus] || ('Frank Lloyd: \u201c' + jTitle + '\u201d \u2014 ' + jStatus.replace(/_/g, ' ') + '.');
  }

  // Generic fallback for free-form queries
  return 'For full AI guidance, add an OpenRouter API key. Current state: Trading ' + (tradingOn ? 'ON' : 'OFF') + ', Research ' + (loopOn ? 'ON' : 'OFF') + (reviewNeeded ? ', review pending.' : '.');
}

// ── Peter chat ────────────────────────────────────────────────────────────
let _peterChat = [];  // [{role:'peter'|'operator', text:str, loading?:true}]

function _peterInputGrow(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

function _escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function peterChatRender() {
  const el = document.getElementById('peter-chat-history');
  if (!el) return;
  if (!_peterChat.length) {
    el.innerHTML = '<div class="chat-msg-peter">Ready. Ask me anything about the system.</div>';
    return;
  }
  el.innerHTML = _peterChat.map(m => {
    const base = m.role === 'peter' ? 'chat-msg-peter' : 'chat-msg-operator';
    const extra = m.loading ? ' chat-loading' : '';
    return `<div class="${base}${extra}">${_escHtml(m.text)}</div>`;
  }).join('');
  el.scrollTop = el.scrollHeight;
}

function peterChatAsk(text) {
  const inp = document.getElementById('peter-chat-input');
  if (inp) { inp.value = text; _peterInputGrow(inp); }
  peterChatSend();
}

// ── Peter chat routing ────────────────────────────────────────────────────────
//
// Three routing paths:
//   1. FL build intent  → /frank-lloyd/smart-queue (shape + queue + autorun)
//   2. FL lifecycle NL  → /peter/action (approve/reject/run/draft/promote/discard)
//   3. Info/status      → /peter/chat (LM guidance) or deterministic fallback
//
// Build detection is intentionally broad — if something looks like a directive
// to change/add/fix/clean something, route it to smart-queue.
// Lifecycle detection catches explicit lifecycle verbs without a structured build-id.

function _isFlBuildIntent(msg) {
  const lower = msg.toLowerCase().trim();
  // Skip obvious status questions
  if (/^(what|when|where|why|who|how)\s+(is|are|does|do|can|has|have|did|was)\b/.test(lower)
      && !/frank\s*lloyd/.test(lower)) return false;
  if (/^(is |are |does |do |can |has |have |did |was )/.test(lower)
      && !/frank\s*lloyd/.test(lower)) return false;
  // Frank Lloyd explicitly mentioned with action verb
  if (/frank\s*lloyd/.test(lower) &&
      /\b(build|add|make|create|write|implement|fix|refactor|clean|diagnose|improve|monitor|remove|delete|update|change|rework|rewrite)\b/.test(lower))
    return true;
  // Strong build directive without FL mention
  const buildVerbs = /\b(build|implement|add|create|write|develop)\s+(a|an|the|new)?\s*\w/;
  const fixVerbs   = /\b(fix|refactor|clean up|diagnose|improve|remove|delete|rework|rewrite)\b/;
  const artifacts  = /\b(endpoint|route|module|handler|function|command|feature|service|script|api|panel|widget|tab|view|page|button|form|class|test)\b/;
  if (buildVerbs.test(lower) && artifacts.test(lower)) return true;
  if (fixVerbs.test(lower) && artifacts.test(lower)) return true;
  // "Queue a build" / "have FL build" patterns from commands.py
  if (/\b(have|ask|tell|get)\s+(frank\s*lloyd|fl)\b/.test(lower)) return true;
  return false;
}

function _isFlLifecycleIntent(msg) {
  const lower = msg.toLowerCase();
  // Status query — handled by /peter/chat (LM), not action
  if (/what.*frank\s*lloyd|frank\s*lloyd.*status|how.*frank\s*lloyd/.test(lower)) return false;
  // Lifecycle action verbs
  return /\b(approve|reject|authorize|run that|run the build|go ahead|auto.?run|discard|scrap|draft|generate draft|promote|ship that|apply that)\b/.test(lower);
}
// Note: _isFlLifecycleIntent is kept for reference but no longer used in peterChatSend.
// All non-build input now routes through _peterCommandDispatch (deterministic-first).

async function _peterSmartQueue(msg, inp, btn) {
  _peterChat.push({role: 'peter', text: '\u2026', loading: true});
  peterChatRender();
  try {
    const r = await fetch('/peter/queue-build', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg}),
    });
    const d = await r.json();
    _peterChat = _peterChat.filter(m => !m.loading);
    const text = d.text || (d.ok ? 'Queued.' : (d.needs_clarification ? d.text : 'Could not queue.'));
    _peterChat.push({role: 'peter', text: text});
    // If queued successfully, auto-poll the FL panel
    if (d.ok && d.build_id) {
      setTimeout(tick, 500);
      setTimeout(tick, 2500);
    }
  } catch(e) {
    _peterChat = _peterChat.filter(m => !m.loading);
    _peterChat.push({role: 'peter', text: 'Could not reach the queueing service \u2014 try again.'});
  } finally {
    inp.disabled = false;
    btn.disabled = false;
    btn.textContent = 'SEND';
    peterChatRender();
    inp.focus();
  }
}

async function _peterFlAction(msg, inp, btn) {
  _peterChat.push({role: 'peter', text: '\u2026', loading: true});
  peterChatRender();
  try {
    const r = await fetch('/peter/action', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg}),
    });
    const d = await r.json();
    _peterChat = _peterChat.filter(m => !m.loading);
    _peterChat.push({role: 'peter', text: d.summary || (d.ok ? 'Done.' : 'Action failed.')});
    // Refresh state after lifecycle action
    if (d.ok) setTimeout(async () => { const s = await fetchState(); if (s) applyState(s); }, 600);
  } catch(e) {
    _peterChat = _peterChat.filter(m => !m.loading);
    _peterChat.push({role: 'peter', text: 'Action failed \u2014 try again.'});
  } finally {
    inp.disabled = false;
    btn.disabled = false;
    btn.textContent = 'SEND';
    peterChatRender();
    inp.focus();
  }
}

async function peterChatSend() {
  const inp = document.getElementById('peter-chat-input');
  const btn = document.getElementById('peter-chat-send');
  if (!inp || !btn) return;
  const msg = inp.value.trim();
  if (!msg) return;
  inp.value = '';
  inp.style.height = '';
  inp.disabled = true;
  btn.disabled = true;
  btn.textContent = '\u2026';
  _peterChat.push({role: 'operator', text: msg});

  // Route 1: FL build intent → smart intake via brief_shaper + /peter/queue-build
  if (_isFlBuildIntent(msg)) {
    await _peterSmartQueue(msg, inp, btn);
    return;
  }

  // Route 2: Deterministic Peter command path → /peter/action → parse_command() → router.
  // If parse_command() recognises the input (command_type !== "unknown"), show the response.
  // Unrecognised input falls through to LM chat or the offline deterministic answer.
  await _peterCommandDispatch(msg, inp, btn);
}

// _peterCommandDispatch: deterministic-first Peter command handler.
// Tries /peter/action for ALL non-build inputs. Only falls back to /peter/chat
// when parse_command() returns command_type === "unknown".
async function _peterCommandDispatch(msg, inp, btn) {
  _peterChat.push({role: 'peter', text: '\u2026', loading: true});
  peterChatRender();
  let recognized = false;
  try {
    const r = await fetch('/peter/action', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg}),
    });
    const d = await r.json();
    _peterChat = _peterChat.filter(m => !m.loading);
    if (d.command_type && d.command_type !== 'unknown') {
      recognized = true;
      _peterChat.push({role: 'peter', text: d.summary || (d.ok ? 'Done.' : 'Action failed.')});
      if (d.ok) setTimeout(async () => { const s = await fetchState(); if (s) applyState(s); }, 600);
    }
  } catch (_e) {
    _peterChat = _peterChat.filter(m => !m.loading);
  }

  if (!recognized) {
    // Unknown command — fall through to LM chat or offline deterministic answer
    const lmAvail = _lastState && _lastState.lm_available;
    if (!lmAvail) {
      _peterChat.push({role: 'peter', text: _peterDeterministicAnswer(msg)});
    } else {
      _peterChat.push({role: 'peter', text: '\u2026', loading: true});
      peterChatRender();
      try {
        const cr = await fetch('/peter/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({message: msg}),
        });
        const cd = await cr.json();
        _peterChat = _peterChat.filter(m => !m.loading);
        _peterChat.push({
          role: 'peter',
          text: (cd.ok && cd.text) ? cd.text : _peterDeterministicAnswer(msg),
        });
      } catch (_e2) {
        _peterChat = _peterChat.filter(m => !m.loading);
        _peterChat.push({role: 'peter', text: _peterDeterministicAnswer(msg)});
      }
    }
  }

  inp.disabled = false;
  btn.disabled = false;
  btn.textContent = 'SEND';
  peterChatRender();
  inp.focus();
}

// ── Belfort inline review card ────────────────────────────────────────────
async function loadBelfortReviewCard() {
  let item = null;
  for (const status of ['pending', 'held']) {
    try {
      const r = await fetch('/supervisor/queue?status=' + status);
      if (!r.ok) continue;
      const items = await r.json();
      if (Array.isArray(items) && items.length > 0) { item = items[0]; break; }
    } catch(e) { /* continue */ }
  }
  const card      = document.getElementById('belfort-review-card');
  const labelEl   = document.getElementById('review-card-label');
  const titleEl   = document.getElementById('review-title');
  const summaryEl = document.getElementById('review-summary');
  const metricEl  = document.getElementById('review-metric');
  if (!card || !titleEl) return;
  if (!item) { card.style.display = 'none'; return; }
  card.style.display = '';
  if (labelEl) labelEl.textContent = '\u26a1 READY FOR REVIEW';
  titleEl.textContent   = item.title || item.experiment_id || item.id || 'Unnamed experiment';
  summaryEl.textContent = (item.summary || item.description || '').slice(0, 100);
  const m = item.metric_delta != null
    ? 'Sharpe \u0394 ' + (item.metric_delta >= 0 ? '+' : '') + item.metric_delta.toFixed(3)
    : item.score != null ? 'Score: ' + item.score.toFixed(3)
    : item.tier  ? 'Tier: ' + item.tier
    : '';
  metricEl.textContent = m;
  card._reviewItemId = item.id || item.experiment_id;
  const approveBtn = document.getElementById('review-approve-btn');
  const rejectBtn  = document.getElementById('review-reject-btn');
  if (approveBtn) approveBtn.disabled = false;
  if (rejectBtn)  rejectBtn.disabled  = false;
}

async function belfortReviewAction(action) {
  const card = document.getElementById('belfort-review-card');
  if (!card) return;
  const itemId = card._reviewItemId;
  if (!itemId) return;
  const approveBtn = document.getElementById('review-approve-btn');
  const rejectBtn  = document.getElementById('review-reject-btn');
  const labelEl    = document.getElementById('review-card-label');
  if (approveBtn) approveBtn.disabled = true;
  if (rejectBtn)  rejectBtn.disabled  = true;
  if (labelEl) labelEl.textContent = action === 'approve' ? '\u23f3 Approving\u2026' : '\u23f3 Rejecting\u2026';
  try {
    const r = await fetch('/supervisor/queue/' + encodeURIComponent(itemId) + '/' + action, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    if (labelEl) labelEl.textContent = action === 'approve' ? '\u2713 Approved' : '\u2713 Rejected';
    setTimeout(async () => {
      card.style.display = 'none';
      const s = await fetchState();
      if (s) applyState(s);
    }, 700);
  } catch(e) {
    if (labelEl) labelEl.textContent = '\u26a1 REVIEW \u2014 Error: ' + e.message.slice(0, 35);
    if (approveBtn) approveBtn.disabled = false;
    if (rejectBtn)  rejectBtn.disabled  = false;
  }
}

// ── Belfort readiness scorecard ──────────────────────────────────────────
async function loadBelfortReadiness() {
  const now = Date.now();
  if (now - _belfortReadinessLastLoad < 55000) return;
  _belfortReadinessLastLoad = now;
  const section = document.getElementById('belfort-readiness-section');
  if (!section) return;
  section.style.display = '';

  const badgeEl      = document.getElementById('readiness-badge');
  const countEl      = document.getElementById('readiness-gates-count');
  const stratEl      = document.getElementById('readiness-strategy');
  const regimeEl     = document.getElementById('readiness-regime');
  const gatesEl      = document.getElementById('readiness-gates');
  const researchEl   = document.getElementById('readiness-research-trigger');
  const blockersEl   = document.getElementById('readiness-blockers');
  const comparisonEl = document.getElementById('readiness-comparison');
  const summaryEl    = document.getElementById('readiness-summary');

  if (badgeEl)      { badgeEl.className = 'dp-badge idle'; badgeEl.textContent = 'Loading\u2026'; }
  if (gatesEl)      gatesEl.innerHTML    = '';
  if (regimeEl)     regimeEl.innerHTML   = '';
  if (researchEl)   { researchEl.innerHTML = ''; researchEl.style.display = 'none'; }
  if (blockersEl)   { blockersEl.innerHTML = ''; blockersEl.style.display = 'none'; }
  if (comparisonEl) { comparisonEl.innerHTML = ''; comparisonEl.style.display = 'none'; }
  if (summaryEl)    summaryEl.textContent = '';

  try {
    const r = await fetch('/belfort/readiness', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    _lastReadiness = d;

    const clsMap = {
      not_started:        'idle',
      awaiting_reset:     'warning',
      evaluation:         'active',
      monitoring:         'review',
      pre_live_candidate: 'ok',
    };
    const badgeCls = clsMap[d.level] || 'idle';
    if (badgeEl) {
      badgeEl.className  = 'dp-badge ' + badgeCls;
      badgeEl.textContent = d.level_label || (d.level || '?').toUpperCase().replace(/_/g, ' ');
    }
    if (countEl) countEl.textContent = (d.gates_passed || 0) + '/' + (d.gates_total || 0) + ' gates passed';
    if (stratEl) stratEl.textContent = d.strategy_description || '';

    // Regime context label
    if (regimeEl && d.regime_context) {
      const rc  = d.regime_context;
      const fitCls = {'good': 'regime-good', 'ok': 'regime-ok', 'poor': 'regime-poor'}[rc.strategy_fit] || 'regime-unknown';
      const erPart  = (rc.efficiency_ratio != null) ? ` ER\u00a0${rc.efficiency_ratio.toFixed(2)}` : '';
      const volPart = rc.vol_note ? ` \u00b7 ${rc.vol_note}` : '';
      regimeEl.innerHTML = `Market: <span class="${fitCls}">${_escHtml(rc.label)}${erPart}${volPart}</span>`;
    }

    if (gatesEl && Array.isArray(d.gates)) {
      gatesEl.innerHTML = d.gates.map(g =>
        `<div class="rgate${g.pass ? '' : ' fail'}" title="${_escHtml(g.note || '')}">${_escHtml(g.label)}</div>`
      ).join('');
    }

    // Research trigger warning
    if (researchEl && d.research_triggers && d.research_triggers.triggered) {
      const rt = d.research_triggers;
      researchEl.innerHTML = `<b>Research signal (${rt.count}):</b> ${_escHtml(rt.recommendation)}`;
      researchEl.style.display = '';
    }

    // Blockers — top failing gates in plain English
    if (blockersEl && Array.isArray(d.blockers) && d.blockers.length > 0) {
      blockersEl.innerHTML = '<b>To advance:</b> ' + d.blockers.map(b => _escHtml(b)).join(' &bull; ');
      blockersEl.style.display = '';
    }

    // Baseline comparison — prev session vs current (with verdict badge)
    if (comparisonEl && d.baseline_comparison && d.baseline_comparison.available) {
      const bc = d.baseline_comparison;
      const verdictBadge = bc.verdict === 'improving' ? ' \u25b2' : bc.verdict === 'declining' ? ' \u25bc' : '';
      comparisonEl.innerHTML = `<b>vs prev session${verdictBadge}:</b> ` + _escHtml(bc.summary);
      comparisonEl.style.display = '';
    }

    // Prefer mentor_summary (more structured) for the summary display
    if (summaryEl) summaryEl.textContent = d.mentor_summary || d.summary || '';

    // Re-render stats grid now that win_rate is available
    if (_lastState && _lastState.belfort) {
      updateBelfortStats(_lastState.belfort, _lastState.supervisor || {});
    }

  } catch(e) {
    if (badgeEl)   { badgeEl.className = 'dp-badge idle'; badgeEl.textContent = '?'; }
    if (summaryEl) summaryEl.textContent = 'Could not load readiness data.';
  }
}

// ── Belfort learning pulse ────────────────────────────────────────────────
async function loadBelfortLearning() {
  const now = Date.now();
  if (now - _belfortLearningLastLoad < 55000) return;
  _belfortLearningLastLoad = now;
  const section   = document.getElementById('belfort-learning-section');
  if (!section) return;

  const verdictEl   = document.getElementById('learning-verdict-row');
  const hurtingEl   = document.getElementById('learning-hurting');
  const helpingEl   = document.getElementById('learning-helping');
  const recEl       = document.getElementById('learning-recommendation');
  const histEl      = document.getElementById('learning-history');
  const goalEl      = document.getElementById('learning-research-goal');
  const researchBtn = document.getElementById('learning-research-btn');

  try {
    const r = await fetch('/belfort/learning', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    _lastLearning = d;
    section.style.display = '';

    // Verdict badge + note
    const vMap = {
      continue: ['verdict-continue', 'CONTINUE'],
      monitor:  ['verdict-monitor',  'MONITOR'],
      tune:     ['verdict-tune',     'TUNE'],
      research: ['verdict-research', 'RESEARCH NEEDED'],
    };
    const [vCls, vLabel] = vMap[d.verdict] || ['verdict-monitor', (d.verdict || '?').toUpperCase()];
    if (verdictEl) {
      verdictEl.innerHTML = (
        `<span class="verdict-badge ${vCls}">${vLabel}</span>` +
        `<span style="font-size:8px;color:#455a64;letter-spacing:0.3px">${_escHtml(d.verdict_note || '')}</span>`
      );
    }

    // Top hurting item (▼ red)
    const topHurt = Array.isArray(d.hurting) && d.hurting.length ? d.hurting[0] : null;
    if (hurtingEl) {
      hurtingEl.textContent   = topHurt ? '\u25bc\u00a0' + topHurt : '';
      hurtingEl.style.display = topHurt ? '' : 'none';
    }

    // Top helping item (▲ green)
    const topHelp = Array.isArray(d.helping) && d.helping.length ? d.helping[0] : null;
    if (helpingEl) {
      helpingEl.textContent   = topHelp ? '\u25b2\u00a0' + topHelp : '';
      helpingEl.style.display = topHelp ? '' : 'none';
    }

    // Recommendation text (from research triggers if available, else verdict note)
    const recText = (d.research_triggers && d.research_triggers.recommendation)
                    || d.verdict_note || '';
    if (recEl) recEl.textContent = recText;

    // Historical context (pattern memory across sessions)
    if (histEl) {
      const hc = d.historical_context;
      if (hc && hc.entry_count > 0 && hc.summary) {
        histEl.innerHTML = '<b>History:</b> ' + _escHtml(hc.summary);
        histEl.style.display = '';
      } else {
        histEl.innerHTML = '';
        histEl.style.display = 'none';
      }
    }

    // Trigger-derived research goal
    if (goalEl) {
      if (d.research_goal && d.verdict === 'research') {
        goalEl.textContent   = '\u25b6 Goal: ' + d.research_goal;
        goalEl.style.display = '';
      } else {
        goalEl.textContent   = '';
        goalEl.style.display = 'none';
      }
    }

    // Research button: only visible when research is recommended AND loop is off
    const loopOn = (_lastState && _lastState.supervisor && _lastState.supervisor.enabled) || false;
    if (researchBtn) {
      researchBtn.style.display = (d.verdict === 'research' && !loopOn) ? '' : 'none';
    }

  } catch(e) {
    section.style.display = 'none';
  }
}

// ── Belfort diagnostics ───────────────────────────────────────────────────
async function loadBelfortDiagnostics() {
  const now = Date.now();
  if (now - _belfortDiagnosticsLastLoad < 30000) return;
  _belfortDiagnosticsLastLoad = now;
  const section = document.getElementById('belfort-diagnostics-section');
  if (!section) return;
  section.style.display = '';

  try {
    const r = await fetch('/belfort/diagnostics', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();

    // ── Strategy drift ────────────────────────────────────────────────────
    const stratEl = document.getElementById('diag-strategy');
    if (stratEl) {
      const dr = d.strategy_drift || {};
      const driftBadge = dr.drifted
        ? `<span class="diag-warn">CHANGED (${dr.changed_params.length} param${dr.changed_params.length !== 1 ? 's' : ''})</span>`
        : `<span class="diag-ok">Unchanged</span>`;
      const resetDate = dr.reset_at ? dr.reset_at.slice(0, 10) : '\u2014';
      const promoPart = dr.promotion_param
        ? `<span class="diag-muted"> · adopted ${_escHtml(dr.promotion_param.replace('promotion:', '').slice(0, 36))}</span>`
        : '';
      let html = (
        `<div class="diag-row"><span class="diag-label">STRATEGY</span>${driftBadge}</div>` +
        `<div class="diag-muted">${_escHtml((dr.current_label || '\u2014').slice(0, 80))}</div>` +
        `<div class="diag-muted">Reset: ${resetDate}${promoPart}</div>`
      );
      if (dr.changed_params && dr.changed_params.length > 0) {
        html += `<div class="diag-warn-text">${dr.changed_params.map(p => _escHtml(p)).join(' \u00b7 ')}</div>`;
      }
      stratEl.innerHTML = html;
    }

    // ── Session P&L path ──────────────────────────────────────────────────
    const pnlEl = document.getElementById('diag-pnl');
    if (pnlEl) {
      const s = d.session_pnl || {};
      const pnl    = s.realized_pnl || 0;
      const pnlCls = pnl > 0.005 ? 'diag-ok' : pnl < -0.005 ? 'diag-warn' : 'diag-muted';
      const pnlStr = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
      const wr     = s.win_rate != null ? Math.round(s.win_rate * 100) + '%' : '\u2014';
      const exp    = s.expectancy    != null ? (s.expectancy    >= 0 ? '+' : '') + s.expectancy.toFixed(2)    : '\u2014';
      const rExp   = s.recent_expectancy != null ? (s.recent_expectancy >= 0 ? '+' : '') + s.recent_expectancy.toFixed(2) : '\u2014';
      const awStr  = s.avg_win  != null ? '+$' + s.avg_win.toFixed(2)          : '\u2014';
      const alStr  = s.avg_loss != null ? '$'  + Math.abs(s.avg_loss).toFixed(2) : '\u2014';
      const ddStr  = s.drawdown_from_peak != null && s.drawdown_from_peak < -0.01
        ? `\u00a0\u25bc\u00a0$${Math.abs(s.drawdown_from_peak).toFixed(2)} from peak` : '';

      pnlEl.innerHTML = (
        `<div class="diag-row"><span class="diag-label">P&amp;L PATH</span><span class="${pnlCls}">${pnlStr}</span></div>` +
        `<div class="diag-muted">${s.total_closed || 0}\u00a0closed\u00b7 ${wr}\u00a0WR\u00b7 expect\u00a0${exp}/tr\u00b7 recent\u00a0${rExp}/tr${ddStr}</div>` +
        `<div class="diag-muted">avg win\u00a0${awStr}\u00b7 avg loss\u00a0${alStr}</div>`
      );
    }

    // ── Trigger detail ────────────────────────────────────────────────────
    const trigEl = document.getElementById('diag-triggers');
    if (trigEl) {
      const t        = d.trigger_detail || {};
      const hard     = t.active_triggers     || [];
      const soft     = t.soft_reasons        || [];
      const gaps     = t.hard_threshold_gaps || [];
      const qStatus  = t.queue_status        || 'unknown';
      const pressure = t.pressure            || 'none';
      const bridge   = t.research_bridge;
      const qCls     = qStatus !== 'empty' && qStatus !== 'unavailable' ? 'diag-ok' : 'diag-muted';

      const pressureCls   = pressure === 'hard' ? 'diag-warn' : pressure === 'soft' ? 'diag-soft' : 'diag-ok';
      const pressureLabel = pressure.toUpperCase();

      let html = `<div class="diag-row"><span class="diag-label">PRESSURE</span><span class="${pressureCls}">${pressureLabel}</span></div>`;

      if (hard.length > 0) {
        html += `<div class="diag-warn-text" style="margin-bottom:1px">Hard signals:</div>`;
        hard.forEach(r => { html += `<div class="diag-warn-text">\u25b2\u00a0${_escHtml(r)}</div>`; });
      }
      if (soft.length > 0) {
        html += `<div class="diag-soft-text" style="margin-top:2px;margin-bottom:1px">Soft signals:</div>`;
        soft.forEach(r => { html += `<div class="diag-soft-text">\u00b7\u00a0${_escHtml(r)}</div>`; });
      }
      if (hard.length === 0 && soft.length === 0) {
        html += `<div class="diag-muted">${_escHtml(t.recommendation || 'No issues detected')}</div>`;
      }

      if (bridge) {
        html += `<div class="diag-bridge">\u25b6\u00a0${_escHtml(bridge)}</div>`;
      }

      if (gaps.length > 0) {
        html += `<details><summary class="diag-detail-toggle">Hard threshold gaps \u25b8</summary>` +
          gaps.map(n => `<div class="diag-muted">\u00b7\u00a0${_escHtml(n)}</div>`).join('') +
          `</details>`;
      }

      html += `<div class="diag-muted" style="margin-top:3px">Queue:\u00a0<span class="${qCls}">${_escHtml(qStatus)}</span></div>`;
      trigEl.innerHTML = html;
    }

  } catch(e) {
    const section = document.getElementById('belfort-diagnostics-section');
    if (section) section.style.display = 'none';
  }
}

// ── Begin Research with trigger-derived goal ──────────────────────────────
async function belfortResearchWithGoal() {
  const btn  = document.getElementById('learning-research-btn');
  const goal = _lastLearning && _lastLearning.research_goal;
  if (btn) { btn.disabled = true; btn.textContent = 'Starting\u2026'; }
  try {
    const body = goal ? JSON.stringify({goal}) : '{}';
    const r    = await fetch('/supervisor/enable', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body,
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    if (btn) btn.textContent = '\u2713';
    setTimeout(async () => {
      if (btn) btn.disabled = false;
      const s = await fetchState();
      if (s) applyState(s);
    }, 600);
  } catch(e) {
    console.error('belfortResearchWithGoal error:', e.message);
    if (btn) { btn.disabled = false; btn.textContent = '\u25b6 Begin Research'; }
  }
}

// ── Belfort stats + controls ──────────────────────────────────────────────
function updateBelfortStats(belfort, supervisor) {
  const cash      = belfort.cash          != null ? belfort.cash          : 100000;
  const rpnl      = belfort.realized_pnl  != null ? belfort.realized_pnl  : 0;
  const upnl      = belfort.unrealized_pnl != null ? belfort.unrealized_pnl : 0;
  const trades    = belfort.trade_count   != null ? belfort.trade_count   : 0;
  const tradingOn = belfort.trading_active || false;
  const loopOn    = (supervisor || {}).enabled || false;

  const statsEl = document.getElementById('belfort-stats');
  if (statsEl) {
    const pnl     = rpnl + upnl;
    const cashFmt = '$' + (cash >= 1000 ? (cash/1000).toFixed(1) + 'k' : cash.toFixed(0));
    const pnlAbs  = Math.abs(pnl);
    const pnlFmt  = (pnl >= 0 ? '+$' : '-$') + (pnlAbs >= 1000 ? (pnlAbs/1000).toFixed(2) + 'k' : pnlAbs.toFixed(2));
    const pnlCls  = pnl > 0.005 ? 'pos' : pnl < -0.005 ? 'neg' : '';
    // Win rate from last loaded readiness data (null until readiness loads)
    const wr      = _lastReadiness && _lastReadiness.win_rate != null ? _lastReadiness.win_rate : null;
    const wrFmt   = wr != null ? Math.round(wr * 100) + '%' : '\u2014';
    const wrCls   = wr != null && wr >= 0.5 ? 'pos' : wr != null && wr < 0.4 ? 'neg' : '';
    statsEl.innerHTML =
      '<div class="bstat"><div class="bstat-label">CASH</div><div class="bstat-value">' + cashFmt + '</div></div>' +
      '<div class="bstat"><div class="bstat-label">P&amp;L</div><div class="bstat-value ' + pnlCls + '">' + pnlFmt + '</div></div>' +
      '<div class="bstat"><div class="bstat-label">TRADES</div><div class="bstat-value">' + trades + '</div></div>' +
      '<div class="bstat"><div class="bstat-label">WIN\u00a0%</div><div class="bstat-value ' + wrCls + '">' + wrFmt + '</div></div>';
  }
  const pillsEl = document.getElementById('belfort-pills');
  if (pillsEl) {
    pillsEl.innerHTML =
      '<div class="bpill ' + (tradingOn ? 'bpill-active' : '') + '">TRADING\u00a0' + (tradingOn ? 'ON' : 'OFF') + '</div>' +
      '<div class="bpill ' + (loopOn ? 'bpill-active' : '') + '">RESEARCH\u00a0' + (loopOn ? 'ON' : 'OFF') + '</div>';
  }

  // Mode / readiness / freshness — always shown as separate labeled fields
  const mrEl = document.getElementById('belfort-mode-readiness');
  if (mrEl) {
    const mode        = (belfort.belfort_mode      || 'observation').toUpperCase();
    const readiness   = (belfort.belfort_readiness || 'NOT_READY');
    const freshness   = (belfort.belfort_freshness || 'no_data');
    const freshLabel  = (belfort.belfort_freshness_label || '\u2014');
    const freshCls    = freshness === 'fresh'     ? 'bmr-ok'
                      : freshness === 'stale'     ? 'bmr-stale'
                      : freshness === 'very_stale'? 'bmr-bad'
                      :                             'bmr-stale';
    const rdyCls      = readiness === 'NOT_READY'   ? 'bmr-bad'
                      : readiness === 'LIVE_ELIGIBLE'? 'bmr-ok'
                      :                               '';
    mrEl.innerHTML =
      '<div class="bmr-cell"><div class="bmr-label">MODE</div><div class="bmr-value">' + _escHtml(mode) + '</div></div>' +
      '<div class="bmr-cell"><div class="bmr-label">READINESS</div><div class="bmr-value ' + rdyCls + '">' + _escHtml(readiness.replace(/_/g, '\u00a0')) + '</div></div>' +
      '<div class="bmr-cell" style="flex:2"><div class="bmr-label">DATA\u00a0FRESHNESS</div><div class="bmr-value ' + freshCls + '">' + _escHtml(freshLabel) + '</div></div>';
  }

  // Signal evaluation row — shadow/paper only
  const sigEl = document.getElementById('belfort-signal-row');
  if (sigEl) {
    const sig  = belfort.belfort_latest_signal;
    const mode = (belfort.belfort_mode || 'observation');
    if (sig && (mode === 'shadow' || mode === 'paper')) {
      const action    = (sig.signal_action || 'hold').toUpperCase();
      const symbol    = _escHtml(sig.symbol || '?');
      const rationale = _escHtml((sig.signal_rationale || '').substring(0, 80));
      const riskOk    = sig.risk_can_proceed !== false;
      const riskLbl   = riskOk ? 'allowed' : _escHtml(('blocked: ' + (sig.risk_block_reason || '')).substring(0, 60));
      const actionCls = action === 'BUY' ? 'bsig-action-buy' : action === 'SELL' ? 'bsig-action-sell' : 'bsig-action-hold';
      const riskCls   = riskOk ? 'bsig-risk-allowed' : 'bsig-risk-blocked';
      sigEl.style.display = '';
      sigEl.innerHTML =
        '<div class="bsig-label">LATEST\u00a0SIGNAL\u00a0(\u2014\u00a0NO\u00a0ORDER\u00a0PLACED)</div>' +
        '<span class="' + actionCls + '">' + action + '\u00a0' + symbol + '</span>' +
        '\u00a0\u2014\u00a0' + rationale +
        '\u00a0[\u00a0risk:\u00a0<span class="' + riskCls + '">' + riskLbl + '</span>\u00a0]';
    } else {
      sigEl.style.display = 'none';
    }
  }

  // Paper execution row — paper mode only, clearly labeled as paper
  const pexEl = document.getElementById('belfort-paper-exec-row');
  if (pexEl) {
    const pex  = belfort.belfort_latest_paper_exec;
    const mode = (belfort.belfort_mode || 'observation');
    if (pex && mode === 'paper') {
      const status  = pex.execution_status || '';
      const summary = _escHtml((pex.exec_summary || '').substring(0, 120));
      let cls = 'bpex-gated', label = 'PAPER\u00a0ORDER\u00a0(\u2014\u00a0NO\u00a0REAL\u00a0MONEY)';
      if (status === 'submitted') {
        cls = 'bpex-submitted';
        label = 'PAPER\u00a0ORDER\u00a0SUBMITTED\u00a0(\u2014\u00a0NO\u00a0REAL\u00a0MONEY)';
      } else if (status === 'broker_error' || status === 'error') {
        cls = 'bpex-error';
        label = 'PAPER\u00a0ORDER\u00a0FAILED';
      }
      pexEl.style.display = '';
      pexEl.innerHTML =
        '<div class="bpex-label">' + label + '</div>' +
        '<span class="' + cls + '">' + summary + '</span>';
    } else {
      pexEl.style.display = 'none';
    }
  }

  // Update toggle button labels based on current state
  const tradBtn = document.getElementById('btn-trading-toggle');
  if (tradBtn && !tradBtn.disabled) {
    tradBtn.textContent = tradingOn ? '\u25a0 Stop Trading' : '\u25b6 Start Trading';
    tradBtn.className   = 'bctrl-btn ' + (tradingOn ? 'bctrl-on bctrl-stop' : 'bctrl-start');
  }
  const loopBtn = document.getElementById('btn-loop-toggle');
  if (loopBtn && !loopBtn.disabled) {
    loopBtn.textContent = loopOn ? '\u25a0 Stop Research' : '\u25b6 Begin Research';
    loopBtn.className   = 'bctrl-btn ' + (loopOn ? 'bctrl-on bctrl-stop' : 'bctrl-start');
  }
}

const _BELFORT_ENDPOINTS = {
  trading_start: '/monitor/trading/start',
  trading_stop:  '/monitor/trading/stop',
  loop_enable:   '/supervisor/enable',
  loop_disable:  '/supervisor/disable',
};
const _BELFORT_BTN_IDS = {
  trading_start: 'btn-trading-start',
  trading_stop:  'btn-trading-stop',
  loop_enable:   'btn-loop-enable',
  loop_disable:  'btn-loop-disable',
};
const _BELFORT_TOGGLE_VERBS = {
  trading_start: 'Starting\u2026',
  trading_stop:  'Stopping\u2026',
  loop_enable:   'Enabling\u2026',
  loop_disable:  'Disabling\u2026',
};

async function belfortToggle(what) {
  let action, btnId;
  if (what === 'trading') {
    const on = _lastState && _lastState.belfort && _lastState.belfort.trading_active;
    action = on ? 'trading_stop' : 'trading_start';
    btnId  = 'btn-trading-toggle';
  } else if (what === 'loop') {
    const on = _lastState && _lastState.supervisor && _lastState.supervisor.enabled;
    action = on ? 'loop_disable' : 'loop_enable';
    btnId  = 'btn-loop-toggle';
  }
  if (!action) return;
  const url = _BELFORT_ENDPOINTS[action];
  if (!url) return;
  const btn = btnId ? document.getElementById(btnId) : null;
  if (btn && btn.disabled) return;
  if (btn) { btn.disabled = true; btn.textContent = _BELFORT_TOGGLE_VERBS[action] || '\u2026'; }
  try {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    if (btn) btn.textContent = '\u2713';
    setTimeout(async () => {
      if (btn) btn.disabled = false;
      const s = await fetchState();
      if (s) applyState(s);  // updateBelfortStats will set correct label after this
    }, 600);
  } catch(e) {
    console.error('belfortToggle error:', what, e.message);
    if (btn) { btn.disabled = false; btn.textContent = what === 'trading' ? '\u25b6 Start Trading' : '\u25b6 Begin Research'; }
  }
}

async function belfortControl(action) {
  const url = _BELFORT_ENDPOINTS[action];
  if (!url) return;
  const btnId = _BELFORT_BTN_IDS[action];
  const btn   = btnId ? document.getElementById(btnId) : null;
  if (btn && btn.disabled) return;
  const origText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '\u2026'; }
  try {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    setTimeout(async () => {
      const s = await fetchState();
      if (s) applyState(s);
    }, 600);
  } catch(e) {
    console.error('belfortControl error:', action, e.message);
  } finally {
    setTimeout(() => {
      if (btn) { btn.disabled = false; btn.textContent = origText; }
    }, 1200);
  }
}

function belfortResetInit() {
  const confirm = document.getElementById('belfort-reset-confirm');
  const initBtn = document.getElementById('btn-reset-init');
  if (confirm) confirm.style.display = 'flex';
  if (initBtn) initBtn.style.display = 'none';
}

function belfortResetCancel() {
  const confirm = document.getElementById('belfort-reset-confirm');
  const initBtn = document.getElementById('btn-reset-init');
  if (confirm) confirm.style.display = 'none';
  if (initBtn) initBtn.style.display = 'block';
  const ri = document.getElementById('belfort-reset-reason');
  if (ri) ri.value = '';
}

async function belfortResetExecute() {
  const ri = document.getElementById('belfort-reset-reason');
  const reason = ri ? ri.value.trim() : '';
  const btns = document.querySelectorAll('#belfort-reset-confirm .reset-btn');
  btns.forEach(b => { b.disabled = true; });
  try {
    const r = await fetch('/monitor/trading/reset', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({reason: reason || 'Operator reset from neighborhood'}),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    belfortResetCancel();
    const statsEl = document.getElementById('belfort-stats');
    if (statsEl) statsEl.innerHTML = '<div style="color:#00e676;font-size:9px;letter-spacing:1px;padding:4px 0">\u2713 Reset to $100k baseline</div>';
    setTimeout(async () => {
      const s = await fetchState();
      if (s) applyState(s);
    }, 400);
  } catch(e) {
    btns.forEach(b => { b.disabled = false; });
    const statsEl = document.getElementById('belfort-stats');
    if (statsEl) statsEl.innerHTML = '<div style="color:#ef5350;font-size:9px;letter-spacing:1px;padding:4px 0">Error: ' + _escHtml(e.message) + '</div>';
  }
}

// ── Frank Lloyd builder workspace ─────────────────────────────────────────────

function _flVisiblePhase(status) {
  // User-facing phase labels — abstract over internal state machine names
  const m = {
    pending_spec:      {label: 'PLANNING',      cls: 'building'},
    pending_review:    {label: 'PLAN REVIEW',   cls: 'review'},
    spec_approved:     {label: 'BUILDING',      cls: 'building'},
    stage2_authorized: {label: 'BUILDING',      cls: 'building'},
    draft_generating:  {label: 'BUILDING',      cls: 'building'},
    draft_generated:   {label: 'READY TO APPLY', cls: 'ready'},
    draft_blocked:     {label: 'BLOCKED',       cls: 'blocked'},
    draft_promoted:    {label: 'COMPLETE',      cls: 'applied'},
    spec_rejected:     {label: 'REJECTED',      cls: 'blocked'},
    abandoned:         {label: 'ABANDONED',     cls: 'blocked'},
  };
  return m[status] || {label: 'BUILDING', cls: 'building'};
}

function _flStatusHasReview(status) {
  return ['pending_review', 'spec_approved', 'stage2_authorized',
          'draft_generating', 'draft_generated', 'draft_blocked'].includes(status);
}

function _flRenderStream(job) {
  const el = document.getElementById('fl-stream-entries');
  if (!el) return;

  const iconColors = {
    'se-ok':     '#455a64',
    'se-done':   '#66bb6a',
    'se-review': '#ffd600',
    'se-active': '#5c6bc0',
    'se-blocked':'#ef5350',
  };

  // ── Real event stream from backend ──────────────────────────────────────────
  // job.events is populated by frank_lloyd/job.py with actual build log events.
  if (job.events && job.events.length) {
    const iconFor = cls =>
      cls === 'ok'      ? '\u2713'  // ✓
    : cls === 'done'    ? '\u2713'
    : cls === 'review'  ? '\u25cf'  // ●
    : cls === 'active'  ? '\u25cc'  // ◌ (spinning-ish)
    : cls === 'blocked' ? '\u2717'  // ✗
    : '\u203a';

    // Show last 6 events, oldest first (slice from end)
    const shown = job.events.length > 6 ? job.events.slice(-6) : job.events;
    el.innerHTML = shown.map(e => {
      const cls    = 'se-' + (e.cls || 'ok');
      const icon   = iconFor(e.cls || 'ok');
      const color  = iconColors[cls] || '#37474f';
      const detail = e.detail ? '<span class="fl-se-detail">\u00a0\u00b7\u00a0' + _escHtml(e.detail) + '</span>' : '';
      const ts     = e.ts_short ? '<span class="fl-se-detail" style="margin-left:auto;opacity:0.5">' + _escHtml(e.ts_short) + '</span>' : '';
      return '<div class="fl-stream-entry">' +
        '<span class="fl-se-icon" style="color:' + color + '">' + icon + '</span>' +
        '<span class="fl-se-text ' + cls + '">' + _escHtml(e.label) + '</span>' +
        detail + ts +
        '</div>';
    }).join('');
    return;
  }

  // ── Fallback: synthesize from status only (no real events available) ────────
  const s       = job.status;
  const entries = [];
  const order   = ['pending_spec','pending_review','spec_approved',
    'stage2_authorized','draft_generating','draft_generated','draft_blocked','draft_promoted'];
  const idx     = order.indexOf(s);

  entries.push({text: 'Build request queued', cls: 'se-ok', icon: '\u2713', detail: job.build_id});

  if (s === 'pending_spec') {
    entries.push({text: 'Generating plan\u2026', cls: 'se-active', icon: '\u25cc'});
  } else if (idx >= order.indexOf('pending_review')) {
    entries.push({text: s === 'pending_review' ? 'Plan ready \u2014 review needed' : 'Plan generated', cls: s === 'pending_review' ? 'se-review' : 'se-ok', icon: s === 'pending_review' ? '\u25cf' : '\u2713'});
  }
  if (idx >= order.indexOf('spec_approved') && s !== 'pending_review') {
    entries.push({text: s === 'spec_approved' ? 'Plan approved \u2014 authorize to start' : 'Plan approved', cls: s === 'spec_approved' ? 'se-active' : 'se-ok', icon: '\u2713'});
  }
  if (idx >= order.indexOf('stage2_authorized') && !['pending_review','spec_approved'].includes(s)) {
    entries.push({text: s === 'stage2_authorized' ? 'Authorized \u2014 ready to generate code' : 'Authorized', cls: s === 'stage2_authorized' ? 'se-active' : 'se-ok', icon: '\u2713'});
  }
  if (idx >= order.indexOf('draft_generating') && !['pending_review','spec_approved','stage2_authorized'].includes(s)) {
    const dText = s === 'draft_generating' ? 'Generating code\u2026' : s === 'draft_generated' ? 'Draft ready for review' : s === 'draft_blocked' ? 'Draft blocked' : 'Draft generated';
    const dCls  = s === 'draft_generating' ? 'se-active' : s === 'draft_generated' ? 'se-review' : s === 'draft_blocked' ? 'se-blocked' : 'se-ok';
    entries.push({text: dText, cls: dCls, icon: s === 'draft_blocked' ? '\u2717' : s === 'draft_generated' ? '\u25cf' : s === 'draft_generating' ? '\u25cc' : '\u2713'});
  }
  if (s === 'draft_promoted') {
    entries.push({text: 'Applied to repository', cls: 'se-done', icon: '\u2713'});
  }

  el.innerHTML = entries.map(e =>
    '<div class="fl-stream-entry">' +
    '<span class="fl-se-icon" style="color:' + (iconColors[e.cls] || '#37474f') + '">' + e.icon + '</span>' +
    '<span class="fl-se-text ' + e.cls + '">' + _escHtml(e.text) + '</span>' +
    (e.detail ? '<span class="fl-se-detail">\u00a0' + _escHtml(e.detail) + '</span>' : '') +
    '</div>'
  ).join('');
}

function _flRenderWorkspace(job) {
  const ws = document.getElementById('fl-job-workspace');
  if (!job) {
    if (ws) ws.style.display = 'none';
    _flActionBuildId = null;
    return;
  }
  if (ws) ws.style.display = '';

  // Track when build_id or status changes so we can reset apply summary / forms
  const prevBuildId = _flActionBuildId;
  const prevStatus  = _flLastStatus;
  _flActionBuildId  = job.build_id;
  _flLastStatus     = job.status;

  if (prevBuildId && prevBuildId !== job.build_id) {
    // Switching to a different build — hide stale apply summary / forms
    _flHideForms();
    const fb = document.getElementById('fl-action-feedback');
    if (fb) fb.style.display = 'none';
    _flReviewVisible = false;
  }

  // Auto-open plan review when entering pending_review for the first time
  if (job.status === 'pending_review' && prevStatus !== 'pending_review') {
    _flReviewVisible = true;
  }

  // Title + phase chip
  const titleEl = document.getElementById('fl-job-title');
  if (titleEl) titleEl.textContent = job.title || job.build_id;

  const chipEl = document.getElementById('fl-phase-chip');
  if (chipEl) {
    const ph = _flVisiblePhase(job.status);
    chipEl.textContent = ph.label;
    chipEl.className = 'fl-phase-chip fl-phase-' + ph.cls;
  }

  // Meta line: build_id · mode · build_type · risk · [provenance chip]
  const metaEl = document.getElementById('fl-job-meta');
  if (metaEl) {
    const parts = [job.build_id];
    if (job.mode && job.mode !== 'build') {
      parts.push(job.mode);          // show non-default mode (refactor/diagnose/etc.)
    }
    if (job.build_type && job.build_type !== 'unknown') {
      parts.push(job.build_type.replace(/_/g, ' '));
    }
    if (job.risk_level && job.risk_level !== 'unknown') {
      parts.push(job.risk_level + ' risk');
    }
    const _src = job.source || '';
    const _srcLabel = _src === 'peter_chat'              ? 'via Peter chat'
                    : _src === 'peter_chat_smart'         ? 'auto via Peter chat'
                    : _src.startsWith('smart_queue_')     ? 'auto-queued'
                    : _src === 'neighborhood_ui'          ? 'via Abode UI'
                    : _src === 'operator'                 ? 'by operator'
                    : null;
    const _metaBase = _escHtml(parts.join(' \u00b7 '));
    if (_srcLabel) {
      metaEl.innerHTML = _metaBase + ' <span class="fl-source-chip">' + _escHtml(_srcLabel) + '</span>';
    } else {
      metaEl.innerHTML = _metaBase + ' <span class="fl-source-chip fl-source-unknown">\u26a0 origin unknown</span>';
    }
  }

  // Source warning — shown for draft_generated builds from auto-intake channels
  const warnEl = document.getElementById('fl-source-warning');
  if (warnEl) {
    const _isAutoDraft = job.status === 'draft_generated' && job.source === 'peter_chat_smart';
    if (_isAutoDraft) {
      warnEl.textContent = '\u26a0 This draft was auto-generated from a Peter chat side-effect \u2014 not an explicit Frank request. Review carefully or discard and re-queue intentionally.';
      warnEl.style.display = '';
    } else {
      warnEl.textContent = '';
      warnEl.style.display = 'none';
    }
  }

  // Work stream
  _flRenderStream(job);

  // Review area — shown when toggle is on and review content exists
  const reviewArea = document.getElementById('fl-review-area');
  const hasReview  = _flStatusHasReview(job.status);
  if (reviewArea) reviewArea.style.display = (hasReview && _flReviewVisible) ? '' : 'none';
  if (hasReview && _flReviewVisible) _flLoadReviewContent(job);

  // Auto-show apply summary when draft is ready (no click needed)
  if (job.status === 'draft_generated') {
    const summaryWrapper = document.getElementById('fl-apply-summary');
    // Only auto-load if not already showing (avoid repeated fetches on every poll)
    if (summaryWrapper && summaryWrapper.style.display === 'none') {
      flLoadApplySummary(job.build_id);
    }
  }
}

async function _flLoadReviewContent(job) {
  const s = job.status;
  const hasDraft = ['draft_generated', 'draft_blocked', 'draft_generating'].includes(s);
  const hasSpec  = ['pending_review', 'spec_approved', 'stage2_authorized',
                    'draft_generating', 'draft_generated', 'draft_blocked'].includes(s);
  const codeTab = document.getElementById('fl-tab-code');
  if (codeTab) codeTab.style.display = hasDraft ? '' : 'none';
  // Auto-open code tab for fresh draft_generated; plan tab otherwise
  if (hasDraft && s === 'draft_generated') flTabSwitch('code');
  else flTabSwitch('plan');
  if (hasSpec)  await flLoadSpec(job.build_id);
  if (hasDraft) await flLoadDraft(job.build_id);
}

function flTabSwitch(tab) {
  const planPane = document.getElementById('fl-pane-plan');
  const codePane = document.getElementById('fl-pane-code');
  const planTab  = document.getElementById('fl-tab-plan');
  const codeTab  = document.getElementById('fl-tab-code');
  if (tab === 'plan') {
    if (planPane) planPane.classList.add('fl-pane-active');
    if (codePane) codePane.classList.remove('fl-pane-active');
    if (planTab)  planTab.classList.add('fl-tab-active');
    if (codeTab)  codeTab.classList.remove('fl-tab-active');
  } else {
    if (codePane) codePane.classList.add('fl-pane-active');
    if (planPane) planPane.classList.remove('fl-pane-active');
    if (codeTab)  codeTab.classList.add('fl-tab-active');
    if (planTab)  planTab.classList.remove('fl-tab-active');
  }
}

function flToggleReview() {
  _flReviewVisible = !_flReviewVisible;
  if (_lastState && _currentSelection === 'frank-lloyd') {
    populatePanel('frank-lloyd', _lastState, true);
  }
}

// ── Frank Lloyd auto-run ──────────────────────────────────────────────────────

async function flAutoRun(buildIdOverride) {
  const bid = buildIdOverride || _flActionBuildId;
  if (!bid) return;
  _flHideForms();
  _flFeedback('Frank Lloyd is on it\u2026 planning and building in the background.', 'pending');
  try {
    const r = await fetch('/frank-lloyd/' + encodeURIComponent(bid) + '/auto-run', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    const d = await r.json();
    if (!d.ok) {
      _flFeedback('Could not start: ' + _escHtml(d.error || 'Unknown error.'), 'error');
    }
    // Fire-and-forget — backend runs in background; poll picks up progress
    setTimeout(tick, 800);
    setTimeout(tick, 3000);
  } catch(e) {
    _flFeedback('Network error: ' + _escHtml(e.message), 'error');
  }
}

// ── Frank Lloyd action controls ────────────────────────────────────────────────

async function flGenerateSpec() {
  const bid = _flActionBuildId;
  if (!bid) return;
  const fb  = document.getElementById('fl-action-feedback');
  const btn = document.querySelector('[onclick="flGenerateSpec()"]');
  if (btn) { btn.disabled = true; btn.textContent = 'Generating\u2026'; }
  if (fb)  { fb.className = 'fl-action-feedback fl-fb-pending'; fb.textContent = 'Generating plan\u2026 this may take a moment.'; fb.style.display = ''; }
  try {
    const r = await fetch('/frank-lloyd/' + encodeURIComponent(bid) + '/spec', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
    });
    const d = await r.json();
    if (fb) {
      if (d.ok !== false && !d.error) {
        fb.className = 'fl-action-feedback fl-fb-ok';
        fb.textContent = '\u2713 Plan ready for ' + bid + '. Review and approve when ready.';
      } else {
        fb.className = 'fl-action-feedback fl-fb-error';
        fb.textContent = '\u2717 ' + (d.detail || d.error || 'Plan generation failed.');
      }
    }
    setTimeout(tick, 500);
  } catch(e) {
    if (fb)  { fb.className = 'fl-action-feedback fl-fb-error'; fb.textContent = '\u2717 Network error.'; fb.style.display = ''; }
    if (btn) { btn.disabled = false; btn.textContent = '\u2699 GENERATE PLAN'; }
  }
}

async function flGenerateDraft() {
  const bid = _flActionBuildId;
  if (!bid) return;
  const fb  = document.getElementById('fl-action-feedback');
  const btn = document.querySelector('[onclick="flGenerateDraft()"]');
  if (btn) { btn.disabled = true; btn.textContent = 'Building\u2026'; }
  if (fb)  { fb.className = 'fl-action-feedback fl-fb-pending'; fb.textContent = 'Frank Lloyd is writing code\u2026 this may take a minute.'; fb.style.display = ''; }
  try {
    const r = await fetch('/frank-lloyd/' + encodeURIComponent(bid) + '/generate-draft', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    const d = await r.json();
    if (fb) {
      if (d.ok) {
        fb.className = 'fl-action-feedback fl-fb-ok';
        fb.textContent = '\u2713 Draft ready for ' + bid + '. Review it above.';
      } else {
        fb.className = 'fl-action-feedback fl-fb-error';
        fb.textContent = '\u2717 ' + (d.error || d.message || 'Draft generation failed.');
      }
    }
    setTimeout(tick, 500);
  } catch(e) {
    if (fb)  { fb.className = 'fl-action-feedback fl-fb-error'; fb.textContent = '\u2717 Network error.'; fb.style.display = ''; }
    if (btn) { btn.disabled = false; btn.textContent = '\u2699 GENERATE DRAFT'; }
  }
}

function flApproveSpec() {
  if (!_flActionBuildId) return;
  _flHideForms();
  _flAction('Approving plan\u2026', async () => {
    const r = await fetch('/frank-lloyd/' + encodeURIComponent(_flActionBuildId) + '/approve-spec', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({notes: ''}),
    });
    return r.json();
  });
}

function flShowRejectForm() {
  _flHideForms();
  document.getElementById('fl-action-feedback').style.display = 'none';
  const f = document.getElementById('fl-reject-form');
  if (f) f.style.display = '';
  const inp = document.getElementById('fl-reject-reason');
  if (inp) { inp.value = ''; inp.focus(); }
}

function flRejectCancel() {
  const f = document.getElementById('fl-reject-form');
  if (f) f.style.display = 'none';
}

async function flRejectConfirm() {
  const reason = ((document.getElementById('fl-reject-reason') || {}).value || '').trim();
  if (!reason) { _flFeedback('A reason is required to reject.', 'error'); return; }
  document.getElementById('fl-reject-form').style.display = 'none';
  _flAction('Rejecting plan\u2026', async () => {
    const r = await fetch('/frank-lloyd/' + encodeURIComponent(_flActionBuildId) + '/reject-spec', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({reason}),
    });
    return r.json();
  });
}

function flShowAuthorizeForm() {
  _flHideForms();
  document.getElementById('fl-action-feedback').style.display = 'none';
  const f = document.getElementById('fl-authorize-form');
  if (f) f.style.display = '';
  const inp = document.getElementById('fl-authorize-notes');
  if (inp) { inp.value = ''; inp.focus(); }
}

function flAuthorizeCancel() {
  const f = document.getElementById('fl-authorize-form');
  if (f) f.style.display = 'none';
}

async function flAuthorizeConfirm() {
  const notes = ((document.getElementById('fl-authorize-notes') || {}).value || '').trim();
  document.getElementById('fl-authorize-form').style.display = 'none';
  _flAction('Authorizing build\u2026', async () => {
    const r = await fetch('/frank-lloyd/' + encodeURIComponent(_flActionBuildId) + '/authorize-stage2', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({notes}),
    });
    return r.json();
  });
}

function flShowPromoteForm() {
  _flHideForms();
  document.getElementById('fl-action-feedback').style.display = 'none';
  const pf = document.getElementById('fl-promote-form');
  if (pf) {
    pf.style.display = '';
    const fb  = document.getElementById('fl-promote-feedback');
    if (fb) fb.style.display = 'none';
    const inp = document.getElementById('fl-promote-target');
    if (inp) { inp.disabled = false; if (!inp.value) inp.focus(); }

    // Adapt form labels based on build type (modification vs new-file)
    const job     = (_lastState && _lastState.frank_lloyd) ? _lastState.frank_lloyd.active_job : null;
    const bt      = ((job || {}).build_type || '').toLowerCase();
    const isMod   = bt.includes('modif') || bt.includes('patch');
    const hintEl  = document.getElementById('fl-promote-hint');
    const labelEl = document.getElementById('fl-promote-form-label');
    const btnEl   = document.getElementById('fl-promote-btn');
    if (isMod) {
      if (hintEl)  hintEl.textContent  = 'Modification build \u2014 existing file will be replaced. Back up manually if needed.';
      if (hintEl)  hintEl.style.color  = '#ff9800';
      if (labelEl) labelEl.textContent = 'TARGET FILE TO REPLACE';
      if (btnEl)   btnEl.textContent   = 'REPLACE FILE IN REPO';
      // Pre-fill target path from apply summary target_path if known
      const summaryEl = document.getElementById('fl-apply-summary-content');
      // Will be pre-filled by flLoadApplySummary if det_target_path is set
    } else {
      if (hintEl)  hintEl.textContent  = 'New .py file only \u2014 file must not already exist.';
      if (hintEl)  hintEl.style.color  = '';
      if (labelEl) labelEl.textContent = 'TARGET PATH IN REPO';
      if (btnEl)   btnEl.textContent   = 'APPLY TO REPO';
    }
  }
  // Load apply summary alongside the form (non-blocking)
  if (_flActionBuildId) flLoadApplySummary(_flActionBuildId);
}

function flPromoteCancel() {
  const pf = document.getElementById('fl-promote-form');
  if (pf) pf.style.display = 'none';
  const sumEl = document.getElementById('fl-apply-summary');
  if (sumEl) sumEl.style.display = 'none';
}

async function flPromoteConfirm() {
  const buildId = _flActionBuildId;
  const fb = document.getElementById('fl-promote-feedback');
  if (!buildId) return;
  const inp = document.getElementById('fl-promote-target');
  const tgt = inp ? inp.value.trim() : '';
  if (!tgt) {
    if (fb) { fb.className = 'fl-action-feedback fl-fb-error'; fb.textContent = 'Target path is required.'; fb.style.display = ''; }
    return;
  }
  if (fb) { fb.className = 'fl-action-feedback fl-fb-pending'; fb.textContent = 'Applying to repo\u2026'; fb.style.display = ''; }
  try {
    const r = await fetch('/frank-lloyd/' + encodeURIComponent(buildId) + '/promote-draft', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({target_path: tgt}),
    });
    const data = await r.json();
    if (data.ok) {
      if (fb) { fb.className = 'fl-action-feedback fl-fb-ok'; fb.textContent = '\u2713 Applied: ' + _escHtml(data.target_path || tgt); fb.style.display = ''; }
      const pf = document.getElementById('fl-promote-form');
      if (pf) pf.querySelectorAll('button, input').forEach(el => el.disabled = true);
      setTimeout(async () => { const s = await fetchState(); if (s) applyState(s); }, 900);
    } else {
      if (fb) { fb.className = 'fl-action-feedback fl-fb-error'; fb.textContent = _escHtml(data.error || 'Promotion failed.'); fb.style.display = ''; }
    }
  } catch(e) {
    if (fb) { fb.className = 'fl-action-feedback fl-fb-error'; fb.textContent = 'Error: ' + _escHtml(e.message); fb.style.display = ''; }
  }
}

async function flDiscardDraft() {
  const buildId = _flActionBuildId;
  if (!buildId) return;
  _flHideForms();
  _flFeedback('Discarding draft\u2026', 'pending');
  try {
    const r = await fetch('/frank-lloyd/' + encodeURIComponent(buildId) + '/discard-draft', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    const data = await r.json();
    if (data.ok) {
      _flFeedback('\u2713 Draft discarded. Ready for a new draft attempt.', 'ok');
      _flReviewVisible = false;
      setTimeout(async () => { const s = await fetchState(); if (s) applyState(s); }, 900);
    } else {
      _flFeedback(data.error || 'Discard failed.', 'error');
    }
  } catch(e) {
    _flFeedback('Error: ' + _escHtml(e.message), 'error');
  }
}

async function _flAction(pendingMsg, fetchFn) {
  _flFeedback(pendingMsg, 'pending');
  try {
    const data = await fetchFn();
    if (data.ok) {
      _flFeedback(data.message || 'Done.', 'ok');
      setTimeout(tick, 400);
    } else {
      _flFeedback(data.error || 'Action failed.', 'error');
    }
  } catch(e) {
    _flFeedback('Network error: ' + e.message, 'error');
  }
}

function _flFeedback(msg, cls) {
  const el = document.getElementById('fl-action-feedback');
  if (!el) return;
  el.textContent = msg;
  el.className = 'fl-action-feedback fl-fb-' + cls;
  el.style.display = '';
  if (cls === 'ok') setTimeout(() => { if (el) el.style.display = 'none'; }, 5000);
}

function _flHideForms() {
  ['fl-reject-form', 'fl-authorize-form', 'fl-promote-form', 'fl-apply-summary'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}

// ── Frank Lloyd apply summary ─────────────────────────────────────────────────

async function flLoadApplySummary(buildId) {
  const wrapper  = document.getElementById('fl-apply-summary');
  const content  = document.getElementById('fl-apply-summary-content');
  if (!wrapper || !content) return;
  wrapper.style.display = '';
  content.innerHTML = '<span class="fl-apply-loading">Loading summary\u2026</span>';
  try {
    const r    = await fetch('/frank-lloyd/' + encodeURIComponent(buildId) + '/apply-summary');
    const data = await r.json();
    if (!data.ok || !data.summary) {
      content.innerHTML = '<span class="fl-apply-loading">Summary not available \u2014 review draft_module.py directly.</span>';
      return;
    }
    const s = data.summary;
    const riskCls = s.risk && s.risk.toLowerCase().includes('critical') ? 'risk-critical'
                  : s.risk && s.risk.toLowerCase().includes('high')     ? 'risk-high'
                  : s.risk && s.risk.toLowerCase().includes('medium')   ? 'risk-medium'
                  : 'risk-low';
    const files = Array.isArray(s.files) ? s.files.join(', ') : (s.files || '');
    function row(key, val, cls) {
      const safeVal = _escHtml(val || '\u2014');
      const valCls  = cls ? ' class="fl-apply-val ' + cls + '"' : ' class="fl-apply-val"';
      return '<div class="fl-apply-row"><span class="fl-apply-key">' + key + '</span><span' + valCls + '>' + safeVal + '</span></div>';
    }
    content.innerHTML =
      row('WHAT',        s.what_built) +
      row('PROBLEM',     s.problem) +
      row('FILES',       files) +
      row('RISK',        s.risk, riskCls) +
      row('VALIDATION',  s.validation) +
      row('ON APPLY',    s.on_apply) +
      row('UNCERTAINTY', s.uncertainty);
    // Pre-fill target path if summary has one
    const tgt = (s.target_path || '').trim();
    const inp  = document.getElementById('fl-promote-target');
    if (inp && tgt && !inp.value) inp.value = tgt;
  } catch(e) {
    content.innerHTML = '<span class="fl-apply-loading">Summary error: ' + _escHtml(e.message) + '</span>';
  }
}

// ── Frank Lloyd spec + draft loaders ─────────────────────────────────────────

async function flLoadSpec(buildId) {
  const yamlEl = document.getElementById('fl-spec-yaml');
  const pfEl   = document.getElementById('fl-preflight-view');
  if (yamlEl) yamlEl.textContent = 'Loading\u2026';
  if (pfEl)   pfEl.style.display = 'none';
  try {
    const r    = await fetch('/frank-lloyd/' + encodeURIComponent(buildId) + '/spec-review');
    const data = await r.json();
    if (!data.ok) {
      if (yamlEl) yamlEl.textContent = data.error || 'Plan not available.';
      return;
    }
    if (data.spec_yaml && yamlEl) yamlEl.textContent = data.spec_yaml.trim();
    if (data.preflight_md && pfEl) {
      pfEl.textContent = data.preflight_md.trim();
      pfEl.style.display = '';
    }
  } catch(e) {
    if (yamlEl) yamlEl.textContent = 'Error: ' + e.message;
  }
}

async function flLoadDraft(buildId) {
  const metaRow   = document.getElementById('fl-draft-meta-row');
  const blockedEl = document.getElementById('fl-draft-blocked-msg');
  const notesEl   = document.getElementById('fl-draft-notes-view');
  const codeEl    = document.getElementById('fl-draft-code');

  if (metaRow)   metaRow.innerHTML       = '<span style="color:#37474f;font-size:8px">Loading\u2026</span>';
  if (blockedEl) blockedEl.style.display = 'none';
  if (notesEl)   notesEl.style.display   = 'none';
  if (codeEl)    { codeEl.textContent = ''; codeEl.style.display = 'none'; }

  try {
    const r    = await fetch('/frank-lloyd/' + encodeURIComponent(buildId) + '/draft');
    const data = await r.json();

    if (!data.ok) {
      if (metaRow)   metaRow.innerHTML = '';
      if (blockedEl) { blockedEl.textContent = data.error || 'Draft unavailable.'; blockedEl.style.display = ''; }
      return;
    }

    const m = data.manifest || {};
    const chips = [m.task_class, m.provider_tier ? (m.provider_tier + ' lane') : null, m.model_used].filter(Boolean);
    if (metaRow) metaRow.innerHTML = chips.map(c => '<span class="fl-draft-chip">' + _escHtml(c) + '</span>').join('');

    if (data.status === 'draft_generated') {
      if (data.notes_text && notesEl) {
        notesEl.textContent = data.notes_text.replace(/^#.*\n/, '').trim();
        notesEl.style.display = '';
      }
      if (data.module_code && codeEl) {
        codeEl.textContent = data.module_code.trim();
        codeEl.style.display = '';
      }
    } else if (data.status === 'draft_blocked') {
      const reason = m.error || data.error || 'Draft blocked \u2014 see build log.';
      if (blockedEl) { blockedEl.textContent = reason; blockedEl.style.display = ''; }
    }
  } catch(e) {
    if (metaRow) metaRow.innerHTML = '<span style="color:#ef5350;font-size:8px">Error: ' + _escHtml(e.message) + '</span>';
  }
}

// ── Frank Lloyd build composer ────────────────────────────────────────────────

async function flQueueBuild() {
  const promptEl = document.getElementById('fl-compose-prompt');
  const fb       = document.getElementById('fl-compose-feedback');
  const raw      = promptEl ? promptEl.value.trim() : '';
  if (!raw) {
    if (fb) { fb.className = 'fl-action-feedback fl-fb-error'; fb.textContent = 'Describe what Frank Lloyd should build.'; fb.style.display = ''; }
    return;
  }
  if (fb) { fb.className = 'fl-action-feedback fl-fb-pending'; fb.textContent = 'Frank Lloyd is planning\u2026'; fb.style.display = ''; }
  try {
    const r = await fetch('/frank-lloyd/smart-queue', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({raw_input: raw}),
    });
    const data = await r.json();
    if (data.needs_clarification) {
      if (fb) { fb.className = 'fl-action-feedback fl-fb-pending'; fb.textContent = data.question || 'Could you be more specific?'; fb.style.display = ''; }
    } else if (data.ok) {
      if (fb) { fb.className = 'fl-action-feedback fl-fb-ok'; fb.textContent = '\u2713 ' + _escHtml(data.message || 'Queued — Frank Lloyd is on it.'); fb.style.display = ''; }
      if (promptEl) promptEl.value = '';
      // Smart-queue fires auto-run server-side; poll quickly to show progress
      setTimeout(tick, 400);
      setTimeout(tick, 1800);
      setTimeout(tick, 4000);
    } else {
      if (fb) { fb.className = 'fl-action-feedback fl-fb-error'; fb.textContent = _escHtml(data.error || 'Could not queue build.'); fb.style.display = ''; }
    }
  } catch(e) {
    if (fb) { fb.className = 'fl-action-feedback fl-fb-error'; fb.textContent = 'Error: ' + _escHtml(e.message); fb.style.display = ''; }
  }
}

async function flAbandon() {
  if (!_flActionBuildId) return;
  if (!confirm('Abandon ' + _flActionBuildId + '? This cannot be undone.')) return;
  const fb = document.getElementById('fl-action-feedback');
  if (fb) { fb.className = 'fl-action-feedback fl-fb-pending'; fb.textContent = 'Abandoning\u2026'; fb.style.display = ''; }
  try {
    const r = await fetch('/frank-lloyd/' + _flActionBuildId + '/abandon', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({}),
    });
    const d = await r.json();
    if (d.ok) {
      if (fb) { fb.className = 'fl-action-feedback fl-fb-ok'; fb.textContent = '\u2713 ' + _flActionBuildId + ' abandoned.'; fb.style.display = ''; }
      _flLastStatus = null;  // Reset so transition detection works for next build
      setTimeout(tick, 400);
    } else {
      if (fb) { fb.className = 'fl-action-feedback fl-fb-error'; fb.textContent = _escHtml(d.error || 'Could not abandon build.'); fb.style.display = ''; }
    }
  } catch(e) {
    if (fb) { fb.className = 'fl-action-feedback fl-fb-error'; fb.textContent = 'Error: ' + _escHtml(e.message); fb.style.display = ''; }
  }
}

async function refreshOpsPanel(id) {
  const btn = document.getElementById('refresh-btn-' + id);
  if (btn && btn.disabled) return;
  const origText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = id === 'custodian' ? 'Checking\u2026' : 'Refreshing\u2026'; }
  try {
    if (id === 'custodian') {
      const r = await fetch('/custodian/health');
      if (!r.ok) throw new Error('HTTP ' + r.status);
    }
    const s = await fetchState();
    if (s) applyState(s);
    if (btn) {
      btn.disabled  = false;
      btn.textContent = '\u2713 Done';
      setTimeout(() => { if (btn) btn.textContent = origText; }, 1600);
    }
  } catch(e) {
    if (_currentSelection === id) {
      setItems('dp-situation', [{text: 'Refresh failed \u2014 ' + e.message, cls: 'warn'}]);
    }
    if (btn) { btn.disabled = false; btn.textContent = origText; }
  }
}

// ── Neighborhood summary ──────────────────────────────────────────────────
function updateSummary(state) {
  const belfort    = state.belfort    || {};
  const supervisor = state.supervisor || {};
  const checker    = state.checker    || {};
  const custodian  = state.custodian  || {};
  const sentinel   = state.sentinel   || {};

  const bStatus      = belfort.status || 'unknown';
  const reviewNeeded = ['waiting_for_review','review_held'].includes(bStatus);
  const warns        = checker.open_warnings || 0;
  const custBad      = custodian.overall === 'degraded';
  const sentBad      = ['review','not_ready'].includes(sentinel.verdict || '');

  const attnEl = document.getElementById('nb-attention');
  if (reviewNeeded) {
    attnEl.textContent = '⚡ Review needed — result ready';
    attnEl.className = 'nb-item attn';
  } else if (warns > 0) {
    attnEl.textContent = `⚠ ${warns} issue${warns > 1 ? 's' : ''} flagged`;
    attnEl.className = 'nb-item warn';
  } else if (custBad) {
    attnEl.textContent = '⚠ System health degraded';
    attnEl.className = 'nb-item warn';
  } else if (sentBad) {
    attnEl.textContent = `⚠ Patch safety: ${(sentinel.verdict || '').replace('_', ' ')}`;
    attnEl.className = 'nb-item warn';
  } else {
    attnEl.textContent = 'All clear';
    attnEl.className = 'nb-item';
  }

  const belEl = document.getElementById('nb-belfort');
  const _bTon = belfort.trading_active || false;
  const _bLon = supervisor.enabled || false;
  belEl.textContent = 'Belfort: ' + (_bTon && _bLon ? 'trading \u00b7 research' : _bTon ? 'trading' : _bLon ? 'research' : reviewNeeded ? 'review needed' : 'idle');
  belEl.className   = 'nb-item' + ((_bTon || _bLon) ? ' ok' : reviewNeeded ? ' attn' : '');

  const flSumEl    = document.getElementById('nb-frank-lloyd');
  const _flAj      = (state.frank_lloyd || {}).active_job || null;
  const _flSt      = (_flAj || (state.frank_lloyd || {}).active_build || {}).status || '';
  const _flPend    = (state.frank_lloyd || {}).pending_count || 0;
  const _flRelayN  = ((state.frank_lloyd || {}).fl_relay || []).length;
  const _flRelayAlert = ((state.frank_lloyd || {}).fl_relay || []).some(r => ['review_needed','spec_blocked','draft_blocked'].includes(r.event));
  const _flText = _flSt === 'draft_generated'  ? 'Build: draft ready'
                : _flSt === 'pending_review'    ? 'Build: plan needs review'
                : _flSt === 'draft_blocked'      ? 'Build: draft blocked'
                : ['draft_generating','stage2_authorized','spec_approved'].includes(_flSt) ? 'Build: building\u2026'
                : _flPend > 0                   ? 'Build: queued'
                : 'Build: idle';
  flSumEl.textContent = _flText;
  flSumEl.className   = 'nb-item' + (_flSt === 'draft_generated' || _flSt === 'pending_review' ? ' attn' : _flRelayAlert ? ' warn' : _flPend > 0 ? '' : '');

  const issues = (warns > 0 ? 1 : 0) + (custBad ? 1 : 0) + (sentBad ? 1 : 0);
  const opsEl  = document.getElementById('nb-ops');
  opsEl.textContent = issues > 0 ? `Ops: ${issues} issue${issues > 1 ? 's' : ''}` : 'Ops: all clear';
  opsEl.className   = 'nb-item ' + (issues > 0 ? 'warn' : 'ok');
}

// ── Main state update ─────────────────────────────────────────────────────
function applyState(state) {
  if (!state) return;
  _lastState = state;

  const belfort    = state.belfort    || {};
  const supervisor = state.supervisor || {};
  const checker    = state.checker    || {};
  const custodian  = state.custodian  || {};
  const sentinel   = state.sentinel   || {};
  const warden     = state.warden     || {};

  // Peter
  const bStatus      = belfort.status || 'unknown';
  const reviewNeeded = ['waiting_for_review','review_held'].includes(bStatus);
  const warnings     = (checker.open_warnings || 0) > 0;
  const custDegraded = custodian.overall === 'degraded';
  const sentBad      = ['review','not_ready'].includes(sentinel.verdict || '');
  const loopEnabled  = supervisor.enabled;

  const peterNeedsAttn = warnings || custDegraded || sentBad;

  // Peter's speech reflects both Belfort review needs AND Frank Lloyd active jobs
  const _flStateForPeter  = state.frank_lloyd || {};
  const _flJobForPeter    = _flStateForPeter.active_job || null;
  const _flStatusForPeter = (_flJobForPeter || {}).status || '';
  const flNeedsReview = ['pending_review','draft_generated'].includes(_flStatusForPeter);
  const flBuilding    = ['pending_spec','spec_approved','stage2_authorized','draft_generating'].includes(_flStatusForPeter);

  setClass(document.getElementById('h-peter'),
    reviewNeeded || flNeedsReview ? 'st-review' :
    peterNeedsAttn                ? 'st-warning' : 'st-idle');
  const pb = document.getElementById('pb-peter');
  if (pb) pb.textContent = reviewNeeded || flNeedsReview ? 'REVIEW' : peterNeedsAttn ? 'ATTENTION' : 'READY';
  const _peterSpeech = reviewNeeded       ? 'Belfort review needed'
                     : flNeedsReview      ? (_flStatusForPeter === 'draft_generated' ? 'Draft ready for review' : 'Plan ready — your call')
                     : flBuilding         ? 'Frank Lloyd is building\u2026'
                     : peterNeedsAttn     ? 'Needs your attention'
                     : 'No urgent items';
  setSpeech('sp-peter', _peterSpeech, true);

  // Frank Lloyd
  const fl           = state.frank_lloyd || {};
  const flPending    = fl.pending_count  || 0;
  const flActive     = fl.active_build   || null;
  const flAStatus    = (flActive || {}).status || '';
  const flRelay      = fl.fl_relay || [];
  const flHasAlert   = flRelay.some(r => ['review_needed','spec_blocked','draft_blocked'].includes(r.event));
  const flHasReady   = flRelay.some(r => r.event === 'draft_ready');
  const flCls = flAStatus === 'pending_review' ? 'st-review'
              : flAStatus === 'draft_generated' ? 'st-review'
              : flHasAlert                       ? 'st-warning'
              : ['draft_generating','stage2_authorized','spec_approved'].includes(flAStatus) ? 'st-ok'
              : flPending > 0                   ? 'st-warning'
              : 'st-idle';
  setClass(document.getElementById('h-frank-lloyd'), flCls);
  const flb = document.getElementById('pb-frank-lloyd');
  if (flb) flb.textContent = flAStatus === 'draft_generated' ? 'DRAFT READY'
                            : flAStatus === 'pending_review'  ? 'NEEDS REVIEW'
                            : flAStatus === 'draft_blocked'   ? 'BLOCKED'
                            : ['draft_generating','stage2_authorized','spec_approved'].includes(flAStatus) ? 'BUILDING'
                            : flPending > 0                   ? 'QUEUED'
                            : 'IDLE';
  const flAj       = fl.active_job || null;
  const flJobTitle = (flAj || {}).title || (flActive || {}).title || '';
  const flSpeech   = flAStatus === 'draft_generated'    ? 'Draft ready for review'
                   : flAStatus === 'pending_review'      ? 'Plan needs review'
                   : flAStatus === 'draft_blocked'       ? 'Draft blocked'
                   : ['draft_generating','stage2_authorized','spec_approved'].includes(flAStatus) ? 'Building\u2026'
                   : flPending > 0                       ? flJobTitle.slice(0, 28)
                   : '';
  setSpeech('sp-frank-lloyd', flSpeech, !!flSpeech);

  // Show relay messages in FL workspace action feedback when FL panel is active
  if (flRelay.length && _currentSelection === 'frank-lloyd') {
    const latest = flRelay[flRelay.length - 1];
    const isAlert = ['review_needed','spec_blocked','draft_blocked'].includes(latest.event);
    _flFeedback(latest.msg, isAlert ? 'error' : latest.event === 'draft_ready' ? 'ok' : 'pending');
  }

  // Belfort
  setClass(document.getElementById('h-belfort'), belfortStatusClass(bStatus));
  const bb = document.getElementById('pb-belfort');
  if (bb) bb.textContent = belfortSummaryLabel(belfort, supervisor);
  const bTradingOn = belfort.trading_active || false;
  const bLoopOn    = loopEnabled;
  const bOpenPos   = belfort.open_positions || [];
  const bLt        = belfort.last_trade;
  const bSpeech    = bOpenPos.length > 0 ? ('Open: ' + bOpenPos.join(', '))
    : bLt ? (bLt.side + '\u00a0' + bLt.symbol + (bLt.pnl != null ? '\u00a0(' + (bLt.pnl >= 0 ? '+$' : '-$') + Math.abs(bLt.pnl).toFixed(2) + ')' : ''))
    : bTradingOn ? 'Mock trading active' : '';
  setSpeech('sp-belfort', bSpeech, bTradingOn || bLoopOn || bSpeech.length > 0);

  // Ops
  const custCls = custodian.overall === 'healthy' ? 'st-ok' :
                  custodian.overall === 'degraded' ? 'st-warning' : 'st-idle';
  setOps('u-custodian', 'os-custodian', custCls, (custodian.overall || '?').toUpperCase());

  const warns = checker.open_warnings || 0;
  setOps('u-checker', 'os-checker', warns > 0 ? 'st-warning' : 'st-ok', warns > 0 ? `${warns} WARN` : 'CLEAR');

  const sv    = sentinel.verdict || 'unknown';
  const svCls = sv === 'safe' ? 'st-ok' : sv === 'not_ready' ? 'st-error' : sv === 'review' ? 'st-warning' : 'st-idle';
  setOps('u-sentinel', 'os-sentinel', svCls, sv.toUpperCase().replace('_', ' '));

  const supCls = supervisor.enabled ? 'st-ok' : supervisor.errors > 0 ? 'st-warning' : 'st-idle';
  setOps('u-supervisor', 'os-supervisor', supCls, supervisor.enabled ? 'RUNNING' : 'OFF');

  const wCalls = warden.total_calls || 0;
  const wCost  = warden.total_cost_usd || 0;
  setOps('u-warden', 'os-warden', wCalls > 0 ? 'st-ok' : 'st-idle',
         wCalls > 0 ? `$${wCost.toFixed(4)}` : 'NO CALLS');

  // Summary bar
  updateSummary(state);

  // Refresh open panel with new state — skip clear to avoid loading flash
  if (_currentSelection) populatePanel(_currentSelection, state, true);

  // Conn bar
  const connDot = document.getElementById('conn-dot');
  connDot.textContent = '● LIVE';
  connDot.className   = 'ok';
  const cs = document.getElementById('conn-status');
  if (cs) { cs.textContent = '✓ Connected'; cs.className = 'ok'; }
  const lu = document.getElementById('last-updated');
  if (lu) lu.textContent = `Updated ${new Date().toLocaleTimeString()}`;
}

// ── Fetch & poll ──────────────────────────────────────────────────────────
async function fetchState() {
  try {
    const r = await fetch(STATE_URL, { cache: 'no-store' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    const connDot = document.getElementById('conn-dot');
    connDot.textContent = '● OFFLINE';
    connDot.className   = 'error';
    const cs = document.getElementById('conn-status');
    if (cs) { cs.textContent = '⚠ API unreachable'; cs.className = ''; }
    return null;
  }
}

async function tick() {
  const state = await fetchState();
  if (state) applyState(state);
}

// ── Boot ──────────────────────────────────────────────────────────────────
showWelcomeIfNew();
tick();
setInterval(tick, POLL_MS);
</script>
</body>
</html>
"""
