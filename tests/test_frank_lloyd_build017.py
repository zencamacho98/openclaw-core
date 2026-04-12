# tests/test_frank_lloyd_build017.py
#
# BUILD-017: Tests for:
#   1. GET /frank-lloyd/{build_id}/spec-review  — new endpoint
#   2. Three-bucket status semantics (pending / inprogress / completed)
#
# Run with:
#   python -m pytest tests/test_frank_lloyd_build017.py -v

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
import app.routes.frank_lloyd_status as fl_status
import app.routes.frank_lloyd_actions as fl_actions

client = TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ev(build_id: str, event: str, ts: str = "2026-04-11T10:00:00+00:00") -> dict:
    return {"timestamp": ts, "build_id": build_id, "event": event,
            "notes": "", "extra": {}}


class _Env:
    """Temp directory with staged spec artifacts and a patched build log."""

    def __init__(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp())

    @property
    def build_log(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "build_log.jsonl"

    @property
    def staging(self) -> pathlib.Path:
        return self._tmp / "staging" / "frank_lloyd"

    @property
    def archives(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "archives"

    def setup(self):
        self.build_log.parent.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        self.archives.mkdir(parents=True, exist_ok=True)
        # Patch fl_actions module paths
        self._orig_root = fl_actions._ROOT
        fl_actions._ROOT = self._tmp
        # Patch fl_status module paths
        self._orig_fl_log = fl_status._BUILD_LOG
        self._orig_fl_req = fl_status._REQUESTS_DIR
        fl_status._BUILD_LOG    = self.build_log
        fl_status._REQUESTS_DIR = self._tmp / "data" / "frank_lloyd" / "requests"

    def restore(self):
        fl_actions._ROOT        = self._orig_root
        fl_status._BUILD_LOG    = self._orig_fl_log
        fl_status._REQUESTS_DIR = self._orig_fl_req

    def cleanup(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def write_log(self, events: list[dict]):
        with self.build_log.open("a", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def write_spec(self, build_id: str, location: str = "staging",
                   spec_content: str = "build_id: TEST\nrisk_level: low\n",
                   preflight_content: str = "# Preflight\nAll checks pass.\n"):
        """Write spec artifacts to staging or archives."""
        if location == "staging":
            d = self.staging / build_id
        else:
            d = self.archives / build_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.yaml").write_text(spec_content, encoding="utf-8")
        (d / "preflight.md").write_text(preflight_content, encoding="utf-8")


# ── Tests: spec-review endpoint ───────────────────────────────────────────────

class TestSpecReviewEndpoint(unittest.TestCase):

    def setUp(self):
        self._env = _Env()
        self._env.setup()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_pending_review_returns_spec_from_staging(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-001", "spec_ready",     "2026-04-11T10:10:00+00:00"),
        ])
        self._env.write_spec("BUILD-001", location="staging",
                             spec_content="build_id: BUILD-001\nrisk_level: low\n")
        resp = client.get("/frank-lloyd/BUILD-001/spec-review")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "pending_review")
        self.assertIn("BUILD-001", body["spec_yaml"])
        self.assertIn("Preflight", body["preflight_md"])

    def test_spec_approved_returns_spec_from_archives(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-001", "spec_ready",     "2026-04-11T10:10:00+00:00"),
            _ev("BUILD-001", "spec_approved",  "2026-04-11T10:20:00+00:00"),
        ])
        self._env.write_spec("BUILD-001", location="archives",
                             spec_content="build_id: BUILD-001\narchived: true\n")
        resp = client.get("/frank-lloyd/BUILD-001/spec-review")
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertIn("archived", body["spec_yaml"])

    def test_stage2_authorized_returns_spec_from_archives(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued",    "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-001", "spec_ready",        "2026-04-11T10:10:00+00:00"),
            _ev("BUILD-001", "spec_approved",     "2026-04-11T10:20:00+00:00"),
            _ev("BUILD-001", "stage2_authorized", "2026-04-11T11:00:00+00:00"),
        ])
        self._env.write_spec("BUILD-001", location="archives")
        body = client.get("/frank-lloyd/BUILD-001/spec-review").json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "stage2_authorized")

    def test_pending_spec_returns_ok_false_no_spec_yet(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", "2026-04-11T10:00:00+00:00"),
        ])
        body = client.get("/frank-lloyd/BUILD-001/spec-review").json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["status"], "pending_spec")
        self.assertIn("not been generated", body["error"])

    def test_unknown_build_returns_ok_false(self):
        body = client.get("/frank-lloyd/BUILD-999/spec-review").json()
        self.assertFalse(body["ok"])
        self.assertIn("BUILD-999", body["error"])

    def test_build_id_uppercased(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued", "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-001", "spec_ready",     "2026-04-11T10:10:00+00:00"),
        ])
        self._env.write_spec("BUILD-001", location="staging")
        body = client.get("/frank-lloyd/build-001/spec-review").json()
        self.assertEqual(body["build_id"], "BUILD-001")

    def test_missing_artifacts_returns_ok_false(self):
        """spec_ready state but no staging artifacts written."""
        self._env.write_log([
            _ev("BUILD-001", "request_queued", "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-001", "spec_ready",     "2026-04-11T10:10:00+00:00"),
        ])
        # No spec artifacts written
        body = client.get("/frank-lloyd/BUILD-001/spec-review").json()
        self.assertFalse(body["ok"])
        self.assertIn("not found", body["error"])

    def test_post_approval_falls_back_to_staging_if_archive_empty(self):
        """If archive has no spec.yaml, fall back to staging."""
        self._env.write_log([
            _ev("BUILD-001", "request_queued", "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-001", "spec_ready",     "2026-04-11T10:10:00+00:00"),
            _ev("BUILD-001", "spec_approved",  "2026-04-11T10:20:00+00:00"),
        ])
        # Write spec to staging only (archive is empty)
        self._env.write_spec("BUILD-001", location="staging",
                             spec_content="build_id: STAGING_FALLBACK\n")
        body = client.get("/frank-lloyd/BUILD-001/spec-review").json()
        self.assertTrue(body["ok"])
        self.assertIn("STAGING_FALLBACK", body["spec_yaml"])

    def test_draft_generated_returns_ok_and_spec_from_archives(self):
        self._env.write_log([
            _ev("BUILD-001", "request_queued",    "2026-04-11T10:00:00+00:00"),
            _ev("BUILD-001", "spec_ready",        "2026-04-11T10:10:00+00:00"),
            _ev("BUILD-001", "spec_approved",     "2026-04-11T10:20:00+00:00"),
            _ev("BUILD-001", "stage2_authorized", "2026-04-11T11:00:00+00:00"),
            _ev("BUILD-001", "draft_generated",   "2026-04-11T11:15:00+00:00"),
        ])
        self._env.write_spec("BUILD-001", location="archives")
        body = client.get("/frank-lloyd/BUILD-001/spec-review").json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "draft_generated")


