# app/experiment.py
#
# Self-contained batch simulation runner.
#
# Executes N trading ticks instantly (no sleep) in complete isolation from:
#   - the live portfolio (app/portfolio.py)
#   - the live strategy state (app/strategy/simple_strategy.py)
#   - the live config (app/strategy/config.py)
#
# Reads live config as the baseline for params, but never writes back to it.
# Results can optionally be saved to data/experiments/ as JSON for later review.
#
# CLI usage:
#   python -m app.experiment                              # 500 ticks, live params
#   python -m app.experiment --ticks 1000 --seed 42
#   python -m app.experiment --stop-loss 0.015 --position-size 0.08
#   python -m app.experiment --compare                   # live params vs. tweaked set
#   python -m app.experiment --no-save                   # skip writing to disk

from __future__ import annotations

import json
import math
import random
import pathlib
import argparse
from datetime import datetime, timezone
from typing import Any

RESULTS_DIR    = pathlib.Path("data/experiments")
CANDIDATE_CFG  = pathlib.Path("data/candidate_config.json")

# Parameter defaults and the authoritative list of valid param names come from
# app.strategy.config.DEFAULTS — there is no separate fallback list here.
# Adding a new param to config.DEFAULTS automatically makes it available in
# _live_params(), _candidate_params(), _merge_params(), and the allowlist filter.

# Valid mode values for run() / compare()
MODE_MA     = "ma_crossover"    # MA crossover only (default, original behaviour)
MODE_MR     = "mean_reversion"  # Mean reversion only
MODE_REGIME = "regime"          # Auto-route based on Efficiency Ratio

INITIAL_CASH: float = 100_000.0
PRICE_START:  float = 525.0
PRICE_MIN:    float = 480.0
PRICE_MAX:    float = 580.0
PRICE_STEP:   float = 3.0


# ── Isolated portfolio ──────────────────────────────────────────────────────────

class _Portfolio:
    """Minimal in-process portfolio for one simulation run. Zero shared state."""

    __slots__ = ("cash", "qty", "avg_cost", "realized_pnl", "trades", "last_price")

    def __init__(self) -> None:
        self.cash:         float = INITIAL_CASH
        self.qty:          float = 0.0
        self.avg_cost:     float = 0.0
        self.realized_pnl: float = 0.0
        self.trades:       list[dict] = []
        self.last_price:   float = PRICE_START

    @property
    def has_position(self) -> bool:
        return self.qty > 0

    @property
    def unrealized_pnl(self) -> float:
        return (self.last_price - self.avg_cost) * self.qty if self.has_position else 0.0

    @property
    def portfolio_value(self) -> float:
        return self.cash + self.qty * self.last_price

    def buy(self, price: float, position_size: float) -> None:
        budget = self.cash * position_size
        qty = round(budget / price, 4)
        cost = qty * price
        if qty <= 0 or cost > self.cash:
            return
        total_cost = self.avg_cost * self.qty + price * qty
        self.qty += qty
        self.avg_cost = total_cost / self.qty
        self.cash -= cost
        self.trades.append({"side": "BUY", "qty": qty, "price": price, "pnl": 0.0})

    def sell(self, price: float, trigger: str = "signal") -> None:
        if not self.has_position:
            return
        pnl = (price - self.avg_cost) * self.qty
        self.realized_pnl += pnl
        self.cash += self.qty * price
        self.trades.append({
            "side":    "SELL",
            "qty":     self.qty,
            "price":   price,
            "pnl":     round(pnl, 2),
            "trigger": trigger,
        })
        self.qty = 0.0
        self.avg_cost = 0.0


# ── Strategy helpers (no shared state) ─────────────────────────────────────────

def _ma(prices: list[float], window: int) -> float:
    return sum(prices[-window:]) / window


def _signal(prices: list[float], short_w: int, long_w: int, min_gap: float = 0.0) -> str:
    """MA crossover signal with optional gap filter."""
    if len(prices) < long_w:
        return "HOLD"
    s = _ma(prices, short_w)
    l = _ma(prices, long_w)
    if abs(s - l) <= min_gap:
        return "HOLD"
    if s > l:   return "BUY"
    if s < l:   return "SELL"
    return "HOLD"


