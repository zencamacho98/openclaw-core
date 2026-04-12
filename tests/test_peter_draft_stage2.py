# tests/test_peter_draft_stage2.py
#
# Tests for the Peter DRAFT_STAGE2 command (BUILD-007).
#
# Coverage:
#   parse_command():
#     - "draft BUILD-001"           → DRAFT_STAGE2, build_id=BUILD-001, notes=""
#     - "draft BUILD-001 my notes"  → DRAFT_STAGE2, notes="my notes"
#     - "draft build-001"           → DRAFT_STAGE2, build_id=BUILD-001 (uppercased)
#     - "draft something"           → NOT DRAFT_STAGE2 (no BUILD- prefix)
#     - "draft"                     → NOT DRAFT_STAGE2 (no tokens after)
#     - "draft BUILD-001 stage2"    → DRAFT_STAGE2, notes="stage2" (notes, not keyword)
#   handle_draft_stage2():
#     - missing build_id → ok=False
#     - result ok=True → ok=True response, mentions staging path and model
#     - result ok=False → ok=False response, error surface
#     - human_review_needed=True on success (draft requires manual review)
#   transport isolation: "import app" is NOT a substring of handler identifier
#   router dispatch: DRAFT_STAGE2 → handle_draft_stage2

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from peter.commands import parse_command, CommandType, Command
from peter.handlers import handle_draft_stage2
from peter import router as peter_router
import frank_lloyd.stage2_drafter as _drafter_mod


# ── Tests: parse_command ──────────────────────────────────────────────────────

class TestDraftStage2Parse(unittest.TestCase):

    def test_draft_build_id_parses_draft_stage2(self):
        cmd = parse_command("draft BUILD-001")
        self.assertEqual(cmd.type, CommandType.DRAFT_STAGE2)
        self.assertEqual(cmd.args["build_id"], "BUILD-001")

    def test_draft_notes_captured(self):
        cmd = parse_command("draft BUILD-001 initial pass")
        self.assertEqual(cmd.type, CommandType.DRAFT_STAGE2)
        self.assertEqual(cmd.args["build_id"], "BUILD-001")
        self.assertEqual(cmd.args["notes"], "initial pass")

    def test_draft_build_id_uppercased(self):
        cmd = parse_command("draft build-001")
        self.assertEqual(cmd.type, CommandType.DRAFT_STAGE2)
        self.assertEqual(cmd.args["build_id"], "BUILD-001")

    def test_draft_without_build_prefix_is_not_draft_stage2(self):
        cmd = parse_command("draft something else")
        self.assertNotEqual(cmd.type, CommandType.DRAFT_STAGE2)

    def test_bare_draft_is_not_draft_stage2(self):
        cmd = parse_command("draft")
        self.assertNotEqual(cmd.type, CommandType.DRAFT_STAGE2)

    def test_draft_stage2_word_captured_as_notes(self):
        """'stage2' after BUILD-N is just a notes token, not a keyword."""
        cmd = parse_command("draft BUILD-001 stage2")
        self.assertEqual(cmd.type, CommandType.DRAFT_STAGE2)
        self.assertEqual(cmd.args["notes"], "stage2")

    def test_approve_build_still_works_after_draft_rule(self):
        """approve BUILD-N must still produce APPROVE_BUILD."""
        cmd = parse_command("approve BUILD-001")
        self.assertEqual(cmd.type, CommandType.APPROVE_BUILD)

    def test_authorize_stage2_still_works_after_draft_rule(self):
        """authorize BUILD-N stage2 must still produce AUTHORIZE_STAGE2."""
        cmd = parse_command("authorize BUILD-001 stage2")
        self.assertEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)

    def test_draft_build_002_multiple_notes_words(self):
        cmd = parse_command("draft BUILD-002 first draft attempt here")
        self.assertEqual(cmd.type, CommandType.DRAFT_STAGE2)
        self.assertEqual(cmd.args["build_id"], "BUILD-002")
        self.assertEqual(cmd.args["notes"], "first draft attempt here")


# ── Tests: handle_draft_stage2 ────────────────────────────────────────────────

def _make_cmd(build_id: str = "BUILD-001", notes: str = "") -> Command:
    return Command(
        type=CommandType.DRAFT_STAGE2,
        args={"build_id": build_id, "notes": notes},
        transport="cli",
        operator_id="cli",
        raw_text=f"draft {build_id}",
    )


def _ok_result(build_id: str = "BUILD-001") -> dict:
    return {
        "ok":              True,
        "build_id":        build_id,
        "staging_path":    f"/tmp/staging/frank_lloyd/{build_id}/stage2",
        "manifest_path":   f"/tmp/staging/frank_lloyd/{build_id}/stage2/draft_manifest.json",
        "files_generated": ["draft_manifest.json", "draft_module.py", "draft_notes.md"],
        "routing": {
            "task_class":      "code_draft_low",
            "provider_tier":   "cheap",
            "provider_family": "openrouter",
            "model":           "openai/gpt-4o-mini",
            "executability":   "executable",
        },
        "error": None,
    }


