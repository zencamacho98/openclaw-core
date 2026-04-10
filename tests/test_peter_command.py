"""
tests/test_peter_command.py

Unit tests for ui/peter_command.py.

Covers:
  - parse routing: all 7 new CommandTypes parse correctly
  - resume_review parses before generic resume (no RESUME_CAMPAIGN collision)
  - why / what is → STATUS; what happened / last → WHAT_LAST
  - Start Auto blocked in: running, stop_pending, waiting_for_review, review_held
  - Start Auto allowed when idle (calls start_campaign with auto_continue_goal)
  - Resume Safe picks resumable[0] (most recent, newest-first ordering)
  - Resume Safe blocked when no resumable campaigns
  - what happened last: reads from event_log + last_completed_action (not EXPLAIN_RESULT)
  - hold / resume_review blocked outside correct states
  - apply blocked without rec_path or when not in waiting_for_review
  - info command (status) routes through peter router, returns event_type=""
  - stop blocked when idle; cancel_stop blocked when no stop pending

Run with:
    python -m pytest tests/test_peter_command.py -v
    python -m unittest tests.test_peter_command -v
"""
from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import patch, MagicMock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from peter.commands import CommandType, parse_command
from peter.responses import Response
from ui.peter_command import execute_ui_command


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(
    text: str,
    *,
    all_campaigns=None,
    resumable=None,
    rec_path="",
    b_action_state="idle",
    last_completed_action="",
    apply_candidate_fn=None,
) -> dict:
    return execute_ui_command(
        text=text,
        all_campaigns=all_campaigns or [],
        resumable=resumable or [],
        rec_path=rec_path,
        b_action_state=b_action_state,
        last_completed_action=last_completed_action,
        apply_candidate_fn=apply_candidate_fn,
    )


# ── Parse routing ─────────────────────────────────────────────────────────────

class TestNewCommandTypeParsing(unittest.TestCase):

    def test_parse_start_auto(self):
        for text in ("start", "start auto", "start auto research", "go", "START AUTO"):
            with self.subTest(text=text):
                self.assertEqual(parse_command(text).type, CommandType.START_AUTO)

    def test_parse_stop_campaign(self):
        for text in ("stop", "stop after session", "halt", "STOP"):
            with self.subTest(text=text):
                self.assertEqual(parse_command(text).type, CommandType.STOP_CAMPAIGN)

    def test_parse_cancel_stop(self):
        for text in ("cancel stop", "keep going"):
            with self.subTest(text=text):
                self.assertEqual(parse_command(text).type, CommandType.CANCEL_STOP)

    def test_parse_hold_review(self):
        for text in ("hold", "hold review", "defer"):
            with self.subTest(text=text):
                self.assertEqual(parse_command(text).type, CommandType.HOLD_REVIEW)

    def test_parse_resume_review_not_resume_campaign(self):
        """'resume review' must parse as RESUME_REVIEW, not RESUME_CAMPAIGN."""
        self.assertEqual(parse_command("resume review").type, CommandType.RESUME_REVIEW)
        self.assertEqual(parse_command("resume review please").type, CommandType.RESUME_REVIEW)
        # Verify existing RESUME_CAMPAIGN rules still work
        self.assertEqual(parse_command("resume campaign c123").type, CommandType.RESUME_CAMPAIGN)
        self.assertEqual(parse_command("resume").type, CommandType.RESUME_CAMPAIGN)

    def test_parse_apply_and_continue(self):
        for text in ("apply", "apply and continue", "APPLY"):
            with self.subTest(text=text):
                self.assertEqual(parse_command(text).type, CommandType.APPLY_AND_CONTINUE)

    def test_parse_what_last(self):
        for text in ("what happened last", "what happened", "last"):
            with self.subTest(text=text):
                self.assertEqual(parse_command(text).type, CommandType.WHAT_LAST)

    def test_parse_why_maps_to_status(self):
        """'why' and 'what is' redirect to STATUS — reuses the existing handler."""
        for text in ("why", "why did belfort stop", "what is belfort doing"):
            with self.subTest(text=text):
                self.assertEqual(parse_command(text).type, CommandType.STATUS)

    def test_existing_commands_unaffected(self):
        """Existing command types must still parse correctly after new rules are added."""
        self.assertEqual(parse_command("status").type,           CommandType.STATUS)
        self.assertEqual(parse_command("best candidate").type,   CommandType.BEST_CANDIDATE)
        self.assertEqual(parse_command("review-worthy").type,    CommandType.LIST_REVIEW_WORTHY)
        self.assertEqual(parse_command("promote").type,          CommandType.PROMOTE_GUIDANCE)
        self.assertEqual(parse_command("help").type,             CommandType.HELP)
        self.assertEqual(parse_command("xyzzy").type,            CommandType.UNKNOWN)


