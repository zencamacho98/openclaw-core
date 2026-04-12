# tests/test_frank_lloyd_spec_approver.py
#
# Unit tests for frank_lloyd/spec_approver.py
#
# Tests cover:
#   - approve_build: validation errors, successful archive, decision/manifest contents,
#     log event appended, spec_hash format, status transition
#   - reject_build: missing reason error, validation errors, successful archive,
#     rejection decision/manifest, log event, revision_cycle field
#   - _validate_pending_review: various status states
#   - _parse_spec_fields: extraction of build_type and risk_level
#   - _write_manifest: file content and format

import hashlib
import json
import pathlib
import tempfile
import unittest


import frank_lloyd.spec_approver as approver


def _patch_paths(test_case, tmp: pathlib.Path):
    """Redirect all module-level path constants to a temp directory."""
    test_case._orig_requests  = approver._FL_REQUESTS
    test_case._orig_build_log = approver._FL_BUILD_LOG
    test_case._orig_archives  = approver._FL_ARCHIVES
    test_case._orig_staging   = approver._FL_STAGING

    approver._FL_REQUESTS  = tmp / "requests"
    approver._FL_BUILD_LOG = tmp / "build_log.jsonl"
    approver._FL_ARCHIVES  = tmp / "archives"
    approver._FL_STAGING   = tmp / "staging"

    approver._FL_REQUESTS.mkdir(parents=True)
    approver._FL_ARCHIVES.mkdir(parents=True)
    approver._FL_STAGING.mkdir(parents=True)


def _restore_paths(test_case):
    approver._FL_REQUESTS  = test_case._orig_requests
    approver._FL_BUILD_LOG = test_case._orig_build_log
    approver._FL_ARCHIVES  = test_case._orig_archives
    approver._FL_STAGING   = test_case._orig_staging


def _seed_build(
    tmp: pathlib.Path,
    build_id: str = "BUILD-001",
    events: list | None = None,
    write_request: bool = True,
    write_spec: bool = True,
    write_preflight: bool = True,
    spec_content: str = "build_type: feature\nrisk_level: low\n",
) -> None:
    """Plant a build in the right state for testing."""
    build_log = tmp / "build_log.jsonl"

    default_events = [
        {"timestamp": "2026-01-01T00:00:00+00:00", "build_id": build_id,
         "event": "request_queued", "notes": "", "extra": {}},
        {"timestamp": "2026-01-01T01:00:00+00:00", "build_id": build_id,
         "event": "spec_ready", "notes": "", "extra": {}},
    ]
    for ev in (events if events is not None else default_events):
        with build_log.open("a") as fh:
            fh.write(json.dumps(ev) + "\n")

    if write_request:
        req_dir = tmp / "requests"
        req_dir.mkdir(parents=True, exist_ok=True)
        req_file = req_dir / f"{build_id}_request.json"
        req_file.write_text(
            json.dumps({"request_id": build_id, "title": "test"}), encoding="utf-8"
        )

    if write_spec or write_preflight:
        staging_dir = tmp / "staging" / build_id
        staging_dir.mkdir(parents=True, exist_ok=True)
        if write_spec:
            (staging_dir / "spec.yaml").write_text(spec_content, encoding="utf-8")
        if write_preflight:
            (staging_dir / "preflight.md").write_text("# Preflight\nLooks fine.", encoding="utf-8")


