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
        base["trading_active"] = get_status().get("running", False)
    except Exception:
        base["trading_active"] = False

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


@router.post("/peter/chat")
async def peter_chat(body: dict = Body(default={})) -> dict:
    """
    LM-backed Peter chat. Accepts {message: str}, returns {ok: bool, text: str, error: str}.
    Read-only guidance only — Peter never executes actions via this endpoint.
    """
    from fastapi import HTTPException
    body = body or {}
    message = str(body.get("message", "")).strip()[:300]
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    state = {
        "belfort":    _belfort_state(),
        "supervisor": _supervisor_state(),
        "checker":    _checker_state(),
        "custodian":  _custodian_state(),
        "sentinel":   _sentinel_state(),
        "warden":     _warden_state(),
    }
    ctx_str = json.dumps(state, separators=(",", ":"))

    system = (
        "You are Peter, coordinator agent for an automated AI trading research system. "
        "Answer the operator's question in plain English — 1 to 3 concise sentences. "
        "Be direct and specific. Use the system state context provided. "
        "You are read-only guidance: do not claim to execute actions. "
        "Do not mention you are an AI or reference the JSON context."
    )
    user = f"System state:\n{ctx_str}\n\nOperator: {message}"

    try:
        from app.cost_warden import LMHelper
        result = LMHelper("peter", "health_explain", max_tokens=200, temperature=0.4).call(
            system=system, user=user,
        )
        if not result.ok:
            return {"ok": False, "text": "", "error": result.error}
        return {"ok": True, "text": result.content.strip(), "error": ""}
    except Exception as exc:
        return {"ok": False, "text": "", "error": str(exc)}


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
.peter   .chimney { background: #9e6a00; }
.belfort .chimney { background: #006b5a; }

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
.peter   .roof { border-bottom: 56px solid #c4820d; }
.belfort .roof { border-bottom: 56px solid #008080; }

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
.peter   .body { background: #f6c90e; border-color: #a06b00; }
.belfort .body { background: #00cec9; border-color: #006b5a; }

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
.peter   .win { background: #b8e0ff; }
.belfort .win { background: #b2f0ed; }

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
.peter   .door { background: #6d3a00; }
.belfort .door { background: #004d40; }

/* Nameplate */
.nameplate {
  font-size: 12px;
  letter-spacing: 3px;
  font-weight: bold;
  margin-top: 6px;
  transition: color 0.3s;
}
.peter   .nameplate { color: #f6c90e; text-shadow: 0 0 6px #f6c90e66; }
.belfort .nameplate { color: #00cec9; text-shadow: 0 0 6px #00cec966; }

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
.peter-chat-input-row { display: flex; gap: 5px; margin-top: 2px; }
.peter-chat-input {
  flex: 1; background: #040d1a; border: 1px solid #1e2d45; color: #b0bec5;
  font-family: 'Courier New', Courier, monospace; font-size: 10px;
  padding: 5px 8px; border-radius: 2px; outline: none; transition: border-color 0.15s;
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
  display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 5px;
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

    </div>
  </div>

  <!-- Neighborhood Summary -->
  <div id="nbhd-summary">
    <span id="nb-attention" class="nb-item">—</span>
    <span class="nb-sep">·</span>
    <span id="nb-belfort" class="nb-item">BELFORT —</span>
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
          <input id="peter-chat-input" class="peter-chat-input" type="text"
                 placeholder="Ask anything…" maxlength="280" autocomplete="off">
          <button id="peter-chat-send" class="peter-chat-send" onclick="peterChatSend()">SEND</button>
        </div>
        <div class="chat-chips">
          <span class="chat-chip" onclick="peterChatAsk('What is happening right now?')">What is happening?</span>
          <span class="chat-chip" onclick="peterChatAsk('What needs my attention?')">Needs attention?</span>
          <span class="chat-chip" onclick="peterChatAsk('What should I do next?')">What next?</span>
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
        <div class="dp-divider"></div>
        <div class="dp-section-label">CONTROLS</div>
        <div class="belfort-controls-grid">
          <button class="bctrl-btn bctrl-start" id="btn-trading-toggle" onclick="belfortToggle('trading')">&#9654; Start Trading</button>
          <button class="bctrl-btn bctrl-start" id="btn-loop-toggle"    onclick="belfortToggle('loop')">&#9654; Enable Loop</button>
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
let _lastState            = null;
let _currentSelection     = null;
let _sentinelPanelAutoRan = false;

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
  const tradingOn = (belfort || {}).trading_active || false;
  const loopOn    = (supervisor || {}).enabled      || false;
  const review    = ['waiting_for_review','review_held'].includes((belfort || {}).status || '');
  if (review)               return 'REVIEW NEEDED';
  if (tradingOn && loopOn)  return 'TRADING \u00b7 RESEARCH ON';
  if (tradingOn)            return 'TRADING ON';
  if (loopOn)               return 'RESEARCH ON';
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
}

// ── Panel population ──────────────────────────────────────────────────────
const _META = {
  peter:      ['PETER',           'Your main interface · workspace guide'],
  belfort:    ['MR BELFORT',      'Runs trading research in the background'],
  custodian:  ['CUSTODIAN',       'Monitors system health and environment'],
  checker:    ['LOOP CHECKER',    'Finds issues and flags suspicious patterns'],
  sentinel:   ['TEST SENTINEL',   'Checks that patches are safe before deploy'],
  supervisor: ['LOOP SUPERVISOR', 'Controls the automated research loop'],
  warden:     ['COST WARDEN',     'Manages AI model usage and routing cost'],
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

function populatePanel(id, state) {
  setBasicPanel(id);
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
    const loopOn       = supervisor.enabled;
    const cls   = reviewNeeded ? 'review' : (warns || custBad || sentBad) ? 'warning' : loopOn ? 'active' : 'idle';
    const label = reviewNeeded ? 'REVIEW NEEDED' : loopOn ? 'LOOP RUNNING' : 'IDLE';
    setBadge(cls, label);
    document.getElementById('dp-status-detail').textContent =
      loopOn ? `Cycle ${supervisor.cycle_count || 0}` : '';

    const sit = [];
    if (reviewNeeded)              sit.push({text: 'A research result is ready for your review', cls: 'warn'});
    if (warns > 0)                 sit.push({text: `${warns} issue${warns > 1 ? 's' : ''} flagged by the audit system`, cls: 'warn'});
    if (custBad)                   sit.push({text: 'System health needs attention', cls: 'warn'});
    if (sentBad)                   sit.push({text: `Patch safety check: ${(sentinel.verdict || '').replace('_',' ')}`, cls: 'warn'});
    if (supervisor.stop_requested) sit.push({text: 'Research loop is stopping', cls: 'warn'});
    if (!sit.length)               sit.push({text: loopOn ? 'Research is running \u2014 monitoring progress' : 'Everything is quiet', cls: 'ok'});
    setItems('dp-situation', sit);

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
      cinp.addEventListener('keydown', function(e) { if (e.key === 'Enter') peterChatSend(); });
    }
    setActions([{text: '\u26a1 Open Peter workspace \u2192', onclick: "openDashTab('peter')", primary: true}]);
  }

  else if (id === 'belfort') {
    const bStatus   = belfort.status || 'unknown';
    const tradingOn = belfort.trading_active || false;
    const loopOn    = supervisor.enabled || false;
    const cls       = belfortStatusClass(bStatus).replace('st-', '') || 'idle';
    setBadge(cls === 'st-idle' ? 'idle' : cls, belfortSummaryLabel(belfort, supervisor));
    document.getElementById('dp-status-detail').textContent =
      tradingOn && loopOn ? 'Trading ON \u00b7 Research ON'
      : tradingOn ? 'Trading ON \u00b7 Research OFF'
      : loopOn    ? 'Trading OFF \u00b7 Research ON'
      : 'Trading OFF \u00b7 Research OFF';

    // Trading-first situation
    const openPos = belfort.open_positions || [];
    const pnl     = (belfort.realized_pnl || 0) + (belfort.unrealized_pnl || 0);
    const trades  = belfort.trade_count || 0;
    const pnlAbs  = Math.abs(pnl);
    const pnlStr  = (pnl >= 0 ? '+$' : '-$') + (pnlAbs >= 1000 ? (pnlAbs/1000).toFixed(2)+'k' : pnlAbs.toFixed(2));
    const sit = [];
    if (openPos.length > 0) {
      sit.push({text: 'Open position: ' + openPos.join(', '), cls: 'ok'});
    } else {
      const lt = belfort.last_trade;
      if (lt) {
        const ltP = lt.pnl != null ? (' (' + (lt.pnl >= 0 ? '+$' : '-$') + Math.abs(lt.pnl).toFixed(2) + ')') : '';
        const ltCls = lt.pnl != null && lt.pnl < 0 ? 'warn' : lt.pnl != null && lt.pnl > 0 ? 'ok' : '';
        sit.push({text: 'Last trade: ' + lt.side + '\u00a0' + lt.symbol + ' @ $' + (lt.price != null ? lt.price.toFixed(2) : '?') + ltP, cls: ltCls});
        sit.push({text: trades + ' total trade' + (trades > 1 ? 's' : '') + ' \u00b7 P\u0026L ' + pnlStr,
                  cls: pnl > 0.005 ? 'ok' : pnl < -0.005 ? 'warn' : ''});
      } else {
        sit.push({text: 'No trades yet \u2014 baseline at $100k'});
      }
    }
    if (['waiting_for_review','review_held'].includes(bStatus))
      sit.push({text: 'Research result ready for review', cls: 'warn'});
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
    setActions([{text: '\ud83d\udcca Open Belfort workspace \u2192', onclick: "openDashTab('belfort')", primary: true}]);
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
    if (!on && !supervisor.errors) sit.push({text: 'Loop is off \u2014 enable via Belfort controls'});
    setItems('dp-situation', sit);
    setItems('dp-next', [{text: on ? 'View loop detail in Controls' : 'Enable via Belfort \u2192 Enable Loop'}]);
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
    } else if (lt) {
      const ltP = lt.pnl != null ? (' (' + (lt.pnl >= 0 ? '+$' : '-$') + Math.abs(lt.pnl).toFixed(2) + ')') : '';
      parts.push('Last trade: ' + lt.side + '\u00a0' + lt.symbol + ltP + '.');
    } else if (trades === 0) {
      parts.push('No trades yet \u2014 portfolio is at baseline.');
    }
    return parts.join(' ');
  }

  if (lower.includes('attention') || lower.includes('need') || lower.includes('urgent') || lower.includes('issue')) {
    const items = [];
    if (reviewNeeded) items.push('A research result is waiting for your review \u2014 open the Belfort workspace.');
    if (warns > 0)    items.push(warns + ' audit warning' + (warns > 1 ? 's' : '') + ' flagged by the Loop Checker.');
    if (custBad)      items.push('System health is degraded \u2014 click Custodian and run a health check.');
    if (sentBad)      items.push('Test Sentinel shows ' + (sentinel.verdict || '').replace('_', ' ') + ' \u2014 click Sentinel and run a smoke check.');
    if (supervisor.stop_requested) items.push('Research loop stop was requested.');
    if (!items.length) return 'Nothing needs attention right now. Trading: ' + (tradingOn ? 'ON' : 'OFF') + ', Research: ' + (loopOn ? 'ON' : 'OFF') + '.';
    return items.join(' ');
  }

  if (lower.includes('next') || lower.includes('should i') || lower.includes('what do') || lower.includes('what to')) {
    if (reviewNeeded) return 'Open the Belfort workspace \u2014 a research result is waiting for your approval.';
    if (warns > 0)    return 'Check the Loop Checker panel: ' + warns + ' warning' + (warns > 1 ? 's need' : ' needs') + ' review in Controls.';
    if (custBad)      return 'Click Custodian and run a health check to diagnose the system issue.';
    if (sentBad)      return 'Click Sentinel and run a smoke check to clear the safety flag.';
    if (!tradingOn && !loopOn) return 'Click the Belfort house and use the controls to start mock trading or enable the research loop.';
    if (loopOn)       return 'Research is running on cycle ' + (supervisor.cycle_count || 0) + '. Watch for review-needed status on the Belfort house.';
    return 'Mock trading is active. Watch the Belfort house for position updates.';
  }

  // Generic fallback for free-form queries
  return 'For full AI guidance, add an OpenRouter API key. Current state: Trading ' + (tradingOn ? 'ON' : 'OFF') + ', Research ' + (loopOn ? 'ON' : 'OFF') + (reviewNeeded ? ', review pending.' : '.');
}

// ── Peter chat ────────────────────────────────────────────────────────────
let _peterChat = [];  // [{role:'peter'|'operator', text:str, loading?:true}]

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
  if (inp) { inp.value = text; }
  peterChatSend();
}

async function peterChatSend() {
  const inp = document.getElementById('peter-chat-input');
  const btn = document.getElementById('peter-chat-send');
  if (!inp || !btn) return;
  const msg = inp.value.trim();
  if (!msg) return;
  inp.value = '';
  inp.disabled = true;
  btn.disabled = true;
  btn.textContent = '\u2026';
  _peterChat.push({role: 'operator', text: msg});

  const lmAvail = _lastState && _lastState.lm_available;

  if (!lmAvail) {
    // Deterministic path — instant, no API call
    _peterChat.push({role: 'peter', text: _peterDeterministicAnswer(msg)});
    inp.disabled = false;
    btn.disabled = false;
    btn.textContent = 'SEND';
    peterChatRender();
    inp.focus();
    return;
  }

  // LM path
  _peterChat.push({role: 'peter', text: '\u2026', loading: true});
  peterChatRender();
  try {
    const r = await fetch('/peter/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg}),
    });
    const d = await r.json();
    _peterChat = _peterChat.filter(m => !m.loading);
    if (d.ok && d.text) {
      _peterChat.push({role: 'peter', text: d.text});
    } else {
      _peterChat.push({role: 'peter', text: _peterDeterministicAnswer(msg)});
    }
  } catch(e) {
    _peterChat = _peterChat.filter(m => !m.loading);
    _peterChat.push({role: 'peter', text: _peterDeterministicAnswer(msg)});
  } finally {
    inp.disabled = false;
    btn.disabled = false;
    btn.textContent = 'SEND';
    peterChatRender();
    inp.focus();
  }
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
    statsEl.innerHTML =
      '<div class="bstat"><div class="bstat-label">CASH</div><div class="bstat-value">' + cashFmt + '</div></div>' +
      '<div class="bstat"><div class="bstat-label">P&amp;L</div><div class="bstat-value ' + pnlCls + '">' + pnlFmt + '</div></div>' +
      '<div class="bstat"><div class="bstat-label">TRADES</div><div class="bstat-value">' + trades + '</div></div>';
  }
  const pillsEl = document.getElementById('belfort-pills');
  if (pillsEl) {
    pillsEl.innerHTML =
      '<div class="bpill ' + (tradingOn ? 'bpill-active' : '') + '">TRADING\u00a0' + (tradingOn ? 'ON' : 'OFF') + '</div>' +
      '<div class="bpill ' + (loopOn ? 'bpill-active' : '') + '">RESEARCH\u00a0' + (loopOn ? 'ON' : 'OFF') + '</div>';
  }

  // Update toggle button labels based on current state
  const tradBtn = document.getElementById('btn-trading-toggle');
  if (tradBtn && !tradBtn.disabled) {
    tradBtn.textContent = tradingOn ? '\u25a0 Stop Trading' : '\u25b6 Start Trading';
    tradBtn.className   = 'bctrl-btn ' + (tradingOn ? 'bctrl-on bctrl-stop' : 'bctrl-start');
  }
  const loopBtn = document.getElementById('btn-loop-toggle');
  if (loopBtn && !loopBtn.disabled) {
    loopBtn.textContent = loopOn ? '\u25a0 Disable Loop' : '\u25b6 Enable Loop';
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
    if (btn) { btn.disabled = false; btn.textContent = what === 'trading' ? '\u25b6 Start Trading' : '\u25b6 Enable Loop'; }
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

// ── Ops panel refresh ─────────────────────────────────────────────────────
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
    attnEl.textContent = supervisor.enabled ? 'Research running' : 'All clear';
    attnEl.className = 'nb-item' + (supervisor.enabled ? ' ok' : '');
  }

  const belEl = document.getElementById('nb-belfort');
  const _bTon = belfort.trading_active || false;
  const _bLon = supervisor.enabled || false;
  belEl.textContent = 'Belfort: ' + (_bTon && _bLon ? 'trading \u00b7 research' : _bTon ? 'trading' : _bLon ? 'research' : reviewNeeded ? 'review needed' : 'idle');
  belEl.className   = 'nb-item' + ((_bTon || _bLon) ? ' ok' : reviewNeeded ? ' attn' : '');

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

  setClass(document.getElementById('h-peter'),
    reviewNeeded ? 'st-review' : (warnings || custDegraded || sentBad) ? 'st-warning' :
    loopEnabled  ? 'st-active' : 'st-idle');
  const pb = document.getElementById('pb-peter');
  if (pb) pb.textContent = reviewNeeded ? 'REVIEW' : loopEnabled ? 'LOOP ON' : 'IDLE';
  setSpeech('sp-peter',
    reviewNeeded            ? 'Candidate ready for your review' :
    supervisor.stop_requested ? 'Stop requested' :
    loopEnabled             ? `Cycle ${supervisor.cycle_count || 0}` : 'Ready for instructions',
    true);

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

  // Refresh open panel with new state
  if (_currentSelection) populatePanel(_currentSelection, state);

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
