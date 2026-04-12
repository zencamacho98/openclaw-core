# frank_lloyd/spec_validator.py
#
# Deterministic post-draft validation for Frank Lloyd Stage 1 spec packets.
#
# Called by spec_writer.py AFTER the LM returns a draft spec and BEFORE any
# files or log events are written. When LM output conflicts with doctrine,
# these rules win.
#
# Design principle: validation is additive. Every field that has a deterministic
# answer gets that answer. Fields that require genuine reasoning (and have no
# doctrine violation) are left as-is from the LM draft.
#
# Public API:
#   validate_and_correct(spec_data, req, offlimits_found)
#       -> (corrected_spec: dict, corrections: list[dict])
#
# Each correction record:
#   {"field": str, "original": any, "corrected": any, "rule": str}

from __future__ import annotations

from typing import Any

# ── Vocabulary constraints (from SPEC_SCHEMA.md) ──────────────────────────────

VALID_BUILD_TYPES = frozenset({
    "new_house",
    "new_service",
    "modification",
    "platform_capability",
    "clone",
    "docs_only",
})

# Aliases that the LM tends to use → canonical SPEC_SCHEMA term
_BUILD_TYPE_ALIASES: dict[str, str] = {
    "new_route":       "platform_capability",
    "new_module":      "platform_capability",
    "modify_existing": "modification",
}

VALID_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})

VALID_ARCH_LAYERS = frozenset({
    "experience",
    "executive_control",
    "specialist_house",
    "operating_services",
})

VALID_FAILURE_MODES = frozenset({"loud", "silent"})

# ── Risk escalation rules (from SPEC_SCHEMA.md §1, FRANK_LLOYD_SPEC.md §12) ───

# Any of these in the change set → risk_level MUST be "critical"
_CRITICAL_FILES = frozenset({
    "app/main.py",
    "scripts/ctl.sh",
    "app/loop.py",
    "app/routes/neighborhood.py",
})

# Any modification to an existing file (not in critical set) → at least "high"
# (Applies when affected_files_modified is non-empty)
_RISK_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# ── Required fields that must be present and non-empty ────────────────────────

_REQUIRED_SPEC_FIELDS = (
    "build_type",
    "risk_level",
    "architecture_layer",
    "blast_radius_failure_mode",
    "sentinel_test_file",
)

_REQUIRED_PREFLIGHT_FIELDS = (
    "preflight_q1",
    "preflight_q2",
    "preflight_q3",
    "preflight_q5",
    "preflight_q6",
    "preflight_q7",
)


# ── Public API ─────────────────────────────────────────────────────────────────

def validate_and_correct(
    spec_data: dict,
    req: dict,
    offlimits_found: list[str],
) -> tuple[dict, list[dict]]:
    """
    Apply deterministic validation rules to LM-generated spec data.

    Rules are applied in order. Each rule records a correction if it changed
    a field. Returns (corrected_spec_data, corrections).

    Corrections list is empty when no rules fired (clean spec).
    """
    spec = dict(spec_data)  # work on a copy — never mutate input
    corrections: list[dict] = []

    # Rule 1: build_type normalization and vocabulary check
    spec, corrections = _rule_build_type(spec, corrections)

    # Rule 2: architecture_layer vocabulary check
    spec, corrections = _rule_arch_layer(spec, corrections)

    # Rule 3: risk_level recomputation from file changes
    spec, corrections = _rule_risk_level(spec, corrections, offlimits_found)

    # Rule 4: blast_radius_failure_mode must be loud when critical files touched
    spec, corrections = _rule_failure_mode(spec, corrections, offlimits_found)

    # Rule 5: sentinel_test_file format check
    spec, corrections = _rule_sentinel_scope(spec, corrections)

    # Rule 6: required fields present
    spec, corrections = _rule_required_fields(spec, corrections)

    return spec, corrections


# ── Individual rules ──────────────────────────────────────────────────────────

def _rule_build_type(spec: dict, corrections: list) -> tuple[dict, list]:
    raw = spec.get("build_type", "")
    if not raw:
        return _apply(spec, corrections, "build_type", raw, "unknown",
                      "missing build_type; set to unknown")
    # Map LM aliases to canonical terms
    aliased = _BUILD_TYPE_ALIASES.get(raw)
    if aliased:
        return _apply(spec, corrections, "build_type", raw, aliased,
                      f"aliased build_type '{raw}' to canonical '{aliased}'")
    if raw not in VALID_BUILD_TYPES:
        return _apply(spec, corrections, "build_type", raw, "unknown",
                      f"unrecognised build_type '{raw}'; set to unknown")
    return spec, corrections


def _rule_arch_layer(spec: dict, corrections: list) -> tuple[dict, list]:
    raw = spec.get("architecture_layer", "")
    if not raw or raw not in VALID_ARCH_LAYERS:
        return _apply(spec, corrections, "architecture_layer", raw, "unknown",
                      f"'{raw}' is not a valid architecture layer; set to unknown")
    return spec, corrections


