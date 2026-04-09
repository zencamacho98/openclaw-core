import random
from app.portfolio import record_trade, get_snapshot, set_market_price
from app.strategy.simple_strategy import (
    record_price, get_signal,
    get_position_qty, check_stop_loss, check_take_profit,
)
from app.strategy.config import get_config

SYMBOL = "SPY"

# Random walk price state — randomness is only in the *price feed*, not the decision.
_sim_price: float = 525.0
_tick: int = 0
_last_trade_tick: int = -9999   # far in the past so first trade is never blocked


def mock_trade_spy():
    """
    Simulated trading task wired to the MA crossover strategy.

    Price feed:   random walk (provides varied input data)
    Decisions:    simple_strategy — fully deterministic given price history
    Risk control: stop-loss and take-profit checked before MA signal
    Execution:    record_trade() writes to portfolio
    """
    global _sim_price, _tick, _last_trade_tick

    _tick += 1

    # Advance simulated price — bounded random walk
    _sim_price = round(_sim_price + random.uniform(-3.0, 3.0), 2)
    _sim_price = max(480.0, min(580.0, _sim_price))

    # Feed price to strategy and portfolio market price tracker
    set_market_price(SYMBOL, _sim_price)
    record_price(SYMBOL, _sim_price)

    cfg = get_config()
    cooldown = int(cfg.get("TRADE_COOLDOWN", 0))
    in_cooldown = cooldown > 0 and (_tick - _last_trade_tick) <= cooldown

    snapshot = get_snapshot()
    has_position = SYMBOL in snapshot["positions"]

    # ── Risk management overrides (stop-loss / take-profit) ────────────────────
    # These fire before the MA signal so they always protect capital.
    if has_position and not in_cooldown:
        pos = snapshot["positions"][SYMBOL]
        entry_price = pos["avg_cost"]
        qty = pos["qty"]

        if check_stop_loss(_sim_price, entry_price):
            trade = record_trade(SYMBOL, "SELL", qty, _sim_price)
            _last_trade_tick = _tick
            print(f"[STOP-LOSS]   SELL {qty} @ ${_sim_price} (entry=${entry_price:.2f})")
            return {**trade, "trigger": "stop_loss"}

        if check_take_profit(_sim_price, entry_price):
            trade = record_trade(SYMBOL, "SELL", qty, _sim_price)
            _last_trade_tick = _tick
            print(f"[TAKE-PROFIT] SELL {qty} @ ${_sim_price} (entry=${entry_price:.2f})")
            return {**trade, "trigger": "take_profit"}

    # ── MA crossover signal ────────────────────────────────────────────────────
    signal = get_signal(SYMBOL)
    print(f"[STRATEGY] signal={signal} price=${_sim_price} has_position={has_position}")

    if signal == "BUY" and not has_position and not in_cooldown:
        qty = get_position_qty(_sim_price, snapshot["cash"])
        if qty > 0:
            trade = record_trade(SYMBOL, "BUY", qty, _sim_price)
            _last_trade_tick = _tick
            print(f"[MOCK TRADE] BUY {qty} @ ${_sim_price}")
            return trade

    elif signal == "SELL" and has_position and not in_cooldown:
        qty = snapshot["positions"][SYMBOL]["qty"]
        trade = record_trade(SYMBOL, "SELL", qty, _sim_price)
        _last_trade_tick = _tick
        print(f"[MOCK TRADE] SELL {qty} @ ${_sim_price}")
        return trade

    result = {"signal": signal, "action": "hold", "price": _sim_price}
    print(f"[MOCK TRADE] HOLD — no action taken")
    return result