class TestApproveBuildValidation(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        _patch_paths(self, pathlib.Path(self._tmp))

    def tearDown(self):
        _restore_paths(self)

    def test_unknown_build_id_returns_error(self):
        result = approver.approve_build("BUILD-999")
        self.assertFalse(result["ok"])
        self.assertIn("BUILD-999", result["error"])
        self.assertIsNone(result["archive_path"])

    def test_pending_spec_state_blocked(self):
        """Build in pending_spec (only request_queued event) cannot be approved."""
        _seed_build(
            pathlib.Path(self._tmp), "BUILD-001",
            events=[{"timestamp": "2026-01-01T00:00:00+00:00",
                     "build_id": "BUILD-001", "event": "request_queued",
                     "notes": "", "extra": {}}],
        )
        result = approver.approve_build("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("pending_spec", result["error"])

    def test_already_approved_blocked(self):
        _seed_build(pathlib.Path(self._tmp), "BUILD-001")
        # Manually append a terminal event
        with (pathlib.Path(self._tmp) / "build_log.jsonl").open("a") as fh:
            fh.write(json.dumps({
                "timestamp": "2026-01-01T02:00:00+00:00",
                "build_id": "BUILD-001", "event": "spec_approved",
                "notes": "", "extra": {}
            }) + "\n")
        result = approver.approve_build("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("spec_approved", result["error"])

    def test_missing_staging_spec(self):
        _seed_build(pathlib.Path(self._tmp), "BUILD-001", write_spec=False)
        result = approver.approve_build("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("spec", result["error"].lower())

    def test_missing_staging_preflight(self):
        _seed_build(pathlib.Path(self._tmp), "BUILD-001", write_preflight=False)
        result = approver.approve_build("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("preflight", result["error"].lower())

    def test_missing_request_file(self):
        _seed_build(pathlib.Path(self._tmp), "BUILD-001", write_request=False)
        result = approver.approve_build("BUILD-001")
        self.assertFalse(result["ok"])
        self.assertIn("request", result["error"].lower())


class TestApproveBuildSuccess(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        _patch_paths(self, pathlib.Path(self._tmp))
        _seed_build(pathlib.Path(self._tmp), "BUILD-001")

    def tearDown(self):
        _restore_paths(self)

    def test_returns_ok(self):
        result = approver.approve_build("BUILD-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["build_id"], "BUILD-001")
        self.assertIsNotNone(result["archive_path"])
        self.assertIsNone(result["error"])

    def test_archive_dir_created(self):
        result = approver.approve_build("BUILD-001")
        archive = pathlib.Path(result["archive_path"])
        self.assertTrue(archive.is_dir())

    def test_archive_contains_required_files(self):
        result = approver.approve_build("BUILD-001")
        archive = pathlib.Path(result["archive_path"])
        for fname in ("request.json", "spec.yaml", "preflight.md",
                      "decision.json", "manifest.json"):
            self.assertTrue((archive / fname).exists(), f"Missing {fname}")

    def test_decision_json_fields(self):
        result = approver.approve_build("BUILD-001", notes="Looks good")
        archive = pathlib.Path(result["archive_path"])
        decision = json.loads((archive / "decision.json").read_text())
        self.assertEqual(decision["build_id"], "BUILD-001")
        self.assertEqual(decision["outcome"], "spec_approved")
        self.assertEqual(decision["stage"], 1)
        self.assertEqual(decision["decided_by"], "operator")
        self.assertEqual(decision["notes"], "Looks good")
        self.assertFalse(decision["stage2_authorized"])
        self.assertIsNone(decision["revision_cycle"])
        self.assertTrue(decision["spec_hash"].startswith("sha256:"))

    def test_spec_hash_correct(self):
        spec_text = "build_type: feature\nrisk_level: low\n"
        expected = "sha256:" + hashlib.sha256(spec_text.encode()).hexdigest()
        result = approver.approve_build("BUILD-001")
        archive = pathlib.Path(result["archive_path"])
        decision = json.loads((archive / "decision.json").read_text())
        self.assertEqual(decision["spec_hash"], expected)

    def test_manifest_json_fields(self):
        result = approver.approve_build("BUILD-001")
        archive = pathlib.Path(result["archive_path"])
        manifest = json.loads((archive / "manifest.json").read_text())
        self.assertEqual(manifest["build_id"], "BUILD-001")
        self.assertEqual(manifest["stage"], 1)
        self.assertEqual(manifest["outcome"], "spec_approved")
        filenames = [c["filename"] for c in manifest["contents"]]
        self.assertIn("request.json", filenames)
        self.assertIn("spec.yaml", filenames)
        self.assertIn("preflight.md", filenames)
        self.assertIn("decision.json", filenames)
        # manifest.json MUST NOT include itself
        self.assertNotIn("manifest.json", filenames)

    def test_log_event_appended(self):
        approver.approve_build("BUILD-001")
        lines = (pathlib.Path(self._tmp) / "build_log.jsonl").read_text().splitlines()
        events = [json.loads(l) for l in lines if l.strip()]
        terminal = [e for e in events if e.get("event") == "spec_approved"]
        self.assertEqual(len(terminal), 1)
        ev = terminal[0]
        self.assertEqual(ev["build_id"], "BUILD-001")
        self.assertEqual(ev["extra"]["stage_completed"], 1)
        self.assertFalse(ev["extra"]["stage2_authorized"])

    def test_build_id_normalized_to_upper(self):
        result = approver.approve_build("build-001")
        self.assertEqual(result["build_id"], "BUILD-001")

    def test_notes_none_when_empty(self):
        result = approver.approve_build("BUILD-001")
        archive = pathlib.Path(result["archive_path"])
        decision = json.loads((archive / "decision.json").read_text())
        self.assertIsNone(decision["notes"])

    def test_spec_fields_in_log_extra(self):
        _seed_build(
            pathlib.Path(self._tmp), "BUILD-002",
            spec_content="build_type: infrastructure\nrisk_level: high\n",
        )
        approver.approve_build("BUILD-002")
        lines = (pathlib.Path(self._tmp) / "build_log.jsonl").read_text().splitlines()
        events = [json.loads(l) for l in lines if l.strip()]
        terminal = [e for e in events
                    if e.get("event") == "spec_approved"
                    and e.get("build_id") == "BUILD-002"]
        self.assertEqual(len(terminal), 1)
        extra = terminal[0]["extra"]
        self.assertEqual(extra["build_type"], "infrastructure")
        self.assertEqual(extra["risk_level"], "high")


class TestRejectBuildValidation(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        _patch_paths(self, pathlib.Path(self._tmp))

    def tearDown(self):
        _restore_paths(self)

    def test_empty_reason_blocked(self):
        result = approver.reject_build("BUILD-001", reason="")
        self.assertFalse(result["ok"])
        self.assertIn("reason", result["error"].lower())

    def test_whitespace_only_reason_blocked(self):
        result = approver.reject_build("BUILD-001", reason="   ")
        self.assertFalse(result["ok"])

    def test_unknown_build_id_returns_error(self):
        result = approver.reject_build("BUILD-999", reason="too broad")
        self.assertFalse(result["ok"])
        self.assertIn("BUILD-999", result["error"])

    def test_pending_spec_state_blocked(self):
        _seed_build(
            pathlib.Path(self._tmp), "BUILD-001",
            events=[{"timestamp": "2026-01-01T00:00:00+00:00",
                     "build_id": "BUILD-001", "event": "request_queued",
                     "notes": "", "extra": {}}],
        )
        result = approver.reject_build("BUILD-001", reason="too broad")
        self.assertFalse(result["ok"])
        self.assertIn("pending_spec", result["error"])

    def test_missing_staging_spec(self):
        _seed_build(pathlib.Path(self._tmp), "BUILD-001", write_spec=False)
        result = approver.reject_build("BUILD-001", reason="too broad")
        self.assertFalse(result["ok"])
        self.assertIn("spec", result["error"].lower())


class TestRejectBuildSuccess(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        _patch_paths(self, pathlib.Path(self._tmp))
        _seed_build(pathlib.Path(self._tmp), "BUILD-001")

    def tearDown(self):
        _restore_paths(self)

    def test_returns_ok(self):
        result = approver.reject_build("BUILD-001", reason="touches wrong files")
        self.assertTrue(result["ok"])
        self.assertEqual(result["build_id"], "BUILD-001")

    def test_decision_json_rejection_fields(self):
        result = approver.reject_build(
            "BUILD-001", reason="too broad", revision_cycle=2
        )
        archive = pathlib.Path(result["archive_path"])
        decision = json.loads((archive / "decision.json").read_text())
        self.assertEqual(decision["outcome"], "spec_rejected")
        self.assertEqual(decision["notes"], "too broad")
        self.assertEqual(decision["revision_cycle"], 2)
        self.assertIsNone(decision["stage2_authorized"])

    def test_manifest_outcome_spec_rejected(self):
        result = approver.reject_build("BUILD-001", reason="too broad")
        archive = pathlib.Path(result["archive_path"])
        manifest = json.loads((archive / "manifest.json").read_text())
        self.assertEqual(manifest["outcome"], "spec_rejected")

    def test_log_event_spec_rejected(self):
        approver.reject_build("BUILD-001", reason="scope too large")
        lines = (pathlib.Path(self._tmp) / "build_log.jsonl").read_text().splitlines()
        events = [json.loads(l) for l in lines if l.strip()]
        terminal = [e for e in events if e.get("event") == "spec_rejected"]
        self.assertEqual(len(terminal), 1)
        ev = terminal[0]
        self.assertEqual(ev["extra"]["reason"], "scope too large")
        self.assertIsNone(ev["extra"]["revision_cycle"])

    def test_revision_cycle_in_log_extra(self):
        approver.reject_build("BUILD-001", reason="bad", revision_cycle=3)
        lines = (pathlib.Path(self._tmp) / "build_log.jsonl").read_text().splitlines()
        events = [json.loads(l) for l in lines if l.strip()]
        terminal = [e for e in events if e.get("event") == "spec_rejected"]
        self.assertEqual(terminal[0]["extra"]["revision_cycle"], 3)

    def test_archive_contains_required_files(self):
        result = approver.reject_build("BUILD-001", reason="too broad")
        archive = pathlib.Path(result["archive_path"])
        for fname in ("request.json", "spec.yaml", "preflight.md",
                      "decision.json", "manifest.json"):
            self.assertTrue((archive / fname).exists(), f"Missing {fname}")


class TestParseSpecFields(unittest.TestCase):

    def test_extracts_build_type_and_risk_level(self):
        text = "build_type: feature\nrisk_level: high\n"
        fields = approver._parse_spec_fields(text)
        self.assertEqual(fields["build_type"], "feature")
        self.assertEqual(fields["risk_level"], "high")

    def test_handles_quoted_values(self):
        text = 'build_type: "infrastructure"\nrisk_level: \'critical\'\n'
        fields = approver._parse_spec_fields(text)
        self.assertEqual(fields["build_type"], "infrastructure")
        self.assertEqual(fields["risk_level"], "critical")

    def test_first_occurrence_wins(self):
        text = "build_type: feature\nbuild_type: bug_fix\n"
        fields = approver._parse_spec_fields(text)
        self.assertEqual(fields["build_type"], "feature")

    def test_missing_keys_absent(self):
        fields = approver._parse_spec_fields("title: My spec\n")
        self.assertNotIn("build_type", fields)
        self.assertNotIn("risk_level", fields)


class TestValidatePendingReview(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        _patch_paths(self, pathlib.Path(self._tmp))

    def tearDown(self):
        _restore_paths(self)

    def test_no_events_returns_error(self):
        err = approver._validate_pending_review("BUILD-999")
        self.assertIsNotNone(err)
        self.assertIn("BUILD-999", err)

    def test_pending_spec_returns_error(self):
        _seed_build(
            pathlib.Path(self._tmp), "BUILD-001",
            events=[{"timestamp": "2026-01-01T00:00:00+00:00",
                     "build_id": "BUILD-001", "event": "request_queued",
                     "notes": "", "extra": {}}],
        )
        err = approver._validate_pending_review("BUILD-001")
        self.assertIsNotNone(err)
        self.assertIn("pending_spec", err)

    def test_pending_review_returns_none(self):
        _seed_build(pathlib.Path(self._tmp), "BUILD-001")
        err = approver._validate_pending_review("BUILD-001")
        self.assertIsNone(err)

    def test_already_approved_returns_error(self):
        _seed_build(pathlib.Path(self._tmp), "BUILD-001")
        with (pathlib.Path(self._tmp) / "build_log.jsonl").open("a") as fh:
            fh.write(json.dumps({
                "timestamp": "2026-01-01T02:00:00+00:00",
                "build_id": "BUILD-001", "event": "spec_approved",
                "notes": "", "extra": {}
            }) + "\n")
        err = approver._validate_pending_review("BUILD-001")
        self.assertIsNotNone(err)
        self.assertIn("spec_approved", err)

    def test_abandoned_returns_error(self):
        _seed_build(pathlib.Path(self._tmp), "BUILD-001")
        with (pathlib.Path(self._tmp) / "build_log.jsonl").open("a") as fh:
            fh.write(json.dumps({
                "timestamp": "2026-01-01T02:00:00+00:00",
                "build_id": "BUILD-001", "event": "abandoned",
                "notes": "", "extra": {}
            }) + "\n")
        err = approver._validate_pending_review("BUILD-001")
        self.assertIsNotNone(err)
        self.assertIn("abandoned", err)


if __name__ == "__main__":
    unittest.main()
