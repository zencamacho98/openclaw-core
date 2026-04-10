"""
tests/test_review_actions.py

Tests for ui/review_actions.py:
  - get_review_payload()
  - skip_and_continue_action()
  - hold_review() / resume_review()

And integration with app/strategy/applier.promote_from_record().

Run with:
    python -m pytest tests/test_review_actions.py -v
    python -m unittest tests.test_review_actions -v
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from ui.review_actions import (
    get_review_payload,
    skip_and_continue_action,
    hold_review,
    resume_review,
    skip_review,
)
from observability.agent_state import (
    STATUS_REVIEW_HELD,
    STATUS_WAITING_FOR_REVIEW,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_record(tmp_dir: pathlib.Path, data: dict) -> pathlib.Path:
    path = tmp_dir / "record.json"
    path.write_text(json.dumps(data))
    return path


# ── TestGetReviewPayload ──────────────────────────────────────────────────────

class TestGetReviewPayload(unittest.TestCase):

    def test_missing_path_returns_error(self):
        ok, err, rec = get_review_payload("")
        self.assertFalse(ok)
        self.assertIn("No record path", err)

    def test_nonexistent_file_returns_error(self):
        ok, err, rec = get_review_payload("/nonexistent/path/record.json")
        self.assertFalse(ok)
        self.assertIn("not found", err)

    def test_rejected_record_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_record(
                pathlib.Path(tmp),
                {"decision": "REJECTED", "candidate_config": {"POSITION_SIZE": 0.2}},
            )
            ok, err, rec = get_review_payload(str(path))
        self.assertFalse(ok)
        self.assertIn("REJECTED", err)

    def test_no_candidate_config_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_record(
                pathlib.Path(tmp),
                {"decision": "ACCEPTED"},
            )
            ok, err, rec = get_review_payload(str(path))
        self.assertFalse(ok)
        self.assertIn("candidate_config", err)

    def test_valid_accepted_record_returns_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_record(
                pathlib.Path(tmp),
                {
                    "decision": "ACCEPTED",
                    "candidate_config": {"POSITION_SIZE": 0.2},
                    "experiment_name": "test_exp",
                },
            )
            ok, err, rec = get_review_payload(str(path))
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertEqual(rec["experiment_name"], "test_exp")

    def test_corrupt_json_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "bad.json"
            path.write_text("not valid json {{")
            ok, err, rec = get_review_payload(str(path))
        self.assertFalse(ok)
        self.assertIn("Cannot read", err)


# ── TestSkipAndContinueAction ─────────────────────────────────────────────────

class TestSkipAndContinueAction(unittest.TestCase):

    def test_no_resumable_no_campaigns_returns_default_goal(self):
        action, target = skip_and_continue_action([], [])
        self.assertEqual(action, "start")
        self.assertEqual(target, "systematic strategy research")

    def test_with_resumable_returns_resume(self):
        resumable = [{"campaign_id": "c1"}, {"campaign_id": "c2"}]
        action, target = skip_and_continue_action(resumable, [])
        self.assertEqual(action, "resume")
        self.assertEqual(target, "c2")  # last one

    def test_no_resumable_with_campaigns_uses_newest_goal(self):
        # list_campaigns() returns newest-first; we want the first valid goal (newest)
        campaigns = [
            {"campaign_id": "c2", "goal": "reduce drawdown"},   # newest
            {"campaign_id": "c1", "goal": "improve filters"},   # older
        ]
        action, target = skip_and_continue_action([], campaigns)
        self.assertEqual(action, "start")
        self.assertEqual(target, "reduce drawdown")  # newest, index 0

    def test_empty_goals_fall_through_to_default(self):
        campaigns = [{"campaign_id": "c1", "goal": ""}, {"campaign_id": "c2"}]
        action, target = skip_and_continue_action([], campaigns)
        self.assertEqual(action, "start")
        self.assertEqual(target, "systematic strategy research")

    def test_resumable_takes_priority_over_campaigns(self):
        campaigns = [{"campaign_id": "c_old", "goal": "old goal"}]
        resumable = [{"campaign_id": "c_resume"}]
        action, target = skip_and_continue_action(resumable, campaigns)
        self.assertEqual(action, "resume")
        self.assertEqual(target, "c_resume")


# ── TestHoldAndResumeReview ───────────────────────────────────────────────────

class TestHoldAndResumeReview(unittest.TestCase):

    def _patch_state(self):
        """Patch save_state to avoid touching disk."""
        return patch("observability.agent_state.save_state")

    def test_hold_review_transitions_to_review_held(self):
        with self._patch_state():
            with patch("observability.agent_state.load_state") as mock_load:
                from observability.agent_state import AgentState
                mock_load.return_value = AgentState.default("mr_belfort", "trading_agent")
                with patch("observability.agent_state.save_state"):
                    result = hold_review("/some/path.json")
        self.assertEqual(result["status"], STATUS_REVIEW_HELD)

    def test_hold_review_preserves_record_path_in_stop_reason(self):
        with patch("observability.agent_state.load_state") as mock_load, \
             patch("observability.agent_state.save_state"):
            from observability.agent_state import AgentState
            mock_load.return_value = AgentState.default("mr_belfort", "trading_agent")
            result = hold_review("/some/record.json")
        self.assertIn("/some/record.json", result.get("stop_reason", ""))

    def test_resume_review_transitions_to_waiting_for_review(self):
        with patch("observability.agent_state.load_state") as mock_load, \
             patch("observability.agent_state.save_state"):
            from observability.agent_state import AgentState
            mock_load.return_value = AgentState.default("mr_belfort", "trading_agent")
            result = resume_review()
        self.assertEqual(result["status"], STATUS_WAITING_FOR_REVIEW)


# ── TestSkipReview ────────────────────────────────────────────────────────────

class TestSkipReview(unittest.TestCase):

    def _mock_state(self, initial_status="waiting_for_review"):
        from observability.agent_state import AgentState
        s = AgentState.default("mr_belfort", "trading_agent")
        s.status = initial_status
        s.stop_reason = "review_held:/some/record.json"
        return s

    def test_skip_review_transitions_to_idle(self):
        with patch("observability.agent_state.load_state") as mock_load, \
             patch("observability.agent_state.save_state"):
            mock_load.return_value = self._mock_state("waiting_for_review")
            result = skip_review("/some/record.json")
        self.assertEqual(result["status"], "idle")

    def test_skip_review_clears_stop_reason(self):
        with patch("observability.agent_state.load_state") as mock_load, \
             patch("observability.agent_state.save_state"):
            mock_load.return_value = self._mock_state("review_held")
            result = skip_review("/some/record.json")
        # stop_reason must be cleared so no stale review context remains
        self.assertIsNone(result.get("stop_reason"))

    def test_skip_review_records_last_action(self):
        with patch("observability.agent_state.load_state") as mock_load, \
             patch("observability.agent_state.save_state"):
            mock_load.return_value = self._mock_state("waiting_for_review")
            result = skip_review()
        self.assertIn("skipped", result.get("last_completed_action", "").lower())

    def test_skip_review_works_from_review_held_too(self):
        # Dismiss and Continue also calls skip_review from review_held
        with patch("observability.agent_state.load_state") as mock_load, \
             patch("observability.agent_state.save_state"):
            mock_load.return_value = self._mock_state("review_held")
            result = skip_review()
        self.assertEqual(result["status"], "idle")


# ── TestPromoteFromRecord ─────────────────────────────────────────────────────

class TestPromoteFromRecord(unittest.TestCase):
    """
    End-to-end tests for app.strategy.applier.promote_from_record().
    Uses a temp config + empty changelog to avoid side-effects.
    """

    def setUp(self):
        from app.strategy import config as _cfg_mod, changelog as _cl_mod
        # Patch config so we don't mutate real strategy_config.json
        self._real_get = _cfg_mod.get_config
        self._real_update = _cfg_mod.update
        self._cfg_store = {"POSITION_SIZE": 0.05, "TRADE_COOLDOWN": 30}
        _cfg_mod.get_config = lambda: dict(self._cfg_store)
        def _fake_update(d):
            self._cfg_store.update(d)
            return dict(self._cfg_store)
        _cfg_mod.update = _fake_update
        # Patch changelog to avoid writing to disk
        self._real_record = _cl_mod.record
        _cl_mod.record = lambda **kwargs: {"recorded": True, **kwargs}
        self._cfg_mod = _cfg_mod
        self._cl_mod = _cl_mod

    def tearDown(self):
        self._cfg_mod.get_config = self._real_get
        self._cfg_mod.update = self._real_update
        self._cl_mod.record = self._real_record

    def _write(self, tmp, data):
        path = pathlib.Path(tmp) / "record.json"
        path.write_text(json.dumps(data))
        return str(path)

    def test_valid_accepted_record_applies(self):
        from app.strategy.applier import promote_from_record
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "decision": "ACCEPTED",
                "candidate_config": {"POSITION_SIZE": 0.1},
                "experiment_name": "test_exp",
            })
            result = promote_from_record(path)
        self.assertTrue(result["applied"])
        self.assertIn("POSITION_SIZE", result["changed"])

    def test_rejected_record_raises(self):
        from app.strategy.applier import promote_from_record
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"decision": "REJECTED", "candidate_config": {"POSITION_SIZE": 0.1}})
            with self.assertRaises(ValueError) as ctx:
                promote_from_record(path)
        self.assertIn("REJECTED", str(ctx.exception))

    def test_missing_file_raises(self):
        from app.strategy.applier import promote_from_record
        with self.assertRaises(ValueError) as ctx:
            promote_from_record("/no/such/file.json")
        self.assertIn("not found", str(ctx.exception))

    def test_no_candidate_config_raises(self):
        from app.strategy.applier import promote_from_record
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"decision": "ACCEPTED"})
            with self.assertRaises(ValueError) as ctx:
                promote_from_record(path)
        self.assertIn("candidate_config", str(ctx.exception))

    def test_duplicate_apply_raises(self):
        from app.strategy.applier import promote_from_record
        # Config already matches the candidate
        self._cfg_store["POSITION_SIZE"] = 0.1
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "decision": "ACCEPTED",
                "candidate_config": {"POSITION_SIZE": 0.1},
            })
            with self.assertRaises(ValueError) as ctx:
                promote_from_record(path)
        self.assertIn("Duplicate", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
