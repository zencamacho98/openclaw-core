"""
tests/test_peter_helpers.py

Tests for ui/peter_helpers.belfort_action_state().

Covers the 5 operator control states:
  - idle with no resumable campaign
  - idle with resumable campaign(s)
  - running (all three active statuses)
  - stop pending (overrides running, idle, and waiting_for_review)
  - waiting_for_review

Run with:
    python -m pytest tests/test_peter_helpers.py -v
    python -m unittest tests.test_peter_helpers -v
"""
from __future__ import annotations

import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from ui.peter_helpers import belfort_action_state, peter_intervention_state, auto_continue_goal, loop_explanation_text


class TestBelfortActionState(unittest.TestCase):

    # ── idle — no resumable ───────────────────────────────────────────────────

    def test_idle_no_resumable(self):
        self.assertEqual(
            belfort_action_state("idle", stop_pending=False, resumable=[]),
            "idle",
        )

    def test_unknown_status_no_resumable(self):
        # Any unrecognised status falls through to idle
        self.assertEqual(
            belfort_action_state("unknown", stop_pending=False, resumable=[]),
            "idle",
        )

    def test_paused_by_budget_no_resumable(self):
        self.assertEqual(
            belfort_action_state("paused_by_budget", stop_pending=False, resumable=[]),
            "idle",
        )

    def test_stopped_by_guardrail_no_resumable(self):
        self.assertEqual(
            belfort_action_state("stopped_by_guardrail", stop_pending=False, resumable=[]),
            "idle",
        )

    # ── idle_with_resumable ───────────────────────────────────────────────────

    def test_idle_with_resumable(self):
        self.assertEqual(
            belfort_action_state("idle", stop_pending=False, resumable=[{"campaign_id": "c1"}]),
            "idle_with_resumable",
        )

    def test_paused_with_resumable(self):
        # Non-active status + resumable campaigns → idle_with_resumable
        self.assertEqual(
            belfort_action_state("paused_by_budget", stop_pending=False, resumable=[{"campaign_id": "c1"}]),
            "idle_with_resumable",
        )

    def test_multiple_resumable(self):
        resumable = [{"campaign_id": "c1"}, {"campaign_id": "c2"}]
        self.assertEqual(
            belfort_action_state("idle", stop_pending=False, resumable=resumable),
            "idle_with_resumable",
        )

    # ── running ───────────────────────────────────────────────────────────────

    def test_running_campaign(self):
        self.assertEqual(
            belfort_action_state("running_campaign", stop_pending=False, resumable=[]),
            "running",
        )

    def test_running_session(self):
        self.assertEqual(
            belfort_action_state("running_session", stop_pending=False, resumable=[]),
            "running",
        )

    def test_running_batch(self):
        self.assertEqual(
            belfort_action_state("running_batch", stop_pending=False, resumable=[]),
            "running",
        )

    def test_running_ignores_resumable_list(self):
        # Resumable list is irrelevant when actively running
        self.assertEqual(
            belfort_action_state("running_campaign", stop_pending=False, resumable=[{"campaign_id": "c1"}]),
            "running",
        )

    # ── stop_pending ──────────────────────────────────────────────────────────

    def test_stop_pending_while_running_campaign(self):
        self.assertEqual(
            belfort_action_state("running_campaign", stop_pending=True, resumable=[]),
            "stop_pending",
        )

    def test_stop_pending_overrides_all_active_statuses(self):
        for status in ("running_campaign", "running_session", "running_batch"):
            with self.subTest(status=status):
                self.assertEqual(
                    belfort_action_state(status, stop_pending=True, resumable=[]),
                    "stop_pending",
                )

    def test_stop_pending_overrides_idle(self):
        # Edge case: signal written but status not yet updated
        self.assertEqual(
            belfort_action_state("idle", stop_pending=True, resumable=[]),
            "stop_pending",
        )

    def test_stop_pending_overrides_waiting_for_review(self):
        self.assertEqual(
            belfort_action_state("waiting_for_review", stop_pending=True, resumable=[]),
            "stop_pending",
        )

    def test_stop_pending_overrides_idle_with_resumable(self):
        self.assertEqual(
            belfort_action_state("idle", stop_pending=True, resumable=[{"campaign_id": "c1"}]),
            "stop_pending",
        )

    # ── waiting_for_review ────────────────────────────────────────────────────

    def test_waiting_for_review(self):
        self.assertEqual(
            belfort_action_state("waiting_for_review", stop_pending=False, resumable=[]),
            "waiting_for_review",
        )

    def test_waiting_for_review_ignores_resumable(self):
        # Review state takes priority over idle_with_resumable
        self.assertEqual(
            belfort_action_state("waiting_for_review", stop_pending=False, resumable=[{"campaign_id": "c1"}]),
            "waiting_for_review",
        )


