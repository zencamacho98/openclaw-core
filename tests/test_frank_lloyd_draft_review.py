# tests/test_frank_lloyd_draft_review.py
#
# Tests for Frank Lloyd draft review surface.
#
# Coverage:
#   get_draft_review() in frank_lloyd/stage2_drafter.py:
#     - unknown build → ok=False, error mentions build_id
#     - build with no draft artifacts (stage2_authorized) → ok=False, "No draft found"
#     - draft_generated build with artifacts → ok=True, manifest/code/notes returned
#     - draft_blocked (LM failure, no artifacts) → ok=False, block reason from log
#     - draft_blocked with existing manifest → ok=True, manifest returned
#     - module_code content returned correctly
#     - notes_text content returned correctly
#     - manifest fields (task_class, provider_tier, model_used, status, files_generated)
#     - build_id uppercased
#
#   GET /frank-lloyd/{build_id}/draft route:
#     - 200 status always (no 4xx)
#     - unknown build → ok=False
#     - stage2_authorized (no draft) → ok=False with status
#     - draft_generated → ok=True, manifest + code + notes
#     - build_id in response matches uppercased input
#     - draft_blocked without artifacts → ok=False, reason surfaced
#
#   _frank_lloyd_state() in neighborhood.py:
#     - returns draft_build field
#     - returns stage2_authorized_build field
#     - draft_build is None when no draft-related builds exist
#     - draft_build prioritizes draft_generated over draft_blocked

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

import frank_lloyd.stage2_drafter as _drafter
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ev(build_id: str, event: str, extra: dict | None = None) -> dict:
    return {"timestamp": _ts(), "build_id": build_id, "event": event,
            "notes": "", "extra": extra or {}}


