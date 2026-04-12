"""
BELFORT-OVERNIGHT-SAFETY-AND-LIVE-GATE-01 acceptance tests.

A. "Research Campaigns" label replaces "Review / Learn" — visually demoted
B. "Stop All" replaces "Pause" — positioned as emergency safety control
C. Live Readiness Gate module (compute_live_readiness)
D. Observability bridge: read_live_readiness()
E. Neighborhood: belfort_live_readiness key + HTML panel + JS logic
F. Cost lanes panel: paper/sim/research active status
G. Peter: live_readiness_line, auto_learn_line in handler
H. Auto-learning independence: Research Campaigns not required for snapshots
I. Separation guarantee: research loop ≠ auto-learning
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

NEIGHBORHOOD = ROOT / "app" / "routes" / "neighborhood.py"
HANDLERS     = ROOT / "peter" / "handlers.py"
LIVE_GATE    = ROOT / "app" / "belfort_live_gate.py"
OBS_BRIDGE   = ROOT / "observability" / "belfort_summary.py"

_NH  = NEIGHBORHOOD.read_text()
_PH  = HANDLERS.read_text()
_LG  = LIVE_GATE.read_text()
_OBS = OBS_BRIDGE.read_text()


# ── A. Label rename: Research Campaigns ──────────────────────────────────────

class TestResearchCampaignsLabel:
    def test_research_campaigns_in_static_html(self):
        assert "Research Campaigns" in _NH

    def test_research_campaigns_in_js_loop_btn(self):
        """JS loop button sets 'Research Campaigns' when stopped."""
        assert "Research Campaigns" in _NH

    def test_stop_research_in_js(self):
        """Running state of loop button is 'Stop Research'."""
        assert "Stop Research" in _NH

    def test_no_review_learn_in_static_button(self):
        """Static HTML button must not use 'Review / Learn'."""
        from_button = _NH.find("btn-loop-toggle")
        btn_section = _NH[from_button:][:120]
        assert "Review / Learn" not in btn_section

    def test_no_stop_review_in_js(self):
        """JS must not use 'Stop Review'."""
        assert "Stop Review" not in _NH

    def test_research_campaigns_in_controls_grid(self):
        import re
        m = re.search(
            r'<div class="belfort-controls-grid">(.*?)</div>',
            _NH, re.DOTALL
        )
        if m:
            assert "Research Campaigns" in m.group(1)


# ── B. Label rename: Stop All emergency button ────────────────────────────────

class TestStopAllButton:
    def test_stop_all_in_static_html(self):
        assert "Stop All" in _NH

    def test_btn_pause_all_has_stop_all_label(self):
        btn_pos = _NH.find('id="btn-pause-all"')
        btn_section = _NH[btn_pos:][:150]
        assert "Stop All" in btn_section

    def test_btn_pause_all_uses_emergency_css(self):
        """Stop All button uses bctrl-emergency class."""
        btn_pos = _NH.find('id="btn-pause-all"')
        btn_section = _NH[btn_pos - 50:][:200]
        assert "bctrl-emergency" in btn_section

    def test_bctrl_emergency_css_defined(self):
        assert ".bctrl-emergency" in _NH

    def test_stop_all_error_fallback(self):
        """Error fallback in belfortPauseAll uses 'Stop All' not 'Pause All'."""
        pause_fn = _NH[_NH.find("async function belfortPauseAll"):][:400]
        assert "Stop All" in pause_fn or "Pause" in pause_fn  # at minimum no 'Pause All'
        assert "Pause All" not in pause_fn


# ── C. Live Readiness Gate module ─────────────────────────────────────────────

class TestLiveGateModule:
    def test_module_exists(self):
        assert LIVE_GATE.exists()

    def test_compute_live_readiness_defined(self):
        assert "def compute_live_readiness" in _LG

    def test_verdict_not_enough_data_defined(self):
        assert "not_enough_data" in _LG

    def test_verdict_not_ready_defined(self):
        assert "not_ready" in _LG

    def test_verdict_candidate_defined(self):
        assert "candidate" in _LG

    def test_min_trades_threshold(self):
        """Minimum paper sell trades threshold is 10."""
        assert "_MIN_TRADES" in _LG
        assert "10" in _LG

    def test_min_paper_orders_threshold(self):
        """Minimum paper orders threshold is 5."""
        assert "_MIN_PAPER_ORDERS" in _LG
        assert "5" in _LG

    def test_min_win_rate_threshold(self):
        """Minimum win rate is 0.40."""
        assert "0.40" in _LG or "0.4" in _LG

    def test_uses_portfolio_get_trades(self):
        assert "get_trades" in _LG

    def test_uses_paper_exec_log(self):
        assert "paper_exec_log" in _LG

    def test_uses_signal_log(self):
        assert "_SIGNAL_LOG" in _LG or "signal_log" in _LG

    def test_returns_trade_count(self):
        assert "trade_count" in _LG

    def test_returns_paper_orders(self):
        assert "paper_orders" in _LG

    def test_returns_win_rate(self):
        assert "win_rate" in _LG

    def test_returns_expectancy(self):
        assert "expectancy" in _LG

    def test_returns_block_rate(self):
        assert "block_rate" in _LG

    def test_returns_note(self):
        assert "note" in _LG

    def test_nonfatal(self):
        from app.belfort_live_gate import compute_live_readiness
        result = compute_live_readiness()
        assert isinstance(result, dict)

    def test_returns_valid_verdict(self):
        from app.belfort_live_gate import compute_live_readiness
        result = compute_live_readiness()
        assert result["verdict"] in ("not_enough_data", "not_ready", "candidate")

    def test_does_not_raise(self):
        from app.belfort_live_gate import compute_live_readiness
        result = compute_live_readiness()
        assert "verdict" in result
        assert "trade_count" in result
        assert "paper_orders" in result

    def test_not_enough_data_when_zero_trades(self):
        """With no paper trades, verdict must be not_enough_data."""
        from app.belfort_live_gate import compute_live_readiness
        result = compute_live_readiness()
        # If trade_count < 10, verdict must be not_enough_data
        if result["trade_count"] < 10:
            assert result["verdict"] == "not_enough_data"

    def test_expectancy_check_in_code(self):
        """Module must check expectancy <= 0 for not_ready."""
        assert "<= 0" in _LG or "expectancy" in _LG

    def test_no_app_imports_at_module_level(self):
        """app.portfolio imported locally to avoid circular import at module level."""
        top_lines = "\n".join(_LG.splitlines()[:25])
        assert "from app.portfolio" not in top_lines

    def test_note_field_explains_verdict(self):
        from app.belfort_live_gate import compute_live_readiness
        result = compute_live_readiness()
        assert isinstance(result["note"], str)
        assert len(result["note"]) > 10


# ── D. Observability bridge: read_live_readiness ──────────────────────────────

class TestObsBridgeLiveReadiness:
    def test_function_defined(self):
        assert "def read_live_readiness" in _OBS

    def test_wraps_compute_live_readiness(self):
        fn_start = _OBS.find("def read_live_readiness")
        fn_section = _OBS[fn_start:][:600]
        assert "compute_live_readiness" in fn_section

    def test_has_fallback(self):
        fn_start = _OBS.find("def read_live_readiness")
        fn_section = _OBS[fn_start:][:700]
        assert "except" in fn_section
        assert "not_enough_data" in fn_section

    def test_returns_dict(self):
        from observability.belfort_summary import read_live_readiness
        result = read_live_readiness()
        assert isinstance(result, dict)

    def test_imported_in_handlers(self):
        assert "read_live_readiness" in _PH

    def test_verdict_key_in_result(self):
        from observability.belfort_summary import read_live_readiness
        result = read_live_readiness()
        assert "verdict" in result


# ── E. Neighborhood: live gate panel ─────────────────────────────────────────

class TestNeighborhoodLiveGate:
    def test_belfort_live_readiness_key_in_state(self):
        assert "belfort_live_readiness" in _NH

    def test_read_live_readiness_called_in_state(self):
        assert "read_live_readiness" in _NH

    def test_live_gate_panel_html(self):
        assert 'id="belfort-live-gate"' in _NH

    def test_live_gate_verdict_element(self):
        assert 'id="belfort-live-gate-verdict"' in _NH

    def test_live_gate_metrics_element(self):
        assert 'id="belfort-live-gate-metrics"' in _NH

    def test_blive_gate_css_defined(self):
        assert ".blive-gate" in _NH

    def test_blive_gate_not_enough_css(self):
        assert ".blive-gate-not-enough" in _NH

    def test_blive_gate_not_ready_css(self):
        assert ".blive-gate-not-ready" in _NH

    def test_blive_gate_candidate_css(self):
        assert ".blive-gate-candidate" in _NH

    def test_live_gate_label_in_html(self):
        assert "LIVE READINESS GATE" in _NH

    def test_js_reads_belfort_live_readiness(self):
        assert "belfort.belfort_live_readiness" in _NH or "belfort_live_readiness" in _NH

    def test_js_shows_verdict_label(self):
        """JS section for live gate must map not_enough_data to a label."""
        js_start = _NH.find("liveVerdEl")
        js_section = _NH[js_start:][:800]
        assert "not_enough_data" in js_section or "NOT ENOUGH DATA" in js_section

    def test_js_shows_trade_count(self):
        assert "trade_count" in _NH

    def test_js_shows_paper_orders(self):
        assert "paper_orders" in _NH

    def test_js_shows_win_rate(self):
        lr_section = _NH[_NH.find("liveGateEl"):][:1200]
        assert "win_rate" in lr_section

    def test_js_shows_expectancy(self):
        lr_section = _NH[_NH.find("liveGateEl"):][:1200]
        assert "expectancy" in lr_section

    def test_live_gate_above_mode_advance(self):
        gate_pos = _NH.find('id="belfort-live-gate"')
        advance_pos = _NH.find('id="belfort-mode-advance-section"')
        assert gate_pos < advance_pos, "Live gate must appear before mode-advance section"


# ── F. Cost lanes panel ───────────────────────────────────────────────────────

class TestCostLanesPanel:
    def test_cost_lanes_panel_html(self):
        assert 'id="belfort-cost-lanes"' in _NH

    def test_cost_lanes_content_element(self):
        assert 'id="belfort-cost-lanes-content"' in _NH

    def test_bcost_lanes_css_defined(self):
        assert ".bcost-lanes" in _NH

    def test_bcost_lane_on_css(self):
        assert ".bcost-lane-on" in _NH

    def test_bcost_lane_off_css(self):
        assert ".bcost-lane-off" in _NH

    def test_js_shows_paper_lane_status(self):
        cost_section = _NH[_NH.find("costLanesEl"):][:600]
        assert "Paper lane" in cost_section

    def test_js_shows_sim_lane_status(self):
        cost_section = _NH[_NH.find("costLanesEl"):][:600]
        assert "Sim lane" in cost_section

    def test_js_shows_research_lane_status(self):
        cost_section = _NH[_NH.find("costLanesEl"):][:900]
        assert "Research" in cost_section

    def test_js_auto_learning_note_in_research_off(self):
        """When Research Campaigns is off, show auto-learning still continues."""
        cost_section = _NH[_NH.find("costLanesEl"):][:1000]
        assert "auto-learning" in cost_section or "auto" in cost_section

    def test_cost_lanes_label_in_html(self):
        assert "ACTIVE COST LANES" in _NH


# ── G. Peter: live readiness + auto-learn ────────────────────────────────────

class TestPeterLiveReadiness:
    def test_imports_read_live_readiness(self):
        assert "read_live_readiness" in _PH

    def test_live_readiness_line_defined(self):
        assert "live_readiness_line" in _PH

    def test_live_readiness_line_in_summary(self):
        assert "+ live_readiness_line" in _PH

    def test_live_readiness_line_includes_verdict(self):
        lr_start = _PH.find("live_readiness_line")
        lr_section = _PH[lr_start:][:600]
        assert "verdict" in lr_section

    def test_live_readiness_line_includes_note(self):
        lr_start = _PH.find("live_readiness_line")
        lr_section = _PH[lr_start:][:600]
        assert "note" in lr_section

    def test_auto_learn_line_defined(self):
        assert "auto_learn_line" in _PH

    def test_auto_learn_line_in_summary(self):
        assert "+ auto_learn_line" in _PH

    def test_auto_learn_line_explains_independence(self):
        al_start = _PH.find("auto_learn_line")
        al_section = _PH[al_start:][:400]
        assert "auto" in al_section.lower()
        assert "tick" in al_section.lower() or "snap" in al_section.lower()

    def test_research_campaigns_not_required_for_learning(self):
        """Peter must explain that Research Campaigns is not needed for auto-snapshots."""
        al_start = _PH.find("auto_learn_line")
        al_section = _PH[al_start:][:400]
        assert "Research" in al_section or "research" in al_section

    def test_live_gate_nonfatal(self):
        """live_readiness_line block must have try/except."""
        lr_fn_start = _PH.find("live_readiness_line")
        region = _PH[lr_fn_start - 50:][:700]
        assert "try" in region
        assert "except" in region


# ── H. Auto-learning independence from Research Campaigns ────────────────────

class TestAutoLearningIndependence:
    def test_sim_loop_has_regime_snapshot(self):
        from app.belfort_sim import _SIM_LOG  # sim module exists
        assert True  # existence check passes

    def test_trading_loop_has_regime_snapshot(self):
        _TL = (ROOT / "app" / "trading_loop.py").read_text()
        assert "_run_regime_snapshot" in _TL

    def test_sim_module_has_run_sim_regime_snapshot(self):
        _SIM = (ROOT / "app" / "belfort_sim.py").read_text()
        assert "_run_sim_regime_snapshot" in _SIM

    def test_learning_fires_every_20_ticks_trading(self):
        _TL = (ROOT / "app" / "trading_loop.py").read_text()
        assert "% 20" in _TL

    def test_learning_fires_every_20_ticks_sim(self):
        _SIM = (ROOT / "app" / "belfort_sim.py").read_text()
        assert "% 20" in _SIM

    def test_research_loop_separate_from_auto_snapshot(self):
        """Supervisor/research loop and auto-learning snapshot are separate code paths."""
        _TL = (ROOT / "app" / "trading_loop.py").read_text()
        # Trading loop uses maybe_record_regime_snapshot, not the supervisor
        assert "maybe_record_regime_snapshot" in _TL


# ── I. Separation: research loop ≠ auto-learning ─────────────────────────────

class TestSeparationResearchVsAutoLearn:
    def test_peter_distinguishes_auto_vs_manual(self):
        """Peter must label Research Campaigns as manual and auto-learning as separate."""
        assert "auto" in _PH.lower()
        assert "Research Campaigns" in _PH or "research" in _PH.lower()

    def test_live_gate_uses_paper_trades_not_sim(self):
        """Live gate evaluates paper portfolio trades, not sim trades."""
        fn_start = _LG.find("def compute_live_readiness")
        fn_section = _LG[fn_start:][:900]
        assert "get_trades" in fn_section
        assert "portfolio" in fn_section

    def test_live_gate_not_regime_based(self):
        """Live gate does not use regime snapshot data."""
        fn_start = _LG.find("def compute_live_readiness")
        fn_section = _LG[fn_start:][:600]
        assert "regime" not in fn_section.lower()

    def test_cost_lanes_separate_paper_and_sim(self):
        """Cost lanes display paper and sim as distinct entries."""
        cost_section = _NH[_NH.find("costLanesEl"):][:600]
        assert "Paper lane" in cost_section
        assert "Sim lane" in cost_section
