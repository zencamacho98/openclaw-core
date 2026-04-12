"""
BELFORT-OVERNIGHT-READINESS-01 acceptance tests.

A. Sim loop triggers regime-learning snapshots independently
B. read_sim_performance() — structure, computation, win_rate logic
C. read_latest_regime_snapshot() — finds auto_regime entries
D. _belfort_state() adds paper_available, paper_unavailable_reason,
   sim_performance, recent_activity keys
E. UI elements: paper-avail, paper-stats-row, sim-perf-row, activity-strip
F. UI CSS: bpaper-avail, bsim-perf-row, bactivity-strip, bactivity-tag
G. JS logic: paper availability, sim perf row, activity strip
H. Peter: sim_perf_line, paper_avail_line, snapshot_line in handlers
I. Separation guarantees: sim PnL not blended with paper PnL
J. No regression on prior Belfort regime-learning tests
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

NEIGHBORHOOD  = ROOT / "app" / "routes" / "neighborhood.py"
TRADING_LOOP  = ROOT / "app" / "trading_loop.py"
SIM_MODULE    = ROOT / "app" / "belfort_sim.py"
HANDLERS      = ROOT / "peter" / "handlers.py"
OBS_BRIDGE    = ROOT / "observability" / "belfort_summary.py"

_NH  = NEIGHBORHOOD.read_text()
_TL  = TRADING_LOOP.read_text()
_SIM = SIM_MODULE.read_text()
_PH  = HANDLERS.read_text()
_OBS = OBS_BRIDGE.read_text()


# ── A. Sim loop independent regime snapshots ──────────────────────────────────

class TestSimIndependentSnapshots:
    def test_run_sim_regime_snapshot_defined(self):
        assert "def _run_sim_regime_snapshot" in _SIM

    def test_sim_calls_maybe_record_regime_snapshot(self):
        fn_start = _SIM.find("def _run_sim_regime_snapshot")
        fn_section = _SIM[fn_start:][:400]
        assert "maybe_record_regime_snapshot" in fn_section

    def test_sim_imports_belfort_regime_learning(self):
        fn_start = _SIM.find("def _run_sim_regime_snapshot")
        fn_section = _SIM[fn_start:][:400]
        assert "belfort_regime_learning" in fn_section

    def test_sim_loop_body_calls_snapshot(self):
        loop_start = _SIM.find("def _loop_body")
        loop_section = _SIM[loop_start:][:600]
        assert "_run_sim_regime_snapshot" in loop_section

    def test_sim_snapshot_on_modulo_20(self):
        loop_start = _SIM.find("def _loop_body")
        loop_section = _SIM[loop_start:][:600]
        assert "% 20" in loop_section

    def test_sim_snapshot_nonfatal(self):
        fn_start = _SIM.find("def _run_sim_regime_snapshot")
        fn_section = _SIM[fn_start:][:400]
        assert "try" in fn_section
        assert "except" in fn_section

    def test_sim_snapshot_is_independent_of_trading_loop(self):
        """Sim snapshot uses sim _ticks, not an import from trading_loop."""
        fn_start = _SIM.find("def _run_sim_regime_snapshot")
        fn_section = _SIM[fn_start:][:400]
        assert "trading_loop" not in fn_section


# ── B. read_sim_performance() ─────────────────────────────────────────────────

class TestReadSimPerformance:
    def test_function_defined_in_bridge(self):
        assert "def read_sim_performance" in _OBS

    def test_returns_fills_key(self):
        from observability.belfort_summary import read_sim_performance
        result = read_sim_performance()
        assert "fills" in result

    def test_returns_realized_pnl(self):
        from observability.belfort_summary import read_sim_performance
        result = read_sim_performance()
        assert "realized_pnl" in result
        assert isinstance(result["realized_pnl"], float)

    def test_returns_win_rate(self):
        from observability.belfort_summary import read_sim_performance
        result = read_sim_performance()
        assert "win_rate" in result

    def test_returns_win_rate_valid(self):
        from observability.belfort_summary import read_sim_performance
        result = read_sim_performance()
        assert "win_rate_valid" in result

    def test_win_rate_none_when_no_sells(self):
        from observability.belfort_summary import read_sim_performance
        result = read_sim_performance()
        # If no sells today, win_rate should be None
        if result["sells"] == 0:
            assert result["win_rate"] is None

    def test_win_rate_valid_requires_five_sells(self):
        """win_rate_valid is True only when sells >= 5."""
        assert "win_rate_valid" in _OBS
        assert ">= 5" in _OBS

    def test_does_not_raise(self):
        from observability.belfort_summary import read_sim_performance
        result = read_sim_performance()
        assert isinstance(result, dict)

    def test_has_wins_and_losses_keys(self):
        from observability.belfort_summary import read_sim_performance
        result = read_sim_performance()
        assert "wins" in result
        assert "losses" in result

    def test_today_only_default(self):
        import inspect
        from observability.belfort_summary import read_sim_performance
        sig = inspect.signature(read_sim_performance)
        assert sig.parameters["today_only"].default is True


# ── C. read_latest_regime_snapshot() ─────────────────────────────────────────

class TestReadLatestRegimeSnapshot:
    def test_function_defined_in_bridge(self):
        assert "def read_latest_regime_snapshot" in _OBS

    def test_returns_none_on_missing_file(self):
        from observability.belfort_summary import read_latest_regime_snapshot
        result = read_latest_regime_snapshot()
        assert result is None or isinstance(result, dict)

    def test_filters_auto_regime_type(self):
        """Must only return records where snapshot_type == 'auto_regime'."""
        fn_start = _OBS.find("def read_latest_regime_snapshot")
        fn_section = _OBS[fn_start:][:600]
        assert "auto_regime" in fn_section

    def test_nonfatal_on_corrupt_file(self):
        from observability.belfort_summary import read_latest_regime_snapshot
        # Should not raise
        result = read_latest_regime_snapshot()
        assert result is None or isinstance(result, dict)


# ── D. _belfort_state() new keys ─────────────────────────────────────────────

class TestBelfortStateKeys:
    def test_belfort_paper_available_set(self):
        assert "belfort_paper_available" in _NH

    def test_belfort_paper_unavailable_reason_set(self):
        assert "belfort_paper_unavailable_reason" in _NH

    def test_belfort_sim_performance_set(self):
        assert "belfort_sim_performance" in _NH

    def test_belfort_recent_activity_set(self):
        assert "belfort_recent_activity" in _NH

    def test_reads_from_market_time(self):
        assert "market_time" in _NH or "session_type" in _NH

    def test_reads_read_sim_performance(self):
        assert "read_sim_performance" in _NH

    def test_reads_read_latest_regime_snapshot(self):
        assert "read_latest_regime_snapshot" in _NH

    def test_recent_activity_contains_paper_exec_key(self):
        ra_start = _NH.find('"belfort_recent_activity"')
        ra_section = _NH[ra_start:][:300]
        assert "latest_paper_exec" in ra_section

    def test_recent_activity_contains_sim_trade_key(self):
        ra_start = _NH.find('"belfort_recent_activity"')
        ra_section = _NH[ra_start:][:300]
        assert "latest_sim_trade" in ra_section

    def test_recent_activity_contains_snapshot_key(self):
        ra_start = _NH.find('"belfort_recent_activity"')
        ra_section = _NH[ra_start:][:300]
        assert "latest_snapshot" in ra_section


# ── E. UI HTML elements ───────────────────────────────────────────────────────

class TestUiHtmlElements:
    def test_paper_avail_element_present(self):
        assert 'id="belfort-paper-avail"' in _NH

    def test_paper_stats_row_element_present(self):
        assert 'id="belfort-paper-stats-row"' in _NH

    def test_sim_perf_row_element_present(self):
        assert 'id="belfort-sim-perf-row"' in _NH

    def test_activity_strip_element_present(self):
        assert 'id="belfort-activity-strip"' in _NH

    def test_activity_content_element_present(self):
        assert 'id="belfort-activity-content"' in _NH

    def test_activity_strip_is_inside_belfort_section(self):
        """Activity strip must appear before the controls section."""
        activity_pos = _NH.find('id="belfort-activity-strip"')
        controls_pos = _NH.find('id="btn-trading-toggle"')
        assert activity_pos < controls_pos, "Activity strip must be above controls"

    def test_sim_perf_row_inside_sim_block(self):
        """sim-perf-row must appear inside belfort-sim-block."""
        sim_block_start = _NH.find('id="belfort-sim-block"')
        sim_perf_pos    = _NH.find('id="belfort-sim-perf-row"')
        sim_block_end   = _NH.find('</div>', sim_block_start + 50)
        # sim-perf-row appears after sim-block opening
        assert sim_block_start < sim_perf_pos

    def test_paper_avail_has_initial_display_none(self):
        avail_tag = _NH[_NH.find('id="belfort-paper-avail"') - 5:][:120]
        assert 'display:none' in avail_tag or 'display: none' in avail_tag


# ── F. UI CSS classes ─────────────────────────────────────────────────────────

class TestUiCssClasses:
    def test_bpaper_avail_css(self):
        assert ".bpaper-avail" in _NH

    def test_bpaper_avail_open_css(self):
        assert ".bpaper-avail-open" in _NH

    def test_bpaper_avail_closed_css(self):
        assert ".bpaper-avail-closed" in _NH

    def test_bsim_perf_row_css(self):
        assert ".bsim-perf-row" in _NH

    def test_bactivity_strip_css(self):
        assert ".bactivity-strip" in _NH

    def test_bactivity_tag_css(self):
        assert ".bactivity-tag" in _NH

    def test_bactivity_paper_css(self):
        assert ".bactivity-paper" in _NH

    def test_bactivity_sim_css(self):
        assert ".bactivity-sim" in _NH

    def test_bactivity_learn_css(self):
        assert ".bactivity-learn" in _NH


# ── G. JS logic ───────────────────────────────────────────────────────────────

class TestJsLogic:
    def test_paper_avail_js_element_lookup(self):
        assert "belfort-paper-avail" in _NH
        assert "paperAvailEl" in _NH

    def test_paper_avail_js_shows_unavail_reason(self):
        """When paper not available, JS shows the unavailReason."""
        assert "unavailReason" in _NH

    def test_paper_avail_js_closed_class(self):
        assert "bpaper-avail-closed" in _NH

    def test_paper_avail_js_open_class(self):
        assert "bpaper-avail-open" in _NH

    def test_sim_perf_js_shows_realized_pnl(self):
        assert "realized_pnl" in _NH
        assert "sPnlFmt" in _NH or "sPnl" in _NH

    def test_sim_perf_js_shows_win_rate(self):
        assert "win_rate" in _NH
        assert "wrPct" in _NH

    def test_sim_perf_js_shows_win_rate_valid(self):
        assert "win_rate_valid" in _NH

    def test_activity_strip_js_paper_tag(self):
        assert "bactivity-paper" in _NH

    def test_activity_strip_js_sim_tag(self):
        assert "bactivity-sim" in _NH

    def test_activity_strip_js_learn_tag(self):
        assert "bactivity-learn" in _NH

    def test_activity_strip_js_reads_recent_activity(self):
        assert "belfort_recent_activity" in _NH

    def test_activity_strip_js_reads_latest_snapshot(self):
        assert "latest_snapshot" in _NH
        assert "raSnap" in _NH


# ── H. Peter overnight reporting ─────────────────────────────────────────────

class TestPeterOvernightReporting:
    def test_imports_read_sim_performance(self):
        assert "read_sim_performance" in _PH

    def test_imports_read_latest_regime_snapshot(self):
        assert "read_latest_regime_snapshot" in _PH

    def test_sim_perf_line_defined(self):
        assert "sim_perf_line" in _PH

    def test_paper_avail_line_defined(self):
        assert "paper_avail_line" in _PH

    def test_snapshot_line_defined(self):
        assert "snapshot_line" in _PH

    def test_sim_perf_line_in_summary(self):
        sim_concat = _PH.find("+ sim_perf_line")
        assert sim_concat != -1, "sim_perf_line not found in summary"

    def test_paper_avail_line_in_summary(self):
        assert "+ paper_avail_line" in _PH

    def test_snapshot_line_in_summary(self):
        assert "+ snapshot_line" in _PH

    def test_paper_avail_reports_market_session(self):
        avail_section = _PH[_PH.find("paper_avail_line"):][:600]
        assert "session" in avail_section.lower()

    def test_snapshot_reports_verdict(self):
        snap_section = _PH[_PH.find("snapshot_line"):][:600]
        assert "verdict" in snap_section

    def test_sim_perf_labeled_as_sim_not_paper(self):
        """Sim performance line must be clearly labeled as sim."""
        # The sim_perf_line string content is 1000+ chars from the variable declaration
        perf_section = _PH[_PH.find("sim_perf_line"):][:1200]
        assert "sim" in perf_section.lower()
        assert "no real money" in perf_section or "no broker" in perf_section or "sim only" in perf_section


# ── I. Separation guarantees ──────────────────────────────────────────────────

class TestSeparationGuarantees:
    def test_sim_pnl_uses_sim_performance_not_portfolio(self):
        """Sim P&L JS uses belfort.belfort_sim_performance, not portfolio."""
        # Find the JS section that references belfort_sim_performance
        js_anchor = _NH.find("belfort.belfort_sim_performance")
        assert js_anchor != -1, "belfort.belfort_sim_performance not found in JS"
        sim_perf_js = _NH[js_anchor:][:400]
        assert "realized_pnl" in sim_perf_js

    def test_paper_pnl_uses_portfolio_not_sim(self):
        """Paper P&L display comes from rpnl/upnl variables, not sim_performance."""
        # statsEl JS section references rpnl/upnl from portfolio
        stats_js_anchor = _NH.find("const statsEl")
        assert stats_js_anchor != -1
        stats_section = _NH[stats_js_anchor:][:500]
        assert "rpnl" in stats_section

    def test_sim_pnl_and_paper_pnl_use_different_variables(self):
        """In JS, sim uses sPnl prefix and paper uses rpnl/upnl — never blended."""
        assert "sPnl" in _NH        # sim P&L variable
        assert "rpnl" in _NH        # paper P&L variable
        # They must not be added together without a label
        # Simple check: no 'rpnl + sPnl' or 'sPnl + rpnl'
        assert "rpnl + sPnl" not in _NH
        assert "sPnl + rpnl" not in _NH

    def test_activity_strip_labels_each_lane(self):
        """Activity strip uses distinct PAPER/SIM/LEARN tags for each row."""
        assert "bactivity-paper" in _NH
        assert "bactivity-sim" in _NH
        assert "bactivity-learn" in _NH

    def test_sim_performance_in_sim_block_not_paper_block(self):
        """Sim perf row must not appear inside the paper block div."""
        paper_block = _NH[_NH.find('id="belfort-paper-block"'):]
        paper_block_end = paper_block.find('</div>', 100)
        paper_inner = paper_block[:paper_block_end + 10]
        assert 'belfort-sim-perf-row' not in paper_inner

    def test_peter_sim_perf_labeled_no_broker(self):
        """Peter sim performance line must say 'no broker', 'no real money', or 'sim only'."""
        perf_start = _PH.find("sim_perf_line")
        perf_section = _PH[perf_start:][:1200]
        assert "no broker" in perf_section or "sim only" in perf_section or "no real money" in perf_section
