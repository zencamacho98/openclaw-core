from __future__ import annotations

from types import SimpleNamespace

import app.strategy.config as cfg
from app.belfort_policy import BelfortPolicyEngine


def _quote(px: float):
    return SimpleNamespace(
        symbol="SPY",
        bid=px - 0.05,
        ask=px + 0.05,
        data_lane="IEX_ONLY",
        session_type="regular",
    )


def _quote_session(px: float, session_type: str):
    q = _quote(px)
    q.session_type = session_type
    return q


def _set_small_config():
    cfg._cache = {
        **cfg.DEFAULTS,
        "SHORT_WINDOW": 2,
        "LONG_WINDOW": 3,
        "REGIME_WINDOW": 3,
        "REGIME_THRESHOLD": 0.5,
        "MEAN_REV_WINDOW": 4,
        "MEAN_REV_THRESHOLD": 0.8,
        "POSITION_SIZE": 0.1,
    }


class TestBelfortPolicyEngine:
    def test_trending_sequence_selects_ma_crossover(self):
        _set_small_config()
        engine = BelfortPolicyEngine("test")
        last_signal = None
        for px in [100, 101, 102, 103, 104, 105]:
            last_signal = engine.evaluate(_quote(px), {"cash": 10_000.0, "positions": {}})

        state = engine.get_state("SPY")
        assert state["active_policy"] == "ma_crossover"
        assert state["market_regime"] == "trending"
        assert last_signal.action == "buy"

    def test_ranging_sequence_selects_mean_reversion(self):
        _set_small_config()
        engine = BelfortPolicyEngine("test")
        last_signal = None
        for px in [100, 101, 99, 101, 99, 100, 98, 100, 97.5]:
            last_signal = engine.evaluate(_quote(px), {"cash": 10_000.0, "positions": {}})

        state = engine.get_state("SPY")
        assert state["active_policy"] == "mean_reversion"
        assert state["market_regime"] == "ranging"
        assert last_signal.action == "buy"
        assert "lower band" in last_signal.rationale

    def test_pre_market_is_tradeable_for_policy_engine(self):
        _set_small_config()
        engine = BelfortPolicyEngine("test")
        last_signal = None
        for px in [100, 101, 102, 103, 104, 105]:
            last_signal = engine.evaluate(_quote_session(px, "pre_market"), {"cash": 10_000.0, "positions": {}})

        assert last_signal.session_type == "pre_market"
        assert "closed" not in last_signal.rationale.lower()
