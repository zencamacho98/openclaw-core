from __future__ import annotations

from app.analog_cockpit import ANALOG_COCKPIT_HTML
from app.routes.neighborhood import _belfort_operator_state


def _scanner_row(symbol: str, *, eligible: bool, label: str, reason: str) -> dict:
    return {
        "symbol": symbol,
        "paper_eligible": eligible,
        "tradeability_label": label,
        "tradeability_reason": reason,
    }


def _base_state() -> dict:
    return {
        "belfort_mode": "paper",
        "belfort_session_type": "closed",
        "sim_active": True,
        "sim_ticks": 18,
        "sim_fills": 1,
        "trading_active": False,
        "belfort_signal_stats_today": {"total": 4, "allowed": 1, "blocked": 3},
        "belfort_paper_exec_stats_today": {"submitted": 0, "filled": 0, "gated": 0},
        "belfort_broker_status": {"is_paper_url": True, "has_credentials": True},
        "belfort_reconciliation": {"halted": False},
        "belfort_focus_symbol": "SOFI",
        "open_positions": [],
        "belfort_paper_focus_symbol": "SPY",
        "belfort_paper_focus_reason": "SPY is Belfort's current paper-eligible name.",
        "belfort_latest_signal": {
            "symbol": "SPY",
            "risk_can_proceed": True,
            "signal_action": "buy",
            "risk_block_reason": "",
        },
        "belfort_latest_paper_exec": {},
        "belfort_latest_paper_fill": {},
        "belfort_latest_sim_record": {"action": "hold", "symbol": "SOFI"},
        "belfort_ticks_today": 18,
        "belfort_scanner": {
            "written_at": "2026-04-14T09:00:00+00:00",
            "universe_size": 12,
            "paper_eligible_count": 2,
            "paper_eligible_focus_symbol": "SPY",
            "paper_eligible_focus_reason": "SPY is Belfort's current paper-eligible name.",
            "leaders": [
                _scanner_row("SOFI", eligible=False, label="watch_only", reason="Watch only for now — not in Belfort's Phase 1 paper universe."),
                _scanner_row("SPY", eligible=True, label="eligible", reason="Eligible for paper trading in Belfort's liquid first phase."),
            ],
            "benchmarks": [],
            "lower_price_watch": [],
        },
    }


class TestPaperOpenReadiness:
    def test_staged_for_open_before_regular_session(self):
        result = _belfort_operator_state(_base_state())
        assert result["verdict"] == "staged_for_open"
        assert result["paper_path_proven"] is True
        assert result["regular_session_open"] is False
        assert result["paper_eligible_focus_symbol"] == "SPY"

    def test_ready_for_operator_start_once_session_opens(self):
        base = _base_state()
        base["belfort_session_type"] = "regular"
        result = _belfort_operator_state(base)
        assert result["verdict"] == "ready_for_operator_start"
        assert result["operator_start_required"] is True
        assert "operator start" in result["summary"].lower()

    def test_ready_for_operator_start_in_pre_market(self):
        base = _base_state()
        base["belfort_session_type"] = "pre_market"
        result = _belfort_operator_state(base)
        assert result["verdict"] == "ready_for_operator_start"
        assert result["paper_session_open"] is True
        assert result["regular_session_open"] is False

    def test_actively_trading_when_loop_is_running(self):
        base = _base_state()
        base["belfort_session_type"] = "regular"
        base["trading_active"] = True
        result = _belfort_operator_state(base)
        assert result["verdict"] == "actively_trading"
        assert result["operator_start_required"] is False

    def test_not_ready_when_no_paper_universe(self):
        base = _base_state()
        base["belfort_scanner"]["paper_eligible_count"] = 0
        base["belfort_scanner"]["paper_eligible_focus_symbol"] = ""
        result = _belfort_operator_state(base)
        assert result["verdict"] == "not_ready"
        assert result["paper_universe_ready"] is False
        assert "no paper-eligible" in result["current_blocker"].lower()

    def test_focus_gap_reason_is_reported(self):
        result = _belfort_operator_state(_base_state())
        assert result["focus_symbol_tradeable"] is False
        assert "paper-eligible focus is SPY" in result["focus_gap_reason"]
        assert result["why_not_trading"]
        assert "remaining_daily_capacity" in result

    def test_closed_session_with_open_positions_is_not_ready(self):
        base = _base_state()
        base["open_positions"] = ["QQQ"]
        result = _belfort_operator_state(base)
        assert result["verdict"] == "not_ready"
        assert result["overnight_inventory_open"] is True
        assert "overnight paper position" in result["current_blocker"].lower()


class TestCurrentUiMarkers:
    def test_trade_workspace_markers_present(self):
        assert "Trade" in ANALOG_COCKPIT_HTML
        assert "Scanner" in ANALOG_COCKPIT_HTML
        assert "Research" in ANALOG_COCKPIT_HTML
        assert "Guide" in ANALOG_COCKPIT_HTML

    def test_belfort_trade_markers_present(self):
        assert "Watchlist" in ANALOG_COCKPIT_HTML
        assert "Current Signal" in ANALOG_COCKPIT_HTML
        assert "Blotter" in ANALOG_COCKPIT_HTML
        assert "Paper Window" in ANALOG_COCKPIT_HTML
        assert "Open Proof" in ANALOG_COCKPIT_HTML

    def test_open_proof_targets_present(self):
        assert 'id="belfort-open-proof"' in ANALOG_COCKPIT_HTML
        assert 'id="belfort-why-not-trading"' in ANALOG_COCKPIT_HTML
        assert 'id="belfort-watchlist"' in ANALOG_COCKPIT_HTML