def _mr_signal(
    prices: list[float],
    window: int,
    threshold: float,
    exit_fraction: float = 1.0,
    min_vol: float = 0.0,
    min_entry_depth: float = 0.0,
    max_er: float = 1.0,
) -> str:
    """Mean reversion signal with exit fraction, volatility, depth, and ER filters."""
    if len(prices) < window:
        return "HOLD"
    recent = prices[-window:]
    mean   = sum(recent) / window
    std    = math.sqrt(sum((p - mean) ** 2 for p in recent) / window)
    if std == 0.0:
        return "HOLD"
    current     = prices[-1]
    lower_band  = mean - threshold * std
    exit_target = mean - (1.0 - exit_fraction) * threshold * std
    low_vol     = (min_vol > 0.0 and std < min_vol)
    if not low_vol and current <= lower_band:
        depth_val = (lower_band - current) / std
        if depth_val >= min_entry_depth:
            # Market condition filter: skip if price action is too directional
            er = _efficiency_ratio(prices, window)
            if er <= max_er:
                return "BUY"
    if current >= exit_target:
        return "SELL"
    return "HOLD"


def _mr_position_size(
    prices: list[float],
    window: int,
    threshold: float,
    multiplier: float,
    base_size: float,
    max_size: float = 1.0,
) -> float:
    """
    Return scaled position-size fraction for a mean reversion BUY.

    multiplier=0  → always base_size (unchanged behaviour).
    multiplier>0  → min(base_size * (1 + multiplier * depth), max_size)
    where depth = (lower_band - current_price) / std  (≥ 0 at entry).
    max_size      → hard cap; defaults to 1.0 when not provided.
    """
    if multiplier == 0.0 or len(prices) < window:
        return base_size
    recent = prices[-window:]
    mean   = sum(recent) / window
    std    = math.sqrt(sum((p - mean) ** 2 for p in recent) / window)
    if std == 0.0:
        return base_size
    lower_band = mean - threshold * std
    depth      = max(0.0, (lower_band - prices[-1]) / std)
    return min(base_size * (1.0 + multiplier * depth), max_size)


def _mr_dynamic_stop(
    prices: list[float],
    window: int,
    entry_price: float,
    vol_mult: float,
    min_stop: float,
    fallback: float,
) -> float:
    """
    Compute the stop loss pct for a mean reversion entry.

    vol_mult=0  → fallback (STOP_LOSS_PCT, unchanged behaviour).
    vol_mult>0  → max(min_stop, (std / entry_price) * vol_mult)
                  Tighter in calm markets, wider in volatile ones.
    """
    if vol_mult == 0.0 or len(prices) < window or entry_price <= 0:
        return fallback
    recent = prices[-window:]
    mean   = sum(recent) / window
    std    = math.sqrt(sum((p - mean) ** 2 for p in recent) / window)
    if std == 0.0:
        return fallback
    return max(min_stop, (std / entry_price) * vol_mult)


def _efficiency_ratio(prices: list[float], window: int) -> float:
    """Kaufman Efficiency Ratio for the last `window+1` prices. Returns 0 if too short."""
    if len(prices) < window + 1:
        return 0.0
    recent     = prices[-(window + 1):]
    net_move   = abs(recent[-1] - recent[0])
    total_path = sum(abs(recent[i] - recent[i - 1]) for i in range(1, len(recent)))
    return net_move / total_path if total_path > 0 else 0.0


def _atr(prices: list[float], window: int) -> float:
    """ATR proxy: SMA of |price[t] - price[t-1]| over last `window` bars. Returns 0 if too short."""
    if len(prices) < window + 1:
        return 0.0
    return sum(abs(prices[i] - prices[i - 1]) for i in range(-window, 0)) / window


def _route_signal(
    prices: list[float],
    sw: int, lw: int, mg: float,
    rw: int, rt: float,
    mrw: int, mrt: float,
    mref: float = 1.0,
    mnv: float = 0.0,
    med: float = 0.0,
    mxer: float = 1.0,
) -> tuple[str, str]:
    """
    Regime-routed signal. Returns (signal, active_strategy_name).
    Uses Efficiency Ratio to choose between MA crossover and mean reversion.
    """
    er = _efficiency_ratio(prices, rw)
    if er >= rt:
        return _signal(prices, sw, lw, mg), MODE_MA
    return _mr_signal(prices, mrw, mrt, mref, mnv, med, mxer), MODE_MR