class _Env:
    """Redirect drafter module path constants to a temp tree."""

    def __init__(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp())

    @property
    def build_log(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "build_log.jsonl"

    @property
    def archives(self) -> pathlib.Path:
        return self._tmp / "data" / "frank_lloyd" / "archives"

    @property
    def staging(self) -> pathlib.Path:
        return self._tmp / "staging" / "frank_lloyd"

    def patch(self):
        self.build_log.parent.mkdir(parents=True, exist_ok=True)
        self.archives.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        self._orig = {
            "log":  _drafter._FL_BUILD_LOG,
            "arch": _drafter._FL_ARCHIVES,
            "stg":  _drafter._FL_STAGING,
        }
        _drafter._FL_BUILD_LOG = self.build_log
        _drafter._FL_ARCHIVES  = self.archives
        _drafter._FL_STAGING   = self.staging

    def restore(self):
        _drafter._FL_BUILD_LOG = self._orig["log"]
        _drafter._FL_ARCHIVES  = self._orig["arch"]
        _drafter._FL_STAGING   = self._orig["stg"]

    def cleanup(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def write_events(self, *events: dict):
        with self.build_log.open("a", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def stage2_dir(self, build_id: str) -> pathlib.Path:
        return self.staging / build_id / "stage2"

    def write_draft_artifacts(
        self,
        build_id: str,
        module_code: str = "def run(): pass\n",
        notes: str = "Draft notes.",
    ) -> pathlib.Path:
        """Write staging artifacts for a draft_generated build."""
        stage2 = self.stage2_dir(build_id)
        stage2.mkdir(parents=True, exist_ok=True)
        manifest = {
            "build_id":        build_id,
            "stage":           2,
            "task_class":      "code_draft_low",
            "provider_tier":   "cheap",
            "provider_family": "openrouter",
            "model_used":      "openai/gpt-4o-mini",
            "generated_at":    _ts(),
            "generated_by":    "frank_lloyd",
            "files_generated": ["draft_module.py", "draft_notes.md"],
            "staging_path":    str(stage2),
            "status":          "draft_generated",
            "input_tokens":    100,
            "output_tokens":   80,
            "cost_usd":        0.00005,
        }
        (stage2 / "draft_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (stage2 / "draft_module.py").write_text(module_code, encoding="utf-8")
        (stage2 / "draft_notes.md").write_text(
            f"# Draft Notes — {build_id}\n\n{notes}\n", encoding="utf-8"
        )
        return stage2

    def make_stage2_authorized(self, build_id: str):
        self.write_events(
            _ev(build_id, "request_queued"),
            _ev(build_id, "spec_ready"),
            _ev(build_id, "spec_approved"),
            _ev(build_id, "stage2_authorized"),
        )

    def make_draft_generated(self, build_id: str, module_code: str = "def run(): pass\n",
                             notes: str = "All good."):
        self.make_stage2_authorized(build_id)
        self.write_events(
            _ev(build_id, "draft_generation_started"),
            _ev(build_id, "draft_generated", {"files_generated": ["draft_module.py"]}),
        )
        self.write_draft_artifacts(build_id, module_code=module_code, notes=notes)

    def make_draft_blocked(self, build_id: str, error: str = "API key missing"):
        self.make_stage2_authorized(build_id)
        self.write_events(
            _ev(build_id, "draft_generation_started"),
            _ev(build_id, "draft_blocked",
                {"reason": "lm_failed", "error": error}),
        )


# ── Tests: get_draft_review() unit ───────────────────────────────────────────

class TestGetDraftReviewUnknownBuild(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_unknown_build_returns_ok_false(self):
        result = _drafter.get_draft_review("BUILD-999")
        self.assertFalse(result["ok"])

    def test_unknown_build_error_mentions_build_id(self):
        result = _drafter.get_draft_review("BUILD-999")
        self.assertIn("BUILD-999", result["error"])

    def test_unknown_build_status_is_none(self):
        result = _drafter.get_draft_review("BUILD-999")
        self.assertIsNone(result["status"])

    def test_build_id_uppercased(self):
        result = _drafter.get_draft_review("build-999")
        self.assertEqual(result["build_id"], "BUILD-999")


class TestGetDraftReviewNoDraft(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_stage2_authorized_no_draft_returns_ok_false(self):
        self._env.make_stage2_authorized("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertFalse(result["ok"])

    def test_stage2_authorized_no_draft_status_in_result(self):
        self._env.make_stage2_authorized("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertEqual(result["status"], "stage2_authorized")

    def test_stage2_authorized_no_draft_error_mentions_staging(self):
        self._env.make_stage2_authorized("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertIn("No draft found", result["error"])

    def test_no_draft_manifest_none(self):
        self._env.make_stage2_authorized("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertIsNone(result["manifest"])

    def test_no_draft_module_code_none(self):
        self._env.make_stage2_authorized("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertIsNone(result["module_code"])


class TestGetDraftReviewSuccess(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_draft_generated_returns_ok_true(self):
        self._env.make_draft_generated("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertTrue(result["ok"])

    def test_draft_generated_status_in_result(self):
        self._env.make_draft_generated("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertEqual(result["status"], "draft_generated")

    def test_draft_generated_build_id_in_result(self):
        self._env.make_draft_generated("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertEqual(result["build_id"], "BUILD-001")

    def test_draft_generated_module_code_returned(self):
        self._env.make_draft_generated("BUILD-001", module_code="def hello(): return 42\n")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertIn("def hello", result["module_code"])

    def test_draft_generated_notes_text_returned(self):
        self._env.make_draft_generated("BUILD-001", notes="This is a stub module.")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertIn("This is a stub module", result["notes_text"])

    def test_draft_generated_manifest_has_task_class(self):
        self._env.make_draft_generated("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertEqual(result["manifest"]["task_class"], "code_draft_low")

    def test_draft_generated_manifest_has_provider_tier(self):
        self._env.make_draft_generated("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertEqual(result["manifest"]["provider_tier"], "cheap")

    def test_draft_generated_manifest_has_model(self):
        self._env.make_draft_generated("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertIn("model_used", result["manifest"])

    def test_draft_generated_manifest_status(self):
        self._env.make_draft_generated("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertEqual(result["manifest"]["status"], "draft_generated")

    def test_draft_generated_manifest_files_generated(self):
        self._env.make_draft_generated("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertIn("draft_module.py", result["manifest"]["files_generated"])

    def test_draft_generated_error_is_none(self):
        self._env.make_draft_generated("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertIsNone(result["error"])


class TestGetDraftReviewBlocked(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_draft_blocked_no_artifacts_returns_ok_false(self):
        self._env.make_draft_blocked("BUILD-001", error="API key missing")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertFalse(result["ok"])

    def test_draft_blocked_status_in_result(self):
        self._env.make_draft_blocked("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertEqual(result["status"], "draft_blocked")

    def test_draft_blocked_error_from_log_event(self):
        self._env.make_draft_blocked("BUILD-001", error="API key missing")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertIn("API key missing", result["error"])

    def test_draft_blocked_no_manifest_none(self):
        self._env.make_draft_blocked("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertIsNone(result["manifest"])

    def test_draft_blocked_with_manifest_returns_ok_true(self):
        """If a manifest exists (rare write-failure case), return it."""
        self._env.make_draft_blocked("BUILD-001")
        # Simulate a partial write — manifest exists but blocked event still in log
        self._env.write_draft_artifacts("BUILD-001")
        result = _drafter.get_draft_review("BUILD-001")
        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["manifest"])


# ── Tests: GET /frank-lloyd/{build_id}/draft route ────────────────────────────

class TestDraftReviewRoute(unittest.TestCase):
    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def test_unknown_build_returns_200(self):
        resp = client.get("/frank-lloyd/BUILD-999/draft")
        self.assertEqual(resp.status_code, 200)

    def test_unknown_build_ok_false(self):
        resp = client.get("/frank-lloyd/BUILD-999/draft")
        self.assertFalse(resp.json()["ok"])

    def test_stage2_authorized_no_draft_ok_false(self):
        self._env.make_stage2_authorized("BUILD-001")
        resp = client.get("/frank-lloyd/BUILD-001/draft")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["ok"])

    def test_stage2_authorized_status_returned(self):
        self._env.make_stage2_authorized("BUILD-001")
        resp = client.get("/frank-lloyd/BUILD-001/draft")
        self.assertEqual(resp.json()["status"], "stage2_authorized")

    def test_draft_generated_returns_ok_true(self):
        self._env.make_draft_generated("BUILD-001")
        resp = client.get("/frank-lloyd/BUILD-001/draft")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

    def test_draft_generated_module_code_in_response(self):
        self._env.make_draft_generated("BUILD-001", module_code="def answer(): return 42\n")
        body = client.get("/frank-lloyd/BUILD-001/draft").json()
        self.assertIn("def answer", body["module_code"])

    def test_draft_generated_notes_in_response(self):
        self._env.make_draft_generated("BUILD-001", notes="Minimal stub generated.")
        body = client.get("/frank-lloyd/BUILD-001/draft").json()
        self.assertIn("Minimal stub", body["notes_text"])

    def test_draft_generated_manifest_in_response(self):
        self._env.make_draft_generated("BUILD-001")
        body = client.get("/frank-lloyd/BUILD-001/draft").json()
        self.assertIsNotNone(body["manifest"])
        self.assertEqual(body["manifest"]["task_class"], "code_draft_low")

    def test_build_id_uppercased_in_response(self):
        self._env.make_draft_generated("BUILD-001")
        body = client.get("/frank-lloyd/build-001/draft").json()
        self.assertEqual(body["build_id"], "BUILD-001")

    def test_draft_blocked_returns_200_ok_false(self):
        self._env.make_draft_blocked("BUILD-001", error="Rate limit exceeded")
        resp = client.get("/frank-lloyd/BUILD-001/draft")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])

    def test_draft_blocked_error_surfaced_in_response(self):
        self._env.make_draft_blocked("BUILD-001", error="Rate limit exceeded")
        body = client.get("/frank-lloyd/BUILD-001/draft").json()
        self.assertIn("Rate limit exceeded", body["error"])

    def test_response_has_required_fields(self):
        self._env.make_draft_generated("BUILD-001")
        body = client.get("/frank-lloyd/BUILD-001/draft").json()
        for field in ("ok", "build_id", "status", "manifest", "module_code",
                      "notes_text", "error"):
            self.assertIn(field, body, f"Missing field: {field}")


# ── Tests: _frank_lloyd_state() extension ─────────────────────────────────────

class TestFrankLloydStateExtension(unittest.TestCase):
    """
    Tests that _frank_lloyd_state() correctly surfaces the new fields.
    Uses the status route approach by patching the route's data source.
    """

    def setUp(self):
        import app.routes.frank_lloyd_status as fl_status
        self._fl_status = fl_status
        self._orig_log      = fl_status._BUILD_LOG
        self._orig_requests = fl_status._REQUESTS_DIR
        self._tmp = pathlib.Path(tempfile.mkdtemp())
        self._log_path = self._tmp / "build_log.jsonl"
        self._req_dir  = self._tmp / "requests"
        fl_status._BUILD_LOG    = self._log_path
        fl_status._REQUESTS_DIR = self._req_dir

    def tearDown(self):
        self._fl_status._BUILD_LOG    = self._orig_log
        self._fl_status._REQUESTS_DIR = self._orig_requests
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_log(self, events: list[dict]) -> None:
        with self._log_path.open("w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def _frank_lloyd_state(self) -> dict:
        from app.routes.neighborhood import _frank_lloyd_state
        return _frank_lloyd_state()

    def test_draft_build_field_present(self):
        state = self._frank_lloyd_state()
        self.assertIn("draft_build", state)

    def test_stage2_authorized_build_field_present(self):
        state = self._frank_lloyd_state()
        self.assertIn("stage2_authorized_build", state)

    def test_draft_build_none_when_no_builds(self):
        state = self._frank_lloyd_state()
        self.assertIsNone(state["draft_build"])

    def test_draft_build_none_when_only_pending(self):
        self._write_log([
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "request_queued", "notes": "", "extra": {"title": "T"}},
        ])
        state = self._frank_lloyd_state()
        self.assertIsNone(state["draft_build"])

    def test_draft_build_populated_for_draft_generated(self):
        self._write_log([
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "request_queued", "notes": "", "extra": {"title": "T"}},
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "spec_approved", "notes": "", "extra": {"stage_completed": 1}},
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "stage2_authorized", "notes": "", "extra": {}},
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "draft_generated", "notes": "", "extra": {}},
        ])
        state = self._frank_lloyd_state()
        self.assertIsNotNone(state["draft_build"])
        self.assertEqual(state["draft_build"]["status"], "draft_generated")

    def test_stage2_authorized_build_populated(self):
        self._write_log([
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "request_queued", "notes": "", "extra": {"title": "T"}},
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "spec_approved", "notes": "", "extra": {"stage_completed": 1}},
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "stage2_authorized", "notes": "", "extra": {}},
        ])
        state = self._frank_lloyd_state()
        self.assertIsNotNone(state["stage2_authorized_build"])
        self.assertEqual(state["stage2_authorized_build"]["build_id"], "BUILD-001")

    def test_draft_build_populated_for_draft_blocked(self):
        self._write_log([
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "request_queued", "notes": "", "extra": {"title": "T"}},
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "spec_approved", "notes": "", "extra": {"stage_completed": 1}},
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "stage2_authorized", "notes": "", "extra": {}},
            {"timestamp": _ts(), "build_id": "BUILD-001",
             "event": "draft_blocked", "notes": "", "extra": {}},
        ])
        state = self._frank_lloyd_state()
        self.assertIsNotNone(state["draft_build"])
        self.assertEqual(state["draft_build"]["status"], "draft_blocked")

    def test_draft_generated_preferred_over_draft_blocked(self):
        """draft_generated build takes priority over draft_blocked in draft_build."""
        self._write_log([
            {"timestamp": "2026-04-11T09:00:00+00:00", "build_id": "BUILD-001",
             "event": "request_queued", "notes": "", "extra": {"title": "First"}},
            {"timestamp": "2026-04-11T09:30:00+00:00", "build_id": "BUILD-001",
             "event": "spec_approved", "notes": "", "extra": {"stage_completed": 1}},
            {"timestamp": "2026-04-11T10:00:00+00:00", "build_id": "BUILD-001",
             "event": "stage2_authorized", "notes": "", "extra": {}},
            {"timestamp": "2026-04-11T10:10:00+00:00", "build_id": "BUILD-001",
             "event": "draft_blocked", "notes": "", "extra": {}},
            {"timestamp": "2026-04-11T08:00:00+00:00", "build_id": "BUILD-002",
             "event": "request_queued", "notes": "", "extra": {"title": "Second"}},
            {"timestamp": "2026-04-11T08:30:00+00:00", "build_id": "BUILD-002",
             "event": "spec_approved", "notes": "", "extra": {"stage_completed": 1}},
            {"timestamp": "2026-04-11T09:00:00+00:00", "build_id": "BUILD-002",
             "event": "stage2_authorized", "notes": "", "extra": {}},
            {"timestamp": "2026-04-11T09:05:00+00:00", "build_id": "BUILD-002",
             "event": "draft_generated", "notes": "", "extra": {}},
        ])
        state = self._frank_lloyd_state()
        self.assertEqual(state["draft_build"]["status"], "draft_generated")


if __name__ == "__main__":
    unittest.main()
