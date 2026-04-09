# app/strategy/mean_reversion.py
#
# Mean reversion strategy for ranging markets.
#
# Logic:
#   - Maintain a rolling window of recent prices.
#   - Compute the mean and standard deviation.
#   - BUY  when price drops below (mean - threshold * std).
#   - SELL when price returns to the mean.
#   - HOLD otherwise.
#
# Intended for use in ranging markets where the MA crossover produces noise.
# All functions are deterministic: same history → same output.

import math
from app.strategy.config import get_config

# Per-symbol price history — independent of simple_strategy's history.
_price_history: dict[str, list[float]] = {}


def _compute_er(history: list[float], window: int) -> float:
    """
    Kaufman Efficiency Ratio over the last window+1 prices.
    ER ∈ [0, 1]: 0 = perfectly choppy, 1 = perfectly directional.
    Returns 0.0 when there is insufficient history (safe default: permits MR entry).
    """
    if len(history) < window + 1:
        return 0.0
    recent     = history[-(window + 1):]
    net_move   = abs(recent[-1] - recent[0])
    total_path = sum(abs(recent[i] - recent[i - 1]) for i in range(1, len(recent)))
    return net_move / total_path if total_path > 0 else 0.0


def _atr(history: list[float], window: int) -> float:
    """ATR proxy: SMA of |price[t] - price[t-1]| over last `window` bars. Returns 0 if too short."""
    if len(history) < window + 1:
        return 0.0
    return sum(abs(history[i] - history[i - 1]) for i in range(-window, 0)) / window


def record_price(symbol: str, price: float) -> None:
    """Append a price observation, trim to MEAN_REV_WINDOW * 2."""
    cfg = get_config()
    max_keep = int(cfg.get("MEAN_REV_WINDOW", 20)) * 2
    if symbol not in _price_history:
        _price_history[symbol] = []
    _price_history[symbol].append(price)
    if len(_price_history[symbol]) > max_keep:
        _price_history[symbol] = _price_history[symbol][-max_keep:]


def get_signal(symbol: str) -> str:
    """Return BUY, SELL, or HOLD based on mean reversion."""
    cfg              = get_config()
    window           = int(cfg.get("MEAN_REV_WINDOW", 20))
    threshold        = float(cfg.get("MEAN_REV_THRESHOLD", 1.0))
    exit_fraction    = float(cfg.get("MEAN_REV_EXIT_FRACTION", 1.0))
    min_vol          = float(cfg.get("MIN_VOLATILITY", 0.0))
    min_entry_depth  = float(cfg.get("MIN_ENTRY_DEPTH", 0.0))
    max_er           = float(cfg.get("MAX_EFFICIENCY_RATIO", 1.0))

    history = _price_history.get(symbol, [])
    if len(history) < window:
        return "HOLD"

    recent = history[-window:]
    mean   = sum(recent) / window
    std    = math.sqrt(sum((p - mean) ** 2 for p in recent) / window)

    if std == 0.0:
        return "HOLD"

    current     = history[-1]
    lower_band  = mean - threshold * std
    exit_target = mean - (1.0 - exit_fraction) * threshold * std

    # Low-volatility filter: suppress entries, still allow exits
    low_vol = (min_vol > 0.0 and std < min_vol)

    if not low_vol and current <= lower_band:
        depth_val = (lower_band - current) / std   # >= 0 here
        if depth_val >= min_entry_depth:
            # Market condition filter: skip if price action is too directional
            er = _compute_er(history, window)
            if er <= max_er:
                return "BUY"
            # Regime gate fired: price is stretched but market is trending — log it
            try:
                from app.logger import log
                log(f"[MR] Regime gate blocked entry: ER={er:.3f} > max_er={max_er:.3f}")
            except Exception:
                pass
    if current >= exit_target:
        return "SELL"
    return "HOLD"


def compute_dynamic_stop(symbol: str, entry_price: float) -> float:
    """
    Compute the stop loss pct for a mean reversion entry.

    Priority:
      1. STOP_ATR_MULT > 0 → stop_pct = ATR * mult / entry_price
      2. MEAN_REV_STOP_VOL_MULT > 0 → stop_pct = (std / entry_price) * vol_mult
      3. fallback → STOP_LOSS_PCT

    All results are floored at MIN_STOP_LOSS_PCT.
    """
    cfg      = get_config()
    fallback = float(cfg.get("STOP_LOSS_PCT", 0.02))
    min_stop = float(cfg.get("MIN_STOP_LOSS_PCT", 0.01))
    history  = _price_history.get(symbol, [])

    if entry_price <= 0:
        return fallback

    # ATR-based stop takes precedence
    atr_mult = float(cfg.get("STOP_ATR_MULT", 0.0))
    if atr_mult > 0.0:
        atr_w = int(cfg.get("ATR_WINDOW", 14))
        atr   = _atr(history, atr_w)
        if atr > 0.0:
            return max(min_stop, atr * atr_mult / entry_price)

    # Vol-mult (std-based) stop
    vol_mult = float(cfg.get("MEAN_REV_STOP_VOL_MULT", 0.0))
    if vol_mult > 0.0:
        window = int(cfg.get("MEAN_REV_WINDOW", 20))
        if len(history) >= window:
            recent = history[-window:]
            mean   = sum(recent) / window
            std    = math.sqrt(sum((p - mean) ** 2 for p in recent) / window)
            if std > 0.0:
                return max(min_stop, (std / entry_price) * vol_mult)

    return fallback