# ── Core simulation ─────────────────────────────────────────────────────────────

def _run_ticks(n_ticks: int, params: dict[str, Any], seed: int,
               mode: str = MODE_MA, use_candidate: bool = False) -> dict:
    """
    Execute n_ticks and return a compact result dict. Fully deterministic given seed.

    mode:          MODE_MA (default), MODE_MR, or MODE_REGIME
    use_candidate: activate candidate-only logic (performance-based adaptation)
    """
    rng  = random.Random(seed)
    port = _Portfolio()

    sw   = int(params["SHORT_WINDOW"])
    lw   = int(params["LONG_WINDOW"])
    mg   = float(params.get("MIN_SIGNAL_GAP", 0.0))
    rw   = int(params.get("REGIME_WINDOW", 20))
    rt   = float(params.get("REGIME_THRESHOLD", 0.3))
    mrw  = int(params.get("MEAN_REV_WINDOW", 20))
    mrt  = float(params.get("MEAN_REV_THRESHOLD", 1.0))
    mref = float(params.get("MEAN_REV_EXIT_FRACTION", 1.0))
    mnv  = float(params.get("MIN_VOLATILITY", 0.0))
    msm   = float(params.get("MEAN_REV_SIZE_MULTIPLIER", 0.0))
    mps   = float(params.get("MAX_POSITION_SIZE", 0.5))
    med   = float(params.get("MIN_ENTRY_DEPTH", 0.0))
    mxer  = float(params.get("MAX_EFFICIENCY_RATIO", 1.0))
    mrsv  = float(params.get("MEAN_REV_STOP_VOL_MULT", 0.0))
    min_sl = float(params.get("MIN_STOP_LOSS_PCT", 0.01))
    sl   = float(params["STOP_LOSS_PCT"])
    tp   = float(params["TAKE_PROFIT_PCT"])
    ps   = float(params["POSITION_SIZE"])
    cd   = int(params["TRADE_COOLDOWN"])
    # Candidate-only: performance-based adaptation params
    pfl  = int(params.get("PERFORMANCE_LOOKBACK", 20))
    pfgt = float(params.get("PERFORMANCE_GOOD_THRESHOLD", 0.6))
    pfbt = float(params.get("PERFORMANCE_BAD_THRESHOLD", 0.4))
    pfsm = float(params.get("PERFORMANCE_REDUCED_SIZE_MULT", 0.5))
    # Stability patch params
    atr_w      = int(params.get("ATR_WINDOW", 14))
    stop_atr_m = float(params.get("STOP_ATR_MULT", 0.0))
    risk_pct   = float(params.get("RISK_PER_TRADE_PCT", 0.0))
    max_trades = int(params.get("MAX_TRADES_PER_SESSION", 0))

    prices:           list[float] = []
    last_trade_tick:  int         = -9999
    ticks_trending:   int         = 0
    ticks_ranging:    int         = 0
    regime_switches:  int         = 0
    last_regime:      str         = ""
    active_stop_pct:  float       = sl   # per-position stop; updated on BUY, reset on SELL
    recent_pnls:      list[float] = []   # rolling window of completed sell PnLs
    total_buys_count: int         = 0    # running BUY count for cap enforcement
    skips_cap:        int         = 0    # BUYs blocked by MAX_TRADES_PER_SESSION
    skips_cooldown:   int         = 0    # ticks skipped due to TRADE_COOLDOWN

    for tick in range(1, n_ticks + 1):
        price = round(port.last_price + rng.uniform(-PRICE_STEP, PRICE_STEP), 2)
        price = max(PRICE_MIN, min(PRICE_MAX, price))
        prices.append(price)
        port.last_price = price

        in_cooldown = cd > 0 and (tick - last_trade_tick) <= cd

        # Risk management takes priority over any signal
        if port.has_position and not in_cooldown:
            entry = port.avg_cost
            if active_stop_pct > 0 and price < entry * (1 - active_stop_pct):
                port.sell(price, trigger="stop_loss")
                recent_pnls = (recent_pnls + [port.trades[-1]["pnl"]])[-pfl:]
                active_stop_pct = sl          # reset to config default
                last_trade_tick = tick
                continue
            if tp > 0 and price >= entry * (1 + tp):
                port.sell(price, trigger="take_profit")
                recent_pnls = (recent_pnls + [port.trades[-1]["pnl"]])[-pfl:]
                active_stop_pct = sl          # reset
                last_trade_tick = tick
                continue

        if in_cooldown:
            skips_cooldown += 1
            continue

        # Select signal based on mode; track whether MR sizing applies
        use_mr_sizing = False
        if mode == MODE_REGIME:
            sig, active = _route_signal(prices, sw, lw, mg, rw, rt, mrw, mrt, mref, mnv, med, mxer)
            cur_regime  = "trending" if active == MODE_MA else "ranging"
            if cur_regime == "trending":
                ticks_trending += 1
            else:
                ticks_ranging += 1
            if last_regime and cur_regime != last_regime:
                regime_switches += 1
            last_regime    = cur_regime
            use_mr_sizing  = (active == MODE_MR)
        elif mode == MODE_MR:
            sig           = _mr_signal(prices, mrw, mrt, mref, mnv, med, mxer)
            use_mr_sizing = True
        else:
            sig = _signal(prices, sw, lw, mg)

        if sig == "BUY" and not port.has_position:
            # Hard cap on total buys per session
            if max_trades > 0 and total_buys_count >= max_trades:
                skips_cap += 1
                continue

            # Determine stop pct for this entry: ATR-based > vol-mult > fixed
            if stop_atr_m > 0.0:
                atr = _atr(prices, atr_w)
                entry_stop = max(min_sl, atr * stop_atr_m / price) if atr > 0.0 else sl
            elif use_mr_sizing and mrsv > 0.0:
                entry_stop = _mr_dynamic_stop(prices, mrw, price, mrsv, min_sl, sl)
            else:
                entry_stop = sl

            # Determine position size: risk-based > MR dynamic > fixed
            if risk_pct > 0.0 and entry_stop > 0.0:
                # size = risk_pct / stop_pct (fraction of cash, since equity ≈ cash at entry)
                buy_size = min(risk_pct / entry_stop, mps)
            elif use_mr_sizing and msm > 0.0:
                buy_size = _mr_position_size(prices, mrw, mrt, msm, ps, mps)
            else:
                buy_size = ps

            allow_buy = True
            if use_candidate and use_mr_sizing and len(recent_pnls) >= pfl:
                win_rate = sum(1 for p in recent_pnls if p > 0) / pfl
                if win_rate < pfbt:
                    allow_buy = False   # block: recent performance too poor
                elif win_rate < pfgt:
                    buy_size *= pfsm    # reduce: recent performance marginal

            if allow_buy:
                port.buy(price, buy_size)
                if port.trades and port.trades[-1]["side"] == "BUY":
                    total_buys_count += 1
                    last_trade_tick  = tick
                    active_stop_pct  = entry_stop
        elif sig == "SELL" and port.has_position:
            port.sell(price, trigger="signal")
            recent_pnls = (recent_pnls + [port.trades[-1]["pnl"]])[-pfl:]
            active_stop_pct = sl              # reset
            last_trade_tick = tick

    sells = [t for t in port.trades if t["side"] == "SELL"]
    pnls  = [t["pnl"] for t in sells]
    wins  = [p for p in pnls if p > 0]

    result = {
        "mode":              mode,
        "ticks":             n_ticks,
        "seed":              seed,
        "total_trades":      len(port.trades),
        "total_buys":        sum(1 for t in port.trades if t["side"] == "BUY"),
        "total_sells":       len(sells),
        "stop_loss_hits":    sum(1 for t in sells if t.get("trigger") == "stop_loss"),
        "take_profit_hits":  sum(1 for t in sells if t.get("trigger") == "take_profit"),
        "win_rate":          round(len(wins) / len(sells), 4) if sells else 0.0,
        "realized_pnl":      round(port.realized_pnl, 2),
        "unrealized_pnl":    round(port.unrealized_pnl, 2),
        "portfolio_value":   round(port.portfolio_value, 2),
        "avg_pnl_per_sell":  round(sum(pnls) / len(sells), 2) if sells else 0.0,
        "best_trade":        round(max(pnls), 2) if pnls else 0.0,
        "worst_trade":       round(min(pnls), 2) if pnls else 0.0,
        "skips_cooldown":    skips_cooldown,
        "skips_cap":         skips_cap,
        "params":            params,
    }
    if mode == MODE_REGIME:
        result["ticks_trending"]  = ticks_trending
        result["ticks_ranging"]   = ticks_ranging
        result["regime_switches"] = regime_switches
    return result


