# tests/test_frank_first_tracking.py
#
# Tests for FRANK-FIRST-TRACKING-01:
#   - Routing metadata persisted in request file and build log
#   - FLJob.routing populated from request file
#   - Peter summary includes builder lane on queue
#   - Absorption candidate visibility
#   - Frank neighborhood state exposes last_routing
#   - No regression on builds without routing (backward compat)

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_fl(tmp_path):
    """Provide temp dirs for FL requests and build log."""
    requests_dir = tmp_path / "requests"
    build_log    = tmp_path / "build_log.jsonl"
    return requests_dir, build_log


def _queue_one(requests_dir, build_log, routing=None, **kwargs):
    from frank_lloyd.request_writer import queue_build
    return queue_build(
        description       = kwargs.get("description", "Add a simple hello world endpoint to the API"),
        success_criterion = kwargs.get("success_criterion", "GET /hello returns 200 with greeting"),
        source            = kwargs.get("source", "operator"),
        routing           = routing,
        requests_dir      = requests_dir,
        build_log         = build_log,
    )


# ── A. Routing metadata in request file ───────────────────────────────────────

class TestRoutingInRequestFile:
    def test_default_routing_written_when_none_passed(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        result = _queue_one(requests_dir, build_log)
        assert result["ok"]
        data = json.loads((requests_dir / f"{result['build_id']}_request.json").read_text())
        assert "routing" in data
        r = data["routing"]
        assert r["builder_lane"] == "frank"
        assert r["cost_tier"] == "cheap"
        assert r["escalation_reason"] is None
        assert r["absorption_candidate"] is False
        assert r["routing_decided_by"] == "default"

    def test_custom_routing_persisted(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        custom_routing = {
            "builder_lane":         "claude",
            "model_provider":       "anthropic",
            "model_used":           "claude-sonnet-4-6",
            "cost_tier":            "escalated",
            "escalation_reason":    "safety_boundary",
            "absorption_candidate": True,
            "absorption_notes":     "Frank can learn this pattern",
            "routing_decided_at":   "2026-04-12T00:00:00+00:00",
            "routing_decided_by":   "operator",
        }
        result = _queue_one(requests_dir, build_log, routing=custom_routing)
        assert result["ok"]
        data = json.loads((requests_dir / f"{result['build_id']}_request.json").read_text())
        r = data["routing"]
        assert r["builder_lane"] == "claude"
        assert r["escalation_reason"] == "safety_boundary"
        assert r["absorption_candidate"] is True
        assert r["absorption_notes"] == "Frank can learn this pattern"

    def test_routing_in_build_log_event(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        result = _queue_one(requests_dir, build_log)
        assert result["ok"]
        events = [json.loads(l) for l in build_log.read_text().splitlines() if l.strip()]
        rq = next(e for e in events if e["event"] == "request_queued")
        assert "routing" in rq["extra"]
        assert rq["extra"]["routing"]["builder_lane"] == "frank"

    def test_routing_model_used_uses_cheap_model_env(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        with patch.dict(os.environ, {"CHEAP_MODEL": "openai/gpt-4o-mini-test"}):
            result = _queue_one(requests_dir, build_log)
        data = json.loads((requests_dir / f"{result['build_id']}_request.json").read_text())
        assert data["routing"]["model_used"] == "openai/gpt-4o-mini-test"

    def test_default_routing_model_fallback(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        env = {k: v for k, v in os.environ.items() if k != "CHEAP_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            result = _queue_one(requests_dir, build_log)
        data = json.loads((requests_dir / f"{result['build_id']}_request.json").read_text())
        assert data["routing"]["model_used"] == "openai/gpt-4o-mini"


# ── B. FLJob routing populated from request file ─────────────────────────────

class TestFLJobRouting:
    def test_job_routing_populated_from_request_file(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        result = _queue_one(requests_dir, build_log)
        build_id = result["build_id"]

        from frank_lloyd.job import _build_job, _read_log
        with patch("frank_lloyd.job._FL_BUILD_LOG", build_log), \
             patch("frank_lloyd.job._FL_REQUESTS", requests_dir):
            events = _read_log(build_log)
            job = _build_job(build_id, events)

        assert job is not None
        assert job.routing is not None
        assert job.routing["builder_lane"] == "frank"

    def test_job_routing_in_to_dict(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        result = _queue_one(requests_dir, build_log)
        build_id = result["build_id"]

        from frank_lloyd.job import _build_job, _read_log
        with patch("frank_lloyd.job._FL_BUILD_LOG", build_log), \
             patch("frank_lloyd.job._FL_REQUESTS", requests_dir):
            events = _read_log(build_log)
            job = _build_job(build_id, events)

        d = job.to_dict()
        assert "routing" in d
        assert d["routing"]["builder_lane"] == "frank"

    def test_job_routing_none_for_old_builds_without_routing(self, tmp_fl):
        """Backward compat: builds queued before routing was added have routing=None."""
        requests_dir, build_log = tmp_fl
        # Write a legacy request file without a routing key
        requests_dir.mkdir(parents=True, exist_ok=True)
        req_file = requests_dir / "BUILD-001_request.json"
        req_file.write_text(json.dumps({
            "request_id": "BUILD-001",
            "title": "Legacy build",
            "description": "Add legacy feature to the old system please",
            "requester": "operator",
            "requested_at": "2026-01-01T00:00:00+00:00",
            "success_criteria": "Feature works in prod env",
        }), encoding="utf-8")
        # Write a minimal build log event (no routing in extra)
        event = {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "build_id": "BUILD-001",
            "event": "request_queued",
            "notes": "Request queued by Peter: Legacy build",
            "extra": {"title": "Legacy build", "build_type_hint": ""},
        }
        build_log.write_text(json.dumps(event) + "\n", encoding="utf-8")

        from frank_lloyd.job import _build_job, _read_log
        with patch("frank_lloyd.job._FL_BUILD_LOG", build_log), \
             patch("frank_lloyd.job._FL_REQUESTS", requests_dir):
            events = _read_log(build_log)
            job = _build_job("BUILD-001", events)

        assert job is not None
        assert job.routing is None
        d = job.to_dict()
        assert d["routing"] is None

    def test_job_absorption_candidate_visible(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        custom_routing = {
            "builder_lane": "claude", "cost_tier": "escalated",
            "escalation_reason": "novel_pattern",
            "absorption_candidate": True,
            "absorption_notes": "Candidate for Frank absorption",
            "model_provider": "anthropic", "model_used": "claude-sonnet-4-6",
            "routing_decided_at": "2026-04-12T00:00:00+00:00",
            "routing_decided_by": "operator",
        }
        result = _queue_one(requests_dir, build_log, routing=custom_routing)
        build_id = result["build_id"]

        from frank_lloyd.job import _build_job, _read_log
        with patch("frank_lloyd.job._FL_BUILD_LOG", build_log), \
             patch("frank_lloyd.job._FL_REQUESTS", requests_dir):
            events = _read_log(build_log)
            job = _build_job(build_id, events)

        assert job.routing["absorption_candidate"] is True
        assert "absorption" in job.routing["absorption_notes"].lower()


# ── C. Peter summary includes routing lane ────────────────────────────────────

class TestPeterRoutingVisibility:
    def _run_handle_build_intent(self, tmp_fl, raw_text, nl_intake=False):
        requests_dir, build_log = tmp_fl
        from peter.commands import Command, CommandType
        from peter.handlers import handle_build_intent

        cmd = Command(
            type        = CommandType.BUILD_INTENT,
            raw_text    = raw_text,
            args        = {
                "raw_request": raw_text,
                "nl_intake":   nl_intake,
            },
            transport   = "cli",
            operator_id = "cli",
        )
        with patch("peter.handlers._FL_REQUESTS", requests_dir), \
             patch("peter.handlers._FL_BUILD_LOG", build_log):
            return handle_build_intent(cmd)

    _GOOD_REQUEST = (
        "Add a unit test for the portfolio module. "
        "Success: pytest tests/test_portfolio.py passes without errors"
    )

    def test_summary_includes_frank_lane(self, tmp_fl):
        resp = self._run_handle_build_intent(tmp_fl, self._GOOD_REQUEST)
        assert resp.ok, resp.summary
        assert "Frank Lloyd" in resp.summary
        assert "cheap lane" in resp.summary

    def test_nl_intake_summary_includes_routing(self, tmp_fl):
        resp = self._run_handle_build_intent(tmp_fl, self._GOOD_REQUEST, nl_intake=True)
        assert resp.ok, resp.summary
        assert "cheap lane" in resp.summary

    def test_request_file_contains_routing(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        resp = self._run_handle_build_intent(tmp_fl, self._GOOD_REQUEST)
        assert resp.ok, resp.summary
        build_id = resp.metrics["build_id"]
        req_file = requests_dir / f"{build_id}_request.json"
        data = json.loads(req_file.read_text())
        assert "routing" in data
        assert data["routing"]["builder_lane"] == "frank"

    def test_build_log_contains_routing(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        resp = self._run_handle_build_intent(tmp_fl, self._GOOD_REQUEST)
        assert resp.ok, resp.summary
        events = [json.loads(l) for l in build_log.read_text().splitlines() if l.strip()]
        rq = next(e for e in events if e["event"] == "request_queued")
        assert "routing" in rq["extra"]


# ── D. Frank neighborhood state exposes last_routing ─────────────────────────

class TestNeighborhoodRoutingVisibility:
    def test_frank_lloyd_state_has_last_routing_key(self):
        from app.routes.neighborhood import _frank_lloyd_state
        state = _frank_lloyd_state()
        assert "last_routing" in state

    def test_last_routing_is_none_or_dict(self):
        from app.routes.neighborhood import _frank_lloyd_state
        state = _frank_lloyd_state()
        lr = state.get("last_routing")
        assert lr is None or isinstance(lr, dict)

    def test_last_routing_from_active_job(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        result = _queue_one(requests_dir, build_log)
        build_id = result["build_id"]

        mock_job = MagicMock()
        mock_job.routing = {"builder_lane": "frank", "cost_tier": "cheap"}
        mock_job.to_dict.return_value = {
            "build_id": build_id, "routing": mock_job.routing,
        }

        with patch("app.routes.neighborhood._frank_lloyd_state") as mock_state:
            mock_state.return_value = {
                "last_routing": mock_job.routing,
                "active_job": mock_job.to_dict(),
            }
            state = mock_state()

        assert state["last_routing"]["builder_lane"] == "frank"

    def test_last_routing_escalated_shows_claude(self, tmp_fl):
        """When routing is escalated, last_routing shows claude lane."""
        requests_dir, build_log = tmp_fl
        escalated = {
            "builder_lane": "claude", "cost_tier": "escalated",
            "escalation_reason": "safety_boundary",
            "absorption_candidate": False, "absorption_notes": "",
            "model_provider": "anthropic", "model_used": "claude-sonnet-4-6",
            "routing_decided_at": "2026-04-12T00:00:00+00:00",
            "routing_decided_by": "operator",
        }
        result = _queue_one(requests_dir, build_log, routing=escalated)
        build_id = result["build_id"]

        from frank_lloyd.job import _build_job, _read_log
        with patch("frank_lloyd.job._FL_BUILD_LOG", build_log), \
             patch("frank_lloyd.job._FL_REQUESTS", requests_dir):
            events = _read_log(build_log)
            job = _build_job(build_id, events)

        assert job.routing["builder_lane"] == "claude"
        assert job.routing["escalation_reason"] == "safety_boundary"


# ── E. Regression — existing queue_build callers still work ──────────────────

class TestNoRegression:
    def test_queue_build_without_routing_param_still_works(self, tmp_fl):
        """Callers that don't pass routing= still get a valid result."""
        requests_dir, build_log = tmp_fl
        from frank_lloyd.request_writer import queue_build
        result = queue_build(
            description="Add a simple endpoint to the codebase now",
            success_criterion="GET /ping returns 200 with pong body",
            source="neighborhood_ui",
            requests_dir=requests_dir,
            build_log=build_log,
        )
        assert result["ok"]
        data = json.loads((requests_dir / f"{result['build_id']}_request.json").read_text())
        assert "routing" in data
        assert data["routing"]["builder_lane"] == "frank"

    def test_queue_build_result_shape_unchanged(self, tmp_fl):
        """Return shape still contains ok, build_id, title, request_path, error."""
        requests_dir, build_log = tmp_fl
        result = _queue_one(requests_dir, build_log)
        for key in ("ok", "build_id", "title", "request_path", "error"):
            assert key in result

    def test_multiple_builds_get_independent_routing(self, tmp_fl):
        requests_dir, build_log = tmp_fl
        r1 = _queue_one(requests_dir, build_log)
        r2 = _queue_one(
            requests_dir, build_log,
            routing={
                "builder_lane": "claude", "cost_tier": "escalated",
                "escalation_reason": "ambiguous_spec",
                "absorption_candidate": False, "absorption_notes": "",
                "model_provider": "anthropic", "model_used": "claude-sonnet-4-6",
                "routing_decided_at": "2026-04-12T00:00:00+00:00",
                "routing_decided_by": "operator",
            },
            description="Refactor the authentication middleware for compliance requirements",
            success_criterion="All auth tests pass and no regressions in CI",
        )
        d1 = json.loads((requests_dir / f"{r1['build_id']}_request.json").read_text())
        d2 = json.loads((requests_dir / f"{r2['build_id']}_request.json").read_text())
        assert d1["routing"]["builder_lane"] == "frank"
        assert d2["routing"]["builder_lane"] == "claude"
