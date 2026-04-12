# tests/test_frank_lloyd_stage2_promoter.py
#
# Tests for frank_lloyd/stage2_promoter.py — first-pass safe promote flow.
#
# Coverage:
#   TestUnknownBuild         — unknown / no-event build
#   TestWrongState           — wrong state rejections (all non-draft_generated states)
#   TestMissingArtifacts     — missing staging manifest or module
#   TestNonPromotableClass   — task class not in _PROMOTABLE_TASK_CLASSES
#   TestTargetPathValidation — .py only, no absolute, no traversal, off-limits
#   TestExistingFileGuard    — target_path already exists in live repo
#   TestSuccessfulPromotion  — live file written, record archived, event logged
#   TestStatusDerival        — draft_promoted status derived correctly

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import frank_lloyd.stage2_promoter as _mod


class _Env:
    """Test harness: isolated tmp directory wired in as the module's _ROOT."""

    def __init__(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root    = pathlib.Path(self._tmpdir.name)

        self.build_log = self.root / "data" / "frank_lloyd" / "build_log.jsonl"
        self.archives  = self.root / "data" / "frank_lloyd" / "archives"
        self.staging   = self.root / "staging" / "frank_lloyd"

        self._patches = [
            patch.object(_mod, "_ROOT",         self.root),
            patch.object(_mod, "_FL_BUILD_LOG",  self.build_log),
            patch.object(_mod, "_FL_ARCHIVES",   self.archives),
            patch.object(_mod, "_FL_STAGING",    self.staging),
        ]
        for p in self._patches:
            p.start()

    def teardown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log(self, build_id: str, event: str, extra: dict | None = None):
        self.build_log.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": "2026-04-11T00:00:00+00:00",
            "build_id":  build_id,
            "event":     event,
            "notes":     "",
            "extra":     extra or {},
        }
        with self.build_log.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")

    # ── State builders ────────────────────────────────────────────────────────

    def make_draft_generated(self, build_id: str = "BUILD-001") -> None:
        """Log the minimal event sequence to reach draft_generated state."""
        for ev in ("request_queued", "spec_ready", "spec_approved",
                   "stage2_authorized", "draft_generated"):
            self._log(build_id, ev)

    def write_draft_artifacts(
        self,
        build_id: str   = "BUILD-001",
        task_class: str = "code_draft_low",
    ) -> pathlib.Path:
        """Write staging draft_manifest.json + draft_module.py. Returns staging dir."""
        stage2_dir = self.staging / build_id / "stage2"
        stage2_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "build_id":      build_id,
            "stage":         2,
            "task_class":    task_class,
            "provider_tier": "cheap",
            "model_used":    "openai/gpt-4o-mini",
            "generated_at":  "2026-04-11T00:01:00+00:00",
            "generated_by":  "frank_lloyd",
            "status":        "draft_generated",
        }
        (stage2_dir / "draft_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (stage2_dir / "draft_module.py").write_text(
            "# generated module\ndef hello(): return 'hello'\n", encoding="utf-8"
        )
        return stage2_dir

    def make_full_env(
        self,
        build_id: str   = "BUILD-001",
        task_class: str = "code_draft_low",
    ) -> None:
        """Build state + staging artifacts — ready to promote."""
        self.make_draft_generated(build_id)
        self.write_draft_artifacts(build_id, task_class)


# ── TestUnknownBuild ─────────────────────────────────────────────────────────

class TestUnknownBuild(unittest.TestCase):
    def setUp(self):    self.env = _Env()
    def tearDown(self): self.env.teardown()

    def test_unknown_build_returns_ok_false(self):
        r = _mod.promote_draft("BUILD-999", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])

    def test_unknown_build_error_mentions_build_id(self):
        r = _mod.promote_draft("BUILD-999", "frank_lloyd/x.py")
        self.assertIn("BUILD-999", r["error"])

    def test_unknown_build_target_path_none(self):
        r = _mod.promote_draft("BUILD-999", "frank_lloyd/x.py")
        self.assertIsNone(r["target_path"])

    def test_build_id_uppercased(self):
        r = _mod.promote_draft("build-999", "frank_lloyd/x.py")
        self.assertEqual(r["build_id"], "BUILD-999")


