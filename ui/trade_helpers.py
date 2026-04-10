# ui/trade_helpers.py
#
# Pure helpers for formatting trading activity data in the Mr Belfort tab.
# No Streamlit imports. Safe to unit-test directly.
#
# Public API:
#   format_pnl(value)                                          -> str
#   format_trade_row(trade)                                    -> dict
#   trading_status_summary(is_trading, trading_state, trades)  -> str

from __future__ import annotations


def format_pnl(value: float) -> str:
    """Format a P&L float as a signed dollar string."""
    if value > 0:
        return f"+${value:,.2f}"
    if value < 0:
        return f"-${abs(value):,.2f}"
    return "$0.00"


def format_trade_row(trade: dict) -> dict:
    """
    Format one trade dict into a display row suitable for st.dataframe.

    Input keys expected: timestamp, side, qty, price, pnl.
    All keys are optional — missing values render as "?".
    """
    ts  = trade.get("timestamp", "")
    time_str = ts[11:19] if len(ts) >= 19 else (ts[:8] if ts else "?")
    pnl  = float(trade.get("pnl", 0.0))
    side = trade.get("side", "?")
    return {
        "Time":   time_str,
        "Side":   side,
        "Qty":    trade.get("qty", 0),
        "Price":  f"${float(trade.get('price', 0)):,.2f}",
        "P&L":    format_pnl(pnl),
        "Result": "Win" if pnl > 0 else ("Loss" if pnl < 0 else "Flat"),
    }


def trading_status_summary(
    is_trading: bool,
    trading_state: dict | None,
    trades: list | None,
) -> str:
    """
    Return a plain-English one-liner about paper trading status.

    Parameters
    ----------
    is_trading     Whether the mock trading loop is currently running.
    trading_state  Dict from /monitor/trading/status — may include ticks, interval.
    trades         List of trade dicts from /monitor/trades (may be None or empty).
    """
    if not is_trading:
        return "Paper trading is off."
    ticks    = (trading_state or {}).get("ticks", 0)
    interval = (trading_state or {}).get("interval", "?")
    n_trades = len(trades or [])
    if n_trades == 0:
        return (
            f"Paper trading is running ({ticks} ticks · {interval}s interval) "
            "— no trades executed yet."
        )
    wins   = sum(1 for t in (trades or []) if float(t.get("pnl", 0)) > 0)
    losses = sum(1 for t in (trades or []) if float(t.get("pnl", 0)) < 0)
    return (
        f"Paper trading active — {n_trades} trade(s) · "
        f"{wins} win(s) · {losses} loss(es) · {ticks} ticks run"
    )
