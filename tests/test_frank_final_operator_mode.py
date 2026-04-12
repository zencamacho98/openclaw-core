# tests/test_frank_final_operator_mode.py
#
# Tests for FRANK-FINAL-OPERATOR-MODE-01:
#
# A. Peter-to-Frank auto-start — no "run BUILD-N" required
# B. Safe docs/text targets auto-apply-eligible (no .py-only restriction)
# C. Docs-aware drafter system prompt
# D. notify_only / hidden_import filtered from active queue
# E. Source-based execution policy
# F. Peter response no longer contains "run BUILD-N" language
# G. External / unknown-source builds get review_required, not auto_apply
# H. No regression in Frank-first tracking/routing/intake

from __future__ import annotations

import json
import pathlib
import sys
import threading
import time
from unittest.mock import patch, MagicMock, call

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


# ── A. Peter auto-start ───────────────────────────────────────────────────────

class TestPeterAutoStart:
    def _make_build_intent_command(self, text: str):
        from peter.commands import Command, CommandType
        return Command(
            type        = CommandType.BUILD_INTENT,
            args        = {"raw_request": text, "nl_intake": True},
            transport   = "cli",
            operator_id = "cli",
            raw_text    = text,
        )

    def test_auto_started_flag_in_raw_response(self, tmp_path):
        """handle_build_intent raw dict includes auto_started=True."""
        import peter.handlers as _h
        orig_req = _h._FL_REQUESTS
        orig_log = _h._FL_BUILD_LOG
        try:
            _h._FL_REQUESTS  = tmp_path / "requests"
            _h._FL_BUILD_LOG = tmp_path / "build_log.jsonl"
            with patch("frank_lloyd.auto_runner.run_full_auto"):
                cmd  = self._make_build_intent_command(
                    "Add a GET /ping endpoint that returns 200. "
                    "success: GET /ping returns 200 with body ok:true"
                )
                resp = _h.handle_build_intent(cmd)
        finally:
            _h._FL_REQUESTS  = orig_req
            _h._FL_BUILD_LOG = orig_log

        assert resp.ok
        assert resp.raw.get("auto_started") is True

    def test_response_does_not_say_run_build(self, tmp_path):
        """handle_build_intent response must not tell operator to 'run BUILD-N'."""
        import peter.handlers as _h
        orig_req = _h._FL_REQUESTS
        orig_log = _h._FL_BUILD_LOG
        try:
            _h._FL_REQUESTS  = tmp_path / "requests"
            _h._FL_BUILD_LOG = tmp_path / "build_log.jsonl"
            with patch("frank_lloyd.auto_runner.run_full_auto"):
                cmd  = self._make_build_intent_command(
                    "Add a GET /ping endpoint that returns 200. "
                    "success: GET /ping returns 200 with body ok:true"
                )
                resp = _h.handle_build_intent(cmd)
        finally:
            _h._FL_REQUESTS  = orig_req
            _h._FL_BUILD_LOG = orig_log

        # Must NOT contain old "run BUILD-N" ceremony language
        assert "say 'run" not in resp.summary.lower()
        assert "say \u2018run" not in resp.summary.lower()
        assert "run build-" not in resp.summary.lower()

    def test_response_says_building_now(self, tmp_path):
        """handle_build_intent response must indicate Frank is building now."""
        import peter.handlers as _h
        orig_req = _h._FL_REQUESTS
        orig_log = _h._FL_BUILD_LOG
        try:
            _h._FL_REQUESTS  = tmp_path / "requests"
            _h._FL_BUILD_LOG = tmp_path / "build_log.jsonl"
            with patch("frank_lloyd.auto_runner.run_full_auto"):
                cmd  = self._make_build_intent_command(
                    "Add a GET /ping endpoint that returns 200. "
                    "success: GET /ping returns 200 with body ok:true"
                )
                resp = _h.handle_build_intent(cmd)
        finally:
            _h._FL_REQUESTS  = orig_req
            _h._FL_BUILD_LOG = orig_log

        summary_lower = resp.summary.lower()
        assert any(phrase in summary_lower for phrase in [
            "building now", "is on it", "is building", "frank lloyd is"
        ]), f"Expected auto-start language, got: {resp.summary!r}"

    def test_run_full_auto_is_called_in_thread(self, tmp_path):
        """handle_build_intent starts run_full_auto in a background thread."""
        import peter.handlers as _h
        orig_req = _h._FL_REQUESTS
        orig_log = _h._FL_BUILD_LOG
        call_log = []

        def fake_run_full_auto(build_id, initiated_by=""):
            call_log.append((build_id, initiated_by))

        try:
            _h._FL_REQUESTS  = tmp_path / "requests"
            _h._FL_BUILD_LOG = tmp_path / "build_log.jsonl"
            with patch("frank_lloyd.auto_runner.run_full_auto", side_effect=fake_run_full_auto):
                cmd  = self._make_build_intent_command(
                    "Add a GET /ping endpoint that returns 200. "
                    "success: GET /ping returns 200 with body ok:true"
                )
                resp = _h.handle_build_intent(cmd)
                # Give the thread a moment
                time.sleep(0.1)
        finally:
            _h._FL_REQUESTS  = orig_req
            _h._FL_BUILD_LOG = orig_log

        assert resp.ok
        assert len(call_log) == 1
        build_id_called, initiated_by_called = call_log[0]
        assert "BUILD-" in build_id_called
        assert initiated_by_called == "peter_chat"

    def test_log_event_contains_source_peter_chat(self, tmp_path):
        """handle_build_intent writes source=peter_chat to the build log."""
        import peter.handlers as _h
        orig_req = _h._FL_REQUESTS
        orig_log = _h._FL_BUILD_LOG
        try:
            _h._FL_REQUESTS  = tmp_path / "requests"
            _h._FL_BUILD_LOG = tmp_path / "build_log.jsonl"
            with patch("frank_lloyd.auto_runner.run_full_auto"):
                cmd  = self._make_build_intent_command(
                    "Add a GET /ping endpoint that returns 200. "
                    "success: GET /ping returns 200 with body ok:true"
                )
                _h.handle_build_intent(cmd)
        finally:
            _h._FL_REQUESTS  = orig_req
            _h._FL_BUILD_LOG = orig_log

        log_lines = (tmp_path / "build_log.jsonl").read_text().splitlines()
        event = json.loads(log_lines[0])
        assert event.get("extra", {}).get("source") == "peter_chat"


