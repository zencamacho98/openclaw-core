# tests/test_peter_promote_draft.py
#
# Tests for the Peter promote BUILD-N command/handler/router integration.
#
# Coverage:
#   TestParseDraftPromote    — command parsing for "promote BUILD-N path.py"
#   TestHandlerPromoteDraft  — handler success/failure, missing args
#   TestTransportIsolation   — no "import app" in handler source
#   TestRouterDispatch       — PROMOTE_DRAFT routed to handle_promote_draft

from __future__ import annotations

import inspect
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from peter.commands import CommandType, parse_command
from peter.handlers import handle_promote_draft
from peter.router import _DISPATCH


# ── TestParseDraftPromote ────────────────────────────────────────────────────

class TestParseDraftPromote(unittest.TestCase):
    """Command parser correctly identifies promote BUILD-N path.py."""

    def _parse(self, text: str) -> "Command":  # type: ignore[name-defined]
        return parse_command(text)

    def test_promote_build_returns_promote_draft_type(self):
        cmd = self._parse("promote BUILD-001 frank_lloyd/my_module.py")
        self.assertEqual(cmd.type, CommandType.PROMOTE_DRAFT)

    def test_promote_build_id_captured(self):
        cmd = self._parse("promote BUILD-042 frank_lloyd/x.py")
        self.assertEqual(cmd.args["build_id"], "BUILD-042")

    def test_promote_build_id_uppercased(self):
        cmd = self._parse("promote build-001 frank_lloyd/x.py")
        self.assertEqual(cmd.args["build_id"], "BUILD-001")

    def test_promote_target_path_captured(self):
        cmd = self._parse("promote BUILD-001 frank_lloyd/my_module.py")
        self.assertEqual(cmd.args["target_path"], "frank_lloyd/my_module.py")

    def test_promote_with_notes_captured(self):
        cmd = self._parse("promote BUILD-001 frank_lloyd/x.py some notes here")
        self.assertEqual(cmd.args["notes"], "some notes here")

    def test_promote_without_notes_empty_string(self):
        cmd = self._parse("promote BUILD-001 frank_lloyd/x.py")
        self.assertEqual(cmd.args["notes"], "")

    def test_promote_missing_target_path_still_matches(self):
        # "promote BUILD-001" with no path — still routes to PROMOTE_DRAFT
        # handler will return the missing-path error
        cmd = self._parse("promote BUILD-001")
        self.assertEqual(cmd.type, CommandType.PROMOTE_DRAFT)
        self.assertEqual(cmd.args["target_path"], "")

    def test_promote_guidance_still_works(self):
        cmd = self._parse("promote guidance")
        self.assertEqual(cmd.type, CommandType.PROMOTE_GUIDANCE)

    def test_promote_alone_falls_through_to_guidance(self):
        cmd = self._parse("promote")
        self.assertEqual(cmd.type, CommandType.PROMOTE_GUIDANCE)

    def test_non_build_second_token_falls_through(self):
        # "promote xyz path.py" — xyz does not start with BUILD-
        cmd = self._parse("promote xyz path.py")
        self.assertEqual(cmd.type, CommandType.PROMOTE_GUIDANCE)

    def test_promote_build_with_app_route_path(self):
        cmd = self._parse("promote BUILD-005 app/routes/new_route.py")
        self.assertEqual(cmd.type, CommandType.PROMOTE_DRAFT)
        self.assertEqual(cmd.args["target_path"], "app/routes/new_route.py")


# ── TestHandlerPromoteDraft ──────────────────────────────────────────────────

