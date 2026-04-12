# tests/test_peter_fl_lifecycle_nl.py
#
# Tests for Peter's conversational Frank Lloyd lifecycle handling.
#
# Coverage:
#   TestFLStatusQueryParse     — "what is Frank Lloyd doing/waiting on/blocked on" → FL_LIFECYCLE_NL
#   TestFLLifecycleParse       — approve/reject/authorize/draft/promote/discard NL phrases
#   TestFLParsePreservation    — structured commands still route to their original types
#   TestFLReasonExtraction     — reason extracted from NL text
#   TestFLBuildResolution      — _fl_resolve_actionable_build returns correct build
#   TestFLHandlerApprove       — approve handler: success, nothing-to-do
#   TestFLHandlerReject        — reject: clarification when no reason, success
#   TestFLHandlerAuthorize     — authorize_stage2 handler
#   TestFLHandlerDraft         — draft handler
#   TestFLHandlerPromote       — promote: clarification when no path, success
#   TestFLHandlerDiscard       — discard handler
#   TestFLHandlerStatusQuery   — status_query handler response format
#   TestFLRouterDispatch       — FL_LIFECYCLE_NL in dispatch table

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from peter.commands import CommandType, parse_command
from peter.handlers import (
    handle_fl_lifecycle_nl,
    _fl_resolve_actionable_build,
    _fl_build_statuses,
    _FL_BUILD_LOG,
)
from peter.router import _DISPATCH


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cmd(args: dict):
    from peter.commands import Command
    return Command(
        type        = CommandType.FL_LIFECYCLE_NL,
        args        = args,
        transport   = "cli",
        operator_id = "test",
        raw_text    = "",
    )


def _full_args(action: str, build_id: str = "", notes: str = "",
               reason: str = "", target_path: str = "") -> dict:
    return {"action": action, "build_id": build_id, "notes": notes,
            "reason": reason, "target_path": target_path}


