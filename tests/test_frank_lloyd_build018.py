# tests/test_frank_lloyd_build018.py
#
# BUILD-018 Phase 2: Tests for:
#   - GET /frank-lloyd/active-job HTTP endpoint
#   - active_job field in _frank_lloyd_state() / /neighborhood/state
#
# Run with:
#   python -m pytest tests/test_frank_lloyd_build018.py -v

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
import frank_lloyd.job as fl_job
import app.routes.neighborhood as nbhd

client = TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(offset: int = 0) -> str:
    from datetime import timedelta
    base = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=offset)).isoformat()


def _ev(build_id: str, event: str, ts_offset: int = 0, extra: dict | None = None) -> dict:
    return {
        "timestamp": _ts(ts_offset),
        "build_id":  build_id,
        "event":     event,
        "notes":     "",
        "extra":     extra or {},
    }


class _Env:
    """Temp dir that patches fl_job path constants."""

    def __init__(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp())

    @property
    def build_log(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "build_log.jsonl"

    @property
    def requests_dir(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "requests"

    def setup(self):
        self.build_log.parent.mkdir(parents=True, exist_ok=True)
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self._orig_log  = fl_job._FL_BUILD_LOG
        self._orig_reqs = fl_job._FL_REQUESTS
        fl_job._FL_BUILD_LOG = self.build_log
        fl_job._FL_REQUESTS  = self.requests_dir

    def restore(self):
        fl_job._FL_BUILD_LOG = self._orig_log
        fl_job._FL_REQUESTS  = self._orig_reqs

    def cleanup(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def write_log(self, events: list[dict]):
        self.build_log.parent.mkdir(parents=True, exist_ok=True)
        with self.build_log.open("w") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

    def write_request(self, build_id: str, description: str = "Build something useful for the system"):
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        (self.requests_dir / f"{build_id}_request.json").write_text(
            json.dumps({"description": description, "success_criterion": "it works"})
        )


# ── GET /frank-lloyd/active-job ───────────────────────────────────────────────

class TestActiveJobEndpoint(unittest.TestCase):

    def setUp(self):
        self.env = _Env()
        self.env.setup()

    def tearDown(self):
        self.env.restore()
        self.env.cleanup()

    def test_no_builds_returns_ok_false(self):
        r = client.get("/frank-lloyd/active-job")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIsNone(body["job"])
        self.assertIn("error", body)

    def test_empty_log_returns_ok_false(self):
        self.env.write_log([])
        r = client.get("/frank-lloyd/active-job")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIsNone(body["job"])

    def test_pending_spec_build_returned(self):
        bid = "BUILD-2026-0001"
        self.env.write_log([_ev(bid, "request_queued", 0)])
        self.env.write_request(bid, "Add a new reporting endpoint for metrics display")
        r = client.get("/frank-lloyd/active-job")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        job = body["job"]
        self.assertIsNotNone(job)
        self.assertEqual(job["build_id"], bid)
        self.assertEqual(job["status"], "pending_spec")
        self.assertEqual(job["phase"],  "intake")
        self.assertEqual(job["waiting_on"], "system")

    def test_pending_review_has_highest_priority(self):
        b1 = "BUILD-2026-0001"
        b2 = "BUILD-2026-0002"
        self.env.write_log([
            _ev(b1, "request_queued",  0),
            _ev(b2, "request_queued", 10),
            _ev(b2, "spec_ready",     20),
        ])
        r = client.get("/frank-lloyd/active-job")
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["job"]["build_id"], b2)
        self.assertEqual(body["job"]["status"],   "pending_review")

    def test_job_dict_has_expected_fields(self):
        bid = "BUILD-2026-0003"
        self.env.write_log([
            _ev(bid, "request_queued", 0),
            _ev(bid, "spec_ready",  5),
        ])
        r = client.get("/frank-lloyd/active-job")
        job = r.json()["job"]
        for field in ("build_id", "title", "status", "phase",
                      "next_action", "waiting_on", "requested_at", "updated_at"):
            self.assertIn(field, job, f"missing field: {field}")

    def test_draft_generated_supersedes_pending_spec(self):
        b1 = "BUILD-2026-0010"
        b2 = "BUILD-2026-0011"
        self.env.write_log([
            _ev(b1, "request_queued",    0),
            _ev(b2, "request_queued",   10),
            _ev(b2, "spec_ready",       20),
            _ev(b2, "spec_approved",    30),
            _ev(b2, "stage2_authorized",40),
            _ev(b2, "draft_generated",  50),
        ])
        r = client.get("/frank-lloyd/active-job")
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["job"]["build_id"], b2)
        self.assertEqual(body["job"]["status"],   "draft_generated")
        self.assertEqual(body["job"]["phase"],    "building")


# ── active_job field in _frank_lloyd_state() ─────────────────────────────────

class TestNeighborhoodStateActiveJob(unittest.TestCase):
    """
    Tests that _frank_lloyd_state() includes an 'active_job' key and that it
    reflects the correct FLJob when builds are present.
    """

    def setUp(self):
        self.env = _Env()
        self.env.setup()

    def tearDown(self):
        self.env.restore()
        self.env.cleanup()

    def _fl_state(self) -> dict:
        """Call the private function directly — avoids full /neighborhood/state overhead."""
        return nbhd._frank_lloyd_state()

    def test_active_job_key_present_when_no_builds(self):
        s = self._fl_state()
        self.assertIn("active_job", s)

    def test_active_job_none_when_no_log(self):
        s = self._fl_state()
        self.assertIsNone(s["active_job"])

    def test_active_job_none_when_empty_log(self):
        self.env.write_log([])
        s = self._fl_state()
        self.assertIsNone(s["active_job"])

    def test_active_job_populated_for_pending_spec(self):
        bid = "BUILD-2026-0020"
        self.env.write_log([_ev(bid, "request_queued", 0)])
        self.env.write_request(bid, "Add a telemetry endpoint for the dashboard panel")
        s = self._fl_state()
        self.assertIsNotNone(s["active_job"])
        self.assertEqual(s["active_job"]["build_id"], bid)
        self.assertEqual(s["active_job"]["status"],   "pending_spec")
        self.assertEqual(s["active_job"]["phase"],    "intake")

    def test_active_job_fields_match_fljob_to_dict(self):
        bid = "BUILD-2026-0021"
        self.env.write_log([
            _ev(bid, "request_queued", 0),
            _ev(bid, "spec_ready",  5),
        ])
        s   = self._fl_state()
        job = s["active_job"]
        self.assertIsNotNone(job)
        for field in ("build_id", "title", "status", "phase",
                      "next_action", "waiting_on"):
            self.assertIn(field, job, f"missing field: {field}")

    def test_active_job_fallback_key_present_on_exception(self):
        """The except branch must also return active_job: None."""
        # Corrupt the build_log path so frank_lloyd_status fails
        fl_job._FL_BUILD_LOG = pathlib.Path("/nonexistent/path/build_log.jsonl")
        s = nbhd._frank_lloyd_state()
        self.assertIn("active_job", s)
        self.assertIsNone(s["active_job"])


if __name__ == "__main__":
    unittest.main()
