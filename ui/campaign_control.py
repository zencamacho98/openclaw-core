# ui/campaign_control.py
#
# UI-layer campaign control helpers.
# No Streamlit imports — returns plain Python dicts, safe to unit-test.
#
# Core campaign logic (start/resume/stop/list/load) lives in
# research/campaign_service.py so that app/supervisor.py can share it
# without importing from ui/.  This module re-exports those functions and
# adds UI-specific helpers (form validation, promotion command, brief paths).
#
# Public API:
#   validate_campaign_form(...)          → (ok, errors, clamped)
#   start_campaign(...)                  → {ok, message, pid}         [re-export]
#   resume_campaign(campaign_id)         → {ok, message, pid}         [re-export]
#   request_stop()                       → {ok, message}              [re-export]
#   cancel_stop_signal()                 → {ok, message}              [re-export]
#   stop_signal_pending()                → bool                       [re-export]
#   check_lock()                         → dict | None                [re-export]
#   list_campaigns()                     → list[dict]                 [re-export]
#   list_resumable_campaigns()           → list[dict]                 [re-export]
#   load_campaign_state(campaign_id)     → dict | None                [re-export]
#   get_best_candidate(campaign_id)      → dict | None                [re-export]
#   get_promotion_command(campaign_id)   → str | None
#   get_campaign_brief_paths(campaign_id) → dict

from __future__ import annotations

from typing import Any

# ── Re-export shared service functions ────────────────────────────────────────
from research.campaign_service import (   # noqa: F401  (re-exported for dashboard)
    start_campaign,
    resume_campaign,
    request_stop,
    cancel_stop_signal,
    stop_signal_pending,
    check_lock,
    list_campaigns,
    list_resumable_campaigns,
    load_campaign_state,
    get_best_candidate,
)

import pathlib

_ROOT  = pathlib.Path(__file__).resolve().parent.parent
_CAMPS = _ROOT / "data" / "campaigns"

# Hard caps — for form validation display only (enforcement is in campaign_service)
_CAP_SESSIONS      = 6
_DEFAULT_SESSIONS  = 3
_CAP_BATCHES       = 4
_DEFAULT_BATCHES   = 3
_MIN_EXP_BATCH     = 3
_CAP_EXP_BATCH     = 5
_DEFAULT_EXP       = 3
_CAP_EXP_TOTAL     = 100
_DEFAULT_EXP_TOTAL = 60
_GOAL_MIN_LEN      = 5


# ── Form validation ───────────────────────────────────────────────────────────

def validate_campaign_form(
    goal:            str,
    max_sessions:    int,
    max_batches:     int,
    experiments:     int,
    max_experiments: int,
    budget_usd:      float,
) -> tuple[bool, list[str], dict[str, Any]]:
    """
    Validate campaign form inputs against policy hard caps.

    Returns:
        ok       — True if all inputs are valid
        errors   — list of human-readable error strings (empty when ok)
        clamped  — inputs clamped to valid ranges (for display / safe use even on error)
    """
    errors: list[str] = []

    goal_stripped = goal.strip()
    if len(goal_stripped) < _GOAL_MIN_LEN:
        errors.append(
            f"Goal must be at least {_GOAL_MIN_LEN} characters "
            f"(got {len(goal_stripped)})."
        )

    if not (1 <= max_sessions <= _CAP_SESSIONS):
        errors.append(f"Max sessions must be 1–{_CAP_SESSIONS} (got {max_sessions}).")

    if not (1 <= max_batches <= _CAP_BATCHES):
        errors.append(f"Max batches per session must be 1–{_CAP_BATCHES} (got {max_batches}).")

    if not (_MIN_EXP_BATCH <= experiments <= _CAP_EXP_BATCH):
        errors.append(
            f"Experiments per batch must be {_MIN_EXP_BATCH}–{_CAP_EXP_BATCH} "
            f"(got {experiments})."
        )

    if not (1 <= max_experiments <= _CAP_EXP_TOTAL):
        errors.append(
            f"Experiment budget must be 1–{_CAP_EXP_TOTAL} "
            f"(got {max_experiments})."
        )

    if budget_usd < 0:
        errors.append(f"Budget must be ≥ 0 (0 = no limit; got {budget_usd:.2f}).")

    clamped = {
        "goal":            goal_stripped,
        "max_sessions":    max(1, min(max_sessions,    _CAP_SESSIONS)),
        "max_batches":     max(1, min(max_batches,     _CAP_BATCHES)),
        "experiments":     max(_MIN_EXP_BATCH, min(experiments,     _CAP_EXP_BATCH)),
        "max_experiments": max(1, min(max_experiments, _CAP_EXP_TOTAL)),
        "budget_usd":      max(0.0, budget_usd),
    }

    return len(errors) == 0, errors, clamped


# ── UI-only helpers ───────────────────────────────────────────────────────────

def get_promotion_command(campaign_id: str) -> "Optional[str]":
    """
    Return the exact promotion command string, or None if no promotable record.
    Always requires manual operator confirmation — never auto-executes.
    """
    state = load_campaign_state(campaign_id)
    if not state:
        return None
    rec = (state.get("artifacts") or {}).get("best_validation_record")
    if not rec:
        return None
    return f"python scripts/promote_candidate.py --record {rec}"


def get_campaign_brief_paths(campaign_id: str) -> dict[str, Optional[str]]:
    """Return paths to campaign brief files (JSON and markdown)."""
    state = load_campaign_state(campaign_id)
    if not state:
        return {"json": None, "md": None}
    art = state.get("artifacts") or {}
    return {
        "json": art.get("campaign_brief_json"),
        "md":   art.get("campaign_brief_md"),
    }