# ── Param helpers ───────────────────────────────────────────────────────────────
#
# config.DEFAULTS is the single source of truth for valid parameter names.
# Both the fallback values and the allowlist filter derive from it, so a new
# parameter registered there is automatically accepted everywhere below.

def _live_params() -> dict[str, Any]:
    """Load live config. Falls back to config.DEFAULTS if disk load fails."""
    from app.strategy.config import get_config, DEFAULTS
    try:
        return dict(get_config())
    except Exception:
        return dict(DEFAULTS)


def _candidate_params() -> dict[str, Any]:
    """
    Load candidate params from data/candidate_config.json, merged onto live params.
    Only keys present in config.DEFAULTS are accepted; unknown keys are dropped.
    """
    from app.strategy.config import DEFAULTS
    base = _live_params()
    try:
        overrides = json.loads(CANDIDATE_CFG.read_text())
        valid = {k: v for k, v in overrides.items() if k in DEFAULTS}
        return {**base, **valid}
    except Exception:
        return base


def _merge_params(overrides: dict, use_candidate: bool = False) -> dict[str, Any]:
    """
    Merge caller-supplied overrides onto live (or candidate) params.
    Only keys present in config.DEFAULTS are accepted; unknown keys are dropped.
    """
    from app.strategy.config import DEFAULTS
    base = _candidate_params() if use_candidate else _live_params()
    valid = {k: v for k, v in overrides.items() if k in DEFAULTS}
    return {**base, **valid}


