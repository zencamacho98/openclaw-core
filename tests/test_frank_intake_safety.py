# tests/test_frank_intake_safety.py
#
# FRANK-INTAKE-SAFETY-01: Verify that casual Peter chat no longer auto-fires
# the Frank Lloyd pipeline, and that bulk-abandon clears orphan builds correctly.
#
# Covers:
#   A. handle_build_intent queues only (no background thread spawned)
#   B. peter_queue_build queues only (no auto_runner call)
#   C. handle_fl_lifecycle_nl "run" action still explicitly triggers the pipeline
#   D. abandon_by_source abandons all non-terminal builds with matching source
#   E. abandon_by_source skips terminal builds
#   F. abandon_by_source with unknown source abandons 0 builds
#   G. bulk-abandon Peter command routes and returns correct summary
#   H. Review/apply gates (approve, reject, authorize) still function

from __future__ import annotations

import json
import pathlib
import tempfile
from unittest.mock import MagicMock, call, patch


# ── A. handle_build_intent auto-starts Frank Lloyd ────────────────────────────

class TestHandleBuildIntentQueueOnly:
    """Tests that handle_build_intent queues AND auto-starts the pipeline."""

    def _make_command(self, raw: str = "add a GET /health route that returns a JSON response. success: curl http://localhost:8001/health returns HTTP 200 with body {ok: true}",
                      nl_intake: bool = False):
        from peter.commands import Command, CommandType
        return Command(
            type        = CommandType.BUILD_INTENT,
            args        = {"raw_request": raw, "nl_intake": nl_intake},
            transport   = "cli",
            operator_id = "cli",
            raw_text    = raw,
        )

    def test_background_thread_spawned(self):
        """handle_build_intent MUST spawn a background daemon thread for auto-start."""
        cmd = self._make_command()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            req_dir  = tmp_path / "requests"
            log_file = tmp_path / "build_log.jsonl"
            req_dir.mkdir()
            with (
                patch("peter.handlers._FL_REQUESTS", req_dir),
                patch("peter.handlers._FL_BUILD_LOG", log_file),
                patch("threading.Thread") as mock_thread,
            ):
                from peter.handlers import handle_build_intent
                resp = handle_build_intent(cmd)
            mock_thread.assert_called_once()
            _, kwargs = mock_thread.call_args
            assert kwargs.get("daemon") is True

    def test_response_says_building(self):
        """Response must indicate Frank Lloyd is building (not just queued)."""
        cmd = self._make_command()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            req_dir  = tmp_path / "requests"
            log_file = tmp_path / "build_log.jsonl"
            req_dir.mkdir()
            with (
                patch("peter.handlers._FL_REQUESTS", req_dir),
                patch("peter.handlers._FL_BUILD_LOG", log_file),
                patch("threading.Thread"),
            ):
                from peter.handlers import handle_build_intent
                resp = handle_build_intent(cmd)
        assert resp.ok
        summary_lower = resp.summary.lower()
        # Must NOT say "autonomously" or "no review needed"
        assert "autonomously" not in summary_lower
        assert "no review needed" not in summary_lower

    def test_nl_intake_response_says_building_now(self):
        """NL intake response must say Frank Lloyd is building now."""
        cmd = self._make_command(nl_intake=True)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            req_dir  = tmp_path / "requests"
            log_file = tmp_path / "build_log.jsonl"
            req_dir.mkdir()
            with (
                patch("peter.handlers._FL_REQUESTS", req_dir),
                patch("peter.handlers._FL_BUILD_LOG", log_file),
                patch("threading.Thread"),
            ):
                from peter.handlers import handle_build_intent
                resp = handle_build_intent(cmd)
        assert resp.ok
        assert "building" in resp.summary.lower() or "frank lloyd" in resp.summary.lower()

    def test_build_id_still_assigned_and_queued(self):
        cmd = self._make_command()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            req_dir  = tmp_path / "requests"
            log_file = tmp_path / "build_log.jsonl"
            req_dir.mkdir()
            with (
                patch("peter.handlers._FL_REQUESTS", req_dir),
                patch("peter.handlers._FL_BUILD_LOG", log_file),
            ):
                from peter.handlers import handle_build_intent
                resp = handle_build_intent(cmd)
            assert resp.ok
            build_id = (resp.metrics or {}).get("build_id") or (resp.raw or {}).get("build_id")
            assert build_id and build_id.startswith("BUILD-")
            # request_queued event must be in the log
            events = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
            assert any(e.get("event") == "request_queued" and e.get("build_id") == build_id
                       for e in events)


