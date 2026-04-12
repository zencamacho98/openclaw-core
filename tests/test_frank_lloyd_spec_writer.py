"""
tests/test_frank_lloyd_spec_writer.py

Tests for Frank Lloyd Stage 1 spec packet generation.

Covers:
  - find_next_queued_build: empty queue, FIFO order, skips past-terminal builds
  - generate_spec_packet: validation errors (wrong state, missing request)
  - generate_spec_packet: successful spec production — files written, log updated
  - generate_spec_packet: LM failure → blocked.md written, blocked event logged
  - spec.yaml content: required fields present and correct
  - preflight.md content: all 8 sections present
  - off-limits file detection: flagged in Q4 when present in description
  - log events: spec_ready and blocked events have correct structure
  - missing directories created automatically

The LM call (_call_spec_lm) is always mocked — no real API calls in tests.

Run with:
    python -m unittest tests.test_frank_lloyd_spec_writer -v
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import frank_lloyd.spec_writer as sw
from frank_lloyd.spec_writer import (
    generate_spec_packet,
    find_next_queued_build,
    _derive_build_status,
    _check_offlimits,
    _format_spec_yaml,
    _format_preflight_md,
    _parse_json_response,
)


# ── Mock LM data ──────────────────────────────────────────────────────────────

_MOCK_SPEC_DATA = {
    "build_type": "new_route",
    "risk_level": "low",
    "affected_files_new": [
        {"path": "app/routes/frank_lloyd_count.py", "purpose": "GET /frank-lloyd/count endpoint"},
    ],
    "affected_files_modified": [
        {"path": "app/main.py", "change": "include frank_lloyd_count_router"},
        {"path": "app/test_sentinel.py", "change": "add FILE_TEST_MAP entry"},
    ],
    "reuse_decisions": [
        {"capability": "LMHelper", "decision": "not_needed", "reason": "deterministic read-only route"},
    ],
    "architecture_layer": "specialist_house",
    "layer_justification": "Frank Lloyd count is Frank Lloyd domain state.",
    "sentinel_test_file": "tests/test_frank_lloyd_count.py",
    "sentinel_coverage_note": "New test file needed for count endpoint.",
    "blast_radius_failure_mode": "loud",
    "blast_radius_rollback": "Delete app/routes/frank_lloyd_count.py and remove from main.py.",
    "blast_radius_scope": "Startup crash if import fails; no data corruption.",
    "preflight_q1": "No existing capability covers a Frank Lloyd count endpoint.",
    "preflight_q2": "Belongs to Frank Lloyd domain — its own build state.",
    "preflight_q3": "Minimum: one new route file + main.py registration + test file.",
    "preflight_q5": "Sits in specialist_house layer. No layer boundary crossed.",
    "preflight_q6": "Startup crash if import fails. Rollback by deleting route file.",
    "preflight_q7": "Source: app/routes/frank_lloyd_count.py → Test: tests/test_frank_lloyd_count.py",
}

_MOCK_LM_OK    = {"ok": True,  "data": _MOCK_SPEC_DATA, "error": None}
_MOCK_LM_FAIL  = {"ok": False, "data": None, "error": "LM unavailable: API key missing"}


# ── Sample request ─────────────────────────────────────────────────────────────

def _sample_request(build_id: str = "BUILD-001") -> dict:
    return {
        "request_id":       build_id,
        "title":            "route for approved build count",
        "description":      "add route GET /frank-lloyd/count that returns the number of approved builds",
        "requester":        "operator",
        "requested_at":     "2026-04-11T00:00:00+00:00",
        "success_criteria": "curl /frank-lloyd/count returns {count: N} for N approved builds",
        "build_type_hint":  "",
        "context_refs":     [],
        "constraints":      [],
    }


def _sample_log_event(build_id: str, event: str, ts: str = "2026-04-11T00:00:00+00:00") -> str:
    return json.dumps({
        "timestamp": ts,
        "build_id":  build_id,
        "event":     event,
        "notes":     "",
        "extra":     {},
    })


# ── Test class ────────────────────────────────────────────────────────────────

class TestFrankLloydSpecWriter(unittest.TestCase):

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        # Patch module-level path constants
        self._orig = {
            "_FL_REQUESTS":  sw._FL_REQUESTS,
            "_FL_BUILD_LOG": sw._FL_BUILD_LOG,
            "_STAGING_ROOT": sw._STAGING_ROOT,
        }
        self._req_dir     = pathlib.Path(self._tmpdir) / "requests"
        self._log_path    = pathlib.Path(self._tmpdir) / "build_log.jsonl"
        self._staging_dir = pathlib.Path(self._tmpdir) / "staging"
        sw._FL_REQUESTS  = self._req_dir
        sw._FL_BUILD_LOG = self._log_path
        sw._STAGING_ROOT = self._staging_dir

    def tearDown(self) -> None:
        sw._FL_REQUESTS  = self._orig["_FL_REQUESTS"]
        sw._FL_BUILD_LOG = self._orig["_FL_BUILD_LOG"]
        sw._STAGING_ROOT = self._orig["_STAGING_ROOT"]
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _write_log(self, *events: str) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.write_text("\n".join(events) + "\n", encoding="utf-8")

    def _write_request(self, build_id: str = "BUILD-001") -> None:
        self._req_dir.mkdir(parents=True, exist_ok=True)
        path = self._req_dir / f"{build_id}_request.json"
        path.write_text(json.dumps(_sample_request(build_id)), encoding="utf-8")

    def _read_log_events(self) -> list[dict]:
        if not self._log_path.exists():
            return []
        return [json.loads(l) for l in self._log_path.read_text().splitlines() if l.strip()]

    # ── find_next_queued_build ─────────────────────────────────────────────────

    def test_find_next_queued_empty_log(self) -> None:
        self.assertIsNone(find_next_queued_build())

    def test_find_next_queued_missing_log(self) -> None:
        self.assertIsNone(find_next_queued_build())

    def test_find_next_queued_returns_pending_spec(self) -> None:
        self._write_log(_sample_log_event("BUILD-001", "request_queued"))
        self.assertEqual(find_next_queued_build(), "BUILD-001")

    def test_find_next_queued_skips_spec_ready(self) -> None:
        self._write_log(
            _sample_log_event("BUILD-001", "request_queued", "2026-04-11T00:00:00+00:00"),
            _sample_log_event("BUILD-001", "spec_ready",     "2026-04-11T00:01:00+00:00"),
            _sample_log_event("BUILD-002", "request_queued", "2026-04-11T00:02:00+00:00"),
        )
        self.assertEqual(find_next_queued_build(), "BUILD-002")

    def test_find_next_queued_skips_terminal(self) -> None:
        self._write_log(
            _sample_log_event("BUILD-001", "request_queued"),
            _sample_log_event("BUILD-001", "spec_approved"),
            _sample_log_event("BUILD-002", "request_queued"),
        )
        self.assertEqual(find_next_queued_build(), "BUILD-002")

    def test_find_next_queued_fifo_order(self) -> None:
        self._write_log(
            _sample_log_event("BUILD-001", "request_queued", "2026-04-11T00:00:00+00:00"),
            _sample_log_event("BUILD-002", "request_queued", "2026-04-11T00:01:00+00:00"),
        )
        self.assertEqual(find_next_queued_build(), "BUILD-001")

    def test_find_next_queued_none_when_all_terminal(self) -> None:
        self._write_log(
            _sample_log_event("BUILD-001", "request_queued"),
            _sample_log_event("BUILD-001", "spec_rejected"),
        )
        self.assertIsNone(find_next_queued_build())

    # ── _derive_build_status ────────────────────────────────────────────────────

    def test_derive_status_pending_spec(self) -> None:
        events = [json.loads(_sample_log_event("BUILD-001", "request_queued"))]
        self.assertEqual(_derive_build_status("BUILD-001", events), "pending_spec")

    def test_derive_status_pending_review(self) -> None:
        events = [
            json.loads(_sample_log_event("BUILD-001", "request_queued")),
            json.loads(_sample_log_event("BUILD-001", "spec_ready")),
        ]
        self.assertEqual(_derive_build_status("BUILD-001", events), "pending_review")

    def test_derive_status_none_for_unknown_id(self) -> None:
        self.assertIsNone(_derive_build_status("BUILD-999", []))

    def test_derive_status_uses_latest_event(self) -> None:
        events = [
            json.loads(_sample_log_event("BUILD-001", "request_queued", "2026-04-11T00:00:00+00:00")),
            json.loads(_sample_log_event("BUILD-001", "spec_ready",     "2026-04-11T00:01:00+00:00")),
            json.loads(_sample_log_event("BUILD-001", "spec_approved",  "2026-04-11T00:02:00+00:00")),
        ]
        self.assertEqual(_derive_build_status("BUILD-001", events), "spec_approved")

    # ── _check_offlimits ────────────────────────────────────────────────────────

    def test_offlimits_none_found(self) -> None:
        self.assertEqual(_check_offlimits("add a new route for count"), [])

    def test_offlimits_main_py_detected(self) -> None:
        result = _check_offlimits("this requires touching app/main.py")
        self.assertIn("app/main.py", result)

    def test_offlimits_multiple_detected(self) -> None:
        result = _check_offlimits("touch app/main.py and scripts/ctl.sh")
        self.assertIn("app/main.py", result)
        self.assertIn("scripts/ctl.sh", result)

    # ── _parse_json_response ────────────────────────────────────────────────────

    def test_parse_json_clean(self) -> None:
        data = _parse_json_response('{"a": 1}')
        self.assertEqual(data, {"a": 1})

    def test_parse_json_with_surrounding_text(self) -> None:
        data = _parse_json_response('Here is the spec:\n{"a": 1}\nDone.')
        self.assertEqual(data, {"a": 1})

    def test_parse_json_invalid_returns_none(self) -> None:
        self.assertIsNone(_parse_json_response("not json"))

    def test_parse_json_empty_returns_none(self) -> None:
        self.assertIsNone(_parse_json_response(""))

    # ── generate_spec_packet: validation errors ────────────────────────────────

    def test_generate_no_request_queued_event(self) -> None:
        result = generate_spec_packet("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertIn("No request_queued", result["error"])

    def test_generate_wrong_state_spec_ready(self) -> None:
        self._write_log(
            _sample_log_event("BUILD-001", "request_queued"),
            _sample_log_event("BUILD-001", "spec_ready"),
        )
        result = generate_spec_packet("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("pending_spec", result["error"])

    def test_generate_missing_request_file(self) -> None:
        self._write_log(_sample_log_event("BUILD-001", "request_queued"))
        # No request file written
        result = generate_spec_packet("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertIn("Request file not found", result["error"])

    # ── generate_spec_packet: success path ────────────────────────────────────

    def _setup_queued_build(self, build_id: str = "BUILD-001") -> None:
        self._write_log(_sample_log_event(build_id, "request_queued"))
        self._write_request(build_id)

    def test_generate_ok_returns_true(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        self.assertTrue(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertIsNone(result["error"])

    def test_generate_writes_spec_yaml(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        self.assertTrue(pathlib.Path(result["spec_path"]).exists())

    def test_generate_writes_preflight_md(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        self.assertTrue(pathlib.Path(result["preflight_path"]).exists())

    def test_generate_appends_spec_ready_event(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            generate_spec_packet("BUILD-001")
        events = self._read_log_events()
        event_types = [e["event"] for e in events]
        self.assertIn("spec_ready", event_types)

    def test_generate_spec_ready_event_has_build_id(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            generate_spec_packet("BUILD-001")
        events = self._read_log_events()
        spec_ready = next(e for e in events if e["event"] == "spec_ready")
        self.assertEqual(spec_ready["build_id"], "BUILD-001")

    def test_generate_creates_staging_directory(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        self.assertTrue(pathlib.Path(result["staging_path"]).is_dir())

    def test_generate_status_becomes_pending_review(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            generate_spec_packet("BUILD-001")
        events = self._read_log_events()
        status = _derive_build_status("BUILD-001", events)
        self.assertEqual(status, "pending_review")

    # ── spec.yaml content ──────────────────────────────────────────────────────

    def test_spec_yaml_contains_build_id(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["spec_path"]).read_text()
        self.assertIn("BUILD-001", content)

    def test_spec_yaml_contains_success_criteria(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["spec_path"]).read_text()
        self.assertIn("success_criteria", content)

    def test_spec_yaml_contains_affected_files(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["spec_path"]).read_text()
        self.assertIn("affected_files", content)
        self.assertIn("frank_lloyd_count.py", content)

    def test_spec_yaml_contains_architecture_layer(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["spec_path"]).read_text()
        self.assertIn("architecture_layer", content)

    def test_spec_yaml_contains_blast_radius(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["spec_path"]).read_text()
        self.assertIn("blast_radius", content)

    def test_spec_yaml_offlimits_flagged_when_present(self) -> None:
        self._write_log(_sample_log_event("BUILD-001", "request_queued"))
        # Request that mentions app/main.py
        req = _sample_request()
        req["description"] += " requires touching app/main.py"
        self._req_dir.mkdir(parents=True, exist_ok=True)
        (self._req_dir / "BUILD-001_request.json").write_text(json.dumps(req))
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["spec_path"]).read_text()
        self.assertIn("offlimits_required", content)
        self.assertIn("app/main.py", content)

    def test_spec_yaml_no_offlimits_section_when_clean(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["spec_path"]).read_text()
        self.assertNotIn("offlimits_required", content)

    # ── preflight.md content ───────────────────────────────────────────────────

    def test_preflight_has_all_8_sections(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["preflight_path"]).read_text()
        for i in range(1, 9):
            self.assertIn(f"## {i}.", content, f"Missing section {i}")

    def test_preflight_q4_clean_when_no_offlimits(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["preflight_path"]).read_text()
        self.assertIn("No off-limits files required", content)

    def test_preflight_q4_flagged_when_offlimits(self) -> None:
        self._write_log(_sample_log_event("BUILD-001", "request_queued"))
        req = _sample_request()
        req["description"] += " and scripts/ctl.sh"
        self._req_dir.mkdir(parents=True, exist_ok=True)
        (self._req_dir / "BUILD-001_request.json").write_text(json.dumps(req))
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["preflight_path"]).read_text()
        self.assertIn("FLAGGED", content)
        self.assertIn("scripts/ctl.sh", content)

    def test_preflight_q8_always_present(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["preflight_path"]).read_text()
        self.assertIn("Spec approval", content)
        self.assertIn("does not authorize Stage 2", content)

    def test_preflight_contains_build_id(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            result = generate_spec_packet("BUILD-001")
        content = pathlib.Path(result["preflight_path"]).read_text()
        self.assertIn("BUILD-001", content)

    # ── LM failure → blocked path ─────────────────────────────────────────────

    def test_lm_failure_returns_blocked_true(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_FAIL):
            result = generate_spec_packet("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])

    def test_lm_failure_writes_blocked_md(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_FAIL):
            result = generate_spec_packet("BUILD-001")
        blocked_path = pathlib.Path(result["staging_path"]) / "blocked.md"
        self.assertTrue(blocked_path.exists())

    def test_lm_failure_appends_blocked_event(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_FAIL):
            generate_spec_packet("BUILD-001")
        events = self._read_log_events()
        event_types = [e["event"] for e in events]
        self.assertIn("blocked", event_types)

    def test_lm_failure_no_spec_yaml_written(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_FAIL):
            result = generate_spec_packet("BUILD-001")
        self.assertIsNone(result["spec_path"])
        # staging dir exists (for blocked.md) but no spec.yaml
        staging = pathlib.Path(result["staging_path"])
        self.assertFalse((staging / "spec.yaml").exists())

    def test_lm_failure_build_stays_pending_spec(self) -> None:
        self._setup_queued_build()
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_FAIL):
            generate_spec_packet("BUILD-001")
        # blocked event is not a Stage 1 terminal/advancement event
        events = self._read_log_events()
        status = _derive_build_status("BUILD-001", events)
        # blocked event is not in _STATUS_FROM_EVENT, so status stays as latest known
        self.assertEqual(status, "pending_spec")

    # ── missing-directory handling ─────────────────────────────────────────────

    def test_generate_creates_missing_staging_dir(self) -> None:
        self._setup_queued_build()
        self.assertFalse(self._staging_dir.exists())
        with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
            generate_spec_packet("BUILD-001")
        self.assertTrue(self._staging_dir.exists())

    def test_generate_creates_missing_log_parent(self) -> None:
        self._write_request("BUILD-001")
        # Write log manually to a non-existent parent
        deep_log = pathlib.Path(self._tmpdir) / "deep" / "nested" / "build_log.jsonl"
        sw._FL_BUILD_LOG = deep_log
        try:
            # Seed with a request_queued event
            deep_log.parent.mkdir(parents=True, exist_ok=True)
            deep_log.write_text(
                _sample_log_event("BUILD-001", "request_queued") + "\n"
            )
            with patch.object(sw, "_call_spec_lm", return_value=_MOCK_LM_OK):
                result = generate_spec_packet("BUILD-001")
            self.assertTrue(result["ok"])
        finally:
            sw._FL_BUILD_LOG = self._orig["_FL_BUILD_LOG"]


if __name__ == "__main__":
    unittest.main()
