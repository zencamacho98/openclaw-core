# tests/test_peter_build_approval.py
#
# Tests for the Peter command layer wiring of Frank Lloyd build approval/rejection.
#
# Covers:
#   - parse_command: approve/reject BUILD-N disambiguation from approve/reject candidate
#   - handle_approve_build / handle_reject_build: success and error paths
#   - router dispatch (CommandType.APPROVE_BUILD / REJECT_BUILD → correct handler)

import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from peter.commands import parse_command, CommandType
from peter.handlers import handle_approve_build, handle_reject_build
from peter.responses import Response


# ── Parser tests ──────────────────────────────────────────────────────────────

class TestParseCommandApproveBuild(unittest.TestCase):

    def test_approve_build_n_routes_to_approve_build(self):
        cmd = parse_command("approve BUILD-001")
        self.assertEqual(cmd.type, CommandType.APPROVE_BUILD)
        self.assertEqual(cmd.args["build_id"], "BUILD-001")
        self.assertEqual(cmd.args["notes"], "")

    def test_approve_build_n_with_notes(self):
        cmd = parse_command("approve BUILD-003 looks good to me")
        self.assertEqual(cmd.type, CommandType.APPROVE_BUILD)
        self.assertEqual(cmd.args["build_id"], "BUILD-003")
        self.assertEqual(cmd.args["notes"], "looks good to me")

    def test_approve_build_case_insensitive(self):
        cmd = parse_command("approve build-007")
        self.assertEqual(cmd.type, CommandType.APPROVE_BUILD)
        self.assertEqual(cmd.args["build_id"], "BUILD-007")

    def test_approve_without_build_prefix_still_candidate(self):
        """approve QUEUE-123 (no BUILD- prefix) must not route to APPROVE_BUILD."""
        cmd = parse_command("approve some-queue-id")
        self.assertEqual(cmd.type, CommandType.APPROVE_CANDIDATE)

    def test_approve_alone_routes_to_candidate(self):
        cmd = parse_command("approve")
        self.assertEqual(cmd.type, CommandType.APPROVE_CANDIDATE)

    def test_ok_routes_to_candidate(self):
        cmd = parse_command("ok")
        self.assertEqual(cmd.type, CommandType.APPROVE_CANDIDATE)


class TestParseCommandRejectBuild(unittest.TestCase):

    def test_reject_build_n_routes_to_reject_build(self):
        cmd = parse_command("reject BUILD-002 touches wrong files")
        self.assertEqual(cmd.type, CommandType.REJECT_BUILD)
        self.assertEqual(cmd.args["build_id"], "BUILD-002")
        self.assertEqual(cmd.args["reason"], "touches wrong files")

    def test_reject_build_n_no_reason(self):
        cmd = parse_command("reject BUILD-002")
        self.assertEqual(cmd.type, CommandType.REJECT_BUILD)
        self.assertEqual(cmd.args["build_id"], "BUILD-002")
        self.assertEqual(cmd.args["reason"], "")

    def test_reject_build_case_insensitive(self):
        cmd = parse_command("reject build-005 scope too large")
        self.assertEqual(cmd.type, CommandType.REJECT_BUILD)
        self.assertEqual(cmd.args["build_id"], "BUILD-005")

    def test_reject_without_build_prefix_still_candidate(self):
        cmd = parse_command("reject some-queue-item")
        self.assertEqual(cmd.type, CommandType.REJECT_CANDIDATE)

    def test_reject_alone_routes_to_candidate(self):
        cmd = parse_command("reject")
        self.assertEqual(cmd.type, CommandType.REJECT_CANDIDATE)

    def test_no_routes_to_candidate(self):
        cmd = parse_command("no")
        self.assertEqual(cmd.type, CommandType.REJECT_CANDIDATE)


# ── Handler tests ─────────────────────────────────────────────────────────────

class TestHandleApproveBuild(unittest.TestCase):

    def _make_command(self, build_id="", notes=""):
        from peter.commands import Command
        return Command(
            type        = CommandType.APPROVE_BUILD,
            args        = {"build_id": build_id, "notes": notes},
            transport   = "cli",
            operator_id = "cli",
            raw_text    = f"approve {build_id}".strip(),
        )

    def test_missing_build_id_returns_error(self):
        cmd = self._make_command(build_id="")
        result = handle_approve_build(cmd)
        self.assertFalse(result.ok)
        self.assertIn("build ID", result.summary)

    def test_approver_error_propagated(self):
        cmd = self._make_command(build_id="BUILD-999")
        with patch("frank_lloyd.spec_approver.approve_build") as mock_approve:
            mock_approve.return_value = {
                "ok": False, "build_id": "BUILD-999",
                "archive_path": None, "error": "Build not found"
            }
            result = handle_approve_build(cmd)
        self.assertFalse(result.ok)
        self.assertIn("Build not found", result.summary)

    def test_success_returns_ok_response(self):
        cmd = self._make_command(build_id="BUILD-001", notes="all good")
        with patch("frank_lloyd.spec_approver.approve_build") as mock_approve:
            mock_approve.return_value = {
                "ok": True, "build_id": "BUILD-001",
                "archive_path": "/some/path", "error": None
            }
            result = handle_approve_build(cmd)
        self.assertTrue(result.ok)
        self.assertIn("BUILD-001", result.summary)
        self.assertIn("spec approved", result.summary)
        self.assertEqual(result.artifacts["archive_path"], "/some/path")

    def test_approver_called_with_correct_args(self):
        cmd = self._make_command(build_id="BUILD-003", notes="ship it")
        with patch("frank_lloyd.spec_approver.approve_build") as mock_approve:
            mock_approve.return_value = {
                "ok": True, "build_id": "BUILD-003",
                "archive_path": "/p", "error": None
            }
            handle_approve_build(cmd)
        mock_approve.assert_called_once_with("BUILD-003", notes="ship it")


