# app/belfort_observer.py
#
# Belfort observation runner.
#
# Runs a single observation tick:
#   - Reads current mode and session from app/belfort_mode and app/market_time
#   - Fetches L1 quotes for the configured universe via app/market_data_feed
#   - Appends observation records to data/belfort/observation_log.jsonl
#   - Writes a preflight snapshot to data/belfort/preflight.json
#
# Observation does NOT execute orders or modify any trading state.
# The preflight snapshot is the authoritative readiness claim used by
# Peter and the UI.
#
# SIP cap rule:
#   If data_lane == "IEX_ONLY", readiness_level is capped at OBSERVATION_ONLY
#   regardless of mode or other checks. IEX data cannot produce PAPER_READY claims.
#
# Public API:
#   run_observation_tick(symbol=None) → dict
#   write_preflight_snapshot()        → dict

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Optional

_ROOT         = pathlib.Path(__file__).resolve().parent.parent
_OBS_LOG      = _ROOT / "data" / "belfort" / "observation_log.jsonl"
_PREFLIGHT    = _ROOT / "data" / "belfort" / "preflight.json"

# Default observation universe
_UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "TSLA"]


def run_observation_tick(symbol: Optional[str] = None) -> dict:
    """
    Run a single observation tick.

    Fetches quotes for one symbol (or the first in the universe if not specified),
    appends a record to observation_log.jsonl, and refreshes the preflight snapshot.

    Returns {ok, symbol, data_lane, session_type, bid, ask, mid, logged_at, error}.
    """
    from app.belfort_mode import current_mode
    from app.market_data_feed import get_quote
    from app.market_time import session_type as get_session_type

    target = symbol or _UNIVERSE[0]
    now_str = datetime.now(timezone.utc).isoformat()
    session = get_session_type()

    try:
        quote = get_quote(target)
    except Exception as exc:
        return {"ok": False, "symbol": target, "error": f"quote fetch failed: {exc}"}

    bid        = float(getattr(quote, "bid",       0.0))
    ask        = float(getattr(quote, "ask",       0.0))
    last       = float(getattr(quote, "last",      0.0))
    data_lane  = str(getattr(quote, "data_lane",   "UNKNOWN"))
    mid        = round((bid + ask) / 2.0, 6) if bid > 0 and ask > 0 else 0.0

    mode = current_mode()

    record = {
        "logged_at":   now_str,
        "mode":        mode.value,
        "symbol":      target,
        "session_type": session,
        "data_lane":   data_lane,
        "bid":         bid,
        "ask":         ask,
        "last":        last,
        "mid":         mid,
    }

    try:
        _OBS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _OBS_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass  # non-fatal — observation continues

    # Refresh preflight
    write_preflight_snapshot()

    return {
        "ok":          True,
        "symbol":      target,
        "data_lane":   data_lane,
        "session_type": session,
        "bid":         bid,
        "ask":         ask,
        "mid":         mid,
        "logged_at":   now_str,
        "error":       None,
    }


def write_preflight_snapshot() -> dict:
    """
    Write a fresh preflight snapshot to data/belfort/preflight.json.

    The snapshot is read by observability/belfort_summary.py and surfaced
    through Peter and the UI. It must never import from peter/ or observability/.

    SIP cap rule: if data_lane == "IEX_ONLY", readiness_level is capped at
    OBSERVATION_ONLY regardless of mode.

    Returns the snapshot dict.
    """
    from app.belfort_mode import current_mode, can_advance_to, BelfortMode
    from app.market_data_feed import feed_status
    from app.market_time import session_type as get_session_type

    now_str = datetime.now(timezone.utc).isoformat()
    mode    = current_mode()
    session = get_session_type()

    # Feed status for data_lane and broker environment
    try:
        feed = feed_status()
        data_lane       = str(getattr(feed, "data_lane", "UNKNOWN"))
        broker_env      = str(getattr(feed, "environment", "not_configured"))
        paper_creds     = bool(getattr(feed, "has_credentials", False))
    except Exception:
        data_lane       = "UNKNOWN"
        broker_env      = "not_configured"
        paper_creds     = False

    # Count today's observation ticks
    ticks_today, last_tick_at = _count_today_ticks()

    # ── Readiness calculation ─────────────────────────────────────────────────
    readiness_level, can_advance_to_mode, advancement_blocked_by = _compute_readiness(
        mode        = mode,
        data_lane   = data_lane,
        session     = session,
        paper_creds = paper_creds,
    )

    snapshot = {
        "written_at":           now_str,
        "mode":                 mode.value,
        "broker_environment":   broker_env,
        "paper_credentials":    paper_creds,
        "data_lane":            data_lane,
        "session_type":         session,
        "universe":             _UNIVERSE,
        "readiness_level":      readiness_level,
        "can_advance_to":       can_advance_to_mode,
        "advancement_blocked_by": advancement_blocked_by,
        "observation_ticks_today": ticks_today,
        "last_tick_at":         last_tick_at,
    }

    try:
        _PREFLIGHT.parent.mkdir(parents=True, exist_ok=True)
        _PREFLIGHT.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    except OSError:
        pass

    return snapshot


