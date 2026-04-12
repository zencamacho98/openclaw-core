# tests/test_frank_lloyd_apply_summary.py
#
# Unit tests for frank_lloyd/apply_summary.py
#
# Tests the apply summary generator: caching, LM parsing,
# deterministic fallback, and helper functions.

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import frank_lloyd.apply_summary as apply_summary


class TestReadHelpers(unittest.TestCase):
    def test_read_text_exists(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "file.txt"
            p.write_text("hello", encoding="utf-8")
            self.assertEqual(apply_summary._read_text(p), "hello")

    def test_read_text_missing(self):
        p = pathlib.Path("/nonexistent/path/file.txt")
        self.assertEqual(apply_summary._read_text(p), "")

    def test_read_json_exists(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "data.json"
            p.write_text('{"key": "val"}', encoding="utf-8")
            self.assertEqual(apply_summary._read_json(p), {"key": "val"})

    def test_read_json_missing(self):
        p = pathlib.Path("/nonexistent/path/data.json")
        self.assertIsNone(apply_summary._read_json(p))

    def test_read_json_malformed(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "bad.json"
            p.write_text("not json{{{", encoding="utf-8")
            self.assertIsNone(apply_summary._read_json(p))


class TestExtractSpecClassification(unittest.TestCase):
    def test_extracts_build_type_section(self):
        spec = (
            "build_id: BUILD-001\n"
            "\n"
            "# ── Build classification ────\n"
            "build_type: new_file\n"
            "risk_level: low\n"
            "\n"
            "# ── File set ────────────────\n"
        )
        result = apply_summary._extract_spec_classification(spec)
        self.assertIn("risk_level", result)

    def test_fallback_on_no_match(self):
        spec = "title: something\ndescription: blah"
        # Should not crash, returns something
        result = apply_summary._extract_spec_classification(spec)
        self.assertIsInstance(result, str)


class TestExtractFieldFromSpec(unittest.TestCase):
    def test_extracts_risk_level(self):
        spec = "risk_level: medium\n"
        self.assertEqual(apply_summary._extract_field_from_spec(spec, "risk_level"), "medium")

    def test_extracts_quoted(self):
        spec = 'risk_level: "low"\n'
        self.assertEqual(apply_summary._extract_field_from_spec(spec, "risk_level"), "low")

    def test_missing_field(self):
        spec = "build_type: new_file\n"
        self.assertIsNone(apply_summary._extract_field_from_spec(spec, "risk_level"))


class TestDeterministicSummary(unittest.TestCase):
    def test_returns_dict_with_all_keys(self):
        manifest = {"files_generated": ["draft_module.py"], "task_class": "CODE_DRAFT_LOW"}
        spec_yaml = "risk_level: low\n"
        request_json = {"description": "Add a stats endpoint"}
        result = apply_summary._deterministic_summary(
            "BUILD-001", manifest, spec_yaml, request_json
        )
        expected_keys = {"what_built", "problem", "files", "risk", "validation", "on_apply", "uncertainty", "target_path"}
        self.assertEqual(set(result.keys()), expected_keys)

    def test_uses_description_for_what_built(self):
        result = apply_summary._deterministic_summary(
            "BUILD-001",
            {"files_generated": ["draft_module.py"], "task_class": "CODE_DRAFT_LOW"},
            "risk_level: low\n",
            {"description": "Add a stats endpoint to the API"},
        )
        self.assertIn("stats", result["what_built"])

    def test_handles_missing_inputs(self):
        result = apply_summary._deterministic_summary("BUILD-001", None, "", None)
        self.assertIsInstance(result, dict)
        self.assertIn("what_built", result)


class TestParseSummary(unittest.TestCase):
    VALID_SUMMARY = {
        "what_built":   "A stats endpoint",
        "problem":      "No stats were available",
        "files":        ["frank_lloyd/stats.py"],
        "risk":         "Low — new isolated file",
        "validation":   "Spec validated, new file only",
        "on_apply":     "draft_module.py will be copied",
        "uncertainty":  "Needs integration test",
        "target_path":  "frank_lloyd/stats.py",
    }

    def test_valid_json(self):
        content = json.dumps(self.VALID_SUMMARY)
        result = apply_summary._parse_summary(content, {}, "")
        self.assertEqual(result["what_built"], "A stats endpoint")

    def test_strips_markdown_fences(self):
        content = "```json\n" + json.dumps(self.VALID_SUMMARY) + "\n```"
        result = apply_summary._parse_summary(content, {}, "")
        self.assertEqual(result["what_built"], "A stats endpoint")

    def test_fallback_on_bad_json(self):
        result = apply_summary._parse_summary("not json at all", {}, "")
        # Falls back to deterministic summary which must still have required keys
        self.assertIn("what_built", result)

    def test_fallback_on_missing_keys(self):
        content = json.dumps({"what_built": "something"})  # missing other keys
        result = apply_summary._parse_summary(content, {}, "")
        self.assertIn("risk", result)  # deterministic fallback filled it in


class TestGenerateApplySummary(unittest.TestCase):
    """Test the main generate_apply_summary function with mocked dependencies."""

    def _make_staging(self, td_path, build_id):
        """Create a minimal staging directory with required artifacts."""
        stage2_dir = td_path / build_id / "stage2"
        stage2_dir.mkdir(parents=True)
        manifest = {
            "build_id":        build_id,
            "stage":           2,
            "task_class":      "CODE_DRAFT_LOW",
            "model_used":      "openai/gpt-4o-mini",
            "files_generated": ["draft_module.py", "draft_notes.md"],
            "staging_path":    str(stage2_dir),
            "status":          "draft_generated",
        }
        (stage2_dir / "draft_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (stage2_dir / "draft_module.py").write_text("def hello(): pass\n", encoding="utf-8")
        (stage2_dir / "draft_notes.md").write_text("# Notes\nLooks good.\n", encoding="utf-8")
        return stage2_dir

    def test_returns_ok_with_lm_success(self):
        import frank_lloyd.apply_summary as _m
        summary_content = json.dumps({
            "what_built":   "test module",
            "problem":      "none",
            "files":        ["draft_module.py"],
            "risk":         "low",
            "validation":   "passed",
            "on_apply":     "file copied",
            "uncertainty":  "minimal",
            "target_path":  "frank_lloyd/test.py",
        })

        mock_lm_result = MagicMock()
        mock_lm_result.ok = True
        mock_lm_result.content = summary_content

        mock_lm_helper = MagicMock()
        mock_lm_helper.return_value.call.return_value = mock_lm_result

        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            self._make_staging(td_path, "BUILD-001")

            with (
                patch.object(_m, "_STAGING",  td_path),
                patch.object(_m, "_ARCHIVES", td_path),  # no archive needed
                patch("app.cost_warden.LMHelper", mock_lm_helper),
            ):
                result = _m.generate_apply_summary("BUILD-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["what_built"], "test module")
        self.assertFalse(result["cached"])

    def test_returns_cached_result_when_available(self):
        import frank_lloyd.apply_summary as _m

        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            stage2_dir = self._make_staging(td_path, "BUILD-002")
            cached_payload = {
                "build_id":     "BUILD-002",
                "generated_at": "2026-04-11T00:00:00+00:00",
                "lm_ok":        True,
                "summary": {
                    "what_built":  "cached module",
                    "problem":     "x",
                    "files":       [],
                    "risk":        "low",
                    "validation":  "y",
                    "on_apply":    "z",
                    "uncertainty": "none",
                    "target_path": "",
                },
            }
            (stage2_dir / "apply_summary.json").write_text(
                json.dumps(cached_payload), encoding="utf-8"
            )

            with (
                patch.object(_m, "_STAGING",  td_path),
                patch.object(_m, "_ARCHIVES", td_path),
            ):
                result = _m.generate_apply_summary("BUILD-002", force=False)

        self.assertTrue(result["ok"])
        self.assertTrue(result["cached"])
        self.assertEqual(result["summary"]["what_built"], "cached module")

    def test_force_regenerates_even_with_cache(self):
        import frank_lloyd.apply_summary as _m

        summary_content = json.dumps({
            "what_built":   "fresh module",
            "problem":      "none",
            "files":        [],
            "risk":         "low",
            "validation":   "passed",
            "on_apply":     "copied",
            "uncertainty":  "minimal",
            "target_path":  "",
        })
        mock_lm_result = MagicMock()
        mock_lm_result.ok = True
        mock_lm_result.content = summary_content
        mock_lm_helper = MagicMock()
        mock_lm_helper.return_value.call.return_value = mock_lm_result

        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            stage2_dir = self._make_staging(td_path, "BUILD-003")
            # Write stale cache
            (stage2_dir / "apply_summary.json").write_text(
                json.dumps({"summary": {"what_built": "old"}}), encoding="utf-8"
            )

            with (
                patch.object(_m, "_STAGING",  td_path),
                patch.object(_m, "_ARCHIVES", td_path),
                patch("app.cost_warden.LMHelper", mock_lm_helper),
            ):
                result = _m.generate_apply_summary("BUILD-003", force=True)

        self.assertTrue(result["ok"])
        self.assertFalse(result["cached"])
        self.assertEqual(result["summary"]["what_built"], "fresh module")

    def test_returns_error_when_manifest_missing(self):
        import frank_lloyd.apply_summary as _m

        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            # Don't create any staging artifacts
            with (
                patch.object(_m, "_STAGING",  td_path),
                patch.object(_m, "_ARCHIVES", td_path),
            ):
                result = _m.generate_apply_summary("BUILD-999")

        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_uses_deterministic_fallback_when_lm_fails(self):
        import frank_lloyd.apply_summary as _m

        mock_lm_result = MagicMock()
        mock_lm_result.ok = False
        mock_lm_result.error = "timeout"
        mock_lm_helper = MagicMock()
        mock_lm_helper.return_value.call.return_value = mock_lm_result

        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            self._make_staging(td_path, "BUILD-004")

            with (
                patch.object(_m, "_STAGING",  td_path),
                patch.object(_m, "_ARCHIVES", td_path),
                patch("app.cost_warden.LMHelper", mock_lm_helper),
            ):
                result = _m.generate_apply_summary("BUILD-004")

        # ok=True even on LM failure — deterministic fallback is used
        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["summary"])
        self.assertIn("what_built", result["summary"])


if __name__ == "__main__":
    unittest.main()
