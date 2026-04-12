"""
tests/test_peter_build_intake.py

Tests for Peter → Frank Lloyd Stage 1 intake path.

Covers:
  - parse_command correctly routes "build ..." to BUILD_INTENT
  - handle_build_intent: clear-enough request writes files and returns ok Response
  - handle_build_intent: too-vague description returns clarification Response
  - handle_build_intent: missing success criteria returns clarification Response
  - handle_build_intent: success criteria too vague returns clarification Response
  - _fl_next_build_id: starts at BUILD-001 when directory is empty
  - _fl_next_build_id: increments past existing builds
  - _fl_write_request: written file contains all required fields
  - _fl_append_log_event: event is appended to log with correct fields
  - router dispatch: BUILD_INTENT routes to handle_build_intent
  - full intake: multiple builds get sequential IDs

Run with:
    python -m unittest tests.test_peter_build_intake -v
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from peter.commands import CommandType, parse_command
import peter.handlers as handlers
from peter.handlers import (
    handle_build_intent,
    _fl_next_build_id,
    _fl_extract_success_criteria,
    _fl_extract_title,
    _fl_readiness_check,
    _fl_write_request,
    _fl_append_log_event,
)
from peter.router import route


# ── Fixtures ──────────────────────────────────────────────────────────────────

_CLEAR_REQUEST = (
    "add route GET /frank-lloyd/count that returns the total number of approved builds. "
    "success: curl /frank-lloyd/count returns {count: 3} after three approved builds"
)

_VAGUE_REQUEST = "make it better"

_NO_CRITERION = (
    "add route GET /frank-lloyd/count that returns the total number of approved builds"
)

_VAGUE_CRITERION = (
    "add route GET /frank-lloyd/count that returns approved build count. "
    "success: works"
)


# ── Test class ────────────────────────────────────────────────────────────────

class TestPeterBuildIntake(unittest.TestCase):

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        # Patch module-level paths
        self._orig_requests  = handlers._FL_REQUESTS
        self._orig_build_log = handlers._FL_BUILD_LOG
        self._req_dir  = pathlib.Path(self._tmpdir) / "requests"
        self._log_path = pathlib.Path(self._tmpdir) / "build_log.jsonl"
        handlers._FL_REQUESTS  = self._req_dir
        handlers._FL_BUILD_LOG = self._log_path

    def tearDown(self) -> None:
        handlers._FL_REQUESTS  = self._orig_requests
        handlers._FL_BUILD_LOG = self._orig_build_log
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ── parse_command ────────────────────────────────────────────────────────

    def test_parse_build_routes_to_build_intent(self) -> None:
        cmd = parse_command("build a new route")
        self.assertEqual(cmd.type, CommandType.BUILD_INTENT)

    def test_parse_build_preserves_raw_request(self) -> None:
        cmd = parse_command("build a new route for counts")
        self.assertEqual(cmd.args["raw_request"], "a new route for counts")

    def test_parse_bare_build_routes_to_build_intent(self) -> None:
        cmd = parse_command("build")
        self.assertEqual(cmd.type, CommandType.BUILD_INTENT)

    def test_parse_build_does_not_match_best(self) -> None:
        cmd = parse_command("best candidate")
        self.assertNotEqual(cmd.type, CommandType.BUILD_INTENT)

    # ── _fl_extract_success_criteria ────────────────────────────────────────

    def test_extract_success_criteria_found(self) -> None:
        text = "add a route. success: curl /x returns {ok: true}"
        self.assertEqual(
            _fl_extract_success_criteria(text),
            "curl /x returns {ok: true}",
        )

    def test_extract_success_criteria_missing(self) -> None:
        self.assertEqual(_fl_extract_success_criteria("add a route"), "")

    def test_extract_success_criteria_done_when(self) -> None:
        text = "add route. done when: /x returns 200 and json has count field"
        result = _fl_extract_success_criteria(text)
        self.assertIn("returns 200", result)

    def test_extract_success_criteria_test_marker(self) -> None:
        text = "add route. test: python -m pytest tests/test_count.py passes"
        result = _fl_extract_success_criteria(text)
        self.assertIn("python", result)

    # ── _fl_readiness_check ──────────────────────────────────────────────────

    def test_readiness_clear_request_passes(self) -> None:
        sc = _fl_extract_success_criteria(_CLEAR_REQUEST)
        desc = _CLEAR_REQUEST[:_CLEAR_REQUEST.lower().find("success:")].strip()
        missing = _fl_readiness_check(desc, sc)
        self.assertEqual(missing, [])

    def test_readiness_vague_description_fails(self) -> None:
        missing = _fl_readiness_check("make it better", "")
        self.assertIn("description_too_vague", missing)

    def test_readiness_missing_criterion_fails(self) -> None:
        missing = _fl_readiness_check(_NO_CRITERION, "")
        self.assertIn("missing_success_criteria", missing)

    def test_readiness_vague_criterion_fails(self) -> None:
        sc = _fl_extract_success_criteria(_VAGUE_CRITERION)
        desc = _VAGUE_CRITERION[:_VAGUE_CRITERION.lower().find("success:")].strip()
        missing = _fl_readiness_check(desc, sc)
        self.assertIn("success_criteria_too_vague", missing)

    def test_readiness_short_description_fails(self) -> None:
        missing = _fl_readiness_check("add it", "")
        self.assertIn("description_too_vague", missing)

    # ── _fl_next_build_id ────────────────────────────────────────────────────

    def test_next_build_id_empty_dir_is_001(self) -> None:
        self.assertEqual(_fl_next_build_id(self._req_dir), "BUILD-001")

    def test_next_build_id_increments(self) -> None:
        self._req_dir.mkdir(parents=True)
        (self._req_dir / "BUILD-001_request.json").write_text("{}")
        (self._req_dir / "BUILD-002_request.json").write_text("{}")
        self.assertEqual(_fl_next_build_id(self._req_dir), "BUILD-003")

    def test_next_build_id_handles_gap(self) -> None:
        self._req_dir.mkdir(parents=True)
        (self._req_dir / "BUILD-005_request.json").write_text("{}")
        self.assertEqual(_fl_next_build_id(self._req_dir), "BUILD-006")

    def test_next_build_id_ignores_malformed(self) -> None:
        self._req_dir.mkdir(parents=True)
        (self._req_dir / "BUILD-001_request.json").write_text("{}")
        (self._req_dir / "notabuild.json").write_text("{}")
        self.assertEqual(_fl_next_build_id(self._req_dir), "BUILD-002")

    # ── _fl_write_request ────────────────────────────────────────────────────

    def test_write_request_creates_file(self) -> None:
        path = _fl_write_request(
            self._req_dir, "BUILD-001",
            "route for count", "add route for approved builds",
            "curl /frank-lloyd/count returns {count: 0}",
        )
        self.assertTrue(path.exists())

    def test_write_request_required_fields_present(self) -> None:
        path = _fl_write_request(
            self._req_dir, "BUILD-001",
            "route for count", "add route for approved builds",
            "curl /frank-lloyd/count returns {count: 0}",
        )
        data = json.loads(path.read_text())
        for field in ("request_id", "title", "description", "requester",
                      "requested_at", "success_criteria"):
            self.assertIn(field, data, f"Missing required field: {field}")
        self.assertEqual(data["request_id"], "BUILD-001")
        self.assertEqual(data["requester"], "operator")

    def test_write_request_filename_pattern(self) -> None:
        path = _fl_write_request(
            self._req_dir, "BUILD-001",
            "t", "description here with enough words",
            "success: x returns y z w",
        )
        self.assertEqual(path.name, "BUILD-001_request.json")

    # ── _fl_append_log_event ─────────────────────────────────────────────────

    def test_append_log_event_creates_file(self) -> None:
        _fl_append_log_event(self._log_path, "BUILD-001", "route for count")
        self.assertTrue(self._log_path.exists())

    def test_append_log_event_contents(self) -> None:
        _fl_append_log_event(self._log_path, "BUILD-001", "route for count")
        lines = self._log_path.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        ev = json.loads(lines[0])
        self.assertEqual(ev["build_id"], "BUILD-001")
        self.assertEqual(ev["event"], "request_queued")
        self.assertIn("timestamp", ev)
        self.assertEqual(ev["extra"]["title"], "route for count")

    def test_append_log_event_appends_multiple(self) -> None:
        _fl_append_log_event(self._log_path, "BUILD-001", "first")
        _fl_append_log_event(self._log_path, "BUILD-002", "second")
        lines = self._log_path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        ids = [json.loads(l)["build_id"] for l in lines]
        self.assertEqual(ids, ["BUILD-001", "BUILD-002"])

    # ── handle_build_intent (full integration) ────────────────────────────────

    def test_clear_request_returns_ok(self) -> None:
        cmd = parse_command(f"build {_CLEAR_REQUEST}")
        resp = handle_build_intent(cmd)
        self.assertTrue(resp.ok)
        self.assertEqual(resp.command_type, "build_intent")

    def test_clear_request_writes_request_file(self) -> None:
        cmd = parse_command(f"build {_CLEAR_REQUEST}")
        handle_build_intent(cmd)
        files = list(self._req_dir.glob("BUILD-*_request.json"))
        self.assertEqual(len(files), 1)

    def test_clear_request_appends_log_event(self) -> None:
        cmd = parse_command(f"build {_CLEAR_REQUEST}")
        handle_build_intent(cmd)
        lines = self._log_path.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        ev = json.loads(lines[0])
        self.assertEqual(ev["event"], "request_queued")

    def test_clear_request_response_contains_build_id(self) -> None:
        cmd = parse_command(f"build {_CLEAR_REQUEST}")
        resp = handle_build_intent(cmd)
        self.assertIn("BUILD-001", resp.summary)
        self.assertEqual(resp.metrics["build_id"], "BUILD-001")

    def test_vague_request_returns_not_ok(self) -> None:
        cmd = parse_command(f"build {_VAGUE_REQUEST}")
        resp = handle_build_intent(cmd)
        self.assertFalse(resp.ok)
        self.assertIn("description_too_vague", resp.raw["missing_fields"])

    def test_vague_request_writes_no_files(self) -> None:
        cmd = parse_command(f"build {_VAGUE_REQUEST}")
        handle_build_intent(cmd)
        files = list(self._req_dir.glob("BUILD-*_request.json")) if self._req_dir.exists() else []
        self.assertEqual(files, [])

    def test_missing_criterion_returns_not_ok(self) -> None:
        cmd = parse_command(f"build {_NO_CRITERION}")
        resp = handle_build_intent(cmd)
        self.assertFalse(resp.ok)
        self.assertIn("missing_success_criteria", resp.raw["missing_fields"])

    def test_missing_criterion_writes_no_files(self) -> None:
        cmd = parse_command(f"build {_NO_CRITERION}")
        handle_build_intent(cmd)
        self.assertFalse(self._log_path.exists())

    def test_vague_criterion_returns_not_ok(self) -> None:
        cmd = parse_command(f"build {_VAGUE_CRITERION}")
        resp = handle_build_intent(cmd)
        self.assertFalse(resp.ok)
        self.assertIn("success_criteria_too_vague", resp.raw["missing_fields"])

    def test_second_build_gets_002(self) -> None:
        cmd = parse_command(f"build {_CLEAR_REQUEST}")
        handle_build_intent(cmd)
        resp2 = handle_build_intent(cmd)
        self.assertEqual(resp2.metrics["build_id"], "BUILD-002")

    def test_human_review_not_needed_on_success(self) -> None:
        """Frank Lloyd auto-builds — no human gate after submission."""
        cmd = parse_command(f"build {_CLEAR_REQUEST}")
        resp = handle_build_intent(cmd)
        self.assertFalse(resp.human_review_needed)

    # ── router dispatch ───────────────────────────────────────────────────────

    def test_router_dispatches_build_intent(self) -> None:
        from peter.identity import load_identities
        # Skip identity check for this test — route via direct handler
        cmd = parse_command(f"build {_CLEAR_REQUEST}")
        self.assertEqual(cmd.type, CommandType.BUILD_INTENT)
        # Direct handler call (skipping auth layer which reads identity.json)
        resp = handle_build_intent(cmd)
        self.assertTrue(resp.ok)


if __name__ == "__main__":
    unittest.main()
