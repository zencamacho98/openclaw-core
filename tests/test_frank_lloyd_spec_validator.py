"""
tests/test_frank_lloyd_spec_validator.py

Tests for the Frank Lloyd deterministic spec validation layer.

Covers all 6 rules in spec_validator.py:
  Rule 1 — build_type: aliases, vocabulary, missing
  Rule 2 — architecture_layer: vocabulary
  Rule 3 — risk_level: deterministic floor from affected_files
           - critical when app/main.py or other critical files in modified set
           - critical when off-limits files found
           - high when any existing file modified (non-critical)
           - medium when new file requires integration
           - low when new isolated file
           - floor wins if > LM value; LM value kept if >= floor
  Rule 4 — blast_radius_failure_mode: forced loud when critical files touched
  Rule 5 — sentinel_test_file: tests/*.py format validation + derivation
  Rule 6 — required fields: spec fields + preflight fields
  Clean spec — zero corrections when everything is valid

Run with:
    python -m unittest tests.test_frank_lloyd_spec_validator -v
"""
from __future__ import annotations

import pathlib
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from frank_lloyd.spec_validator import (
    validate_and_correct,
    VALID_BUILD_TYPES,
    VALID_RISK_LEVELS,
    VALID_ARCH_LAYERS,
    VALID_FAILURE_MODES,
)


# ── Minimal valid spec ─────────────────────────────────────────────────────────

def _valid_spec(**overrides) -> dict:
    """Return a minimal spec that passes all 6 rules, with optional overrides."""
    base = {
        "build_type":               "new_service",
        "risk_level":               "low",
        "architecture_layer":       "operating_services",
        "blast_radius_failure_mode": "loud",
        "sentinel_test_file":       "tests/test_my_service.py",
        "sentinel_coverage_note":   "Covers the new service endpoints.",
        "affected_files_new":       [{"path": "app/my_service.py", "purpose": "New service"}],
        "affected_files_modified":  [],
        "reuse_decisions":          [],
        "layer_justification":      "Operating service layer for backstage tools.",
        "blast_radius_rollback":    "Delete app/my_service.py.",
        "blast_radius_scope":       "Isolated to new service only.",
        "preflight_q1": "No existing capability.",
        "preflight_q2": "New operating service.",
        "preflight_q3": "One new file.",
        "preflight_q5": "Operating services layer.",
        "preflight_q6": "Loud failure on startup.",
        "preflight_q7": "app/my_service.py → tests/test_my_service.py",
    }
    base.update(overrides)
    return base


def _req() -> dict:
    return {
        "title": "My service",
        "description": "Add a new isolated service.",
        "success_criteria": "Service starts and responds to requests.",
    }


# ── Rule 1: build_type ────────────────────────────────────────────────────────

class TestRuleBuildType(unittest.TestCase):

    def _run(self, spec_overrides: dict, offlimits: list[str] = None):
        spec, corrections = validate_and_correct(
            _valid_spec(**spec_overrides), _req(), offlimits or []
        )
        return spec, corrections

    def test_valid_build_type_no_correction(self) -> None:
        for bt in VALID_BUILD_TYPES:
            with self.subTest(build_type=bt):
                spec, corrections = self._run({"build_type": bt})
                bt_corrections = [c for c in corrections if c["field"] == "build_type"]
                self.assertEqual(bt_corrections, [],
                                 f"Unexpected correction for valid build_type '{bt}'")

    def test_alias_new_route_becomes_platform_capability(self) -> None:
        spec, corrections = self._run({"build_type": "new_route"})
        self.assertEqual(spec["build_type"], "platform_capability")
        self.assertTrue(any(c["field"] == "build_type" for c in corrections))

    def test_alias_new_module_becomes_platform_capability(self) -> None:
        spec, corrections = self._run({"build_type": "new_module"})
        self.assertEqual(spec["build_type"], "platform_capability")

    def test_alias_modify_existing_becomes_modification(self) -> None:
        spec, corrections = self._run({"build_type": "modify_existing"})
        self.assertEqual(spec["build_type"], "modification")

    def test_unknown_build_type_becomes_unknown(self) -> None:
        spec, corrections = self._run({"build_type": "wizard_thing"})
        self.assertEqual(spec["build_type"], "unknown")
        self.assertTrue(any(c["field"] == "build_type" for c in corrections))

    def test_missing_build_type_becomes_unknown(self) -> None:
        spec, corrections = self._run({"build_type": ""})
        self.assertEqual(spec["build_type"], "unknown")
        self.assertTrue(any(c["field"] == "build_type" for c in corrections))

    def test_correction_records_original_value(self) -> None:
        _, corrections = self._run({"build_type": "new_route"})
        bt_corr = next(c for c in corrections if c["field"] == "build_type")
        self.assertEqual(bt_corr["original"], "new_route")
        self.assertEqual(bt_corr["corrected"], "platform_capability")