def _rule_risk_level(
    spec: dict,
    corrections: list,
    offlimits_found: list[str],
) -> tuple[dict, list]:
    """
    Risk level is computed deterministically from the file change set.
    Per SPEC_SCHEMA.md §1:
      critical — any change to a critical/off-limits file
      high     — any modification to an existing file (non-critical)
      medium   — new file requiring integration (registration in main.py etc.)
      low      — new isolated file with no integration

    The deterministic floor is computed and used if it EXCEEDS the LM's value.
    Off-limits files always force critical regardless.
    """
    modified = [
        f.get("path", "")
        for f in (spec.get("affected_files_modified") or [])
        if f.get("path")
    ]
    new_files = [
        f.get("path", "")
        for f in (spec.get("affected_files_new") or [])
        if f.get("path")
    ]

    # Determine deterministic floor
    all_modified = set(modified) | set(offlimits_found)

    if any(f in _CRITICAL_FILES or f in offlimits_found for f in all_modified):
        floor = "critical"
        reason = (
            "critical file in change set: "
            + ", ".join(sorted(f for f in all_modified if f in _CRITICAL_FILES or f in offlimits_found))
        )
    elif modified:
        # Any modification to any existing file → at least high
        floor = "high"
        reason = f"modified existing file(s): {', '.join(sorted(modified))}"
    elif new_files:
        # New files that require main.py integration → medium; otherwise low
        needs_integration = any(
            "main.py" in str(spec.get("affected_files_modified", [])) or
            _touches_integration(nf, spec)
            for nf in new_files
        )
        floor = "medium" if needs_integration else "low"
        reason = f"new file(s) only; integration={'yes' if needs_integration else 'no'}"
    else:
        floor = "low"
        reason = "no file changes detected in spec"

    current = spec.get("risk_level", "")
    if current not in VALID_RISK_LEVELS:
        return _apply(spec, corrections, "risk_level", current, floor,
                      f"invalid risk_level '{current}'; using deterministic floor ({reason})")

    # Deterministic floor wins if it is HIGHER than LM's value
    if _RISK_RANK.get(floor, 0) > _RISK_RANK.get(current, 0):
        return _apply(spec, corrections, "risk_level", current, floor,
                      f"LM assessed '{current}' but deterministic floor is '{floor}' ({reason})")

    return spec, corrections


def _rule_failure_mode(
    spec: dict,
    corrections: list,
    offlimits_found: list[str],
) -> tuple[dict, list]:
    """
    blast_radius_failure_mode must be 'loud' when critical files are touched.
    Touching off-limits / runtime infrastructure cannot be a silent failure.
    Also validates that the value is in the allowed set.
    """
    raw = spec.get("blast_radius_failure_mode", "")
    modified = [
        f.get("path", "")
        for f in (spec.get("affected_files_modified") or [])
        if f.get("path")
    ]
    all_modified = set(modified) | set(offlimits_found)

    if any(f in _CRITICAL_FILES for f in all_modified):
        if raw != "loud":
            return _apply(spec, corrections, "blast_radius_failure_mode", raw, "loud",
                          "critical file touched; failure mode must be loud")
        return spec, corrections

    if raw not in VALID_FAILURE_MODES:
        return _apply(spec, corrections, "blast_radius_failure_mode", raw, "loud",
                      f"'{raw}' is not a valid failure mode; defaulting to loud")

    return spec, corrections


def _rule_sentinel_scope(spec: dict, corrections: list) -> tuple[dict, list]:
    """
    sentinel_test_file must start with 'tests/' and end with '.py'.
    If malformed, generate a best-effort name from the first new file.
    """
    raw = spec.get("sentinel_test_file", "")
    if not raw or not raw.startswith("tests/") or not raw.endswith(".py"):
        # Try to derive from first new file
        derived = _derive_test_file(spec)
        return _apply(spec, corrections, "sentinel_test_file", raw, derived,
                      f"'{raw}' is not a valid tests/*.py path; derived '{derived}'")
    return spec, corrections


def _rule_required_fields(spec: dict, corrections: list) -> tuple[dict, list]:
    """
    Ensure required spec fields are present and non-empty.
    Preflight answer fields get a placeholder if missing (records an uncertainty).
    """
    for field in _REQUIRED_SPEC_FIELDS:
        val = spec.get(field)
        if not val:
            spec, corrections = _apply(spec, corrections, field, val, "unknown",
                                       f"required field '{field}' was missing or empty")

    for field in _REQUIRED_PREFLIGHT_FIELDS:
        val = spec.get(field)
        if not val:
            spec, corrections = _apply(spec, corrections, field, val,
                                       "[Not answered — see spec.yaml for context]",
                                       f"preflight field '{field}' was missing")

    return spec, corrections


# ── Internal helpers ──────────────────────────────────────────────────────────

def _apply(
    spec: dict,
    corrections: list,
    field: str,
    original: Any,
    corrected: Any,
    rule: str,
) -> tuple[dict, list]:
    spec = dict(spec)
    spec[field] = corrected
    corrections = list(corrections)
    corrections.append({
        "field":     field,
        "original":  original,
        "corrected": corrected,
        "rule":      rule,
    })
    return spec, corrections


def _derive_test_file(spec: dict) -> str:
    """Generate a best-effort test file path from the first new file."""
    new_files = spec.get("affected_files_new") or []
    if new_files:
        first = new_files[0].get("path", "")
        if first:
            stem = first.split("/")[-1].replace(".py", "")
            return f"tests/test_{stem}.py"
    return "tests/test_unknown.py"


def _touches_integration(new_file_path: str, spec: dict) -> bool:
    """
    Return True if any modified file (e.g. main.py) suggests this new file
    needs integration registration.
    """
    modified = [
        f.get("path", "")
        for f in (spec.get("affected_files_modified") or [])
    ]
    # A new route/service file that requires main.py registration is medium risk
    return any("main.py" in m for m in modified)
