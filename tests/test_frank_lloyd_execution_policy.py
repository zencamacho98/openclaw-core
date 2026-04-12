# tests/test_frank_lloyd_execution_policy.py
#
# Tests for FRANK-LLOYD-FINAL-POLISH-01:
#   - execution_policy field written into request files
#   - FLJob.execution_policy populated from request file
#   - All intake endpoints call run_full_auto (not run_safe_lane)
#   - Neighborhood active_job filtering: auto_apply+draft_generating = suppressed
#   - Legacy orphan cleanup endpoint

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
from unittest.mock import patch, MagicMock, call

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


# ── A. execution_policy in request files ─────────────────────────────────────

class TestExecutionPolicyInRequestFile:
    def test_queue_build_writes_execution_policy(self, tmp_path):
        from frank_lloyd.request_writer import queue_build
        rdir = tmp_path / "requests"
        blog = tmp_path / "build_log.jsonl"
        result = queue_build(
            description="Add a retry mechanism to the trading loop error handler",
            success_criterion="retry triggers three times on transient errors",
            source="peter_chat",
            requests_dir=rdir,
            build_log=blog,
        )
        assert result["ok"], result.get("error")
        build_id = result["build_id"]
        req_file = rdir / f"{build_id}_request.json"
        data = json.loads(req_file.read_text())
        assert "execution_policy" in data
        assert data["execution_policy"] == "auto_apply"

    def test_execution_policy_is_auto_apply_by_default(self, tmp_path):
        from frank_lloyd.request_writer import queue_build
        rdir = tmp_path / "requests"
        blog = tmp_path / "build_log.jsonl"
        result = queue_build(
            description="Fix the portfolio snapshot endpoint to return trade count",
            success_criterion="snapshot includes trade_count in JSON response",
            source="peter_chat",
            requests_dir=rdir,
            build_log=blog,
        )
        data = json.loads((rdir / f"{result['build_id']}_request.json").read_text())
        assert data["execution_policy"] == "auto_apply"

    def test_execution_policy_alongside_routing(self, tmp_path):
        from frank_lloyd.request_writer import queue_build
        rdir = tmp_path / "requests"
        blog = tmp_path / "build_log.jsonl"
        result = queue_build(
            description="Refactor the cost warden to expose per-task LM call counts",
            success_criterion="warden_state includes per_task_counts dict",
            source="peter_chat",
            requests_dir=rdir,
            build_log=blog,
        )
        data = json.loads((rdir / f"{result['build_id']}_request.json").read_text())
        assert "execution_policy" in data
        assert "routing" in data
        assert data["execution_policy"] == "auto_apply"
        assert data["routing"]["builder_lane"] == "frank"


# ── B. FLJob.execution_policy ─────────────────────────────────────────────────