def _write_log(log_path: pathlib.Path, events: list[dict]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")


def _ev(build_id: str, event: str, ts: str = "2026-04-11T00:00:00+00:00") -> dict:
    return {"timestamp": ts, "build_id": build_id, "event": event, "notes": "", "extra": {}}


# ── TestFLStatusQueryParse ───────────────────────────────────────────────────

class TestFLStatusQueryParse(unittest.TestCase):
    """Natural-language status queries route to FL_LIFECYCLE_NL(action=status_query)."""

    def _assert_sq(self, text: str):
        cmd = parse_command(text)
        self.assertEqual(cmd.type, CommandType.FL_LIFECYCLE_NL, f"Expected FL_LIFECYCLE_NL for: {text!r}")
        self.assertEqual(cmd.args["action"], "status_query", f"Expected status_query action for: {text!r}")

    def test_what_is_frank_lloyd_doing(self):
        self._assert_sq("What is Frank Lloyd doing?")

    def test_what_is_frank_lloyd_working_on(self):
        self._assert_sq("What is Frank Lloyd working on?")

    def test_what_is_frank_lloyd_waiting_on(self):
        self._assert_sq("What is Frank Lloyd waiting on?")

    def test_what_is_frank_lloyd_blocked_on(self):
        self._assert_sq("What is Frank Lloyd blocked on?")

    def test_what_is_frank_lloyd_ready_for(self):
        self._assert_sq("What is Frank Lloyd ready for?")

    def test_whats_frank_lloyd_doing(self):
        self._assert_sq("What's Frank Lloyd doing?")

    def test_where_is_frank_lloyd(self):
        self._assert_sq("Where is Frank Lloyd at?")

    def test_frank_lloyd_status(self):
        self._assert_sq("frank lloyd status")

    def test_how_is_frank_lloyd_doing(self):
        self._assert_sq("How is Frank Lloyd doing?")


# ── TestFLLifecycleParse ─────────────────────────────────────────────────────

class TestFLLifecycleParse(unittest.TestCase):
    """NL lifecycle phrases route to FL_LIFECYCLE_NL with correct action."""

    def _parse(self, text: str):
        return parse_command(text)

    def _assert_action(self, text: str, expected_action: str):
        cmd = self._parse(text)
        self.assertEqual(cmd.type, CommandType.FL_LIFECYCLE_NL, f"Expected FL_LIFECYCLE_NL for: {text!r}")
        self.assertEqual(cmd.args["action"], expected_action, f"Expected action={expected_action!r} for: {text!r}")

    # Approve
    def test_approve_that_frank_lloyd_build(self):
        self._assert_action("Approve that Frank Lloyd build", "approve")

    def test_approve_the_spec(self):
        self._assert_action("approve the spec", "approve")

    def test_go_ahead_and_approve(self):
        self._assert_action("go ahead and approve", "approve")

    def test_approve_that_build(self):
        self._assert_action("approve that build", "approve")

    def test_approve_the_frank_lloyd_spec(self):
        self._assert_action("approve the Frank Lloyd spec", "approve")

    # Reject
    def test_reject_that_frank_lloyd_build(self):
        self._assert_action("Reject that Frank Lloyd build because it touches the wrong files", "reject")

    def test_reject_the_spec(self):
        self._assert_action("reject the spec — the description is too vague", "reject")

    def test_reject_that_spec(self):
        self._assert_action("reject that spec", "reject")

    # Authorize Stage 2
    def test_let_frank_lloyd_move_to_stage2(self):
        self._assert_action("Let Frank Lloyd move that one into Stage 2", "authorize_stage2")

    def test_authorize_stage_2(self):
        self._assert_action("authorize Stage 2 for that one", "authorize_stage2")

    def test_greenlight_stage2(self):
        self._assert_action("greenlight Stage 2", "authorize_stage2")

    def test_move_into_stage2(self):
        self._assert_action("move that into Stage 2", "authorize_stage2")

    # Draft
    def test_have_frank_lloyd_try_drafting_again(self):
        self._assert_action("Have Frank Lloyd try drafting again", "draft")

    def test_generate_the_draft(self):
        self._assert_action("generate the draft", "draft")

    def test_draft_that_now(self):
        self._assert_action("draft that now", "draft")

    def test_frank_lloyd_draft_it(self):
        self._assert_action("Frank Lloyd draft it", "draft")

    # Promote
    def test_promote_the_latest_frank_lloyd_draft(self):
        self._assert_action("Promote the latest Frank Lloyd draft", "promote")

    def test_promote_the_draft(self):
        self._assert_action("promote the draft", "promote")

    def test_ship_that_draft(self):
        self._assert_action("Ship that draft", "promote")

    def test_merge_that_draft(self):
        self._assert_action("Merge that draft into the repo", "promote")

    # Discard
    def test_discard_that_draft_and_retry(self):
        self._assert_action("Discard that draft and let him retry", "discard")

    def test_scrap_the_current_draft(self):
        self._assert_action("Scrap the current draft", "discard")

    def test_throw_away_that_draft(self):
        self._assert_action("Throw away that draft", "discard")

    def test_toss_the_draft(self):
        self._assert_action("Toss the draft", "discard")


# ── TestFLParsePreservation ──────────────────────────────────────────────────

class TestFLParsePreservation(unittest.TestCase):
    """Structured commands with BUILD-N still route to their original types."""

    def test_approve_build_n_still_approve_build(self):
        cmd = parse_command("approve BUILD-003 looks good")
        self.assertEqual(cmd.type, CommandType.APPROVE_BUILD)

    def test_reject_build_n_still_reject_build(self):
        cmd = parse_command("reject BUILD-003 spec is wrong")
        self.assertEqual(cmd.type, CommandType.REJECT_BUILD)

    def test_authorize_build_n_still_authorize_stage2(self):
        cmd = parse_command("authorize BUILD-003 stage2")
        self.assertEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)

    def test_draft_build_n_still_draft_stage2(self):
        cmd = parse_command("draft BUILD-003")
        self.assertEqual(cmd.type, CommandType.DRAFT_STAGE2)

    def test_promote_build_n_path_still_promote_draft(self):
        cmd = parse_command("promote BUILD-003 frank_lloyd/x.py")
        self.assertEqual(cmd.type, CommandType.PROMOTE_DRAFT)

    def test_discard_build_n_still_discard_draft(self):
        cmd = parse_command("discard BUILD-003")
        self.assertEqual(cmd.type, CommandType.DISCARD_DRAFT)

    def test_plain_status_still_status(self):
        cmd = parse_command("status")
        self.assertEqual(cmd.type, CommandType.STATUS)

    def test_plain_approve_no_context_still_approve_candidate(self):
        # "approve" alone with no FL context → approve_candidate
        cmd = parse_command("approve")
        self.assertEqual(cmd.type, CommandType.APPROVE_CANDIDATE)

    def test_nl_build_intake_still_build_intent(self):
        cmd = parse_command("have Frank Lloyd build a health endpoint")
        self.assertEqual(cmd.type, CommandType.BUILD_INTENT)


