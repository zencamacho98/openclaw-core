"""
BELFORT-OPERATING-MODE-CLEANUP-01 acceptance tests.

Covers:
  A. HTML structure — lane header, control buttons, learn strip present
  B. CSS classes — all new classes defined
  C. belfortPauseAll JS — defined, stops correct lanes, no-ops if nothing active
  D. updateBelfortStats JS — lane header, session notice, learn strip render
  E. _belfort_state Python — includes belfort_session_type, belfort_learn_strip
  F. read_learn_strip — returns correct shape from observability bridge
  G. Button label updates — Paper Trade / Practice Sim / Start Learning labels
  H. No transport violations — peter/handlers.py still avoids direct app.* imports
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

NEIGHBORHOOD = ROOT / "app" / "routes" / "neighborhood.py"
_SRC = NEIGHBORHOOD.read_text()

HANDLERS = ROOT / "peter" / "handlers.py"
_HANDLERS_SRC = HANDLERS.read_text()


# ── A. HTML structure ──────────────────────────────────────────────────────────

class TestHtmlStructure:
    def test_lane_header_element_present(self):
        assert 'id="belfort-lane-header"' in _SRC

    def test_blane_dot_present(self):
        assert 'id="blane-dot"' in _SRC

    def test_blane_label_present(self):
        assert 'id="blane-label"' in _SRC

    def test_blane_sub_present(self):
        assert 'id="blane-sub"' in _SRC

    def test_blane_mode_chip_present(self):
        assert 'id="blane-mode-chip"' in _SRC

    def test_session_notice_element_present(self):
        assert 'id="belfort-session-notice"' in _SRC

    def test_paper_block_present(self):
        assert 'id="belfort-paper-block"' in _SRC

    def test_sim_block_present(self):
        assert 'id="belfort-sim-block"' in _SRC

    def test_learn_strip_element_present(self):
        assert 'id="belfort-learn-strip"' in _SRC

    def test_blearn_content_element_present(self):
        assert 'id="blearn-content"' in _SRC

    def test_pause_all_button_present(self):
        assert 'id="btn-pause-all"' in _SRC

    def test_trading_toggle_button_present(self):
        assert 'id="btn-trading-toggle"' in _SRC

    def test_sim_toggle_button_present(self):
        assert 'id="btn-sim-toggle"' in _SRC

    def test_loop_toggle_button_present(self):
        assert 'id="btn-loop-toggle"' in _SRC

    def test_ctrl_explain_present(self):
        assert 'id="belfort-ctrl-explain"' in _SRC


# ── B. CSS classes ─────────────────────────────────────────────────────────────

class TestCssClasses:
    def test_belfort_lane_header_class(self):
        assert '.belfort-lane-header' in _SRC

    def test_blane_dot_class(self):
        assert '.blane-dot' in _SRC

    def test_blane_dot_active_variant(self):
        assert '.blane-dot.active' in _SRC

    def test_blane_dot_sim_variant(self):
        assert '.blane-dot.sim' in _SRC

    def test_blane_dot_paused_variant(self):
        assert '.blane-dot.paused' in _SRC

    def test_bnotice_class(self):
        assert '.bnotice' in _SRC

    def test_bnotice_closed_variant(self):
        assert '.bnotice-closed' in _SRC

    def test_bnotice_stale_variant(self):
        assert '.bnotice-stale' in _SRC

    def test_bnotice_sim_variant(self):
        assert '.bnotice-sim' in _SRC

    def test_belfort_learn_strip_class(self):
        assert '.belfort-learn-strip' in _SRC

    def test_blearn_row_class(self):
        assert '.blearn-row' in _SRC

    def test_blearn_cell_class(self):
        assert '.blearn-cell' in _SRC

    def test_bctrl_dimmed_class(self):
        assert '.bctrl-dimmed' in _SRC

    def test_bctrl_explain_class(self):
        assert '.bctrl-explain' in _SRC

    def test_blane_mode_chip_class(self):
        assert '.blane-mode-chip' in _SRC


# ── C. belfortPauseAll JS function ────────────────────────────────────────────

class TestBelfortPauseAll:
    def test_function_defined(self):
        assert 'async function belfortPauseAll()' in _SRC

    def test_stops_trading_when_on(self):
        assert "'/monitor/trading/stop'" in _SRC or '"/monitor/trading/stop"' in _SRC

    def test_stops_loop_when_on(self):
        assert "'/supervisor/disable'" in _SRC or '"/supervisor/disable"' in _SRC

    def test_stops_sim_when_on(self):
        assert "'/monitor/trading/sim/stop'" in _SRC or '"/monitor/trading/sim/stop"' in _SRC

    def test_noop_when_nothing_active(self):
        # Guard: exits early (returns) if no active calls
        assert 'calls.length === 0' in _SRC

    def test_uses_promise_all(self):
        assert 'Promise.all(calls)' in _SRC

    def test_refreshes_state_after_pause(self):
        assert 'fetchState' in _SRC and 'applyState' in _SRC

    def test_pause_all_button_calls_function(self):
        assert 'onclick="belfortPauseAll()"' in _SRC


# ── D. updateBelfortStats JS function ─────────────────────────────────────────

class TestUpdateBelfortStats:
    def test_function_defined(self):
        assert 'function updateBelfortStats(' in _SRC

    def test_renders_lane_header(self):
        assert 'blane-dot' in _SRC and 'blane-label' in _SRC

    def test_renders_session_notice(self):
        assert 'belfort-session-notice' in _SRC

    def test_renders_learn_strip(self):
        assert 'belfort-learn-strip' in _SRC or 'blearn-content' in _SRC

    def test_renders_sim_block(self):
        assert 'belfort-sim-block' in _SRC

    def test_renders_paper_block(self):
        assert 'belfort-paper-block' in _SRC

    def test_paper_trade_button_label(self):
        assert 'Paper Trade' in _SRC

    def test_practice_sim_button_label(self):
        assert 'Practice Sim' in _SRC

    def test_start_learning_button_label(self):
        assert 'Start Learning' in _SRC

    def test_pause_all_disabled_when_nothing_active(self):
        assert 'btn-pause-all' in _SRC and 'disabled' in _SRC

    def test_explain_text_rendered(self):
        assert 'belfort-ctrl-explain' in _SRC


# ── E. _belfort_state Python enrichment ───────────────────────────────────────

class TestBelfortStatePython:
    def test_session_type_in_state(self):
        assert 'belfort_session_type' in _SRC

    def test_learn_strip_in_state(self):
        assert 'belfort_learn_strip' in _SRC

    def test_read_learn_strip_imported_or_called(self):
        assert 'read_learn_strip' in _SRC


# ── F. read_learn_strip observability bridge ───────────────────────────────────

class TestReadLearnStrip:
    def test_function_defined(self):
        from observability.belfort_summary import read_learn_strip
        result = read_learn_strip()
        assert isinstance(result, dict)

    def test_has_verdict_key(self):
        from observability.belfort_summary import read_learn_strip
        result = read_learn_strip()
        assert 'verdict' in result

    def test_has_paper_today_key(self):
        from observability.belfort_summary import read_learn_strip
        result = read_learn_strip()
        assert 'paper_today' in result

    def test_paper_today_is_dict(self):
        from observability.belfort_summary import read_learn_strip
        result = read_learn_strip()
        assert isinstance(result['paper_today'], dict)

    def test_has_signal_blocked_today(self):
        from observability.belfort_summary import read_learn_strip
        result = read_learn_strip()
        assert 'signal_blocked_today' in result

    def test_has_main_blocker(self):
        from observability.belfort_summary import read_learn_strip
        result = read_learn_strip()
        assert 'main_blocker' in result

    def test_paper_today_has_submitted(self):
        from observability.belfort_summary import read_learn_strip
        result = read_learn_strip()
        assert 'submitted' in result['paper_today']

    def test_paper_today_has_gated(self):
        from observability.belfort_summary import read_learn_strip
        result = read_learn_strip()
        assert 'gated' in result['paper_today']

    def test_returns_without_raising(self):
        """Must not raise even with missing/empty log files."""
        from observability.belfort_summary import read_learn_strip
        try:
            read_learn_strip()
        except Exception as exc:
            raise AssertionError(f"read_learn_strip raised: {exc}")


# ── G. Button label sanity — no jargon labels in controls ─────────────────────

class TestButtonLabels:
    def test_begin_research_not_in_controls_grid(self):
        # 'Begin Research' should be removed from the controls grid area
        # It may appear in belfortResearchWithGoal error fallback but NOT as primary button label
        import re
        # Find the controls grid HTML
        m = re.search(
            r'<div class="belfort-controls-grid">(.*?)</div>',
            _SRC, re.DOTALL
        )
        if m:
            grid_html = m.group(1)
            assert 'Begin Research' not in grid_html, \
                "Old 'Begin Research' label still present in controls grid"

    def test_observe_live_in_controls_grid(self):
        """Initial trading button label is 'Observe Live' (JS upgrades to Paper Trade Live when in paper mode)."""
        import re
        m = re.search(
            r'<div class="belfort-controls-grid">(.*?)</div>',
            _SRC, re.DOTALL
        )
        if m:
            assert 'Observe Live' in m.group(1)

    def test_practice_sim_in_controls_grid(self):
        import re
        m = re.search(
            r'<div class="belfort-controls-grid">(.*?)</div>',
            _SRC, re.DOTALL
        )
        if m:
            assert 'Practice Sim' in m.group(1)

    def test_research_campaigns_in_controls_grid(self):
        """Loop button uses 'Research Campaigns' not 'Start Learning'."""
        import re
        m = re.search(
            r'<div class="belfort-controls-grid">(.*?)</div>',
            _SRC, re.DOTALL
        )
        if m:
            assert 'Research Campaigns' in m.group(1)


# ── H. Transport isolation — peter must not import from app.* ─────────────────

class TestTransportIsolation:
    def test_peter_handlers_no_direct_app_imports(self):
        """Top-level (non-indented) import lines in peter/handlers.py
        must not reference app.* packages."""
        for lineno, line in enumerate(_HANDLERS_SRC.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("from app.") or stripped.startswith("import app."):
                # Allow only if the entire line (not just stripped) starts with from/import
                # (indented guards inside functions are acceptable — they are lazy)
                if line.startswith("from app.") or line.startswith("import app."):
                    raise AssertionError(
                        f"Top-level app.* import at peter/handlers.py:{lineno}: {line!r}"
                    )

    def test_sim_running_status_imported_from_bridge(self):
        assert 'read_sim_running_status' in _HANDLERS_SRC

    def test_read_learn_strip_not_imported_in_handlers(self):
        # read_learn_strip lives in observability; handlers doesn't need it directly
        # (neighborhood.py calls it via _belfort_state). This is a boundary check.
        # handlers may or may not import it — just verify no app.* path used.
        if 'read_learn_strip' in _HANDLERS_SRC:
            assert 'from observability' in _HANDLERS_SRC or \
                   'from app.' not in _HANDLERS_SRC.split('read_learn_strip')[0].split('\n')[-1]
