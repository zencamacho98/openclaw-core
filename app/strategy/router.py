# app/strategy/router.py
#
# Regime-aware strategy router.
#
# Detects the current market regime on every call and dispatches to:
#   trending → simple_strategy  (MA crossover)
#   ranging  → mean_reversion
#
# The caller should use router.record_price() and router.get_signal() rather
# than calling the sub-strategies directly. Both strategies receive every price
# tick so they are always warmed up and ready to switch.

from app.strategy import regime as _regime
from app.strategy import simple_strategy as _ma
from app.strategy import mean_reversion as _mr


def record_price(symbol: str, price: float) -> None:
    """Feed a new price to both sub-strategies."""
    _ma.record_price(symbol, price)
    _mr.record_price(symbol, price)


def get_signal(symbol: str) -> str:
    """
    Detect the current regime and return the signal from the appropriate strategy.
    """
    prices        = _ma._price_history.get(symbol, [])
    current_regime = _regime.detect(prices)

    if current_regime == _regime.TRENDING:
        return _ma.get_signal(symbol)
    return _mr.get_signal(symbol)


def get_state(symbol: str) -> dict:
    """Return combined state for monitoring: regime, ER, and both sub-strategy states."""
    prices         = _ma._price_history.get(symbol, [])
    current_regime = _regime.detect(prices)
    er             = _regime.efficiency_ratio(prices)

    return {
        "symbol":            symbol,
        "regime":            current_regime,
        "efficiency_ratio":  er,
        "active_strategy":   "ma_crossover" if current_regime == _regime.TRENDING else "mean_reversion",
        "signal":            get_signal(symbol),
        "ma_crossover":      _ma.get_state(symbol),
        "mean_reversion":    _mr.get_state(symbol),
    }