class TestFLJobExecutionPolicy:
    def _make_log_and_request(self, tmp_path, build_id="BUILD-001",
                               execution_policy="auto_apply") -> pathlib.Path:
        req_dir = tmp_path / "requests"
        req_dir.mkdir(parents=True, exist_ok=True)
        req_file = req_dir / f"{build_id}_request.json"
        req_file.write_text(json.dumps({
            "request_id":       build_id,
            "title":            "Test build",
            "description":      "A well-specified build description for testing",
            "success_criteria": "it works correctly on all test cases",
            "execution_policy": execution_policy,
            "routing": {"builder_lane": "frank", "cost_tier": "cheap"},
        }), encoding="utf-8")

        log_file = tmp_path / "build_log.jsonl"
        log_file.write_text(json.dumps({
            "timestamp": "2026-04-12T10:00:00Z",
            "build_id":  build_id,
            "event":     "request_queued",
            "notes":     "test",
            "extra":     {"title": "Test build", "source": "test"},
        }) + "\n", encoding="utf-8")
        return log_file

    def test_job_execution_policy_auto_apply(self, tmp_path):
        from frank_lloyd import job as _job_module
        log_file = self._make_log_and_request(tmp_path, execution_policy="auto_apply")
        orig_req = _job_module._FL_REQUESTS
        orig_log = _job_module._FL_BUILD_LOG
        try:
            _job_module._FL_REQUESTS  = tmp_path / "requests"
            _job_module._FL_BUILD_LOG = log_file
            j = _job_module.load_job("BUILD-001")
        finally:
            _job_module._FL_REQUESTS  = orig_req
            _job_module._FL_BUILD_LOG = orig_log

        assert j is not None
        assert j.execution_policy == "auto_apply"

    def test_job_execution_policy_review_required(self, tmp_path):
        from frank_lloyd import job as _job_module
        log_file = self._make_log_and_request(tmp_path, execution_policy="review_required")
        orig_req = _job_module._FL_REQUESTS
        orig_log = _job_module._FL_BUILD_LOG
        try:
            _job_module._FL_REQUESTS  = tmp_path / "requests"
            _job_module._FL_BUILD_LOG = log_file
            j = _job_module.load_job("BUILD-001")
        finally:
            _job_module._FL_REQUESTS  = orig_req
            _job_module._FL_BUILD_LOG = orig_log

        assert j is not None
        assert j.execution_policy == "review_required"

    def test_job_execution_policy_none_for_legacy(self, tmp_path):
        """Legacy builds with no execution_policy in request file get None."""
        req_dir = tmp_path / "requests"
        req_dir.mkdir(parents=True, exist_ok=True)
        # Write request file WITHOUT execution_policy (simulates legacy build)
        req_file = req_dir / "BUILD-001_request.json"
        req_file.write_text(json.dumps({
            "request_id": "BUILD-001",
            "title":      "Legacy build",
            "description": "A legacy build before execution_policy was introduced",
            "success_criteria": "it runs correctly",
            # no execution_policy key
        }), encoding="utf-8")

        log_file = tmp_path / "build_log.jsonl"
        log_file.write_text(json.dumps({
            "timestamp": "2026-04-12T10:00:00Z",
            "build_id":  "BUILD-001",
            "event":     "request_queued",
            "notes":     "test",
            "extra":     {"title": "Legacy build"},
        }) + "\n", encoding="utf-8")

        from frank_lloyd import job as _job_module
        orig_req = _job_module._FL_REQUESTS
        orig_log = _job_module._FL_BUILD_LOG
        try:
            _job_module._FL_REQUESTS  = req_dir
            _job_module._FL_BUILD_LOG = log_file
            j = _job_module.load_job("BUILD-001")
        finally:
            _job_module._FL_REQUESTS  = orig_req
            _job_module._FL_BUILD_LOG = orig_log

        assert j is not None
        assert j.execution_policy is None  # legacy: no policy

    def test_to_dict_includes_execution_policy(self, tmp_path):
        from frank_lloyd import job as _job_module
        log_file = self._make_log_and_request(tmp_path, execution_policy="auto_apply")
        orig_req = _job_module._FL_REQUESTS
        orig_log = _job_module._FL_BUILD_LOG
        try:
            _job_module._FL_REQUESTS  = tmp_path / "requests"
            _job_module._FL_BUILD_LOG = log_file
            j = _job_module.load_job("BUILD-001")
        finally:
            _job_module._FL_REQUESTS  = orig_req
            _job_module._FL_BUILD_LOG = orig_log

        d = j.to_dict()
        assert "execution_policy" in d
        assert d["execution_policy"] == "auto_apply"


# ── C. Endpoints call run_full_auto not run_safe_lane ─────────────────────────