# ── Rule 2: architecture_layer ────────────────────────────────────────────────

class TestRuleArchLayer(unittest.TestCase):

    def _run(self, spec_overrides: dict):
        spec, corrections = validate_and_correct(
            _valid_spec(**spec_overrides), _req(), []
        )
        return spec, corrections

    def test_valid_arch_layers_no_correction(self) -> None:
        for layer in VALID_ARCH_LAYERS:
            with self.subTest(layer=layer):
                spec, corrections = self._run({"architecture_layer": layer})
                layer_corrections = [c for c in corrections if c["field"] == "architecture_layer"]
                self.assertEqual(layer_corrections, [],
                                 f"Unexpected correction for valid layer '{layer}'")

    def test_invalid_layer_becomes_unknown(self) -> None:
        spec, corrections = self._run({"architecture_layer": "frontend"})
        self.assertEqual(spec["architecture_layer"], "unknown")
        self.assertTrue(any(c["field"] == "architecture_layer" for c in corrections))

    def test_empty_layer_becomes_unknown(self) -> None:
        spec, corrections = self._run({"architecture_layer": ""})
        self.assertEqual(spec["architecture_layer"], "unknown")

    def test_layer_correction_records_original(self) -> None:
        _, corrections = self._run({"architecture_layer": "services"})
        corr = next(c for c in corrections if c["field"] == "architecture_layer")
        self.assertEqual(corr["original"], "services")
        self.assertEqual(corr["corrected"], "unknown")


# ── Rule 3: risk_level ────────────────────────────────────────────────────────

