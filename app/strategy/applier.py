# app/strategy/applier.py
#
# Safe, auditable parameter applicator.
# This is the ONLY place that mutates strategy config at runtime.
# The operator always initiates this; it is never called automatically.
#
# Validates the proposal against type + bounds, captures a performance snapshot,
# applies via config.update(), and records the change in the changelog.

import json
import pathlib

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
    # Regime confidence filter
    "REGIME_CONF_LOOKBACK":          (10,  200,  int),
    "REGIME_CONF_GOOD_THRESHOLD":    (0.0, 1.0,  float),
    "REGIME_CONF_OK_THRESHOLD":      (0.0, 1.0,  float),
    "REGIME_CONF_REDUCED_SIZE_MULT": (0.0, 1.0,  float),
    # Risk management
    "STOP_LOSS_PCT":          (0.005, 0.1,  float),
    "TAKE_PROFIT_PCT":        (0.0,   0.5,  float),
    "MEAN_REV_STOP_VOL_MULT": (0.0,   10.0, float),
    "MIN_STOP_LOSS_PCT":      (0.001, 0.05, float),
    "POSITION_SIZE":      (0.01,  0.5,  float),
    "TRADE_COOLDOWN":     (0,     300,  int),
    # Stability patch
    "ATR_WINDOW":             (5,    100,  int),
    "STOP_ATR_MULT":          (0.0,  10.0, float),
    "RISK_PER_TRADE_PCT":     (0.0,  0.05, float),
    "MAX_TRADES_PER_SESSION": (0,    500,  int),
    # Entry quality confirmation
    "MR_CONFIRM_TICKS": (0,   20,  int),
    "MR_REBOUND_CAP":   (0.1, 3.0, float),
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


def promote_from_record(
    record_path: str,
    reason: str = "Operator applied from UI",
) -> dict:
    """
    Promote all candidate_config params from a validation record to the live baseline.

    Guards (raise ValueError):
      - record file must exist
      - record.decision must be "ACCEPTED"
      - candidate_config must be present and non-empty
      - at least one parameter value must actually differ from baseline
        (duplicate-apply protection: a second click returns 400 via this guard)

    Writes all params in one config.update() call and appends a single
    "candidate_promotion" changelog entry.

    Returns {applied, changed, experiment_name, record_path, new_config, changelog_entry}.
    """
    path = pathlib.Path(record_path)
    if not path.exists():
        raise ValueError(f"Validation record not found: {record_path}")

    try:
        record = json.loads(path.read_text())
    except Exception as exc:
        raise ValueError(f"Cannot read validation record: {exc}")

    decision = record.get("decision")
    if decision != "ACCEPTED":
        raise ValueError(
            f"Promotion blocked: decision is {decision!r}, expected ACCEPTED."
        )

    candidate_cfg = record.get("candidate_config")
    if not candidate_cfg:
        raise ValueError("Validation record has no candidate_config — nothing to promote.")

    current = config.get_config()
    changed = {
        k: {"old": current.get(k), "new": v}
        for k, v in candidate_cfg.items()
        if current.get(k) != v
    }
    if not changed:
        raise ValueError(
            "Duplicate apply: all candidate_config values already match the current baseline."
        )

    try:
        perf = compute_report()
    except Exception:
        perf = {}

    new_cfg = config.update(candidate_cfg)

    entry = changelog.record(
        parameter=f"promotion:{record.get('experiment_name', 'unknown')}",
        old_value=str({k: v["old"] for k, v in changed.items()}),
        new_value=str({k: v["new"] for k, v in changed.items()}),
        reason=reason,
        performance_snapshot=perf,
    )

    return {
        "applied":          True,
        "changed":          changed,
        "experiment_name":  record.get("experiment_name", "?"),
        "record_path":      str(record_path),
        "new_config":       new_cfg,
        "changelog_entry":  entry,
    }
