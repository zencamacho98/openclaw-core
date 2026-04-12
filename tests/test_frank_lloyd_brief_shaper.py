# tests/test_frank_lloyd_brief_shaper.py
#
# Unit tests for frank_lloyd/brief_shaper.py
#
# Tests deterministic_shape() (no LM cost) and public shape() fallback behavior.

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from frank_lloyd.brief_shaper import ShapedBrief, deterministic_shape, shape, _extract_success_criterion


class TestDeterministicShape(unittest.TestCase):
    """Tests for the regex-based deterministic shaper (no LM)."""

    # ── mode classification ───────────────────────────────────────────────────

    def test_mode_build_is_default(self):
        b = deterministic_shape("Add a /stats endpoint that returns trade counts")
        self.assertEqual(b.mode, "build")
        self.assertFalse(b.needs_clarification)

    def test_mode_refactor_keyword(self):
        b = deterministic_shape("Refactor the trading loop to use a helper class")
        self.assertEqual(b.mode, "refactor")
        self.assertFalse(b.needs_clarification)

    def test_mode_cleanup_keyword(self):
        b = deterministic_shape("Clean up stale work stream entries in the sidebar")
        self.assertEqual(b.mode, "cleanup")
        self.assertFalse(b.needs_clarification)

    def test_mode_diagnose_keyword(self):
        b = deterministic_shape("Diagnose why Peter and Frank Lloyd feel disconnected")
        self.assertEqual(b.mode, "diagnose")
        self.assertFalse(b.needs_clarification)

    def test_mode_diagnose_broken_keyword(self):
        b = deterministic_shape("Figure out why the relay queue is broken in prod")
        self.assertEqual(b.mode, "diagnose")

    def test_mode_improve_keyword(self):
        b = deterministic_shape("Improve the apply summary to show affected files more clearly")
        self.assertEqual(b.mode, "improve")
        self.assertFalse(b.needs_clarification)

    def test_mode_monitor_keyword(self):
        b = deterministic_shape("Add logging for every spec generation attempt in the pipeline")
        self.assertEqual(b.mode, "monitor")
        self.assertFalse(b.needs_clarification)

    def test_mode_docs_keyword(self):
        b = deterministic_shape("Update the documentation for the relay module")
        self.assertEqual(b.mode, "docs")
        self.assertFalse(b.needs_clarification)

    def test_mode_rewrite_maps_to_refactor(self):
        b = deterministic_shape("Rewrite the neighborhood panel for the Frank Lloyd section")
        self.assertEqual(b.mode, "refactor")

    def test_mode_remove_maps_to_cleanup(self):
        b = deterministic_shape("Remove the dead code from the research ledger module")
        self.assertEqual(b.mode, "cleanup")

    # ── success criterion extraction ─────────────────────────────────────────

    def test_extracts_success_criterion_from_success_marker(self):
        b = deterministic_shape("Add a /stats endpoint. success: returns HTTP 200 with trade count")
        self.assertIn("HTTP 200", b.success_criterion)

    def test_extracts_success_criterion_from_done_when_marker(self):
        b = deterministic_shape("Add a health tab. done when: health badge is green")
        self.assertIn("green", b.success_criterion)

    def test_extracts_success_criterion_from_verify_marker(self):
        b = deterministic_shape("Add logging to spec generator. verify: logs appear in backend.log")
        self.assertIn("backend.log", b.success_criterion)

    def test_synthesizes_default_criterion_when_none_given(self):
        b = deterministic_shape("Add a /ping endpoint to the backend")
        self.assertTrue(len(b.success_criterion) > 0)
        self.assertFalse(b.needs_clarification)

    def test_default_criterion_for_refactor(self):
        b = deterministic_shape("Refactor the trading loop to extract a helper class")
        self.assertIn("test", b.success_criterion.lower())

    def test_default_criterion_for_diagnose(self):
        b = deterministic_shape("Diagnose why the spec generation fails intermittently")
        self.assertIn("root cause", b.success_criterion.lower())

    def test_default_criterion_for_monitor(self):
        b = deterministic_shape("Add observability metrics to the relay queue")
        self.assertIn("monitoring", b.success_criterion.lower())

    # ── needs_clarification ───────────────────────────────────────────────────

    def test_too_short_input_needs_clarification(self):
        b = deterministic_shape("fix this")
        self.assertTrue(b.needs_clarification)
        self.assertTrue(len(b.clarification_question) > 0)

    def test_vague_alone_phrase_needs_clarification(self):
        b = deterministic_shape("make it better")
        self.assertTrue(b.needs_clarification)

    def test_empty_after_strip_needs_clarification_from_shape(self):
        b = shape("")
        self.assertTrue(b.needs_clarification)
        self.assertFalse(b.lm_shaped)

    def test_description_trimmed_when_marker_present(self):
        b = deterministic_shape("Add a health endpoint. success: returns 200")
        # description should not include the success marker text
        self.assertNotIn("success:", b.description.lower())

    # ── ShapedBrief fields ────────────────────────────────────────────────────

    def test_returns_shaped_brief_instance(self):
        b = deterministic_shape("Add a /ping endpoint to the backend route")
        self.assertIsInstance(b, ShapedBrief)

    def test_lm_shaped_is_false_for_deterministic(self):
        b = deterministic_shape("Build a log viewer endpoint for Frank Lloyd")
        self.assertFalse(b.lm_shaped)

    def test_clarification_question_empty_when_not_needed(self):
        b = deterministic_shape("Build a log viewer endpoint for Frank Lloyd")
        self.assertFalse(b.needs_clarification)
        self.assertEqual(b.clarification_question, "")

    def test_description_preserved_when_no_marker(self):
        raw = "Add an admin command to reset the relay cursor"
        b = deterministic_shape(raw)
        self.assertEqual(b.description, raw)


