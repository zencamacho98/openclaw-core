# research/approval_policy.py
#
# Approval policy for the continuous learning supervisor.
# Pure functions — no I/O, no imports from app/, ui/, or peter/.
#
# V1 auto-apply rule (ALL five must hold):
#   1. tier == "strong"              (score ≥ 80, from research/policy.py SCORING["tier_strong"])
#   2. n_changed_params <= 2         (small scope: at most 2 params changed vs baseline)
#   3. pnl_delta > 0                 (net improvement)
#   4. worst_pnl_delta >= -0.001     (worst-case drawdown < 0.1%)
#   5. quality_labels == []          (no quality concerns)
#      AND flags == []               (no flags)
#
# Fail-safe contract:
#   If any required field is missing or has an unexpected type, the candidate
#   is NOT eligible for auto-apply. Default is review_required, never auto_apply.
#
# Required fields for evaluation:
#   tier, score, n_changed_params, pnl_delta, worst_pnl_delta, quality_labels, flags
#
# Public API:
#   auto_apply_eligible(candidate)                      → (bool, list[str])
#   classify_candidate(candidate)                       → "auto_apply" | "review_required" | "skip"
#   build_risk_summary(candidate, eligible, reasons)    → str
#   should_continue_loop(supervisor_state, agent_status) → (bool, str)

from __future__ import annotations

# Fields required to be present and correctly typed for auto-apply evaluation.
# Absence of ANY of these → fail-safe return of (False, [reason]).
_REQUIRED_FIELDS: tuple[str, ...] = (
    "tier",
    "score",
    "n_changed_params",
    "pnl_delta",
    "worst_pnl_delta",
    "quality_labels",
    "flags",
)

# Tiers too weak to merit queuing — skip silently.
_SKIP_TIERS = frozenset({"weak", "rejected"})

# Agent statuses that require disabling the loop (hard stop from the engine).
_HARD_STOP_STATUSES = frozenset({"stopped_by_guardrail", "paused_by_budget"})

# V1 threshold constants (mirrors research/policy.py SCORING["tier_strong"])
_WORST_PNL_THRESHOLD   = -0.001   # worst-case drawdown must be >= this
_MAX_CHANGED_PARAMS    = 2        # at most this many params may differ from baseline


def auto_apply_eligible(candidate: dict) -> tuple[bool, list[str]]:
    """
    Check whether a candidate meets all V1 auto-apply criteria.

    Returns:
        eligible     — True only if ALL five criteria pass AND all fields are valid.
        fail_reasons — List of human-readable strings for each failed criterion.
                       Empty when eligible=True.

    Fail-safe contract: missing or malformed fields yield eligible=False immediately.
    The caller must treat this function as the sole gating authority for auto-apply.
    """
    if not isinstance(candidate, dict):
        return False, ["candidate is not a dict — cannot evaluate"]

    # ── Required field presence ───────────────────────────────────────────────
    for field_name in _REQUIRED_FIELDS:
        if field_name not in candidate:
            return False, [f"missing required field: {field_name!r}"]

    # ── Type and parseability ─────────────────────────────────────────────────
    tier = candidate["tier"]
    if not isinstance(tier, str) or not tier:
        return False, ["'tier' must be a non-empty string"]

    try:
        score = float(candidate["score"])
    except (TypeError, ValueError):
        return False, ["'score' is not numeric"]

    try:
        n_changed = int(candidate["n_changed_params"])
    except (TypeError, ValueError):
        return False, ["'n_changed_params' is not an integer"]
    if n_changed < 0:
        return False, [f"'n_changed_params' is negative ({n_changed})"]

    try:
        pnl = float(candidate["pnl_delta"])
    except (TypeError, ValueError):
        return False, ["'pnl_delta' is not numeric"]

    try:
        worst_pnl = float(candidate["worst_pnl_delta"])
    except (TypeError, ValueError):
        return False, ["'worst_pnl_delta' is not numeric"]

    quality_labels = candidate["quality_labels"]
    if not isinstance(quality_labels, list):
        return False, ["'quality_labels' is not a list"]

    flags = candidate["flags"]
    if not isinstance(flags, list):
        return False, ["'flags' is not a list"]

    # ── Policy criteria — all five must pass ──────────────────────────────────
    fail_reasons: list[str] = []

    # 1. Must be strong tier
    if tier != "strong":
        fail_reasons.append(f"tier is {tier!r} (required: strong)")

    # 2. At most _MAX_CHANGED_PARAMS parameters changed
    if n_changed > _MAX_CHANGED_PARAMS:
        fail_reasons.append(
            f"n_changed_params={n_changed} exceeds limit of {_MAX_CHANGED_PARAMS} "
            f"(multi-parameter change requires review)"
        )

    # 3. Net improvement
    if pnl <= 0:
        fail_reasons.append(f"pnl_delta={pnl:.4f} ≤ 0 (no net improvement)")

    # 4. Worst-case drawdown within tolerance
    if worst_pnl < _WORST_PNL_THRESHOLD:
        fail_reasons.append(
            f"worst_pnl_delta={worst_pnl:.4f} < {_WORST_PNL_THRESHOLD} "
            f"(potential downside regression)"
        )

    # 5. No quality concerns or flags
    if quality_labels:
        fail_reasons.append(
            f"{len(quality_labels)} quality label(s) present "
            f"({', '.join(str(x) for x in quality_labels[:3])})"
        )
    if flags:
        fail_reasons.append(
            f"{len(flags)} flag(s) present "
            f"({', '.join(str(x) for x in flags[:3])})"
        )

    return len(fail_reasons) == 0, fail_reasons


