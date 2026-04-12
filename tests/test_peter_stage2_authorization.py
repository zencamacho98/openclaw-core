# tests/test_peter_stage2_authorization.py
#
# Unit tests for the Stage 2 authorization gate in Peter's command layer.
#
# Coverage:
#   - parse_command(): "authorize BUILD-N stage2 [notes]" → AUTHORIZE_STAGE2
#   - parse_command(): non-matching "authorize ..." inputs do NOT produce AUTHORIZE_STAGE2
#   - handle_authorize_stage2(): success and error paths
#   - router.py: AUTHORIZE_STAGE2 is dispatched correctly
#   - Transport isolation: no "import app" substring in handlers.py import lines

import unittest
from unittest.mock import MagicMock, patch

from peter.commands import CommandType, parse_command
from peter.handlers import handle_authorize_stage2
from peter.router   import _DISPATCH


# ── parse_command() ───────────────────────────────────────────────────────────

class TestParseCommandAuthorizeStage2(unittest.TestCase):
    def test_basic_authorize_command(self):
        cmd = parse_command("authorize BUILD-001 stage2")
        self.assertEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)
        self.assertEqual(cmd.args["build_id"], "BUILD-001")
        self.assertEqual(cmd.args["notes"], "")

    def test_build_id_uppercased(self):
        cmd = parse_command("authorize build-002 stage2")
        self.assertEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)
        self.assertEqual(cmd.args["build_id"], "BUILD-002")

    def test_with_optional_notes(self):
        cmd = parse_command("authorize BUILD-003 stage2 ready to draft now")
        self.assertEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)
        self.assertEqual(cmd.args["build_id"], "BUILD-003")
        self.assertEqual(cmd.args["notes"], "ready to draft now")

    def test_case_insensitive_command(self):
        cmd = parse_command("AUTHORIZE BUILD-001 STAGE2")
        self.assertEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)

    def test_mixed_case_stage2_token(self):
        cmd = parse_command("authorize BUILD-001 Stage2")
        self.assertEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)

    def test_high_build_number(self):
        cmd = parse_command("authorize BUILD-999 stage2")
        self.assertEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)
        self.assertEqual(cmd.args["build_id"], "BUILD-999")


class TestParseCommandAuthorizeStage2NonMatching(unittest.TestCase):
    def test_missing_stage2_token_does_not_match(self):
        """authorize BUILD-001 alone (no stage2) must NOT produce AUTHORIZE_STAGE2."""
        cmd = parse_command("authorize BUILD-001")
        self.assertNotEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)

    def test_non_build_second_token_does_not_match(self):
        """authorize something stage2 (second token not BUILD-) must not match."""
        cmd = parse_command("authorize something stage2")
        self.assertNotEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)

    def test_wrong_third_token_does_not_match(self):
        """authorize BUILD-001 production (third token not 'stage2') must not match."""
        cmd = parse_command("authorize BUILD-001 production")
        self.assertNotEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)

    def test_bare_authorize_does_not_match(self):
        cmd = parse_command("authorize")
        self.assertNotEqual(cmd.type, CommandType.AUTHORIZE_STAGE2)

    def test_does_not_intercept_approve_build(self):
        """'approve BUILD-001' must still route to APPROVE_BUILD, not AUTHORIZE_STAGE2."""
        cmd = parse_command("approve BUILD-001")
        self.assertEqual(cmd.type, CommandType.APPROVE_BUILD)

    def test_does_not_intercept_approve_candidate(self):
        """'approve' alone must still route to APPROVE_CANDIDATE."""
        cmd = parse_command("approve")
        self.assertEqual(cmd.type, CommandType.APPROVE_CANDIDATE)


# ── handle_authorize_stage2() ────────────────────────────────────────────────

class TestHandleAuthorizeStage2(unittest.TestCase):
    def _make_command(self, build_id="BUILD-001", notes=""):
        from peter.commands import Command
        return Command(
            type        = CommandType.AUTHORIZE_STAGE2,
            args        = {"build_id": build_id, "notes": notes},
            transport   = "cli",
            operator_id = "cli",
            raw_text    = f"authorize {build_id} stage2",
        )

    def test_missing_build_id_returns_error(self):
        cmd = self._make_command(build_id="")
        result = handle_authorize_stage2(cmd)
        self.assertFalse(result.ok)
        self.assertIn("No build ID", result.summary)

    def test_success_returns_ok_response(self):
        mock_result = {
            "ok":                 True,
            "build_id":           "BUILD-001",
            "archive_path":       "/tmp/archives/BUILD-001",
            "authorization_path": "/tmp/archives/BUILD-001/stage2_authorization.json",
            "error":              None,
        }
        with patch("frank_lloyd.stage2_authorizer.authorize_stage2",
                   return_value=mock_result):
            with patch("pathlib.Path.read_text",
                       return_value='{"provider_readiness": {"executable_lanes": ["cheap"], "config_only_lanes": [], "external_supervised_lanes": ["codex_supervised"]}}'):
                result = handle_authorize_stage2(self._make_command())
        self.assertTrue(result.ok)
        self.assertIn("BUILD-001", result.summary)
        self.assertIn("authorized", result.summary.lower())

    def test_error_returns_not_ok_response(self):
        mock_result = {
            "ok":                 False,
            "build_id":           "BUILD-001",
            "archive_path":       None,
            "authorization_path": None,
            "error":              "BUILD-001 is not in spec_approved state.",
        }
        with patch("frank_lloyd.stage2_authorizer.authorize_stage2",
                   return_value=mock_result):
            result = handle_authorize_stage2(self._make_command())
        self.assertFalse(result.ok)
        self.assertIn("spec_approved", result.summary)

    def test_next_action_mentions_authorization_only(self):
        mock_result = {
            "ok":                 True,
            "build_id":           "BUILD-001",
            "archive_path":       "/tmp/archives/BUILD-001",
            "authorization_path": "/tmp/archives/BUILD-001/stage2_authorization.json",
            "error":              None,
        }
        with patch("frank_lloyd.stage2_authorizer.authorize_stage2",
                   return_value=mock_result):
            with patch("pathlib.Path.read_text", return_value='{"provider_readiness": {"executable_lanes": [], "config_only_lanes": [], "external_supervised_lanes": []}}'):
                result = handle_authorize_stage2(self._make_command())
        self.assertIn("authorization only", result.next_action.lower())


# ── Transport isolation ───────────────────────────────────────────────────────

class TestHandlerTransportIsolation(unittest.TestCase):
    """handlers.py must not contain 'import app' as a substring in any import line."""

    def test_handlers_do_not_import_app_modules(self):
        import pathlib
        handlers_path = pathlib.Path(__file__).parent.parent / "peter" / "handlers.py"
        source = handlers_path.read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                self.assertNotIn(
                    "import app",
                    stripped,
                    f"handlers.py contains a top-level 'import app' line: {stripped!r}",
                )


# ── Router dispatch ───────────────────────────────────────────────────────────

class TestRouterDispatch(unittest.TestCase):
    def test_authorize_stage2_in_dispatch_table(self):
        self.assertIn(CommandType.AUTHORIZE_STAGE2, _DISPATCH)

    def test_authorize_stage2_dispatches_to_correct_handler(self):
        self.assertIs(_DISPATCH[CommandType.AUTHORIZE_STAGE2], handle_authorize_stage2)


if __name__ == "__main__":
    unittest.main()
