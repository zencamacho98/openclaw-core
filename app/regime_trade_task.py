# app/regime_trade_task.py
#
# Regime-aware simulated trading task.
# Drop-in alternative to mock_trade_spy that routes signals through the
# regime detector instead of always using MA crossover.
#
# Registered in tasks.py as "regime_trade_spy".
# Risk management (stop-loss, take-profit, cooldown) is identical to
# mock_trade_spy — only the signal source changes.

import random
from app.portfolio import record_trade, get_snapshot, set_market_price
from app.strategy.router import record_price, get_signal, get_state as router_state
from app.strategy.simple_strategy import get_position_qty, check_take_profit
from app.strategy.mean_reversion import (
    compute_position_size  as mr_position_size,
    compute_dynamic_stop   as mr_dynamic_stop,
)
from app.strategy.config import get_config

SYMBOL = "SPY"

_sim_price:       float       = 525.0
_tick:            int         = 0
_last_trade_tick: int         = -9999
_mr_stop_pct:     float | None = None   # dynamic stop for the current MR position


def regime_trade_spy():
    """
    Simulated trading task with regime-aware signal routing.

    Price feed:    random walk — identical to mock_trade_spy
    Signal source: router.get_signal() → MA crossover (trending) or
                   mean reversion (ranging) based on Efficiency Ratio
    Risk control:  stop-loss and take-profit checked first (same as mock_trade_spy)
    """
    global _sim_price, _tick, _last_trade_tick, _mr_stop_pct

    _tick += 1

    _sim_price = round(_sim_price + random.uniform(-3.0, 3.0), 2)
    _sim_price = max(480.0, min(580.0, _sim_price))

    set_market_price(SYMBOL, _sim_price)
    record_price(SYMBOL, _sim_price)   # feeds both sub-strategies

    cfg         = get_config()
    cooldown    = int(cfg.get("TRADE_COOLDOWN", 0))
    in_cooldown = cooldown > 0 and (_tick - _last_trade_tick) <= cooldown

    snapshot     = get_snapshot()
    has_position = SYMBOL in snapshot["positions"]

    # ── Risk management overrides ──────────────────────────────────────────────
    if has_position and not in_cooldown:
        pos   = snapshot["positions"][SYMBOL]
        entry = pos["avg_cost"]
        qty   = pos["qty"]

        # Use stored dynamic stop for MR positions; fall back to config stop
        eff_stop = _mr_stop_pct if _mr_stop_pct is not None else cfg.get("STOP_LOSS_PCT", 0.02)
        if eff_stop > 0 and _sim_price < entry * (1 - eff_stop):
            trade = record_trade(SYMBOL, "SELL", qty, _sim_price)
            _mr_stop_pct     = None
            _last_trade_tick = _tick
            print(f"[STOP-LOSS/REGIME]   SELL {qty} @ ${_sim_price} "
                  f"(entry=${entry:.2f} stop={eff_stop:.2%})")
            return {**trade, "trigger": "stop_loss"}

        if check_take_profit(_sim_price, entry):
            trade = record_trade(SYMBOL, "SELL", qty, _sim_price)
            _mr_stop_pct     = None
            _last_trade_tick = _tick
            print(f"[TAKE-PROFIT/REGIME] SELL {qty} @ ${_sim_price} (entry=${entry:.2f})")
            return {**trade, "trigger": "take_profit"}

    # ── Regime-routed signal ───────────────────────────────────────────────────
    state  = router_state(SYMBOL)
    signal = state["signal"]
    active = state["active_strategy"]
    reg    = state["regime"]

    print(f"[REGIME/{active}] signal={signal} price=${_sim_price} regime={reg} "
          f"er={state.get('efficiency_ratio')}")

    if signal == "BUY" and not has_position and not in_cooldown:
        if active == "mean_reversion":
            qty          = mr_position_size(SYMBOL, _sim_price, snapshot["cash"])
            _mr_stop_pct = mr_dynamic_stop(SYMBOL, _sim_price)   # set dynamic stop at entry
        else:
            qty          = get_position_qty(_sim_price, snapshot["cash"])
            _mr_stop_pct = None                                   # use config stop
        if qty > 0:
            trade = record_trade(SYMBOL, "BUY", qty, _sim_price)
            _last_trade_tick = _tick
            print(f"[MOCK TRADE/REGIME] BUY {qty} @ ${_sim_price} "
                  f"({'dyn-stop' if _mr_stop_pct else 'fixed-stop'})")
            return {**trade, "strategy": active}

    elif signal == "SELL" and has_position and not in_cooldown:
        qty          = snapshot["positions"][SYMBOL]["qty"]
        trade        = record_trade(SYMBOL, "SELL", qty, _sim_price)
        _mr_stop_pct = None
        _last_trade_tick = _tick
        print(f"[MOCK TRADE/REGIME] SELL {qty} @ ${_sim_price}")
        return {**trade, "strategy": active}

    return {"signal": signal, "action": "hold", "price": _sim_price,
            "regime": reg, "strategy": active}