# ── TestPeterInterventionState ────────────────────────────────────────────────

class TestPeterInterventionState(unittest.TestCase):

    def test_waiting_for_review_is_review_needed(self):
        self.assertEqual(
            peter_intervention_state("waiting_for_review", stop_pending=False, resumable=[]),
            "review_needed",
        )

    def test_review_held_is_review_held(self):
        self.assertEqual(
            peter_intervention_state("review_held", stop_pending=False, resumable=[]),
            "review_held",
        )

    def test_review_needed_takes_priority_over_stop_pending(self):
        # waiting_for_review is highest priority — operator must act on candidate
        self.assertEqual(
            peter_intervention_state("waiting_for_review", stop_pending=True, resumable=[]),
            "review_needed",
        )

    def test_review_held_takes_priority_over_stop_pending(self):
        self.assertEqual(
            peter_intervention_state("review_held", stop_pending=True, resumable=[]),
            "review_held",
        )

    def test_stop_pending_overrides_active_statuses(self):
        for status in ("running_campaign", "running_session", "running_batch"):
            with self.subTest(status=status):
                self.assertEqual(
                    peter_intervention_state(status, stop_pending=True, resumable=[]),
                    "stop_pending",
                )

    def test_active_status_is_running(self):
        for status in ("running_campaign", "running_session", "running_batch"):
            with self.subTest(status=status):
                self.assertEqual(
                    peter_intervention_state(status, stop_pending=False, resumable=[]),
                    "running",
                )

    def test_stopped_hard_by_guardrail(self):
        self.assertEqual(
            peter_intervention_state("stopped_by_guardrail", stop_pending=False, resumable=[]),
            "stopped_hard",
        )

    def test_stopped_hard_by_budget(self):
        self.assertEqual(
            peter_intervention_state("paused_by_budget", stop_pending=False, resumable=[]),
            "stopped_hard",
        )

    def test_idle_with_resumable_is_resumable(self):
        self.assertEqual(
            peter_intervention_state("idle", stop_pending=False, resumable=[{"campaign_id": "c1"}]),
            "resumable",
        )

    def test_idle_no_resumable_is_ready(self):
        self.assertEqual(
            peter_intervention_state("idle", stop_pending=False, resumable=[]),
            "ready",
        )

    def test_unknown_status_no_resumable_is_ready(self):
        self.assertEqual(
            peter_intervention_state("unknown_status", stop_pending=False, resumable=[]),
            "ready",
        )


# ── TestAutoContinueGoal ──────────────────────────────────────────────────────

class TestAutoContinueGoal(unittest.TestCase):

    def test_empty_list_returns_default(self):
        self.assertEqual(auto_continue_goal([]), "systematic strategy research")

    def test_picks_newest_valid_goal(self):
        # list_campaigns() is newest-first; we expect the first valid goal
        campaigns = [
            {"campaign_id": "c2", "goal": "reduce drawdown"},   # newest
            {"campaign_id": "c1", "goal": "improve filters"},   # older
        ]
        self.assertEqual(auto_continue_goal(campaigns), "reduce drawdown")

    def test_skips_empty_goal_entries(self):
        campaigns = [
            {"campaign_id": "c3", "goal": ""},
            {"campaign_id": "c2", "goal": "   "},
            {"campaign_id": "c1", "goal": "improve entry quality"},
        ]
        self.assertEqual(auto_continue_goal(campaigns), "improve entry quality")

    def test_research_goal_field_also_works(self):
        campaigns = [{"campaign_id": "c1", "research_goal": "tune stop loss"}]
        self.assertEqual(auto_continue_goal(campaigns), "tune stop loss")

    def test_all_empty_returns_default(self):
        campaigns = [{"campaign_id": "c1"}, {"campaign_id": "c2", "goal": ""}]
        self.assertEqual(auto_continue_goal(campaigns), "systematic strategy research")


