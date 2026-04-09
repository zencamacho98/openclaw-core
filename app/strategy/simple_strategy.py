# app/strategy/simple_strategy.py
#
# Simple moving average crossover strategy.
# Deterministic: given the same price history, always produces the same signal.
#
# Logic:
#   - Track a SHORT_WINDOW and LONG_WINDOW moving average per symbol.
#   - BUY  when short MA crosses above long MA (recent momentum up).
#   - SELL when short MA crosses below long MA (recent momentum down).
#   - HOLD when MAs are equal or not enough data has accumulated.

from typing import Dict, List

from app.strategy.config import get_config

# Module-level defaults — kept for any code that imports these directly.
# Strategy functions always read live values from config at call time.
SHORT_WINDOW = 3
LONG_WINDOW = 7

# Per-symbol price history — populated by record_price() on every tick.
_price_history: Dict[str, List[float]] = {}


def _windows() -> tuple[int, int]:
    """Return (SHORT_WINDOW, LONG_WINDOW) from live config."""
    cfg = get_config()
    return cfg["SHORT_WINDOW"], cfg["LONG_WINDOW"]


def record_price(symbol: str, price: float) -> None:
    """Append a new price observation. Trims history beyond what is needed."""
    _, long_window = _windows()
    if symbol not in _price_history:
        _price_history[symbol] = []
    _price_history[symbol].append(price)
    # Retain 2× LONG_WINDOW so MAs are stable without unbounded growth
    max_keep = long_window * 2
    if len(_price_history[symbol]) > max_keep:
        _price_history[symbol] = _price_history[symbol][-max_keep:]


def get_signal(symbol: str) -> str:
    """Return BUY, SELL, or HOLD based on MA crossover with signal-strength filter.

    The gap filter (MIN_SIGNAL_GAP) suppresses trades when the short and long MAs
    are close together — i.e. the market is ranging rather than trending.
    """
    cfg          = get_config()
    short_window = cfg["SHORT_WINDOW"]
    long_window  = cfg["LONG_WINDOW"]
    min_gap      = float(cfg.get("MIN_SIGNAL_GAP", 0.0))

    history = _price_history.get(symbol, [])
    if len(history) < long_window:
        return "HOLD"  # warm-up period: not enough data

    short_ma = sum(history[-short_window:]) / short_window
    long_ma  = sum(history[-long_window:])  / long_window

    if abs(short_ma - long_ma) <= min_gap:
        return "HOLD"  # signal too weak — gap below threshold

    if short_ma > long_ma:
        return "BUY"
    elif short_ma < long_ma:
        return "SELL"
    return "HOLD"


def get_position_qty(price: float, cash: float) -> float:
    """Return shares to buy: POSITION_SIZE fraction of available cash."""
    if price <= 0 or cash <= 0:
        return 0.0
    cfg = get_config()
    return round(cash * cfg["POSITION_SIZE"] / price, 4)


def check_stop_loss(current_price: float, entry_price: float) -> bool:
    """Return True if current price has fallen below the stop-loss threshold."""
    if entry_price <= 0:
        return False
    cfg = get_config()
    return current_price < entry_price * (1 - cfg["STOP_LOSS_PCT"])


def check_take_profit(current_price: float, entry_price: float) -> bool:
    """Return True if current price has risen above the take-profit threshold.
    Returns False when TAKE_PROFIT_PCT is 0 (feature disabled).
    """
    if entry_price <= 0:
        return False
    cfg = get_config()
    tp = cfg["TAKE_PROFIT_PCT"]
    return tp > 0 and current_price >= entry_price * (1 + tp)


def get_state(symbol: str) -> dict:
    """Return strategy internals for monitoring and debugging."""
    cfg          = get_config()
    short_window = cfg["SHORT_WINDOW"]
    long_window  = cfg["LONG_WINDOW"]
    min_gap      = float(cfg.get("MIN_SIGNAL_GAP", 0.0))

    history = _price_history.get(symbol, [])
    n = len(history)

    short_ma = round(sum(history[-short_window:]) / short_window, 2) if n >= short_window else None
    long_ma  = round(sum(history[-long_window:])  / long_window, 2)  if n >= long_window  else None

    signal_gap = round(abs(short_ma - long_ma), 4) if short_ma is not None and long_ma is not None else None

    return {
        "symbol":          symbol,
        "price_count":     n,
        "short_window":    short_window,
        "long_window":     long_window,
        "min_signal_gap":  min_gap,
        "short_ma":        short_ma,
        "long_ma":         long_ma,
        "signal_gap":      signal_gap,
        "gap_sufficient":  signal_gap is not None and signal_gap > min_gap,
        "signal":          get_signal(symbol),
        "warmed_up":       n >= long_window,
    }