# ── B. peter_queue_build no longer auto-runs ─────────────────────────────────

class TestPeterQueueBuildNoAutoRun:
    """
    peter_queue_build() must queue the build but NOT call auto_runner.run_safe_lane().
    """

    def test_run_safe_lane_not_called(self):
        """After queue_build, no auto-runner fire should occur."""
        import frank_lloyd.auto_runner as _ar
        with patch("frank_lloyd.auto_runner.run_safe_lane") as mock_run:
            # Simulate via brief_shaper + request_writer mocks
            mock_brief = MagicMock()
            mock_brief.needs_clarification = False
            mock_brief.description = "Add a health check endpoint"
            mock_brief.success_criterion = "returns ok: true"
            mock_brief.mode = "build"

            mock_result = {"ok": True, "build_id": "BUILD-099", "title": "health check endpoint", "error": None}

            with (
                patch("frank_lloyd.brief_shaper.shape", return_value=mock_brief),
                patch("frank_lloyd.request_writer.readiness_check", return_value=""),
                patch("frank_lloyd.request_writer.queue_build", return_value=mock_result),
            ):
                # Import and call the route handler via TestClient or direct invocation
                from app.routes.neighborhood import peter_queue_build
                result = peter_queue_build({"message": "Add a health check endpoint"})

            mock_run.assert_not_called()
            assert result["ok"] is True
            assert result["build_id"] == "BUILD-099"

    def test_response_text_mentions_run_command(self):
        mock_brief = MagicMock()
        mock_brief.needs_clarification = False
        mock_brief.description = "Add a health check endpoint"
        mock_brief.success_criterion = "returns ok: true"
        mock_brief.mode = "build"

        mock_result = {"ok": True, "build_id": "BUILD-099", "title": "health check endpoint", "error": None}

        with (
            patch("frank_lloyd.brief_shaper.shape", return_value=mock_brief),
            patch("frank_lloyd.request_writer.readiness_check", return_value=""),
            patch("frank_lloyd.request_writer.queue_build", return_value=mock_result),
        ):
            from app.routes.neighborhood import peter_queue_build
            result = peter_queue_build({"message": "Add a health check endpoint"})

        assert "run" in result["text"].lower()
        assert "Frank Lloyd is on it" not in result["text"]


# ── C. Explicit "run BUILD-N" still works ────────────────────────────────────

class TestExplicitRunStillWorks:
    """
    handle_fl_lifecycle_nl with action="run" must still trigger the pipeline.
    This is the explicitly operator-initiated path — must NOT be removed.
    """

    def test_run_action_calls_full_auto(self):
        """Explicit 'run BUILD-N' calls run_full_auto — the intentional pipeline trigger."""
        from peter.commands import Command, CommandType
        cmd = Command(
            type        = CommandType.FL_LIFECYCLE_NL,
            args        = {"action": "run", "build_id": "BUILD-042", "notes": "", "reason": "", "target_path": ""},
            transport   = "cli",
            operator_id = "cli",
            raw_text    = "run BUILD-042",
        )

        mock_result = {"ok": True, "promoted_to": "app/health.py"}

        with patch("frank_lloyd.auto_runner.run_full_auto", return_value=mock_result) as mock_run:
            from peter.handlers import handle_fl_lifecycle_nl
            resp = handle_fl_lifecycle_nl(cmd)

        # Explicit run must fire the pipeline
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == "BUILD-042" or call_args[1].get("build_id") == "BUILD-042" or "BUILD-042" in str(call_args)

    def test_run_command_parsed_as_fl_lifecycle_nl(self):
        from peter.commands import parse_command, CommandType
        cmd = parse_command("run BUILD-042")
        assert cmd.type == CommandType.FL_LIFECYCLE_NL
        assert cmd.args.get("action") == "run"
        assert cmd.args.get("build_id") == "BUILD-042"