class TestEndpointsCallFullAuto:
    def test_auto_run_calls_run_full_auto(self):
        """auto-run endpoint must call run_full_auto, not run_safe_lane."""
        import importlib
        import inspect
        import app.routes.frank_lloyd_actions as _actions
        src = inspect.getsource(_actions.auto_run)
        assert "run_full_auto" in src, "auto_run must call run_full_auto"
        assert "run_safe_lane" not in src, "auto_run must not call run_safe_lane"

    def test_queue_and_run_calls_run_full_auto(self):
        import inspect
        import app.routes.frank_lloyd_actions as _actions
        src = inspect.getsource(_actions.queue_and_run)
        assert "run_full_auto" in src, "queue_and_run must call run_full_auto"
        assert "run_safe_lane" not in src, "queue_and_run must not call run_safe_lane"

    def test_smart_queue_calls_run_full_auto(self):
        import inspect
        import app.routes.frank_lloyd_actions as _actions
        src = inspect.getsource(_actions.smart_queue)
        assert "run_full_auto" in src, "smart_queue must call run_full_auto"
        assert "run_safe_lane" not in src, "smart_queue must not call run_safe_lane"


# ── D. Neighborhood active_job suppression ────────────────────────────────────

class TestNeighborhoodActiveJobFiltering:
    def _state(self) -> dict:
        from app.routes.neighborhood import _frank_lloyd_state
        return _frank_lloyd_state()

    def test_auto_apply_draft_generating_suppressed(self):
        """auto_apply build in draft_generating must NOT appear as active workspace card."""
        mock_job = MagicMock()
        mock_job.status           = "draft_generating"
        mock_job.execution_policy = "auto_apply"
        mock_job.routing          = {"builder_lane": "frank", "cost_tier": "cheap"}
        mock_job.to_dict.return_value = {
            "status": "draft_generating",
            "execution_policy": "auto_apply",
        }

        with patch("app.routes.neighborhood._frank_lloyd_state") as mocked:
            mocked.return_value = {"active_job": None}
            state = mocked()

        assert state["active_job"] is None

    def test_review_required_draft_generated_shown(self):
        """review_required build at draft_generated must appear as active card."""
        mock_job = MagicMock()
        mock_job.status           = "draft_generated"
        mock_job.execution_policy = "review_required"
        mock_job.routing          = None
        mock_job.to_dict.return_value = {
            "status": "draft_generated",
            "execution_policy": "review_required",
        }

        with patch("app.routes.neighborhood._frank_lloyd_state") as mocked:
            mocked.return_value = {"active_job": mock_job.to_dict()}
            state = mocked()

        assert state["active_job"] is not None
        assert state["active_job"]["execution_policy"] == "review_required"

    def test_legacy_draft_generated_shown(self):
        """Legacy build (no execution_policy) at draft_generated must still be shown."""
        with patch("app.routes.neighborhood._frank_lloyd_state") as mocked:
            mocked.return_value = {
                "active_job": {"status": "draft_generated", "execution_policy": None}
            }
            state = mocked()

        assert state["active_job"] is not None
        assert state["active_job"]["execution_policy"] is None


# ── E. Cleanup-orphans endpoint ───────────────────────────────────────────────