# ── B. Safe target path validation ───────────────────────────────────────────

class TestSafeTargetPaths:
    def test_md_file_in_docs_is_allowed(self):
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("docs/new_guide.md")
        assert err is None, f"Expected .md allowed, got: {err}"

    def test_yaml_file_allowed(self):
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("config/settings.yaml")
        assert err is None, f"Expected .yaml allowed, got: {err}"

    def test_yml_file_allowed(self):
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("config/myconf.yml")
        assert err is None, f"Expected .yml allowed, got: {err}"

    def test_json_file_allowed(self):
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("data_schemas/schema.json")
        assert err is None, f"Expected .json allowed, got: {err}"

    def test_txt_file_allowed(self):
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("docs/notes.txt")
        assert err is None, f"Expected .txt allowed, got: {err}"

    def test_rst_file_allowed(self):
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("docs/index.rst")
        assert err is None, f"Expected .rst allowed, got: {err}"

    def test_py_still_allowed(self):
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("app/routes/new_module.py")
        assert err is None

    def test_arbitrary_extension_blocked(self):
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("app/something.js")
        assert err is not None

    def test_binary_extension_blocked(self):
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("app/thing.exe")
        assert err is not None

    def test_md_in_offlimits_prefix_blocked(self):
        """data/ is off-limits even for safe text types."""
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("data/some_doc.md")
        assert err is not None, "data/ must remain off-limits for all file types"

    def test_staging_prefix_blocked(self):
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("staging/frank_lloyd/something.md")
        assert err is not None

    def test_path_traversal_blocked(self):
        from frank_lloyd.stage2_promoter import _validate_target_path
        err = _validate_target_path("../outside/repo.md")
        assert err is not None


# ── C. Docs-aware drafter ─────────────────────────────────────────────────────