# ── TestFLReasonExtraction ───────────────────────────────────────────────────

class TestFLReasonExtraction(unittest.TestCase):
    """Reason is extracted from NL reject text."""

    def test_reason_extracted_from_because(self):
        cmd = parse_command("reject that Frank Lloyd build because it touches the wrong files")
        self.assertIn("touches the wrong files", cmd.args.get("reason", ""))

    def test_reason_extracted_from_dash_separator(self):
        cmd = parse_command("reject that spec -- the description is incomplete")
        self.assertIn("description is incomplete", cmd.args.get("reason", ""))

    def test_no_reason_gives_empty_string(self):
        cmd = parse_command("reject that Frank Lloyd build")
        # reason may be empty; type should still be FL_LIFECYCLE_NL
        self.assertEqual(cmd.type, CommandType.FL_LIFECYCLE_NL)
        self.assertEqual(cmd.args["action"], "reject")

    def test_build_id_extracted_from_nl_text(self):
        cmd = parse_command("reject that Frank Lloyd build — BUILD-004 touches wrong files")
        self.assertEqual(cmd.args.get("build_id"), "BUILD-004")


# ── TestFLBuildResolution ────────────────────────────────────────────────────

class TestFLBuildResolution(unittest.TestCase):
    """_fl_resolve_actionable_build returns correct build_id for each action."""

    def _with_log(self, events: list[dict]) -> None:
        """Temporarily patch _FL_BUILD_LOG to use a tmp file."""
        # (called inside tests using context)
        raise NotImplementedError  # not called directly

    def _patch_log(self, events: list[dict]):
        """Return a context manager patching _FL_BUILD_LOG."""
        import peter.handlers as _handlers
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w")
        for ev in events:
            tmp.write(json.dumps(ev) + "\n")
        tmp.close()
        return patch.object(_handlers, "_FL_BUILD_LOG", pathlib.Path(tmp.name))

    def test_approve_resolves_pending_review_build(self):
        events = [
            _ev("BUILD-001", "request_queued"),
            _ev("BUILD-001", "spec_ready"),
        ]
        with self._patch_log(events):
            result = _fl_resolve_actionable_build("approve")
        self.assertEqual(result, "BUILD-001")

    def test_authorize_stage2_resolves_spec_approved_build(self):
        events = [
            _ev("BUILD-001", "request_queued"),
            _ev("BUILD-001", "spec_approved"),
        ]
        with self._patch_log(events):
            result = _fl_resolve_actionable_build("authorize_stage2")
        self.assertEqual(result, "BUILD-001")

    def test_draft_resolves_stage2_authorized_build(self):
        events = [
            _ev("BUILD-001", "request_queued"),
            _ev("BUILD-001", "stage2_authorized"),
        ]
        with self._patch_log(events):
            result = _fl_resolve_actionable_build("draft")
        self.assertEqual(result, "BUILD-001")

    def test_promote_resolves_draft_generated_build(self):
        events = [
            _ev("BUILD-001", "request_queued"),
            _ev("BUILD-001", "draft_generated"),
        ]
        with self._patch_log(events):
            result = _fl_resolve_actionable_build("promote")
        self.assertEqual(result, "BUILD-001")

    def test_discard_resolves_draft_generated_build(self):
        events = [
            _ev("BUILD-001", "request_queued"),
            _ev("BUILD-001", "draft_generated"),
        ]
        with self._patch_log(events):
            result = _fl_resolve_actionable_build("discard")
        self.assertEqual(result, "BUILD-001")

    def test_discard_resolves_draft_blocked_build(self):
        events = [
            _ev("BUILD-001", "request_queued"),
            _ev("BUILD-001", "draft_blocked"),
        ]
        with self._patch_log(events):
            result = _fl_resolve_actionable_build("discard")
        self.assertEqual(result, "BUILD-001")

    def test_no_actionable_build_returns_none(self):
        events = [
            _ev("BUILD-001", "request_queued"),
            _ev("BUILD-001", "spec_rejected"),
        ]
        with self._patch_log(events):
            result = _fl_resolve_actionable_build("approve")
        self.assertIsNone(result)

    def test_resolves_most_recent_when_multiple(self):
        events = [
            _ev("BUILD-001", "request_queued",    "2026-04-11T00:01:00+00:00"),
            _ev("BUILD-001", "spec_ready",         "2026-04-11T00:02:00+00:00"),
            _ev("BUILD-002", "request_queued",    "2026-04-11T00:03:00+00:00"),
            _ev("BUILD-002", "spec_ready",         "2026-04-11T00:04:00+00:00"),
        ]
        with self._patch_log(events):
            result = _fl_resolve_actionable_build("approve")
        self.assertEqual(result, "BUILD-002")

    def test_discarded_build_resolves_as_stage2_authorized(self):
        events = [
            _ev("BUILD-001", "stage2_authorized", "2026-04-11T00:04:00+00:00"),
            _ev("BUILD-001", "draft_generated",   "2026-04-11T00:05:00+00:00"),
            _ev("BUILD-001", "draft_discarded",   "2026-04-11T00:06:00+00:00"),
        ]
        with self._patch_log(events):
            result = _fl_resolve_actionable_build("draft")  # stage2_authorized after discard
        self.assertEqual(result, "BUILD-001")


