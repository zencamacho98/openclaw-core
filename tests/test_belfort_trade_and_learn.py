# tests/test_belfort_trade_and_learn.py
#
# Acceptance tests for BELFORT-TRADE-AND-LEARN-01:
#   A. _SimQuoteProxy overrides session_type and data_lane correctly
#   B. Sim lane start/stop/status API
#   C. Sim fills written to sim_log.jsonl correctly
#   D. Observability bridge reads sim log
#   E. _belfort_state() includes sim fields
#   F. Peter handle_belfort_status includes sim info
#   G. Monitor endpoints exist for sim start/stop

from __future__ import annotations

import inspect
import json
import pathlib
import sys
import threading
import time
from unittest.mock import patch, MagicMock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


# ── A. _SimQuoteProxy ─────────────────────────────────────────────────────────

class TestSimQuoteProxy:
    def _make_proxy(self, data_lane="IEX_ONLY", session_type="closed"):
        from app.belfort_sim import _SimQuoteProxy

        class FakeQuote:
            bid          = 100.0
            ask          = 100.10
            symbol       = "SPY"
            self_data_lane = data_lane
            self_session   = session_type

            def __getattr__(self, name):
                if name == "data_lane":
                    return data_lane
                if name == "session_type":
                    return session_type
                raise AttributeError(name)

        # Build a simple namespace object
        import types
        q = types.SimpleNamespace(
            bid=100.0, ask=100.10, symbol="SPY",
            data_lane=data_lane, session_type=session_type,
        )
        return _SimQuoteProxy(q)

    def test_session_type_always_regular(self):
        """_SimQuoteProxy.session_type must always return 'regular'."""
        proxy = self._make_proxy(session_type="closed")
        assert proxy.session_type == "regular"

    def test_session_type_regular_even_when_after_hours(self):
        proxy = self._make_proxy(session_type="after_hours")
        assert proxy.session_type == "regular"

    def test_data_lane_passed_through_when_not_unknown(self):
        """data_lane IEX_ONLY must be preserved."""
        proxy = self._make_proxy(data_lane="IEX_ONLY")
        assert proxy.data_lane == "IEX_ONLY"

    def test_data_lane_passed_through_sip(self):
        proxy = self._make_proxy(data_lane="SIP_CONSOLIDATED")
        assert proxy.data_lane == "SIP_CONSOLIDATED"

    def test_data_lane_unknown_becomes_iex_only(self):
        """UNKNOWN data_lane must be overridden to IEX_ONLY for sim."""
        proxy = self._make_proxy(data_lane="UNKNOWN")
        assert proxy.data_lane == "IEX_ONLY"

    def test_bid_ask_passed_through(self):
        """Non-overridden attributes must fall through to the wrapped quote."""
        proxy = self._make_proxy()
        assert proxy.bid == 100.0
        assert proxy.ask == 100.10
        assert proxy.symbol == "SPY"

    def test_invalid_ask_is_sanitized_for_sim_training(self):
        """Sim proxy must repair broken overnight books so practice can continue."""
        from app.belfort_sim import _SimQuoteProxy
        import types

        q = types.SimpleNamespace(
            bid=686.0,
            ask=0.0,
            last=685.75,
            symbol="SPY",
            data_lane="IEX_ONLY",
            session_type="closed",
        )
        proxy = _SimQuoteProxy(q)
        assert proxy.quote_sanitized is True
        assert proxy.bid > 0
        assert proxy.ask > 0
        assert proxy.ask >= proxy.bid

    def test_strategy_sees_regular_session(self):
        """MeanReversionV1 must not gate on session_type when given a SimQuoteProxy."""
        from app.belfort_sim import _SimQuoteProxy
        from app.belfort_strategy import MeanReversionV1
        import types

        # Fill the window first so we get a real signal
        strategy = MeanReversionV1(window=4, threshold=0.005)
        for price in [100.0, 99.5, 100.2, 99.8]:
            q = types.SimpleNamespace(bid=price-0.05, ask=price+0.05,
                                      symbol="SPY", data_lane="IEX_ONLY",
                                      session_type="closed")
            strategy.evaluate(_SimQuoteProxy(q))

        q_signal = types.SimpleNamespace(bid=95.0, ask=95.10, symbol="SPY",
                                         data_lane="IEX_ONLY", session_type="closed")
        sig = strategy.evaluate(_SimQuoteProxy(q_signal))
        # With session="closed" raw, without proxy the strategy would hold.
        # With proxy, session_type="regular" so strategy evaluates properly.
        assert sig.session_type == "regular", (
            "Strategy must see 'regular' session via _SimQuoteProxy"
        )
        assert sig.rationale != "outside regular hours — no execution", (
            "Strategy must not gate on session when wrapped by _SimQuoteProxy"
        )