class TestRuleRiskLevel(unittest.TestCase):

    def _run(self, spec_overrides: dict, offlimits: list[str] = None):
        spec, corrections = validate_and_correct(
            _valid_spec(**spec_overrides), _req(), offlimits or []
        )
        return spec, corrections

    # Critical file in modified set → critical
    def test_main_py_modified_forces_critical(self) -> None:
        spec, corrections = self._run({
            "risk_level": "low",
            "affected_files_modified": [{"path": "app/main.py", "change": "add router"}],
        })
        self.assertEqual(spec["risk_level"], "critical")
        self.assertTrue(any(c["field"] == "risk_level" for c in corrections))

    def test_ctl_sh_modified_forces_critical(self) -> None:
        spec, corrections = self._run({
            "risk_level": "medium",
            "affected_files_modified": [{"path": "scripts/ctl.sh", "change": "add cmd"}],
        })
        self.assertEqual(spec["risk_level"], "critical")

    def test_loop_py_modified_forces_critical(self) -> None:
        spec, corrections = self._run({
            "risk_level": "high",
            "affected_files_modified": [{"path": "app/loop.py", "change": "tweak"}],
        })
        self.assertEqual(spec["risk_level"], "critical")

    def test_neighborhood_py_modified_forces_critical(self) -> None:
        spec, corrections = self._run({
            "risk_level": "low",
            "affected_files_modified": [{"path": "app/routes/neighborhood.py", "change": "fix"}],
        })
        self.assertEqual(spec["risk_level"], "critical")

    # Off-limits files → critical regardless
    def test_offlimits_found_forces_critical(self) -> None:
        spec, corrections = self._run(
            {"risk_level": "low", "affected_files_modified": []},
            offlimits=["app/main.py"],
        )
        self.assertEqual(spec["risk_level"], "critical")

    # Any existing file modified (non-critical) → at least high
    def test_non_critical_modification_forces_high(self) -> None:
        spec, corrections = self._run({
            "risk_level": "low",
            "affected_files_modified": [{"path": "app/state.py", "change": "refactor"}],
        })
        self.assertEqual(spec["risk_level"], "high")

    def test_lm_assessed_medium_corrected_to_high_when_modified(self) -> None:
        spec, corrections = self._run({
            "risk_level": "medium",
            "affected_files_modified": [{"path": "peter/handlers.py", "change": "add handler"}],
        })
        self.assertEqual(spec["risk_level"], "high")

    # New files only → low or medium
    def test_new_isolated_file_stays_low(self) -> None:
        spec, corrections = self._run({
            "risk_level": "low",
            "affected_files_new": [{"path": "frank_lloyd/new_module.py", "purpose": "new"}],
            "affected_files_modified": [],
        })
        self.assertEqual(spec["risk_level"], "low")
        risk_corrections = [c for c in corrections if c["field"] == "risk_level"]
        self.assertEqual(risk_corrections, [])

    # LM assessed higher than floor → LM value kept
    def test_lm_higher_than_floor_kept(self) -> None:
        # Floor = low (new isolated file), LM says medium — LM wins
        spec, corrections = self._run({
            "risk_level": "medium",
            "affected_files_new": [{"path": "frank_lloyd/new_module.py", "purpose": "new"}],
            "affected_files_modified": [],
        })
        self.assertEqual(spec["risk_level"], "medium")
        risk_corrections = [c for c in corrections if c["field"] == "risk_level"]
        self.assertEqual(risk_corrections, [])

    # LM assessed high (or critical) already — no downgrade
    def test_lm_already_critical_not_downgraded(self) -> None:
        spec, corrections = self._run({
            "risk_level": "critical",
            "affected_files_modified": [{"path": "app/main.py", "change": "add router"}],
        })
        self.assertEqual(spec["risk_level"], "critical")
        risk_corrections = [c for c in corrections if c["field"] == "risk_level"]
        self.assertEqual(risk_corrections, [])

    def test_invalid_risk_level_uses_floor(self) -> None:
        spec, corrections = self._run({
            "risk_level": "extreme",
            "affected_files_modified": [],
            "affected_files_new": [{"path": "frank_lloyd/thing.py", "purpose": "new"}],
        })
        # Floor = low (no modified, no integration)
        self.assertIn(spec["risk_level"], VALID_RISK_LEVELS)
        self.assertTrue(any(c["field"] == "risk_level" for c in corrections))

    # Correction record content
    def test_risk_correction_records_original_and_corrected(self) -> None:
        _, corrections = self._run({
            "risk_level": "low",
            "affected_files_modified": [{"path": "app/main.py", "change": "add router"}],
        })
        corr = next(c for c in corrections if c["field"] == "risk_level")
        self.assertEqual(corr["original"], "low")
        self.assertEqual(corr["corrected"], "critical")


# ── Rule 4: blast_radius_failure_mode ─────────────────────────────────────────