def compute_position_size(symbol: str, price: float, cash: float) -> float:
    """
    Return the number of shares to buy for a mean reversion entry.

    Priority:
      1. RISK_PER_TRADE_PCT > 0 → shares = cash * risk_pct / stop_distance
      2. MEAN_REV_SIZE_MULTIPLIER > 0 → size scales with signal depth
      3. fallback → POSITION_SIZE fraction of cash

    All results are capped at MAX_POSITION_SIZE fraction of cash.
    """
    if price <= 0 or cash <= 0:
        return 0.0

    cfg      = get_config()
    max_frac = float(cfg.get("MAX_POSITION_SIZE", 0.5))

    # Risk-per-trade sizing: overrides both fixed and dynamic sizing
    risk_pct = float(cfg.get("RISK_PER_TRADE_PCT", 0.0))
    if risk_pct > 0.0:
        stop_pct = compute_dynamic_stop(symbol, price)
        if stop_pct > 0.0:
            buy_frac = min(risk_pct / stop_pct, max_frac)
            return round(cash * buy_frac / price, 4)

    base_frac  = float(cfg.get("POSITION_SIZE", 0.1))
    multiplier = float(cfg.get("MEAN_REV_SIZE_MULTIPLIER", 0.0))

    if multiplier == 0.0:
        return round(cash * base_frac / price, 4)

    window    = int(cfg.get("MEAN_REV_WINDOW", 20))
    threshold = float(cfg.get("MEAN_REV_THRESHOLD", 1.0))
    history   = _price_history.get(symbol, [])

    if len(history) < window:
        return round(cash * base_frac / price, 4)

    recent = history[-window:]
    mean   = sum(recent) / window
    std    = math.sqrt(sum((p - mean) ** 2 for p in recent) / window)

    if std == 0.0:
        return round(cash * base_frac / price, 4)

    lower_band  = mean - threshold * std
    depth       = max(0.0, (lower_band - price) / std)
    scaled_frac = min(base_frac * (1.0 + multiplier * depth), max_frac)

    return round(cash * scaled_frac / price, 4)


def get_state(symbol: str) -> dict:
    """Return mean reversion internals for monitoring."""
    cfg            = get_config()
    window         = int(cfg.get("MEAN_REV_WINDOW", 20))
    threshold      = float(cfg.get("MEAN_REV_THRESHOLD", 1.0))
    exit_fraction  = float(cfg.get("MEAN_REV_EXIT_FRACTION", 1.0))
    min_vol        = float(cfg.get("MIN_VOLATILITY", 0.0))
    size_mult       = float(cfg.get("MEAN_REV_SIZE_MULTIPLIER", 0.0))
    base_frac       = float(cfg.get("POSITION_SIZE", 0.1))
    max_pos         = float(cfg.get("MAX_POSITION_SIZE", 0.5))
    min_entry_depth = float(cfg.get("MIN_ENTRY_DEPTH", 0.0))
    max_er          = float(cfg.get("MAX_EFFICIENCY_RATIO", 1.0))
    vol_mult        = float(cfg.get("MEAN_REV_STOP_VOL_MULT", 0.0))
    min_stop       = float(cfg.get("MIN_STOP_LOSS_PCT", 0.01))
    fallback_stop  = float(cfg.get("STOP_LOSS_PCT", 0.02))

    history = _price_history.get(symbol, [])
    n       = len(history)

    if n < window:
        return {
            "symbol":            symbol,
            "price_count":       n,
            "window":            window,
            "threshold":         threshold,
            "exit_fraction":     exit_fraction,
            "min_volatility":    min_vol,
            "size_multiplier":   size_mult,
            "max_position_size": max_pos,
            "min_entry_depth":   min_entry_depth,
            "max_efficiency_ratio": max_er,
            "efficiency_ratio":  None,
            "stop_vol_mult":     vol_mult,
            "mean":              None,
            "std":               None,
            "lower_band":        None,
            "upper_band":        None,
            "exit_target":       None,
            "signal_depth":      None,
            "scaled_size_frac":  None,
            "dynamic_stop_pct":  None,
            "signal":            "HOLD",
            "warmed_up":         False,
        }

    recent      = history[-window:]
    mean        = sum(recent) / window
    std         = math.sqrt(sum((p - mean) ** 2 for p in recent) / window)
    current     = history[-1]
    lower_band  = mean - threshold * std
    exit_target = mean - (1.0 - exit_fraction) * threshold * std

    depth       = max(0.0, (lower_band - current) / std) if current <= lower_band else 0.0
    scaled_frac = min(base_frac * (1.0 + size_mult * depth), max_pos) if size_mult > 0 else base_frac

    # Dynamic stop estimate at current price (what would be set on a BUY now)
    if vol_mult > 0.0 and std > 0.0 and current > 0:
        dyn_stop = max(min_stop, (std / current) * vol_mult)
    else:
        dyn_stop = fallback_stop

    er = _compute_er(history, window)

    return {
        "symbol":               symbol,
        "price_count":          n,
        "window":               window,
        "threshold":            threshold,
        "exit_fraction":        exit_fraction,
        "min_volatility":       min_vol,
        "size_multiplier":      size_mult,
        "max_position_size":    max_pos,
        "min_entry_depth":      min_entry_depth,
        "max_efficiency_ratio": max_er,
        "efficiency_ratio":     round(er, 4),
        "er_filter_active":     (max_er < 1.0 and er > max_er),
        "stop_vol_mult":        vol_mult,
        "mean":                 round(mean, 2),
        "std":                  round(std, 4),
        "lower_band":           round(lower_band, 2),
        "upper_band":           round(mean + threshold * std, 2),
        "exit_target":          round(exit_target, 2),
        "signal_depth":         round(depth, 4),
        "scaled_size_frac":     round(scaled_frac, 4),
        "dynamic_stop_pct":     round(dyn_stop, 4),
        "low_vol_filter":       (min_vol > 0.0 and std < min_vol),
        "signal":               get_signal(symbol),
        "warmed_up":            True,
    }
