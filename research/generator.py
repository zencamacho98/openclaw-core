# research/generator.py
#
# Bounded candidate generator.
#
# Produces 3–5 ExperimentManifest objects per batch.
# Experiments are tightly scoped to three classes:
#   - profit_taking   : take-profit level, exit fraction
#   - entry_quality   : ER gate, entry threshold, cooldown
#   - loss_structure  : stop size, ATR-based stop, stop floor
#
# Each candidate mutates 1–2 parameters and carries an explicit hypothesis.
# All candidates are validated against governance rules before being returned.
# The generator will raise ValueError if it cannot produce a valid manifest.
#
# Candidate templates are intentionally hand-curated, not auto-generated.
# This avoids combinatorial explosion and keeps experiments interpretable.

from __future__ import annotations

from typing import Any

from .governance import (
    APPROVED_PARAMS,
    MAX_EXPERIMENTS_PER_BATCH,
    MIN_EXPERIMENTS_PER_BATCH,
    enforce,
)
from .manifest import ExperimentManifest, make_batch_id, make_experiment_id
from .policy import SIMULATION as _SIM

# ── Candidate templates ───────────────────────────────────────────────────────
# Each entry: (param_overrides_dict, hypothesis_string)
# Templates are ordered from most targeted to most exploratory.
# Live baseline: MAX_EFFICIENCY_RATIO=0.4, TRADE_COOLDOWN=5, STOP_LOSS_PCT=0.015,
#                TAKE_PROFIT_PCT=0.04, MEAN_REV_EXIT_FRACTION=1.0, MEAN_REV_THRESHOLD=1.0

_PROFIT_TAKING_TEMPLATES: list[tuple[dict[str, Any], str]] = [
    (
        {"TAKE_PROFIT_PCT": 0.03},
        "Tighten take-profit from 4% to 3% to capture mean-reversion completions "
        "before price drifts back — tests whether faster exits improve win rate.",
    ),
    (
        {"TAKE_PROFIT_PCT": 0.05},
        "Widen take-profit to 5% to allow more upside on strong reversions — tests "
        "whether holding longer improves average winner without hurting win rate.",
    ),
    (
        {"MEAN_REV_EXIT_FRACTION": 0.70},
        "Exit at 70% of the way back to mean instead of full mean — tests whether "
        "partial exits reduce whipsaw and improve consistency.",
    ),
    (
        {"MEAN_REV_EXIT_FRACTION": 1.30},
        "Exit slightly past the mean (130%) to capture overshoot on strong reversions — "
        "tests whether overextension adds value or increases risk.",
    ),
    (
        {"TAKE_PROFIT_PCT": 0.03, "MEAN_REV_EXIT_FRACTION": 0.80},
        "Combine a tighter take-profit with an 80% partial exit target — tests whether "
        "a more conservative exit structure improves win rate on weak reversions.",
    ),
]

_ENTRY_QUALITY_TEMPLATES: list[tuple[dict[str, Any], str]] = [
    (
        {"MAX_EFFICIENCY_RATIO": 0.35},
        "Tighten ER gate from 0.4 to 0.35 to further exclude borderline trending "
        "regimes — tests whether stricter regime filtering improves entry quality.",
    ),
    (
        {"MAX_EFFICIENCY_RATIO": 0.45},
        "Slightly relax ER gate to 0.45 to allow more ranging-regime entries — "
        "tests the trade-off between entry frequency and regime purity.",
    ),
    (
        {"MEAN_REV_THRESHOLD": 1.20},
        "Raise MR entry threshold to 1.2 std devs to require deeper overshoots "
        "before entering — tests whether higher bars produce better-timed entries.",
    ),
    (
        {"MEAN_REV_THRESHOLD": 0.80},
        "Lower entry threshold to 0.8 std devs to capture shallower mean-reversion "
        "opportunities — tests whether earlier entries improve trade count and PnL.",
    ),
    (
        {"TRADE_COOLDOWN": 8},
        "Increase cooldown from 5 to 8 ticks to reduce rapid re-entry after exits — "
        "tests whether longer recovery periods reduce churn without hurting PnL.",
    ),
    (
        {"TRADE_COOLDOWN": 3},
        "Reduce cooldown from 5 to 3 ticks to capture more opportunities in fast "
        "ranging markets — tests whether higher frequency helps or hurts quality.",
    ),
    (
        {"MAX_EFFICIENCY_RATIO": 0.35, "TRADE_COOLDOWN": 8},
        "Combine tighter ER gate with longer cooldown — tests whether both "
        "quality filters together improve the risk-adjusted return profile.",
    ),
]

