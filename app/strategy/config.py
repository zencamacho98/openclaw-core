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
    # Belfort brokerage-ready desk controls
    "BELFORT_MAX_ORDERS_PER_DAY": 100,      # final safety backstop; pacing should bite first
    "BELFORT_MAX_ORDERS_PER_HOUR": 16,      # rolling hourly pace limit to keep fees/churn under control
    "BELFORT_GLOBAL_COOLDOWN_SECONDS": 90,  # minimum time between new paper entries
    "BELFORT_SYMBOL_COOLDOWN_SECONDS": 300, # minimum time before re-entering the same symbol
    "BELFORT_MIN_HOLD_SECONDS": 180,        # minimum hold before a fresh same-symbol re-entry
    "BELFORT_TURNOVER_BUDGET_PCT": 2.0,     # max submitted notional as a fraction of equity per day
    "BELFORT_MAX_SYMBOL_EXPOSURE_PCT": 0.2, # cap each new name to 20% of equity
    "BELFORT_MAX_TOTAL_EXPOSURE_PCT": 0.65, # keep some dry powder in the book
    "BELFORT_MAX_ACTIVE_POSITIONS": 4,      # avoid one-click over-diversification
    "BELFORT_COST_EDGE_RATIO_LIMIT": 0.25,  # estimated trading cost must stay below 25% of expected edge
    "BELFORT_TRAINING_COMMISSION_PER_ORDER": 0.75, # fee reserve to keep paper behavior realistic for live broker costs
    "BELFORT_MIN_NET_EDGE_PCT": 0.0035,     # expected net edge after round-trip costs must still be worth the trade
    "BELFORT_MIN_MARKET_CAP_USD": 300_000_000.0,   # allow more volatile names, but avoid true micro-caps
    "BELFORT_MIN_FLOAT_SHARES": 15_000_000.0,      # avoid ultra-low-float chaos in paper phase
    "BELFORT_MIN_AVG_VOLUME": 800_000.0,           # require a reasonable tape before paper entries
    "BELFORT_MIN_RELATIVE_VOLUME": 0.8,            # do not paper-trade sleepy names just because they are moving a little
    "BELFORT_MIN_FLOAT_TURNOVER_PCT": 0.001,       # require at least some meaningful participation versus float
    "BELFORT_MAX_VOLATILE_SPREAD_PCT": 0.015,      # widened spread tolerance for controlled volatile names
    "BELFORT_MAX_VOLATILE_TAPE_PCT": 0.18,         # block names already moving too wildly for this phase
    # High-quality MR entry confirmation (experiment-path only — not wired to live mean_reversion.py)
    "MR_CONFIRM_TICKS": 0,    # ticks to look back for a confirmed overshoot low; 0 = off (original)
    "MR_REBOUND_CAP":   0.5,  # max rebound from that low in std-dev units; beyond = entry blocked
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
