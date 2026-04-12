# tests/test_peter_discard_draft.py
#
# Tests for the Peter discard BUILD-N command/handler/router integration.
#
# Coverage:
#   TestParseDiscardDraft    — command parsing for "discard BUILD-N [notes]"
#   TestHandlerDiscardDraft  — handler success/failure, missing args
#   TestTransportIsolation   — no "import app" in handler source
#   TestRouterDispatch       — DISCARD_DRAFT routed to handle_discard_draft

from __future__ import annotations

import inspect
import pathlib
import sys
import unittest
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from peter.commands import CommandType, parse_command
from peter.handlers import handle_discard_draft
from peter.router import _DISPATCH


# ── TestParseDiscardDraft ────────────────────────────────────────────────────

class TestParseDiscardDraft(unittest.TestCase):

    def _parse(self, text: str):
        return parse_command(text)

    def test_discard_build_returns_discard_draft_type(self):
        cmd = self._parse("discard BUILD-001")
        self.assertEqual(cmd.type, CommandType.DISCARD_DRAFT)

    def test_discard_build_id_captured(self):
        cmd = self._parse("discard BUILD-042")
        self.assertEqual(cmd.args["build_id"], "BUILD-042")

    def test_discard_build_id_uppercased(self):
        cmd = self._parse("discard build-005")
        self.assertEqual(cmd.args["build_id"], "BUILD-005")

    def test_discard_with_notes_captured(self):
        cmd = self._parse("discard BUILD-001 bad output, try again")
        self.assertEqual(cmd.args["notes"], "bad output, try again")

    def test_discard_without_notes_empty_string(self):
        cmd = self._parse("discard BUILD-001")
        self.assertEqual(cmd.args["notes"], "")

    def test_discard_non_build_token_not_discard_draft(self):
        # "discard xyz" — xyz does not start with BUILD-
        cmd = self._parse("discard xyz")
        self.assertNotEqual(cmd.type, CommandType.DISCARD_DRAFT)

    def test_discard_alone_not_discard_draft(self):
        cmd = self._parse("discard")
        self.assertNotEqual(cmd.type, CommandType.DISCARD_DRAFT)


# ── TestHandlerDiscardDraft ──────────────────────────────────────────────────

class TestHandlerDiscardDraft(unittest.TestCase):

    def _cmd(self, args: dict):
        from peter.commands import Command
        return Command(
            type        = CommandType.DISCARD_DRAFT,
            args        = args,
            transport   = "cli",
            operator_id = "test",
            raw_text    = "discard BUILD-001",
        )

    def test_missing_build_id_returns_ok_false(self):
        cmd = self._cmd({"build_id": "", "notes": ""})
        r   = handle_discard_draft(cmd)
        self.assertFalse(r.ok)
        self.assertIn("build ID", r.summary)

    def test_failure_from_discarder_surfaces_error(self):
        _fail = {
            "ok":           False,
            "build_id":     "BUILD-001",
            "discarded_at": None,
            "error":        "No events found for BUILD-001.",
        }
        cmd = self._cmd({"build_id": "BUILD-001", "notes": ""})
        with patch("frank_lloyd.stage2_discarder.discard_draft", return_value=_fail):
            r = handle_discard_draft(cmd)
        self.assertFalse(r.ok)
        self.assertIn("BUILD-001", r.summary)

    def test_success_returns_ok_true(self):
        _ok = {
            "ok":           True,
            "build_id":     "BUILD-001",
            "discarded_at": "2026-04-11T00:10:00+00:00",
            "error":        None,
        }
        cmd = self._cmd({"build_id": "BUILD-001", "notes": ""})
        with patch("frank_lloyd.stage2_discarder.discard_draft", return_value=_ok):
            r = handle_discard_draft(cmd)
        self.assertTrue(r.ok)

    def test_success_summary_mentions_build_id(self):
        _ok = {
            "ok":           True,
            "build_id":     "BUILD-001",
            "discarded_at": "2026-04-11T00:10:00+00:00",
            "error":        None,
        }
        cmd = self._cmd({"build_id": "BUILD-001", "notes": ""})
        with patch("frank_lloyd.stage2_discarder.discard_draft", return_value=_ok):
            r = handle_discard_draft(cmd)
        self.assertIn("BUILD-001", r.summary)

    def test_success_summary_mentions_stage2_authorized(self):
        _ok = {
            "ok":           True,
            "build_id":     "BUILD-001",
            "discarded_at": "2026-04-11T00:10:00+00:00",
            "error":        None,
        }
        cmd = self._cmd({"build_id": "BUILD-001", "notes": ""})
        with patch("frank_lloyd.stage2_discarder.discard_draft", return_value=_ok):
            r = handle_discard_draft(cmd)
        self.assertIn("stage2_authorized", r.summary)

    def test_success_next_action_mentions_draft(self):
        _ok = {
            "ok":           True,
            "build_id":     "BUILD-001",
            "discarded_at": "2026-04-11T00:10:00+00:00",
            "error":        None,
        }
        cmd = self._cmd({"build_id": "BUILD-001", "notes": ""})
        with patch("frank_lloyd.stage2_discarder.discard_draft", return_value=_ok):
            r = handle_discard_draft(cmd)
        self.assertIn("draft", r.next_action.lower())


# ── TestTransportIsolation ───────────────────────────────────────────────────

class TestTransportIsolation(unittest.TestCase):

    def test_handler_source_has_no_import_app(self):
        src = inspect.getsource(handle_discard_draft)
        self.assertNotIn("import app", src)

    def test_handler_uses_stage2_discarder_module(self):
        src = inspect.getsource(handle_discard_draft)
        self.assertIn("frank_lloyd.stage2_discarder", src)


# ── TestRouterDispatch ───────────────────────────────────────────────────────

class TestRouterDispatch(unittest.TestCase):

    def test_discard_draft_in_dispatch(self):
        self.assertIn(CommandType.DISCARD_DRAFT, _DISPATCH)

    def test_discard_draft_dispatches_to_handle_discard_draft(self):
        self.assertIs(_DISPATCH[CommandType.DISCARD_DRAFT], handle_discard_draft)


if __name__ == "__main__":
    unittest.main()