def _count_today_ticks() -> tuple[int, Optional[str]]:
    """Count observation ticks logged today. Returns (count, last_tick_at_iso)."""
    from datetime import date as _date
    today = _date.today().isoformat()
    if not _OBS_LOG.exists():
        return 0, None
    count     = 0
    last_tick = None
    try:
        for line in _OBS_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts  = rec.get("logged_at", "")
                if ts.startswith(today):
                    count += 1
                    last_tick = ts
            except (json.JSONDecodeError, ValueError):
                continue
    except OSError:
        pass
    return count, last_tick


def _compute_readiness(
    mode:        object,
    data_lane:   str,
    session:     str,
    paper_creds: bool,
) -> tuple[str, Optional[str], Optional[str]]:
    """
    Compute readiness_level, can_advance_to, and advancement_blocked_by.

    Readiness levels (ascending):
        NOT_READY         — no observations or missing prerequisites
        OBSERVATION_ONLY  — can observe only (e.g., IEX data, no paper creds)
        PAPER_READY       — can run paper strategy evaluation
        SHADOW_COMPLETE   — shadow mode completed successfully
        LIVE_ELIGIBLE     — eligible for LIVE (human sign-off still required)

    SIP cap: IEX_ONLY data → cap at OBSERVATION_ONLY.
    """
    from app.belfort_mode import BelfortMode, can_advance_to as _can_advance

    if not isinstance(mode, BelfortMode):
        from app.belfort_mode import current_mode
        mode = current_mode()

    # IEX cap — cannot claim better than OBSERVATION_ONLY on IEX data
    if data_lane == "IEX_ONLY":
        blocked = "IEX_ONLY data lane — SIP required for higher readiness claims"
        if mode == BelfortMode.OBSERVATION:
            next_mode = BelfortMode.SHADOW
            allowed, gate = _can_advance(next_mode)
            if not allowed:
                return "OBSERVATION_ONLY", None, gate
            return "OBSERVATION_ONLY", None, blocked

        # In shadow/paper/live but still on IEX → capped
        return "OBSERVATION_ONLY", None, blocked

    # No credentials at all
    if not paper_creds and data_lane == "UNKNOWN":
        return "NOT_READY", None, "No market data feed configured"

    # OBSERVATION mode
    if mode == BelfortMode.OBSERVATION:
        next_mode = BelfortMode.SHADOW
        allowed, gate = _can_advance(next_mode)
        return "OBSERVATION_ONLY", (next_mode.value if allowed else None), (gate if not allowed else None)

    # SHADOW mode
    if mode == BelfortMode.SHADOW:
        next_mode = BelfortMode.PAPER
        allowed, gate = _can_advance(next_mode)
        return "PAPER_READY", (next_mode.value if allowed else None), (gate if not allowed else None)

    # PAPER mode
    if mode == BelfortMode.PAPER:
        next_mode = BelfortMode.LIVE
        allowed, gate = _can_advance(next_mode)
        return "SHADOW_COMPLETE", (next_mode.value if allowed else None), (gate if not allowed else None)

    # LIVE mode
    if mode == BelfortMode.LIVE:
        return "LIVE_ELIGIBLE", None, None

    return "NOT_READY", None, "Unknown mode"