class TestRuleFailureMode(unittest.TestCase):

    def _run(self, spec_overrides: dict, offlimits: list[str] = None):
        spec, corrections = validate_and_correct(
            _valid_spec(**spec_overrides), _req(), offlimits or []
        )
        return spec, corrections

    def test_critical_file_forces_loud(self) -> None:
        spec, corrections = self._run({
            "blast_radius_failure_mode": "silent",
            "affected_files_modified": [{"path": "app/main.py", "change": "add router"}],
        })
        self.assertEqual(spec["blast_radius_failure_mode"], "loud")
        self.assertTrue(any(c["field"] == "blast_radius_failure_mode" for c in corrections))

    def test_critical_file_already_loud_no_correction(self) -> None:
        spec, corrections = self._run({
            "blast_radius_failure_mode": "loud",
            "affected_files_modified": [{"path": "app/main.py", "change": "add router"}],
        })
        fm_corrections = [c for c in corrections if c["field"] == "blast_radius_failure_mode"]
        self.assertEqual(fm_corrections, [])

    def test_invalid_mode_defaults_to_loud(self) -> None:
        spec, corrections = self._run({"blast_radius_failure_mode": "maybe"})
        self.assertEqual(spec["blast_radius_failure_mode"], "loud")
        self.assertTrue(any(c["field"] == "blast_radius_failure_mode" for c in corrections))

    def test_valid_silent_kept_when_no_critical_files(self) -> None:
        spec, corrections = self._run({
            "blast_radius_failure_mode": "silent",
            "affected_files_modified": [],
        })
        self.assertEqual(spec["blast_radius_failure_mode"], "silent")
        fm_corrections = [c for c in corrections if c["field"] == "blast_radius_failure_mode"]
        self.assertEqual(fm_corrections, [])

    def test_valid_loud_kept_no_correction(self) -> None:
        spec, corrections = self._run({
            "blast_radius_failure_mode": "loud",
            "affected_files_modified": [],
        })
        self.assertEqual(spec["blast_radius_failure_mode"], "loud")
        fm_corrections = [c for c in corrections if c["field"] == "blast_radius_failure_mode"]
        self.assertEqual(fm_corrections, [])


# ── Rule 5: sentinel_test_file ────────────────────────────────────────────────

class TestRuleSentinelScope(unittest.TestCase):

    def _run(self, spec_overrides: dict):
        spec, corrections = validate_and_correct(
            _valid_spec(**spec_overrides), _req(), []
        )
        return spec, corrections

    def test_valid_sentinel_path_no_correction(self) -> None:
        spec, corrections = self._run({"sentinel_test_file": "tests/test_my_thing.py"})
        sentinel_corrections = [c for c in corrections if c["field"] == "sentinel_test_file"]
        self.assertEqual(sentinel_corrections, [])

    def test_missing_tests_prefix_is_corrected(self) -> None:
        spec, corrections = self._run({
            "sentinel_test_file": "test_my_thing.py",
            "affected_files_new": [{"path": "app/my_thing.py", "purpose": "new"}],
        })
        self.assertTrue(spec["sentinel_test_file"].startswith("tests/"))
        self.assertTrue(any(c["field"] == "sentinel_test_file" for c in corrections))

    def test_missing_py_suffix_is_corrected(self) -> None:
        spec, corrections = self._run({
            "sentinel_test_file": "tests/test_my_thing",
            "affected_files_new": [{"path": "app/my_thing.py", "purpose": "new"}],
        })
        self.assertTrue(spec["sentinel_test_file"].endswith(".py"))

    def test_empty_sentinel_file_derived_from_new_file(self) -> None:
        spec, corrections = self._run({
            "sentinel_test_file": "",
            "affected_files_new": [{"path": "frank_lloyd/cool_module.py", "purpose": "new"}],
        })
        self.assertEqual(spec["sentinel_test_file"], "tests/test_cool_module.py")
        self.assertTrue(any(c["field"] == "sentinel_test_file" for c in corrections))

    def test_empty_sentinel_no_new_files_uses_unknown(self) -> None:
        spec, corrections = self._run({
            "sentinel_test_file": "",
            "affected_files_new": [],
        })
        self.assertEqual(spec["sentinel_test_file"], "tests/test_unknown.py")

    def test_malformed_path_derived_from_new_file(self) -> None:
        spec, corrections = self._run({
            "sentinel_test_file": "not/a/valid/path.txt",
            "affected_files_new": [{"path": "app/routes/new_route.py", "purpose": "new"}],
        })
        self.assertEqual(spec["sentinel_test_file"], "tests/test_new_route.py")