# ── TestWrongState ───────────────────────────────────────────────────────────

class TestWrongState(unittest.TestCase):
    def setUp(self):    self.env = _Env()
    def tearDown(self): self.env.teardown()

    def _state(self, *events, build_id="BUILD-001"):
        for ev in events:
            self.env._log(build_id, ev)

    def test_pending_spec_rejected(self):
        self._state("request_queued")
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])
        self.assertIn("pending_spec", r["error"])

    def test_pending_review_rejected(self):
        self._state("request_queued", "spec_ready")
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])
        self.assertIn("pending_review", r["error"])

    def test_spec_approved_rejected(self):
        self._state("request_queued", "spec_ready", "spec_approved")
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])
        self.assertIn("stage 2", r["error"].lower())

    def test_stage2_authorized_rejected(self):
        self._state("request_queued", "spec_ready", "spec_approved", "stage2_authorized")
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])
        self.assertIn("stage2_authorized", r["error"])

    def test_draft_blocked_rejected(self):
        self._state("request_queued", "spec_ready", "spec_approved",
                    "stage2_authorized", "draft_blocked")
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])
        self.assertIn("blocked", r["error"].lower())

    def test_already_promoted_rejected(self):
        self._state("request_queued", "spec_ready", "spec_approved",
                    "stage2_authorized", "draft_generated", "draft_promoted")
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])
        self.assertIn("already been promoted", r["error"])

    def test_spec_rejected_build_not_promotable(self):
        self._state("request_queued", "spec_ready", "spec_rejected")
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])


# ── TestMissingArtifacts ─────────────────────────────────────────────────────

class TestMissingArtifacts(unittest.TestCase):
    def setUp(self):    self.env = _Env()
    def tearDown(self): self.env.teardown()

    def test_missing_manifest_returns_error(self):
        self.env.make_draft_generated()
        # Do NOT write staging artifacts
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])
        self.assertIn("draft_manifest.json", r["error"])

    def test_missing_module_returns_error(self):
        self.env.make_draft_generated()
        stage2_dir = self.env.staging / "BUILD-001" / "stage2"
        stage2_dir.mkdir(parents=True, exist_ok=True)
        # Write manifest but not module
        manifest = {"build_id": "BUILD-001", "task_class": "code_draft_low"}
        (stage2_dir / "draft_manifest.json").write_text(json.dumps(manifest))
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])
        self.assertIn("draft_module.py", r["error"])


# ── TestNonPromotableClass ───────────────────────────────────────────────────

class TestNonPromotableClass(unittest.TestCase):
    def setUp(self):    self.env = _Env()
    def tearDown(self): self.env.teardown()

    def test_code_draft_medium_not_promotable(self):
        self.env.make_full_env(task_class="code_draft_medium")
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])
        self.assertIn("code_draft_medium", r["error"])

    def test_code_draft_critical_not_promotable(self):
        self.env.make_full_env(task_class="code_draft_critical")
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/x.py")
        self.assertFalse(r["ok"])

    def test_code_draft_low_is_promotable(self):
        self.env.make_full_env(task_class="code_draft_low")
        # Would fail on target_path validation or missing file — but NOT on task class
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/new_module.py")
        # May fail (file won't exist to write to an isolated tmp dir properly
        # without further setup) but NOT with a task_class error
        if not r["ok"]:
            self.assertNotIn("not promotable", r["error"])


# ── TestTargetPathValidation ─────────────────────────────────────────────────