# ── Tests: three-bucket semantics ────────────────────────────────────────────

class TestThreeBucketSemantics(unittest.TestCase):
    """Verify the inprogress / completed boundary is correctly placed."""

    def setUp(self):
        self._env = _Env()
        self._env.setup()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def _get_status(self) -> dict:
        return client.get("/frank-lloyd/status").json()

    def _log(self, *events):
        self._env.write_log(list(events))

    def test_spec_approved_not_in_completed(self):
        self._log(_ev("BUILD-001", "request_queued"), _ev("BUILD-001", "spec_approved"))
        body = self._get_status()
        self.assertEqual(len(body["completed_builds"]),  0)
        self.assertEqual(len(body["inprogress_builds"]), 1)

    def test_stage2_authorized_not_in_completed(self):
        self._log(_ev("BUILD-001", "request_queued"),
                  _ev("BUILD-001", "spec_approved"),
                  _ev("BUILD-001", "stage2_authorized"))
        self.assertEqual(len(self._get_status()["completed_builds"]), 0)

    def test_draft_generated_not_in_completed(self):
        self._log(_ev("BUILD-001", "request_queued"),
                  _ev("BUILD-001", "spec_approved"),
                  _ev("BUILD-001", "stage2_authorized"),
                  _ev("BUILD-001", "draft_generated"))
        self.assertEqual(len(self._get_status()["completed_builds"]), 0)

    def test_draft_blocked_not_in_completed(self):
        self._log(_ev("BUILD-001", "request_queued"),
                  _ev("BUILD-001", "spec_approved"),
                  _ev("BUILD-001", "stage2_authorized"),
                  _ev("BUILD-001", "draft_blocked"))
        self.assertEqual(len(self._get_status()["completed_builds"]), 0)

    def test_draft_promoted_in_completed_not_inprogress(self):
        self._log(_ev("BUILD-001", "request_queued"),
                  _ev("BUILD-001", "spec_approved"),
                  _ev("BUILD-001", "stage2_authorized"),
                  _ev("BUILD-001", "draft_generated"),
                  _ev("BUILD-001", "draft_promoted"))
        body = self._get_status()
        self.assertEqual(len(body["inprogress_builds"]), 0)
        self.assertEqual(len(body["completed_builds"]),  1)

    def test_spec_rejected_in_completed_not_inprogress(self):
        self._log(_ev("BUILD-001", "request_queued"), _ev("BUILD-001", "spec_rejected"))
        body = self._get_status()
        self.assertEqual(len(body["inprogress_builds"]), 0)
        self.assertEqual(len(body["completed_builds"]),  1)

    def test_abandoned_in_completed_not_inprogress(self):
        self._log(_ev("BUILD-001", "request_queued"), _ev("BUILD-001", "abandoned"))
        body = self._get_status()
        self.assertEqual(len(body["inprogress_builds"]), 0)
        self.assertEqual(len(body["completed_builds"]),  1)

    def test_response_has_inprogress_builds_key(self):
        body = self._get_status()
        self.assertIn("inprogress_builds", body)

    def test_summary_has_inprogress_count(self):
        self._log(_ev("BUILD-001", "request_queued"), _ev("BUILD-001", "spec_approved"))
        summary = self._get_status()["summary"]
        self.assertIn("inprogress_count", summary)
        self.assertEqual(summary["inprogress_count"], 1)
        self.assertEqual(summary["completed_count"],  0)

    def test_draft_discarded_stays_inprogress_as_stage2_authorized(self):
        """draft_discarded resets build to stage2_authorized — still in progress."""
        self._log(_ev("BUILD-001", "request_queued"),
                  _ev("BUILD-001", "spec_approved"),
                  _ev("BUILD-001", "stage2_authorized"),
                  _ev("BUILD-001", "draft_generated"),
                  _ev("BUILD-001", "draft_discarded"))
        body = self._get_status()
        inprog = body["inprogress_builds"]
        self.assertEqual(len(inprog), 1)
        self.assertEqual(inprog[0]["status"], "stage2_authorized")
        self.assertEqual(len(body["completed_builds"]), 0)


if __name__ == "__main__":
    unittest.main()
