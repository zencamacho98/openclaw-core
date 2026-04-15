from __future__ import annotations

import math
from datetime import datetime, timezone

from app.belfort_strategy import BelfortSignal
from app.strategy.config import get_config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _efficiency_ratio(prices: list[float], window: int) -> float | None:
    if window <= 0 or len(prices) < window + 1:
        return None
    recent = prices[-(window + 1):]
    net_move = abs(recent[-1] - recent[0])
    total_path = sum(abs(recent[i] - recent[i - 1]) for i in range(1, len(recent)))
    if total_path <= 0:
        return 0.0
    return net_move / total_path


def _atr(prices: list[float], window: int) -> float:
    if window <= 0 or len(prices) < window + 1:
        return 0.0
    return sum(abs(prices[i] - prices[i - 1]) for i in range(-window, 0)) / window


def _as_int_qty(raw_qty: float) -> int:
    if raw_qty <= 0:
        return 0
    return max(1, int(raw_qty))


class BelfortPolicyEngine:
    """
    Regime-aware Belfort strategy selector.

    This engine keeps its own rolling price history so live Belfort and sim
    Belfort never share state. It computes both trend and mean-reversion views,
    picks one via a bounded regime selector, and exposes the full evidence pack
    used for the decision.
    """

    def __init__(self, lane: str = "live") -> None:
        self._lane = lane
        self._prices: dict[str, list[float]] = {}
        self.last_evidence: dict = {}

    def reset(self) -> None:
        self._prices.clear()
        self.last_evidence = {}

    def evaluate(self, quote: object, portfolio: dict | None = None) -> BelfortSignal:
        portfolio = portfolio or {}
        symbol = str(getattr(quote, "symbol", "UNKNOWN")).upper()
        bid = float(getattr(quote, "bid", 0.0) or 0.0)
        ask = float(getattr(quote, "ask", 0.0) or 0.0)
        data_lane = str(getattr(quote, "data_lane", "UNKNOWN"))
        session_type = str(getattr(quote, "session_type", "unknown"))

        if session_type not in ("regular", "pre_market", "after_hours"):
            signal = self._hold(symbol, data_lane, session_type, "paper-tradeable session is closed — no execution")
            self.last_evidence = {
                "policy_selector": "regime_router_v1",
                "active_policy": "none",
                "policy_family": "none",
                "market_regime": "inactive",
                "selection_reason": "session gate blocked evaluation",
            }
            return signal

        if data_lane == "UNKNOWN":
            signal = self._hold(symbol, data_lane, session_type, "data lane unknown — signal suppressed")
            self.last_evidence = {
                "policy_selector": "regime_router_v1",
                "active_policy": "none",
                "policy_family": "none",
                "market_regime": "inactive",
                "selection_reason": "data lane gate blocked evaluation",
            }
            return signal

        if bid <= 0.0 or ask <= 0.0 or ask < bid:
            signal = self._hold(
                symbol,
                data_lane,
                session_type,
                f"bad bid/ask spread (bid={bid}, ask={ask}) — signal suppressed",
            )
            self.last_evidence = {
                "policy_selector": "regime_router_v1",
                "active_policy": "none",
                "policy_family": "none",
                "market_regime": "inactive",
                "selection_reason": "quote quality gate blocked evaluation",
            }
            return signal

        mid = (bid + ask) / 2.0
        prices = self._record_price(symbol, mid)
        state = self.get_state(symbol)
        active_policy = state["active_policy"]
        action = state["signal_action"]

        qty = 0
        limit_price = 0.0
        order_type = "none"

        if action == "buy":
            limit_price = round(ask, 4)
            order_type = "marketable_limit"
            qty = self._buy_qty(symbol, active_policy, limit_price, portfolio)
        elif action == "sell":
            limit_price = round(bid, 4)
            order_type = "marketable_limit"
            qty = self._sell_qty(symbol, active_policy, limit_price, portfolio)

        if action != "hold" and qty <= 0:
            action = "hold"
            order_type = "none"
            limit_price = 0.0

        rationale = self._build_rationale(state, action, bid, ask, prices[-1] if prices else mid)
        signal = BelfortSignal(
            symbol=symbol,
            action=action,
            qty=qty,
            order_type=order_type,
            limit_price=limit_price,
            rationale=rationale,
            data_lane=data_lane,
            session_type=session_type,
            generated_at=_now(),
        )
        self.last_evidence = {
            "policy_selector": state["policy_selector"],
            "active_policy": state["active_policy"],
            "policy_family": state["policy_family"],
            "market_regime": state["market_regime"],
            "efficiency_ratio": state["efficiency_ratio"],
            "selection_reason": state["selection_reason"],
            "midpoint": round(mid, 4),
            "ma_crossover": state["ma_crossover"],
            "mean_reversion": state["mean_reversion"],
        }
        return signal

    def get_state(self, symbol: str) -> dict:
        symbol = symbol.upper()
        cfg = get_config()
        prices = self._prices.get(symbol, [])
        n = len(prices)
        ma = self._ma_state(symbol, cfg, prices)
        mr = self._mr_state(symbol, cfg, prices)
        er = _efficiency_ratio(prices, int(cfg.get("REGIME_WINDOW", 20)))
        reg_threshold = float(cfg.get("REGIME_THRESHOLD", 0.3))

        active_policy = "warming_up"
        policy_family = "none"
        market_regime = "warming_up"
        selection_reason = "building price history for policy selection"
        selected = {
            "signal": "HOLD",
            "rationale": selection_reason,
            "warmed_up": False,
        }

        if er is None:
            if ma["warmed_up"] and not mr["warmed_up"]:
                active_policy = "ma_crossover"
                policy_family = "trend"
                market_regime = "warming_up"
                selection_reason = "trend policy active while regime model warms up"
                selected = ma
            elif mr["warmed_up"] and not ma["warmed_up"]:
                active_policy = "mean_reversion"
                policy_family = "mean_reversion"
                market_regime = "warming_up"
                selection_reason = "mean-reversion policy active while regime model warms up"
                selected = mr
        else:
            market_regime = "trending" if er >= reg_threshold else "ranging"
            if market_regime == "trending":
                active_policy = "ma_crossover"
                policy_family = "trend"
                selection_reason = f"efficiency ratio {er:.3f} >= threshold {reg_threshold:.3f}"
                selected = ma
            else:
                active_policy = "mean_reversion"
                policy_family = "mean_reversion"
                selection_reason = f"efficiency ratio {er:.3f} < threshold {reg_threshold:.3f}"
                selected = mr

        top = {
            "symbol": symbol,
            "lane": self._lane,
            "policy_selector": "regime_router_v1",
            "active_policy": active_policy,
            "active_strategy": active_policy,
            "policy_family": policy_family,
            "market_regime": market_regime,
            "regime": market_regime,
            "selection_reason": selection_reason,
            "efficiency_ratio": round(er, 4) if er is not None else None,
            "signal": str(selected.get("signal", "HOLD")),
            "signal_action": str(selected.get("signal", "HOLD")).lower(),
            "signal_rationale": selected.get("rationale", selection_reason),
            "warmed_up": bool(selected.get("warmed_up", False)),
            "price_count": n,
            "ma_crossover": ma,
            "mean_reversion": mr,
            "short_window": ma.get("short_window"),
            "long_window": ma.get("long_window"),
            "min_signal_gap": ma.get("min_signal_gap"),
            "short_ma": ma.get("short_ma"),
            "long_ma": ma.get("long_ma"),
            "signal_gap": ma.get("signal_gap"),
            "gap_sufficient": ma.get("gap_sufficient"),
            "mean": mr.get("mean"),
            "std": mr.get("std"),
            "lower_band": mr.get("lower_band"),
            "exit_target": mr.get("exit_target"),
            "mr_signal_depth": mr.get("signal_depth"),
        }
        return top

    def _record_price(self, symbol: str, price: float) -> list[float]:
        cfg = get_config()
        max_keep = max(
            int(cfg.get("LONG_WINDOW", 7)) * 3,
            int(cfg.get("MEAN_REV_WINDOW", 20)) * 3,
            int(cfg.get("REGIME_WINDOW", 20)) * 3,
        )
        prices = self._prices.setdefault(symbol, [])
        prices.append(price)
        if len(prices) > max_keep:
            del prices[:-max_keep]
        return prices

    def _buy_qty(self, symbol: str, active_policy: str, price: float, portfolio: dict) -> int:
        cash = float((portfolio or {}).get("cash", 0.0) or 0.0)
        if price <= 0.0 or cash <= 0.0:
            return 0

        if active_policy == "mean_reversion":
            cfg = get_config()
            max_frac = float(cfg.get("MAX_POSITION_SIZE", 0.5))
            risk_pct = float(cfg.get("RISK_PER_TRADE_PCT", 0.0))
            stop_pct = self._mr_dynamic_stop(symbol, price)
            if risk_pct > 0.0 and stop_pct > 0.0:
                raw_qty = cash * min(risk_pct / stop_pct, max_frac) / price
                return _as_int_qty(raw_qty)

            base_frac = float(cfg.get("POSITION_SIZE", 0.1))
            size_mult = float(cfg.get("MEAN_REV_SIZE_MULTIPLIER", 0.0))
            mr = self._mr_state(symbol, cfg, self._prices.get(symbol, []))
            depth = float(mr.get("signal_depth") or 0.0)
            frac = min(base_frac * (1.0 + size_mult * depth), max_frac) if size_mult > 0 else base_frac
            return _as_int_qty(cash * frac / price)

        cfg = get_config()
        return _as_int_qty(cash * float(cfg.get("POSITION_SIZE", 0.1)) / price)

    def _sell_qty(self, symbol: str, active_policy: str, price: float, portfolio: dict) -> int:
        positions = (portfolio or {}).get("positions") or {}
        pos = positions.get(symbol) or positions.get(symbol.upper()) or {}
        held = int(float(pos.get("qty", 0) or 0))
        if held > 0:
            return held
        return self._buy_qty(symbol, active_policy, price, portfolio)

    def _ma_state(self, symbol: str, cfg: dict, prices: list[float]) -> dict:
        short_window = int(cfg.get("SHORT_WINDOW", 3))
        long_window = int(cfg.get("LONG_WINDOW", 7))
        min_gap = float(cfg.get("MIN_SIGNAL_GAP", 0.0))
        n = len(prices)

        short_ma = round(sum(prices[-short_window:]) / short_window, 4) if n >= short_window else None
        long_ma = round(sum(prices[-long_window:]) / long_window, 4) if n >= long_window else None
        signal_gap = round(abs(short_ma - long_ma), 4) if short_ma is not None and long_ma is not None else None
        gap_sufficient = signal_gap is not None and signal_gap > min_gap

        if n < long_window or short_ma is None or long_ma is None:
            signal = "HOLD"
            rationale = f"trend policy warming up ({n}/{long_window} ticks)"
        elif not gap_sufficient:
            signal = "HOLD"
            rationale = f"trend gap {signal_gap:.4f} <= MIN_SIGNAL_GAP {min_gap:.4f}"
        elif short_ma > long_ma:
            signal = "BUY"
            rationale = f"short MA {short_ma:.4f} above long MA {long_ma:.4f}"
        elif short_ma < long_ma:
            signal = "SELL"
            rationale = f"short MA {short_ma:.4f} below long MA {long_ma:.4f}"
        else:
            signal = "HOLD"
            rationale = "trend averages overlap — no directional edge"

        return {
            "signal": signal,
            "rationale": rationale,
            "warmed_up": n >= long_window,
            "short_window": short_window,
            "long_window": long_window,
            "min_signal_gap": min_gap,
            "short_ma": short_ma,
            "long_ma": long_ma,
            "signal_gap": signal_gap,
            "gap_sufficient": gap_sufficient,
            "price_count": n,
        }

    def _mr_state(self, symbol: str, cfg: dict, prices: list[float]) -> dict:
        window = int(cfg.get("MEAN_REV_WINDOW", 20))
        threshold = float(cfg.get("MEAN_REV_THRESHOLD", 1.0))
        exit_fraction = float(cfg.get("MEAN_REV_EXIT_FRACTION", 1.0))
        min_vol = float(cfg.get("MIN_VOLATILITY", 0.0))
        min_entry_depth = float(cfg.get("MIN_ENTRY_DEPTH", 0.0))
        max_er = float(cfg.get("MAX_EFFICIENCY_RATIO", 1.0))
        regime_window = int(cfg.get("REGIME_WINDOW", 20))
        n = len(prices)

        if n < window:
            return {
                "signal": "HOLD",
                "rationale": f"mean-reversion policy warming up ({n}/{window} ticks)",
                "warmed_up": False,
                "window": window,
                "threshold": threshold,
                "mean": None,
                "std": None,
                "lower_band": None,
                "upper_band": None,
                "exit_target": None,
                "signal_depth": None,
                "entry_efficiency_ratio": None,
                "dynamic_stop_pct": None,
            }

        recent = prices[-window:]
        mean = sum(recent) / window
        std = math.sqrt(sum((p - mean) ** 2 for p in recent) / window)
        current = prices[-1]
        lower_band = mean - threshold * std
        upper_band = mean + threshold * std
        exit_target = mean - (1.0 - exit_fraction) * threshold * std
        depth = max(0.0, (lower_band - current) / std) if std > 0.0 and current <= lower_band else 0.0
        er = _efficiency_ratio(prices, regime_window)
        dyn_stop = self._mr_dynamic_stop(symbol, current)

        if std <= 0.0:
            signal = "HOLD"
            rationale = "mean-reversion volatility is zero — no edge"
        elif min_vol > 0.0 and std < min_vol and current < exit_target:
            signal = "HOLD"
            rationale = f"mean-reversion std {std:.4f} below MIN_VOLATILITY {min_vol:.4f}"
        elif current <= lower_band:
            if depth < min_entry_depth:
                signal = "HOLD"
                rationale = f"mean-reversion depth {depth:.3f} below MIN_ENTRY_DEPTH {min_entry_depth:.3f}"
            elif er is not None and er > max_er:
                signal = "HOLD"
                rationale = f"mean-reversion gate blocked: ER {er:.3f} > {max_er:.3f}"
            else:
                signal = "BUY"
                rationale = f"mid {current:.4f} below lower band {lower_band:.4f} by {depth:.3f} std"
        elif current >= exit_target:
            signal = "SELL"
            rationale = f"mid {current:.4f} recovered to exit target {exit_target:.4f}"
        else:
            signal = "HOLD"
            rationale = f"mid {current:.4f} inside mean-reversion range around {mean:.4f}"

        return {
            "signal": signal,
            "rationale": rationale,
            "warmed_up": True,
            "window": window,
            "threshold": threshold,
            "mean": round(mean, 4),
            "std": round(std, 4),
            "lower_band": round(lower_band, 4),
            "upper_band": round(upper_band, 4),
            "exit_target": round(exit_target, 4),
            "signal_depth": round(depth, 4),
            "entry_efficiency_ratio": round(er, 4) if er is not None else None,
            "dynamic_stop_pct": round(dyn_stop, 4) if dyn_stop > 0 else None,
        }

    def _mr_dynamic_stop(self, symbol: str, entry_price: float) -> float:
        if entry_price <= 0.0:
            return 0.0
        cfg = get_config()
        fallback = float(cfg.get("STOP_LOSS_PCT", 0.02))
        min_stop = float(cfg.get("MIN_STOP_LOSS_PCT", 0.01))
        prices = self._prices.get(symbol, [])
        atr_mult = float(cfg.get("STOP_ATR_MULT", 0.0))
        if atr_mult > 0.0:
            atr_window = int(cfg.get("ATR_WINDOW", 14))
            atr_val = _atr(prices, atr_window)
            if atr_val > 0.0:
                return max(min_stop, atr_val * atr_mult / entry_price)

        vol_mult = float(cfg.get("MEAN_REV_STOP_VOL_MULT", 0.0))
        window = int(cfg.get("MEAN_REV_WINDOW", 20))
        if vol_mult > 0.0 and len(prices) >= window:
            recent = prices[-window:]
            mean = sum(recent) / window
            std = math.sqrt(sum((p - mean) ** 2 for p in recent) / window)
            if std > 0.0:
                return max(min_stop, (std / entry_price) * vol_mult)
        return fallback

    def _build_rationale(self, state: dict, action: str, bid: float, ask: float, mid: float) -> str:
        policy = state["active_policy"]
        regime = state["market_regime"]
        er = state.get("efficiency_ratio")
        er_txt = f"{er:.3f}" if isinstance(er, float) else "warming"
        if policy == "ma_crossover":
            ma = state["ma_crossover"]
            return (
                f"Trend policy in {regime} regime (ER {er_txt}): {ma['rationale']}. "
                f"Mid {mid:.4f}; buy at ask {ask:.4f} / sell at bid {bid:.4f}."
            )
        if policy == "mean_reversion":
            mr = state["mean_reversion"]
            return (
                f"Mean-reversion policy in {regime} regime (ER {er_txt}): {mr['rationale']}. "
                f"Mid {mid:.4f}; buy at ask {ask:.4f} / sell at bid {bid:.4f}."
            )
        return f"Policy selector warming up: {state['selection_reason']}."

    @staticmethod
    def _hold(symbol: str, data_lane: str, session_type: str, rationale: str) -> BelfortSignal:
        return BelfortSignal(
            symbol=symbol,
            action="hold",
            qty=0,
            order_type="none",
            limit_price=0.0,
            rationale=rationale,
            data_lane=data_lane,
            session_type=session_type,
            generated_at=_now(),
        )


_LIVE_ENGINE = BelfortPolicyEngine("live")


def get_live_policy_state(symbol: str = "SPY") -> dict:
    return _LIVE_ENGINE.get_state(symbol)


def reset_live_policy_engine() -> None:
    _LIVE_ENGINE.reset()


def live_engine() -> BelfortPolicyEngine:
    return _LIVE_ENGINE