# ── Start Auto — blocked states ───────────────────────────────────────────────

class TestStartAutoBlocking(unittest.TestCase):

    def test_blocked_when_running(self):
        r = _run("start", b_action_state="running")
        self.assertFalse(r["ok"])
        self.assertIn("already running", r["message"])
        self.assertEqual(r["event_type"], "")  # no event logged for blocked commands

    def test_blocked_when_stop_pending(self):
        r = _run("start", b_action_state="stop_pending")
        self.assertFalse(r["ok"])
        self.assertIn("stop signal", r["message"].lower())

    def test_blocked_when_waiting_for_review(self):
        r = _run("start", b_action_state="waiting_for_review")
        self.assertFalse(r["ok"])
        self.assertIn("review", r["message"].lower())

    def test_blocked_when_review_held(self):
        r = _run("start", b_action_state="review_held")
        self.assertFalse(r["ok"])
        self.assertIn("deferred", r["message"].lower())

    def test_allowed_when_idle_calls_start_campaign(self):
        campaigns = [{"campaign_id": "c1", "goal": "reduce drawdown"}]
        with patch("ui.peter_command.start_campaign") as mock_start:
            mock_start.return_value = {"ok": True, "message": "Campaign started (PID 99)."}
            r = _run("start", all_campaigns=campaigns, b_action_state="idle")
        self.assertTrue(r["ok"])
        mock_start.assert_called_once_with(goal="reduce drawdown")
        self.assertEqual(r["event_type"], "campaign_started")
        self.assertEqual(r["severity"],   "important")
        self.assertTrue(r["extra"].get("auto"))

    def test_allowed_when_idle_with_resumable_but_start_typed(self):
        """idle_with_resumable + 'start' command → still starts, not blocked."""
        with patch("ui.peter_command.start_campaign") as mock_start:
            mock_start.return_value = {"ok": True, "message": "Started."}
            r = _run(
                "start",
                all_campaigns=[{"goal": "test goal"}],
                resumable=[{"campaign_id": "c1"}],
                b_action_state="idle_with_resumable",
            )
        self.assertTrue(r["ok"])
        mock_start.assert_called_once()

    def test_start_failure_returns_ok_false_with_event(self):
        with patch("ui.peter_command.start_campaign") as mock_start:
            mock_start.return_value = {"ok": False, "message": "Already running."}
            r = _run("start", all_campaigns=[], b_action_state="idle")
        self.assertFalse(r["ok"])
        self.assertEqual(r["event_type"], "campaign_start_failed")


# ── Resume Safe — ordering ────────────────────────────────────────────────────

class TestResumeSafeOrdering(unittest.TestCase):

    def test_uses_most_recent_resumable_index_0(self):
        """
        resumable is newest-first (sorted by created_at desc in list_campaigns()).
        The most recent interrupted campaign is at index 0, NOT index -1.
        """
        resumable = [
            {"campaign_id": "c_newest", "created_at": "2026-04-10T12:00:00"},
            {"campaign_id": "c_middle", "created_at": "2026-04-09T12:00:00"},
            {"campaign_id": "c_oldest", "created_at": "2026-04-08T12:00:00"},
        ]
        with patch("ui.peter_command.resume_campaign") as mock_resume:
            mock_resume.return_value = {"ok": True, "message": "Resuming c_newest."}
            r = _run(
                "resume",
                resumable=resumable,
                b_action_state="idle_with_resumable",
            )
        # Must call with index 0 (newest), not index -1 (oldest)
        mock_resume.assert_called_once_with("c_newest")
        self.assertTrue(r["ok"])
        self.assertEqual(r["event_type"], "campaign_resumed")

    def test_blocked_when_no_resumable(self):
        r = _run("resume", resumable=[], b_action_state="idle")
        self.assertFalse(r["ok"])
        self.assertIn("No interrupted campaigns", r["message"])

    def test_explicit_id_overrides_auto_pick(self):
        """'resume campaign c_specific' uses the provided ID, not resumable[0]."""
        resumable = [{"campaign_id": "c_auto", "created_at": "2026-04-10"}]
        with patch("ui.peter_command.resume_campaign") as mock_resume:
            mock_resume.return_value = {"ok": True, "message": "OK."}
            _run(
                "resume campaign c_specific",
                resumable=resumable,
                b_action_state="idle_with_resumable",
            )
        mock_resume.assert_called_once_with("c_specific")


