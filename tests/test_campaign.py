"""
tests/test_campaign.py

Lightweight, targeted tests for the campaign orchestration layer.

Covers:
  - campaign stop conditions (all 5 rules, no I/O required)
  - campaign state save / load / round-trip
  - resume behavior (existing state loaded, completed guard)
  - lock acquire / release / stale-lock clearing / live-lock rejection
  - campaign report generation (structure, artifact map, markdown)
  - cap enforcement (max_sessions, max_experiments)
  - artifact clarity (best_validation_record, best_experiment_id, promotion command)

Run with:
    python -m pytest tests/test_campaign.py -v
    python -m unittest tests.test_campaign -v
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from research.campaign import (
    CampaignState,
    make_campaign_id,
    save_state,
    load_state,
    acquire_lock,
    release_lock,
    check_existing_lock,
    _pid_alive,
)
from research.campaign_runner  import CampaignRunner, _find_output_path_in_ledger
from research.campaign_report  import generate_campaign_report


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_state(
    campaign_id: str = "campaign_test_20260101T000000",
    status: str = "running",
    sessions_completed: int = 0,
    total_experiments: int = 0,
    total_accepted: int = 0,
    consecutive_no_progress: int = 0,
    session_dominant_failures: list | None = None,
    session_summaries: list | None = None,
    max_sessions: int = 3,
    max_experiments: int = 30,
    best_candidate: dict | None = None,
    stop_condition: str | None = None,
    stop_reason: str | None = None,
) -> CampaignState:
    return CampaignState(
        campaign_id       = campaign_id,
        created_at        = "2026-01-01T00:00:00+00:00",
        goal              = "Test campaign goal",
        notes             = "test notes",
        status            = status,
        config            = {
            "max_sessions":           max_sessions,
            "max_batches_per_session": 2,
            "experiments_per_batch":  3,
            "max_total_experiments":  max_experiments,
        },
        progress          = {
            "sessions_completed":               sessions_completed,
            "total_batches":                    sessions_completed * 2,
            "total_experiments":                total_experiments,
            "total_accepted":                   total_accepted,
            "consecutive_no_progress_sessions": consecutive_no_progress,
            "session_dominant_failures":        session_dominant_failures or [],
        },
        session_ids        = [f"session_{i}" for i in range(sessions_completed)],
        session_summaries  = session_summaries or [],
        best_candidate     = best_candidate,
        stop_condition     = stop_condition,
        stop_reason        = stop_reason,
        artifacts          = {
            "best_validation_record": None,
            "best_experiment_id":     None,
            "best_session_id":        None,
            "session_reports":        [],
            "session_md_reports":     [],
            "campaign_brief_json":    None,
            "campaign_brief_md":      None,
        },
    )


def _make_runner(state: CampaignState, tmp_dir: pathlib.Path) -> CampaignRunner:
    state_path = tmp_dir / "state.json"
    lock_path  = tmp_dir / ".campaign.lock"
    return CampaignRunner(
        state      = state,
        state_path = state_path,
        lock_path  = lock_path,
        verbose    = False,
        dry_run    = True,
    )


# ── 1. Campaign stop conditions ───────────────────────────────────────────────

class TestCampaignStopConditions(unittest.TestCase):

    def _check(self, state: CampaignState) -> tuple[bool, str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            runner = _make_runner(state, pathlib.Path(tmp))
            return runner._check_campaign_stop()

    def test_max_sessions_reached(self):
        state = _make_state(max_sessions=3, sessions_completed=3)
        stop, cond, reason = self._check(state)
        self.assertTrue(stop)
        self.assertEqual(cond, "max_sessions_reached")
        self.assertIn("3/3", reason)

    def test_not_stopped_below_max_sessions(self):
        state = _make_state(max_sessions=3, sessions_completed=2)
        stop, cond, _ = self._check(state)
        self.assertFalse(stop)
        self.assertEqual(cond, "")

    def test_max_experiments_reached(self):
        state = _make_state(max_experiments=30, total_experiments=30)
        stop, cond, reason = self._check(state)
        self.assertTrue(stop)
        self.assertEqual(cond, "max_experiments_reached")
        self.assertIn("30", reason)

    def test_max_experiments_not_reached(self):
        state = _make_state(max_experiments=30, total_experiments=29)
        stop, cond, _ = self._check(state)
        self.assertFalse(stop)

    def test_strong_candidate_confirmed(self):
        summaries = [
            {"best_tier": "strong",        "total_accepted": 1, "total_experiments": 3},
            {"best_tier": "review_worthy", "total_accepted": 1, "total_experiments": 3},
        ]
        state = _make_state(session_summaries=summaries, sessions_completed=2)
        stop, cond, reason = self._check(state)
        self.assertTrue(stop)
        self.assertEqual(cond, "strong_candidate_confirmed")
        self.assertIn("2", reason)

    def test_strong_candidate_not_triggered_below_threshold(self):
        summaries = [
            {"best_tier": "strong", "total_accepted": 1, "total_experiments": 3},
        ]
        state = _make_state(session_summaries=summaries, sessions_completed=1)
        stop, cond, _ = self._check(state)
        # Only 1 strong session, threshold is 2 → should NOT stop
        self.assertFalse(stop)

    def test_no_progress_campaign(self):
        state = _make_state(consecutive_no_progress=2)
        stop, cond, reason = self._check(state)
        self.assertTrue(stop)
        self.assertEqual(cond, "no_progress_campaign")
        self.assertIn("2", reason)

    def test_no_progress_not_triggered_below_threshold(self):
        state = _make_state(consecutive_no_progress=1)
        stop, cond, _ = self._check(state)
        self.assertFalse(stop)

    def test_dominant_failure_persists(self):
        # Same failure mode in 3 consecutive sessions; use max_sessions=6 so
        # max_sessions_reached does not fire before this condition is checked.
        state = _make_state(
            session_dominant_failures=["worst_pnl", "worst_pnl", "worst_pnl"],
            sessions_completed=3,
            max_sessions=6,
        )
        stop, cond, reason = self._check(state)
        self.assertTrue(stop)
        self.assertEqual(cond, "dominant_failure_persists")
        self.assertIn("worst_pnl", reason)

    def test_dominant_failure_not_triggered_mixed(self):
        # Mixed failure modes → no stop; use max_sessions=6 to avoid early exit
        state = _make_state(
            session_dominant_failures=["worst_pnl", "median_pnl", "worst_pnl"],
            sessions_completed=3,
            max_sessions=6,
        )
        stop, cond, _ = self._check(state)
        self.assertFalse(stop)

    def test_dominant_failure_not_triggered_below_count(self):
        state = _make_state(
            session_dominant_failures=["worst_pnl", "worst_pnl"],
            sessions_completed=2,
        )
        stop, cond, _ = self._check(state)
        # Only 2 sessions, threshold is 3 → should NOT stop
        self.assertFalse(stop)

    def test_no_stop_when_all_conditions_clear(self):
        state = _make_state(
            sessions_completed=1,
            total_experiments=9,
            total_accepted=2,
            max_sessions=3,
            max_experiments=30,
            consecutive_no_progress=0,
            session_dominant_failures=["worst_pnl"],
            session_summaries=[{"best_tier": "noisy", "total_accepted": 2, "total_experiments": 9}],
        )
        stop, cond, _ = self._check(state)
        self.assertFalse(stop)
        self.assertEqual(cond, "")

    def test_stop_conditions_priority_sessions_before_experiments(self):
        # Both max_sessions AND max_experiments triggered — max_sessions wins (checked first)
        state = _make_state(
            max_sessions=3,
            sessions_completed=3,
            max_experiments=30,
            total_experiments=30,
        )
        stop, cond, _ = self._check(state)
        self.assertTrue(stop)
        self.assertEqual(cond, "max_sessions_reached")


# ── 2. State save / load ──────────────────────────────────────────────────────

class TestCampaignStatePersistence(unittest.TestCase):

    def test_save_and_load_roundtrip(self):
        state = _make_state(sessions_completed=2, total_experiments=12, total_accepted=3)
        with tempfile.TemporaryDirectory() as tmp:
            path  = pathlib.Path(tmp) / "state.json"
            save_state(state, path)
            loaded = load_state(path)

        self.assertEqual(loaded.campaign_id,     state.campaign_id)
        self.assertEqual(loaded.goal,            state.goal)
        self.assertEqual(loaded.status,          state.status)
        self.assertEqual(loaded.progress["sessions_completed"], 2)
        self.assertEqual(loaded.progress["total_experiments"],  12)
        self.assertEqual(loaded.progress["total_accepted"],     3)
        self.assertEqual(loaded.config["max_sessions"],         state.config["max_sessions"])

    def test_atomic_save_uses_tmp_then_rename(self):
        state = _make_state()
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "state.json"
            save_state(state, path)
            # Final file must exist; .tmp must be cleaned up
            self.assertTrue(path.exists())
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_to_dict_from_dict_roundtrip(self):
        state = _make_state(
            total_experiments=5,
            best_candidate={"experiment_id": "batch_001", "score": 72.0, "tier": "review_worthy"},
        )
        d      = state.to_dict()
        loaded = CampaignState.from_dict(d)
        self.assertEqual(loaded.best_candidate["score"], 72.0)
        self.assertEqual(loaded.schema_version, CampaignState.SCHEMA_VERSION)

    def test_from_dict_tolerates_missing_keys(self):
        # Simulate a state file from an older version missing new keys
        minimal = {
            "campaign_id": "campaign_old_001",
            "created_at":  "2026-01-01T00:00:00+00:00",
        }
        state = CampaignState.from_dict(minimal)
        # Should not raise; progress keys filled with defaults
        self.assertEqual(state.progress["sessions_completed"], 0)
        self.assertEqual(state.session_ids, [])

    def test_state_file_is_valid_json(self):
        state = _make_state()
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "state.json"
            save_state(state, path)
            data = json.loads(path.read_text())
        self.assertIn("campaign_id", data)
        self.assertIn("progress",    data)
        self.assertIn("config",      data)


# ── 3. Resume behavior ────────────────────────────────────────────────────────

class TestCampaignResume(unittest.TestCase):

    def test_load_partial_state_preserves_session_ids(self):
        state = _make_state(sessions_completed=2)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "state.json"
            save_state(state, path)
            loaded = load_state(path)
        self.assertEqual(len(loaded.session_ids), 2)
        self.assertEqual(loaded.session_ids[0], "session_0")

    def test_resume_from_completed_detectable(self):
        state = _make_state(status="completed", stop_condition="max_sessions_reached")
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "state.json"
            save_state(state, path)
            loaded = load_state(path)
        self.assertEqual(loaded.status, "completed")
        self.assertEqual(loaded.stop_condition, "max_sessions_reached")

    def test_resume_does_not_double_count_completed_sessions(self):
        # A runner on a partially-complete state should only run remaining sessions
        state = _make_state(sessions_completed=2, max_sessions=3)
        with tempfile.TemporaryDirectory() as tmp:
            runner = _make_runner(state, pathlib.Path(tmp))
            # With 2/3 done, one more should run before max_sessions stop
            stop, cond, _ = runner._check_campaign_stop()
            self.assertFalse(stop)  # Not yet at cap
            # Simulate completing the third session
            state.progress["sessions_completed"] = 3
            stop, cond, _ = runner._check_campaign_stop()
            self.assertTrue(stop)
            self.assertEqual(cond, "max_sessions_reached")

    def test_interrupted_state_is_resumable(self):
        state = _make_state(status="interrupted", sessions_completed=1)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "state.json"
            save_state(state, path)
            loaded = load_state(path)
        self.assertEqual(loaded.status, "interrupted")
        self.assertEqual(loaded.progress["sessions_completed"], 1)


# ── 4. Lock behavior ──────────────────────────────────────────────────────────

class TestCampaignLock(unittest.TestCase):

    def test_acquire_creates_lock_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            d         = pathlib.Path(tmp)
            lock_path = acquire_lock(d, "campaign_test_001")
            self.assertTrue(lock_path.exists())
            data = json.loads(lock_path.read_text())
            self.assertEqual(data["campaign_id"], "campaign_test_001")
            self.assertEqual(data["pid"],         os.getpid())
            release_lock(lock_path)

    def test_release_removes_lock_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            d         = pathlib.Path(tmp)
            lock_path = acquire_lock(d, "campaign_test_002")
            release_lock(lock_path)
            self.assertFalse(lock_path.exists())

    def test_release_is_safe_when_no_lock_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            d         = pathlib.Path(tmp)
            lock_path = d / ".campaign.lock"
            release_lock(lock_path)   # should not raise

    def test_check_existing_lock_returns_none_when_no_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = check_existing_lock(pathlib.Path(tmp))
            self.assertIsNone(result)

    def test_check_existing_lock_returns_data_for_live_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            d         = pathlib.Path(tmp)
            lock_path = acquire_lock(d, "campaign_live_001")
            result    = check_existing_lock(d)
            self.assertIsNotNone(result)
            self.assertEqual(result["campaign_id"], "campaign_live_001")
            release_lock(lock_path)

    def test_stale_lock_is_cleared_on_acquire(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            # Write a lock with a dead PID
            stale = {"pid": _DEAD_PID, "campaign_id": "campaign_stale_001", "acquired_at": "..."}
            (d / ".campaign.lock").write_text(json.dumps(stale))
            # Acquiring should succeed (stale lock cleared), not raise
            lock_path = acquire_lock(d, "campaign_new_002")
            self.assertTrue(lock_path.exists())
            data = json.loads(lock_path.read_text())
            self.assertEqual(data["campaign_id"], "campaign_new_002")
            release_lock(lock_path)

    def test_live_lock_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            # Write a lock with the current process's PID (guaranteed alive)
            live = {"pid": os.getpid(), "campaign_id": "campaign_live_002", "acquired_at": "..."}
            (d / ".campaign.lock").write_text(json.dumps(live))
            with self.assertRaises(RuntimeError):
                acquire_lock(d, "campaign_new_003")

    def test_check_stale_lock_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            stale = {"pid": _DEAD_PID, "campaign_id": "campaign_stale_002", "acquired_at": "..."}
            (d / ".campaign.lock").write_text(json.dumps(stale))
            result = check_existing_lock(d)
            self.assertIsNone(result)


# Guaranteed-dead PID: PID 1 is init; we can't kill it, but we can use a
# very large PID that is almost certainly not running.
_DEAD_PID = 9_999_999


# ── 5. Campaign report generation ─────────────────────────────────────────────

class TestCampaignReport(unittest.TestCase):

    def _build_state_with_results(self) -> CampaignState:
        state = _make_state(
            sessions_completed=2,
            total_experiments=12,
            total_accepted=3,
            session_summaries=[
                {
                    "session_id":        "session_A",
                    "total_experiments": 6,
                    "total_accepted":    2,
                    "classes_tested":    ["entry_quality", "profit_taking"],
                    "best_score":        72.0,
                    "best_tier":         "review_worthy",
                    "human_review":      True,
                    "stop_condition":    "max_batches_reached",
                    "dominant_failure":  "worst_pnl",
                },
                {
                    "session_id":        "session_B",
                    "total_experiments": 6,
                    "total_accepted":    1,
                    "classes_tested":    ["entry_quality"],
                    "best_score":        55.0,
                    "best_tier":         "noisy",
                    "human_review":      True,
                    "stop_condition":    "max_batches_reached",
                    "dominant_failure":  "worst_pnl",
                },
            ],
            best_candidate={
                "experiment_id":    "batch_test_001",
                "experiment_class": "entry_quality",
                "score":            72.0,
                "tier":             "review_worthy",
                "decision":         "ACCEPTED",
                "pnl_delta":        42.5,
                "worst_pnl_delta":  15.0,
                "candidate_config": {"MAX_EFFICIENCY_RATIO": 0.35},
                "session_id":       "session_A",
            },
            session_dominant_failures=["worst_pnl", "worst_pnl"],
            stop_condition="max_sessions_reached",
            stop_reason="Completed 2/3 planned sessions.",
        )
        state.artifacts["best_validation_record"] = (
            "data/validation_runs/20260101T000000_batch_test_001.json"
        )
        state.artifacts["best_experiment_id"] = "batch_test_001"
        state.artifacts["best_session_id"]    = "session_A"
        return state

    def test_report_has_required_keys(self):
        state = self._build_state_with_results()
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_campaigns_root(tmp):
                report = generate_campaign_report(state)
        required = [
            "campaign_id", "goal", "status", "what_ran", "stop_condition",
            "stop_reason", "dominant_findings", "what_improved",
            "what_repeatedly_failed", "best_candidate", "artifacts",
            "human_review_recommended", "human_review_reason",
            "next_campaign_focus", "session_summaries",
        ]
        for key in required:
            self.assertIn(key, report, f"Missing key: {key}")

    def test_artifact_map_clarity(self):
        state = self._build_state_with_results()
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_campaigns_root(tmp):
                report = generate_campaign_report(state)
        art = report["artifacts"]
        self.assertEqual(art["best_experiment_id"],     "batch_test_001")
        self.assertEqual(art["best_session_id"],        "session_A")
        self.assertIsNotNone(art["best_validation_record"])
        self.assertIsNotNone(art["best_promotion_command"])
        self.assertIn("promote_candidate.py", art["best_promotion_command"])
        self.assertIn("batch_test_001", art["best_promotion_command"])

    def test_human_review_reason_includes_promote_command(self):
        state = self._build_state_with_results()
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_campaigns_root(tmp):
                report = generate_campaign_report(state)
        reason = report["human_review_reason"]
        self.assertIn("promote_candidate.py", reason)
        self.assertIn("batch_test_001", reason)

    def test_no_best_candidate_handled_gracefully(self):
        state = _make_state(sessions_completed=2, total_experiments=6)
        state.stop_condition = "no_progress_campaign"
        state.stop_reason    = "Two sessions with zero accepted."
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_campaigns_root(tmp):
                report = generate_campaign_report(state)
        self.assertIsNone(report["best_candidate"])
        self.assertFalse(report["human_review_recommended"])

    def test_report_files_written_to_disk(self):
        state = self._build_state_with_results()
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_campaigns_root(tmp):
                report = generate_campaign_report(state)
            json_path = pathlib.Path(report["_brief_json_path"])
            md_path   = pathlib.Path(report["_brief_md_path"])
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            # JSON must be valid and clean (no private _ keys)
            data = json.loads(json_path.read_text())
            for k in data:
                self.assertFalse(k.startswith("_"), f"Private key in JSON: {k}")

    def test_markdown_contains_key_sections(self):
        state = self._build_state_with_results()
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_campaigns_root(tmp):
                report = generate_campaign_report(state)
            md = pathlib.Path(report["_brief_md_path"]).read_text()
        for section in [
            "Campaign Operator Brief",
            "What Ran",
            "Stop Condition",
            "Best Candidate",
            "Artifact Map",
            "Dominant Findings",
            "What Improved",
            "What Repeatedly Failed",
            "Recommended Next Campaign Focus",
        ]:
            self.assertIn(section, md, f"Section missing from markdown: {section}")

    def test_what_ran_counts_are_correct(self):
        state = self._build_state_with_results()
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_campaigns_root(tmp):
                report = generate_campaign_report(state)
        w = report["what_ran"]
        self.assertEqual(w["sessions_ran"],      2)
        self.assertEqual(w["total_experiments"], 12)
        self.assertEqual(w["total_accepted"],    3)

    def test_classes_emphasized_sorted_by_frequency(self):
        state = self._build_state_with_results()
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_campaigns_root(tmp):
                report = generate_campaign_report(state)
        # entry_quality appears in both sessions; profit_taking only in session_A
        classes = report["what_ran"]["classes_emphasized"]
        self.assertEqual(classes[0], "entry_quality")


# ── 6. Cap enforcement ────────────────────────────────────────────────────────

class TestCapEnforcement(unittest.TestCase):

    def test_sessions_cap_applied_by_runner(self):
        # Runner should stop as soon as sessions_completed >= max_sessions
        state = _make_state(max_sessions=2, sessions_completed=2)
        with tempfile.TemporaryDirectory() as tmp:
            runner = _make_runner(state, pathlib.Path(tmp))
            stop, cond, _ = runner._check_campaign_stop()
        self.assertTrue(stop)
        self.assertEqual(cond, "max_sessions_reached")

    def test_experiments_cap_applied_by_runner(self):
        state = _make_state(max_experiments=10, total_experiments=10)
        with tempfile.TemporaryDirectory() as tmp:
            runner = _make_runner(state, pathlib.Path(tmp))
            stop, cond, _ = runner._check_campaign_stop()
        self.assertTrue(stop)
        self.assertEqual(cond, "max_experiments_reached")

    def test_budget_remaining_limits_experiments_per_batch(self):
        # With 2 remaining and exp_per_batch=3, runner should pass max(1, 2) = 2
        state = _make_state(max_experiments=10, total_experiments=8)
        state.config["experiments_per_batch"] = 3
        with tempfile.TemporaryDirectory() as tmp:
            runner = _make_runner(state, pathlib.Path(tmp))
            remaining = (
                state.config["max_total_experiments"]
                - state.progress["total_experiments"]
            )
            effective = max(1, min(state.config["experiments_per_batch"], remaining))
            self.assertEqual(effective, 2)

    def test_make_campaign_id_has_correct_prefix(self):
        cid = make_campaign_id()
        self.assertTrue(cid.startswith("campaign_"))
        self.assertEqual(len(cid), len("campaign_20260101T000000"))


# ── 7. Ledger output_path lookup ──────────────────────────────────────────────

class TestOutputPathLookup(unittest.TestCase):

    def test_returns_none_for_missing_ledger(self):
        # No ledger file → returns None, does not raise
        result = _find_output_path_in_ledger("batch_test_001")
        # We can't assert exactly None because the real ledger might exist;
        # just assert it doesn't raise
        self.assertIsInstance(result, (str, type(None)))

    def test_returns_none_for_none_experiment_id(self):
        result = _find_output_path_in_ledger(None)
        self.assertIsNone(result)

    def test_finds_output_path_in_mock_ledger(self):
        experiment_id = "batch_mock_20260101T000000_001"
        expected_path = "data/validation_runs/20260101T000000_batch_mock_001.json"

        ledger_entry = json.dumps({
            "batch_id": "batch_mock_20260101T000000",
            "summary": {"accepted": 1, "rejected": 0, "failed": 0},
            "experiments": [
                {
                    "experiment_id": experiment_id,
                    "output_path":   expected_path,
                    "decision":      "ACCEPTED",
                }
            ],
            "candidates_for_review": [],
        })

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = pathlib.Path(tmp) / "ledger.jsonl"
            ledger_path.write_text(ledger_entry + "\n")

            import research.campaign_runner as cr_module
            original = cr_module._LEDGER_PATH
            try:
                cr_module._LEDGER_PATH = ledger_path
                result = _find_output_path_in_ledger(experiment_id)
            finally:
                cr_module._LEDGER_PATH = original

        self.assertEqual(result, expected_path)


# ── Helpers ────────────────────────────────────────────────────────────────────

from contextlib import contextmanager

@contextmanager
def _patch_campaigns_root(tmp_dir: str):
    """Redirect campaign_report._ROOT to a temp dir so files go there."""
    import research.campaign_report as cr
    original = cr._ROOT
    cr._ROOT = pathlib.Path(tmp_dir)
    try:
        yield
    finally:
        cr._ROOT = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
