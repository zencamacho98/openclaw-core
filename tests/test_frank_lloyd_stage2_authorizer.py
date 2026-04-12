# tests/test_frank_lloyd_stage2_authorizer.py
#
# Unit tests for frank_lloyd/stage2_authorizer.py
#
# Coverage:
#   - authorize_stage2(): validation failures (all 7 failure paths), success
#   - stage2_authorization.json: correct fields written
#   - build_log.jsonl: stage2_authorized event appended
#   - _derive_status(): stage2_authorized event maps correctly
#   - _provider_readiness(): returns correct structure

import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone

import frank_lloyd.stage2_authorizer as _mod


def _make_log_event(build_id: str, event: str) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "build_id":  build_id,
        "event":     event,
        "notes":     "",
        "extra":     {},
    }


class _PatchedPaths:
    """Redirect module-level path constants to a temp directory."""

    def __init__(self, tmp: pathlib.Path):
        self.tmp        = tmp
        self.build_log  = tmp / "data" / "frank_lloyd" / "build_log.jsonl"
        self.archives   = tmp / "data" / "frank_lloyd" / "archives"
        self._orig_log  = _mod._FL_BUILD_LOG
        self._orig_arch = _mod._FL_ARCHIVES

    def patch(self):
        self.build_log.parent.mkdir(parents=True, exist_ok=True)
        self.archives.mkdir(parents=True, exist_ok=True)
        _mod._FL_BUILD_LOG = self.build_log
        _mod._FL_ARCHIVES  = self.archives

    def restore(self):
        _mod._FL_BUILD_LOG = self._orig_log
        _mod._FL_ARCHIVES  = self._orig_arch

    def write_log_events(self, *events: dict):
        with self.build_log.open("a", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def write_decision(self, build_id: str, outcome: str = "spec_approved"):
        arch = self.archives / build_id
        arch.mkdir(parents=True, exist_ok=True)
        decision = {
            "build_id":          build_id,
            "outcome":           outcome,
            "stage":             1,
            "decided_at":        datetime.now(timezone.utc).isoformat(),
            "decided_by":        "operator",
            "notes":             None,
            "deferred_items":    None,
            "stage2_authorized": False,
            "spec_hash":         None,
            "revision_cycle":    None,
        }
        (arch / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
        return arch


# ── Validation failures ───────────────────────────────────────────────────────

class TestAuthorizeStage2ValidationNoEvents(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._pp  = _PatchedPaths(pathlib.Path(self._tmp))
        self._pp.patch()

    def tearDown(self):
        self._pp.restore()
        import shutil; shutil.rmtree(self._tmp, ignore_errors=True)

    def test_unknown_build_id_returns_error(self):
        result = _mod.authorize_stage2("BUILD-999")
        self.assertFalse(result["ok"])
        self.assertIn("BUILD-999", result["error"])
        self.assertIsNone(result["authorization_path"])


class TestAuthorizeStage2ValidationWrongState(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._pp  = _PatchedPaths(pathlib.Path(self._tmp))
        self._pp.patch()

    def tearDown(self):
        self._pp.restore()
        import shutil; shutil.rmtree(self._tmp, ignore_errors=True)

    def test_pending_spec_blocked(self):
        self._pp.write_log_events(
            _make_log_event("BUILD-001", "request_queued"),
        )
        result = _mod.authorize_stage2("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("pending_spec", result["error"])

    def test_pending_review_blocked(self):
        self._pp.write_log_events(
            _make_log_event("BUILD-001", "request_queued"),
            _make_log_event("BUILD-001", "spec_ready"),
        )
        result = _mod.authorize_stage2("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("pending_review", result["error"])

    def test_spec_rejected_blocked(self):
        self._pp.write_log_events(
            _make_log_event("BUILD-001", "request_queued"),
            _make_log_event("BUILD-001", "spec_ready"),
            _make_log_event("BUILD-001", "spec_rejected"),
        )
        result = _mod.authorize_stage2("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("rejected", result["error"])

    def test_abandoned_blocked(self):
        self._pp.write_log_events(
            _make_log_event("BUILD-001", "request_queued"),
            _make_log_event("BUILD-001", "abandoned"),
        )
        result = _mod.authorize_stage2("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("abandoned", result["error"])

    def test_already_authorized_blocked_via_status(self):
        """stage2_authorized status (from log event) is caught before file check."""
        self._pp.write_log_events(
            _make_log_event("BUILD-001", "request_queued"),
            _make_log_event("BUILD-001", "spec_ready"),
            _make_log_event("BUILD-001", "spec_approved"),
            _make_log_event("BUILD-001", "stage2_authorized"),
        )
        result = _mod.authorize_stage2("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("already authorized", result["error"])


class TestAuthorizeStage2ValidationArtifacts(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._pp  = _PatchedPaths(pathlib.Path(self._tmp))
        self._pp.patch()

    def tearDown(self):
        self._pp.restore()
        import shutil; shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_approved_log(self):
        self._pp.write_log_events(
            _make_log_event("BUILD-001", "request_queued"),
            _make_log_event("BUILD-001", "spec_ready"),
            _make_log_event("BUILD-001", "spec_approved"),
        )

    def test_missing_decision_json_blocked(self):
        self._write_approved_log()
        # Archive dir exists but no decision.json
        (self._pp.archives / "BUILD-001").mkdir(parents=True, exist_ok=True)
        result = _mod.authorize_stage2("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("decision.json", result["error"])

    def test_wrong_decision_outcome_blocked(self):
        self._write_approved_log()
        self._pp.write_decision("BUILD-001", outcome="spec_rejected")
        result = _mod.authorize_stage2("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("spec_rejected", result["error"])

    def test_already_authorized_file_blocked(self):
        """stage2_authorization.json already present → error (belt-and-suspenders)."""
        self._write_approved_log()
        arch = self._pp.write_decision("BUILD-001")
        (arch / "stage2_authorization.json").write_text("{}", encoding="utf-8")
        # Also write the log event so status check passes
        self._pp.write_log_events()  # no-op; status is spec_approved from above
        result = _mod.authorize_stage2("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("already authorized", result["error"])


# ── Success path ──────────────────────────────────────────────────────────────

class TestAuthorizeStage2Success(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._pp  = _PatchedPaths(pathlib.Path(self._tmp))
        self._pp.patch()
        # Write a minimal spec_approved build
        self._pp.write_log_events(
            _make_log_event("BUILD-002", "request_queued"),
            _make_log_event("BUILD-002", "spec_ready"),
            _make_log_event("BUILD-002", "spec_approved"),
        )
        self._pp.write_decision("BUILD-002")
        self._result = _mod.authorize_stage2("BUILD-002", notes="ready to draft")

    def tearDown(self):
        self._pp.restore()
        import shutil; shutil.rmtree(self._tmp, ignore_errors=True)

    def test_returns_ok(self):
        self.assertTrue(self._result["ok"])
        self.assertIsNone(self._result["error"])

    def test_returns_correct_build_id(self):
        self.assertEqual(self._result["build_id"], "BUILD-002")

    def test_returns_authorization_path(self):
        auth_path = pathlib.Path(self._result["authorization_path"])
        self.assertTrue(auth_path.exists())
        self.assertEqual(auth_path.name, "stage2_authorization.json")

    def test_authorization_file_has_required_fields(self):
        auth_path = pathlib.Path(self._result["authorization_path"])
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        for key in ("build_id", "stage", "authorized_at", "authorized_by",
                    "authorization_notes", "stage1_decision_outcome", "provider_readiness"):
            self.assertIn(key, auth, f"Missing field: {key}")

    def test_authorization_file_stage_is_2(self):
        auth = json.loads(
            pathlib.Path(self._result["authorization_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(auth["stage"], 2)

    def test_authorization_file_authorized_by_operator(self):
        auth = json.loads(
            pathlib.Path(self._result["authorization_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(auth["authorized_by"], "operator")

    def test_authorization_file_outcome_is_spec_approved(self):
        auth = json.loads(
            pathlib.Path(self._result["authorization_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(auth["stage1_decision_outcome"], "spec_approved")

    def test_authorization_file_notes_captured(self):
        auth = json.loads(
            pathlib.Path(self._result["authorization_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(auth["authorization_notes"], "ready to draft")

    def test_authorization_file_has_provider_readiness(self):
        auth = json.loads(
            pathlib.Path(self._result["authorization_path"]).read_text(encoding="utf-8")
        )
        pr = auth["provider_readiness"]
        self.assertIn("executable_lanes", pr)
        self.assertIn("config_only_lanes", pr)
        self.assertIn("external_supervised_lanes", pr)

    def test_build_log_has_stage2_authorized_event(self):
        events = []
        for line in self._pp.build_log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        s2_events = [e for e in events
                     if e.get("event") == "stage2_authorized"
                     and e.get("build_id") == "BUILD-002"]
        self.assertEqual(len(s2_events), 1)

    def test_log_event_has_authorization_notes(self):
        events = []
        for line in self._pp.build_log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        ev = next(e for e in events if e.get("event") == "stage2_authorized")
        self.assertEqual(ev["extra"]["authorization_notes"], "ready to draft")

    def test_empty_notes_stored_as_none(self):
        # Authorize a second distinct build with no notes
        self._pp.write_log_events(
            _make_log_event("BUILD-003", "request_queued"),
            _make_log_event("BUILD-003", "spec_ready"),
            _make_log_event("BUILD-003", "spec_approved"),
        )
        self._pp.write_decision("BUILD-003")
        result = _mod.authorize_stage2("BUILD-003")
        self.assertTrue(result["ok"])
        auth = json.loads(
            pathlib.Path(result["authorization_path"]).read_text(encoding="utf-8")
        )
        self.assertIsNone(auth["authorization_notes"])

    def test_idempotency_second_call_fails(self):
        """Second authorize call on the same build must fail."""
        result2 = _mod.authorize_stage2("BUILD-002")
        self.assertFalse(result2["ok"])
        self.assertIn("already authorized", result2["error"])


# ── _derive_status() ──────────────────────────────────────────────────────────

class TestDeriveStatus(unittest.TestCase):
    def _events(self, *event_types):
        return [_make_log_event("BUILD-X", et) for et in event_types]

    def test_request_queued_gives_pending_spec(self):
        status = _mod._derive_status("BUILD-X", self._events("request_queued"))
        self.assertEqual(status, "pending_spec")

    def test_spec_ready_gives_pending_review(self):
        status = _mod._derive_status("BUILD-X",
                                     self._events("request_queued", "spec_ready"))
        self.assertEqual(status, "pending_review")

    def test_spec_approved_gives_spec_approved(self):
        status = _mod._derive_status("BUILD-X",
                                     self._events("request_queued", "spec_ready", "spec_approved"))
        self.assertEqual(status, "spec_approved")

    def test_stage2_authorized_gives_stage2_authorized(self):
        status = _mod._derive_status(
            "BUILD-X",
            self._events("request_queued", "spec_ready", "spec_approved", "stage2_authorized"),
        )
        self.assertEqual(status, "stage2_authorized")

    def test_no_events_gives_none(self):
        status = _mod._derive_status("BUILD-X", [])
        self.assertIsNone(status)

    def test_only_other_build_events_gives_none(self):
        events = [_make_log_event("BUILD-Y", "spec_approved")]
        status = _mod._derive_status("BUILD-X", events)
        self.assertIsNone(status)


# ── _provider_readiness() ─────────────────────────────────────────────────────

class TestProviderReadiness(unittest.TestCase):
    def test_returns_dict_with_three_lane_keys(self):
        pr = _mod._provider_readiness()
        self.assertIn("executable_lanes", pr)
        self.assertIn("config_only_lanes", pr)
        self.assertIn("external_supervised_lanes", pr)

    def test_all_values_are_lists(self):
        pr = _mod._provider_readiness()
        for key in ("executable_lanes", "config_only_lanes", "external_supervised_lanes"):
            self.assertIsInstance(pr[key], list)

    def test_cheap_is_executable(self):
        pr = _mod._provider_readiness()
        self.assertIn("cheap", pr["executable_lanes"])

    def test_codex_supervised_is_external_supervised(self):
        pr = _mod._provider_readiness()
        self.assertIn("codex_supervised", pr["external_supervised_lanes"])

    def test_coding_is_config_only(self):
        pr = _mod._provider_readiness()
        self.assertIn("coding", pr["config_only_lanes"])

    def test_no_warning_key_when_import_succeeds(self):
        pr = _mod._provider_readiness()
        self.assertNotIn("warning", pr)


if __name__ == "__main__":
    unittest.main()