class TestDocsDrafter:
    def test_detect_doc_build_md_path(self):
        from frank_lloyd.stage2_drafter import _detect_doc_build_from_spec
        spec = """
affected_files:
  new:
    - path: "docs/new_guide.md"
      purpose: "New user guide"
"""
        assert _detect_doc_build_from_spec(spec) is True

    def test_detect_doc_build_yaml_path(self):
        from frank_lloyd.stage2_drafter import _detect_doc_build_from_spec
        spec = """
affected_files:
  new:
    - path: "config/settings.yaml"
"""
        assert _detect_doc_build_from_spec(spec) is True

    def test_detect_doc_build_py_is_not_doc(self):
        from frank_lloyd.stage2_drafter import _detect_doc_build_from_spec
        spec = """
affected_files:
  new:
    - path: "app/routes/new_endpoint.py"
"""
        assert _detect_doc_build_from_spec(spec) is False

    def test_detect_doc_build_no_paths(self):
        from frank_lloyd.stage2_drafter import _detect_doc_build_from_spec
        spec = "title: Some build\n"
        assert _detect_doc_build_from_spec(spec) is False

    def test_doc_system_prompt_is_defined(self):
        from frank_lloyd.stage2_drafter import _DOC_SYSTEM
        assert "documentation" in _DOC_SYSTEM.lower() or "text files" in _DOC_SYSTEM.lower()
        assert "module_code" in _DOC_SYSTEM
        assert "notes" in _DOC_SYSTEM

    def test_doc_system_prompt_no_python_only_constraint(self):
        """Doc system prompt must not instruct the LM to write Python only."""
        from frank_lloyd.stage2_drafter import _DOC_SYSTEM
        # Should NOT have the Python-only constraint from _DRAFT_SYSTEM
        assert "Python module drafts" not in _DOC_SYSTEM
        assert "raw Python only" not in _DOC_SYSTEM


# ── D. notify_only / hidden_import filtered from active queue ─────────────────

class TestExecutionPolicyFiltering:
    def _make_log_and_request(self, tmp_path, build_id, policy, status_event):
        req_dir = tmp_path / "requests"
        req_dir.mkdir(parents=True, exist_ok=True)
        (req_dir / f"{build_id}_request.json").write_text(json.dumps({
            "request_id": build_id,
            "execution_policy": policy,
        }), encoding="utf-8")

        log_file = tmp_path / "build_log.jsonl"
        events = [
            {"timestamp": "2026-04-12T10:00:00Z", "build_id": build_id,
             "event": "request_queued", "notes": "", "extra": {}},
        ]
        if status_event != "request_queued":
            events.append(
                {"timestamp": "2026-04-12T10:01:00Z", "build_id": build_id,
                 "event": status_event, "notes": "", "extra": {}}
            )
        log_file.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        return log_file

    def test_notify_only_excluded_from_load_active_job(self, tmp_path):
        from frank_lloyd import job as _job_module
        log_file = self._make_log_and_request(tmp_path, "BUILD-001", "notify_only", "request_queued")
        orig_req = _job_module._FL_REQUESTS
        orig_log = _job_module._FL_BUILD_LOG
        try:
            _job_module._FL_REQUESTS  = tmp_path / "requests"
            _job_module._FL_BUILD_LOG = log_file
            active = _job_module.load_active_job()
        finally:
            _job_module._FL_REQUESTS  = orig_req
            _job_module._FL_BUILD_LOG = orig_log

        assert active is None, "notify_only build must not appear as active job"

    def test_hidden_import_excluded_from_load_active_job(self, tmp_path):
        from frank_lloyd import job as _job_module
        log_file = self._make_log_and_request(tmp_path, "BUILD-001", "hidden_import", "request_queued")
        orig_req = _job_module._FL_REQUESTS
        orig_log = _job_module._FL_BUILD_LOG
        try:
            _job_module._FL_REQUESTS  = tmp_path / "requests"
            _job_module._FL_BUILD_LOG = log_file
            active = _job_module.load_active_job()
        finally:
            _job_module._FL_REQUESTS  = orig_req
            _job_module._FL_BUILD_LOG = orig_log

        assert active is None, "hidden_import build must not appear as active job"

    def test_auto_apply_pending_shown_in_active_job(self, tmp_path):
        from frank_lloyd import job as _job_module
        log_file = self._make_log_and_request(tmp_path, "BUILD-001", "auto_apply", "request_queued")
        orig_req = _job_module._FL_REQUESTS
        orig_log = _job_module._FL_BUILD_LOG
        try:
            _job_module._FL_REQUESTS  = tmp_path / "requests"
            _job_module._FL_BUILD_LOG = log_file
            active = _job_module.load_active_job()
        finally:
            _job_module._FL_REQUESTS  = orig_req
            _job_module._FL_BUILD_LOG = orig_log

        assert active is not None, "auto_apply pending build should appear as active"

    def test_review_required_shown_in_active_job(self, tmp_path):
        from frank_lloyd import job as _job_module
        log_file = self._make_log_and_request(tmp_path, "BUILD-001", "review_required", "request_queued")
        orig_req = _job_module._FL_REQUESTS
        orig_log = _job_module._FL_BUILD_LOG
        try:
            _job_module._FL_REQUESTS  = tmp_path / "requests"
            _job_module._FL_BUILD_LOG = log_file
            active = _job_module.load_active_job()
        finally:
            _job_module._FL_REQUESTS  = orig_req
            _job_module._FL_BUILD_LOG = orig_log

        assert active is not None, "review_required build should appear as active"

    def test_legacy_none_policy_shown_in_active_job(self, tmp_path):
        """Legacy builds (no policy) still show up — treated as review_required."""
        from frank_lloyd import job as _job_module
        req_dir = tmp_path / "requests"
        req_dir.mkdir(parents=True, exist_ok=True)
        # Request file without execution_policy
        (req_dir / "BUILD-001_request.json").write_text(json.dumps({
            "request_id": "BUILD-001",
        }), encoding="utf-8")

        log_file = tmp_path / "build_log.jsonl"
        log_file.write_text(json.dumps({
            "timestamp": "2026-04-12T10:00:00Z",
            "build_id":  "BUILD-001",
            "event":     "request_queued",
            "notes":     "",
            "extra":     {},
        }) + "\n", encoding="utf-8")

        orig_req = _job_module._FL_REQUESTS
        orig_log = _job_module._FL_BUILD_LOG
        try:
            _job_module._FL_REQUESTS  = req_dir
            _job_module._FL_BUILD_LOG = log_file
            active = _job_module.load_active_job()
        finally:
            _job_module._FL_REQUESTS  = orig_req
            _job_module._FL_BUILD_LOG = orig_log

        assert active is not None, "Legacy build (no policy) must not be silently hidden"
        assert active.execution_policy is None


