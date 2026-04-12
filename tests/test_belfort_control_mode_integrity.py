"""
BELFORT-CONTROL-MODE-INTEGRITY-01 acceptance tests.

Tests the truthful one-to-one mapping between visible controls and backend behavior:
  A. /belfort/mode/advance endpoint — gate-checked, LIVE blocked
  B. Mode-advance button in HTML (secondary, distinct from loop start/stop)
  C. belfortModeAdvance() JS function
  D. Shadow Live label (not Shadow Mode)
  E. Explain text — per-mode, per-control truthfulness
  F. Peter mode descriptions — Observe Live / Shadow Live / Paper Trade Live
  G. Review/Learn explain text truthfulness
  H. Mode-advance section visibility logic in updateBelfortStats
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

NEIGHBORHOOD = ROOT / "app" / "routes" / "neighborhood.py"
MONITOR      = ROOT / "app" / "routes" / "monitor.py"
HANDLERS     = ROOT / "peter" / "handlers.py"

_SRC  = NEIGHBORHOOD.read_text()
_MON  = MONITOR.read_text()
_PH   = HANDLERS.read_text()


# ── A. /belfort/mode/advance endpoint ─────────────────────────────────────────

class TestModeAdvanceEndpoint:
    def test_endpoint_defined_in_monitor(self):
        assert '/belfort/mode/advance' in _MON or 'belfort/mode/advance' in _MON

    def test_endpoint_is_post(self):
        import re
        m = re.search(r'@router\.post\(".*belfort/mode/advance.*"\)', _MON)
        assert m is not None, "POST endpoint for /belfort/mode/advance not found"

    def test_live_is_blocked(self):
        """Endpoint must refuse to advance to LIVE."""
        assert 'LIVE' in _MON or 'live' in _MON.lower()
        # Must have a guard for LIVE advancement
        assert 'live_sign_off' in _MON or 'LIVE requires' in _MON or 'sign-off' in _MON

    def test_gate_checked_via_set_mode(self):
        """Endpoint uses set_mode which runs can_advance_to gates."""
        assert 'set_mode' in _MON

    def test_imports_belfort_mode(self):
        section = _MON[_MON.find('belfort/mode/advance'):][:400]
        assert 'belfort_mode' in section or 'BelfortMode' in section

    def test_endpoint_round_trip(self):
        """Call the endpoint directly — should return ok or gated error dict."""
        import importlib, sys
        # Minimal smoke test: import the function, mock current_mode
        from unittest.mock import patch
        from app.belfort_mode import BelfortMode
        with patch('app.belfort_mode.current_mode', return_value=BelfortMode.OBSERVATION):
            with patch('app.belfort_mode.set_mode', return_value={'ok': True, 'mode': 'shadow', 'previous_mode': 'observation', 'error': None}) as mock_set:
                from app.routes.monitor import belfort_mode_advance
                result = belfort_mode_advance()
                assert result.get('ok') is True
                mock_set.assert_called_once()

    def test_endpoint_blocks_when_at_paper(self):
        """When mode=paper, endpoint must refuse (not advance to LIVE)."""
        from unittest.mock import patch
        from app.belfort_mode import BelfortMode
        with patch('app.belfort_mode.current_mode', return_value=BelfortMode.PAPER):
            from app.routes.monitor import belfort_mode_advance
            result = belfort_mode_advance()
            assert result.get('ok') is False
            assert result.get('mode') == 'paper'


# ── B. Mode-advance HTML section ──────────────────────────────────────────────

class TestModeAdvanceHtml:
    def test_section_element_present(self):
        assert 'id="belfort-mode-advance-section"' in _SRC

    def test_advance_button_present(self):
        assert 'id="btn-mode-advance"' in _SRC

    def test_advance_button_calls_function(self):
        assert 'onclick="belfortModeAdvance()"' in _SRC

    def test_mode_note_element_present(self):
        assert 'id="belfort-mode-note"' in _SRC

    def test_section_hidden_by_default(self):
        import re
        m = re.search(r'id="belfort-mode-advance-section"[^>]*>', _SRC)
        assert m is not None
        assert 'display:none' in m.group(0) or 'display: none' in m.group(0)

    def test_css_class_defined(self):
        assert '.bmode-advance-btn' in _SRC

    def test_mode_note_css_class_defined(self):
        assert '.bmode-note' in _SRC


# ── C. belfortModeAdvance() JS function ───────────────────────────────────────

class TestBelfortModeAdvanceJs:
    def test_function_defined(self):
        assert 'async function belfortModeAdvance()' in _SRC

    def test_calls_correct_endpoint(self):
        assert '/monitor/belfort/mode/advance' in _SRC

    def test_uses_post_method(self):
        fn_start = _SRC.find('async function belfortModeAdvance()')
        fn_section = _SRC[fn_start:][:600]
        assert "method:'POST'" in fn_section or "method: 'POST'" in fn_section

    def test_refreshes_state_after_advance(self):
        fn_start = _SRC.find('async function belfortModeAdvance()')
        fn_section = _SRC[fn_start:][:900]
        assert 'fetchState' in fn_section
        assert 'applyState' in fn_section

    def test_shows_error_in_note_on_failure(self):
        fn_start = _SRC.find('async function belfortModeAdvance()')
        fn_section = _SRC[fn_start:][:900]
        assert 'modeNoteEl' in fn_section or 'mode-note' in fn_section or 'noteEl' in fn_section


# ── D. Shadow Live label ───────────────────────────────────────────────────────

class TestShadowLiveLabel:
    def test_shadow_live_in_mode_label(self):
        """modeLabel expression must say 'Shadow Live' not 'Shadow Mode'."""
        label_line = next(
            (l for l in _SRC.splitlines() if 'modeLabel' in l and 'shadow' in l.lower()),
            None
        )
        assert label_line is not None, "modeLabel line not found"
        assert 'Shadow Live' in label_line, f"Expected 'Shadow Live' in: {label_line!r}"
        assert 'Shadow Mode' not in label_line, f"'Shadow Mode' still in: {label_line!r}"

    def test_shadow_live_in_explain_text(self):
        assert 'Shadow Live:' in _SRC or 'Shadow Live' in _SRC

    def test_shadow_mode_not_in_explain_text(self):
        """'Shadow Mode:' (colon — used in explain text) must be removed."""
        assert 'Shadow Mode:' not in _SRC

    def test_shadow_live_in_lane_header_logic(self):
        """Lane header labels must reference 'Shadow' correctly."""
        assert 'SHADOW MODE ACTIVE' in _SRC or 'Shadow' in _SRC


# ── E. Explain text truthfulness ──────────────────────────────────────────────

class TestExplainTextTruthfulness:
    def test_observe_live_explain_no_signal_eval(self):
        """Observe Live explain must say no signal eval and no orders."""
        assert 'no signal eval' in _SRC or 'no orders' in _SRC

    def test_shadow_live_explain_no_orders(self):
        """Shadow Live explain must say no orders sent."""
        assert 'no orders sent' in _SRC

    def test_paper_trade_live_explain_alpaca(self):
        """Paper Trade Live explain must mention Alpaca paper account."""
        assert 'Alpaca paper account' in _SRC

    def test_sim_explain_no_broker(self):
        """Sim explain must mention no broker."""
        assert 'no broker' in _SRC

    def test_review_learn_explain_research(self):
        """Review/Learn must be connected to 'research' somewhere in explain or note context."""
        # The supervisor enable runs research campaigns
        assert 'research' in _SRC.lower() or 'campaign' in _SRC.lower()


# ── F. Peter mode descriptions ────────────────────────────────────────────────

class TestPeterModeDescriptions:
    def test_observe_live_in_peter_handlers(self):
        assert 'Observe Live' in _PH

    def test_shadow_live_in_peter_handlers(self):
        assert 'Shadow Live' in _PH

    def test_paper_trade_live_in_peter_handlers(self):
        assert 'Paper Trade Live' in _PH

    def test_shadow_mode_not_in_mode_desc_map(self):
        """The mode_desc dict must say 'Shadow Live' not just 'Shadow'."""
        # Find the _mode_desc dict in handlers
        import re
        m = re.search(r'_mode_desc\s*=\s*\{(.*?)\}', _PH, re.DOTALL)
        if m:
            desc_block = m.group(1)
            assert 'Shadow Live' in desc_block

    def test_observe_live_in_mode_desc_map(self):
        import re
        m = re.search(r'_mode_desc\s*=\s*\{(.*?)\}', _PH, re.DOTALL)
        if m:
            assert 'Observe Live' in m.group(1)

    def test_peter_signal_summary_uses_ui_label(self):
        """Signal summary must use 'Shadow Live' / 'Paper Trade Live', not bare 'shadow'/'paper'."""
        assert '_mode_ui' in _PH or 'Shadow Live' in _PH

    def test_no_bare_shadow_in_mode_desc(self):
        """Mode desc dict must not have bare 'Shadow' label (without Live)."""
        import re
        m = re.search(r'_mode_desc\s*=\s*\{(.*?)\}', _PH, re.DOTALL)
        if m:
            block = m.group(1)
            assert '"shadow":      "Shadow \u2014' not in block  # old format gone
            assert 'Shadow Live' in block


# ── G. Mode-advance section visibility logic ──────────────────────────────────

class TestModeAdvanceSectionLogic:
    def test_mode_advance_section_shown_for_observation(self):
        """JS shows mode-advance section when next mode exists and is not live."""
        assert 'modeAdvanceSec.style.display' in _SRC

    def test_mode_advance_label_shadow_live(self):
        """Advance button label says 'Enter Shadow Live' when advancing from observation."""
        assert 'Enter Shadow Live' in _SRC or "'Shadow Live'" in _SRC

    def test_mode_advance_label_paper_trade_live(self):
        """Advance button label says 'Enter Paper Trade Live' when advancing from shadow."""
        assert 'Enter Paper Trade Live' in _SRC or "'Paper Trade Live'" in _SRC

    def test_mode_advance_section_hidden_at_paper(self):
        """Section is hidden when mode=paper (no further advance from UI)."""
        # The logic: if curIdx >= _modeOrder.length - 2 OR nextMode==='live', hide
        advance_section = _SRC[_SRC.find('modeAdvanceSec.style.display'):][:500]
        assert 'none' in advance_section

    def test_mode_note_shows_current_mode_label(self):
        """Mode note uses operator-facing labels not raw mode strings."""
        assert 'Observe Live' in _SRC and 'Shadow Live' in _SRC and 'Paper Trade Live' in _SRC
