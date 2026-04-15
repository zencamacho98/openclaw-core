from __future__ import annotations

from app.analog_cockpit import ANALOG_COCKPIT_HTML


class TestBelfortTradingDeskTruth:
    def test_trade_tab_is_the_default_workspace(self):
        assert "setBelfortWorkspace('trade')" in ANALOG_COCKPIT_HTML
        assert 'id="belfort-pane-trade"' in ANALOG_COCKPIT_HTML

    def test_trade_surface_uses_operator_first_markers(self):
        assert "Trading Shortlist" in ANALOG_COCKPIT_HTML
        assert "Market Pulse" in ANALOG_COCKPIT_HTML
        assert "Current Signal" in ANALOG_COCKPIT_HTML
        assert "Recent Trading Flow" in ANALOG_COCKPIT_HTML
        assert "Opening-Drive Leaders" in ANALOG_COCKPIT_HTML
        assert "Trade Console" in ANALOG_COCKPIT_HTML
        assert "Paper Window" in ANALOG_COCKPIT_HTML
        assert "Why Not Trading" in ANALOG_COCKPIT_HTML
        assert "Open Proof" in ANALOG_COCKPIT_HTML
        assert "Order capacity" in ANALOG_COCKPIT_HTML
        assert "Order Monitor" in ANALOG_COCKPIT_HTML
        assert "Live chart" in ANALOG_COCKPIT_HTML
        assert "Close All Positions" in ANALOG_COCKPIT_HTML

    def test_research_surface_keeps_non_immediate_context(self):
        assert "Research" in ANALOG_COCKPIT_HTML
        assert "Setup Scorecards" in ANALOG_COCKPIT_HTML
        assert "Adjustment Desk" in ANALOG_COCKPIT_HTML
        assert "Blotter" in ANALOG_COCKPIT_HTML

    def test_scanner_surface_keeps_market_context(self):
        assert "Setup Radar" in ANALOG_COCKPIT_HTML
        assert "Catalyst Desk" in ANALOG_COCKPIT_HTML
        assert "Tape Context" in ANALOG_COCKPIT_HTML
        assert "Leaderboards" in ANALOG_COCKPIT_HTML
        assert "Scanner Overview" in ANALOG_COCKPIT_HTML
        assert "Radar Detail" in ANALOG_COCKPIT_HTML

    def test_tradeability_and_proof_targets_exist(self):
        assert 'id="belfort-watchlist"' in ANALOG_COCKPIT_HTML
        assert 'id="belfort-open-proof"' in ANALOG_COCKPIT_HTML
        assert 'id="belfort-why-not-trading"' in ANALOG_COCKPIT_HTML
        assert "Eligible" in ANALOG_COCKPIT_HTML
        assert 'id="belfort-chart-toolbar"' in ANALOG_COCKPIT_HTML
        assert 'id="belfort-opening-drive-strip"' in ANALOG_COCKPIT_HTML
        assert "setBelfortChartTimeframe(" in ANALOG_COCKPIT_HTML
        assert 'id="belfort-scanner-setup-toolbar"' in ANALOG_COCKPIT_HTML
        assert 'id="belfort-radar-detail"' in ANALOG_COCKPIT_HTML
        assert 'id="belfort-scanner-cap-filter-toolbar"' in ANALOG_COCKPIT_HTML
        assert 'id="belfort-scanner-float-filter-toolbar"' in ANALOG_COCKPIT_HTML