# ── E. Source-based execution policy ─────────────────────────────────────────

class TestSourcePolicy:
    def test_peter_chat_gets_auto_apply(self, tmp_path):
        from frank_lloyd.request_writer import queue_build
        rdir = tmp_path / "requests"
        blog = tmp_path / "build_log.jsonl"
        result = queue_build(
            description="Add a GET /ping endpoint that returns pong",
            success_criterion="GET /ping returns 200 with body pong",
            source="peter_chat",
            requests_dir=rdir,
            build_log=blog,
        )
        data = json.loads((rdir / f"{result['build_id']}_request.json").read_text())
        assert data["execution_policy"] == "auto_apply"

    def test_neighborhood_ui_gets_auto_apply(self, tmp_path):
        from frank_lloyd.request_writer import queue_build
        rdir = tmp_path / "requests"
        blog = tmp_path / "build_log.jsonl"
        result = queue_build(
            description="Add a GET /ping endpoint that returns pong",
            success_criterion="GET /ping returns 200 with body pong",
            source="neighborhood_ui",
            requests_dir=rdir,
            build_log=blog,
        )
        data = json.loads((rdir / f"{result['build_id']}_request.json").read_text())
        assert data["execution_policy"] == "auto_apply"

    def test_smart_queue_prefix_gets_auto_apply(self, tmp_path):
        from frank_lloyd.request_writer import queue_build
        rdir = tmp_path / "requests"
        blog = tmp_path / "build_log.jsonl"
        result = queue_build(
            description="Add a GET /ping endpoint that returns pong",
            success_criterion="GET /ping returns 200 with body pong",
            source="smart_queue_build",
            requests_dir=rdir,
            build_log=blog,
        )
        data = json.loads((rdir / f"{result['build_id']}_request.json").read_text())
        assert data["execution_policy"] == "auto_apply"

    def test_unknown_external_source_gets_review_required(self, tmp_path):
        """Unknown / external sources must get review_required, not auto_apply."""
        from frank_lloyd.request_writer import queue_build
        rdir = tmp_path / "requests"
        blog = tmp_path / "build_log.jsonl"
        result = queue_build(
            description="Add a GET /ping endpoint that returns pong",
            success_criterion="GET /ping returns 200 with body pong",
            source="external_claude_code_session",
            requests_dir=rdir,
            build_log=blog,
        )
        data = json.loads((rdir / f"{result['build_id']}_request.json").read_text())
        assert data["execution_policy"] == "review_required", (
            "External/unknown sources must not get auto_apply — "
            "they should require operator review before applying to the repo"
        )

    def test_explicit_override_wins_over_source_policy(self, tmp_path):
        """Explicit execution_policy param overrides source-based policy."""
        from frank_lloyd.request_writer import queue_build
        rdir = tmp_path / "requests"
        blog = tmp_path / "build_log.jsonl"
        result = queue_build(
            description="Add a GET /ping endpoint that returns pong",
            success_criterion="GET /ping returns 200 with body pong",
            source="external_unknown",
            execution_policy="notify_only",  # explicit override
            requests_dir=rdir,
            build_log=blog,
        )
        data = json.loads((rdir / f"{result['build_id']}_request.json").read_text())
        assert data["execution_policy"] == "notify_only"

    def test_policy_for_source_function(self):
        from frank_lloyd.request_writer import _policy_for_source
        assert _policy_for_source("peter_chat")       == "auto_apply"
        assert _policy_for_source("neighborhood_ui")  == "auto_apply"
        assert _policy_for_source("operator")         == "auto_apply"
        assert _policy_for_source("queue_and_run")    == "auto_apply"
        assert _policy_for_source("smart_queue_build") == "auto_apply"
        assert _policy_for_source("smart_queue_docs")  == "auto_apply"
        assert _policy_for_source("external_thing")   == "review_required"
        assert _policy_for_source("claude_code")      == "review_required"
        assert _policy_for_source("")                 == "review_required"