# ── What happened last ────────────────────────────────────────────────────────

class TestWhatLast(unittest.TestCase):

    def test_shows_last_completed_action(self):
        with patch("ui.peter_command._read_events", return_value=[]):
            r = _run(
                "what happened last",
                last_completed_action="Applied exp123 · started next run",
            )
        self.assertTrue(r["ok"])
        self.assertIn("Applied exp123", r["message"])
        self.assertEqual(r["event_type"], "")  # info command — no event logged

    def test_shows_recent_events_from_event_log(self):
        """Sourced from event_log, not from peter.handlers.handle_explain_result."""
        mock_events = [
            {"event_type": "campaign_started",            "summary": "Campaign started — reduce drawdown"},
            {"event_type": "candidate_applied_and_continued", "summary": "Applied exp99 · started next run"},
        ]
        with patch("ui.peter_command._read_events", return_value=mock_events):
            r = _run("last")
        self.assertTrue(r["ok"])
        self.assertIn("campaign started", r["message"])
        self.assertIn("Applied exp99", r["message"])

    def test_no_activity_returns_graceful_message(self):
        with patch("ui.peter_command._read_events", return_value=[]):
            r = _run("what happened", last_completed_action="")
        self.assertTrue(r["ok"])
        self.assertIn("No recent activity", r["message"])

    def test_does_not_route_through_explain_result(self):
        """WHAT_LAST must never call the peter router's EXPLAIN_RESULT handler."""
        with patch("ui.peter_command.route") as mock_route, \
             patch("ui.peter_command._read_events", return_value=[]):
            _run("what happened last", last_completed_action="test action")
        mock_route.assert_not_called()


# ── Hold / Resume review ──────────────────────────────────────────────────────

class TestHoldAndResumeReview(unittest.TestCase):

    def test_hold_blocked_outside_waiting_for_review(self):
        for state in ("idle", "running", "review_held"):
            with self.subTest(state=state):
                r = _run("hold", b_action_state=state)
                self.assertFalse(r["ok"])

    def test_hold_succeeds_in_waiting_for_review(self):
        with patch("ui.peter_command.hold_review") as mock_hold:
            r = _run("hold", rec_path="/data/val.json", b_action_state="waiting_for_review")
        mock_hold.assert_called_once_with("/data/val.json")
        self.assertTrue(r["ok"])
        self.assertEqual(r["event_type"], "review_held")
        self.assertEqual(r["severity"],   "action_needed")

    def test_resume_review_blocked_outside_review_held(self):
        for state in ("idle", "running", "waiting_for_review"):
            with self.subTest(state=state):
                r = _run("resume review", b_action_state=state)
                self.assertFalse(r["ok"])

    def test_resume_review_succeeds_in_review_held(self):
        with patch("ui.peter_command.resume_review") as mock_resume:
            r = _run("resume review", rec_path="/data/val.json", b_action_state="review_held")
        mock_resume.assert_called_once_with("/data/val.json")
        self.assertTrue(r["ok"])
        self.assertEqual(r["event_type"], "review_resumed")


# ── Apply and continue ────────────────────────────────────────────────────────

