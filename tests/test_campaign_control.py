"""
tests/test_campaign_control.py

Targeted tests for the operator control panel backend (ui/campaign_control.py).

Covers:
  - validate_campaign_form: happy path, goal length, cap violations, budget
  - list_campaigns / list_resumable_campaigns: mock filesystem
  - get_best_candidate / get_promotion_command: mock state JSON
  - stop signal helpers: request_stop, stop_requested, clear_stop_signal
  - start_campaign guards: lock active, validation failed
  - resume_campaign guards: already completed, not found, lock active

Run with:
    python -m pytest tests/test_campaign_control.py -v
    python -m unittest tests.test_campaign_control -v
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import ui.campaign_control as cc
from research.campaign import (
    request_stop,
    stop_requested,
    clear_stop_signal,
)


# ── validate_campaign_form ────────────────────────────────────────────────────

class TestValidateCampaignForm(unittest.TestCase):

    def _call(self, **kwargs):
        defaults = dict(
            goal="Find a better MR strategy",
            max_sessions=3,
            max_batches=3,
            experiments=3,
            max_experiments=60,
            budget_usd=0.0,
        )
        defaults.update(kwargs)
        return cc.validate_campaign_form(**defaults)

    def test_happy_path(self):
        ok, errors, clamped = self._call()
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        self.assertEqual(clamped["goal"], "Find a better MR strategy")

    def test_goal_stripped(self):
        ok, errors, clamped = self._call(goal="  trim me  ")
        self.assertTrue(ok)
        self.assertEqual(clamped["goal"], "trim me")

    def test_goal_too_short(self):
        ok, errors, _ = self._call(goal="ab")
        self.assertFalse(ok)
        self.assertTrue(any("Goal" in e for e in errors))

    def test_goal_empty(self):
        ok, errors, _ = self._call(goal="")
        self.assertFalse(ok)
        self.assertTrue(any("Goal" in e for e in errors))

    def test_goal_exactly_min_length(self):
        ok, errors, _ = self._call(goal="abcde")  # 5 chars
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_sessions_zero(self):
        ok, errors, _ = self._call(max_sessions=0)
        self.assertFalse(ok)
        self.assertTrue(any("sessions" in e for e in errors))

    def test_sessions_over_cap(self):
        ok, errors, _ = self._call(max_sessions=7)
        self.assertFalse(ok)
        self.assertTrue(any("sessions" in e for e in errors))

    def test_sessions_at_cap(self):
        ok, errors, _ = self._call(max_sessions=6)
        self.assertTrue(ok)

    def test_batches_zero(self):
        ok, errors, _ = self._call(max_batches=0)
        self.assertFalse(ok)
        self.assertTrue(any("batch" in e.lower() for e in errors))

    def test_batches_over_cap(self):
        ok, errors, _ = self._call(max_batches=5)
        self.assertFalse(ok)
        self.assertTrue(any("batch" in e.lower() for e in errors))

    def test_batches_at_cap(self):
        ok, errors, _ = self._call(max_batches=4)
        self.assertTrue(ok)

    def test_experiments_below_min(self):
        ok, errors, _ = self._call(experiments=2)
        self.assertFalse(ok)
        self.assertTrue(any("Experiments per batch" in e for e in errors))

    def test_experiments_above_cap(self):
        ok, errors, _ = self._call(experiments=6)
        self.assertFalse(ok)
        self.assertTrue(any("Experiments per batch" in e for e in errors))

    def test_experiments_at_bounds(self):
        for n in (3, 4, 5):
            ok, errors, _ = self._call(experiments=n)
            self.assertTrue(ok, f"experiments={n} should be valid")

    def test_max_experiments_zero(self):
        ok, errors, _ = self._call(max_experiments=0)
        self.assertFalse(ok)
        self.assertTrue(any("budget" in e.lower() for e in errors))

    def test_max_experiments_over_cap(self):
        ok, errors, _ = self._call(max_experiments=101)
        self.assertFalse(ok)
        self.assertTrue(any("budget" in e.lower() for e in errors))

    def test_max_experiments_at_cap(self):
        ok, errors, _ = self._call(max_experiments=100)
        self.assertTrue(ok)

    def test_negative_budget(self):
        ok, errors, _ = self._call(budget_usd=-1.0)
        self.assertFalse(ok)
        self.assertTrue(any("Budget" in e for e in errors))

    def test_zero_budget_allowed(self):
        ok, errors, _ = self._call(budget_usd=0.0)
        self.assertTrue(ok)

    def test_positive_budget_allowed(self):
        ok, errors, _ = self._call(budget_usd=25.0)
        self.assertTrue(ok)

    def test_clamped_values_returned_even_on_error(self):
        # Clamped dict always comes back regardless of errors
        _, _, clamped = self._call(max_sessions=99, experiments=99)
        self.assertLessEqual(clamped["max_sessions"], 6)
        self.assertLessEqual(clamped["experiments"], 5)

    def test_multiple_errors_accumulated(self):
        ok, errors, _ = self._call(goal="x", max_sessions=0, max_batches=0)
        self.assertFalse(ok)
        self.assertGreaterEqual(len(errors), 3)


# ── list_campaigns / list_resumable_campaigns ─────────────────────────────────

def _write_campaign(camps_dir: pathlib.Path, campaign_id: str, status: str) -> None:
    d = camps_dir / campaign_id
    d.mkdir(parents=True)
    state = {
        "campaign_id": campaign_id,
        "goal": f"Goal for {campaign_id}",
        "status": status,
        "created_at": f"2026-04-0{campaign_id[-1]}T00:00:00+00:00",
        "progress": {"sessions_completed": 1, "total_experiments": 10, "total_accepted": 2},
        "config": {"max_sessions": 3},
        "stop_condition": None,
        "best_candidate": None,
        "artifacts": {},
    }
    (d / "state.json").write_text(json.dumps(state))


class TestListCampaigns(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self._camps = pathlib.Path(self._tmpdir.name)
        # Patch _CAMPS in the service module (campaign_control re-exports from there)
        self._patcher = patch("research.campaign_service._CAMPS", self._camps)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def test_empty_dir(self):
        result = cc.list_campaigns()
        self.assertEqual(result, [])

    def test_nonexistent_dir(self):
        patch("research.campaign_service._CAMPS", pathlib.Path("/nonexistent/path/xyz")).start()
        result = cc.list_campaigns()
        self.assertEqual(result, [])
        # restore
        patch.stopall()
        self._patcher = patch("research.campaign_service._CAMPS", self._camps)
        self._patcher.start()

    def test_single_campaign(self):
        _write_campaign(self._camps, "campaign_1", "completed")
        result = cc.list_campaigns()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["campaign_id"], "campaign_1")
        self.assertEqual(result[0]["status"], "completed")

    def test_multiple_campaigns_sorted_newest_first(self):
        _write_campaign(self._camps, "campaign_1", "completed")
        _write_campaign(self._camps, "campaign_2", "interrupted")
        _write_campaign(self._camps, "campaign_3", "running")
        result = cc.list_campaigns()
        self.assertEqual(len(result), 3)
        # sorted by created_at descending
        ids = [r["campaign_id"] for r in result]
        self.assertEqual(ids, ["campaign_3", "campaign_2", "campaign_1"])

    def test_result_fields(self):
        _write_campaign(self._camps, "campaign_1", "completed")
        r = cc.list_campaigns()[0]
        for key in ("campaign_id", "goal", "status", "created_at",
                    "sessions_completed", "max_sessions",
                    "total_experiments", "total_accepted"):
            self.assertIn(key, r)

    def test_list_resumable_excludes_completed(self):
        _write_campaign(self._camps, "campaign_1", "completed")
        _write_campaign(self._camps, "campaign_2", "interrupted")
        with patch("research.campaign_service.check_lock", return_value=None):
            result = cc.list_resumable_campaigns()
        ids = [r["campaign_id"] for r in result]
        self.assertNotIn("campaign_1", ids)
        self.assertIn("campaign_2", ids)

    def test_list_resumable_excludes_live_campaign(self):
        _write_campaign(self._camps, "campaign_2", "running")
        _write_campaign(self._camps, "campaign_3", "interrupted")
        with patch("research.campaign_service.check_lock", return_value={"campaign_id": "campaign_2", "pid": 99999}):
            result = cc.list_resumable_campaigns()
        ids = [r["campaign_id"] for r in result]
        self.assertNotIn("campaign_2", ids)
        self.assertIn("campaign_3", ids)


# ── get_best_candidate / get_promotion_command ────────────────────────────────

class TestArtifactReaders(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self._camps = pathlib.Path(self._tmpdir.name)
        self._patcher = patch("research.campaign_service._CAMPS", self._camps)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def _write_state(self, campaign_id: str, state: dict) -> None:
        d = self._camps / campaign_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps(state))

    def test_get_best_candidate_none_when_missing(self):
        result = cc.get_best_candidate("campaign_missing")
        self.assertIsNone(result)

    def test_get_best_candidate_returns_dict(self):
        self._write_state("c1", {
            "campaign_id": "c1",
            "best_candidate": {"tier": "strong", "score": 0.85},
            "artifacts": {},
        })
        result = cc.get_best_candidate("c1")
        self.assertIsNotNone(result)
        self.assertEqual(result["tier"], "strong")

    def test_get_best_candidate_none_when_null(self):
        self._write_state("c1", {"campaign_id": "c1", "best_candidate": None, "artifacts": {}})
        self.assertIsNone(cc.get_best_candidate("c1"))

    def test_get_promotion_command_none_when_no_state(self):
        result = cc.get_promotion_command("campaign_missing")
        self.assertIsNone(result)

    def test_get_promotion_command_none_when_no_record(self):
        self._write_state("c1", {
            "campaign_id": "c1",
            "artifacts": {"best_validation_record": None},
        })
        self.assertIsNone(cc.get_promotion_command("c1"))

    def test_get_promotion_command_format(self):
        rec = "data/validation_runs/20260409T123456_batch_xyz_001.json"
        self._write_state("c1", {
            "campaign_id": "c1",
            "artifacts": {"best_validation_record": rec},
        })
        cmd = cc.get_promotion_command("c1")
        self.assertIsNotNone(cmd)
        self.assertIn("promote_candidate.py", cmd)
        self.assertIn(rec, cmd)
        self.assertIn("--record", cmd)

    def test_get_campaign_brief_paths_missing(self):
        result = cc.get_campaign_brief_paths("campaign_missing")
        self.assertIsNone(result["json"])
        self.assertIsNone(result["md"])

    def test_get_campaign_brief_paths_found(self):
        self._write_state("c1", {
            "campaign_id": "c1",
            "artifacts": {
                "campaign_brief_json": "data/campaigns/c1/brief.json",
                "campaign_brief_md":   "data/campaigns/c1/brief.md",
            },
        })
        result = cc.get_campaign_brief_paths("c1")
        self.assertEqual(result["json"], "data/campaigns/c1/brief.json")
        self.assertEqual(result["md"], "data/campaigns/c1/brief.md")


# ── Stop signal helpers (research.campaign) ───────────────────────────────────

class TestStopSignalHelpers(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self._camps = pathlib.Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_not_requested_initially(self):
        self.assertFalse(stop_requested(self._camps))

    def test_request_creates_signal(self):
        request_stop(self._camps)
        self.assertTrue(stop_requested(self._camps))

    def test_clear_removes_signal(self):
        request_stop(self._camps)
        clear_stop_signal(self._camps)
        self.assertFalse(stop_requested(self._camps))

    def test_clear_idempotent_when_no_signal(self):
        # Should not raise even when file absent
        clear_stop_signal(self._camps)
        self.assertFalse(stop_requested(self._camps))

    def test_request_creates_dir_if_missing(self):
        nested = self._camps / "nested" / "subdir"
        request_stop(nested)
        self.assertTrue(stop_requested(nested))


# ── start_campaign guards ─────────────────────────────────────────────────────

class TestStartCampaignGuards(unittest.TestCase):

    def test_validation_failure_returns_not_ok(self):
        result = cc.start_campaign(goal="x")  # too short
        self.assertFalse(result["ok"])
        self.assertIn("Goal", result["message"])
        self.assertIsNone(result["pid"])

    def test_live_lock_blocks_start(self):
        with patch("research.campaign_service.check_lock", return_value={"campaign_id": "c1", "pid": 12345}):
            result = cc.start_campaign(goal="A valid research goal here")
        self.assertFalse(result["ok"])
        self.assertIn("already running", result["message"])
        self.assertIsNone(result["pid"])

    def test_subprocess_error_returns_not_ok(self):
        with patch("research.campaign_service.check_lock", return_value=None):
            with patch("subprocess.Popen", side_effect=OSError("no such file")):
                result = cc.start_campaign(goal="A valid research goal here")
        self.assertFalse(result["ok"])
        self.assertIn("Failed", result["message"])

    def test_successful_start_returns_pid(self):
        mock_proc = MagicMock()
        mock_proc.pid = 42000
        with patch("research.campaign_service.check_lock", return_value=None):
            with patch("subprocess.Popen", return_value=mock_proc):
                result = cc.start_campaign(goal="A valid research goal here")
        self.assertTrue(result["ok"])
        self.assertEqual(result["pid"], 42000)


# ── resume_campaign guards ────────────────────────────────────────────────────

class TestResumeCampaignGuards(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self._camps = pathlib.Path(self._tmpdir.name)
        self._patcher = patch("research.campaign_service._CAMPS", self._camps)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def _write_state(self, campaign_id: str, status: str) -> None:
        d = self._camps / campaign_id
        d.mkdir(parents=True, exist_ok=True)
        state = {
            "campaign_id": campaign_id,
            "status": status,
            "progress": {"sessions_completed": 1},
            "config": {"max_sessions": 3},
        }
        (d / "state.json").write_text(json.dumps(state))

    def test_empty_id_rejected(self):
        with patch("research.campaign_service.check_lock", return_value=None):
            result = cc.resume_campaign("")
        self.assertFalse(result["ok"])

    def test_live_lock_blocks_resume(self):
        self._write_state("c1", "interrupted")
        with patch("research.campaign_service.check_lock", return_value={"campaign_id": "c2", "pid": 99}):
            result = cc.resume_campaign("c1")
        self.assertFalse(result["ok"])
        self.assertIn("already running", result["message"])

    def test_not_found_returns_error(self):
        with patch("research.campaign_service.check_lock", return_value=None):
            result = cc.resume_campaign("campaign_does_not_exist")
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["message"])

    def test_completed_campaign_blocked(self):
        self._write_state("c1", "completed")
        with patch("research.campaign_service.check_lock", return_value=None):
            result = cc.resume_campaign("c1")
        self.assertFalse(result["ok"])
        self.assertIn("completed", result["message"])

    def test_interrupted_campaign_resumes(self):
        self._write_state("c1", "interrupted")
        mock_proc = MagicMock()
        mock_proc.pid = 55000
        with patch("research.campaign_service.check_lock", return_value=None):
            with patch("subprocess.Popen", return_value=mock_proc):
                result = cc.resume_campaign("c1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["pid"], 55000)


# ── request_stop / cancel_stop (via campaign_control) ─────────────────────────

class TestControlStopFunctions(unittest.TestCase):

    def test_request_stop_no_lock_fails(self):
        with patch("research.campaign_service.check_lock", return_value=None):
            result = cc.request_stop()
        self.assertFalse(result["ok"])
        self.assertIn("No campaign", result["message"])

    def test_request_stop_with_lock_succeeds(self):
        with patch("research.campaign_service.check_lock", return_value={"campaign_id": "c1", "pid": 100}):
            with patch("research.campaign.request_stop") as mock_rs:
                result = cc.request_stop()
        self.assertTrue(result["ok"])
        mock_rs.assert_called_once()

    def test_cancel_stop_signal(self):
        with patch("research.campaign.clear_stop_signal") as mock_cs:
            result = cc.cancel_stop_signal()
        self.assertTrue(result["ok"])
        mock_cs.assert_called_once()

    def test_stop_signal_pending_false(self):
        with patch("research.campaign.stop_requested", return_value=False):
            self.assertFalse(cc.stop_signal_pending())

    def test_stop_signal_pending_true(self):
        with patch("research.campaign.stop_requested", return_value=True):
            self.assertTrue(cc.stop_signal_pending())


if __name__ == "__main__":
    unittest.main()