# ── B. Sim lane start/stop/status ─────────────────────────────────────────────

class TestSimLaneControl:
    def test_get_sim_status_returns_dict_shape(self):
        """get_sim_status() must return a dict with all required keys."""
        from app.belfort_sim import get_sim_status
        s = get_sim_status()
        required = {"running", "interval", "ticks", "fills", "started_at",
                    "sim_cash", "sim_position"}
        assert required <= set(s.keys()), f"Missing keys: {required - set(s.keys())}"

    def test_stop_sim_when_not_running(self):
        """stop_sim() when not running must return already_stopped."""
        import app.belfort_sim as _sim
        was_running = _sim._running
        _sim._running = False
        try:
            result = _sim.stop_sim()
            assert result["status"] == "already_stopped"
        finally:
            _sim._running = was_running

    def test_start_sim_spawns_daemon_thread(self):
        """start_sim() must spawn a daemon thread."""
        import app.belfort_sim as _sim
        spawned: list = []
        orig_thread = threading.Thread

        class _CapturingThread:
            def __init__(self, *args, **kwargs):
                spawned.append(kwargs.get("daemon"))
                self._t = orig_thread(*args, **kwargs)
            def start(self):
                pass  # don't actually start — just capture
            def __getattr__(self, name):
                return getattr(self._t, name)

        was_running = _sim._running
        _sim._running = False
        try:
            with patch("app.belfort_sim.threading.Thread", side_effect=_CapturingThread):
                _sim.start_sim(interval=60)
        finally:
            _sim._running = False  # ensure stopped

        assert spawned, "start_sim() must create a Thread"
        assert spawned[0] is True, "Thread must be a daemon thread"

    def test_start_sim_already_running(self):
        """start_sim() must return already_running if sim is active."""
        import app.belfort_sim as _sim
        was_running = _sim._running
        _sim._running = True
        try:
            result = _sim.start_sim()
            assert result["status"] == "already_running"
        finally:
            _sim._running = was_running

    def test_start_sim_resets_portfolio(self):
        """start_sim() must reset sim_cash, sim_position, sim_cost."""
        import app.belfort_sim as _sim
        was_running = _sim._running
        _sim._running = False
        _sim._sim_cash = 1.0
        _sim._sim_position = 99
        try:
            with patch("app.belfort_sim.threading.Thread") as mt:
                mt.return_value = MagicMock()
                _sim.start_sim(interval=60)
            assert _sim._sim_cash == 10_000.0
            assert _sim._sim_position == 0
        finally:
            _sim._running = False


# ── C. Sim fills written correctly ────────────────────────────────────────────