# ── Public API ──────────────────────────────────────────────────────────────────

def run(
    n_ticks: int = 500,
    param_overrides: dict | None = None,
    seed: int | None = None,
    save: bool = True,
    mode: str = MODE_MA,
    use_candidate: bool = False,
) -> dict:
    """
    Run a single simulation and return the result.

    param_overrides — any subset of strategy params; merged onto live config.
    seed            — fixes the random price walk for reproducibility.
    mode            — "ma_crossover" | "mean_reversion" | "regime"
    save            — write result to data/experiments/ when True.
    use_candidate   — load base params from data/candidate_config.json instead of live config.
    """
    if seed is None:
        seed = random.randint(0, 2 ** 32 - 1)

    params = _merge_params(param_overrides or {}, use_candidate=use_candidate)
    result = _run_ticks(n_ticks, params, seed, mode=mode, use_candidate=use_candidate)
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    result["type"] = "single"

    if save:
        _save(result)

    return result


def compare(
    n_ticks: int = 500,
    variants: list[dict] | None = None,
    seed: int | None = None,
    save: bool = True,
    mode: str = MODE_MA,
    use_candidate: bool = False,
) -> dict:
    """
    Run the same price sequence against multiple param sets and rank the results.

    variants      — list of override dicts merged onto live config independently.
                    {} represents the current live params unchanged.
    seed          — shared across all variants so differences are param-only.
    mode          — applied to all variants; use compare_modes() to compare modes directly.
    use_candidate — load base params from data/candidate_config.json instead of live config.

    Returns a dict with a ranked 'results' list (best portfolio_value first).
    """
    if seed is None:
        seed = random.randint(0, 2 ** 32 - 1)
    if not variants:
        variants = [{}]

    results = []
    for i, overrides in enumerate(variants):
        params = _merge_params(overrides, use_candidate=use_candidate)
        r = _run_ticks(n_ticks, params, seed, mode=mode, use_candidate=use_candidate)
        r["variant_index"] = i
        r["label"] = _label(overrides)
        results.append(r)

    results.sort(key=lambda r: r["portfolio_value"], reverse=True)

    out = {
        "type":                 "compare",
        "mode":                 mode,
        "ticks":                n_ticks,
        "seed":                 seed,
        "variants_run":         len(variants),
        "best_portfolio_value": results[0]["portfolio_value"] if results else 0.0,
        "results":              results,
        "timestamp":            datetime.now(timezone.utc).isoformat(),
    }

    if save:
        _save(out)

    return out