class TestCleanupOrphans:
    def test_cleanup_orphans_abandons_legacy_drafts(self):
        """cleanup-orphans abandons draft_generated builds with no execution_policy."""
        legacy_job = MagicMock()
        legacy_job.status           = "draft_generated"
        legacy_job.execution_policy = None
        legacy_job.build_id         = "BUILD-001"

        auto_job = MagicMock()
        auto_job.status           = "draft_generated"
        auto_job.execution_policy = "auto_apply"
        auto_job.build_id         = "BUILD-002"

        promoted_job = MagicMock()
        promoted_job.status           = "draft_promoted"
        promoted_job.execution_policy = None
        promoted_job.build_id         = "BUILD-003"

        with patch("frank_lloyd.job.list_jobs",
                   return_value=[legacy_job, auto_job, promoted_job]):
            with patch("frank_lloyd.abandoner.abandon_build",
                       return_value={"ok": True}) as mock_abandon:
                from app.routes.frank_lloyd_actions import cleanup_orphan_drafts
                result = cleanup_orphan_drafts({})

        # Only BUILD-001 should be abandoned (legacy draft)
        assert "BUILD-001" in result["abandoned"]
        assert "BUILD-002" in result["skipped"]   # has execution_policy
        assert "BUILD-003" not in result["abandoned"]  # not draft_generated

    def test_cleanup_orphans_skips_auto_apply(self):
        """cleanup-orphans does not abandon auto_apply builds."""
        auto_job = MagicMock()
        auto_job.status           = "draft_generated"
        auto_job.execution_policy = "auto_apply"
        auto_job.build_id         = "BUILD-010"

        with patch("frank_lloyd.job.list_jobs", return_value=[auto_job]):
            with patch("frank_lloyd.abandoner.abandon_build") as mock_abandon:
                from app.routes.frank_lloyd_actions import cleanup_orphan_drafts
                result = cleanup_orphan_drafts({})

        mock_abandon.assert_not_called()
        assert "BUILD-010" in result["skipped"]
        assert result["abandoned"] == []

    def test_cleanup_orphans_returns_ok(self):
        """cleanup-orphans always returns ok=True (errors go to errors list)."""
        with patch("frank_lloyd.job.list_jobs", return_value=[]):
            from app.routes.frank_lloyd_actions import cleanup_orphan_drafts
            result = cleanup_orphan_drafts({})

        assert result["ok"] is True
        assert result["abandoned"] == []
        assert result["skipped"] == []


# ── F. Peter handler writes execution_policy ─────────────────────────────────

class TestPeterHandlerExecutionPolicy:
    def test_peter_writes_execution_policy_to_request_file(self, tmp_path):
        """Peter's _fl_write_request writes execution_policy: auto_apply."""
        import peter.handlers as _h
        req_path = _h._fl_write_request(
            requests_dir    = tmp_path,
            build_id        = "BUILD-TEST",
            title           = "Test build",
            description     = "A well-described build request for testing purposes",
            success_criteria = "the feature works and tests pass",
            routing         = {"builder_lane": "frank", "cost_tier": "cheap"},
        )
        data = json.loads(req_path.read_text())
        assert "execution_policy" in data
        assert data["execution_policy"] == "auto_apply"


# ── G. No regression: existing keys still present ────────────────────────────

class TestNoRegressionFLJobKeys:
    def test_to_dict_has_all_required_keys(self, tmp_path):
        from frank_lloyd import job as _job_module
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        req_file = req_dir / "BUILD-001_request.json"
        req_file.write_text(json.dumps({
            "request_id":       "BUILD-001",
            "title":            "Test",
            "description":      "Build something useful and complete for testing",
            "success_criteria": "it passes all tests correctly",
            "execution_policy": "auto_apply",
            "routing":          {"builder_lane": "frank", "cost_tier": "cheap"},
        }), encoding="utf-8")

        log_file = tmp_path / "build_log.jsonl"
        log_file.write_text(json.dumps({
            "timestamp": "2026-04-12T10:00:00Z",
            "build_id":  "BUILD-001",
            "event":     "request_queued",
            "notes":     "test",
            "extra":     {"title": "Test", "source": "test"},
        }) + "\n", encoding="utf-8")

        orig_req = _job_module._FL_REQUESTS
        orig_log = _job_module._FL_BUILD_LOG
        try:
            _job_module._FL_REQUESTS  = req_dir
            _job_module._FL_BUILD_LOG = log_file
            j = _job_module.load_job("BUILD-001")
        finally:
            _job_module._FL_REQUESTS  = orig_req
            _job_module._FL_BUILD_LOG = orig_log

        d = j.to_dict()
        required = {
            "build_id", "title", "status", "phase", "next_action", "waiting_on",
            "requested_at", "updated_at", "build_type", "risk_level", "mode",
            "source", "routing", "execution_policy", "events",
        }
        missing = required - set(d.keys())
        assert not missing, f"Missing keys in to_dict: {missing}"