class TestApplyAndContinue(unittest.TestCase):

    def test_blocked_without_rec_path(self):
        r = _run("apply", rec_path="", b_action_state="waiting_for_review")
        self.assertFalse(r["ok"])
        self.assertIn("No candidate record", r["message"])

    def test_blocked_when_not_in_review(self):
        r = _run("apply", rec_path="/data/val.json", b_action_state="idle")
        self.assertFalse(r["ok"])
        self.assertIn("waiting for review", r["message"].lower())

    def test_blocked_without_apply_fn(self):
        r = _run(
            "apply",
            rec_path="/data/val.json",
            b_action_state="waiting_for_review",
            apply_candidate_fn=None,
        )
        self.assertFalse(r["ok"])
        self.assertIn("Apply function not available", r["message"])

    def test_success_with_resumable_uses_index_0(self):
        """After applying, resume the most recent resumable (index 0)."""
        resumable = [
            {"campaign_id": "c_newest"},
            {"campaign_id": "c_older"},
        ]
        apply_fn = MagicMock(return_value={"experiment_name": "exp42"})
        with patch("ui.peter_command.resume_campaign") as mock_resume:
            mock_resume.return_value = {"ok": True, "message": "Resuming c_newest."}
            r = _run(
                "apply",
                resumable=resumable,
                rec_path="/data/val.json",
                b_action_state="waiting_for_review",
                apply_candidate_fn=apply_fn,
            )
        apply_fn.assert_called_once_with("/data/val.json")
        mock_resume.assert_called_once_with("c_newest")
        self.assertTrue(r["ok"])
        self.assertIn("exp42", r["message"])
        self.assertEqual(r["event_type"], "candidate_applied_and_continued")

    def test_success_with_no_resumable_starts_new(self):
        """When no resumable campaigns exist, start fresh with auto_continue_goal."""
        apply_fn = MagicMock(return_value={"experiment_name": "exp77"})
        campaigns = [{"goal": "improve filters"}]
        with patch("ui.peter_command.start_campaign") as mock_start:
            mock_start.return_value = {"ok": True, "message": "Started."}
            r = _run(
                "apply",
                all_campaigns=campaigns,
                resumable=[],
                rec_path="/data/val.json",
                b_action_state="waiting_for_review",
                apply_candidate_fn=apply_fn,
            )
        mock_start.assert_called_once_with(goal="improve filters")
        self.assertTrue(r["ok"])
        self.assertIn("exp77", r["message"])


# ── Info commands route through router ────────────────────────────────────────

class TestInfoCommandRouting(unittest.TestCase):

    def test_status_routes_through_router_not_local(self):
        mock_resp = Response(command_type="status", ok=True, summary="Mr Belfort is idle.")
        with patch("ui.peter_command.route", return_value=mock_resp) as mock_route:
            r = _run("status", b_action_state="idle")
        mock_route.assert_called_once()
        self.assertTrue(r["ok"])
        self.assertEqual(r["event_type"], "")  # info commands never log events

    def test_stop_blocked_when_idle(self):
        r = _run("stop", b_action_state="idle")
        self.assertFalse(r["ok"])
        self.assertIn("No campaign is currently running", r["message"])

    def test_cancel_stop_blocked_when_no_stop_pending(self):
        r = _run("cancel stop", b_action_state="running")
        self.assertFalse(r["ok"])
        self.assertIn("No stop signal", r["message"])

    def test_stop_succeeds_when_running(self):
        with patch("ui.peter_command.request_stop") as mock_stop:
            mock_stop.return_value = {"ok": True, "message": "Stop signal sent."}
            r = _run("stop", b_action_state="running")
        mock_stop.assert_called_once()
        self.assertTrue(r["ok"])
        self.assertEqual(r["event_type"], "stop_requested")

    def test_cancel_stop_succeeds_when_stop_pending(self):
        with patch("ui.peter_command.cancel_stop_signal") as mock_cancel:
            mock_cancel.return_value = {"ok": True, "message": "Stop signal cancelled."}
            r = _run("cancel stop", b_action_state="stop_pending")
        mock_cancel.assert_called_once()
        self.assertTrue(r["ok"])
        self.assertEqual(r["event_type"], "stop_cancelled")
        self.assertEqual(r["severity"],   "routine")

    def test_empty_command_returns_ok_false(self):
        r = _run("", b_action_state="idle")
        self.assertFalse(r["ok"])


# ── Approve top — real apply path ─────────────────────────────────────────────

_PENDING_ITEM = {
    "queue_id":      "cq_test_001",
    "status":        "pending",
    "experiment_id": "exp_abc",
    "title":         "Test candidate",
    "record_path":   "/data/val/exp_abc.json",
    "campaign_id":   "camp_x",
    "tier":          "strong",
    "score":         85.0,
}

_PROMOTE_RESULT = {
    "applied":         True,
    "experiment_name": "exp_abc",
    "changed":         {"POSITION_SIZE": {"old": 0.05, "new": 0.10}},
    "record_path":     "/data/val/exp_abc.json",
    "new_config":      {"POSITION_SIZE": 0.10},
}