def classify_candidate(candidate: dict) -> str:
    """
    Classify a candidate for the supervisor decision.

    Returns one of:
        "auto_apply"      — meets all V1 criteria; apply without human review
        "review_required" — queue for operator approval; learning continues
        "skip"            — tier is weak or rejected; not worth queuing

    Decision tree (order matters):
        1. If tier is weak or rejected → skip
        2. If auto_apply_eligible → auto_apply
        3. Otherwise → review_required

    Malformed data on a non-skip tier always yields review_required (fail-safe).
    """
    if not isinstance(candidate, dict):
        return "review_required"

    tier = candidate.get("tier", "")
    if isinstance(tier, str) and tier in _SKIP_TIERS:
        return "skip"

    eligible, _ = auto_apply_eligible(candidate)
    if eligible:
        return "auto_apply"

    return "review_required"


def build_risk_summary(
    candidate: dict,
    eligible: bool,
    fail_reasons: list[str],
) -> str:
    """
    Build a short deterministic explanation of the auto-apply eligibility decision.

    Used to populate the queue entry's risk_summary field for operator display.
    """
    n       = candidate.get("n_changed_params", "?")
    pnl     = candidate.get("pnl_delta", "?")
    w_pnl   = candidate.get("worst_pnl_delta", "?")
    tier    = candidate.get("tier", "?")

    if eligible:
        return (
            f"{n} param(s) changed; pnl_delta={pnl}; worst_pnl_delta={w_pnl}; "
            "all criteria met — auto-apply eligible."
        )

    if not fail_reasons:
        return f"Tier={tier}; auto-apply not eligible (reason unknown)."

    reasons_str = "; ".join(fail_reasons)
    return f"Tier={tier}; auto-apply blocked: {reasons_str}."


def should_continue_loop(
    supervisor_state: dict,
    agent_status: str,
) -> tuple[bool, str]:
    """
    Decide whether the continuous learning loop should proceed to the next cycle.

    Returns (should_continue: bool, reason: str).

    Returns False when:
    - supervisor_state["stop_requested"] is True
    - agent_status is a hard-stop status (guardrail / budget)
    """
    if not isinstance(supervisor_state, dict):
        return False, "supervisor_state is malformed"

    if supervisor_state.get("stop_requested"):
        return False, "stop_requested"

    if agent_status in _HARD_STOP_STATUSES:
        return False, f"agent_hard_stop:{agent_status}"

    return True, "ok"