def compare_modes(
    n_ticks: int = 500,
    modes: list[str] | None = None,
    param_overrides: dict | None = None,
    seed: int | None = None,
    save: bool = True,
    use_candidate: bool = False,
) -> dict:
    """
    Run the same price sequence and params under different strategy modes.

    Useful for the core question: does regime routing beat pure MA crossover?

    modes         — defaults to [MODE_MA, MODE_MR, MODE_REGIME]
    use_candidate — load base params from data/candidate_config.json instead of live config.
    """
    if seed is None:
        seed = random.randint(0, 2 ** 32 - 1)
    if not modes:
        modes = [MODE_MA, MODE_MR, MODE_REGIME]

    params  = _merge_params(param_overrides or {}, use_candidate=use_candidate)
    results = []
    for m in modes:
        r = _run_ticks(n_ticks, params, seed, mode=m, use_candidate=use_candidate)
        r["label"] = m
        results.append(r)

    results.sort(key=lambda r: r["portfolio_value"], reverse=True)

    out = {
        "type":                 "compare_modes",
        "ticks":                n_ticks,
        "seed":                 seed,
        "modes_compared":       modes,
        "best_mode":            results[0]["mode"],
        "best_portfolio_value": results[0]["portfolio_value"],
        "results":              results,
        "timestamp":            datetime.now(timezone.utc).isoformat(),
    }

    if save:
        _save(out)

    return out