class TestTargetPathValidation(unittest.TestCase):
    def setUp(self):
        self.env = _Env()
        self.env.make_full_env()

    def tearDown(self): self.env.teardown()

    def _promote(self, path):
        return _mod.promote_draft("BUILD-001", path)

    def test_empty_target_path_rejected(self):
        r = self._promote("")
        self.assertFalse(r["ok"])
        self.assertIn("required", r["error"].lower())

    def test_non_py_extension_rejected(self):
        r = self._promote("frank_lloyd/module.js")
        self.assertFalse(r["ok"])
        self.assertIn(".py", r["error"])

    def test_txt_extension_rejected(self):
        r = self._promote("frank_lloyd/notes.txt")
        self.assertFalse(r["ok"])

    def test_absolute_path_rejected(self):
        r = self._promote("/frank_lloyd/x.py")
        self.assertFalse(r["ok"])
        self.assertIn("relative", r["error"].lower())

    def test_path_traversal_dotdot_rejected(self):
        r = self._promote("../outside.py")
        self.assertFalse(r["ok"])

    def test_data_prefix_rejected(self):
        r = self._promote("data/frank_lloyd/evil.py")
        self.assertFalse(r["ok"])
        self.assertIn("off-limits", r["error"].lower())

    def test_staging_prefix_rejected(self):
        r = self._promote("staging/frank_lloyd/evil.py")
        self.assertFalse(r["ok"])
        self.assertIn("off-limits", r["error"].lower())

    def test_logs_prefix_rejected(self):
        r = self._promote("logs/evil.py")
        self.assertFalse(r["ok"])

    def test_run_prefix_rejected(self):
        r = self._promote("run/evil.py")
        self.assertFalse(r["ok"])

    def test_venv_prefix_rejected(self):
        r = self._promote(".venv/evil.py")
        self.assertFalse(r["ok"])

    def test_tests_prefix_allowed(self):
        """tests/ is no longer off-limits — Frank Lloyd can write test files."""
        # The promote call may fail for other reasons (draft not generated, etc.)
        # but NOT because of an off-limits prefix check.
        r = self._promote("tests/test_generated.py")
        if not r["ok"]:
            # Must NOT be an off-limits error — only state/staging errors are ok
            self.assertNotIn("off-limits", (r.get("error") or "").lower())

    def test_offlimits_exact_app_main_rejected(self):
        r = self._promote("app/main.py")
        self.assertFalse(r["ok"])
        self.assertIn("off-limits", r["error"].lower())

    def test_offlimits_exact_ctl_sh_rejected(self):
        r = self._promote("scripts/ctl.sh")
        self.assertFalse(r["ok"])
        # ctl.sh is not .py, so will fail on extension first
        # but must still be rejected

    def test_offlimits_exact_neighborhood_rejected(self):
        r = self._promote("app/routes/neighborhood.py")
        self.assertFalse(r["ok"])

    def test_valid_path_in_frank_lloyd_accepted(self):
        # A new path in a non-off-limits directory should pass validation
        # (will still fail later if file already exists, but not validation)
        err = _mod._validate_target_path("frank_lloyd/my_new_module.py")
        self.assertIsNone(err)

    def test_valid_path_in_app_routes_accepted(self):
        err = _mod._validate_target_path("app/routes/new_thing.py")
        self.assertIsNone(err)


# ── TestExistingFileGuard ────────────────────────────────────────────────────

class TestExistingFileGuard(unittest.TestCase):
    def setUp(self):
        self.env = _Env()
        self.env.make_full_env()

    def tearDown(self): self.env.teardown()

    def test_existing_file_rejected(self):
        # Create the target file in the temp repo root
        target = self.env.root / "frank_lloyd" / "existing.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# already exists\n")
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/existing.py")
        self.assertFalse(r["ok"])
        self.assertIn("already exists", r["error"])

    def test_nonexistent_file_allowed(self):
        r = _mod.promote_draft("BUILD-001", "frank_lloyd/brand_new.py")
        # Should succeed — no existing file at that path in tmp
        self.assertTrue(r["ok"])


# ── TestSuccessfulPromotion ──────────────────────────────────────────────────