class TestExtractSuccessCriterion(unittest.TestCase):
    """Tests for the private _extract_success_criterion helper."""

    def test_extracts_after_success_colon(self):
        self.assertIn("HTTP 200", _extract_success_criterion("Do X. success: HTTP 200"))

    def test_extracts_after_done_when(self):
        self.assertIn("badge", _extract_success_criterion("Do X. done when: badge is green"))

    def test_returns_empty_when_no_marker(self):
        self.assertEqual("", _extract_success_criterion("Just do this thing"))

    def test_case_insensitive(self):
        result = _extract_success_criterion("Do X. SUCCESS: it works")
        self.assertIn("it works", result)

    def test_verify_marker(self):
        result = _extract_success_criterion("Log it. verify: logs appear in file")
        self.assertIn("logs appear", result)


class TestShapeFallback(unittest.TestCase):
    """
    Tests for shape() when the LM is unavailable.
    shape() must always return a ShapedBrief without raising.
    """

    def test_shape_returns_shaped_brief(self):
        b = shape("Add a /status route to the Frank Lloyd backend module")
        self.assertIsInstance(b, ShapedBrief)

    def test_shape_graceful_when_lm_helper_raises(self):
        """Even with broken LM, shape() must not raise."""
        import frank_lloyd.brief_shaper as bs
        original = None
        try:
            import app.cost_warden as cw
            original = cw.LMHelper
            cw.LMHelper = None  # break import
        except Exception:
            pass
        try:
            b = shape("Add a /status route to the Frank Lloyd backend module")
            self.assertIsInstance(b, ShapedBrief)
        finally:
            if original is not None:
                cw.LMHelper = original

    def test_shape_empty_string_clarification(self):
        b = shape("  ")
        self.assertTrue(b.needs_clarification)
        self.assertFalse(b.lm_shaped)

    def test_shape_mode_consistency_with_deterministic(self):
        """Deterministic fallback should produce the same mode as deterministic_shape."""
        raw = "Refactor the campaign orchestrator to split concerns"
        b_det = deterministic_shape(raw)
        # shape() may use LM but if it falls back to deterministic, must match
        b_shape = shape(raw)
        if not b_shape.lm_shaped:
            self.assertEqual(b_shape.mode, b_det.mode)


class TestModeDefaults(unittest.TestCase):
    """All modes produce non-empty success_criterion defaults."""

    _SAMPLES = {
        "build":    "Add a new /health endpoint to the backend service",
        "refactor": "Refactor the research module to use a shared base class",
        "cleanup":  "Clean up old stale state from the campaign folder",
        "diagnose": "Diagnose why the spec generation pipeline breaks sometimes",
        "improve":  "Improve the apply summary to make it more readable",
        "monitor":  "Add telemetry logging to the auto-runner pipeline",
        "docs":     "Update the readme documentation for the relay module",
    }

    def test_all_modes_produce_nonempty_criterion(self):
        for mode, raw in self._SAMPLES.items():
            with self.subTest(mode=mode):
                b = deterministic_shape(raw)
                self.assertTrue(len(b.success_criterion) > 0, f"empty criterion for mode={mode}")
                self.assertFalse(b.needs_clarification, f"unexpected clarification for mode={mode}")


if __name__ == "__main__":
    unittest.main()
