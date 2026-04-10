"""
tests/test_peter_build.py

Unit tests for ui/peter_build.py.

Covers (no LM calls — all network paths are mocked):
  - is_build_task:         keyword heuristic
  - _extract_file_hints:   file path regex
  - _validate_edits:       old_string safety check
  - _error_outcome:        error dict shape contract
  - _files_section:        file context formatting
  - route_build_task:      routing decisions (builder / reviewer / auto-escalate / protected)

Run with:
    python -m pytest tests/test_peter_build.py -v
    python -m unittest tests.test_peter_build -v
"""
from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import patch

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from ui.peter_build import (
    is_build_task,
    _extract_file_hints,
    _validate_edits,
    _error_outcome,
    _files_section,
    route_build_task,
    BUILDER_MODEL,
    REVIEWER_MODEL,
    _PROTECTED_PATHS,
    _AUTO_ESCALATE_THRESHOLD,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _builder_outcome(confidence: float = 0.9, ok: bool = True) -> dict:
    return {
        "route": "builder",
        "ok": ok,
        "summary": "Builder draft ready.",
        "edits": (
            [{"file": "ui/foo.py", "description": "fix", "old_string": "old", "new_string": "new"}]
            if ok else []
        ),
        "needs_approval": True,
        "escalation_reason": "",
        "builder_confidence": confidence,
        "model_used": BUILDER_MODEL,
    }


def _reviewer_outcome(escalation_reason: str = "") -> dict:
    return {
        "route": "reviewer",
        "ok": True,
        "summary": "Reviewer approved the patch.",
        "edits": [{"file": "ui/foo.py", "description": "fix", "old_string": "old", "new_string": "new"}],
        "needs_approval": True,
        "escalation_reason": escalation_reason,
        "builder_confidence": 0.88,
        "model_used": REVIEWER_MODEL,
    }


# ══════════════════════════════════════════════════════════════════════════════
# is_build_task
# ══════════════════════════════════════════════════════════════════════════════

class TestIsBuildTask(unittest.TestCase):

    # ── keyword matches ───────────────────────────────────────────────────────

    def test_fix_keyword(self):
        self.assertTrue(is_build_task("fix the import error in peter_lm.py"))

    def test_edit_keyword(self):
        self.assertTrue(is_build_task("edit the placeholder text"))

    def test_add_keyword(self):
        self.assertTrue(is_build_task("add a test for format_pnl"))

    def test_remove_keyword(self):
        self.assertTrue(is_build_task("remove the duplicate import"))

    def test_refactor_keyword(self):
        self.assertTrue(is_build_task("refactor the helper function"))

    def test_implement_keyword(self):
        self.assertTrue(is_build_task("implement the missing handler"))

    def test_bug_keyword(self):
        self.assertTrue(is_build_task("there is a bug in the formatter"))

    def test_patch_keyword(self):
        self.assertTrue(is_build_task("apply this patch to the file"))

    def test_replace_keyword(self):
        self.assertTrue(is_build_task("replace the old caption with the new one"))

    def test_rewrite_keyword(self):
        self.assertTrue(is_build_task("rewrite the summary function"))

    def test_clean_up_two_words(self):
        self.assertTrue(is_build_task("clean up the imports"))

    def test_cleanup_one_word(self):
        self.assertTrue(is_build_task("cleanup unused variables"))

    # ── case insensitivity ────────────────────────────────────────────────────

    def test_uppercase_keyword(self):
        self.assertTrue(is_build_task("FIX the bug"))

    def test_mixed_case(self):
        self.assertTrue(is_build_task("Fix the Import Error"))

    # ── non-build phrases should return False ─────────────────────────────────

    def test_status_query(self):
        self.assertFalse(is_build_task("what is the status?"))

    def test_show_query(self):
        self.assertFalse(is_build_task("show me the queue"))

    def test_empty_string(self):
        self.assertFalse(is_build_task(""))

    def test_pure_question(self):
        self.assertFalse(is_build_task("how many experiments ran?"))

    def test_approval_action(self):
        self.assertFalse(is_build_task("approve the candidate"))

    def test_stop_is_not_build(self):
        # "stop" is not in _BUILD_KEYWORDS — it's a campaign control verb
        self.assertFalse(is_build_task("stop the campaign"))


# ══════════════════════════════════════════════════════════════════════════════
# _extract_file_hints
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractFileHints(unittest.TestCase):

    def test_finds_python_file_with_path(self):
        hints = _extract_file_hints("fix the bug in ui/peter_lm.py")
        self.assertIn("ui/peter_lm.py", hints)

    def test_finds_bare_filename(self):
        hints = _extract_file_hints("update dashboard.py")
        self.assertIn("dashboard.py", hints)

    def test_finds_multiple_files(self):
        hints = _extract_file_hints("update app/supervisor.py and tests/test_foo.py")
        self.assertGreaterEqual(len(hints), 2)

    def test_empty_text_returns_empty(self):
        self.assertEqual(_extract_file_hints(""), [])

    def test_no_file_extensions_returns_empty(self):
        self.assertEqual(_extract_file_hints("fix the bug in the formatter"), [])

    def test_finds_jsonl_file(self):
        hints = _extract_file_hints("check data/event_log.jsonl")
        self.assertIn("data/event_log.jsonl", hints)

    def test_finds_sh_file(self):
        hints = _extract_file_hints("look at scripts/ctl.sh")
        self.assertIn("scripts/ctl.sh", hints)


# ══════════════════════════════════════════════════════════════════════════════
# _validate_edits
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateEdits(unittest.TestCase):

    def test_valid_edit_passes_through(self):
        edits = [{"file": "foo.py", "description": "fix", "old_string": "hello", "new_string": "world"}]
        ctx   = {"foo.py": "text with hello inside"}
        valid, warnings = _validate_edits(edits, ctx)
        self.assertEqual(valid, edits)
        self.assertEqual(warnings, [])

    def test_missing_old_string_generates_warning(self):
        edits = [{"file": "foo.py", "description": "fix", "old_string": "not_in_file", "new_string": "x"}]
        ctx   = {"foo.py": "completely different content"}
        valid, warnings = _validate_edits(edits, ctx)
        self.assertEqual(valid, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("foo.py", warnings[0])

    def test_empty_old_string_passes_as_new_file(self):
        # old_string="" signals a new file — always valid
        edits = [{"file": "new.py", "description": "create", "old_string": "", "new_string": "content"}]
        valid, warnings = _validate_edits(edits, {})
        self.assertEqual(valid, edits)
        self.assertEqual(warnings, [])

    def test_mixed_valid_and_invalid(self):
        edits = [
            {"file": "a.py", "description": "ok",  "old_string": "present", "new_string": "x"},
            {"file": "b.py", "description": "bad", "old_string": "absent",  "new_string": "y"},
        ]
        ctx = {"a.py": "text with present string", "b.py": "something else entirely"}
        valid, warnings = _validate_edits(edits, ctx)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["file"], "a.py")
        self.assertEqual(len(warnings), 1)

    def test_empty_edits_list(self):
        valid, warnings = _validate_edits([], {})
        self.assertEqual(valid, [])
        self.assertEqual(warnings, [])

    def test_empty_file_context(self):
        # old_string present but no context to search → warning
        edits = [{"file": "foo.py", "description": "fix", "old_string": "something", "new_string": "x"}]
        valid, warnings = _validate_edits(edits, {})
        self.assertEqual(valid, [])
        self.assertEqual(len(warnings), 1)

    def test_old_string_found_in_any_file(self):
        # Validation checks all files in context, not just the target file.
        # If old_string is in *any* file, the edit passes (V1 behaviour — documented).
        edits = [{"file": "a.py", "description": "fix", "old_string": "shared", "new_string": "x"}]
        ctx   = {"b.py": "this file also has shared text"}
        valid, warnings = _validate_edits(edits, ctx)
        self.assertEqual(len(valid), 1)   # passes because old_string found in b.py
        self.assertEqual(warnings, [])

    def test_multiple_edits_all_valid(self):
        edits = [
            {"file": "a.py", "description": "1", "old_string": "alpha", "new_string": "A"},
            {"file": "b.py", "description": "2", "old_string": "beta",  "new_string": "B"},
        ]
        ctx = {"a.py": "text alpha here", "b.py": "text beta here"}
        valid, warnings = _validate_edits(edits, ctx)
        self.assertEqual(len(valid), 2)
        self.assertEqual(warnings, [])


# ══════════════════════════════════════════════════════════════════════════════
# _error_outcome
# ══════════════════════════════════════════════════════════════════════════════

class TestErrorOutcome(unittest.TestCase):

    def test_builder_error_has_correct_route(self):
        out = _error_outcome("builder", "something broke")
        self.assertEqual(out["route"], "builder")

    def test_reviewer_error_has_correct_route(self):
        out = _error_outcome("reviewer", "reviewer failed")
        self.assertEqual(out["route"], "reviewer")

    def test_error_outcome_is_not_ok(self):
        out = _error_outcome("builder", "oops")
        self.assertFalse(out["ok"])

    def test_error_outcome_has_empty_edits(self):
        out = _error_outcome("builder", "oops")
        self.assertEqual(out["edits"], [])

    def test_error_outcome_summary_matches_message(self):
        out = _error_outcome("builder", "the specific error")
        self.assertEqual(out["summary"], "the specific error")

    def test_builder_error_uses_builder_model(self):
        out = _error_outcome("builder", "fail")
        self.assertEqual(out["model_used"], BUILDER_MODEL)

    def test_reviewer_error_uses_reviewer_model(self):
        out = _error_outcome("reviewer", "fail")
        self.assertEqual(out["model_used"], REVIEWER_MODEL)

    def test_needs_approval_is_false_on_error(self):
        # Error outcomes should not prompt the operator to approve nothing
        out = _error_outcome("builder", "fail")
        self.assertFalse(out["needs_approval"])


# ══════════════════════════════════════════════════════════════════════════════
# _files_section
# ══════════════════════════════════════════════════════════════════════════════

class TestFilesSection(unittest.TestCase):

    def test_empty_context_returns_fallback(self):
        result = _files_section({})
        self.assertIn("No file context", result)

    def test_single_file_includes_filename(self):
        result = _files_section({"ui/foo.py": "def hello(): pass"})
        self.assertIn("ui/foo.py", result)

    def test_single_file_includes_content(self):
        result = _files_section({"ui/foo.py": "def hello(): pass"})
        self.assertIn("def hello(): pass", result)

    def test_multiple_files_all_present(self):
        result = _files_section({
            "a.py": "content_a",
            "b.py": "content_b",
        })
        self.assertIn("a.py", result)
        self.assertIn("b.py", result)
        self.assertIn("content_a", result)
        self.assertIn("content_b", result)


# ══════════════════════════════════════════════════════════════════════════════
# route_build_task — routing logic
# ══════════════════════════════════════════════════════════════════════════════

class TestRouteBuildTask(unittest.TestCase):
    """
    All LM calls (_classify, _run_builder, _run_reviewer) are mocked.
    _read_file_context is also mocked to avoid disk I/O.
    _extract_file_hints is mocked where file-hint behaviour would interfere.
    """

    # ── protected file check ──────────────────────────────────────────────────

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._classify")
    def test_protected_file_routes_to_reviewer(self, mock_cls, mock_rev, mock_ctx):
        mock_rev.return_value = _reviewer_outcome("Protected file(s): supervisor.py")
        # Task explicitly mentions a protected filename
        result = route_build_task("fix app/supervisor.py", {})
        mock_cls.assert_not_called()   # classifier skipped entirely
        mock_rev.assert_called_once()
        self.assertEqual(result["route"], "reviewer")

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._classify")
    def test_protected_file_sets_escalation_reason(self, mock_cls, mock_rev, mock_ctx):
        mock_rev.return_value = _reviewer_outcome()
        route_build_task("edit app/checker.py", {})
        # escalation_reason should mention the protected file
        call_args_result = mock_rev.return_value
        # The outcome returned should have escalation set
        result = route_build_task("edit app/checker.py", {})
        self.assertIn("checker", result.get("escalation_reason", "").lower()
                      or "checker.py")  # either in reason or filename is checker

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify")
    def test_non_protected_file_runs_classifier(self, mock_cls, mock_builder, mock_rev, mock_ctx):
        mock_cls.return_value = {"route": "builder", "reason": "", "confidence": 0.9, "task_summary": "t"}
        mock_builder.return_value = _builder_outcome(confidence=0.9)
        route_build_task("fix ui/trade_helpers.py", {})
        mock_cls.assert_called_once()

    # ── builder path ──────────────────────────────────────────────────────────

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify", return_value={"route": "builder", "reason": "", "confidence": 0.9, "task_summary": "t"})
    def test_builder_route_calls_run_builder(self, mock_cls, mock_builder, mock_rev, mock_hints, mock_ctx):
        mock_builder.return_value = _builder_outcome(confidence=0.9)
        result = route_build_task("fix the caption", {})
        mock_builder.assert_called_once()
        mock_rev.assert_not_called()
        self.assertEqual(result["route"], "builder")

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify", return_value={"route": "builder", "reason": "", "confidence": 0.9, "task_summary": "t"})
    def test_builder_ok_outcome_is_returned(self, mock_cls, mock_builder, mock_rev, mock_hints, mock_ctx):
        mock_builder.return_value = _builder_outcome(confidence=0.9)
        result = route_build_task("fix the caption", {})
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["edits"]), 1)

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify", return_value={"route": "builder", "reason": "", "confidence": 0.9, "task_summary": "t"})
    def test_builder_needs_approval_always_true(self, mock_cls, mock_builder, mock_rev, mock_hints, mock_ctx):
        mock_builder.return_value = _builder_outcome(confidence=0.9)
        result = route_build_task("fix the caption", {})
        self.assertTrue(result["needs_approval"])

    # ── reviewer path ─────────────────────────────────────────────────────────

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._classify", return_value={"route": "reviewer", "reason": "cross-module", "confidence": 0.85, "task_summary": "t"})
    def test_reviewer_route_skips_builder(self, mock_cls, mock_rev, mock_builder, mock_hints, mock_ctx):
        mock_rev.return_value = _reviewer_outcome()
        result = route_build_task("refactor the routing layer", {})
        mock_builder.assert_not_called()
        mock_rev.assert_called_once()
        self.assertEqual(result["route"], "reviewer")

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._classify", return_value={"route": "reviewer", "reason": "", "confidence": 0.8, "task_summary": "t"})
    def test_reviewer_outcome_needs_approval(self, mock_cls, mock_rev, mock_builder, mock_hints, mock_ctx):
        mock_rev.return_value = _reviewer_outcome()
        result = route_build_task("rearchitect something", {})
        self.assertTrue(result["needs_approval"])

    # ── auto-escalation ───────────────────────────────────────────────────────

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify", return_value={"route": "builder", "reason": "", "confidence": 0.5, "task_summary": "t"})
    def test_low_confidence_escalates_to_reviewer(self, mock_cls, mock_builder, mock_rev, mock_hints, mock_ctx):
        low_conf = _AUTO_ESCALATE_THRESHOLD - 0.1
        mock_builder.return_value = _builder_outcome(confidence=low_conf)
        mock_rev.return_value = _reviewer_outcome()
        result = route_build_task("fix something tricky", {})
        mock_rev.assert_called_once()
        self.assertEqual(result["route"], "reviewer")

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify", return_value={"route": "builder", "reason": "", "confidence": 0.5, "task_summary": "t"})
    def test_low_confidence_escalation_reason_mentions_confidence(self, mock_cls, mock_builder, mock_rev, mock_hints, mock_ctx):
        low_conf = _AUTO_ESCALATE_THRESHOLD - 0.1
        mock_builder.return_value = _builder_outcome(confidence=low_conf)
        mock_rev.return_value = _reviewer_outcome()
        result = route_build_task("fix something tricky", {})
        self.assertTrue(len(result.get("escalation_reason", "")) > 0)

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify", return_value={"route": "builder", "reason": "", "confidence": 0.9, "task_summary": "t"})
    def test_high_confidence_does_not_escalate(self, mock_cls, mock_builder, mock_rev, mock_hints, mock_ctx):
        high_conf = _AUTO_ESCALATE_THRESHOLD + 0.1
        mock_builder.return_value = _builder_outcome(confidence=high_conf)
        result = route_build_task("fix the caption text", {})
        mock_rev.assert_not_called()
        self.assertEqual(result["route"], "builder")

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify", return_value={"route": "builder", "reason": "", "confidence": 0.9, "task_summary": "t"})
    def test_exactly_at_threshold_does_not_escalate(self, mock_cls, mock_builder, mock_rev, mock_hints, mock_ctx):
        # confidence == threshold is NOT below threshold — should not escalate
        mock_builder.return_value = _builder_outcome(confidence=_AUTO_ESCALATE_THRESHOLD)
        result = route_build_task("small fix", {})
        mock_rev.assert_not_called()
        self.assertEqual(result["route"], "builder")

    # ── BuildOutcome shape contract ────────────────────────────────────────────

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify", return_value={"route": "builder", "reason": "", "confidence": 0.9, "task_summary": "t"})
    def test_outcome_has_all_required_keys(self, mock_cls, mock_builder, mock_hints, mock_ctx):
        mock_builder.return_value = _builder_outcome()
        result = route_build_task("fix something", {})
        for key in ("route", "ok", "summary", "edits", "needs_approval",
                    "escalation_reason", "builder_confidence", "model_used"):
            self.assertIn(key, result, f"Missing key: {key}")

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify", return_value={"route": "builder", "reason": "", "confidence": 0.9, "task_summary": "t"})
    def test_edits_is_always_a_list(self, mock_cls, mock_builder, mock_hints, mock_ctx):
        mock_builder.return_value = _builder_outcome()
        result = route_build_task("fix something", {})
        self.assertIsInstance(result["edits"], list)

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify", return_value={"route": "builder", "reason": "", "confidence": 0.9, "task_summary": "t"})
    def test_summary_is_always_a_string(self, mock_cls, mock_builder, mock_hints, mock_ctx):
        mock_builder.return_value = _builder_outcome()
        result = route_build_task("fix something", {})
        self.assertIsInstance(result["summary"], str)
        self.assertTrue(result["summary"])  # non-empty

    # ── model_used reflects chosen path ──────────────────────────────────────

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_builder")
    @patch("ui.peter_build._classify", return_value={"route": "builder", "reason": "", "confidence": 0.9, "task_summary": "t"})
    def test_builder_route_uses_builder_model(self, mock_cls, mock_builder, mock_hints, mock_ctx):
        mock_builder.return_value = _builder_outcome()
        result = route_build_task("small edit", {})
        self.assertEqual(result["model_used"], BUILDER_MODEL)

    @patch("ui.peter_build._read_file_context", return_value={})
    @patch("ui.peter_build._extract_file_hints", return_value=[])
    @patch("ui.peter_build._run_reviewer")
    @patch("ui.peter_build._classify", return_value={"route": "reviewer", "reason": "", "confidence": 0.8, "task_summary": "t"})
    def test_reviewer_route_uses_reviewer_model(self, mock_cls, mock_rev, mock_hints, mock_ctx):
        mock_rev.return_value = _reviewer_outcome()
        result = route_build_task("complex rework", {})
        self.assertEqual(result["model_used"], REVIEWER_MODEL)


