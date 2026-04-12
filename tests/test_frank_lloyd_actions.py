# tests/test_frank_lloyd_actions.py
#
# Route tests for the Frank Lloyd action control endpoints (BUILD-006).
#
# Coverage:
#   POST /frank-lloyd/{build_id}/approve-spec
#     - delegates to frank_lloyd.spec_approver.approve_build()
#     - returns ok=True + outcome + message on success
#     - returns ok=False + error on failure (wrong state, missing artifacts)
#     - optional notes passed through
#
#   POST /frank-lloyd/{build_id}/reject-spec
#     - delegates to frank_lloyd.spec_approver.reject_build()
#     - missing reason → 200 ok=False with error message (not 422)
#     - empty reason → 200 ok=False with error message
#     - returns ok=True + outcome on success
#
#   POST /frank-lloyd/{build_id}/authorize-stage2
#     - delegates to frank_lloyd.stage2_authorizer.authorize_stage2()
#     - returns ok=True + outcome + message on success
#     - returns ok=False + error on failure (wrong state)
#     - message includes "authorization only" (no code gen claim)
#     - optional notes passed through
#
# Uses FastAPI TestClient + temporary path patching (same pattern as
# test_frank_lloyd_status.py / test_frank_lloyd_spec_approver.py).

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
import frank_lloyd.spec_approver as _fl_approver
import frank_lloyd.stage2_authorizer as _fl_s2auth

client = TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Env:
    """Redirect module path constants to a temp tree and populate minimal fixtures."""

    def __init__(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp())

    # ── Path constants to patch ──────────────────────────────────────────────
    @property
    def build_log(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "build_log.jsonl"

    @property
    def archives(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "archives"

    @property
    def requests_dir(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "requests"

    @property
    def staging(self) -> pathlib.Path:
        return self._tmp / "staging" / "frank_lloyd"

    # ── Setup / teardown ────────────────────────────────────────────────────
    def patch(self):
        self.build_log.parent.mkdir(parents=True, exist_ok=True)
        self.archives.mkdir(parents=True, exist_ok=True)
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        # Patch approver module
        self._orig_approver = {
            "log":  _fl_approver._FL_BUILD_LOG,
            "arch": _fl_approver._FL_ARCHIVES,
            "req":  _fl_approver._FL_REQUESTS,
            "stg":  _fl_approver._FL_STAGING,
        }
        _fl_approver._FL_BUILD_LOG = self.build_log
        _fl_approver._FL_ARCHIVES  = self.archives
        _fl_approver._FL_REQUESTS  = self.requests_dir
        _fl_approver._FL_STAGING   = self.staging
        # Patch authorizer module
        self._orig_s2auth = {
            "log":  _fl_s2auth._FL_BUILD_LOG,
            "arch": _fl_s2auth._FL_ARCHIVES,
        }
        _fl_s2auth._FL_BUILD_LOG = self.build_log
        _fl_s2auth._FL_ARCHIVES  = self.archives

    def restore(self):
        _fl_approver._FL_BUILD_LOG = self._orig_approver["log"]
        _fl_approver._FL_ARCHIVES  = self._orig_approver["arch"]
        _fl_approver._FL_REQUESTS  = self._orig_approver["req"]
        _fl_approver._FL_STAGING   = self._orig_approver["stg"]
        _fl_s2auth._FL_BUILD_LOG   = self._orig_s2auth["log"]
        _fl_s2auth._FL_ARCHIVES    = self._orig_s2auth["arch"]

    def cleanup(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ── Write helpers ────────────────────────────────────────────────────────
    def write_log(self, events: list[dict]):
        with self.build_log.open("a", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def _ev(self, build_id: str, event: str, extra: dict | None = None) -> dict:
        return {
            "timestamp": _ts(),
            "build_id":  build_id,
            "event":     event,
            "notes":     "",
            "extra":     extra or {},
        }

    def make_pending_review(self, build_id: str):
        """Write the minimal fixture for a build in pending_review state."""
        self.write_log([
            self._ev(build_id, "request_queued", {"title": f"Test build {build_id}"}),
            self._ev(build_id, "spec_ready"),
        ])
        # Write request file
        req = self.requests_dir / f"{build_id}_request.json"
        req.write_text(json.dumps({"request_id": build_id, "title": f"Test build {build_id}"}),
                       encoding="utf-8")
        # Write staging artifacts
        stg = self.staging / build_id
        stg.mkdir(parents=True, exist_ok=True)
        (stg / "spec.yaml").write_text("build_id: " + build_id + "\nbuild_type: test\nrisk_level: low\n",
                                       encoding="utf-8")
        (stg / "preflight.md").write_text("# Preflight\nAll checks pass.", encoding="utf-8")

    def make_spec_approved(self, build_id: str):
        """Write fixture for a build that has been spec_approved and archived."""
        self.make_pending_review(build_id)
        # Archive the build
        arch = self.archives / build_id
        arch.mkdir(parents=True, exist_ok=True)
        decision = {
            "build_id": build_id, "outcome": "spec_approved", "stage": 1,
            "decided_at": _ts(), "decided_by": "operator",
            "notes": None, "stage2_authorized": False,
        }
        (arch / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
        # Append spec_approved log event
        self.write_log([self._ev(build_id, "spec_approved", {"stage_completed": 1})])


# ── Tests: approve-spec ───────────────────────────────────────────────────────

class TestApproveSpecEndpoint(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_approve_success_returns_ok(self):
        self._env.make_pending_review("BUILD-001")
        resp = client.post("/frank-lloyd/BUILD-001/approve-spec", json={})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["build_id"], "BUILD-001")
        self.assertEqual(body["outcome"], "spec_approved")

    def test_approve_success_message_mentions_stage1_complete(self):
        self._env.make_pending_review("BUILD-001")
        body = client.post("/frank-lloyd/BUILD-001/approve-spec", json={}).json()
        self.assertIn("Stage 1 complete", body["message"])

    def test_approve_success_message_mentions_stage2_separate(self):
        self._env.make_pending_review("BUILD-001")
        body = client.post("/frank-lloyd/BUILD-001/approve-spec", json={}).json()
        self.assertIn("Stage 2", body["message"])

    def test_approve_notes_passed_through(self):
        self._env.make_pending_review("BUILD-001")
        body = client.post("/frank-lloyd/BUILD-001/approve-spec",
                           json={"notes": "looks good"}).json()
        self.assertTrue(body["ok"])
        # Verify decision.json captured the notes
        decision = json.loads(
            (self._env.archives / "BUILD-001" / "decision.json").read_text(encoding="utf-8")
        )
        self.assertEqual(decision["notes"], "looks good")

    def test_approve_wrong_state_returns_ok_false(self):
        """No events for build → ok=False, not a 4xx HTTP error."""
        resp = client.post("/frank-lloyd/BUILD-999/approve-spec", json={})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertIn("BUILD-999", body["error"])

    def test_approve_already_approved_returns_ok_false(self):
        self._env.make_spec_approved("BUILD-001")
        resp = client.post("/frank-lloyd/BUILD-001/approve-spec", json={})
        body = resp.json()
        self.assertFalse(body["ok"])

    def test_approve_build_id_uppercased(self):
        self._env.make_pending_review("BUILD-001")
        body = client.post("/frank-lloyd/build-001/approve-spec", json={}).json()
        self.assertEqual(body["build_id"], "BUILD-001")

    def test_approve_creates_decision_json(self):
        self._env.make_pending_review("BUILD-001")
        client.post("/frank-lloyd/BUILD-001/approve-spec", json={})
        decision_path = self._env.archives / "BUILD-001" / "decision.json"
        self.assertTrue(decision_path.exists())
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        self.assertEqual(decision["outcome"], "spec_approved")

    def test_approve_appends_log_event(self):
        self._env.make_pending_review("BUILD-001")
        client.post("/frank-lloyd/BUILD-001/approve-spec", json={})
        events = [json.loads(line) for line in
                  self._env.build_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        approved_events = [e for e in events if e.get("event") == "spec_approved"]
        self.assertEqual(len(approved_events), 1)


# ── Tests: reject-spec ────────────────────────────────────────────────────────

class TestRejectSpecEndpoint(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_reject_success_returns_ok(self):
        self._env.make_pending_review("BUILD-001")
        resp = client.post("/frank-lloyd/BUILD-001/reject-spec",
                           json={"reason": "scope is wrong"})
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["outcome"], "spec_rejected")

    def test_reject_missing_reason_returns_ok_false_not_422(self):
        """Missing reason must return ok=False JSON, not a 422 validation error."""
        self._env.make_pending_review("BUILD-001")
        resp = client.post("/frank-lloyd/BUILD-001/reject-spec", json={})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertIn("reason", body["error"].lower())

    def test_reject_empty_reason_returns_ok_false(self):
        self._env.make_pending_review("BUILD-001")
        resp = client.post("/frank-lloyd/BUILD-001/reject-spec", json={"reason": "  "})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["ok"])

    def test_reject_wrong_state_returns_ok_false(self):
        resp = client.post("/frank-lloyd/BUILD-999/reject-spec",
                           json={"reason": "bad spec"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["ok"])

    def test_reject_reason_in_response_message(self):
        self._env.make_pending_review("BUILD-001")
        body = client.post("/frank-lloyd/BUILD-001/reject-spec",
                           json={"reason": "scope is wrong"}).json()
        self.assertIn("scope is wrong", body["message"])

    def test_reject_appends_log_event(self):
        self._env.make_pending_review("BUILD-001")
        client.post("/frank-lloyd/BUILD-001/reject-spec",
                    json={"reason": "wrong scope"})
        events = [json.loads(line) for line in
                  self._env.build_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        rejected_events = [e for e in events if e.get("event") == "spec_rejected"]
        self.assertEqual(len(rejected_events), 1)

    def test_reject_creates_decision_json_with_rejection_outcome(self):
        self._env.make_pending_review("BUILD-001")
        client.post("/frank-lloyd/BUILD-001/reject-spec",
                    json={"reason": "not ready"})
        decision = json.loads(
            (self._env.archives / "BUILD-001" / "decision.json").read_text(encoding="utf-8")
        )
        self.assertEqual(decision["outcome"], "spec_rejected")


# ── Tests: authorize-stage2 ───────────────────────────────────────────────────

class TestAuthorizeStage2Endpoint(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_authorize_success_returns_ok(self):
        self._env.make_spec_approved("BUILD-001")
        resp = client.post("/frank-lloyd/BUILD-001/authorize-stage2", json={})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["outcome"], "stage2_authorized")

    def test_authorize_message_says_stage2_authorized(self):
        self._env.make_spec_approved("BUILD-001")
        body = client.post("/frank-lloyd/BUILD-001/authorize-stage2", json={}).json()
        self.assertIn("stage 2 authorized", body["message"].lower())

    def test_authorize_wrong_state_returns_ok_false(self):
        """Build in pending_review state cannot be stage2-authorized."""
        self._env.make_pending_review("BUILD-001")
        resp = client.post("/frank-lloyd/BUILD-001/authorize-stage2", json={})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["ok"])

    def test_authorize_unknown_build_returns_ok_false(self):
        resp = client.post("/frank-lloyd/BUILD-999/authorize-stage2", json={})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["ok"])

    def test_authorize_notes_captured_in_authorization_file(self):
        self._env.make_spec_approved("BUILD-001")
        client.post("/frank-lloyd/BUILD-001/authorize-stage2",
                    json={"notes": "ready for draft"})
        auth_path = self._env.archives / "BUILD-001" / "stage2_authorization.json"
        self.assertTrue(auth_path.exists())
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        self.assertEqual(auth["authorization_notes"], "ready for draft")

    def test_authorize_already_authorized_returns_ok_false(self):
        self._env.make_spec_approved("BUILD-001")
        client.post("/frank-lloyd/BUILD-001/authorize-stage2", json={})
        # Second call
        resp = client.post("/frank-lloyd/BUILD-001/authorize-stage2", json={})
        self.assertFalse(resp.json()["ok"])

    def test_authorize_appends_log_event(self):
        self._env.make_spec_approved("BUILD-001")
        client.post("/frank-lloyd/BUILD-001/authorize-stage2", json={})
        events = [json.loads(line) for line in
                  self._env.build_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        auth_events = [e for e in events if e.get("event") == "stage2_authorized"]
        self.assertEqual(len(auth_events), 1)

    def test_authorize_build_id_uppercased(self):
        self._env.make_spec_approved("BUILD-001")
        body = client.post("/frank-lloyd/build-001/authorize-stage2", json={}).json()
        self.assertEqual(body["build_id"], "BUILD-001")

    def test_authorize_does_not_claim_code_generation(self):
        self._env.make_spec_approved("BUILD-001")
        body = client.post("/frank-lloyd/BUILD-001/authorize-stage2", json={}).json()
        # Message must not claim code generation happened
        msg_lower = body["message"].lower()
        self.assertNotIn("generated", msg_lower)
        self.assertNotIn("code written", msg_lower)


if __name__ == "__main__":
    unittest.main()