# ── TestFLHandlerApprove ─────────────────────────────────────────────────────

class TestFLHandlerApprove(unittest.TestCase):

    def test_approve_success_ok_true(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "archive_path": "/tmp/arch", "error": None}
        cmd = _cmd(_full_args("approve", build_id="BUILD-001"))
        with patch("frank_lloyd.spec_approver.approve_build", return_value=_ok):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertTrue(r.ok)

    def test_approve_success_conversational_summary(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "archive_path": "/tmp/arch", "error": None}
        cmd = _cmd(_full_args("approve", build_id="BUILD-001"))
        with patch("frank_lloyd.spec_approver.approve_build", return_value=_ok):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("approved", r.summary.lower())
        self.assertNotIn("Usage:", r.summary)  # not CLI-style

    def test_approve_failure_surfaces_error(self):
        _fail = {"ok": False, "build_id": "BUILD-001", "archive_path": None, "error": "Not in pending_review."}
        cmd = _cmd(_full_args("approve", build_id="BUILD-001"))
        with patch("frank_lloyd.spec_approver.approve_build", return_value=_fail):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertFalse(r.ok)
        self.assertIn("pending_review", r.summary)

    def test_approve_nothing_to_do_when_no_build(self):
        cmd = _cmd(_full_args("approve", build_id=""))
        with patch("peter.handlers._fl_resolve_actionable_build", return_value=None):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertFalse(r.ok)
        self.assertIn("Nothing", r.summary)


# ── TestFLHandlerReject ──────────────────────────────────────────────────────

class TestFLHandlerReject(unittest.TestCase):

    def test_reject_no_reason_asks_conversationally(self):
        cmd = _cmd(_full_args("reject", build_id="BUILD-001", reason=""))
        r = handle_fl_lifecycle_nl(cmd)
        self.assertFalse(r.ok)
        self.assertIn("reason", r.summary.lower())
        self.assertNotIn("Usage:", r.summary)

    def test_reject_no_reason_next_action_includes_reject_cmd(self):
        cmd = _cmd(_full_args("reject", build_id="BUILD-001", reason=""))
        r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("reject BUILD-001", r.next_action)

    def test_reject_with_reason_ok_true(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "archive_path": "/tmp/arch", "error": None}
        cmd = _cmd(_full_args("reject", build_id="BUILD-001", reason="Spec touches wrong files"))
        with patch("frank_lloyd.spec_approver.reject_build", return_value=_ok):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertTrue(r.ok)

    def test_reject_with_reason_summary_includes_reason(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "archive_path": "/tmp/arch", "error": None}
        cmd = _cmd(_full_args("reject", build_id="BUILD-001", reason="Spec touches wrong files"))
        with patch("frank_lloyd.spec_approver.reject_build", return_value=_ok):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("Spec touches wrong files", r.summary)