# ── Rule 6: required fields ───────────────────────────────────────────────────

class TestRuleRequiredFields(unittest.TestCase):

    REQUIRED_SPEC = (
        "build_type", "risk_level", "architecture_layer",
        "blast_radius_failure_mode", "sentinel_test_file",
    )
    REQUIRED_PREFLIGHT = (
        "preflight_q1", "preflight_q2", "preflight_q3",
        "preflight_q5", "preflight_q6", "preflight_q7",
    )

    def test_missing_spec_field_set_to_unknown(self) -> None:
        for field in self.REQUIRED_SPEC:
            with self.subTest(field=field):
                base = _valid_spec()
                del base[field]
                spec, corrections = validate_and_correct(base, _req(), [])
                # Field should now be present (set to unknown or derived value)
                self.assertIn(field, spec)
                self.assertTrue(spec[field])  # non-empty

    def test_missing_preflight_field_set_to_placeholder(self) -> None:
        for field in self.REQUIRED_PREFLIGHT:
            with self.subTest(field=field):
                base = _valid_spec()
                del base[field]
                spec, corrections = validate_and_correct(base, _req(), [])
                self.assertIn(field, spec)
                preflight_corrections = [c for c in corrections if c["field"] == field]
                self.assertEqual(len(preflight_corrections), 1)

    def test_missing_preflight_gets_placeholder_text(self) -> None:
        base = _valid_spec()
        del base["preflight_q1"]
        spec, corrections = validate_and_correct(base, _req(), [])
        self.assertIn("Not answered", spec["preflight_q1"])

    def test_all_present_and_valid_no_corrections(self) -> None:
        spec, corrections = validate_and_correct(_valid_spec(), _req(), [])
        # A spec with all required fields and valid values should produce zero corrections
        self.assertEqual(corrections, [])


# ── Clean spec — zero corrections ─────────────────────────────────────────────

class TestCleanSpec(unittest.TestCase):

    def test_fully_valid_spec_produces_no_corrections(self) -> None:
        spec, corrections = validate_and_correct(_valid_spec(), _req(), [])
        self.assertEqual(corrections, [], f"Expected no corrections, got: {corrections}")

    def test_corrections_list_is_empty_list_not_none(self) -> None:
        _, corrections = validate_and_correct(_valid_spec(), _req(), [])
        self.assertIsInstance(corrections, list)

    def test_spec_returned_is_copy_not_same_object(self) -> None:
        original = _valid_spec()
        spec, _ = validate_and_correct(original, _req(), [])
        # Mutations to spec should not affect original
        self.assertIsNot(spec, original)


# ── Correction record structure ───────────────────────────────────────────────

class TestCorrectionRecords(unittest.TestCase):

    def test_correction_has_required_keys(self) -> None:
        # Force a correction by using an invalid build_type
        _, corrections = validate_and_correct(
            _valid_spec(build_type="new_route"), _req(), []
        )
        self.assertTrue(len(corrections) >= 1)
        for c in corrections:
            with self.subTest(correction=c):
                self.assertIn("field", c)
                self.assertIn("original", c)
                self.assertIn("corrected", c)
                self.assertIn("rule", c)

    def test_multiple_corrections_all_recorded(self) -> None:
        # Both build_type and architecture_layer invalid → at least 2 corrections
        spec, corrections = validate_and_correct(
            _valid_spec(build_type="bogus", architecture_layer="bogus"),
            _req(), []
        )
        fields = [c["field"] for c in corrections]
        self.assertIn("build_type", fields)
        self.assertIn("architecture_layer", fields)

    def test_rule_field_is_non_empty_string(self) -> None:
        _, corrections = validate_and_correct(
            _valid_spec(build_type="bogus"), _req(), []
        )
        for c in corrections:
            self.assertIsInstance(c["rule"], str)
            self.assertTrue(c["rule"])


if __name__ == "__main__":
    unittest.main()