_LOSS_STRUCTURE_TEMPLATES: list[tuple[dict[str, Any], str]] = [
    (
        {"STOP_LOSS_PCT": 0.010},
        "Tighten stop from 1.5% to 1.0% to cut losses faster on bad entries — "
        "tests whether tighter stops reduce worst-case drawdowns.",
    ),
    (
        {"STOP_LOSS_PCT": 0.020},
        "Widen stop from 1.5% to 2.0% to give trades more room before stopping out — "
        "tests whether fewer premature stops improve overall win rate.",
    ),
    (
        {"STOP_ATR_MULT": 1.50},
        "Switch to volatility-aware stop at 1.5× ATR — tests whether scaling stop "
        "distance with realized volatility reduces stop-outs in noisy periods.",
    ),
    (
        {"STOP_ATR_MULT": 2.00},
        "Use wider ATR-based stop at 2.0× ATR — tests a more permissive volatility-"
        "scaled stop to reduce premature exits in high-volatility regimes.",
    ),
    (
        {"STOP_ATR_MULT": 1.50, "MIN_STOP_LOSS_PCT": 0.008},
        "ATR-based stop (1.5×) with a floor at 0.8% — tests whether a volatility-"
        "scaled stop with a minimum prevents dangerously tight stops in quiet markets.",
    ),
]

_TEMPLATES_BY_CLASS: dict[str, list[tuple[dict[str, Any], str]]] = {
    "profit_taking":  _PROFIT_TAKING_TEMPLATES,
    "entry_quality":  _ENTRY_QUALITY_TEMPLATES,
    "loss_structure": _LOSS_STRUCTURE_TEMPLATES,
}

# Sequence of experiment classes across a 5-slot batch.
# entry_quality first (regime gating affects everything downstream),
# loss_structure second (core risk management),
# profit_taking third,
# then continue alternating for slots 4–5.
_BATCH_CLASS_SEQUENCE: list[str] = [
    "entry_quality",
    "loss_structure",
    "profit_taking",
    "entry_quality",
    "profit_taking",
]


# ── Public API ────────────────────────────────────────────────────────────────

def generate_batch(
    batch_id: str | None = None,
    n: int = MAX_EXPERIMENTS_PER_BATCH,
    seeds: list[int] | None = None,
    tick_sizes: list[int] | None = None,
    focus_classes: list[str] | None = None,
) -> list[ExperimentManifest]:
    """
    Generate a bounded batch of experiment manifests.

    Args:
        batch_id:      Caller-supplied ID; auto-generated if None.
        n:             Target batch size (clamped to [MIN, MAX]).
        seeds:         Seed list for experiments; defaults to standard 7-seed set.
        tick_sizes:    Tick lengths; defaults to [2000, 5000].
        focus_classes: If provided, restrict the batch to these experiment classes,
                       cycling through them to fill the n slots. Useful for targeted
                       session batches. Must be a subset of approved classes.
                       Example: ["entry_quality"] → all n experiments test entry_quality.

    Returns:
        List of validated ExperimentManifest objects, ready to run.

    Raises:
        ValueError: If focus_classes contains unapproved classes, or if
                    a generated manifest fails governance validation.
    """
    if batch_id is None:
        batch_id = make_batch_id()

    if seeds is None:
        seeds = list(_SIM["default_seeds"])

    if tick_sizes is None:
        tick_sizes = list(_SIM["default_tick_sizes"])

    n = max(MIN_EXPERIMENTS_PER_BATCH, min(n, MAX_EXPERIMENTS_PER_BATCH))

    # Build effective class sequence for this batch
    if focus_classes:
        invalid = [c for c in focus_classes if c not in APPROVED_PARAMS]
        if invalid:
            raise ValueError(
                f"focus_classes contains unapproved classes: {invalid}. "
                f"Approved: {sorted(APPROVED_PARAMS)}"
            )
        # Cycle through focus_classes to fill n slots
        effective_sequence = [
            focus_classes[i % len(focus_classes)]
            for i in range(n)
        ]
    else:
        effective_sequence = _BATCH_CLASS_SEQUENCE[:n]

    manifests: list[ExperimentManifest] = []
    class_template_index: dict[str, int] = {cls: 0 for cls in _TEMPLATES_BY_CLASS}

    for slot_index, experiment_class in enumerate(effective_sequence):
        templates = _TEMPLATES_BY_CLASS[experiment_class]
        template_idx = class_template_index[experiment_class]

        if template_idx >= len(templates):
            # Exhausted templates for this class; skip silently
            continue

        params_override, hypothesis = templates[template_idx]
        class_template_index[experiment_class] += 1

        experiment_id = make_experiment_id(batch_id, slot_index + 1)

        # Build approved_ranges from governance for auditability
        allowed = APPROVED_PARAMS[experiment_class]
        approved_ranges = {
            param: list(allowed[param])
            for param in params_override
            if param in allowed
        }

        manifest = ExperimentManifest(
            experiment_id=experiment_id,
            batch_id=batch_id,
            experiment_class=experiment_class,
            hypothesis=hypothesis,
            mutated_params=dict(params_override),
            approved_ranges=approved_ranges,
            seed_set=list(seeds),
            tick_sizes=list(tick_sizes),
        )

        # Hard gate: any governance violation aborts generation
        enforce(manifest)

        manifests.append(manifest)

    if len(manifests) < MIN_EXPERIMENTS_PER_BATCH:
        raise RuntimeError(
            f"Generator produced only {len(manifests)} manifests; "
            f"minimum is {MIN_EXPERIMENTS_PER_BATCH}. "
            "Check template counts in research/generator.py."
        )

    return manifests