def get_saved(n: int = 10) -> list[dict]:
    """Return the last N saved experiment results, newest-first."""
    if not RESULTS_DIR.exists():
        return []
    files = sorted(RESULTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files[:n]:
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            pass
    return out


# ── Persistence ─────────────────────────────────────────────────────────────────

def _save(result: dict) -> pathlib.Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts    = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    kind  = result.get("type", "run")
    ticks = result.get("ticks", 0)
    path  = RESULTS_DIR / f"{ts}_{kind}_{ticks}ticks.json"
    path.write_text(json.dumps(result, indent=2))
    return path


def _label(overrides: dict) -> str:
    if not overrides:
        return "baseline (live params)"
    return ", ".join(f"{k}={v}" for k, v in overrides.items())


# ── CLI ─────────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run a fast batch simulation experiment.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--ticks",         type=int,   default=500,  help="Number of ticks to simulate")
    p.add_argument("--seed",          type=int,   default=None, help="Random seed (omit for random)")
    p.add_argument("--short-window",    type=int,   default=None, metavar="N")
    p.add_argument("--long-window",     type=int,   default=None, metavar="N")
    p.add_argument("--min-signal-gap",  type=float, default=None, metavar="F", help="e.g. 1.5")
    p.add_argument("--stop-loss",       type=float, default=None, metavar="F", help="e.g. 0.015")
    p.add_argument("--take-profit",     type=float, default=None, metavar="F", help="e.g. 0.04")
    p.add_argument("--position-size",   type=float, default=None, metavar="F", help="e.g. 0.1")
    p.add_argument("--cooldown",          type=int,   default=None, metavar="N")
    p.add_argument("--mr-window",         type=int,   default=None, metavar="N",
                   help="MEAN_REV_WINDOW: rolling window for mean/std (e.g. 15)")
    p.add_argument("--mr-threshold",      type=float, default=None, metavar="F",
                   help="MEAN_REV_THRESHOLD: std devs below mean to trigger BUY (e.g. 1.5)")
    p.add_argument("--mr-exit-fraction",  type=float, default=None, metavar="F",
                   help="MEAN_REV_EXIT_FRACTION e.g. 0.5 (halfway); 1.0 = full mean reversion")
    p.add_argument("--min-volatility",    type=float, default=None, metavar="F",
                   help="MIN_VOLATILITY: skip entries when rolling std < this (0 = disabled)")
    p.add_argument("--mr-size-mult",       type=float, default=None, metavar="F",
                   help="MEAN_REV_SIZE_MULTIPLIER: scales buy size with signal depth (0 = fixed)")
    p.add_argument("--max-position-size",  type=float, default=None, metavar="F",
                   help="MAX_POSITION_SIZE: hard cap on MR position fraction (e.g. 0.2)")
    p.add_argument("--min-entry-depth",    type=float, default=None, metavar="F",
                   help="MIN_ENTRY_DEPTH: min depth below lower band to allow BUY (e.g. 0.1)")
    p.add_argument("--max-er",             type=float, default=None, metavar="F",
                   help="MAX_EFFICIENCY_RATIO: block MR entry above this ER (1.0 = disabled)")
    p.add_argument("--mr-stop-vol-mult",   type=float, default=None, metavar="F",
                   help="MEAN_REV_STOP_VOL_MULT: dynamic stop = (std/price)*this (0 = fixed stop)")
    p.add_argument("--min-stop-loss",      type=float, default=None, metavar="F",
                   help="MIN_STOP_LOSS_PCT: floor on dynamic stop loss (default 0.01)")
    p.add_argument(
        "--mode",
        choices=[MODE_MA, MODE_MR, MODE_REGIME],
        default=MODE_MA,
        help="Strategy mode: ma_crossover | mean_reversion | regime",
    )
    p.add_argument(
        "--compare-modes",
        action="store_true",
        help="Compare all three strategy modes side-by-side (ignores --compare)",
    )
    p.add_argument(
        "--compare",
        action="store_true",
        help="Compare live params (baseline) against the overrides you provide",
    )
    p.add_argument("--no-save",       action="store_true", help="Skip writing results to disk")
    p.add_argument("--use-candidate", action="store_true",
                   help="Load base params from data/candidate_config.json instead of live config")
    return p


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()

    overrides: dict[str, Any] = {}
    if args.short_window   is not None: overrides["SHORT_WINDOW"]    = args.short_window
    if args.long_window    is not None: overrides["LONG_WINDOW"]     = args.long_window
    if args.min_signal_gap is not None: overrides["MIN_SIGNAL_GAP"]  = args.min_signal_gap
    if args.stop_loss        is not None: overrides["STOP_LOSS_PCT"]          = args.stop_loss
    if args.take_profit      is not None: overrides["TAKE_PROFIT_PCT"]        = args.take_profit
    if args.position_size    is not None: overrides["POSITION_SIZE"]          = args.position_size
    if args.cooldown         is not None: overrides["TRADE_COOLDOWN"]         = args.cooldown
    if args.mr_window        is not None: overrides["MEAN_REV_WINDOW"]         = args.mr_window
    if args.mr_threshold     is not None: overrides["MEAN_REV_THRESHOLD"]     = args.mr_threshold
    if args.mr_exit_fraction is not None: overrides["MEAN_REV_EXIT_FRACTION"] = args.mr_exit_fraction
    if args.min_volatility   is not None: overrides["MIN_VOLATILITY"]          = args.min_volatility
    if args.mr_size_mult      is not None: overrides["MEAN_REV_SIZE_MULTIPLIER"] = args.mr_size_mult
    if args.max_position_size is not None: overrides["MAX_POSITION_SIZE"]  = args.max_position_size
    if args.min_entry_depth   is not None: overrides["MIN_ENTRY_DEPTH"]       = args.min_entry_depth
    if args.max_er            is not None: overrides["MAX_EFFICIENCY_RATIO"]   = args.max_er
    if args.mr_stop_vol_mult is not None: overrides["MEAN_REV_STOP_VOL_MULT"]   = args.mr_stop_vol_mult
    if args.min_stop_loss    is not None: overrides["MIN_STOP_LOSS_PCT"]         = args.min_stop_loss

    save          = not args.no_save
    use_candidate = args.use_candidate

    if args.compare_modes:
        result = compare_modes(args.ticks, seed=args.seed,
                               param_overrides=overrides or None, save=save,
                               use_candidate=use_candidate)
    elif args.compare:
        variants = [{}]
        if overrides:
            variants.append(overrides)
        result = compare(args.ticks, variants, seed=args.seed, mode=args.mode, save=save,
                         use_candidate=use_candidate)
    else:
        result = run(args.ticks, overrides, seed=args.seed, mode=args.mode, save=save,
                     use_candidate=use_candidate)

    print(json.dumps(result, indent=2))