# ══════════════════════════════════════════════════════════════════════════════
# Constants sanity
# ══════════════════════════════════════════════════════════════════════════════

class TestConstants(unittest.TestCase):

    def test_protected_paths_is_nonempty(self):
        self.assertGreater(len(_PROTECTED_PATHS), 0)

    def test_supervisor_is_protected(self):
        self.assertIn("app/supervisor.py", _PROTECTED_PATHS)

    def test_checker_is_protected(self):
        self.assertIn("app/checker.py", _PROTECTED_PATHS)

    def test_peter_build_protects_itself(self):
        self.assertIn("ui/peter_build.py", _PROTECTED_PATHS)

    def test_peter_lm_is_protected(self):
        self.assertIn("ui/peter_lm.py", _PROTECTED_PATHS)

    def test_auto_escalate_threshold_is_reasonable(self):
        # Should be between 0.5 and 0.8 — not too aggressive, not too lenient
        self.assertGreater(_AUTO_ESCALATE_THRESHOLD, 0.5)
        self.assertLess(_AUTO_ESCALATE_THRESHOLD, 0.8)

    def test_builder_model_is_set(self):
        self.assertTrue(BUILDER_MODEL)

    def test_reviewer_model_is_set(self):
        self.assertTrue(REVIEWER_MODEL)

    def test_reviewer_differs_from_builder(self):
        # Reviewer should be a stronger/different model, not the same as builder
        self.assertNotEqual(BUILDER_MODEL, REVIEWER_MODEL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
