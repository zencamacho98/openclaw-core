# app/strategy/config.py
#
# Central store for live strategy parameters.
# Persisted to data/strategy_config.json between restarts.
# All strategy functions read from here at call time — not at import time.
# Changing a value here takes effect on the NEXT tick.

import json
import pathlib
from typing import Any

CONFIG_FILE = pathlib.Path("data/strategy_config.json")

DEFAULTS: dict[str, Any] = {
    # MA crossover
    "SHORT_WINDOW":       3,
    "LONG_WINDOW":        7,
    "MIN_SIGNAL_GAP":     0.0,   # |short_ma - long_ma| must exceed this to trade (0 = off)
    # Regime detection (Kaufman Efficiency Ratio)
    "REGIME_WINDOW":      20,    # lookback for efficiency ratio computation
    "REGIME_THRESHOLD":   0.3,   # ER >= this → trending; below → ranging
    # Mean reversion
    "MEAN_REV_WINDOW":          20,   # rolling window for mean/std calculation
    "MEAN_REV_THRESHOLD":       1.0,  # std devs from mean to trigger BUY
    "MEAN_REV_EXIT_FRACTION":   1.0,  # 1.0 = exit at mean; 0.5 = exit halfway back
    "MIN_VOLATILITY":           0.0,  # min rolling std to allow entry (0 = disabled)
    "MEAN_REV_SIZE_MULTIPLIER": 0.0,   # scales position with signal depth (0 = fixed size)
    "MAX_POSITION_SIZE":        0.5,   # hard cap on MR position fraction (caps dynamic sizing)
    "MIN_ENTRY_DEPTH":          0.0,   # min depth below lower band to allow entry (0 = disabled)
    "MAX_EFFICIENCY_RATIO":     1.0,   # block MR entry when ER exceeds this (1.0 = disabled)
    # Regime confidence filter (candidate-only experiment params)
    "REGIME_CONF_LOOKBACK":          50,   # bars of history to assess MR suitability
    "REGIME_CONF_GOOD_THRESHOLD":    0.7,  # confidence >= this → trade normally
    "REGIME_CONF_OK_THRESHOLD":      0.5,  # confidence >= this → trade at reduced size
    "REGIME_CONF_REDUCED_SIZE_MULT": 0.5,  # multiply position size when confidence is marginal
    # Risk management
    "STOP_LOSS_PCT":            0.02,  # exit if price drops this far below entry
    "TAKE_PROFIT_PCT":          0.04,  # exit if price rises this far above entry (0 = disabled)
    # Mean reversion dynamic stop (overrides STOP_LOSS_PCT for MR entries when vol_mult > 0)
    "MEAN_REV_STOP_VOL_MULT":   0.0,   # stop = max(MIN_STOP_LOSS_PCT, (std/price) * this)
    "MIN_STOP_LOSS_PCT":        0.01,  # floor so dynamic stops never become unrealistically tight
    "POSITION_SIZE":      0.1,   # fraction of available cash to deploy per BUY
    "TRADE_COOLDOWN":     0,     # minimum ticks between trades (0 = no cooldown)
    # Stability patch: volatility-aware sizing and stops
    "ATR_WINDOW":             14,    # lookback for ATR (simple |Δprice| proxy)
    "STOP_ATR_MULT":          0.0,   # stop_pct = ATR*mult/entry_price (0 = use STOP_LOSS_PCT)
    "RISK_PER_TRADE_PCT":     0.0,   # equity fraction to risk per trade (0 = use POSITION_SIZE)
    "MAX_TRADES_PER_SESSION": 0,     # hard BUY cap per session/run (0 = unlimited)
}

_cache: dict | None = None


def get_config() -> dict:
    """Return current live config. Loads from disk on first call."""
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def update(params: dict) -> dict:
    """Merge params into current config, persist, and return new config."""
    global _cache
    merged = {**get_config(), **params}
    _save(merged)
    _cache = merged
    return merged


def reset() -> dict:
    """Reset to defaults and persist."""
    global _cache
    _save(dict(DEFAULTS))
    _cache = dict(DEFAULTS)
    return dict(DEFAULTS)


def _load() -> dict:
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text())
            return {**DEFAULTS, **saved}   # fill in any missing keys
        except Exception:
            pass
    return dict(DEFAULTS)


def _save(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
