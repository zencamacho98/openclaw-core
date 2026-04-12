# tests/test_frank_lloyd_build016.py
#
# BUILD-016: Tests for:
#   1. POST /frank-lloyd/{build_id}/generate-draft  — new endpoint
#   2. _clean_display_title() in frank_lloyd_status  — boilerplate stripping
#   3. extract_title() in frank_lloyd.request_writer — boilerplate stripping
#
# Run with:
#   python -m pytest tests/test_frank_lloyd_build016.py -v

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
import frank_lloyd.stage2_drafter as _fl_drafter
import frank_lloyd.stage2_authorizer as _fl_s2auth
import frank_lloyd.spec_approver as _fl_approver
import app.routes.frank_lloyd_status as fl_status
import frank_lloyd.request_writer as _fl_rw

client = TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Env:
    """Temp tree redirecting the approver, authorizer, and drafter module paths."""

    def __init__(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp())

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

    def patch(self):
        self.build_log.parent.mkdir(parents=True, exist_ok=True)
        self.archives.mkdir(parents=True, exist_ok=True)
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)

        self._orig_approver = {
            "log": _fl_approver._FL_BUILD_LOG,
            "arch": _fl_approver._FL_ARCHIVES,
            "req": _fl_approver._FL_REQUESTS,
            "stg": _fl_approver._FL_STAGING,
        }
        _fl_approver._FL_BUILD_LOG = self.build_log
        _fl_approver._FL_ARCHIVES  = self.archives
        _fl_approver._FL_REQUESTS  = self.requests_dir
        _fl_approver._FL_STAGING   = self.staging

        self._orig_s2auth = {
            "log": _fl_s2auth._FL_BUILD_LOG,
            "arch": _fl_s2auth._FL_ARCHIVES,
        }
        _fl_s2auth._FL_BUILD_LOG = self.build_log
        _fl_s2auth._FL_ARCHIVES  = self.archives

        self._orig_drafter = {
            "log": _fl_drafter._FL_BUILD_LOG,
            "arch": _fl_drafter._FL_ARCHIVES,
            "stg": _fl_drafter._FL_STAGING,
        }
        _fl_drafter._FL_BUILD_LOG = self.build_log
        _fl_drafter._FL_ARCHIVES  = self.archives
        _fl_drafter._FL_STAGING   = self.staging

    def restore(self):
        _fl_approver._FL_BUILD_LOG = self._orig_approver["log"]
        _fl_approver._FL_ARCHIVES  = self._orig_approver["arch"]
        _fl_approver._FL_REQUESTS  = self._orig_approver["req"]
        _fl_approver._FL_STAGING   = self._orig_approver["stg"]
        _fl_s2auth._FL_BUILD_LOG   = self._orig_s2auth["log"]
        _fl_s2auth._FL_ARCHIVES    = self._orig_s2auth["arch"]
        _fl_drafter._FL_BUILD_LOG  = self._orig_drafter["log"]
        _fl_drafter._FL_ARCHIVES   = self._orig_drafter["arch"]
        _fl_drafter._FL_STAGING    = self._orig_drafter["stg"]

    def cleanup(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _ev(self, build_id: str, event: str, extra: dict | None = None) -> dict:
        return {
            "timestamp": _ts(),
            "build_id": build_id,
            "event": event,
            "notes": "",
            "extra": extra or {},
        }

    def write_log(self, events: list[dict]):
        with self.build_log.open("a", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def make_pending_review(self, build_id: str):
        self.write_log([
            self._ev(build_id, "request_queued", {"title": f"Test {build_id}"}),
            self._ev(build_id, "spec_ready"),
        ])
        req = self.requests_dir / f"{build_id}_request.json"
        req.write_text(json.dumps({"request_id": build_id, "title": f"Test {build_id}"}),
                       encoding="utf-8")
        stg = self.staging / build_id
        stg.mkdir(parents=True, exist_ok=True)
        (stg / "spec.yaml").write_text(
            "build_id: " + build_id + "\nbuild_type: test\nrisk_level: low\n",
            encoding="utf-8",
        )
        (stg / "preflight.md").write_text("# Preflight\nAll checks pass.", encoding="utf-8")

    def make_spec_approved(self, build_id: str):
        self.make_pending_review(build_id)
        arch = self.archives / build_id
        arch.mkdir(parents=True, exist_ok=True)
        decision = {
            "build_id": build_id, "outcome": "spec_approved", "stage": 1,
            "decided_at": _ts(), "decided_by": "operator",
            "notes": None, "stage2_authorized": False,
        }
        (arch / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
        # Copy spec to archive
        spec_src = self.staging / build_id / "spec.yaml"
        (arch / "spec.yaml").write_text(spec_src.read_text(), encoding="utf-8")
        self.write_log([self._ev(build_id, "spec_approved", {"stage_completed": 1})])

    def make_stage2_authorized(self, build_id: str):
        self.make_spec_approved(build_id)
        arch = self.archives / build_id
        auth = {
            "build_id": build_id, "authorized_at": _ts(),
            "authorized_by": "operator", "authorization_notes": "",
        }
        (arch / "stage2_authorization.json").write_text(json.dumps(auth), encoding="utf-8")
        self.write_log([self._ev(build_id, "stage2_authorized")])


# ── Tests: generate-draft endpoint ───────────────────────────────────────────

class TestGenerateDraftEndpoint(unittest.TestCase):

    def setUp(self):
        self._env = _Env()
        self._env.patch()

    def tearDown(self):
        self._env.restore()
        self._env.cleanup()

    def _mock_success(self, build_id: str = "BUILD-001") -> dict:
        return {
            "ok": True,
            "build_id": build_id,
            "status": "draft_generated",
            "staging_path": f"staging/frank_lloyd/{build_id}/stage2",
            "manifest_path": f"staging/frank_lloyd/{build_id}/stage2/draft_manifest.json",
            "files_generated": ["draft_module.py", "draft_notes.md", "draft_manifest.json"],
            "routing": {"task_class": "CODE_DRAFT_LOW"},
            "error": None,
        }

    def test_generate_draft_success_returns_ok(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch("frank_lloyd.stage2_drafter.generate_stage2_draft",
                   return_value=self._mock_success()) as mock_fn:
            resp = client.post("/frank-lloyd/BUILD-001/generate-draft", json={})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["build_id"], "BUILD-001")
        self.assertEqual(body["outcome"], "draft_generated")

    def test_generate_draft_success_message_mentions_review(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch("frank_lloyd.stage2_drafter.generate_stage2_draft",
                   return_value=self._mock_success()):
            body = client.post("/frank-lloyd/BUILD-001/generate-draft", json={}).json()
        self.assertIn("draft generated", body["message"].lower())

    def test_generate_draft_build_id_uppercased(self):
        self._env.make_stage2_authorized("BUILD-001")
        with patch("frank_lloyd.stage2_drafter.generate_stage2_draft",
                   return_value=self._mock_success()):
            body = client.post("/frank-lloyd/build-001/generate-draft", json={}).json()
        self.assertEqual(body["build_id"], "BUILD-001")

    def test_generate_draft_notes_passed_through(self):
        self._env.make_stage2_authorized("BUILD-001")
        captured = {}
        def _capture(build_id, notes="", **kw):
            captured["notes"] = notes
            return self._mock_success()
        with patch("frank_lloyd.stage2_drafter.generate_stage2_draft", side_effect=_capture):
            client.post("/frank-lloyd/BUILD-001/generate-draft", json={"notes": "use gpt"})
        self.assertEqual(captured["notes"], "use gpt")

    def test_generate_draft_lm_failure_returns_ok_false(self):
        self._env.make_stage2_authorized("BUILD-001")
        fail = {"ok": False, "error": "LM call failed: timeout", "build_id": "BUILD-001"}
        with patch("frank_lloyd.stage2_drafter.generate_stage2_draft", return_value=fail):
            body = client.post("/frank-lloyd/BUILD-001/generate-draft", json={}).json()
        self.assertFalse(body["ok"])
        self.assertIn("LM", body["error"])

    def test_generate_draft_wrong_state_returns_ok_false_not_422(self):
        """Wrong state (e.g. pending_review) — must return ok=False, not a 4xx."""
        self._env.make_pending_review("BUILD-001")
        with patch("frank_lloyd.stage2_drafter.generate_stage2_draft",
                   return_value={"ok": False, "error": "Not stage2_authorized",
                                 "build_id": "BUILD-001"}):
            resp = client.post("/frank-lloyd/BUILD-001/generate-draft", json={})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["ok"])

    def test_generate_draft_unexpected_status_returns_ok_false(self):
        """If drafter returns ok=True but status is not draft_generated, surface it."""
        partial = {
            "ok": True,
            "build_id": "BUILD-001",
            "status": "draft_blocked",
            "error": "task class not executable",
        }
        self._env.make_stage2_authorized("BUILD-001")
        with patch("frank_lloyd.stage2_drafter.generate_stage2_draft", return_value=partial):
            body = client.post("/frank-lloyd/BUILD-001/generate-draft", json={}).json()
        self.assertFalse(body["ok"])
        self.assertIn("draft_blocked", body.get("outcome", "") + body.get("message", ""))


# ── Tests: _clean_display_title (frank_lloyd_status) ─────────────────────────

class TestCleanDisplayTitle(unittest.TestCase):
    """Unit tests for the boilerplate-stripping title function in frank_lloyd_status."""

    def _clean(self, description: str) -> str:
        return fl_status._clean_display_title(description)

    def test_strips_peter_have_frank_lloyd(self):
        result = self._clean("Peter, have Frank Lloyd fix Belfort's stopping-state UI control buttons")
        self.assertNotIn("Peter", result)
        self.assertNotIn("Frank Lloyd", result)
        self.assertIn("fix", result.lower())

    def test_strips_tell_frank_lloyd_to(self):
        result = self._clean("Tell Frank Lloyd to build the event log query endpoint")
        self.assertNotIn("Tell", result)
        self.assertNotIn("Frank Lloyd", result)
        self.assertIn("build", result.lower())

    def test_strips_ask_frank_lloyd(self):
        result = self._clean("Ask Frank Lloyd to add a health check endpoint")
        self.assertNotIn("Ask", result)
        self.assertNotIn("Frank Lloyd", result)

    def test_no_boilerplate_unchanged(self):
        result = self._clean("Add health check endpoint with success criterion")
        self.assertIn("health", result.lower())

    def test_max_six_meaningful_words(self):
        result = self._clean("a b c d e f g h i j k l m n")
        self.assertLessEqual(len(result.split()), 6)

    def test_skips_stopwords(self):
        result = self._clean("build a new the endpoint for routing")
        # "a", "new", "the", "for" are stopwords; only meaningful words count
        words = result.split()
        for w in words:
            self.assertNotIn(w.lower(), {"a", "an", "the", "new", "for"})

    def test_returns_build_id_length_fallback_for_empty(self):
        """When description is empty-ish, returns something (no crash)."""
        result = self._clean("   ")
        self.assertIsInstance(result, str)


# ── Tests: extract_title in request_writer ────────────────────────────────────

class TestExtractTitleRequestWriter(unittest.TestCase):
    """Unit tests for extract_title() boilerplate stripping in request_writer."""

    def test_strips_peter_have_frank_lloyd(self):
        desc = "Peter, have Frank Lloyd fix Belfort's stopping-state UI"
        title = _fl_rw.extract_title(desc)
        self.assertNotIn("Peter", title)
        self.assertNotIn("Frank Lloyd", title)
        self.assertIn("fix", title.lower())

    def test_strips_please_have_frank_lloyd_to(self):
        desc = "Please have Frank Lloyd to add a trading endpoint"
        title = _fl_rw.extract_title(desc)
        self.assertNotIn("Please", title)
        self.assertNotIn("Frank Lloyd", title)

    def test_strips_peter_tell_frank_lloyd(self):
        desc = "Peter, tell Frank Lloyd to build the spec writer"
        title = _fl_rw.extract_title(desc)
        self.assertNotIn("Peter", title)
        self.assertNotIn("Frank Lloyd", title)
        self.assertIn("build", title.lower())

    def test_no_boilerplate_returns_meaningful_words(self):
        desc = "Build a new trading endpoint that returns the portfolio snapshot"
        title = _fl_rw.extract_title(desc)
        self.assertIn("trading", title.lower())

    def test_title_at_most_six_words(self):
        desc = "Peter, have Frank Lloyd create an entirely new event log query endpoint for Belfort"
        title = _fl_rw.extract_title(desc)
        self.assertLessEqual(len(title.split()), 6)

    def test_empty_description_returns_something(self):
        title = _fl_rw.extract_title("")
        self.assertIsInstance(title, str)

    def test_trailing_punctuation_stripped(self):
        desc = "Add health endpoint here."
        title = _fl_rw.extract_title(desc)
        self.assertFalse(title.endswith("."))

    def test_real_build001_description(self):
        """The actual BUILD-001 description should produce a clean title."""
        desc = (
            "Peter, have Frank Lloyd fix Belfort\u2019s stopping-state UI so the control "
            "buttons reflect stopping correctly. Success: when Belfort is stopping, the "
            "control buttons visibly reflect stopping and do not look like normal "
            "active-trading controls."
        )
        title = _fl_rw.extract_title(desc)
        # Must not start with Peter or Frank Lloyd
        self.assertFalse(title.lower().startswith("peter"))
        self.assertFalse(title.lower().startswith("frank"))
        # Should contain "fix" or "belfort"
        self.assertTrue(
            "fix" in title.lower() or "belfort" in title.lower(),
            f"Unexpected title: {title!r}",
        )


if __name__ == "__main__":
    unittest.main()