def _fail_result(build_id: str = "BUILD-001", error: str = "Wrong state") -> dict:
    return {
        "ok":              False,
        "build_id":        build_id,
        "staging_path":    None,
        "manifest_path":   None,
        "files_generated": [],
        "routing":         None,
        "error":           error,
    }


class TestHandleDraftStage2(unittest.TestCase):

    def test_missing_build_id_returns_ok_false(self):
        cmd = Command(
            type=CommandType.DRAFT_STAGE2, args={},
            transport="cli", operator_id="cli", raw_text="draft",
        )
        resp = handle_draft_stage2(cmd)
        self.assertFalse(resp.ok)

    def test_success_returns_ok_true(self):
        with patch.object(_drafter_mod, "generate_stage2_draft",
                          return_value=_ok_result()) as mock_fn:
            resp = handle_draft_stage2(_make_cmd())
        self.assertTrue(resp.ok)
        mock_fn.assert_called_once()

    def test_success_response_mentions_staging_path(self):
        with patch.object(_drafter_mod, "generate_stage2_draft",
                          return_value=_ok_result()):
            resp = handle_draft_stage2(_make_cmd())
        self.assertIn("staging", resp.next_action.lower())

    def test_success_response_mentions_model(self):
        with patch.object(_drafter_mod, "generate_stage2_draft",
                          return_value=_ok_result()):
            resp = handle_draft_stage2(_make_cmd())
        self.assertIn("gpt-4o-mini", resp.summary)

    def test_success_response_mentions_task_class(self):
        with patch.object(_drafter_mod, "generate_stage2_draft",
                          return_value=_ok_result()):
            resp = handle_draft_stage2(_make_cmd())
        self.assertIn("code_draft_low", resp.summary)

    def test_success_human_review_needed_is_true(self):
        with patch.object(_drafter_mod, "generate_stage2_draft",
                          return_value=_ok_result()):
            resp = handle_draft_stage2(_make_cmd())
        self.assertTrue(resp.human_review_needed)

    def test_failure_returns_ok_false(self):
        with patch.object(_drafter_mod, "generate_stage2_draft",
                          return_value=_fail_result(error="Not stage2_authorized")):
            resp = handle_draft_stage2(_make_cmd())
        self.assertFalse(resp.ok)

    def test_failure_surfaces_error_in_summary(self):
        with patch.object(_drafter_mod, "generate_stage2_draft",
                          return_value=_fail_result(error="lane is config_only")):
            resp = handle_draft_stage2(_make_cmd())
        self.assertIn("config_only", resp.summary)

    def test_notes_passed_to_drafter(self):
        with patch.object(_drafter_mod, "generate_stage2_draft",
                          return_value=_ok_result()) as mock_fn:
            handle_draft_stage2(_make_cmd(notes="first pass"))
        call_kwargs = mock_fn.call_args
        # notes is passed as keyword argument
        self.assertEqual(call_kwargs.kwargs.get("notes", ""), "first pass")

    def test_next_action_says_staging_only(self):
        """Handler must make clear draft is staged, not live."""
        with patch.object(_drafter_mod, "generate_stage2_draft",
                          return_value=_ok_result()):
            resp = handle_draft_stage2(_make_cmd())
        lower = resp.next_action.lower()
        self.assertIn("staging", lower)

    def test_success_artifacts_contain_staging_path(self):
        with patch.object(_drafter_mod, "generate_stage2_draft",
                          return_value=_ok_result()):
            resp = handle_draft_stage2(_make_cmd())
        self.assertIn("staging_path", resp.artifacts)


# ── Tests: transport isolation ────────────────────────────────────────────────

class TestDraftStage2TransportIsolation(unittest.TestCase):
    """
    handle_draft_stage2 must not import from app.*  at module level.
    The test checks that the string "import app" does not appear in the
    handler function's source text.  "import frank_lloyd" is allowed.

    Note: "approve_build" contains "app" as a substring — the pattern we
    are guarding is "import app" (the substring test used in the real sentinel),
    not the presence of "app" as a word.
    """

    def test_handler_does_not_import_app_at_module_level(self):
        import inspect
        src = inspect.getsource(handle_draft_stage2)
        # The guard: "import frank_lloyd.stage2_drafter" is fine;
        # "import app" anywhere in the handler source is not allowed.
        self.assertNotIn("import app", src)


# ── Tests: router dispatch ────────────────────────────────────────────────────

class TestDraftStage2RouterDispatch(unittest.TestCase):

    def test_draft_stage2_in_dispatch_table(self):
        from peter.router import _DISPATCH
        self.assertIn(CommandType.DRAFT_STAGE2, _DISPATCH)

    def test_draft_stage2_dispatches_to_correct_handler(self):
        from peter.router import _DISPATCH
        self.assertEqual(_DISPATCH[CommandType.DRAFT_STAGE2], handle_draft_stage2)


if __name__ == "__main__":
    unittest.main()
