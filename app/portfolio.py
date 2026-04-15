# app/portfolio.py

import json
import pathlib
from datetime import datetime
from typing import Dict, List

DATA_DIR = pathlib.Path("data")
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"

# --- State ---
cash: float = 100_000.0
positions: Dict[str, dict] = {}      # {symbol: {"qty": float, "avg_cost": float}}
realized_pnl: float = 0.0
trade_history: List[dict] = []
market_prices: Dict[str, float] = {} # last known market price per symbol


# --- Functions ---

def set_market_price(symbol: str, price: float) -> None:
    """Update the current market price for a symbol (used for unrealized P&L)."""
    market_prices[symbol] = price


def record_trade(symbol: str, side: str, qty: float, price: float) -> dict:
    global cash, realized_pnl

    # Guard: never sell more than the current position
    if side == "SELL" and symbol in positions:
        qty = min(qty, positions[symbol]["qty"])

    pnl = update_position(symbol, side, qty, price)

    if side == "BUY":
        cash -= qty * price
    elif side == "SELL":
        cash += qty * price
        realized_pnl += pnl

    trade = {
        "timestamp": datetime.utcnow().isoformat(),
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "pnl": round(pnl, 2),
    }

    trade_history.append(trade)
    save_state()
    return trade


def update_position(symbol: str, side: str, qty: float, price: float) -> float:
    global positions

    if symbol not in positions:
        positions[symbol] = {"qty": 0.0, "avg_cost": 0.0}

    pos = positions[symbol]
    pnl = 0.0

    if side == "BUY":
        total_cost = pos["avg_cost"] * pos["qty"] + price * qty
        pos["qty"] += qty
        pos["avg_cost"] = total_cost / pos["qty"]

    elif side == "SELL":
        pnl = (price - pos["avg_cost"]) * qty
        pos["qty"] -= qty
        if pos["qty"] <= 0:
            del positions[symbol]

    return pnl


def get_snapshot() -> dict:
    unrealized = sum(
        (market_prices.get(sym, pos["avg_cost"]) - pos["avg_cost"]) * pos["qty"]
        for sym, pos in positions.items()
    )
    return {
        "cash": round(cash, 2),
        "positions": positions.copy(),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized, 2),
        "trade_count": len(trade_history),
    }


def get_trades(limit: int | None = None) -> list:
    """
    Return trade history, optionally capped to the most recent `limit` trades.
    """
    if limit is None:
        return trade_history.copy()
    if limit <= 0:
        return []
    return trade_history[-limit:].copy()


def save_state() -> None:
    """Persist portfolio state to disk."""
    DATA_DIR.mkdir(exist_ok=True)
    state = {
        "cash": cash,
        "positions": positions,
        "realized_pnl": realized_pnl,
        "trade_history": trade_history,
        "market_prices": market_prices,
    }
    PORTFOLIO_FILE.write_text(json.dumps(state, indent=2))


def load_state() -> None:
    """Restore portfolio state from disk if a snapshot exists."""
    global cash, positions, realized_pnl, trade_history, market_prices
    if not PORTFOLIO_FILE.exists():
        return
    state = json.loads(PORTFOLIO_FILE.read_text())
    cash = state.get("cash", cash)
    positions = state.get("positions", positions)
    realized_pnl = state.get("realized_pnl", realized_pnl)
    trade_history = state.get("trade_history", trade_history)
    market_prices = state.get("market_prices", market_prices)


def reset_portfolio(reason: str = "") -> dict:
    """Reset portfolio to baseline: $100k cash, no positions, no trade history."""
    global cash, positions, realized_pnl, trade_history
    cash = 100_000.0
    positions = {}
    realized_pnl = 0.0
    trade_history = []
    # market_prices preserved — external reference data, not part of the reset
    save_state()
    return {
        "reset": True,
        "cash": cash,
        "realized_pnl": 0.0,
        "trade_count": 0,
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat(),
    }


# Restore state on import
load_state()
