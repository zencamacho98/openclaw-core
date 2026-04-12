# app/belfort_regime_learning.py
#
# Regime-separated learning snapshots for Belfort.
#
# Market regimes:
#   "regular"    — NYSE regular hours; paper trading active
#   "closed_sim" — Market closed or extended hours; sim practice only
#   "extended"   — Pre/after hours (paper NOT supported — honest label)
#
# Auto-snapshot: called from trading_loop every N ticks.
# Writes to data/learning_history.jsonl (same append-only schema).
#
# Public API:
#   compute_regime_metrics()              → dict
#   current_strategy_profile()           → dict
#   maybe_record_regime_snapshot(tick)   → bool   (True if snapshot written)

from __future__ import annotations

import json
import pathlib
from datetime import date, datetime, timezone

_ROOT             = pathlib.Path(__file__).resolve().parent.parent
_PAPER_EXEC_LOG   = _ROOT / "data" / "belfort" / "paper_exec_log.jsonl"
_SIM_LOG          = _ROOT / "data" / "belfort" / "sim_log.jsonl"
_LEARNING_HISTORY = _ROOT / "data" / "learning_history.jsonl"

# Minimum ticks between auto-snapshots (prevents spamming history file)
_MIN_TICKS_BETWEEN_SNAPSHOTS = 20

_last_snapshot_tick: int = 0


def compute_regime_metrics(today_only: bool = True) -> dict:
    """
    Compute per-regime learning metrics from paper_exec_log and sim_log.

    Returns:
        regular:    dict — {submitted, gated, errored, total}
        closed_sim: dict — {fills, buys, sells, holds, ticks}
        extended:   str  — "not_supported"
    """
    today = date.today().isoformat() if today_only else None
    return {
        "regular":    _paper_metrics(today),
        "closed_sim": _sim_metrics(today),
        "extended":   "not_supported",
    }


def _paper_metrics(today: str | None) -> dict:
    stats = {"submitted": 0, "gated": 0, "errored": 0, "total": 0}
    if not _PAPER_EXEC_LOG.exists():
        return stats
    try:
        for line in _PAPER_EXEC_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if today and not rec.get("written_at", "").startswith(today):
                continue
            stats["total"] += 1
            status = rec.get("execution_status", "")
            if status == "submitted":
                stats["submitted"] += 1
            elif status == "gated":
                stats["gated"] += 1
            elif status in ("broker_error", "error"):
                stats["errored"] += 1
    except Exception:
        pass
    return stats


def _sim_metrics(today: str | None) -> dict:
    stats = {"fills": 0, "buys": 0, "sells": 0, "holds": 0, "ticks": 0}
    if not _SIM_LOG.exists():
        return stats
    try:
        for line in _SIM_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if today and not rec.get("written_at", "").startswith(today):
                continue
            stats["ticks"] += 1
            action = rec.get("action", "hold")
            if action == "buy":
                stats["buys"]  += 1
                stats["fills"] += 1
            elif action == "sell":
                stats["sells"] += 1
                stats["fills"] += 1
            else:
                stats["holds"] += 1
    except Exception:
        pass
    return stats


def current_strategy_profile() -> dict:
    """
    Plain-English summary of the strategy's current regime fitness.

    Returns:
        current_regime:  str — actual market session type from market_time
        paper_regime:    "regular"
        sim_regime:      "closed_sim"
        regime_metrics:  dict from compute_regime_metrics()
        fitness_regular: str — human note for regular-hours paper performance
        fitness_sim:     str — human note for sim/closed performance
        extended_hours:  "not_supported"
    """
    try:
        from app.market_time import session_type as _st
        cur = _st()
    except Exception:
        cur = "unknown"

    metrics = compute_regime_metrics()
    reg     = metrics["regular"]
    sim     = metrics["closed_sim"]

    if reg["total"] == 0:
        fitness_regular = "No paper data today — run paper trading during regular hours."
    elif reg["submitted"] > 0:
        fitness_regular = f"{reg['submitted']} paper order(s) submitted, {reg['gated']} gated today."
    else:
        fitness_regular = f"{reg['gated']} paper order(s) gated today — no submissions."

    if sim["ticks"] == 0:
        fitness_sim = "No sim data today — run Practice Sim to collect closed-market data."
    elif sim["fills"] > 0:
        fitness_sim = f"{sim['fills']} sim fill(s) today ({sim['buys']} buy, {sim['sells']} sell)."
    else:
        fitness_sim = f"{sim['ticks']} sim tick(s) today — no fills yet."

    return {
        "current_regime":  cur,
        "paper_regime":    "regular",
        "sim_regime":      "closed_sim",
        "regime_metrics":  metrics,
        "fitness_regular": fitness_regular,
        "fitness_sim":     fitness_sim,
        "extended_hours":  "not_supported",
    }


# ── Auto-snapshot ─────────────────────────────────────────────────────────────

def maybe_record_regime_snapshot(current_tick: int) -> bool:
    """
    Write a regime snapshot to learning_history.jsonl if enough ticks
    have passed since the last snapshot.

    Called from trading_loop._run_regime_snapshot() on a tick cadence.
    Returns True if a snapshot was written. Never raises.
    """
    global _last_snapshot_tick
    if current_tick - _last_snapshot_tick < _MIN_TICKS_BETWEEN_SNAPSHOTS:
        return False
    try:
        _write_regime_snapshot()
        _last_snapshot_tick = current_tick
        return True
    except Exception:
        return False


def _write_regime_snapshot() -> None:
    """Build and append a regime snapshot to learning_history.jsonl."""
    try:
        from app.market_time import session_type as _st
        cur_regime = _st()
    except Exception:
        cur_regime = "unknown"

    metrics = compute_regime_metrics()
    reg     = metrics["regular"]
    sim     = metrics["closed_sim"]

    # Derive simple verdict from available regime data
    if cur_regime == "regular":
        if reg["total"] == 0:
            verdict, fit = "research", "warming_up"
        elif reg["submitted"] > 0:
            verdict, fit = "continue", "active"
        else:
            verdict, fit = "monitor", "gated"
    else:
        if sim["fills"] > 0:
            verdict, fit = "continue", "active"
        elif sim["ticks"] > 0:
            verdict, fit = "monitor", "warming_up"
        else:
            verdict, fit = "research", "no_data"

    entry = {
        "written_at":     datetime.now(timezone.utc).isoformat(),
        "snapshot_type":  "auto_regime",
        "market_regime":  cur_regime,
        "regime":         cur_regime,
        "regime_fit":     fit,
        "verdict":        verdict,
        "regime_metrics": {
            "regular":    reg,
            "closed_sim": sim,
        },
    }
    _LEARNING_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with _LEARNING_HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
