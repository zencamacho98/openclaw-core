# app/report.py

from app.portfolio import get_snapshot, get_trades, market_prices


def compute_report() -> dict:
    """Summarise simulated trading performance from current portfolio state."""
    snapshot = get_snapshot()
    trades = get_trades()

    sells = [t for t in trades if t["side"] == "SELL"]
    wins = [t for t in sells if t["pnl"] > 0]

    avg_pnl = sum(t["pnl"] for t in sells) / len(sells) if sells else 0.0
    best = max(sells, key=lambda t: t["pnl"], default=None)
    worst = min(sells, key=lambda t: t["pnl"], default=None)

    position_value = sum(
        market_prices.get(sym, pos["avg_cost"]) * pos["qty"]
        for sym, pos in snapshot["positions"].items()
    )

    return {
        "total_trades": len(trades),
        "total_buys": len([t for t in trades if t["side"] == "BUY"]),
        "total_sells": len(sells),
        "win_rate": round(len(wins) / len(sells), 4) if sells else 0.0,
        "avg_pnl_per_sell": round(avg_pnl, 2),
        "total_realized_pnl": snapshot["realized_pnl"],
        "unrealized_pnl": snapshot["unrealized_pnl"],
        "best_trade_pnl": round(best["pnl"], 2) if best else 0.0,
        "worst_trade_pnl": round(worst["pnl"], 2) if worst else 0.0,
        "cash": snapshot["cash"],
        "portfolio_value": round(snapshot["cash"] + position_value, 2),
    }