# ── TestFLHandlerAuthorize ───────────────────────────────────────────────────

class TestFLHandlerAuthorize(unittest.TestCase):

    def test_authorize_success_ok_true(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "archive_path": "/tmp/a",
               "authorization_path": "/tmp/a/auth.json", "error": None}
        cmd = _cmd(_full_args("authorize_stage2", build_id="BUILD-001"))
        with patch("frank_lloyd.stage2_authorizer.authorize_stage2", return_value=_ok), \
             patch("pathlib.Path.read_text", side_effect=OSError):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertTrue(r.ok)

    def test_authorize_success_conversational(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "archive_path": "/tmp/a",
               "authorization_path": "/tmp/a/auth.json", "error": None}
        cmd = _cmd(_full_args("authorize_stage2", build_id="BUILD-001"))
        with patch("frank_lloyd.stage2_authorizer.authorize_stage2", return_value=_ok), \
             patch("pathlib.Path.read_text", side_effect=OSError):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("Stage 2", r.summary)
        self.assertNotIn("Usage:", r.summary)

    def test_authorize_nothing_to_do_when_no_build(self):
        cmd = _cmd(_full_args("authorize_stage2", build_id=""))
        with patch("peter.handlers._fl_resolve_actionable_build", return_value=None):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertFalse(r.ok)
        self.assertIn("Nothing", r.summary)


# ── TestFLHandlerDraft ───────────────────────────────────────────────────────

class TestFLHandlerDraft(unittest.TestCase):

    def test_draft_success_ok_true(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "status": "draft_generated", "error": None}
        cmd = _cmd(_full_args("draft", build_id="BUILD-001"))
        with patch("frank_lloyd.stage2_drafter.generate_stage2_draft", return_value=_ok):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertTrue(r.ok)

    def test_draft_success_summary_mentions_review(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "status": "draft_generated", "error": None}
        cmd = _cmd(_full_args("draft", build_id="BUILD-001"))
        with patch("frank_lloyd.stage2_drafter.generate_stage2_draft", return_value=_ok):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("review", r.summary.lower())

    def test_draft_failure_surfaces_error(self):
        _fail = {"ok": False, "build_id": "BUILD-001", "status": "draft_blocked", "error": "LM unavailable."}
        cmd = _cmd(_full_args("draft", build_id="BUILD-001"))
        with patch("frank_lloyd.stage2_drafter.generate_stage2_draft", return_value=_fail):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertFalse(r.ok)

    def test_draft_nothing_to_do_when_no_build(self):
        cmd = _cmd(_full_args("draft", build_id=""))
        with patch("peter.handlers._fl_resolve_actionable_build", return_value=None):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertFalse(r.ok)
        self.assertIn("Nothing", r.summary)


# ── TestFLHandlerPromote ─────────────────────────────────────────────────────

