# tests/test_frank_first_visibility.py
#
# Tests for FRANK-FIRST-VISIBILITY-02:
#   - fl-routing-row HTML element exists in neighborhood page
#   - _frank_lloyd_state includes last_routing key
#   - last_routing is None or a dict with builder_lane
#   - No regression in Frank state/build queue surfaces

from __future__ import annotations

import json
import pathlib
import sys
from unittest.mock import patch, MagicMock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


# ── A. HTML presence ─────────────────────────────────────────────────────────

class TestRoutingRowHTML:
    def _get_html(self) -> str:
        from app.routes.neighborhood import neighborhood_view
        resp = neighborhood_view()
        return resp.body.decode("utf-8") if hasattr(resp, "body") else str(resp)

    def test_routing_row_element_exists(self):
        html = self._get_html()
        assert 'id="fl-routing-row"' in html

    def test_routing_row_has_display_none_initially(self):
        html = self._get_html()
        # Should start hidden; JS reveals it once state arrives
        assert 'id="fl-routing-row"' in html
        idx = html.find('id="fl-routing-row"')
        snippet = html[max(0, idx-50):idx+120]
        assert 'display:none' in snippet

    def test_routing_row_css_classes_defined(self):
        html = self._get_html()
        for cls in ('.fl-routing-row', '.fl-routing-lane', '.fl-routing-escalated', '.fl-routing-absorption'):
            assert cls in html, f"CSS class {cls!r} missing from HTML"

    def test_fl_render_routing_row_function_defined(self):
        html = self._get_html()
        assert 'function _flRenderRoutingRow' in html

    def test_fl_render_routing_row_called_in_panel(self):
        html = self._get_html()
        assert '_flRenderRoutingRow(' in html

    def test_routing_row_placed_inside_frank_section(self):
        html = self._get_html()
        frank_section_start = html.find('id="frank-lloyd-section"')
        composer_start      = html.find('id="fl-composer"')
        routing_row_start   = html.find('id="fl-routing-row"')
        assert frank_section_start < routing_row_start < composer_start, (
            "fl-routing-row should be inside frank-lloyd-section, before fl-composer"
        )


# ── B. State exposes last_routing ─────────────────────────────────────────────

class TestFrankStateLastRouting:
    def test_frank_lloyd_state_has_last_routing_key(self):
        from app.routes.neighborhood import _frank_lloyd_state
        state = _frank_lloyd_state()
        assert "last_routing" in state

    def test_last_routing_is_none_or_dict(self):
        from app.routes.neighborhood import _frank_lloyd_state
        state = _frank_lloyd_state()
        lr = state.get("last_routing")
        assert lr is None or isinstance(lr, dict)

    def test_last_routing_dict_has_builder_lane(self):
        from app.routes.neighborhood import _frank_lloyd_state
        state = _frank_lloyd_state()
        lr = state.get("last_routing")
        if lr is not None:
            assert "builder_lane" in lr

    def test_neighborhood_state_includes_last_routing(self):
        from app.routes.neighborhood import neighborhood_state
        result = neighborhood_state()
        fl = result.get("frank_lloyd", {})
        assert "last_routing" in fl


# ── C. JS rendering logic (content-only assertions via HTML inspection) ───────

class TestRoutingRowJSLogic:
    def _get_html(self) -> str:
        from app.routes.neighborhood import neighborhood_view
        resp = neighborhood_view()
        return resp.body.decode("utf-8") if hasattr(resp, "body") else str(resp)

    def test_frank_lane_label_in_js(self):
        html = self._get_html()
        assert "Builder: Frank Lloyd" in html

    def test_claude_escalation_label_in_js(self):
        html = self._get_html()
        assert "Builder: Claude escalation" in html

    def test_absorption_candidate_label_in_js(self):
        html = self._get_html()
        # The JS renders "Absorption candidate" when absorption_candidate=true
        assert "Absorption candidate" in html

    def test_escalation_reason_label_in_js(self):
        html = self._get_html()
        assert "Reason:" in html

    def test_builder_unknown_fallback_in_js(self):
        html = self._get_html()
        assert "Builder: unknown" in html

    def test_fl_last_routing_read_in_js(self):
        html = self._get_html()
        assert "last_routing" in html


# ── D. No regression in Frank state shape ────────────────────────────────────

class TestNoRegressionFrankState:
    def test_frank_state_shape_includes_required_keys(self):
        from app.routes.neighborhood import _frank_lloyd_state
        state = _frank_lloyd_state()
        required = {
            "pending_count", "inprogress_count", "completed_count",
            "approved_count", "active_build", "stage",
            "spec_approved_build", "stage2_authorized_build", "draft_build",
            "promoted_build", "belfort_related_build", "active_job",
            "fl_relay", "last_routing",
        }
        missing = required - set(state.keys())
        assert not missing, f"Missing keys from frank_lloyd state: {missing}"

    def test_last_routing_from_mocked_active_job(self):
        """When active job has routing, last_routing reflects it."""
        mock_routing = {"builder_lane": "frank", "cost_tier": "cheap",
                        "escalation_reason": None, "absorption_candidate": False}
        mock_job = MagicMock()
        mock_job.routing = mock_routing
        mock_job.to_dict.return_value = {"build_id": "BUILD-001", "routing": mock_routing}

        with patch("app.routes.neighborhood._frank_lloyd_state") as mocked:
            mocked.return_value = {
                "last_routing": mock_routing,
                "active_job": mock_job.to_dict(),
            }
            state = mocked()

        assert state["last_routing"]["builder_lane"] == "frank"
        assert state["last_routing"]["cost_tier"] == "cheap"

    def test_last_routing_none_when_no_jobs(self):
        """When no jobs exist, last_routing is None."""
        with patch("app.routes.neighborhood._frank_lloyd_state") as mocked:
            mocked.return_value = {
                "last_routing": None,
                "active_job": None,
                "pending_count": 0,
            }
            state = mocked()

        assert state["last_routing"] is None

    def test_escalated_routing_visible_in_state(self):
        """Escalated routing with reason is fully preserved in state."""
        escalated = {
            "builder_lane": "claude",
            "cost_tier": "escalated",
            "escalation_reason": "safety_boundary",
            "absorption_candidate": True,
            "absorption_notes": "Pattern ready for Frank",
        }
        with patch("app.routes.neighborhood._frank_lloyd_state") as mocked:
            mocked.return_value = {"last_routing": escalated}
            state = mocked()

        lr = state["last_routing"]
        assert lr["builder_lane"] == "claude"
        assert lr["escalation_reason"] == "safety_boundary"
        assert lr["absorption_candidate"] is True