class TestSimFillLog:
    def test_buy_fill_written_to_log(self, tmp_path):
        """A buy fill must be written to sim_log.jsonl with sim=True."""
        import app.belfort_sim as _sim
        orig_log = _sim._SIM_LOG
        sim_log  = tmp_path / "sim_log.jsonl"
        _sim._SIM_LOG = sim_log
        _sim._sim_cash     = 10_000.0
        _sim._sim_position = 0
        _sim._sim_cost     = 0.0
        try:
            fill = _sim._apply_sim_fill("buy", 1, 100.0, "test rationale", "IEX_ONLY")
        finally:
            _sim._SIM_LOG = orig_log

        assert fill is not None, "Buy fill must not return None"
        assert fill["action"] == "buy"
        assert fill["sim"] is True
        assert fill["qty"] == 1
        assert fill["fill_price"] == 100.0
        assert fill["sim_cash"] == pytest_approx(9900.0, abs=0.01)

    def test_sell_fill_written_with_pnl(self, tmp_path):
        """A sell fill must record sim_pnl."""
        import app.belfort_sim as _sim
        _sim._sim_cash     = 9_900.0
        _sim._sim_position = 1
        _sim._sim_cost     = 100.0
        fill = _sim._apply_sim_fill("sell", 1, 102.0, "take profit", "IEX_ONLY")
        assert fill is not None
        assert fill["action"] == "sell"
        assert fill["sim_pnl"] == pytest_approx(2.0, abs=0.01)
        assert fill["sim_position"] == 0

    def test_buy_insufficient_cash_returns_none(self):
        """Buy fill must return None when sim_cash < cost."""
        import app.belfort_sim as _sim
        _sim._sim_cash = 0.0
        fill = _sim._apply_sim_fill("buy", 100, 200.0, "test", "IEX_ONLY")
        assert fill is None

    def test_sell_no_position_returns_none(self):
        """Sell fill must return None when sim_position == 0."""
        import app.belfort_sim as _sim
        _sim._sim_position = 0
        fill = _sim._apply_sim_fill("sell", 1, 100.0, "test", "IEX_ONLY")
        assert fill is None

    def test_write_sim_record_creates_jsonl(self, tmp_path):
        """_write_sim_record must create the log file and write valid JSON."""
        import app.belfort_sim as _sim
        orig_log = _sim._SIM_LOG
        sim_log  = tmp_path / "sim_log.jsonl"
        _sim._SIM_LOG = sim_log
        try:
            _sim._write_sim_record({"action": "hold", "sim": True, "written_at": "2026-04-12T00:00:00+00:00"})
        finally:
            _sim._SIM_LOG = orig_log

        assert sim_log.exists()
        entry = json.loads(sim_log.read_text())
        assert entry["action"] == "hold"
        assert entry["sim"] is True


def pytest_approx(val, abs=None):
    """Simple approx helper to avoid pytest import."""
    class _Approx:
        def __eq__(self, other):
            return builtins_abs(other - val) <= (abs or 0.01)
        def __repr__(self):
            return f"≈{val}±{abs}"
    import builtins
    builtins_abs = builtins.abs
    return _Approx()


# ── D. Observability bridge reads sim log ─────────────────────────────────────