class TestFLHandlerPromote(unittest.TestCase):

    def test_promote_no_path_asks_conversationally(self):
        cmd = _cmd(_full_args("promote", build_id="BUILD-001", target_path=""))
        r = handle_fl_lifecycle_nl(cmd)
        self.assertFalse(r.ok)
        self.assertIn(".py", r.summary)
        self.assertNotIn("Usage:", r.summary)

    def test_promote_no_path_next_action_includes_promote_cmd(self):
        cmd = _cmd(_full_args("promote", build_id="BUILD-001", target_path=""))
        r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("promote BUILD-001", r.next_action)

    def test_promote_with_path_ok_true(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "target_path": "frank_lloyd/x.py",
               "promoted_at": "2026-04-11T00:10:00+00:00", "archive_path": "/tmp/arch", "error": None}
        cmd = _cmd(_full_args("promote", build_id="BUILD-001", target_path="frank_lloyd/x.py"))
        with patch("frank_lloyd.stage2_promoter.promote_draft", return_value=_ok):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertTrue(r.ok)

    def test_promote_with_path_summary_conversational(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "target_path": "frank_lloyd/x.py",
               "promoted_at": "2026-04-11T00:10:00+00:00", "archive_path": "/tmp/arch", "error": None}
        cmd = _cmd(_full_args("promote", build_id="BUILD-001", target_path="frank_lloyd/x.py"))
        with patch("frank_lloyd.stage2_promoter.promote_draft", return_value=_ok):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("frank_lloyd/x.py", r.summary)

    def test_promote_success_human_review_needed(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "target_path": "frank_lloyd/x.py",
               "promoted_at": "2026-04-11T00:10:00+00:00", "archive_path": "/tmp/arch", "error": None}
        cmd = _cmd(_full_args("promote", build_id="BUILD-001", target_path="frank_lloyd/x.py"))
        with patch("frank_lloyd.stage2_promoter.promote_draft", return_value=_ok):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertTrue(r.human_review_needed)


# ── TestFLHandlerDiscard ─────────────────────────────────────────────────────

class TestFLHandlerDiscard(unittest.TestCase):

    def test_discard_success_ok_true(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "discarded_at": "2026-04-11T00:06:00+00:00", "error": None}
        cmd = _cmd(_full_args("discard", build_id="BUILD-001"))
        with patch("frank_lloyd.stage2_discarder.discard_draft", return_value=_ok):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertTrue(r.ok)

    def test_discard_success_summary_mentions_retry(self):
        _ok = {"ok": True, "build_id": "BUILD-001", "discarded_at": "2026-04-11T00:06:00+00:00", "error": None}
        cmd = _cmd(_full_args("discard", build_id="BUILD-001"))
        with patch("frank_lloyd.stage2_discarder.discard_draft", return_value=_ok):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("draft", r.next_action.lower())

    def test_discard_nothing_to_do_when_no_build(self):
        cmd = _cmd(_full_args("discard", build_id=""))
        with patch("peter.handlers._fl_resolve_actionable_build", return_value=None):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertFalse(r.ok)
        self.assertIn("Nothing", r.summary)


# ── TestFLHandlerStatusQuery ─────────────────────────────────────────────────

class TestFLHandlerStatusQuery(unittest.TestCase):

    def test_status_query_ok_true(self):
        cmd = _cmd(_full_args("status_query"))
        with patch("peter.handlers._fl_build_statuses", return_value={}):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertTrue(r.ok)

    def test_status_query_no_builds_conversational(self):
        cmd = _cmd(_full_args("status_query"))
        with patch("peter.handlers._fl_build_statuses", return_value={}):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("no builds", r.summary.lower())

    def test_status_query_pending_review_mentions_review(self):
        cmd = _cmd(_full_args("status_query"))
        with patch("peter.handlers._fl_build_statuses", return_value={"BUILD-001": "pending_review"}):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("review", r.summary.lower())

    def test_status_query_draft_generated_mentions_draft(self):
        cmd = _cmd(_full_args("status_query"))
        with patch("peter.handlers._fl_build_statuses", return_value={"BUILD-001": "draft_generated"}):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("draft", r.summary.lower())

    def test_status_query_includes_build_id(self):
        cmd = _cmd(_full_args("status_query"))
        with patch("peter.handlers._fl_build_statuses", return_value={"BUILD-042": "pending_review"}):
            r = handle_fl_lifecycle_nl(cmd)
        self.assertIn("BUILD-042", r.summary)


# ── TestFLRouterDispatch ─────────────────────────────────────────────────────

class TestFLRouterDispatch(unittest.TestCase):

    def test_fl_lifecycle_nl_in_dispatch(self):
        self.assertIn(CommandType.FL_LIFECYCLE_NL, _DISPATCH)

    def test_fl_lifecycle_nl_dispatches_to_handle_fl_lifecycle_nl(self):
        self.assertIs(_DISPATCH[CommandType.FL_LIFECYCLE_NL], handle_fl_lifecycle_nl)


if __name__ == "__main__":
    unittest.main()