# ── TestLoopExplanationText ────────────────────────────────────────────────────

class TestLoopExplanationText(unittest.TestCase):
    """loop_explanation_text() returns correct status_line and how_it_works text."""

    _BASE_SUP = {"enabled": False, "stop_requested": False, "cycle_count": 0}
    _BASE_CAMP = {
        "config": {"max_sessions": 3, "max_batches_per_session": 3, "experiments_per_batch": 3},
        "progress": {"sessions_completed": 0, "total_experiments": 0},
    }

    def _run(self, sup=None, camp=None, **kwargs):
        s = {**self._BASE_SUP, **(sup or {})}
        c = camp  # None is valid (no active campaign)
        return loop_explanation_text(s, c, **kwargs)

    # ── status_line states ────────────────────────────────────────────────────

    def test_disabled_status_line(self):
        r = self._run(sup={"enabled": False, "cycle_count": 4})
        self.assertIn("Off", r["status_line"])
        self.assertIn("4", r["status_line"])

    def test_enabled_status_line_says_active(self):
        r = self._run(
            sup={"enabled": True, "stop_requested": False, "cycle_count": 2},
            camp={
                **self._BASE_CAMP,
                "progress": {"sessions_completed": 1, "total_experiments": 9},
            },
        )
        self.assertIn("Active", r["status_line"])
        # cycle count displayed as cycle_count + 1 (cycle in progress)
        self.assertIn("3", r["status_line"])

    def test_stop_requested_status_line(self):
        r = self._run(sup={"enabled": True, "stop_requested": True, "cycle_count": 5})
        self.assertIn("Stopping", r["status_line"])
        self.assertIn("5", r["status_line"])

    def test_status_line_includes_session_progress_when_running(self):
        r = self._run(
            sup={"enabled": True, "stop_requested": False, "cycle_count": 0},
            camp={
                **self._BASE_CAMP,
                "progress": {"sessions_completed": 2, "total_experiments": 18},
            },
        )
        self.assertIn("2", r["status_line"])   # sessions done
        self.assertIn("18", r["status_line"])  # experiments done

    # ── how_it_works — actual config numbers ──────────────────────────────────

    def test_how_it_works_uses_actual_session_count(self):
        r = self._run(camp={
            "config": {"max_sessions": 5, "max_batches_per_session": 2, "experiments_per_batch": 4},
            "progress": {},
        })
        self.assertIn("5", r["how_it_works"])   # max_sessions
        self.assertIn("2", r["how_it_works"])   # batches
        self.assertIn("4", r["how_it_works"])   # experiments per batch
        self.assertIn("40", r["how_it_works"])  # total = 5 × 2 × 4

    def test_how_it_works_falls_back_to_defaults_when_no_camp(self):
        r = self._run(camp=None, default_sessions=3, default_batches=3, default_exp=3)
        self.assertIn("3", r["how_it_works"])
        self.assertIn("27", r["how_it_works"])  # 3 × 3 × 3

    def test_how_it_works_mentions_human_control(self):
        r = self._run()
        text = r["how_it_works"].lower()
        # Should explain why cycles are bounded
        self.assertTrue(
            "control" in text or "approve" in text or "review" in text,
            f"Expected mention of human control in: {text}",
        )

    # ── return shape ──────────────────────────────────────────────────────────

    def test_returns_dict_with_required_keys(self):
        r = self._run()
        self.assertIn("status_line", r)
        self.assertIn("how_it_works", r)
        self.assertIsInstance(r["status_line"], str)
        self.assertIsInstance(r["how_it_works"], str)
        self.assertTrue(r["status_line"])
        self.assertTrue(r["how_it_works"])


if __name__ == "__main__":
    unittest.main()
