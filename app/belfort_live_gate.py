# app/belfort_live_gate.py
#
# Live Readiness Gate — evaluates whether Mr Belfort's paper trading track record
# is sufficient to be considered a candidate for live trading promotion.
#
# READ-ONLY. Never modifies state. Uses paper portfolio, paper exec log, signal log.
#
# Verdicts:
#   not_enough_data — < 10 completed paper sell trades OR < 5 submitted paper orders
#   not_ready       — win_rate < 0.40 OR expectancy <= 0
#   candidate       — metrics acceptable; human sign-off still required before live
#
# Public API:
#   compute_live_readiness() → dict

from __future__ import annotations

import json
import pathlib
from typing import Optional

_ROOT           = pathlib.Path(__file__).resolve().parent.parent
_PAPER_EXEC_LOG = _ROOT / "data" / "belfort" / "paper_exec_log.jsonl"
_SIGNAL_LOG     = _ROOT / "data" / "belfort" / "signal_log.jsonl"

_MIN_TRADES       = 10    # minimum completed paper sell trades
_MIN_PAPER_ORDERS = 5     # minimum submitted Alpaca paper orders (all-time)
_MIN_WIN_RATE     = 0.40  # win rate threshold for not_ready verdict


def compute_live_readiness() -> dict:
    """
    Evaluate paper trading readiness for live promotion.

    Returns:
        verdict:      "not_enough_data" | "not_ready" | "candidate"
        trade_count:  int         — completed paper sell trades
        paper_orders: int         — submitted Alpaca paper orders (all-time)
        win_rate:     float|None  — wins / sell trades
        expectancy:   float|None  — avg P&L per completed sell trade
        block_rate:   float|None  — fraction of signals blocked by risk (all-time)
        note:         str         — human-readable explanation of verdict
    """
    # ── Paper portfolio trade record ──────────────────────────────────────────
    trade_count = 0
    win_rate:   Optional[float] = None
    expectancy: Optional[float] = None
    try:
        from app.portfolio import get_trades
        trades = get_trades()
        sells  = [t for t in trades if t.get("side") == "SELL"]
        trade_count = len(sells)
        if sells:
            wins       = sum(1 for t in sells if t.get("pnl", 0) > 0)
            win_rate   = round(wins / len(sells), 3)
            expectancy = round(sum(t.get("pnl", 0) for t in sells) / len(sells), 2)
    except Exception:
        pass

    # ── Alpaca paper order submission count (all-time) ────────────────────────
    paper_orders = 0
    try:
        if _PAPER_EXEC_LOG.exists():
            for line in _PAPER_EXEC_LOG.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("execution_status") == "submitted":
                        paper_orders += 1
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception:
        pass

    # ── Signal block rate (all-time) ──────────────────────────────────────────
    block_rate: Optional[float] = None
    try:
        if _SIGNAL_LOG.exists():
            total_sig = 0
            blocked   = 0
            for line in _SIGNAL_LOG.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("skipped"):
                        continue
                    total_sig += 1
                    if not rec.get("risk_can_proceed", True):
                        blocked += 1
                except (json.JSONDecodeError, ValueError):
                    continue
            if total_sig > 0:
                block_rate = round(blocked / total_sig, 3)
    except Exception:
        pass

    # ── Verdict ───────────────────────────────────────────────────────────────
    if trade_count < _MIN_TRADES or paper_orders < _MIN_PAPER_ORDERS:
        verdict = "not_enough_data"
        note = (
            f"Need at least {_MIN_TRADES} completed paper sell trades and "
            f"{_MIN_PAPER_ORDERS} paper orders submitted. "
            f"Have: {trade_count} trade(s), {paper_orders} order(s)."
        )
    elif win_rate is not None and win_rate < _MIN_WIN_RATE:
        verdict = "not_ready"
        note = (
            f"Win rate {int(win_rate * 100)}% is below the {int(_MIN_WIN_RATE * 100)}% threshold. "
            "More paper trading needed before live consideration."
        )
    elif expectancy is not None and expectancy <= 0:
        verdict = "not_ready"
        note = (
            f"Expectancy ${expectancy:.2f}/trade is not positive. "
            "Strategy must show positive edge before live consideration."
        )
    else:
        verdict = "candidate"
        note = (
            "Metrics acceptable. Human sign-off required before advancing to live. "
            "This is a readiness signal only \u2014 not a go-ahead recommendation."
        )

    return {
        "verdict":      verdict,
        "trade_count":  trade_count,
        "paper_orders": paper_orders,
        "win_rate":     win_rate,
        "expectancy":   expectancy,
        "block_rate":   block_rate,
        "note":         note,
    }