class TestObservabilitySimBridge:
    def test_read_latest_sim_trade_none_when_no_log(self, tmp_path):
        """read_latest_sim_trade() must return None when log doesn't exist."""
        import observability.belfort_summary as bs
        orig = bs._SIM_LOG
        bs._SIM_LOG = tmp_path / "nonexistent_sim.jsonl"
        try:
            result = bs.read_latest_sim_trade()
        finally:
            bs._SIM_LOG = orig
        assert result is None

    def test_read_latest_sim_trade_returns_most_recent_fill(self, tmp_path):
        """read_latest_sim_trade() must return the most recent buy/sell record."""
        import observability.belfort_summary as bs
        sim_log = tmp_path / "sim_log.jsonl"
        records = [
            {"action": "hold", "written_at": "2026-04-12T01:00:00+00:00", "sim": True},
            {"action": "buy",  "written_at": "2026-04-12T01:01:00+00:00", "sim": True, "fill_price": 100.0},
            {"action": "hold", "written_at": "2026-04-12T01:02:00+00:00", "sim": True},
        ]
        sim_log.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        orig = bs._SIM_LOG
        bs._SIM_LOG = sim_log
        try:
            result = bs.read_latest_sim_trade()
        finally:
            bs._SIM_LOG = orig
        assert result is not None
        assert result["action"] == "buy"
        assert result["fill_price"] == 100.0

    def test_read_latest_sim_trade_skips_holds(self, tmp_path):
        """read_latest_sim_trade() must skip hold ticks and find last fill."""
        import observability.belfort_summary as bs
        sim_log = tmp_path / "sim_log.jsonl"
        records = [
            {"action": "sell", "written_at": "2026-04-12T00:00:00+00:00", "sim": True, "fill_price": 99.0},
            {"action": "hold", "written_at": "2026-04-12T00:01:00+00:00", "sim": True},
            {"action": "hold", "written_at": "2026-04-12T00:02:00+00:00", "sim": True},
        ]
        sim_log.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        orig = bs._SIM_LOG
        bs._SIM_LOG = sim_log
        try:
            result = bs.read_latest_sim_trade()
        finally:
            bs._SIM_LOG = orig
        assert result is not None
        assert result["action"] == "sell"

    def test_read_sim_stats_today_counts_correctly(self, tmp_path):
        """read_sim_stats_today() must count fills by type."""
        import observability.belfort_summary as bs
        from datetime import date
        today = date.today().isoformat()
        sim_log = tmp_path / "sim_log.jsonl"
        records = [
            {"action": "buy",  "written_at": f"{today}T01:00:00+00:00", "sim": True},
            {"action": "hold", "written_at": f"{today}T01:01:00+00:00", "sim": True},
            {"action": "sell", "written_at": f"{today}T01:02:00+00:00", "sim": True},
            {"action": "buy",  "written_at": f"{today}T01:03:00+00:00", "sim": True},
        ]
        sim_log.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        orig = bs._SIM_LOG
        bs._SIM_LOG = sim_log
        try:
            stats = bs.read_sim_stats_today()
        finally:
            bs._SIM_LOG = orig
        assert stats["ticks"]  == 4
        assert stats["buys"]   == 2
        assert stats["sells"]  == 1
        assert stats["holds"]  == 1
        assert stats["fills"]  == 3

    def test_read_sim_stats_empty_when_no_log(self, tmp_path):
        """read_sim_stats_today() must return zeroed dict when log missing."""
        import observability.belfort_summary as bs
        orig = bs._SIM_LOG
        bs._SIM_LOG = tmp_path / "no_sim.jsonl"
        try:
            stats = bs.read_sim_stats_today()
        finally:
            bs._SIM_LOG = orig
        assert stats["fills"] == 0
        assert stats["ticks"] == 0

    def test_read_latest_sim_record_includes_holds(self, tmp_path):
        """read_latest_sim_record() must expose the latest hold tick for UI feedback."""
        import observability.belfort_summary as bs
        sim_log = tmp_path / "sim_log.jsonl"
        records = [
            {"action": "buy", "written_at": "2026-04-12T00:00:00+00:00", "sim": True},
            {"action": "hold", "written_at": "2026-04-12T00:01:00+00:00", "sim": True, "rationale": "quote quality gate blocked evaluation"},
        ]
        sim_log.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        orig = bs._SIM_LOG
        bs._SIM_LOG = sim_log
        try:
            result = bs.read_latest_sim_record(today_only=False)
        finally:
            bs._SIM_LOG = orig
        assert result is not None
        assert result["action"] == "hold"
        assert "quote quality" in result["rationale"]


# ── E. _belfort_state() includes sim fields ───────────────────────────────────

class TestBelfortStateSim:
    def test_belfort_state_has_sim_fields(self):
        """_belfort_state() must include sim_active, sim_position, sim_cash, sim_fills."""
        import app.routes.neighborhood as _nb
        state = _nb._belfort_state()
        assert "sim_active"   in state, "sim_active must be in belfort state"
        assert "sim_position" in state, "sim_position must be in belfort state"
        assert "sim_cash"     in state, "sim_cash must be in belfort state"
        assert "sim_fills"    in state, "sim_fills must be in belfort state"

    def test_belfort_state_has_sim_stats_today(self):
        """_belfort_state() must include belfort_sim_stats_today."""
        import app.routes.neighborhood as _nb
        state = _nb._belfort_state()
        # belfort_sim_stats_today is None or a dict
        assert "belfort_sim_stats_today" in state

    def test_belfort_state_has_latest_sim_trade_key(self):
        """_belfort_state() must include belfort_latest_sim_trade key."""
        import app.routes.neighborhood as _nb
        state = _nb._belfort_state()
        assert "belfort_latest_sim_trade" in state

    def test_belfort_state_has_sim_runtime_fields(self):
        """_belfort_state() must include sim runtime heartbeat fields."""
        import app.routes.neighborhood as _nb
        state = _nb._belfort_state()
        assert "sim_ticks" in state
        assert "sim_interval" in state
        assert "sim_started_at" in state


