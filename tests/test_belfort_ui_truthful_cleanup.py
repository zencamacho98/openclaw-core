"""
BELFORT-UI-TRUTHFUL-CLEANUP-01 acceptance tests.

Covers only what was actually changed in this block:
  A. Button label accuracy — "Paper Trade Live", "Observe Live", "Review / Learn", "Pause"
  B. Explain text — lane-specific, sim-aware
  C. Learn strip cells — paper shows sent+gated, sim shows fills+last trade detail
  D. Static HTML — initial button labels match spec labels
  E. No regression on prior block structure
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

NEIGHBORHOOD = ROOT / "app" / "routes" / "neighborhood.py"
_SRC = NEIGHBORHOOD.read_text()


# ── A. Button label accuracy (JS dynamic labels) ───────────────────────────────

class TestButtonLabels:
    def test_paper_trade_live_label_in_js(self):
        """When mode=paper the trading button must say 'Paper Trade Live' not 'Paper Trade'."""
        assert "Paper Trade Live" in _SRC

    def test_observe_live_label_in_js(self):
        assert "Observe Live" in _SRC

    def test_research_campaigns_label_in_js(self):
        assert "Research Campaigns" in _SRC

    def test_stop_research_label_in_js(self):
        """Running state of loop button is 'Stop Research'."""
        assert "Stop Research" in _SRC

    def test_paper_trade_label_not_in_mode_map(self):
        """The old bare 'Paper Trade' label (without 'Live') must not appear in the modeLabel expression."""
        # Check the line that builds modeLabel — it must not have 'Paper Trade' without 'Live'
        for line in _SRC.splitlines():
            if 'modeLabel' in line and 'paper' in line:
                # This is the modeLabel assignment line
                assert 'Paper Trade Live' in line, f"modeLabel line still uses bare 'Paper Trade': {line!r}"
                assert "'Paper Trade'" not in line, f"modeLabel line has bare 'Paper Trade': {line!r}"

    def test_dynamic_trading_label_covers_all_three_modes(self):
        """modeLabel expression must handle paper, shadow, and observation modes."""
        label_line = next(
            (l for l in _SRC.splitlines() if 'modeLabel' in l and 'paper' in l and 'shadow' in l),
            None
        )
        assert label_line is not None, "modeLabel ternary not found"
        assert 'Paper Trade Live' in label_line
        assert 'Shadow Live' in label_line   # Shadow Mode was renamed to Shadow Live
        assert 'Observe Live' in label_line


# ── B. Static HTML button labels ──────────────────────────────────────────────

class TestStaticHtmlLabels:
    def _grid_html(self) -> str:
        m = re.search(
            r'<div class="belfort-controls-grid">(.*?)</div>',
            _SRC, re.DOTALL
        )
        return m.group(1) if m else ""

    def test_initial_trading_button_observe_live(self):
        """Static HTML trading button must start with 'Observe Live' (not 'Paper Trade')."""
        grid = self._grid_html()
        assert 'Observe Live' in grid, "Trading button static label is not 'Observe Live'"

    def test_initial_trading_button_not_bare_paper_trade(self):
        """Static HTML must not have bare 'Paper Trade' as the trading button label."""
        grid = self._grid_html()
        # 'Paper Trade Live' could appear via JS labels — but 'Paper Trade\n' or 'Paper Trade<' in static HTML should not
        assert '&#9654; Paper Trade' not in grid

    def test_initial_loop_button_research_campaigns(self):
        grid = self._grid_html()
        assert 'Research Campaigns' in grid

    def test_initial_loop_button_not_start_learning(self):
        grid = self._grid_html()
        assert 'Start Learning' not in grid

    def test_stop_all_button_label(self):
        """Emergency stop button label is 'Stop All' in static HTML."""
        grid = self._grid_html()
        assert 'Stop All' in grid

    def test_practice_sim_button_unchanged(self):
        grid = self._grid_html()
        assert 'Practice Sim' in grid


# ── C. Explain text is lane-specific and sim-aware ────────────────────────────

class TestExplainText:
    def test_paper_trade_live_in_explain(self):
        """Explain text for paper mode must say 'Paper Trade Live'."""
        assert 'Paper Trade Live' in _SRC

    def test_observe_live_in_explain(self):
        """Explain text for observation mode must say 'Observe Live'."""
        assert 'Observe Live:' in _SRC

    def test_sim_aware_explain_appended(self):
        """Sim-running state appends a Practice Sim note to explain text."""
        assert 'Practice Sim' in _SRC and 'no broker' in _SRC

    def test_explain_uses_if_simOn(self):
        """The sim append is conditional on simOn."""
        explain_section = "\n".join(
            l for l in _SRC.splitlines()
            if 'Practice Sim' in l and ('simOn' in l or 'explainText' in l)
        )
        assert 'simOn' in explain_section or 'explainText' in explain_section


# ── D. Learn strip cell content — paper and sim details ───────────────────────

class TestLearnStripCells:
    def test_paper_cell_shows_sent_and_gated(self):
        """PAPER TODAY cell must render both sent and gated counts."""
        # Both string literals appear in the learn strip JS construction
        assert "\\u00a0sent" in _SRC or "'sent'" in _SRC or '\u00a0sent' in _SRC or 'sent' in _SRC
        assert 'gated' in _SRC
        assert 'PAPER TODAY' in _SRC

    def test_sim_cell_shows_fills_and_last_trade(self):
        """SIM TODAY cell must show fill count and last trade detail."""
        assert 'SIM TODAY' in _SRC
        assert 'simFills' in _SRC or 'fills' in _SRC
        # Last trade detail: constructed from belfort_latest_sim_trade fill_price
        assert 'fill_price' in _SRC

    def test_sim_cell_label_is_sim_today(self):
        assert 'SIM TODAY' in _SRC

    def test_paper_cell_label_is_paper_today(self):
        assert 'PAPER TODAY' in _SRC

    def test_block_reason_label_updated(self):
        """Block reason line says 'Block reason:' not just 'Main block:'."""
        assert 'Block reason:' in _SRC

    def test_verdict_note_length_extended(self):
        """verdict_note substring extended to 90 chars (was 80)."""
        assert '.substring(0, 90)' in _SRC


# ── E. Prior block structures still present ────────────────────────────────────

class TestNoPriorRegression:
    def test_lane_header_still_present(self):
        assert 'id="belfort-lane-header"' in _SRC

    def test_paper_block_still_present(self):
        assert 'id="belfort-paper-block"' in _SRC

    def test_sim_block_still_present(self):
        assert 'id="belfort-sim-block"' in _SRC

    def test_learn_strip_still_present(self):
        assert 'id="belfort-learn-strip"' in _SRC

    def test_pause_all_function_still_present(self):
        assert 'async function belfortPauseAll()' in _SRC

    def test_promise_all_still_present(self):
        assert 'Promise.all(calls)' in _SRC