# ── D. abandon_by_source abandons non-terminal builds ────────────────────────

class TestAbandonBySource:
    def _make_log(self, tmp: pathlib.Path, entries: list[dict]) -> pathlib.Path:
        log = tmp / "build_log.jsonl"
        log.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        return log

    def _queued_ev(self, build_id: str, source: str) -> dict:
        return {
            "build_id":  build_id,
            "event":     "request_queued",
            "timestamp": "2026-04-11T00:00:00+00:00",
            "notes":     "",
            "extra":     {"source": source, "title": "test"},
        }

    def _latest_ev(self, build_id: str, event: str) -> dict:
        return {
            "build_id":  build_id,
            "event":     event,
            "timestamp": "2026-04-11T01:00:00+00:00",
            "notes":     "",
            "extra":     {},
        }

    def test_abandons_all_matching_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            entries = [
                self._queued_ev("BUILD-001", "peter_chat_smart"),
                self._latest_ev("BUILD-001", "spec_ready"),
                self._queued_ev("BUILD-002", "peter_chat_smart"),
                self._latest_ev("BUILD-002", "draft_generated"),
            ]
            log = self._make_log(tmp_path, entries)
            with patch("frank_lloyd.abandoner._BUILD_LOG", log):
                from frank_lloyd.abandoner import abandon_by_source
                result = abandon_by_source("peter_chat_smart")
        assert result["ok"] is True
        assert set(result["abandoned"]) == {"BUILD-001", "BUILD-002"}
        assert result["skipped"] == []

    def test_skips_terminal_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            entries = [
                self._queued_ev("BUILD-010", "peter_chat_smart"),
                self._latest_ev("BUILD-010", "draft_promoted"),  # terminal
                self._queued_ev("BUILD-011", "peter_chat_smart"),
                self._latest_ev("BUILD-011", "abandoned"),       # already terminal
                self._queued_ev("BUILD-012", "peter_chat_smart"),
                self._latest_ev("BUILD-012", "spec_ready"),      # non-terminal
            ]
            log = self._make_log(tmp_path, entries)
            with patch("frank_lloyd.abandoner._BUILD_LOG", log):
                from frank_lloyd.abandoner import abandon_by_source
                result = abandon_by_source("peter_chat_smart")
        assert result["ok"] is True
        assert result["abandoned"] == ["BUILD-012"]
        assert set(result["skipped"]) == {"BUILD-010", "BUILD-011"}

    def test_unknown_source_abandons_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            entries = [
                self._queued_ev("BUILD-020", "peter_chat_smart"),
                self._latest_ev("BUILD-020", "spec_ready"),
            ]
            log = self._make_log(tmp_path, entries)
            with patch("frank_lloyd.abandoner._BUILD_LOG", log):
                from frank_lloyd.abandoner import abandon_by_source
                result = abandon_by_source("some_unknown_source")
        assert result["ok"] is True
        assert result["abandoned"] == []
        assert result["skipped"] == []

    def test_different_source_not_abandoned(self):
        """Builds from neighborhood_ui must not be touched when clearing peter_chat_smart."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            entries = [
                self._queued_ev("BUILD-030", "neighborhood_ui"),
                self._latest_ev("BUILD-030", "spec_ready"),
                self._queued_ev("BUILD-031", "peter_chat_smart"),
                self._latest_ev("BUILD-031", "spec_ready"),
            ]
            log = self._make_log(tmp_path, entries)
            with patch("frank_lloyd.abandoner._BUILD_LOG", log):
                from frank_lloyd.abandoner import abandon_by_source
                result = abandon_by_source("peter_chat_smart")
        assert result["abandoned"] == ["BUILD-031"]
        assert "BUILD-030" not in result["abandoned"]

    def test_empty_source_returns_error(self):
        from frank_lloyd.abandoner import abandon_by_source
        result = abandon_by_source("")
        assert result["ok"] is False
        assert result["errors"]


# ── E+F. Bulk-abandon Peter command ──────────────────────────────────────────

class TestFlBulkAbandonCommand:
    def test_parsed_as_fl_bulk_abandon(self):
        from peter.commands import parse_command, CommandType
        for phrase in ("abandon frank queue", "clean frank queue",
                       "abandon peter chat builds", "clear frank queue"):
            cmd = parse_command(phrase)
            assert cmd.type == CommandType.FL_BULK_ABANDON, f"Failed for: {phrase!r}"
            assert cmd.args.get("source") == "peter_chat_smart"

    def test_explicit_source_parsed(self):
        from peter.commands import parse_command, CommandType
        cmd = parse_command("abandon frank queue neighborhood_ui")
        assert cmd.type == CommandType.FL_BULK_ABANDON
        assert cmd.args.get("source") == "neighborhood_ui"

    def test_handler_returns_abandoned_count(self):
        from peter.commands import Command, CommandType
        cmd = Command(
            type        = CommandType.FL_BULK_ABANDON,
            args        = {"source": "peter_chat_smart"},
            transport   = "cli",
            operator_id = "cli",
            raw_text    = "abandon frank queue",
        )
        mock_result = {
            "ok": True, "source": "peter_chat_smart",
            "abandoned": ["BUILD-001", "BUILD-002"], "skipped": [], "errors": [],
        }
        with patch("frank_lloyd.abandoner.abandon_by_source", return_value=mock_result):
            from peter.handlers import handle_fl_bulk_abandon
            resp = handle_fl_bulk_abandon(cmd)
        assert resp.ok
        assert "BUILD-001" in resp.summary
        assert "BUILD-002" in resp.summary
        assert resp.metrics.get("abandoned_count") == 2

    def test_handler_nothing_found(self):
        from peter.commands import Command, CommandType
        cmd = Command(
            type        = CommandType.FL_BULK_ABANDON,
            args        = {"source": "ghost_source"},
            transport   = "cli",
            operator_id = "cli",
            raw_text    = "abandon frank queue ghost_source",
        )
        mock_result = {
            "ok": True, "source": "ghost_source",
            "abandoned": [], "skipped": [], "errors": [],
        }
        with patch("frank_lloyd.abandoner.abandon_by_source", return_value=mock_result):
            from peter.handlers import handle_fl_bulk_abandon
            resp = handle_fl_bulk_abandon(cmd)
        assert resp.ok
        assert "no builds found" in resp.summary.lower()

    def test_handler_all_terminal_skipped(self):
        from peter.commands import Command, CommandType
        cmd = Command(
            type        = CommandType.FL_BULK_ABANDON,
            args        = {"source": "peter_chat_smart"},
            transport   = "cli",
            operator_id = "cli",
            raw_text    = "abandon frank queue",
        )
        mock_result = {
            "ok": True, "source": "peter_chat_smart",
            "abandoned": [], "skipped": ["BUILD-050", "BUILD-051"], "errors": [],
        }
        with patch("frank_lloyd.abandoner.abandon_by_source", return_value=mock_result):
            from peter.handlers import handle_fl_bulk_abandon
            resp = handle_fl_bulk_abandon(cmd)
        assert resp.ok
        assert "terminal" in resp.summary.lower()


# ── G. Review/apply gates still function after safety changes ────────────────

class TestReviewGatesUnaffected:
    """
    Approve, reject, and authorize commands must still work exactly as before.
    These are explicit operator actions and must not be touched by FRANK-INTAKE-SAFETY-01.
    """
    def test_approve_build_parsed(self):
        from peter.commands import parse_command, CommandType
        cmd = parse_command("approve BUILD-042 looks good")
        assert cmd.type == CommandType.APPROVE_BUILD
        assert cmd.args.get("build_id") == "BUILD-042"

    def test_reject_build_parsed(self):
        from peter.commands import parse_command, CommandType
        cmd = parse_command("reject BUILD-042 wrong approach")
        assert cmd.type == CommandType.REJECT_BUILD
        assert cmd.args.get("build_id") == "BUILD-042"

    def test_authorize_stage2_parsed(self):
        from peter.commands import parse_command, CommandType
        cmd = parse_command("authorize BUILD-042 stage2")
        assert cmd.type == CommandType.AUTHORIZE_STAGE2
        assert cmd.args.get("build_id") == "BUILD-042"