class TestSuccessfulPromotion(unittest.TestCase):
    def setUp(self):
        self.env = _Env()
        self.env.make_full_env()

    def tearDown(self): self.env.teardown()

    def _promote(self):
        return _mod.promote_draft("BUILD-001", "frank_lloyd/promoted.py", notes="test run")

    def test_success_returns_ok_true(self):
        self.assertTrue(self._promote()["ok"])

    def test_success_target_path_in_result(self):
        r = self._promote()
        self.assertEqual(r["target_path"], "frank_lloyd/promoted.py")

    def test_success_promoted_at_in_result(self):
        r = self._promote()
        self.assertIsNotNone(r["promoted_at"])

    def test_success_archive_path_in_result(self):
        r = self._promote()
        self.assertIsNotNone(r["archive_path"])

    def test_live_file_written(self):
        self._promote()
        live = self.env.root / "frank_lloyd" / "promoted.py"
        self.assertTrue(live.exists())

    def test_live_file_content_matches_draft(self):
        self._promote()
        live_text    = (self.env.root / "frank_lloyd" / "promoted.py").read_text()
        staging_text = (self.env.staging / "BUILD-001" / "stage2" / "draft_module.py").read_text()
        self.assertEqual(live_text, staging_text)

    def test_promotion_record_written(self):
        self._promote()
        record_path = self.env.archives / "BUILD-001" / "promotion_record.json"
        self.assertTrue(record_path.exists())

    def test_promotion_record_has_build_id(self):
        self._promote()
        record = json.loads((self.env.archives / "BUILD-001" / "promotion_record.json").read_text())
        self.assertEqual(record["build_id"], "BUILD-001")

    def test_promotion_record_has_target_path(self):
        self._promote()
        record = json.loads((self.env.archives / "BUILD-001" / "promotion_record.json").read_text())
        self.assertEqual(record["target_path"], "frank_lloyd/promoted.py")

    def test_promotion_record_has_promoted_by_operator(self):
        self._promote()
        record = json.loads((self.env.archives / "BUILD-001" / "promotion_record.json").read_text())
        self.assertEqual(record["promoted_by"], "operator")

    def test_draft_promoted_event_logged(self):
        self._promote()
        events = _mod._read_log(self.env.build_log)
        promoted_evs = [e for e in events if e.get("event") == "draft_promoted"]
        self.assertEqual(len(promoted_evs), 1)

    def test_draft_promoted_event_has_target_path(self):
        self._promote()
        events  = _mod._read_log(self.env.build_log)
        ev      = next(e for e in events if e.get("event") == "draft_promoted")
        self.assertEqual(ev["extra"]["target_path"], "frank_lloyd/promoted.py")

    def test_staging_artifacts_preserved_after_promotion(self):
        self._promote()
        self.assertTrue((self.env.staging / "BUILD-001" / "stage2" / "draft_module.py").exists())
        self.assertTrue((self.env.staging / "BUILD-001" / "stage2" / "draft_manifest.json").exists())

    def test_second_promotion_rejected(self):
        self._promote()
        # Now the log has draft_promoted — second call must fail
        r2 = _mod.promote_draft("BUILD-001", "frank_lloyd/another.py")
        self.assertFalse(r2["ok"])
        self.assertIn("already been promoted", r2["error"])

    def test_error_is_none_on_success(self):
        r = self._promote()
        self.assertIsNone(r["error"])


# ── TestStatusDerival ────────────────────────────────────────────────────────

class TestStatusDerival(unittest.TestCase):
    def setUp(self):    self.env = _Env()
    def tearDown(self): self.env.teardown()

    def _events(self, *evs, build_id="BUILD-001"):
        for ev in evs:
            self.env._log(build_id, ev)

    def test_draft_promoted_status_derived(self):
        self._events("request_queued", "spec_ready", "spec_approved",
                     "stage2_authorized", "draft_generated", "draft_promoted")
        all_events = _mod._read_log(self.env.build_log)
        status = _mod._derive_status("BUILD-001", all_events)
        self.assertEqual(status, "draft_promoted")

    def test_draft_generated_status_before_promote(self):
        self._events("request_queued", "spec_ready", "spec_approved",
                     "stage2_authorized", "draft_generated")
        all_events = _mod._read_log(self.env.build_log)
        status = _mod._derive_status("BUILD-001", all_events)
        self.assertEqual(status, "draft_generated")

    def test_draft_promoted_supersedes_draft_generated(self):
        self._events("request_queued", "spec_ready", "spec_approved",
                     "stage2_authorized", "draft_generated", "draft_promoted")
        all_events = _mod._read_log(self.env.build_log)
        status = _mod._derive_status("BUILD-001", all_events)
        self.assertNotEqual(status, "draft_generated")
        self.assertEqual(status, "draft_promoted")


if __name__ == "__main__":
    unittest.main()