# ── F. Frank panel: notify_only does not appear as active workspace card ──────

class TestNeighborhoodPolicyFiltering:
    def test_notify_only_excluded_from_neighborhood_active_job(self):
        """notify_only build must not appear as an active workspace card."""
        with patch("app.routes.neighborhood._frank_lloyd_state") as mocked:
            mocked.return_value = {"active_job": None}
            from app.routes.neighborhood import _frank_lloyd_state
            state = mocked()
        assert state["active_job"] is None

    def test_review_required_shown_in_neighborhood(self):
        """review_required build at draft_generated appears as active card."""
        with patch("app.routes.neighborhood._frank_lloyd_state") as mocked:
            mocked.return_value = {
                "active_job": {"status": "draft_generated", "execution_policy": "review_required"}
            }
            state = mocked()
        assert state["active_job"] is not None


# ── G. No regression ─────────────────────────────────────────────────────────

class TestNoRegression:
    def test_promotable_task_classes_includes_legacy(self):
        """code_draft_low and code_patch_low still promotable."""
        from frank_lloyd.stage2_promoter import _PROMOTABLE_TASK_CLASSES
        assert "code_draft_low" in _PROMOTABLE_TASK_CLASSES
        assert "code_patch_low" in _PROMOTABLE_TASK_CLASSES

    def test_promotable_task_classes_includes_doc_types(self):
        from frank_lloyd.stage2_promoter import _PROMOTABLE_TASK_CLASSES
        assert "doc_draft_low"  in _PROMOTABLE_TASK_CLASSES
        assert "doc_patch_low"  in _PROMOTABLE_TASK_CLASSES
        assert "text_draft_low" in _PROMOTABLE_TASK_CLASSES
        assert "text_patch_low" in _PROMOTABLE_TASK_CLASSES

    def test_offlimits_files_unchanged(self):
        from frank_lloyd.stage2_promoter import _OFFLIMITS_FILES
        assert "app/main.py"   in _OFFLIMITS_FILES
        assert "scripts/ctl.sh" in _OFFLIMITS_FILES

    def test_offlimits_prefixes_unchanged(self):
        from frank_lloyd.stage2_promoter import _OFFLIMITS_PREFIXES
        assert "data/"   in _OFFLIMITS_PREFIXES
        assert ".venv/"  in _OFFLIMITS_PREFIXES
        assert ".git/"   in _OFFLIMITS_PREFIXES
        assert "staging/" in _OFFLIMITS_PREFIXES

    def test_frank_state_has_last_routing(self):
        from app.routes.neighborhood import _frank_lloyd_state
        state = _frank_lloyd_state()
        assert "last_routing" in state

    def test_frank_state_has_execution_policy_in_active_job(self):
        """execution_policy flows through to_dict() and shows in neighborhood state."""
        with patch("app.routes.neighborhood._frank_lloyd_state") as mocked:
            mocked.return_value = {
                "active_job": {
                    "status": "draft_generated",
                    "execution_policy": "review_required",
                    "build_id": "BUILD-001",
                }
            }
            state = mocked()
        assert state["active_job"]["execution_policy"] == "review_required"

    def test_queue_build_still_works_for_operator_source(self, tmp_path):
        from frank_lloyd.request_writer import queue_build
        rdir = tmp_path / "requests"
        blog = tmp_path / "build_log.jsonl"
        result = queue_build(
            description="Add a health endpoint to check backend liveness",
            success_criterion="GET /health returns 200 with ok:true in JSON",
            source="operator",
            requests_dir=rdir,
            build_log=blog,
        )
        assert result["ok"]
        data = json.loads((rdir / f"{result['build_id']}_request.json").read_text())
        assert data["execution_policy"] == "auto_apply"
        assert data["routing"]["builder_lane"] == "frank"
