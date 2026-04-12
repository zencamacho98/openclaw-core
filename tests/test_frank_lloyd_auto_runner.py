# tests/test_frank_lloyd_auto_runner.py
#
# Unit tests for frank_lloyd/auto_runner.py
#
# Tests the safe-lane pipeline orchestration logic.
# All external module calls are mocked — no LM calls, no file I/O in most cases.

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch

# Make sure project root is on path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import frank_lloyd.auto_runner as auto_runner


class TestReadRiskLevel(unittest.TestCase):
    """_read_risk_level reads risk_level from spec.yaml in staging."""

    def test_low_risk(self, tmp_path=None):
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            # Patch _STAGING to temp dir
            bid = "BUILD-001"
            spec_dir = td_path / bid
            spec_dir.mkdir()
            (spec_dir / "spec.yaml").write_text("risk_level: low\n")
            with patch.object(auto_runner, "_STAGING", td_path):
                self.assertEqual(auto_runner._read_risk_level(bid), "low")

    def test_high_risk(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            bid = "BUILD-002"
            spec_dir = td_path / bid
            spec_dir.mkdir()
            (spec_dir / "spec.yaml").write_text("risk_level: high\n")
            with patch.object(auto_runner, "_STAGING", td_path):
                self.assertEqual(auto_runner._read_risk_level(bid), "high")

    def test_quoted_value(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            bid = "BUILD-003"
            spec_dir = td_path / bid
            spec_dir.mkdir()
            (spec_dir / "spec.yaml").write_text('risk_level: "medium"\n')
            with patch.object(auto_runner, "_STAGING", td_path):
                self.assertEqual(auto_runner._read_risk_level(bid), "medium")

    def test_missing_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            with patch.object(auto_runner, "_STAGING", td_path):
                self.assertEqual(auto_runner._read_risk_level("BUILD-999"), "unknown")

    def test_field_not_present(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            bid = "BUILD-004"
            spec_dir = td_path / bid
            spec_dir.mkdir()
            (spec_dir / "spec.yaml").write_text("build_type: new_file\n")
            with patch.object(auto_runner, "_STAGING", td_path):
                self.assertEqual(auto_runner._read_risk_level(bid), "unknown")


class TestRunSafeLane(unittest.TestCase):
    """run_safe_lane orchestrates the pipeline and respects the risk gate."""

    def _mock_spec_writer(self, ok=True, blocked=False, error=None):
        m = MagicMock()
        m.generate_spec_packet.return_value = {
            "ok":      ok,
            "blocked": blocked,
            "error":   error or "",
        }
        return m

    def _mock_approver(self, ok=True, error=None):
        m = MagicMock()
        m.approve_build.return_value = {"ok": ok, "error": error or ""}
        return m

    def _mock_s2auth(self, ok=True, error=None):
        m = MagicMock()
        m.authorize_stage2.return_value = {"ok": ok, "error": error or ""}
        return m

    def _mock_drafter(self, ok=True, error=None):
        m = MagicMock()
        m.generate_stage2_draft.return_value = {"ok": ok, "error": error or ""}
        return m

    def test_full_success_low_risk(self):
        spec_m    = self._mock_spec_writer(ok=True)
        approver  = self._mock_approver(ok=True)
        s2auth    = self._mock_s2auth(ok=True)
        drafter   = self._mock_drafter(ok=True)
        with (
            patch.dict("sys.modules", {
                "frank_lloyd.spec_writer":       spec_m,
                "frank_lloyd.spec_approver":     approver,
                "frank_lloyd.stage2_authorizer": s2auth,
                "frank_lloyd.stage2_drafter":    drafter,
            }),
            patch.object(auto_runner, "_read_risk_level", return_value="low"),
            patch.object(auto_runner, "_derive_current_status", return_value="draft_generated"),
        ):
            result = auto_runner.run_safe_lane("BUILD-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["final_status"], "draft_generated")
        self.assertIsNone(result["paused_reason"])
        # All 5 steps completed
        self.assertEqual(len(result["steps"]), 5)

    def test_proceeds_on_high_risk(self):
        """High-risk builds no longer pause — all builds run the full pipeline."""
        spec_m   = self._mock_spec_writer(ok=True)
        approver = self._mock_approver(ok=True)
        s2auth   = self._mock_s2auth(ok=True)
        drafter  = self._mock_drafter(ok=True)
        with (
            patch.dict("sys.modules", {
                "frank_lloyd.spec_writer":       spec_m,
                "frank_lloyd.spec_approver":     approver,
                "frank_lloyd.stage2_authorizer": s2auth,
                "frank_lloyd.stage2_drafter":    drafter,
            }),
            patch.object(auto_runner, "_read_risk_level", return_value="high"),
            patch.object(auto_runner, "_derive_current_status", return_value="draft_generated"),
        ):
            result = auto_runner.run_safe_lane("BUILD-002")

        # High risk no longer pauses — pipeline completes
        self.assertTrue(result["ok"])
        self.assertIsNone(result["paused_reason"])

    def test_proceeds_on_medium_risk(self):
        """Medium-risk builds also proceed without pausing."""
        spec_m   = self._mock_spec_writer(ok=True)
        approver = self._mock_approver(ok=True)
        s2auth   = self._mock_s2auth(ok=True)
        drafter  = self._mock_drafter(ok=True)
        with (
            patch.dict("sys.modules", {
                "frank_lloyd.spec_writer":       spec_m,
                "frank_lloyd.spec_approver":     approver,
                "frank_lloyd.stage2_authorizer": s2auth,
                "frank_lloyd.stage2_drafter":    drafter,
            }),
            patch.object(auto_runner, "_read_risk_level", return_value="medium"),
            patch.object(auto_runner, "_derive_current_status", return_value="draft_generated"),
        ):
            result = auto_runner.run_safe_lane("BUILD-003")

        self.assertTrue(result["ok"])
        self.assertIsNone(result["paused_reason"])

    def test_pauses_when_spec_blocked(self):
        spec_m = self._mock_spec_writer(ok=False, blocked=True, error="off-limits file")
        with (
            patch.dict("sys.modules", {"frank_lloyd.spec_writer": spec_m}),
            patch.object(auto_runner, "_derive_current_status", return_value="pending_spec"),
        ):
            result = auto_runner.run_safe_lane("BUILD-004")

        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["paused_reason"])
        self.assertIn("blocked", result["paused_reason"].lower())

    def test_fails_when_spec_errors_non_blocked(self):
        spec_m = self._mock_spec_writer(ok=False, blocked=False, error="Invalid state")
        with (
            patch.dict("sys.modules", {"frank_lloyd.spec_writer": spec_m}),
            patch.object(auto_runner, "_derive_current_status", return_value="pending_spec"),
        ):
            result = auto_runner.run_safe_lane("BUILD-005")

        self.assertFalse(result["ok"])
        self.assertIsNone(result["paused_reason"])
        self.assertIsNotNone(result["error"])

    def test_pauses_when_approve_fails(self):
        spec_m   = self._mock_spec_writer(ok=True)
        approver = self._mock_approver(ok=False, error="Spec already approved")
        with (
            patch.dict("sys.modules", {
                "frank_lloyd.spec_writer":   spec_m,
                "frank_lloyd.spec_approver": approver,
            }),
            patch.object(auto_runner, "_read_risk_level", return_value="low"),
            patch.object(auto_runner, "_derive_current_status", return_value="pending_review"),
        ):
            result = auto_runner.run_safe_lane("BUILD-006")

        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["paused_reason"])

    def test_pauses_when_auth_fails(self):
        spec_m  = self._mock_spec_writer(ok=True)
        approve = self._mock_approver(ok=True)
        s2auth  = self._mock_s2auth(ok=False, error="Already authorized")
        with (
            patch.dict("sys.modules", {
                "frank_lloyd.spec_writer":       spec_m,
                "frank_lloyd.spec_approver":     approve,
                "frank_lloyd.stage2_authorizer": s2auth,
            }),
            patch.object(auto_runner, "_read_risk_level", return_value="low"),
            patch.object(auto_runner, "_derive_current_status", return_value="spec_approved"),
        ):
            result = auto_runner.run_safe_lane("BUILD-007")

        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["paused_reason"])

    def test_pauses_when_draft_fails(self):
        spec_m  = self._mock_spec_writer(ok=True)
        approve = self._mock_approver(ok=True)
        s2auth  = self._mock_s2auth(ok=True)
        drafter = self._mock_drafter(ok=False, error="LM timeout")
        with (
            patch.dict("sys.modules", {
                "frank_lloyd.spec_writer":       spec_m,
                "frank_lloyd.spec_approver":     approve,
                "frank_lloyd.stage2_authorizer": s2auth,
                "frank_lloyd.stage2_drafter":    drafter,
            }),
            patch.object(auto_runner, "_read_risk_level", return_value="low"),
            patch.object(auto_runner, "_derive_current_status", return_value="stage2_authorized"),
        ):
            result = auto_runner.run_safe_lane("BUILD-008")

        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["paused_reason"])

    def test_build_id_uppercased(self):
        spec_m   = self._mock_spec_writer(ok=True)
        approver = self._mock_approver(ok=True)
        s2auth   = self._mock_s2auth(ok=True)
        drafter  = self._mock_drafter(ok=True)
        with (
            patch.dict("sys.modules", {
                "frank_lloyd.spec_writer":       spec_m,
                "frank_lloyd.spec_approver":     approver,
                "frank_lloyd.stage2_authorizer": s2auth,
                "frank_lloyd.stage2_drafter":    drafter,
            }),
            patch.object(auto_runner, "_read_risk_level", return_value="low"),
            patch.object(auto_runner, "_derive_current_status", return_value="draft_generated"),
        ):
            result = auto_runner.run_safe_lane("build-001")

        self.assertEqual(result["build_id"], "BUILD-001")

    def test_steps_track_progress(self):
        spec_m   = self._mock_spec_writer(ok=True)
        approver = self._mock_approver(ok=True)
        s2auth   = self._mock_s2auth(ok=True)
        drafter  = self._mock_drafter(ok=True)
        with (
            patch.dict("sys.modules", {
                "frank_lloyd.spec_writer":       spec_m,
                "frank_lloyd.spec_approver":     approver,
                "frank_lloyd.stage2_authorizer": s2auth,
                "frank_lloyd.stage2_drafter":    drafter,
            }),
            patch.object(auto_runner, "_read_risk_level", return_value="low"),
            patch.object(auto_runner, "_derive_current_status", return_value="draft_generated"),
        ):
            result = auto_runner.run_safe_lane("BUILD-001")

        step_names = [s["step"] for s in result["steps"]]
        self.assertIn("generate_spec",    step_names)
        self.assertIn("risk_note",        step_names)
        self.assertIn("approve_spec",     step_names)
        self.assertIn("authorize_stage2", step_names)
        self.assertIn("generate_draft",   step_names)


if __name__ == "__main__":
    unittest.main()
