"""
tests/test_frank_lloyd_status.py

Route tests for GET /frank-lloyd/status (BUILD-002).

Covers:
  - missing build log file returns 200 with empty lists
  - missing data/frank_lloyd/ directory returns 200 with empty lists
  - empty log file (exists but empty) returns 200 with empty lists
  - builder_stage is always 1
  - response has all required shape fields
  - request_queued → pending_spec in pending_builds
  - request_queued + spec_ready → pending_review in pending_builds
  - spec_approved → completed_builds with status spec_approved
  - spec_rejected → completed_builds with status spec_rejected
  - abandoned → completed_builds with status abandoned
  - title from request_queued.extra.title
  - title fallback from request file when no request_queued event
  - title fallback to build_id when neither source has title
  - build_type_hint from request_queued.extra
  - spec_approved carries build_type, risk_level, stage_completed
  - spec_rejected and abandoned have null build_type, risk_level, stage_completed
  - summary counts are correct across mixed statuses
  - multiple builds with mixed statuses bucket correctly
  - unknown/future Stage 2 events are skipped — latest Stage 1 event governs
  - malformed JSONL lines are skipped without crashing
  - completed_builds sorted newest-first by resolved_at
  - pending_builds sorted newest-first by requested_at

Run with:
    python -m pytest tests/test_frank_lloyd_status.py -v
    python -m unittest tests.test_frank_lloyd_status -v
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

import app.routes.frank_lloyd_status as fl
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


# ── Event factory helpers ─────────────────────────────────────────────────────

def _ev(
    build_id: str,
    event: str,
    timestamp: str = "2026-04-11T10:00:00+00:00",
    notes: str | None = None,
    extra: dict | None = None,
) -> dict:
    return {
        "timestamp": timestamp,
        "build_id":  build_id,
        "event":     event,
        "notes":     notes,
        "extra":     extra or {},
    }


def _request_queued(
    build_id: str,
    title: str,
    timestamp: str,
    build_type_hint: str | None = "platform_capability",
) -> dict:
    return _ev(build_id, "request_queued", timestamp=timestamp, extra={
        "title":           title,
        "build_type_hint": build_type_hint,
        "requester":       "operator",
    })


def _spec_approved(build_id: str, timestamp: str) -> dict:
    return _ev(build_id, "spec_approved", timestamp=timestamp, extra={
        "build_type":       "platform_capability",
        "risk_level":       "critical",
        "new_files":        ["app/routes/builder_status.py"],
        "modified_files":   ["app/main.py"],
        "sentinel_scope":   "targeted",
        "stage_completed":  1,
        "stage2_authorized": False,
    })


# ── Test class ────────────────────────────────────────────────────────────────

class TestBuilderStatusRoute(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_log      = fl._BUILD_LOG
        self._orig_requests = fl._REQUESTS_DIR
        self._log_path = pathlib.Path(self._tmpdir) / "build_log.jsonl"
        self._req_dir  = pathlib.Path(self._tmpdir) / "requests"
        fl._BUILD_LOG    = self._log_path
        fl._REQUESTS_DIR = self._req_dir

    def tearDown(self):
        fl._BUILD_LOG    = self._orig_log
        fl._REQUESTS_DIR = self._orig_requests
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_log(self, events: list[dict]) -> None:
        with self._log_path.open("w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def _write_request_file(self, build_id: str, title: str) -> None:
        self._req_dir.mkdir(parents=True, exist_ok=True)
        path = self._req_dir / f"{build_id}_request.json"
        path.write_text(json.dumps({
            "request_id":      build_id,
            "title":           title,
            "description":     "...",
            "requester":       "operator",
            "requested_at":    "2026-04-11T10:00:00+00:00",
            "success_criteria": "...",
        }), encoding="utf-8")

    # ── empty / missing state ─────────────────────────────────────────────────

    def test_missing_log_returns_200_empty_lists(self):
        # _BUILD_LOG was never created
        resp = client.get("/frank-lloyd/status")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["pending_builds"], [])
        self.assertEqual(body["completed_builds"], [])

    def test_missing_data_frank_lloyd_dir_returns_200(self):
        # Entire temp dir is empty — no subdirectories
        resp = client.get("/frank-lloyd/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["pending_builds"], [])

    def test_empty_log_file_returns_200_empty_lists(self):
        self._log_path.touch()  # exists but has no content
        resp = client.get("/frank-lloyd/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["pending_builds"], [])
        self.assertEqual(resp.json()["completed_builds"], [])

    # ── response shape ────────────────────────────────────────────────────────

    def test_builder_stage_is_always_1(self):
        resp = client.get("/frank-lloyd/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["builder_stage"], 1)

    def test_response_has_all_required_top_level_fields(self):
        resp = client.get("/frank-lloyd/status")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("builder_stage", "pending_builds", "completed_builds", "summary"):
            self.assertIn(key, body, f"Missing top-level key: {key}")

    def test_summary_has_all_required_fields(self):
        resp = client.get("/frank-lloyd/status")
        summary = resp.json()["summary"]
        for key in ("pending_count", "completed_count", "approved_count",
                    "rejected_count", "abandoned_count"):
            self.assertIn(key, summary, f"Missing summary key: {key}")

    # ── status derivation ─────────────────────────────────────────────────────

    def test_request_queued_is_pending_spec(self):
        self._write_log([_request_queued("BUILD-002", "My build", "2026-04-11T10:00:00+00:00")])
        resp = client.get("/frank-lloyd/status")
        pending = resp.json()["pending_builds"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["build_id"], "BUILD-002")
        self.assertEqual(pending[0]["status"],   "pending_spec")

    def test_request_queued_plus_spec_ready_is_pending_review(self):
        self._write_log([
            _request_queued("BUILD-002", "My build", "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-002", "spec_ready", "2026-04-11T10:20:00+00:00"),
        ])
        pending = client.get("/frank-lloyd/status").json()["pending_builds"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "pending_review")

    def test_spec_approved_in_completed(self):
        self._write_log([
            _request_queued("BUILD-001", "Event log query", "2026-04-11T10:00:00+00:00"),
            _spec_approved("BUILD-001", "2026-04-11T10:30:00+00:00"),
        ])
        body = client.get("/frank-lloyd/status").json()
        self.assertEqual(len(body["pending_builds"]),   0)
        self.assertEqual(len(body["completed_builds"]), 1)
        self.assertEqual(body["completed_builds"][0]["status"], "spec_approved")

    def test_spec_rejected_in_completed(self):
        self._write_log([
            _request_queued("BUILD-002", "My build", "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-002", "spec_rejected", "2026-04-11T10:20:00+00:00",
                extra={"revision_cycle": 1, "reason": "Too wide"}),
        ])
        completed = client.get("/frank-lloyd/status").json()["completed_builds"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["status"], "spec_rejected")

    def test_abandoned_in_completed(self):
        self._write_log([
            _request_queued("BUILD-002", "My build", "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-002", "abandoned", "2026-04-11T10:30:00+00:00",
                extra={"revision_cycles_completed": 3}),
        ])
        completed = client.get("/frank-lloyd/status").json()["completed_builds"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["status"], "abandoned")

    # ── field values ──────────────────────────────────────────────────────────

    def test_title_from_request_queued_extra(self):
        self._write_log([
            _request_queued("BUILD-002", "Builder status endpoint", "2026-04-11T10:00:00+00:00"),
        ])
        pending = client.get("/frank-lloyd/status").json()["pending_builds"]
        self.assertEqual(pending[0]["title"], "Builder status endpoint")

    def test_title_fallback_from_request_file(self):
        # No request_queued event in log — title must come from request file
        self._write_log([_ev("BUILD-002", "spec_ready", "2026-04-11T10:00:00+00:00")])
        self._write_request_file("BUILD-002", "From request file")
        pending = client.get("/frank-lloyd/status").json()["pending_builds"]
        self.assertEqual(pending[0]["title"], "From request file")

    def test_title_fallback_to_build_id_when_no_source(self):
        # No request_queued, no request file — defaults to build_id
        self._write_log([_ev("BUILD-999", "spec_ready", "2026-04-11T10:00:00+00:00")])
        pending = client.get("/frank-lloyd/status").json()["pending_builds"]
        self.assertEqual(pending[0]["title"], "BUILD-999")

    def test_build_type_hint_from_request_queued(self):
        self._write_log([
            _request_queued("BUILD-002", "My build", "2026-04-11T10:00:00+00:00",
                            build_type_hint="platform_capability"),
        ])
        pending = client.get("/frank-lloyd/status").json()["pending_builds"]
        self.assertEqual(pending[0]["build_type_hint"], "platform_capability")

    def test_spec_approved_carries_build_type_risk_level_stage(self):
        self._write_log([
            _request_queued("BUILD-001", "Event log query", "2026-04-11T10:00:00+00:00"),
            _spec_approved("BUILD-001", "2026-04-11T10:30:00+00:00"),
        ])
        item = client.get("/frank-lloyd/status").json()["completed_builds"][0]
        self.assertEqual(item["build_type"],     "platform_capability")
        self.assertEqual(item["risk_level"],     "critical")
        self.assertEqual(item["stage_completed"], 1)

    def test_spec_rejected_has_null_build_type_and_stage(self):
        self._write_log([
            _request_queued("BUILD-002", "My build", "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-002", "spec_rejected", "2026-04-11T10:20:00+00:00"),
        ])
        item = client.get("/frank-lloyd/status").json()["completed_builds"][0]
        self.assertIsNone(item["build_type"])
        self.assertIsNone(item["risk_level"])
        self.assertIsNone(item["stage_completed"])

    def test_abandoned_has_null_build_type_and_stage(self):
        self._write_log([
            _request_queued("BUILD-002", "My build", "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-002", "abandoned", "2026-04-11T10:30:00+00:00"),
        ])
        item = client.get("/frank-lloyd/status").json()["completed_builds"][0]
        self.assertIsNone(item["build_type"])
        self.assertIsNone(item["stage_completed"])

    # ── summary counts ────────────────────────────────────────────────────────

    def test_summary_counts_correct(self):
        self._write_log([
            _request_queued("BUILD-001", "Approved", "2026-04-11T08:00:00+00:00"),
            _spec_approved("BUILD-001", "2026-04-11T08:30:00+00:00"),
            _request_queued("BUILD-002", "Rejected", "2026-04-11T09:00:00+00:00"),
            _ev("BUILD-002", "spec_rejected", "2026-04-11T09:20:00+00:00"),
            _request_queued("BUILD-003", "Pending",  "2026-04-11T10:00:00+00:00"),
        ])
        summary = client.get("/frank-lloyd/status").json()["summary"]
        self.assertEqual(summary["pending_count"],   1)
        self.assertEqual(summary["completed_count"], 2)
        self.assertEqual(summary["approved_count"],  1)
        self.assertEqual(summary["rejected_count"],  1)
        self.assertEqual(summary["abandoned_count"], 0)

    # ── multiple builds / bucketing ───────────────────────────────────────────

    def test_multiple_builds_bucket_correctly(self):
        self._write_log([
            _request_queued("BUILD-001", "Approved",  "2026-04-11T08:00:00+00:00"),
            _spec_approved("BUILD-001", "2026-04-11T08:30:00+00:00"),
            _request_queued("BUILD-002", "Pending",   "2026-04-11T09:00:00+00:00"),
            _request_queued("BUILD-003", "Abandoned", "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-003", "abandoned", "2026-04-11T10:20:00+00:00"),
        ])
        body = client.get("/frank-lloyd/status").json()
        self.assertEqual(len(body["pending_builds"]),   1)
        self.assertEqual(len(body["completed_builds"]), 2)
        self.assertEqual({b["build_id"] for b in body["pending_builds"]},   {"BUILD-002"})
        self.assertEqual({b["build_id"] for b in body["completed_builds"]}, {"BUILD-001", "BUILD-003"})

    # ── resilience ────────────────────────────────────────────────────────────

    def test_unknown_future_events_are_skipped(self):
        # Stage 2+ event "promoted" appears after spec_approved — must not change status
        self._write_log([
            _request_queued("BUILD-001", "My build", "2026-04-11T10:00:00+00:00"),
            _spec_approved("BUILD-001", "2026-04-11T10:20:00+00:00"),
            _ev("BUILD-001", "promoted", "2026-04-11T10:30:00+00:00"),
        ])
        completed = client.get("/frank-lloyd/status").json()["completed_builds"]
        self.assertEqual(len(completed), 1)
        # "promoted" is not a Stage 1 event; latest known Stage 1 event is spec_approved
        self.assertEqual(completed[0]["status"], "spec_approved")

    def test_malformed_lines_skipped_no_crash(self):
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(_request_queued("BUILD-001", "Good", "2026-04-11T10:00:00+00:00")) + "\n")
            fh.write("NOT JSON AT ALL\n")
            fh.write("{incomplete json\n")
            fh.write("\n")  # blank line
        resp = client.get("/frank-lloyd/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["pending_builds"]), 1)

    def test_events_without_build_id_are_skipped(self):
        self._write_log([
            {"timestamp": "2026-04-11T10:00:00+00:00", "event": "request_queued"},  # no build_id
            _request_queued("BUILD-001", "Good build", "2026-04-11T10:01:00+00:00"),
        ])
        pending = client.get("/frank-lloyd/status").json()["pending_builds"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["build_id"], "BUILD-001")

    # ── sort order ────────────────────────────────────────────────────────────

    def test_completed_builds_sorted_newest_resolved_first(self):
        self._write_log([
            _request_queued("BUILD-001", "Older", "2026-04-11T08:00:00+00:00"),
            _spec_approved("BUILD-001", "2026-04-11T08:30:00+00:00"),
            _request_queued("BUILD-002", "Newer", "2026-04-11T09:00:00+00:00"),
            _spec_approved("BUILD-002", "2026-04-11T09:30:00+00:00"),
        ])
        completed = client.get("/frank-lloyd/status").json()["completed_builds"]
        self.assertEqual(completed[0]["build_id"], "BUILD-002")
        self.assertEqual(completed[1]["build_id"], "BUILD-001")

    def test_pending_builds_sorted_newest_requested_first(self):
        self._write_log([
            _request_queued("BUILD-001", "Older", "2026-04-11T08:00:00+00:00"),
            _request_queued("BUILD-002", "Newer", "2026-04-11T09:00:00+00:00"),
        ])
        pending = client.get("/frank-lloyd/status").json()["pending_builds"]
        self.assertEqual(pending[0]["build_id"], "BUILD-002")
        self.assertEqual(pending[1]["build_id"], "BUILD-001")


if __name__ == "__main__":
    unittest.main()