class TestHandleRejectBuild(unittest.TestCase):

    def _make_command(self, build_id="", reason=""):
        from peter.commands import Command
        return Command(
            type        = CommandType.REJECT_BUILD,
            args        = {"build_id": build_id, "reason": reason},
            transport   = "cli",
            operator_id = "cli",
            raw_text    = f"reject {build_id} {reason}".strip(),
        )

    def test_missing_build_id_returns_error(self):
        cmd = self._make_command(build_id="", reason="too broad")
        result = handle_reject_build(cmd)
        self.assertFalse(result.ok)
        self.assertIn("build ID", result.summary)

    def test_missing_reason_returns_error(self):
        cmd = self._make_command(build_id="BUILD-001", reason="")
        result = handle_reject_build(cmd)
        self.assertFalse(result.ok)
        self.assertIn("reason", result.summary.lower())

    def test_approver_error_propagated(self):
        cmd = self._make_command(build_id="BUILD-999", reason="bad spec")
        with patch("frank_lloyd.spec_approver.reject_build") as mock_reject:
            mock_reject.return_value = {
                "ok": False, "build_id": "BUILD-999",
                "archive_path": None, "error": "Not in pending_review"
            }
            result = handle_reject_build(cmd)
        self.assertFalse(result.ok)
        self.assertIn("Not in pending_review", result.summary)

    def test_success_returns_ok_response(self):
        cmd = self._make_command(build_id="BUILD-002", reason="touches wrong files")
        with patch("frank_lloyd.spec_approver.reject_build") as mock_reject:
            mock_reject.return_value = {
                "ok": True, "build_id": "BUILD-002",
                "archive_path": "/some/path", "error": None
            }
            result = handle_reject_build(cmd)
        self.assertTrue(result.ok)
        self.assertIn("BUILD-002", result.summary)
        self.assertIn("rejected", result.summary)
        self.assertIn("touches wrong files", result.summary)

    def test_rejector_called_with_correct_args(self):
        cmd = self._make_command(build_id="BUILD-004", reason="scope too large")
        with patch("frank_lloyd.spec_approver.reject_build") as mock_reject:
            mock_reject.return_value = {
                "ok": True, "build_id": "BUILD-004",
                "archive_path": "/p", "error": None
            }
            handle_reject_build(cmd)
        mock_reject.assert_called_once_with("BUILD-004", reason="scope too large")


# ── Router dispatch tests ─────────────────────────────────────────────────────

class TestRouterDispatch(unittest.TestCase):

    def _make_authed_command(self, ctype, args):
        from peter.commands import Command
        return Command(
            type        = ctype,
            args        = args,
            transport   = "cli",
            operator_id = "cli",
            raw_text    = "",
        )

    def test_approve_build_dispatches_to_handler(self):
        from peter.router import route
        cmd = self._make_authed_command(
            CommandType.APPROVE_BUILD, {"build_id": "BUILD-001", "notes": ""}
        )
        with patch("peter.identity.is_approved", return_value=True):
            with patch("frank_lloyd.spec_approver.approve_build") as mock_fn:
                mock_fn.return_value = {
                    "ok": True, "build_id": "BUILD-001",
                    "archive_path": "/p", "error": None
                }
                result = route(cmd)
        self.assertTrue(result.ok)
        mock_fn.assert_called_once()

    def test_reject_build_dispatches_to_handler(self):
        from peter.router import route
        cmd = self._make_authed_command(
            CommandType.REJECT_BUILD, {"build_id": "BUILD-001", "reason": "bad"}
        )
        with patch("peter.identity.is_approved", return_value=True):
            with patch("frank_lloyd.spec_approver.reject_build") as mock_fn:
                mock_fn.return_value = {
                    "ok": True, "build_id": "BUILD-001",
                    "archive_path": "/p", "error": None
                }
                result = route(cmd)
        self.assertTrue(result.ok)
        mock_fn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
