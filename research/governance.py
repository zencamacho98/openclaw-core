# research/governance.py
#
# Governance and safety enforcement for the autonomous research loop.
#
# All policy constants are sourced from research/policy.py — the single
# human-editable config. This module provides the enforcement layer:
# validation logic, public constants derived from policy, and the hard gate
# function used before any experiment is allowed to run.
#
# To change approved classes, parameter ranges, or batch limits:
#   → Edit research/policy.py, not this file.

from __future__ import annotations

from typing import Any

from .policy import BATCH, EXPERIMENT_CLASSES

# ── Public constants (derived from policy) ────────────────────────────────────
# These are the authoritative values used throughout the research/ package.
# Import them from here, not from policy directly, to keep a single import
# point for governance concerns.

APPROVED_EXPERIMENT_CLASSES: frozenset[str] = frozenset(EXPERIMENT_CLASSES.keys())

# Per-class approved parameters → tuple(min, max) for fast range checks
APPROVED_PARAMS: dict[str, dict[str, tuple[float, float]]] = {
    cls: {param: (lo, hi) for param, (lo, hi) in bounds.items()}
    for cls, bounds in EXPERIMENT_CLASSES.items()
}

MAX_EXPERIMENTS_PER_BATCH: int = int(BATCH["max_experiments"])
MIN_EXPERIMENTS_PER_BATCH: int = int(BATCH["min_experiments"])
MAX_PARAMS_PER_EXPERIMENT: int = int(BATCH["max_params_per_experiment"])
MAX_SEEDS:                  int = int(BATCH["max_seeds"])


# ── Manifest validation ───────────────────────────────────────────────────────

def validate_manifest(manifest: Any) -> list[str]:
    """
    Validate an ExperimentManifest against all governance rules.

    Returns a list of human-readable violation strings.
    An empty list means the manifest is valid and safe to run.
    Callers must treat any non-empty return as a hard block.
    """
    violations: list[str] = []

    # Experiment class must be approved
    if manifest.experiment_class not in APPROVED_EXPERIMENT_CLASSES:
        violations.append(
            f"experiment_class '{manifest.experiment_class}' is not approved. "
            f"Approved: {sorted(APPROVED_EXPERIMENT_CLASSES)}"
        )
        # Can't validate params without a known class
        return violations

    allowed = APPROVED_PARAMS[manifest.experiment_class]

    # Must have at least one mutation
    if not manifest.mutated_params:
        violations.append("mutated_params is empty — nothing to test")

    # Param count cap
    if len(manifest.mutated_params) > MAX_PARAMS_PER_EXPERIMENT:
        violations.append(
            f"Too many mutated params ({len(manifest.mutated_params)}); "
            f"max is {MAX_PARAMS_PER_EXPERIMENT} "
            f"(see BATCH.max_params_per_experiment in policy.py)"
        )

    # Each param must be approved and within range
    for param, value in manifest.mutated_params.items():
        if param not in allowed:
            violations.append(
                f"Param '{param}' is not approved for class "
                f"'{manifest.experiment_class}'. "
                f"Approved params: {sorted(allowed)}"
            )
            continue
        lo, hi = allowed[param]
        try:
            fval = float(value)
        except (TypeError, ValueError):
            violations.append(f"Param '{param}' has non-numeric value: {value!r}")
            continue
        if not (lo <= fval <= hi):
            violations.append(
                f"Param '{param}'={value} is outside approved range "
                f"[{lo}, {hi}] (see EXPERIMENT_CLASSES in policy.py)"
            )

    # Hypothesis must be a non-empty string
    if not manifest.hypothesis or not str(manifest.hypothesis).strip():
        violations.append("hypothesis is required and cannot be empty")

    # Seed constraints
    if not manifest.seed_set:
        violations.append("seed_set is required and cannot be empty")
    elif len(manifest.seed_set) > MAX_SEEDS:
        violations.append(
            f"seed_set has {len(manifest.seed_set)} seeds; "
            f"max is {MAX_SEEDS} (see BATCH.max_seeds in policy.py)"
        )

    return violations


def enforce(manifest: Any) -> None:
    """
    Hard gate: validate and raise ValueError if any violations are found.

    Call this before running any experiment. Violations are listed explicitly
    so the caller knows exactly what to fix.
    """
    violations = validate_manifest(manifest)
    if violations:
        bullet = "\n  - ".join(violations)
        raise ValueError(
            f"Governance violation(s) for '{manifest.experiment_id}':\n"
            f"  - {bullet}\n"
            f"  → Edit research/policy.py to adjust approved ranges."
        )