class TestHandlerPromoteDraft(unittest.TestCase):
    """handle_promote_draft delegates to frank_lloyd.stage2_promoter.promote_draft."""

    def _cmd(self, args: dict) -> "Command":  # type: ignore[name-defined]
        from peter.commands import Command
        return Command(
            type        = CommandType.PROMOTE_DRAFT,
            args        = args,
            transport   = "cli",
            operator_id = "test",
            raw_text    = "promote BUILD-001 frank_lloyd/x.py",
        )

    def test_missing_build_id_returns_ok_false(self):
        cmd = self._cmd({"build_id": "", "target_path": "frank_lloyd/x.py", "notes": ""})
        r = handle_promote_draft(cmd)
        self.assertFalse(r.ok)
        self.assertIn("build ID", r.summary)

    def test_missing_target_path_returns_ok_false(self):
        cmd = self._cmd({"build_id": "BUILD-001", "target_path": "", "notes": ""})
        r = handle_promote_draft(cmd)
        self.assertFalse(r.ok)
        self.assertIn("target", r.summary.lower())

    def test_failure_from_promoter_surfaces_error(self):
        _fail_result = {
            "ok": False, "build_id": "BUILD-001",
            "target_path": None, "promoted_at": None,
            "archive_path": None,
            "error": "No events found for BUILD-001.",
        }
        cmd = self._cmd({"build_id": "BUILD-001", "target_path": "frank_lloyd/x.py", "notes": ""})
        with patch("frank_lloyd.stage2_promoter.promote_draft", return_value=_fail_result):
            r = handle_promote_draft(cmd)
        self.assertFalse(r.ok)
        self.assertIn("BUILD-001", r.summary)

    def test_success_returns_ok_true(self):
        _ok_result = {
            "ok": True, "build_id": "BUILD-001",
            "target_path": "frank_lloyd/x.py",
            "promoted_at": "2026-04-11T00:10:00+00:00",
            "archive_path": "/tmp/fake/archives/BUILD-001",
            "error": None,
        }
        cmd = self._cmd({"build_id": "BUILD-001", "target_path": "frank_lloyd/x.py", "notes": ""})
        with patch("frank_lloyd.stage2_promoter.promote_draft", return_value=_ok_result):
            r = handle_promote_draft(cmd)
        self.assertTrue(r.ok)

    def test_success_mentions_target_path(self):
        _ok_result = {
            "ok": True, "build_id": "BUILD-001",
            "target_path": "frank_lloyd/x.py",
            "promoted_at": "2026-04-11T00:10:00+00:00",
            "archive_path": "/tmp/fake/archives/BUILD-001",
            "error": None,
        }
        cmd = self._cmd({"build_id": "BUILD-001", "target_path": "frank_lloyd/x.py", "notes": ""})
        with patch("frank_lloyd.stage2_promoter.promote_draft", return_value=_ok_result):
            r = handle_promote_draft(cmd)
        self.assertIn("frank_lloyd/x.py", r.summary)

    def test_success_human_review_needed_true(self):
        _ok_result = {
            "ok": True, "build_id": "BUILD-001",
            "target_path": "frank_lloyd/x.py",
            "promoted_at": "2026-04-11T00:10:00+00:00",
            "archive_path": "/tmp/fake/archives/BUILD-001",
            "error": None,
        }
        cmd = self._cmd({"build_id": "BUILD-001", "target_path": "frank_lloyd/x.py", "notes": ""})
        with patch("frank_lloyd.stage2_promoter.promote_draft", return_value=_ok_result):
            r = handle_promote_draft(cmd)
        self.assertTrue(r.human_review_needed)

    def test_success_mentions_tests_in_next_action(self):
        _ok_result = {
            "ok": True, "build_id": "BUILD-001",
            "target_path": "frank_lloyd/x.py",
            "promoted_at": "2026-04-11T00:10:00+00:00",
            "archive_path": "/tmp/fake/archives/BUILD-001",
            "error": None,
        }
        cmd = self._cmd({"build_id": "BUILD-001", "target_path": "frank_lloyd/x.py", "notes": ""})
        with patch("frank_lloyd.stage2_promoter.promote_draft", return_value=_ok_result):
            r = handle_promote_draft(cmd)
        self.assertIn("test", r.next_action.lower())


# ── TestTransportIsolation ───────────────────────────────────────────────────

class TestTransportIsolation(unittest.TestCase):
    """Handler and its imports must not reference 'import app' at module level."""

    def test_handler_source_has_no_import_app(self):
        src = inspect.getsource(handle_promote_draft)
        self.assertNotIn("import app", src)

    def test_handler_uses_module_level_import(self):
        src = inspect.getsource(handle_promote_draft)
        self.assertIn("frank_lloyd.stage2_promoter", src)


# ── TestRouterDispatch ───────────────────────────────────────────────────────

class TestRouterDispatch(unittest.TestCase):
    def test_promote_draft_in_dispatch(self):
        self.assertIn(CommandType.PROMOTE_DRAFT, _DISPATCH)

    def test_promote_draft_dispatches_to_handle_promote_draft(self):
        self.assertIs(_DISPATCH[CommandType.PROMOTE_DRAFT], handle_promote_draft)


if __name__ == "__main__":
    unittest.main()