class TestApproveTop(unittest.TestCase):
    """approve top must execute the real apply path, not just print a command."""

    # ── helpers ───────────────────────────────────────────────────────────────

    def _run_approve(self, *, pending=None, promote_side_effect=None, promote_return=None):
        """
        Run 'approve top' with mocked queue + applier.
        pending: list returned by pending_candidates (default: [_PENDING_ITEM])
        promote_side_effect: exception to raise from promote_from_record (simulates failure)
        promote_return: dict returned by promote_from_record (simulates success)
        """
        pending_list = pending if pending is not None else [dict(_PENDING_ITEM)]
        promote_rv   = promote_return if promote_return is not None else dict(_PROMOTE_RESULT)

        with patch("research.candidate_queue.pending_candidates", return_value=pending_list), \
             patch("research.candidate_queue.get_queue_item"), \
             patch("research.candidate_queue.update_queue_item") as mock_update, \
             patch("observability.event_log.append_event") as mock_event, \
             patch("app.strategy.applier.promote_from_record",
                   side_effect=promote_side_effect,
                   return_value=None if promote_side_effect else promote_rv) as mock_promote:
            # "approve" (no argument) → approve the top pending candidate via pending_candidates()
            r = _run("approve", b_action_state="idle")
        return r, mock_update, mock_event, mock_promote

    # ── success ───────────────────────────────────────────────────────────────

    def test_approve_top_calls_promote_from_record(self):
        r, _, _, mock_promote = self._run_approve()
        mock_promote.assert_called_once_with(
            "/data/val/exp_abc.json",
            reason="Approved by ui",
        )

    def test_approve_top_success_updates_queue_to_approved(self):
        r, mock_update, _, _ = self._run_approve()
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args
        # First positional arg is queue_id
        self.assertEqual(call_kwargs.args[0], "cq_test_001")
        kw = call_kwargs.kwargs
        self.assertEqual(kw["status"], "approved")
        self.assertIn("resolved_at", kw)
        self.assertIn("applied", kw["resolution"])

    def test_approve_top_success_emits_candidate_approved_event(self):
        r, _, mock_event, _ = self._run_approve()
        mock_event.assert_called_once()
        event_type = mock_event.call_args.args[0]
        self.assertEqual(event_type, "candidate_approved")

    def test_approve_top_success_returns_ok_true(self):
        r, _, _, _ = self._run_approve()
        self.assertTrue(r["ok"])
        self.assertEqual(r["event_type"], "candidate_approved")
        self.assertEqual(r["severity"], "important")
        self.assertEqual(r["command_type"], "approve_candidate")

    def test_approve_top_success_message_mentions_applied(self):
        r, _, _, _ = self._run_approve()
        self.assertIn("Applied", r["message"])
        self.assertIn("exp_abc", r["message"])

    def test_approve_top_success_extra_contains_changed(self):
        r, _, _, _ = self._run_approve()
        self.assertIn("changed", r["extra"])
        self.assertIn("POSITION_SIZE", r["extra"]["changed"])

    def test_approve_top_success_message_does_not_mention_promote_command(self):
        """Success message must confirm apply happened, not tell operator to run a command."""
        r, _, _, _ = self._run_approve()
        self.assertNotIn("promote_candidate.py", r["message"])
        self.assertNotIn("To apply:", r["message"])

    # ── failure: apply raises ─────────────────────────────────────────────────

    def test_approve_top_apply_failure_returns_ok_false(self):
        r, _, _, _ = self._run_approve(promote_side_effect=ValueError("Duplicate apply"))
        self.assertFalse(r["ok"])
        self.assertIn("Apply failed", r["message"])

    def test_approve_top_apply_failure_does_not_update_queue(self):
        """Queue must stay untouched when apply raises — item remains pending/held."""
        r, mock_update, _, _ = self._run_approve(promote_side_effect=ValueError("boom"))
        mock_update.assert_not_called()

    def test_approve_top_apply_failure_does_not_emit_event(self):
        r, _, mock_event, _ = self._run_approve(promote_side_effect=RuntimeError("network"))
        mock_event.assert_not_called()

    # ── edge: no pending candidates ───────────────────────────────────────────

    def test_approve_top_blocked_when_no_pending(self):
        r, mock_update, mock_event, mock_promote = self._run_approve(pending=[])
        self.assertFalse(r["ok"])
        self.assertIn("No pending", r["message"])
        mock_promote.assert_not_called()
        mock_update.assert_not_called()

    # ── edge: missing record_path ─────────────────────────────────────────────

    def test_approve_top_error_when_no_record_path(self):
        item_no_path = dict(_PENDING_ITEM)
        item_no_path.pop("record_path")
        r, mock_update, mock_event, mock_promote = self._run_approve(pending=[item_no_path])
        self.assertFalse(r["ok"])
        self.assertIn("record_path", r["message"])
        mock_promote.assert_not_called()
        mock_update.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