# ── F. Peter handle_belfort_status includes sim ───────────────────────────────

class TestPeterBelfortStatusSim:
    def test_handle_belfort_status_imports_sim_readers(self):
        """handle_belfort_status must reference sim running status via observability bridge."""
        import peter.handlers as _h
        src = inspect.getsource(_h.handle_belfort_status)
        assert "sim" in src.lower(), (
            "handle_belfort_status must include sim lane information"
        )
        # Transport isolation: must NOT import directly from app.belfort_sim
        assert "from app.belfort_sim" not in src, (
            "peter/handlers.py must not import from app.belfort_sim directly — "
            "use the observability bridge"
        )

    def test_handle_belfort_status_returns_ok(self):
        """handle_belfort_status must return a Response with ok=True under normal conditions."""
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command
        cmd    = parse_command("belfort status")
        result = handle_belfort_status(cmd)
        assert result.ok is True
        assert result.command_type == "belfort_status"

    def test_handle_belfort_status_has_sim_metrics(self):
        """handle_belfort_status metrics must include sim_running and sim_fills_today."""
        from peter.handlers import handle_belfort_status
        from peter.commands import parse_command
        cmd    = parse_command("belfort status")
        result = handle_belfort_status(cmd)
        assert "sim_running"     in result.metrics
        assert "sim_fills_today" in result.metrics


# ── G. Monitor endpoints exist ────────────────────────────────────────────────

class TestMonitorSimEndpoints:
    def test_sim_start_endpoint_exists(self):
        """POST /monitor/trading/sim/start must be a registered route."""
        from app.routes.monitor import router
        paths = [r.path for r in router.routes]
        assert any("sim/start" in p for p in paths), (
            f"/trading/sim/start must be registered in monitor router; got: {paths}"
        )

    def test_sim_stop_endpoint_exists(self):
        """POST /monitor/trading/sim/stop must be a registered route."""
        from app.routes.monitor import router
        paths = [r.path for r in router.routes]
        assert any("sim/stop" in p for p in paths)

    def test_sim_status_endpoint_exists(self):
        """GET /monitor/trading/sim/status must be a registered route."""
        from app.routes.monitor import router
        paths = [r.path for r in router.routes]
        assert any("sim/status" in p for p in paths)

    def test_sim_endpoints_call_belfort_sim(self):
        """Sim endpoints must delegate to app.belfort_sim functions."""
        import app.routes.monitor as _m
        src = inspect.getsource(_m)
        assert "belfort_sim" in src, (
            "monitor.py must import from app.belfort_sim for sim endpoints"
        )
        assert "start_sim" in src
        assert "stop_sim"  in src

    def test_js_sim_endpoints_wired(self):
        """neighborhood.py JS must wire sim_start and sim_stop in _BELFORT_ENDPOINTS."""
        import app.routes.neighborhood as _nb
        src = inspect.getsource(_nb)
        assert "sim_start" in src, "sim_start must be in _BELFORT_ENDPOINTS"
        assert "sim_stop"  in src, "sim_stop must be in _BELFORT_ENDPOINTS"
        assert "sim/start" in src, "Endpoint path /monitor/trading/sim/start must be present"

    def test_js_sim_toggle_button_exists(self):
        """neighborhood.py HTML must include btn-sim-toggle button."""
        import app.routes.neighborhood as _nb
        src = inspect.getsource(_nb)
        assert "btn-sim-toggle" in src
        assert "Practice Sim"   in src or "Practice\u00a0Sim" in src or "practice" in src.lower()
