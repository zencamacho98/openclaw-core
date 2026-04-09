# app/strategy/applier.py
#
# Safe, auditable parameter applicator.
# This is the ONLY place that mutates strategy config at runtime.
# The operator always initiates this; it is never called automatically.
#
# Validates the proposal against type + bounds, captures a performance snapshot,
# applies via config.update(), and records the change in the changelog.

from app.strategy import config
from app.strategy import changelog
from app.report import compute_report

# (lo, hi, type) — inclusive bounds enforced before writing to config
BOUNDS: dict[str, tuple] = {
    # MA crossover
    "SHORT_WINDOW":       (2,    30,   int),
    "LONG_WINDOW":        (4,    60,   int),
    "MIN_SIGNAL_GAP":     (0.0,  50.0, float),
    # Regime detection
    "REGIME_WINDOW":      (5,    100,  int),
    "REGIME_THRESHOLD":   (0.1,  0.9,  float),
    # Mean reversion
    "MEAN_REV_WINDOW":        (5,    100,  int),
    "MEAN_REV_THRESHOLD":     (0.1,  5.0,  float),
    "MEAN_REV_EXIT_FRACTION":   (0.1,  1.0,  float),
    "MIN_VOLATILITY":           (0.0,  5.0,  float),
    "MEAN_REV_SIZE_MULTIPLIER": (0.0,  5.0,  float),
    "MAX_POSITION_SIZE":        (0.05, 1.0,  float),
    "MIN_ENTRY_DEPTH":          (0.0,  3.0,  float),
    "MAX_EFFICIENCY_RATIO":     (0.0,  1.0,  float),
    # Risk management
    "STOP_LOSS_PCT":          (0.005, 0.1,  float),
    "TAKE_PROFIT_PCT":        (0.0,   0.5,  float),
    "MEAN_REV_STOP_VOL_MULT": (0.0,   10.0, float),
    "MIN_STOP_LOSS_PCT":      (0.001, 0.05, float),
    "POSITION_SIZE":      (0.01,  0.5,  float),
    "TRADE_COOLDOWN":     (0,     300,  int),
}


def apply(proposal: dict) -> dict:
    """
    Apply a validated proposal and record it in the changelog.

    Expected proposal keys: parameter, proposed_value, reason
    Returns a result dict with the new config and changelog entry.
    Raises ValueError if the proposal is invalid or out of bounds.
    """
    parameter = proposal.get("parameter")
    new_value = proposal.get("proposed_value")
    reason = proposal.get("reason", "Operator-applied proposal")

    if not parameter:
        raise ValueError("Proposal must include 'parameter'.")
    if new_value is None:
        raise ValueError("Proposal must include 'proposed_value'.")
    if parameter not in BOUNDS:
        raise ValueError(
            f"Unknown parameter: {parameter!r}. Allowed: {sorted(BOUNDS)}"
        )

    lo, hi, typ = BOUNDS[parameter]

    try:
        new_value = typ(new_value)
    except (TypeError, ValueError):
        raise ValueError(
            f"{parameter} expects type {typ.__name__}, got {type(new_value).__name__}."
        )

    if not (lo <= new_value <= hi):
        raise ValueError(
            f"{parameter} must be between {lo} and {hi}, got {new_value!r}."
        )

    current_cfg = config.get_config()
    old_value = current_cfg[parameter]

    if new_value == old_value:
        raise ValueError(
            f"proposed_value ({new_value}) equals the current value — nothing to apply."
        )

    # Snapshot performance at the time of the change for before/after comparison
    try:
        perf = compute_report()
    except Exception:
        perf = {}

    new_cfg = config.update({parameter: new_value})

    entry = changelog.record(
        parameter=parameter,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        performance_snapshot=perf,
    )

    return {
        "applied":         True,
        "parameter":       parameter,
        "old_value":       old_value,
        "new_value":       new_value,
        "new_config":      new_cfg,
        "changelog_entry": entry,
    }
